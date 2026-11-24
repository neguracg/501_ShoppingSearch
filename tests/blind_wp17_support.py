# @owns WP17 ブラインド試験の共通部品（fixture の読み込み・Yahoo 用の偽 Adapter・候補の組み立て・秘密が出ない事の検査）
"""test_blind_wp17.py（アダプタ）と test_blind_wp17_compare.py（比較・malls・一貫）が共有する部品。試験は含まない。"""
from __future__ import annotations

import copy
import io
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from fakes import FakeAdapter, FakeOpener, load_fixture, make_offer
from shopping import service
from shopping.adapters.yahoo import YahooAdapter, parse_hit
from shopping.models import Offer

NOSLEEP = lambda s: None  # noqa: E731

SECRET = "TESTAPPID-s3cr3t-zz9"          # 試験用の Client ID（出力のどこにも出てはいけない値）
ENDPOINT = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
FETCHED = "2026-11-24T10:00:00+09:00"
FIXTURE = "blind_wp17_yahoo_search.json"


# --------------------------------------------------------------------------
# 部品
# --------------------------------------------------------------------------

def _resp() -> dict:
    return load_fixture(FIXTURE)


def _set(d: dict, path: str, value) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        d = d[k]
    d[keys[-1]] = value


def _hit(i: int = 0, **over) -> dict:
    """実応答（fixture）の i 番目の hit を写し、"a.b" 形式のキーで上書きする。"""
    h = copy.deepcopy(_resp()["hits"][i])
    for path, v in over.items():
        _set(h, path.replace("__", "."), v)
    return h


def _parse(h: dict) -> Offer:
    return parse_hit(h, FETCHED)


class YahooFake(FakeAdapter):
    """service に渡す Yahoo 用の偽 Adapter（FakeAdapter と同じ記録・同じ pages の形。mall だけ yahoo）。
    モールごとの設定（指示書 方針1・C1 の属性名）は契約の値を置く。"""
    mall = "yahoo"
    label = "Yahoo!ショッピング"
    max_hits = 50
    max_page = 20
    min_interval_sec = 0.0
    credit = "Webサービス by Yahoo! JAPAN （https://developer.yahoo.co.jp/sitemap/）"


def _yoffer(code, name, price, ship="included", unconf=("price_options_unchecked",), **kw) -> Offer:
    """parse_hit が作るのと同じ形の Yahoo の候補（mall_unconfirmed に price_options_unchecked）。"""
    return Offer(mall="yahoo", mall_item_code=code, item_name=name, price=price,
                 item_url=f"https://store.shopping.yahoo.co.jp/ys/{code}.html", item_url_status="ok",
                 shipping_status=ship, mall_unconfirmed=list(unconf), **kw)


def _rof(code, name, price, **kw) -> Offer:
    return make_offer(code, name, price, shipping_status="included", **kw)


def _adapters(rak_offers, yah_offers, kw="aa"):
    rak = FakeAdapter({(kw, 1): (rak_offers, len(rak_offers))})
    yah = YahooFake({(kw, 1): (yah_offers, len(yah_offers))})
    return rak, yah


def _cmp(rak_offers, yah_offers, *, malls=None, **kw):
    rak, yah = _adapters(rak_offers, yah_offers)
    kw.setdefault("desired_quantity", 60)
    kw.setdefault("basis", "個")
    r = service.compare_offers(["aa"], adapters={"rakuten": rak, "yahoo": yah}, malls=malls,
                               sleep=NOSLEEP, **kw)
    return r, rak, yah


def _baseline(rak_offers, **kw):
    """楽天だけ（既存の adapter= の経路）。"""
    kw.setdefault("desired_quantity", 60)
    kw.setdefault("basis", "個")
    rak = FakeAdapter({("aa", 1): (rak_offers, len(rak_offers))})
    return service.compare_offers(["aa"], adapter=rak, sleep=NOSLEEP, **kw)


def _offers_of(c) -> list[dict]:
    return [o for g in c["groups"] for o in g["offers"]] + list(c["unknown_offers"])


def _o(c, code) -> dict:
    for o in _offers_of(c):
        if o["item_code"] == code:
            return o
    raise AssertionError(f"{code!r} が候補に無い: {[o['item_code'] for o in _offers_of(c)]}")


def _plan(c, code) -> dict:
    for p in c["order_plans"]:
        if p["item_code"] == code:
            return p
    raise AssertionError(f"{code!r} が注文案に無い: {[p['item_code'] for p in c['order_plans']]}")


def _tc(c, code):
    for t in c["to_check"]:
        if t["item_code"] == code:
            return t
    return None


def _codes(items) -> set:
    return {x["item_code"] for x in items}


def _walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


def _chain(exc):
    seen, e = [], exc
    while e is not None and all(e is not s for s in seen):
        seen.append(e)
        e = e.__cause__ or e.__context__
    return seen


def _no_leak(exc) -> None:
    """例外とその連鎖の str・repr・args に、appid の値・URL が無い（Y6）。"""
    texts = []
    for e in _chain(exc):
        texts += [str(e), repr(e)] + [str(a) for a in e.args]
    for t in texts:
        assert SECRET not in t, t
        assert "yahooapis" not in t, t
        assert "appid" not in t.lower(), t


def _http_err(code: int, body: bytes = b"") -> HTTPError:
    url = f"{ENDPOINT}?appid={SECRET}&query=x"
    return HTTPError(url, code, "msg " + SECRET, {}, io.BytesIO(body or (b"<html>body " + SECRET.encode() + b"</html>")))


def _adapter(*responses, client_id=SECRET) -> tuple[YahooAdapter, FakeOpener]:
    op = FakeOpener(*responses)
    return YahooAdapter(client_id, opener=op), op


def _query(req) -> dict:
    return parse_qs(urlsplit(req.full_url).query)


