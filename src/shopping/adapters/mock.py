# @owns SHOPPING_MOCK 用の架空データ Adapter（API を呼ばない）
"""モック Adapter。src/shopping/mock_data.json（架空データ）を楽天の応答形のまま読み、
本物と同じ parse_item で Offer にする。tests/fixtures とは別物。"""
from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from pathlib import Path

from ..models import Offer
from .base import AdapterError, MarketplaceAdapter
from .rakuten import JST, RakutenAdapter, is_item_url as rakuten_is_item_url, parse_item
from .yahoo import PAGE_SIZE as YAHOO_PAGE_SIZE, YahooAdapter, parse_hit

MOCK_DATA_PATH = Path(__file__).resolve().parent.parent / "mock_data.json"


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).lower()


class MockAdapter(MarketplaceAdapter):
    mall = "rakuten"
    is_mock = True
    label = RakutenAdapter.label
    short_label = RakutenAdapter.short_label
    source = RakutenAdapter.source
    is_item_url = staticmethod(rakuten_is_item_url)

    def __init__(self, data_path: Path | str | None = None, clock=None):
        self.default_data = data_path is None        # 既定の架空データ（モック運用）なら、他のモールのモックも並べる（malls.default_adapters）
        self._path = Path(data_path) if data_path else MOCK_DATA_PATH
        self._clock = clock or (lambda: datetime.now(JST))
        self.calls = 0

    def search(self, keyword: str, *, page: int = 1, hits: int = 30,
               ng_keyword: str | None = None, min_price: int | None = None,
               max_price: int | None = None, sort: str = "standard",
               availability: int = 1) -> tuple[list[Offer], int]:
        if not isinstance(keyword, str) or not keyword.strip():
            raise AdapterError("invalid_request")
        if not (1 <= hits <= 30) or page < 1:    # 本物（rakuten.py）と同じ検査。hits 1〜30 は楽天の仕様
            raise AdapterError("invalid_request")
        self.calls += 1
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise AdapterError("unexpected_response") from None
        terms = _norm(keyword).split()
        ng_terms = _norm(ng_keyword).split() if ng_keyword else []
        matched = []
        for item in data.get("Items", []):
            name = _norm(item.get("itemName", ""))
            if not all(t in name for t in terms):
                continue
            if any(t in name for t in ng_terms):
                continue
            price = item.get("itemPrice")
            if min_price is not None and (price is None or price < min_price):
                continue
            if max_price is not None and (price is None or price > max_price):
                continue
            if availability == 1 and item.get("availability") == 0:
                continue
            matched.append(item)
        if sort == "+itemPrice":
            matched.sort(key=lambda i: i.get("itemPrice", 0))
        elif sort == "-itemPrice":
            matched.sort(key=lambda i: -i.get("itemPrice", 0))
        start = (page - 1) * hits
        fetched_at = self._clock().isoformat()
        offers = [parse_item(i, fetched_at) for i in matched[start:start + hits]]
        return offers, len(matched)


class MockYahooAdapter(YahooAdapter):
    """Yahoo のモック。mock_data.json の YahooHits（Yahoo の応答の形の架空データ）を本物と同じ parse_hit で Offer にする。API を呼ばない。"""
    is_mock = True

    def __init__(self, data_path: Path | str | None = None, clock=None):
        super().__init__("mock", clock=clock or (lambda: datetime.now(JST)))
        self._path = Path(data_path) if data_path else MOCK_DATA_PATH
        self.calls = 0

    def __repr__(self) -> str:
        return "MockYahooAdapter()"

    def search(self, keyword: str, *, page: int = 1, hits: int = YAHOO_PAGE_SIZE,
               ng_keyword: str | None = None, min_price: int | None = None,
               max_price: int | None = None, sort: str = "standard",
               availability: int = 1) -> tuple[list[Offer], int]:
        if not isinstance(keyword, str) or not keyword.strip():
            raise AdapterError("invalid_request")
        if not (1 <= hits <= self.max_hits) or not (1 <= page <= self.max_page):      # 本物（yahoo.py）と同じ範囲
            raise AdapterError("invalid_request")
        self.calls += 1
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise AdapterError("unexpected_response") from None
        terms = _norm(keyword).split()
        ng_terms = _norm(ng_keyword).split() if ng_keyword else []
        matched = []
        for hit in data.get("YahooHits", []):
            name = _norm(hit.get("name", ""))
            if not all(t in name for t in terms):
                continue
            price = hit.get("price")
            if min_price is not None and (price is None or price < min_price):
                continue
            if max_price is not None and (price is None or price > max_price):
                continue
            if availability == 1 and hit.get("inStock") is False:
                continue
            matched.append(hit)
        if sort == "+itemPrice":
            matched.sort(key=lambda h: h.get("price", 0))
        elif sort == "-itemPrice":
            matched.sort(key=lambda h: -h.get("price", 0))
        start = (page - 1) * hits
        fetched_at = self._clock().isoformat()
        offers = [parse_hit(h, fetched_at) for h in matched[start:start + hits]]
        if ng_terms:
            offers = [o for o in offers if not any(t in _norm(o.item_name) for t in ng_terms)]
        return offers, len(matched)
