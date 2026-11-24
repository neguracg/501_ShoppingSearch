# @owns ツール単位の処理（検索・比較・定番品）と、呼び出し側へ返す JSON 化可能な dict の形
"""MCP と CLI の共通処理。失敗は例外ではなく {"ok": False, "error": {...}} で返す。
戻り値に認証情報・生レスポンスは含めない。"""
from __future__ import annotations

import os
import time
import unicodedata
from dataclasses import asdict

from . import malls as malls_mod
from .adapters.base import MarketplaceAdapter, adapter_attr
from .adapters.mock import MockAdapter
from .adapters.rakuten import RakutenAdapter
from .config import RakutenCredentials, load_credentials
from .credit import credits_list
from .models import Offer, SearchStats
from .orchestrator import Limits
from .inputs import (DEFAULT_PAGES, InvalidInput, check_basis, check_desired_range,
                     check_term_lengths)
from .pricing import (Comparison, OrderPlan, ToCheck, compare, filter_by_terms, round_unit_price,
                      total_price, unconfirmed_reasons, unit_price_reasons)
from .caption_quantity import read_offer_quantity
from .regulars import Regular, RegularsError, get_regular

SOURCE = RakutenAdapter.source
CAPTION_MAX = 200
MOCK_ENV = "SHOPPING_MOCK"

_FRESHNESS_NOTE = "価格・在庫は fetched_at 時点の値。キャッシュは24時間以内に取り直すこと。"
_MOCK_NOTE = "これは架空のモックデータで、実在の商品・価格ではない（SHOPPING_MOCK）。"


def is_mock_env() -> bool:
    return os.environ.get(MOCK_ENV) == "1"


LIVE_ENV = "SHOPPING_LIVE"


def make_adapter(mock: bool | None = None, credentials: RakutenCredentials | None = None,
                 *, local_tool: bool = False) -> MarketplaceAdapter:
    """Adapter 生成。mock が True/False ならそれに従う。None なら環境変数 SHOPPING_MOCK=1 でモック。
    local_tool=True（CLI・stdio MCP＝運営者の開発・試験用。SPEC §11）は既定がモックで、
    実 API は明示した時だけ（CLI の --live、または環境変数 SHOPPING_LIVE=1）。公開Web は local_tool=False
    （実 API が既定）。"""
    if mock is None:
        mock = is_mock_env() or (local_tool and os.environ.get(LIVE_ENV) != "1")
    if mock:
        return MockAdapter()
    creds = credentials or load_credentials()
    return RakutenAdapter(creds.app_id, creds.access_key)


def make_adapters(mock: bool | None = None, credentials: RakutenCredentials | None = None,
                  *, local_tool: bool = False) -> dict[str, MarketplaceAdapter]:
    """有効なモールのアダプタ（モール名 → アダプタ。楽天が先）。楽天は make_adapter（従来どおり）、他のモールは同じ種類
    〔モック→モック・本物→鍵がある時だけ〕を malls.default_adapters が並べる。"""
    return malls_mod.default_adapters(make_adapter(mock, credentials, local_tool=local_tool))


def _error(kind: str, message: str, **extra) -> dict:
    out = {"ok": False, "error": {"kind": kind, "message": message}}
    out.update(extra)
    return out


def _price_fields(value: float | None, reasons: list[str], key: str) -> dict:
    """単価を出力 dict のキーへ振り分ける唯一の場所（WP15 §8 Q21・Q23）。value は内部の計算値、reasons は単価の未確定理由
    （pricing.unit_price_reasons。送料を含まない）。確認済みなら key に値、未確定なら key は null で値は provisional_<key>。
    単価が無ければ status は unknown。"""
    shown = round_unit_price(value)
    status = "unknown" if shown is None else ("unconfirmed" if reasons else "confirmed")
    return {key: shown if status == "confirmed" else None,
            f"provisional_{key}": shown if status == "unconfirmed" else None,
            "unit_price_status": status,
            "unit_price_unconfirmed_reasons": list(reasons) if status == "unconfirmed" else []}


