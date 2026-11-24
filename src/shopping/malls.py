# @owns モールの選択と束ね（どのモールが有効か・アダプタの組み立て・モール別の検索の並走・結果の統合）
"""楽天と Yahoo を同じ検索条件で引き、候補を 1 つのリストに混ぜる。モール固有の知識はアダプタの属性（label・max_page…）から引くだけ。
モール内の検索（ページング・重複排除・流量）は orchestrator.search_many。ここはモールをまたぐ所だけ。"""
from __future__ import annotations

import dataclasses
import threading
import time

from .adapters.base import MarketplaceAdapter, adapter_attr
from .adapters.mock import MockAdapter, MockYahooAdapter
from .adapters.rakuten import RakutenAdapter
from .adapters.yahoo import YahooAdapter
from .config import load_yahoo_credentials
from .inputs import check_malls
from .models import Offer, SearchStats
from .orchestrator import Limits, search_many

# モール名 → アダプタのクラス（表示名・商品 URL の形・出典をクラスの属性から引く）。順番が結果の並び（楽天が先）
REGISTRY: dict[str, type] = {"rakuten": RakutenAdapter, "yahoo": YahooAdapter}


def label(mall: str) -> str:
    cls = REGISTRY.get(mall)
    return cls.label if cls else str(mall or "")


def short_label(mall: str) -> str:
    cls = REGISTRY.get(mall)
    return cls.short_label if cls else str(mall or "")


def source(mall: str) -> str:
    cls = REGISTRY.get(mall)
    return cls.source if cls else str(mall or "")


def is_item_url(mall: str, url: object) -> bool:
    """そのモールの商品固有 URL の形か（未知のモールは False＝リンクを出さない）。"""
    cls = REGISTRY.get(mall)
    return bool(cls and cls.is_item_url(url))


def default_adapters(primary: MarketplaceAdapter) -> dict[str, MarketplaceAdapter]:
    """楽天のアダプタ（make_adapter の結果）に、同じ種類の他モールのアダプタを並べる。
    既定の架空データのモック → Yahoo もモック。本物の楽天アダプタ → Yahoo の鍵（環境変数・.env・.env.yahoo.local）がある時だけ Yahoo も有効
    （鍵が無ければ楽天だけ＝従来どおり）。それ以外（データを差し替えたモック・試験の偽物）は楽天だけ。"""
    out: dict[str, MarketplaceAdapter] = {getattr(primary, "mall", "rakuten"): primary}
    if isinstance(primary, MockAdapter):
        if primary.default_data:
            out["yahoo"] = MockYahooAdapter()
    elif isinstance(primary, RakutenAdapter):
        creds = load_yahoo_credentials()
        if creds.present:
            out["yahoo"] = YahooAdapter(creds.client_id)
    return out


def select(adapters: dict[str, MarketplaceAdapter], malls) -> dict[str, MarketplaceAdapter]:
    """検索するモールのアダプタ（楽天が先）。malls=None は有効な全モール。無効・未知・空の指定は InvalidInput（API を呼ばない）。"""
    wanted = check_malls(malls, list(adapters))
    names = list(adapters) if wanted is None else wanted
    order = list(REGISTRY)
    names.sort(key=lambda m: order.index(m) if m in order else len(order))
    return {m: adapters[m] for m in names}


def _mall_limits(adapter, limits: Limits) -> Limits:
    """間隔はモールごと。公開面が 0（GuardedAdapter が直列化）や楽天の値のままならそのまま、より遅いモール（Yahoo 2.2 秒）は上げる。"""
    iv = adapter_attr(adapter, "min_interval_sec")
    if limits.min_interval_sec > 0 and iv > limits.min_interval_sec and iv > MarketplaceAdapter.min_interval_sec:
        return dataclasses.replace(limits, min_interval_sec=iv)
    return limits


def search_malls(adapters: dict[str, MarketplaceAdapter], keywords: list[str], *, max_pages: int | None = None,
                 start_page: int = 1, hits: int = 30, limits: Limits | None = None, sleep=time.sleep, clock=None,
                 **filters) -> tuple[list[Offer], SearchStats]:
    """モールごとに search_many を呼び、候補を混ぜて返す（モールの並び順＝楽天が先）。2 モール以上はモール単位で並走する
    （スレッド 1 本ずつ。モール内は今のとおり直列・モールごとの間隔）。片方の失敗はもう片方の結果を消さない
    （モール別の失敗は stats.per_mall・per_keyword の error）。不正な指定（ValueError）は通信前に、最初のモールの分を再送出する。"""
    limits = limits or Limits()
    items = list(adapters.items())
    results: dict[str, tuple[list[Offer], SearchStats] | BaseException] = {}

    def run(mall: str, adapter) -> None:
        try:
            results[mall] = search_many(adapter, keywords, max_pages=max_pages, start_page=start_page, hits=hits,
                                        limits=_mall_limits(adapter, limits), sleep=sleep, clock=clock, **filters)
        except BaseException as exc:      # スレッドの外で再送出する
            results[mall] = exc

    if len(items) == 1:
        run(*items[0])
    else:
        threads = [threading.Thread(target=run, args=item, daemon=True) for item in items]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    for mall, _ in items:
        if isinstance(results[mall], BaseException):
            raise results[mall]
    parts = [results[m] for m, _ in items]
    if len(parts) == 1:
        return parts[0]
    return _merge(parts)


def _merge(parts: list[tuple[list[Offer], SearchStats]]) -> tuple[list[Offer], SearchStats]:
    offers: list[Offer] = []
    first = parts[0][1]
    merged = SearchStats(fetched_at=first.fetched_at)
    for part_offers, st in parts:
        offers.extend(part_offers)
        merged.per_keyword.extend(st.per_keyword)
        merged.per_mall.extend(st.per_mall)
        merged.total_received += st.total_received
        merged.duplicates_removed += st.duplicates_removed
        merged.unique_offers += st.unique_offers
        merged.stopped_reason = merged.stopped_reason or st.stopped_reason
        merged.elapsed_sec = max(merged.elapsed_sec or 0.0, st.elapsed_sec or 0.0)      # 並走なので長い方
    return offers, merged
