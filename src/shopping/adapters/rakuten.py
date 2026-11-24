# @owns 楽天市場APIとの通信と応答のOffer化（モール固有知識）
"""楽天市場 商品検索 API Adapter。

モール固有の知識（エンドポイント・項目名・送料フラグ・URL 形式）はここだけに置く。
URL・ヘッダー・例外本文・応答本文はログにも例外にも出さない（preflight.py の作法）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from ..inputs import MAX_HITS, MAX_PAGES, fits_limit
from ..models import Offer
from .base import AdapterError, MarketplaceAdapter
from .fields import str_or_none as _str_or_none, to_float as _to_float, to_int as _to_int    # 従来の名前でも引ける
from .http_json import MAX_RESPONSE_BYTES, TIMEOUT_SEC, NoRedirect as _NoRedirect, fetch_json  # noqa: F401  (従来の名前でも引ける)

ENDPOINT = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
JST = timezone(timedelta(hours=9))


def _now_jst() -> datetime:
    return datetime.now(JST)


def is_item_url(url: object) -> bool:
    """商品固有 URL（https://item.rakuten.co.jp/<shop>/<item>/）の形式か。"""
    if not isinstance(url, str) or not url:
        return False
    try:
        u = urlsplit(url)
        segments = [p for p in u.path.split("/") if p]
        return (u.scheme == "https" and u.hostname == "item.rakuten.co.jp"
                and len(segments) >= 2 and not u.username and not u.password)
    except (ValueError, TypeError):
        return False


def _price_range(item: dict) -> tuple[int | None, int | None]:
    """選択肢の価格幅（itemPriceMin/Max。WP14 W1）。3 → 1 → 2 の順（指示書 WP14 W1）で、min と max が揃って読める組を採る。"""
    for n in (3, 1, 2):
        lo, hi = _to_int(item.get(f"itemPriceMin{n}")), _to_int(item.get(f"itemPriceMax{n}"))
        if lo is not None and hi is not None:
            return lo, hi
    return None, None


def parse_item(item: object, fetched_at: str) -> Offer:
    """formatVersion=2 の平らな item dict を Offer にする。"""
    if not isinstance(item, dict):
        raise AdapterError("unexpected_response")
    code = item.get("itemCode")
    if not isinstance(code, str) or not code:
        raise AdapterError("unexpected_response")
    url = item.get("itemUrl")
    postage = _to_int(item.get("postageFlag"))
    shipping_status = {0: "included", 1: "separate"}.get(postage, "unknown")
    avail = _to_int(item.get("availability"))
    caption = item.get("itemCaption")
    name = item.get("itemName")
    price_min, price_max = _price_range(item)
    asuraku = _to_int(item.get("asurakuFlag"))
    return Offer(
        mall="rakuten",
        mall_item_code=code,
        item_name=name if isinstance(name, str) else "",
        price=_to_int(item.get("itemPrice")),
        item_url=url if isinstance(url, str) else "",
        item_url_status="ok" if is_item_url(url) else "needs_review",
        shop_name=_str_or_none(item.get("shopName")),
        shop_code=_str_or_none(item.get("shopCode")),
        shipping_status=shipping_status,
        shipping_fee=None,  # 検索 API からは実額が得られない
        availability={0: False, 1: True}.get(avail) if avail is not None else None,
        points_rate=_to_int(item.get("pointRate")),
        review_average=_to_float(item.get("reviewAverage")),
        review_count=_to_int(item.get("reviewCount")),
        jan=_str_or_none(item.get("janCode")),
        model_number=_str_or_none(item.get("productCode")),
        caption=caption if isinstance(caption, str) else None,
        fetched_at=fetched_at,
        price_min=price_min, price_max=price_max,
        asuraku_flag={0: False, 1: True}.get(asuraku) if asuraku is not None else None,
        asuraku_closing_time=_str_or_none(item.get("asurakuClosingTime")),
    )


class RakutenAdapter(MarketplaceAdapter):
    mall = "rakuten"
    label = "楽天市場"
    source = "楽天市場（楽天ウェブサービス）"
    max_hits = MAX_HITS              # 出典: 楽天 IchibaItem Search 仕様（hits 1〜30）
    max_page = MAX_PAGES             # 出典: 同（page 1〜100）
    min_interval_sec = 1.0           # 出典: 楽天ウェブサービスの 1 秒 1 リクエスト
    is_item_url = staticmethod(is_item_url)

    def __init__(self, app_id: str, access_key: str, opener=None, clock=None):
        self._app_id = app_id or ""
        self._access_key = access_key or ""
        self._opener = opener
        self._clock = clock or _now_jst

    def __repr__(self) -> str:
        return "RakutenAdapter(credentials=***)"

    def _build_request(self, params: dict) -> Request:
        if not self._app_id or not self._access_key:
            raise AdapterError("missing_credentials")
        if any(c in self._app_id + self._access_key for c in "\r\n"):
            raise AdapterError("invalid_credentials")
        query = dict(applicationId=self._app_id, format="json", formatVersion=2)
        query.update(params)
        return Request(ENDPOINT + "?" + urlencode(query),
                       headers={"accessKey": self._access_key, "Accept": "application/json"})

    def search(self, keyword: str, *, page: int = 1, hits: int = 30,
               ng_keyword: str | None = None, min_price: int | None = None,
               max_price: int | None = None, sort: str = "standard",
               availability: int = 1) -> tuple[list[Offer], int]:
        # 長さの判定は公開面の入力検査（Gate）と同じ関数（inputs.fits_limit。UTF-8 で 128 バイト以内）
        if not isinstance(keyword, str) or not keyword.strip() or not fits_limit(keyword):
            raise AdapterError("invalid_request")
        if ng_keyword is not None and (not isinstance(ng_keyword, str) or not fits_limit(ng_keyword.strip())):
            raise AdapterError("invalid_request")
        if not (1 <= hits <= self.max_hits) or page < 1:    # hits 1〜30 は楽天 IchibaItem Search の仕様（出典: 楽天ウェブサービス API 仕様）
            raise AdapterError("invalid_request")
        params: dict = dict(keyword=keyword, hits=hits, page=page, sort=sort,
                            availability=availability)
        if ng_keyword:
            params["NGKeyword"] = ng_keyword
        if min_price is not None:
            params["minPrice"] = min_price
        if max_price is not None:
            params["maxPrice"] = max_price
        req = self._build_request(params)
        data = self._fetch_json(req)
        return self._parse_response(data)

    def _fetch_json(self, req: Request) -> object:
        return fetch_json(req, opener=self._opener, timeout=TIMEOUT_SEC, max_bytes=MAX_RESPONSE_BYTES)

    def _parse_response(self, data: object) -> tuple[list[Offer], int]:
        if not isinstance(data, dict) or "error" in data:
            raise AdapterError("unexpected_response")
        present = [k for k in ("items", "Items") if k in data]
        if len(present) != 1 or not isinstance(data[present[0]], list):
            raise AdapterError("unexpected_response")
        count = data.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise AdapterError("unexpected_response")
        fetched_at = self._clock().isoformat()
        offers = [parse_item(item, fetched_at) for item in data[present[0]]]
        return offers, count