def offer_to_dict(offer: Offer, known_urls: list[str] | None = None) -> dict:
    q = offer.quantity
    price_fields = _price_fields(offer.unit_price, unit_price_reasons(unconfirmed_reasons(offer)), "unit_price")
    d = {
        "mall": offer.mall,
        "item_code": offer.mall_item_code,
        "name": offer.item_name,
        "price": offer.price,
        "shop_name": offer.shop_name,
        "url": offer.item_url,
        "url_status": offer.item_url_status,
        "shipping_status": offer.shipping_status,
        "shipping_fee": offer.shipping_fee,
        "total_price": total_price(offer),
        "availability": offer.availability,
        "points_rate": offer.points_rate,
        "review_average": offer.review_average,
        "review_count": offer.review_count,
        "shipping_title_conflict": shipping_title_conflict(offer),
        "caption": (offer.caption[:CAPTION_MAX] if offer.caption else offer.caption),
        "fetched_at": offer.fetched_at,
        "matched_keywords": list(offer.matched_keywords),
        "quantity": None if q is None else {
            "count_total": q.count_total, "count_unit": q.count_unit,
            "content_amount": q.content_amount, "content_dimension": q.content_dimension,
            "content_unit": q.content_unit, "measure_total": q.measure_total,
            "confidence": "conflict" if q.caption_conflict else q.confidence,       # 出力は「単価に使ってよいか」（§7 Q22）
            "title_confidence": q.confidence,                                      # 題名の判定（内部の値のまま）
            "evidence": q.evidence,
            "content_amounts": dict(q.content_amounts or {}),
            "source": q.source, "caption_evidence": q.caption_evidence, "caption_conflict": q.caption_conflict,
            "packs": [dict(x) for x in (q.packs or [])],                        # 包装の数（§7。常に出す。読めなければ []）
            "caption_candidate": None if q.caption_candidate is None else dict(q.caption_candidate),
            # WP16（§7）: 印であって確定値ではない。low_reason・readings は題名 low の時だけ値（他は null）。caption_candidates は常に出す（無ければ []）
            "low_reason": q.low_reason,
            "readings": None if q.readings is None else {"counts": [dict(c) for c in q.readings.get("counts", [])],
                                                        "contents": {d: list(v) for d, v in q.readings.get("contents", {}).items()}},
            "caption_candidates": [dict(c) for c in q.caption_candidates]},
        **price_fields,
        "unit_price_label": offer.unit_price_label,
        "unit_price_dimension": offer.unit_price_dimension,
        "unit_price_outlier": offer.unit_price_outlier,
        "price_min": offer.price_min,
        "price_max": offer.price_max,
        "price_varies": offer.price_varies,
        "asuraku_flag": offer.asuraku_flag,
        "asuraku_closing_time": offer.asuraku_closing_time,
        # WP17（§5b）: モールが付ける参考。points_amount＝円相当の参考値（総額・単価・最安には使わない）、shipping_condition＝
        # conditional_free（条件付き送料無料）、condition＝商品の状態、sale＝セール中の参考。楽天は None
        "points_amount": offer.points_amount,
        "shipping_condition": offer.shipping_condition,
        "condition": offer.condition,
        "sale": None if offer.sale is None else dict(offer.sale),
    }
    if known_urls is not None:
        d["is_known_url"] = offer.item_url in known_urls
    return d


def _stats_to_dict(stats: SearchStats) -> dict:
    return asdict(stats)


def _validate_keywords(keywords) -> list[str] | dict:
    if isinstance(keywords, str):
        keywords = [keywords]
    if (not isinstance(keywords, (list, tuple)) or not keywords
            or not all(isinstance(k, str) and k.strip() for k in keywords)):
        return _error("invalid_request", "keywords は空でない文字列のリストで指定する")
    return [k.strip() for k in keywords]


def _adapter_map(adapter, adapters) -> dict[str, MarketplaceAdapter]:
    """呼び出しが渡したアダプタ。adapter（従来の単独指定）は {adapter.mall: adapter} と同じ意味。どちらも無ければ有効な全モール（鍵のあるモール）。"""
    out: dict[str, MarketplaceAdapter] = dict(adapters or {})
    if adapter is not None:
        out.setdefault(getattr(adapter, "mall", "") or "rakuten", adapter)
    return out if out else make_adapters(local_tool=True)


