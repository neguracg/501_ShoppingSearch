# @owns Yahoo!ショッピング 商品検索 API(V3)との通信と応答のOffer化（Yahoo 固有知識）
"""Yahoo!ショッピング 商品検索 API(V3) Adapter。

モール固有の知識（エンドポイント・項目名・送料コード・URL 形式・件数と流量の上限）はここだけに置く。
appid（Client ID）は URL のクエリに入るので、URL・ヘッダー・例外本文・応答本文はログにも例外にも出さない。
リダイレクトは追わない。出典: https://developer.yahoo.co.jp/webapi/shopping/v3/itemsearch.html
"""
from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from ..inputs import fits_limit
from ..models import Offer
from .base import AdapterError, MarketplaceAdapter
from .fields import str_or_none, to_float, to_int
from .http_json import fetch_json

ENDPOINT = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
JST = timezone(timedelta(hours=9))
PAGE_SIZE = 50                 # results の上限（1 ページ＝50 件に固定）
RESULT_CEILING = 1000          # start + results - 1 がこの値までしか返さない（1000 件目まで）
MAX_PAGE = RESULT_CEILING // PAGE_SIZE      # 20
# 1 リクエストごとの間隔。公式の「1 分 30 回」「1 秒 1 回」の厳しい方（2 秒）に余裕を足した値
MIN_INTERVAL_SEC = 2.2

SORT_MAP = {"standard": "-score", "+itemPrice": "+price", "-itemPrice": "-price", "-reviewCount": "-review_count"}

# 商品ページ URL: store.shopping.yahoo.co.jp/<seller>/<item>.html と lohaco.yahoo.co.jp/store/<store>/item/<item>/
_STORE_HOST = "store.shopping.yahoo.co.jp"
_LOHACO_HOST = "lohaco.yahoo.co.jp"


def _now_jst() -> datetime:
    return datetime.now(JST)


def is_item_url(url: object) -> bool:
    """商品固有 URL の形式か（Yahoo ストアの <seller>/<item>.html、または LOHACO の store/<store>/item/<item>/）。"""
    if not isinstance(url, str) or not url:
        return False
    try:
        u = urlsplit(url)
        segs = [p for p in u.path.split("/") if p]
        if u.scheme != "https" or u.username or u.password:
            return False
        if u.hostname == _STORE_HOST:
            return len(segs) == 2 and segs[1].endswith(".html") and len(segs[1]) > len(".html")
        if u.hostname == _LOHACO_HOST:
            return len(segs) == 4 and segs[0] == "store" and segs[2] == "item"
    except (ValueError, TypeError):
        return False
    return False


_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]*>")


def html_to_text(value: object) -> str:
    """説明欄の HTML を文字にする（<br> を改行、他のタグを除去、実体参照を戻す）。"""
    if not isinstance(value, str):
        return ""
    return html.unescape(_TAG.sub("", _BR.sub("\n", value))).strip()


def _caption(hit: dict) -> str | None:
    body = html_to_text(hit.get("description"))
    head = hit.get("headLine")
    head = head.strip() if isinstance(head, str) else ""
    text = "\n".join(x for x in (head, body) if x)
    return text or None


def _status_kind(code: int) -> str:
    """HTTP の状態 → 種別。Yahoo は流量超過でも 403・HTML の 500 を返し得る。"""
    return {400: "bad_request", 401: "forbidden", 403: "forbidden", 429: "rate_limited",
            500: "server_error", 503: "server_error"}.get(code, f"http_{code}")


def parse_hit(hit: object, fetched_at: str) -> Offer:
    """hit 1 件を Offer にする。読めない hit は AdapterError("unexpected_response")。"""
    if not isinstance(hit, dict):
        raise AdapterError("unexpected_response")
    code = hit.get("code")
    if not isinstance(code, str) or not code:
        raise AdapterError("unexpected_response")
    url = hit.get("url")
    name = hit.get("name")
    seller = hit.get("seller") if isinstance(hit.get("seller"), dict) else {}
    review = hit.get("review") if isinstance(hit.get("review"), dict) else {}
    label = hit.get("priceLabel") if isinstance(hit.get("priceLabel"), dict) else {}
    point = hit.get("point") if isinstance(hit.get("point"), dict) else {}
    shipping = hit.get("shipping") if isinstance(hit.get("shipping"), dict) else {}
    ship_code = to_int(shipping.get("code"))
    in_stock = hit.get("inStock")
    condition = str_or_none(hit.get("condition"))
    # 検索 API には楽天の itemPriceMin/Max に当たる項目が無い＝選択肢ごとの価格は確かめていない（全候補が未確定）
    unconfirmed = ["price_options_unchecked"]
    if label.get("taxable") is not True:
        unconfirmed.append("price_tax_unknown")
    if condition != "new":
        unconfirmed.append("condition_not_new")
    discounted = to_int(label.get("discountedPrice"))
    return Offer(
        mall="yahoo",
        mall_item_code=code,
        item_name=name if isinstance(name, str) else "",
        price=to_int(hit.get("price")),
        item_url=url if isinstance(url, str) else "",
        item_url_status="ok" if is_item_url(url) else "needs_review",
        shop_name=str_or_none(seller.get("name")),
        shop_code=str_or_none(seller.get("sellerId")),
        shipping_status="included" if ship_code == 2 else "unknown",   # 名前の文字（「送料無料」）では決めない
        shipping_fee=None,
        availability=in_stock if isinstance(in_stock, bool) else None,
        points_rate=None,
        review_average=to_float(review.get("rate")),
        review_count=to_int(review.get("count")),
        jan=str_or_none(hit.get("janCode")),
        caption=_caption(hit),
        fetched_at=fetched_at,
        mall_unconfirmed=unconfirmed,
        points_amount=to_int(point.get("lyLimitedBonusAmount")),    # ストアポイント（期間限定）。参考値で、総額・単価・最安には使わない
        shipping_condition="conditional_free" if ship_code == 3 else None,
        condition=condition,
        sale=({"discounted_price": discounted, "period_end": str_or_none(label.get("periodEnd"))}
              if discounted else None),
    )


