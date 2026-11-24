# @owns 1 モール・複数キーワード検索の実行制御（ページング・重複排除・統計・流量制限・流量超過の打ち切り）
"""検索オーケストレーション。モール固有の知識は持たない（Adapter の属性〔max_page・page_size・stop_kinds…〕を引くだけ）。
モールをまたぐ束ね（並走・統合）は malls.py。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .adapters.base import AdapterError, adapter_attr
from .inputs import check_page_range
from .models import KeywordStat, MallStat, Offer, SearchStats

JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class Limits:
    max_keywords: int = 5          # 検索語の数。楽天由来ではなくこのアプリの既存仕様（SPEC §6・inputs.MAX_KEYWORDS と同じ値）
    min_interval_sec: float = 1.0  # 出典: 楽天ウェブサービスの 1 秒 1 リクエスト。より遅いモール（Yahoo 2.2 秒）は malls.py がモール別に上げる
    # 1 回の呼び出しの取得時間の上限。出典: Cloudflare の既定プロキシ読み取りタイムアウト 100 秒（超えると 524 で全損）に、
    # 応答の生成・送信の余裕 20 秒を見込んだ 80 秒。超えそうなら取れた分で止めて next_page を返す
    time_budget_sec: float = 80.0


def _validate(keywords, max_pages: int | None, start_page: int, hits: int, limits: Limits, max_hits: int) -> None:
    if not keywords:
        raise ValueError("keywords must not be empty")
    if len(keywords) > limits.max_keywords:
        raise ValueError(f"too many keywords: {len(keywords)} > {limits.max_keywords}")
    check_page_range(start_page, max_pages)     # 1〜100 の整数と start_page+pages-1 ≤ 100（楽天の天井。他のモールはモールの max_page で切る）。不正は InvalidInput(ValueError)
    if not (1 <= hits <= max_hits):       # モールの 1 ページの上限（楽天 30: 出典 楽天 IchibaItem Search 仕様）
        raise ValueError(f"hits must be 1..{max_hits}")
    if limits.min_interval_sec < 0:
        raise ValueError("min_interval_sec must be >= 0")
    if limits.time_budget_sec <= 0:
        raise ValueError("time_budget_sec must be > 0")


def _finish_stat(stat: KeywordStat, hits: int, max_page: int) -> None:
    """取得を終えた語の last_page・remaining・truncated を決める（next_page は呼び出し側が先に決めておく）。"""
    if stat.pages_fetched:
        stat.last_page = stat.start_page + stat.pages_fetched - 1
    if stat.api_count is not None and stat.last_page is not None:
        reachable = min(stat.api_count, max_page * hits)      # モールが返すのは max_page ページ目まで（楽天 100・Yahoo 20）
        stat.remaining = max(0, reachable - stat.last_page * hits)
    stat.truncated = stat.truncated or stat.next_page is not None


def search_many(adapter, keywords: list[str], *, max_pages: int | None = None, start_page: int = 1,
                hits: int = 30, limits: Limits = Limits(), sleep=time.sleep, clock=None,
                **filters) -> tuple[list[Offer], SearchStats]:
    """keywords を順に検索し、mall_item_code で重複排除した Offer と統計を返す。

    語ごとに start_page 〜 start_page+max_pages-1 ページを取る（max_pages=None は既定の 3 ページ）。
    範囲が 100 ページ天井を超える指定は ValueError（黙って切らない・通信前に判定）。モールの max_page（Yahoo は 20）を
    越えるページは呼ばず、その語は truncated=True・next_page=None（モールの件数の上限。ceiling_note を持つモールだけ。楽天は従来どおり）。
    ヒットが尽きたら早く止める。続きがあれば stat.next_page に次のページ番号を入れる。
    1 回の取得が limits.time_budget_sec を超えそうなら、そこで止めて取れた分を返す（stopped_reason=time_limit・
    未取得の語は next_page=start_page）。clock は試験で実時間を固定するために差し替えられる。
    アダプタの stop_kinds（楽天 http_429・Yahoo rate_limited/server_error）のエラーは、そのモールの残り全部を打ち切る。
    他の AdapterError はそのキーワードだけ記録して続行。
    """
    clock = clock or time.monotonic       # 呼び出し時に解決（試験で time.monotonic を差し替えられる）
    keywords = list(keywords)
    mall = getattr(adapter, "mall", "") or ""
    max_page = adapter_attr(adapter, "max_page")
    stop_kinds = tuple(adapter_attr(adapter, "stop_kinds"))
    empty_means_end = adapter_attr(adapter, "empty_means_end")
    ceiling_note = adapter_attr(adapter, "ceiling_note")
    hits = adapter_attr(adapter, "page_size") or hits     # 1 ページの件数が固定のモール（Yahoo 50）は呼び出しの hits に従わない
    _validate(keywords, max_pages, start_page, hits, limits, adapter_attr(adapter, "max_hits"))
    pages_wanted = check_page_range(start_page, max_pages)[1]
    requested_end = start_page + pages_wanted - 1
    end_page = min(requested_end, max_page)
    started = clock()

    stats = SearchStats(fetched_at=datetime.now(JST).isoformat())
    unique: dict[tuple[str, str], Offer] = {}
    requests_done = 0
    skipped = 0

    def time_is_up() -> bool:
        """次の 1 回（直近までの平均所要時間と同じだけかかると見る）を終えた時点で上限を超えるか。"""
        elapsed = clock() - started
        return elapsed + elapsed / requests_done > limits.time_budget_sec

    for index, keyword in enumerate(keywords):
        stat = KeywordStat(keyword=keyword, start_page=start_page, mall=mall)
        stats.per_keyword.append(stat)
        stop_kind = None
        timed_out = False
        if start_page > max_page and ceiling_note:      # このモールが返せる範囲の外。呼ばない
            stat.truncated = True
        for page in range(start_page, end_page + 1):
            if requests_done:
                if time_is_up():
                    timed_out = True
                    stat.next_page = page
                    break
                sleep(limits.min_interval_sec)
            requests_done += 1
            try:
                offers, api_count = adapter.search(keyword, page=page, hits=hits, **filters)
            except AdapterError as exc:
                stat.error = exc.kind
                stop_kind = exc.kind if exc.kind in stop_kinds else None
                break
            if stat.api_count is None:
                stat.api_count = api_count
            stat.pages_fetched += 1
            stat.received += len(offers)
            stats.total_received += len(offers)
            skipped += getattr(offers, "skipped", 0)
            for offer in offers:
                key = (offer.mall, offer.mall_item_code)
                existing = unique.get(key)
                if existing is None:
                    offer.matched_keywords = [keyword]
                    unique[key] = offer
                else:
                    stats.duplicates_removed += 1
                    if keyword not in existing.matched_keywords:
                        existing.matched_keywords.append(keyword)
            if (not offers and empty_means_end) or page * hits >= api_count:
                break
        else:
            # break せずに指定範囲の最後のページまで来た。ヒットが残っていて、モールの天井（楽天 100・Yahoo 20）の手前なら続きがある
            if stat.api_count is not None and stat.api_count > end_page * hits and end_page < max_page:
                stat.next_page = end_page + 1
            elif ceiling_note and stat.api_count is not None and stat.api_count > max_page * hits:
                stat.truncated = True      # モールの件数の上限に達した（next_page は無い。指定が上限を越えていて越えた分を呼ばなかった時も）
        _finish_stat(stat, hits, max_page)
        if stop_kind:
            stats.stopped_reason = "rate_limited" if stop_kind in ("http_429", "rate_limited") else "server_error"
            break
        if timed_out:
            stats.stopped_reason = "time_limit"
            for rest in keywords[index + 1:]:       # 未着手の語。続きは最初のページから
                unstarted = KeywordStat(keyword=rest, start_page=start_page, next_page=start_page, truncated=True,
                                        mall=mall)
                stats.per_keyword.append(unstarted)
            break

    stats.unique_offers = len(unique)
    stats.elapsed_sec = round(clock() - started, 1)    # 取得にかかった秒
    stats.per_mall = [_mall_stat(mall, stats, skipped)]
    return list(unique.values()), stats


def _mall_stat(mall: str, stats: SearchStats, skipped: int) -> MallStat:
    rows = stats.per_keyword
    counts = [s.api_count for s in rows if s.api_count is not None]
    failed = bool(rows) and all(s.error for s in rows) and not stats.total_received
    return MallStat(mall=mall, fetched=stats.total_received, api_count=sum(counts) if counts else None,
                    error=rows[0].error if failed else None, truncated=any(s.truncated for s in rows),
                    stopped_reason=stats.stopped_reason, skipped=skipped)