def _search(keywords, adapter, *, pages, start_page, hits, limits, sleep, filters, adapters=None, malls=None):
    """(offers, stats, mock, 使ったモールのアダプタ) または エラー dict。"""
    kws = _validate_keywords(keywords)
    if isinstance(kws, dict):
        return kws
    try:                                         # 1 文字だけの語は楽天が HTTP 400 にする。送る前に弾く（inputs に一本化）
        check_term_lengths(kws, "検索語")
        if filters.get("ng_keyword"):
            check_term_lengths(filters["ng_keyword"], "除外語（楽天側）")
    except InvalidInput as exc:
        return _error(exc.kind, str(exc))
    try:
        used = malls_mod.select(_adapter_map(adapter, adapters), malls)     # 無効・未知・空のモール指定は API を呼ばずに弾く（C2）
    except InvalidInput as exc:
        return _error(exc.kind, str(exc))
    mock = any(isinstance(a, MockAdapter) or bool(getattr(a, "is_mock", False)) for a in used.values())
    if sleep is None:
        sleep = (lambda s: None) if mock else time.sleep
    try:
        offers, stats = malls_mod.search_malls(used, kws, max_pages=pages, start_page=start_page, hits=hits,
                                               limits=limits or Limits(), sleep=sleep, **filters)
    except ValueError as exc:  # 上限超え・不正値（メッセージは自前の文言のみ）
        return _error("invalid_request", str(exc))
    if not offers and stats.per_keyword and all(s.error for s in stats.per_keyword):
        first = stats.per_keyword[0].error          # 全モールが失敗した時は最初に失敗したモール（楽天が先）の種別
        return _error(first, f"全キーワードの検索に失敗した（{first}）",
                      stats=_stats_to_dict(stats), mock=mock)
    return offers, stats, mock, used


_TITLE_FREE_SHIP = ("送料無料", "送料込", "送料0円", "送料込み")
_TITLE_SEPARATE_SHIP = ("送料別", "別途送料", "送料は別", "送料お客様負担", "送料はお客様負担")


def shipping_title_conflict(offer: Offer) -> str | None:
    """タイトルの送料表記とモールのフラグ（楽天 postageFlag・Yahoo shipping.code 由来の shipping_status）が食い違う時の説明。

    送料はフラグを正とする（タイトルの文字で送料を決めない）。食い違いは注意として出すだけ。"""
    title = unicodedata.normalize("NFKC", offer.item_name or "")
    who = malls_mod.short_label(offer.mall)
    if offer.shipping_status == "separate" and any(w in title for w in _TITLE_FREE_SHIP):
        return (f"タイトルに「送料無料」等の表記があるが、{who}のデータでは送料別。"
                "条件付き（一定額以上で無料など）の可能性があるため、購入前に商品ページで確認すること")
    if offer.shipping_status == "included" and any(w in title for w in _TITLE_SEPARATE_SHIP):
        return (f"タイトルに「送料別」等の表記があるが、{who}のデータでは送料込み。"
                "購入前に商品ページで確認すること")
    return None


def _shipping_conflict_note(offers: list[Offer]) -> str | None:
    hit = [o for o in offers if shipping_title_conflict(o)]
    if not hit:
        return None
    who = "・".join(dict.fromkeys(malls_mod.short_label(o.mall) for o in hit))
    return (f"タイトルの送料表記と{who}のデータ（送料込み/別）が食い違う候補が {len(hit)} 件ある。"
            f"送料は{who}のデータを正として扱い、タイトルの文字では決めていない。購入前に商品ページで確認すること。")


def _annotate(offers: list[Offer]) -> None:
    for o in offers:
        o.quantity = read_offer_quantity(o)


def _source_fields(used: dict) -> dict:
    """結果の出典まわり。source は使ったモールの出典（楽天だけの時は従来の文字列）、malls は使ったモール。
    楽天だけでない時は sources（一覧）、Yahoo を使った時は credits（クレジットの一覧。既存の credit〔楽天〕は変えない）。"""
    names = list(used)
    out: dict = {"source": " / ".join(malls_mod.source(m) for m in names), "malls": names}
    if names != ["rakuten"]:
        out["sources"] = [malls_mod.source(m) for m in names]
    if "yahoo" in names:
        out["credits"] = credits_list(names)
    return out