class HitList(list):
    """search の戻り（Offer のリスト）。skipped＝読めずに捨てた hit の件数（注記用）。"""

    skipped: int = 0


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).lower()


class YahooAdapter(MarketplaceAdapter):
    mall = "yahoo"
    label = "Yahoo!ショッピング"
    source = "Yahoo!ショッピング（Yahoo! JAPAN Webサービス）"
    max_hits = PAGE_SIZE
    page_size = PAGE_SIZE
    max_page = MAX_PAGE
    min_interval_sec = MIN_INTERVAL_SEC
    stop_kinds = ("rate_limited", "server_error")       # 流量超過。再試行ループしない
    empty_means_end = False      # ng_keyword で捨てて空になったページを、検索の終わりと取り違えない
    ceiling_note = f"Yahoo は {RESULT_CEILING} 件目まで"
    is_item_url = staticmethod(is_item_url)

    def __init__(self, client_id: str, *, opener=None, clock=None):
        self._client_id = client_id or ""
        self._opener = opener
        self._clock = clock or _now_jst

    def __repr__(self) -> str:
        return "YahooAdapter(client_id=***)"

    def request_notes(self, *, sort: str = "standard", ng_keyword: str | None = None) -> list[str]:
        notes: list[str] = []
        if sort not in SORT_MAP:
            notes.append("Yahoo はこの並び順に無いため標準順")
        if ng_keyword and ng_keyword.strip():
            notes.append("Yahoo は商品名で除外")
        return notes

    def _build_request(self, params: dict) -> Request:
        if not self._client_id:
            raise AdapterError("missing_credentials")
        if any(c in self._client_id for c in "\r\n \t"):
            raise AdapterError("invalid_credentials")
        query = dict(appid=self._client_id)
        query.update(params)
        return Request(ENDPOINT + "?" + urlencode(query), headers={"Accept": "application/json"})

    def search(self, keyword: str, *, page: int = 1, hits: int = PAGE_SIZE,
               ng_keyword: str | None = None, min_price: int | None = None,
               max_price: int | None = None, sort: str = "standard",
               availability: int = 1) -> tuple[list[Offer], int]:
        if not isinstance(keyword, str) or not keyword.strip() or not fits_limit(keyword):
            raise AdapterError("invalid_request")
        if ng_keyword is not None and (not isinstance(ng_keyword, str) or not fits_limit(ng_keyword.strip())):
            raise AdapterError("invalid_request")
        if (isinstance(hits, bool) or not isinstance(hits, int) or not 1 <= hits <= PAGE_SIZE
                or isinstance(page, bool) or not isinstance(page, int) or page < 1):
            raise AdapterError("invalid_request")
        start = (page - 1) * hits + 1
        if start + hits - 1 > RESULT_CEILING:        # Yahoo は 1000 件目までしか返さない。越えるページは呼ばない
            raise AdapterError("invalid_request")
        params: dict = dict(query=keyword, results=hits, start=start, sort=SORT_MAP.get(sort, "-score"))
        if availability == 1:
            params["in_stock"] = "true"
        if min_price is not None:
            params["price_from"] = min_price
        if max_price is not None:
            params["price_to"] = max_price
        req = self._build_request(params)
        data = fetch_json(req, opener=self._opener, kind_for_status=_status_kind)
        offers, count = self._parse_response(data)
        terms = _norm(ng_keyword).split() if ng_keyword else []
        if terms:       # Yahoo に除外語の引数が無いので、商品名に除外語を含む候補はここで捨てる（api_count は API の値のまま）
            offers = _keep_without(offers, terms)
        return offers, count

    def _parse_response(self, data: object) -> tuple[HitList, int]:
        if not isinstance(data, dict) or not isinstance(data.get("hits"), list):
            raise AdapterError("unexpected_response")
        count = data.get("totalResultsAvailable")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise AdapterError("unexpected_response")
        fetched_at = self._clock().isoformat()
        offers = HitList()
        for hit in data["hits"]:
            try:
                offers.append(parse_hit(hit, fetched_at))
            except AdapterError:           # hit 単位で読めない物は数えて捨てる（応答全体の形が違う時だけ unexpected_response）
                offers.skipped += 1
        return offers, count


def _keep_without(offers: HitList, terms: list[str]) -> HitList:
    kept = HitList(o for o in offers if not any(t in _norm(o.item_name) for t in terms))
    kept.skipped = offers.skipped
    return kept