def _mall_attr(mall: str, name: str):
    """モール名からアダプタのクラス属性（上限・表示名）を引く。未知のモールは楽天相当の既定。"""
    return adapter_attr(malls_mod.REGISTRY.get(mall), name)


def _mall_notes(stats: SearchStats, used: dict, filters: dict) -> list[str]:
    """モール別の注記（C5・Y2〜Y4）。1 モールだけの検索（楽天のみ）では、従来の文言のまま。"""
    notes: list[str] = []
    multi = len(used) > 1
    for ms in stats.per_mall:
        lab = malls_mod.label(ms.mall)
        ad = used.get(ms.mall)
        if multi and ms.error:       # 片方のモールが全部失敗しても、もう片方の結果で比べる（全モールが失敗した時は error 応答）
            others = "・".join(malls_mod.label(o.mall) for o in stats.per_mall if o is not ms and not o.error)
            notes.append(f"{lab}は {ms.error} で取得できなかった（{others}だけで比較）")
        if ms.stopped_reason == "rate_limited" and ms.mall == "rakuten":
            notes.append("楽天APIの流量制限(429)で残りの検索を打ち切った。時間をおいて再実行すること。")
        elif ms.stopped_reason == "rate_limited":
            notes.append(f"{lab}の流量制限（rate_limited）で残りの検索を打ち切った。時間をおいて再実行すること。")
        elif ms.stopped_reason == "server_error":
            notes.append(f"{lab}が server_error を返したため、残りの検索を打ち切った。時間をおいて再実行すること。")
        if ms.skipped:
            notes.append(f"{lab}の応答のうち、読めない {ms.skipped} 件を捨てた。")
        if ad is not None:
            notes.extend(ad.request_notes(sort=filters.get("sort", "standard"), ng_keyword=filters.get("ng_keyword"))
                         if hasattr(ad, "request_notes") else [])
        ceiling_note = _mall_attr(ms.mall, "ceiling_note")
        if ceiling_note and any(s.mall == ms.mall and s.truncated and s.next_page is None for s in stats.per_keyword):
            notes.append(ceiling_note)
    return notes


def _base_notes(offers: list[Offer], stats: SearchStats, mock: bool, hits: int,
                *, shipping_conflict: bool = True, paging_notes: bool = True,
                used: dict | None = None, filters: dict | None = None) -> list[str]:
    malls_used = list(used) if used else ["rakuten"]
    multi = len(malls_used) > 1
    sources = [malls_mod.source(m) for m in malls_used]
    notes = [_FRESHNESS_NOTE, "出典: " + " / ".join(sources)]
    if mock:
        notes.insert(0, _MOCK_NOTE)
    review = sum(1 for o in offers if o.item_url_status != "ok")
    if review:
        notes.append(f"商品URLの形式が想定外の候補が {review} 件ある（url_status=needs_review）。"
                     "購入前にリンク先を確認すること。")
    conflict = _shipping_conflict_note(offers) if shipping_conflict else None
    if conflict:
        notes.append(conflict)
    errs = [(f"{malls_mod.label(s.mall)} " if multi else "") + f"{s.keyword}: {s.error}" for s in stats.per_keyword if s.error]
    if errs:
        notes.append("一部の検索でエラー: " + " / ".join(errs))
    notes.extend(_mall_notes(stats, used or {m: None for m in malls_used}, filters or {}))
    if paging_notes:                  # 続きの取り方は MCP・CLI 向け。Web 画面は 1 ページ固定なので出さない
        notes.extend(_paging_notes(stats, hits, multi))
    return notes


def _paging_notes(stats: SearchStats, hits: int, multi: bool = False) -> list[str]:
    """全量と取得範囲、続きの取り方（語ごと）。利用者に全量と取得範囲を伝えるための材料。"""
    notes: list[str] = []
    if stats.stopped_reason == "time_limit":
        notes.append("時間の上限で途中まで。取れた分だけ返した。続きは下記の start_page で呼ぶこと。")
    more = [s for s in stats.per_keyword if s.next_page is not None]

    def who(s):
        return f"（{malls_mod.label(s.mall)}）" if multi else ""
    for s in more:
        if s.pages_fetched:
            rest = f"（残り約 {s.remaining} 件）" if s.remaining is not None else ""
            notes.append(f"「{s.keyword}」{who(s)}はヒット {s.api_count} 件のうち {s.start_page}〜{s.last_page} ページ目の "
                         f"{s.received} 件を取得{rest}。続きは start_page={s.next_page} で呼ぶ。")
        else:
            notes.append(f"「{s.keyword}」{who(s)}は未取得。start_page={s.next_page} で呼ぶ。")
    if len(more) and len(stats.per_keyword) > 1:
        notes.append("続きを取る時は、続きが要る語だけを keywords に指定すること（他の語は同じページを取り直してしまう）。")
    for s in stats.per_keyword:                  # 楽天は 100 ページ目で件数の天井。Yahoo は ceiling_note（_mall_notes）が案内する
        if _mall_attr(s.mall or "rakuten", "ceiling_note"):
            continue
        max_page = _mall_attr(s.mall or "rakuten", "max_page")
        ceiling = max_page * hits
        if s.api_count is not None and s.api_count > ceiling:
            notes.append(f"「{s.keyword}」{who(s)}はヒット {s.api_count} 件だが、{malls_mod.short_label(s.mall or 'rakuten')}が返すのは {max_page} ページ目"
                         f"（先頭 {ceiling} 件）まで。絞り込み（語・価格・ng_keyword）で件数を減らすこと。")
    return notes


def search_products(keywords, *, ng_keyword: str | None = None, min_price: int | None = None,
                    max_price: int | None = None, sort: str = "standard", pages: int | None = DEFAULT_PAGES,
                    start_page: int = 1, hits: int = 30, max_results: int | None = None,      # hits 30 は楽天の上限（1 ページ最大）
                    include_terms=None, exclude_terms=None,
                    adapter: MarketplaceAdapter | None = None, sleep=None,
                    limits: Limits | None = None, paging_notes: bool = True,
                    adapters: dict[str, MarketplaceAdapter] | None = None, malls: list[str] | None = None) -> dict:
    inc = _terms_arg(include_terms, "include_terms")
    exc = _terms_arg(exclude_terms, "exclude_terms")
    for v in (inc, exc):
        if isinstance(v, dict):
            return v
    filters = dict(ng_keyword=ng_keyword, min_price=min_price, max_price=max_price, sort=sort)
    r = _search(keywords, adapter, pages=pages, start_page=start_page, hits=hits, limits=limits,
                sleep=sleep, filters=filters, adapters=adapters, malls=malls)
    if isinstance(r, dict):
        return r
    offers, stats, mock, used = r
    _annotate(offers)
    kept, term_notes = filter_by_terms(offers, inc, exc)     # 比較（compare）と同じ絞り込み（S9）
    shown = kept if max_results is None else kept[:max(0, max_results)]   # None は全件（切り詰めは利用者が max_results を指定した時だけ）
    notes = _base_notes(kept, stats, mock, hits, paging_notes=paging_notes, used=used, filters=filters) + term_notes
    if len(shown) < len(kept):
        notes.append(f"候補 {len(kept)} 件のうち先頭 {len(shown)} 件だけ返した（max_results）。")
    return {"ok": True, **_source_fields(used), "mock": mock, "keywords": _validate_keywords(keywords),
            "include_terms": inc, "exclude_terms": exc,
            "stats": _stats_to_dict(stats), "returned": len(shown),
            "offers": [offer_to_dict(o) for o in shown], "notes": notes}


def order_plan_to_dict(p: OrderPlan) -> dict:
    """注文案（同じ商品を n 個）。候補の全項目は出さず、商品を特定する項目と注文の数字だけ（候補一覧は groups[].offers）。"""
    o, q = p.offer, p.offer.quantity
    kind = ("payment_total" if p.confirmed else                    # 確認済みの案だけ支払総額（§8 Q23。WP15 レビュー B1）
            "unconfirmed_total" if p.shipping_status == "included" else "item_subtotal")
    return {
        "mall": o.mall, "item_code": o.mall_item_code, "name": o.item_name, "shop_name": o.shop_name,
        "url": o.item_url, "url_status": o.item_url_status,
        "price": o.price, "price_min": o.price_min, "price_max": o.price_max, "price_varies": o.price_varies,
        "n": p.n, "order_quantity": p.order_quantity, "order_total": p.order_total,
        "payment_total": p.order_total if kind == "payment_total" else None,
        "order_total_kind": kind,
        **_price_fields(p.order_unit_price, unit_price_reasons(p.reasons), "order_unit_price"),
        "unit_price_label": p.label or o.unit_price_label,           # 他の数え語の候補を主グループの数え語で換算した案は主グループのラベル
        "shipping_status": p.shipping_status, "count_unit": p.count_unit,
        "quantity_source": None if q is None else q.source, "caption_evidence": None if q is None else q.caption_evidence,
        "confirmed": p.confirmed, "unconfirmed_reasons": list(p.reasons),
    }


def to_check_to_dict(t: ToCheck) -> dict:
    return dict(order_plan_to_dict(t.plan), conditions=[dict(c) for c in t.conditions])


def _comparison_to_dict(c: Comparison, known_urls: list[str] | None = None,
                        group_offers_max: int | None = None) -> dict:
    """group_offers_max: groups[].offers と unknown_offers を先頭何件で切るか。None は切らない（MCP・CLI）。
    Web 画面だけが表示のために指定する（web.WEB_GROUP_OFFERS_MAX）。count / unknown_count は常に全件数。"""
    def cut(offers):
        return offers if group_offers_max is None else offers[:group_offers_max]

    def one(o: Offer | None):
        return None if o is None else offer_to_dict(o, known_urls)
    return {
        "basis": c.basis,
        "basis_label": c.basis_label,
        "groups": [{"basis": g.basis, "dimension": g.dimension, "count_unit": g.count_unit, "count": len(g.offers),
                    "cheapest_unit_price": one(g.cheapest_unit_price),
                    "order_plans": [order_plan_to_dict(p) for p in g.order_plans],
                    "cheapest_order": None if g.cheapest_order is None else order_plan_to_dict(g.cheapest_order),
                    "to_check": [to_check_to_dict(t) for t in g.to_check],
                    "offers": [offer_to_dict(o, known_urls) for o in cut(g.offers)]}
                   for g in c.groups],
        "unknown_offers": [offer_to_dict(o, known_urls) for o in cut(c.unknown_offers)],
        "unknown_count": len(c.unknown_offers),
        "cheapest_price": one(c.cheapest_price),
        "main_count_unit": c.main_count_unit,
        "cheapest_unit_price": one(c.cheapest_unit_price),
        "cheapest_total": one(c.cheapest_total),
        "cheapest_for_quantity": one(c.cheapest_for_quantity),
        "order_plans": [order_plan_to_dict(p) for p in c.order_plans],
        "cheapest_order": None if c.cheapest_order is None else order_plan_to_dict(c.cheapest_order),
        "to_check": [to_check_to_dict(t) for t in c.to_check],
        "caveats": list(c.caveats),
        "notes": list(c.notes),
    }


def _terms_arg(value, name: str) -> list[str] | None | dict:
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not all(isinstance(t, str) for t in value):
        return _error("invalid_request", f"{name} は文字列のリストで指定する")
    return [t.strip() for t in value if t.strip()] or None


def _compare_flow(keywords, include_terms, exclude_terms, desired_quantity, basis, *, adapter,
                  pages, start_page, hits, limits, sleep, filters, known_urls=None,
                  group_offers_max: int | None = None, paging_notes: bool = True,
                  desired_quantity_max=None, adapters=None, malls=None) -> dict:
    inc = _terms_arg(include_terms, "include_terms")
    exc = _terms_arg(exclude_terms, "exclude_terms")
    for v in (inc, exc):
        if isinstance(v, dict):
            return v
    if basis == "":
        basis = None
    try:                                         # 検査の実装は inputs に一本化（公開面の Gate と同じ）
        check_basis(basis)
        check_desired_range(desired_quantity, desired_quantity_max)
    except InvalidInput as exc:
        return _error("invalid_request", str(exc))
    r = _search(keywords, adapter, pages=pages, start_page=start_page, hits=hits, limits=limits,
                sleep=sleep, filters=filters, adapters=adapters, malls=malls)
    if isinstance(r, dict):
        return r
    offers, stats, mock, used = r
    _annotate(offers)
    comparison = compare(offers, include_terms=inc, exclude_terms=exc,
                         desired_quantity=desired_quantity, basis=basis,
                         desired_quantity_max=desired_quantity_max)
    conflict = _shipping_conflict_note(offers)
    if conflict:
        comparison.caveats.append(conflict)
    notes = _base_notes(offers, stats, mock, hits, shipping_conflict=False,
                         paging_notes=paging_notes, used=used, filters=filters) + comparison.notes
    return {"ok": True, **_source_fields(used), "mock": mock, "keywords": _validate_keywords(keywords),
            "include_terms": inc, "exclude_terms": exc, "desired_quantity": desired_quantity,
            "desired_quantity_max": desired_quantity_max, "basis": comparison.basis, "stats": _stats_to_dict(stats),
            "comparison": _comparison_to_dict(comparison, known_urls, group_offers_max),
            "notes": notes}


def compare_offers(keywords, include_terms=None, exclude_terms=None, desired_quantity=None,
                   basis: str | None = None, *, ng_keyword: str | None = None,
                   min_price: int | None = None, max_price: int | None = None,
                   sort: str = "standard", pages: int | None = DEFAULT_PAGES, start_page: int = 1,
                   hits: int = 30, adapter: MarketplaceAdapter | None = None, sleep=None,
                   limits: Limits | None = None, group_offers_max: int | None = None,
                   paging_notes: bool = True, desired_quantity_max: float | None = None,
                   adapters: dict[str, MarketplaceAdapter] | None = None, malls: list[str] | None = None) -> dict:
    filters = dict(ng_keyword=ng_keyword, min_price=min_price, max_price=max_price, sort=sort)
    return _compare_flow(keywords, include_terms, exclude_terms, desired_quantity, basis,
                         adapter=adapter, pages=pages, start_page=start_page, hits=hits, limits=limits,
                         sleep=sleep, filters=filters, group_offers_max=group_offers_max,
                         paging_notes=paging_notes, desired_quantity_max=desired_quantity_max,
                         adapters=adapters, malls=malls)


def _regular_info(r: Regular) -> dict:
    return {"id": r.id, "name": r.name, "maker": r.maker, "model_number": r.model_number,
            "jan": r.jan, "include_terms": r.include_terms,
            "exclude_terms": r.exclude_terms, "basis": r.basis,
            "desired_quantity": r.desired_quantity, "keywords": r.keywords, "notes": r.notes}


_REGULARS_MESSAGES = {
    "file_not_found": "定番品マスタ（data/regulars.json）が見つからない。"
                      "examples/regulars.sample.json をコピーして作る。",
    "invalid_json": "定番品マスタが正しい JSON ではない。",
    "invalid_format": "定番品マスタの形式が不正。",
    "not_found": "その id の定番品がマスタにない。",
}


def find_regular_item(regular_id: str, *, regulars_path=None, pages: int | None = DEFAULT_PAGES,
                      start_page: int = 1, hits: int = 30,
                      adapter: MarketplaceAdapter | None = None, sleep=None,
                      limits: Limits | None = None,
                      adapters: dict[str, MarketplaceAdapter] | None = None, malls: list[str] | None = None) -> dict:
    if not isinstance(regular_id, str) or not regular_id.strip():
        return _error("invalid_request", "regular_id は文字列で指定する")
    try:
        reg = get_regular(regular_id.strip(), regulars_path)
    except RegularsError as exc:
        msg = _REGULARS_MESSAGES.get(exc.kind, "定番品マスタを読めない。")
        if exc.kind == "invalid_format" and exc.detail:
            msg += f"（{exc.detail}）"
        return _error(f"regulars_{exc.kind}", msg)
    out = _compare_flow(reg.keywords, reg.include_terms or None, reg.exclude_terms or None,
                        reg.desired_quantity, reg.basis, adapter=adapter, pages=pages, start_page=start_page,
                        hits=hits, limits=limits,
                        sleep=sleep, filters={}, known_urls=reg.known_urls, adapters=adapters, malls=malls)
    out["regular"] = _regular_info(reg)
    return out
