"""WP17 U1: Yahoo!ショッピング Adapter（楽天のアダプタ試験 tests/test_rakuten_adapter.py の型）。"""
import copy
import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from fakes import FakeOpener, FakeResponse, http_error, load_fixture
from shopping.adapters.base import AdapterError
from shopping.adapters.yahoo import YahooAdapter, html_to_text, is_item_url, parse_hit
from shopping.config import YAHOO_VAR, load_yahoo_credentials

CLIENT_ID = "FAKECLIENTID_123"
POC_PATH = Path(os.environ.get("YAHOO_POC_RESULTS", r"C:\Claude\501_RakutenSearch\data\yahoo_poc\Yahoo_PoC_Results.json"))


def CLOCK():
    return datetime(2026, 11, 24, 9, 0, 0, tzinfo=timezone(timedelta(hours=9)))


EMPTY = {"totalResultsAvailable": 0, "totalResultsReturned": 0, "firstResultsPosition": 1, "hits": []}


def make(*responses, client_id=CLIENT_ID):
    opener = FakeOpener(*responses)
    return YahooAdapter(client_id, opener=opener, clock=CLOCK), opener


def hit(**over):
    h = copy.deepcopy(load_fixture("yahoo_search.json")["hits"][0])
    h.update(over)
    return h


def test_parses_fixture():
    ad, _ = make(load_fixture("yahoo_search.json"))
    offers, count = ad.search("貼るカイロ")
    assert count == 194 and len(offers) == 8
    o = offers[0]
    assert (o.mall, o.mall_item_code, o.price) == ("yahoo", "irisplaza_h264589", 1680)
    assert o.item_url == "https://store.shopping.yahoo.co.jp/irisplaza/h264589.html" and o.item_url_status == "ok"
    assert o.shop_name == "アイリスプラザ Yahoo!店" and o.shop_code == "irisplaza"
    assert o.jan == "4905009678921" and o.availability is True
    assert o.review_average == 4.62 and o.review_count == 52
    assert o.shipping_status == "included" and o.shipping_fee is None and o.points_rate is None
    assert o.fetched_at == "2026-11-24T09:00:00+09:00"
    assert o.points_amount == 15 and o.condition == "new" and o.shipping_condition is None
    assert offers[6].availability is False
    assert [x.jan is None for x in offers] == [False, False, True, False, True, True, False, False]   # 空文字は None


def test_all_candidates_are_unconfirmed_for_option_prices():
    ad, _ = make(load_fixture("yahoo_search.json"))
    offers, _ = ad.search("x")
    assert all("price_options_unchecked" in o.mall_unconfirmed for o in offers)
    assert all(o.price_min is None and o.price_max is None and o.price_varies is False for o in offers)
    assert all(o.mall_unconfirmed == ["price_options_unchecked"] for o in offers)      # 実応答は taxable=true・condition=new


def test_lohaco_url_is_ok():
    ad, _ = make(load_fixture("yahoo_search.json"))
    offers, _ = ad.search("x")
    assert offers[1].item_url.startswith("https://lohaco.yahoo.co.jp/store/") and offers[1].item_url_status == "ok"


@pytest.mark.parametrize("url,ok", [
    ("https://store.shopping.yahoo.co.jp/seller/item.html", True),
    ("https://store.shopping.yahoo.co.jp/seller/1894684.html", True),
    ("https://lohaco.yahoo.co.jp/store/h-lohaco/item/nw92584/", True),
    ("http://store.shopping.yahoo.co.jp/seller/item.html", False),
    ("https://store.shopping.yahoo.co.jp/seller/", False),
    ("https://store.shopping.yahoo.co.jp/seller/item", False),
    ("https://store.shopping.yahoo.co.jp/seller/.html", False),
    ("https://store.shopping.yahoo.co.jp/seller/a/item.html", False),
    ("https://store.shopping.yahoo.co.jp.evil.example/seller/item.html", False),
    ("https://user:pw@store.shopping.yahoo.co.jp/seller/item.html", False),
    ("https://shopping.yahoo.co.jp/search?p=x", False),
    ("https://lohaco.yahoo.co.jp/store/h-lohaco/", False),
    ("https://lohaco.yahoo.co.jp/store/h-lohaco/item/", False),
    ("https://item.rakuten.co.jp/shop/item/", False),
    ("", False), (None, False), (123, False),
])
def test_is_item_url(url, ok):
    assert is_item_url(url) is ok


def test_search_page_url_is_needs_review_not_dropped():
    url = "https://shopping.yahoo.co.jp/search?p=%E3%82%AB%E3%82%A4%E3%83%AD"
    o = parse_hit(hit(url=url), "t")
    assert o.item_url_status == "needs_review" and o.item_url == url      # 捨てない・作らない・改変しない


@pytest.mark.parametrize("code,status,cond", [
    (2, "included", None), (1, "unknown", None), (3, "unknown", "conditional_free"),
    (0, "unknown", None), (9, "unknown", None), (None, "unknown", None), ("2", "included", None),
])
def test_shipping_code_mapping(code, status, cond):
    h = hit(name="送料無料 たっぷり")
    h["shipping"] = {"code": code, "name": "x"}
    o = parse_hit(h, "t")
    assert (o.shipping_status, o.shipping_condition, o.shipping_fee) == (status, cond, None)


def test_shipping_is_not_decided_by_the_name():
    h = hit(name="【送料無料】カイロ")
    h["shipping"] = {"code": 1, "name": "設定なし"}
    assert parse_hit(h, "t").shipping_status == "unknown"
    h2 = hit(name="カイロ 送料別")
    h2["shipping"] = {"code": 2, "name": "送料無料"}
    assert parse_hit(h2, "t").shipping_status == "included"
    h3 = hit()
    del h3["shipping"]
    assert parse_hit(h3, "t").shipping_status == "unknown"


def test_points_uses_only_limited_store_points():
    h = hit()
    h["point"] = {"amount": 99, "bonusAmount": 98, "premiumAmount": 97, "premiumBonusAmount": 96,
                  "lyLimitedBonusAmount": 15, "lyLimitedPremiumBonusAmount": 95}
    o = parse_hit(h, "t")
    assert o.points_amount == 15 and o.points_rate is None
    h["point"] = {"amount": 99}
    assert parse_hit(h, "t").points_amount is None
    h["point"] = {"lyLimitedBonusAmount": 0}
    assert parse_hit(h, "t").points_amount == 0
    del h["point"]
    assert parse_hit(h, "t").points_amount is None


def test_price_uses_price_not_premium_and_sale_is_reference():
    h = hit(price=1680, premiumPrice=1500)
    h["priceLabel"] = {"taxable": True, "defaultPrice": 1980, "discountedPrice": 1680, "periodEnd": 1769000000}
    o = parse_hit(h, "t")
    assert o.price == 1680
    assert o.sale == {"discounted_price": 1680, "period_end": None}      # periodEnd が文字列でなければ読まない
    h["priceLabel"]["periodEnd"] = "2026-12-01"
    assert parse_hit(h, "t").sale == {"discounted_price": 1680, "period_end": "2026-12-01"}
    h["priceLabel"]["discountedPrice"] = None
    assert parse_hit(h, "t").sale is None
    assert parse_hit(h, "t").price == 1680


@pytest.mark.parametrize("label,reason", [
    ({"taxable": False}, True), ({"taxable": None}, True), ({}, True), ({"taxable": "true"}, True),
    ({"taxable": True}, False),
])
def test_untaxable_price_is_unconfirmed(label, reason):
    h = hit()
    h["priceLabel"] = label
    assert ("price_tax_unknown" in parse_hit(h, "t").mall_unconfirmed) is reason
    assert "price_options_unchecked" in parse_hit(h, "t").mall_unconfirmed


@pytest.mark.parametrize("cond,reason", [("used", True), ("open", True), (None, True), ("new", False)])
def test_used_item_is_unconfirmed_and_exposes_condition(cond, reason):
    o = parse_hit(hit(condition=cond), "t")
    assert ("condition_not_new" in o.mall_unconfirmed) is reason
    assert o.condition == cond


def test_reasons_order_is_stable():
    h = hit(condition="used")
    h["priceLabel"] = {"taxable": False}
    assert parse_hit(h, "t").mall_unconfirmed == ["price_options_unchecked", "price_tax_unknown", "condition_not_new"]


def test_caption_html_to_text_and_headline():
    h = hit(description="サイズ/約3cm<br>内容量/1個<BR/>＜注意＞&amp;&lt;b&gt;太字&lt;/b&gt;<a href=\"x\">リンク</a><br /><br>末尾",
            headLine="見出し")
    o = parse_hit(h, "t")
    assert o.caption == "見出し\nサイズ/約3cm\n内容量/1個\n＜注意＞&<b>太字</b>リンク\n\n末尾"
    assert parse_hit(hit(description="本文<br>2行目", headLine=""), "t").caption == "本文\n2行目"
    assert parse_hit(hit(description=None, headLine="見出しだけ"), "t").caption == "見出しだけ"
    assert parse_hit(hit(description=None, headLine=None), "t").caption is None
    assert parse_hit(hit(description="", headLine=""), "t").caption is None


def test_html_to_text_edges():
    assert html_to_text(None) == "" and html_to_text(5) == ""
    assert html_to_text("a<br>b") == "a\nb"
    assert html_to_text("&yen;1,000&nbsp;円") == "¥1,000\xa0円"


def test_review_and_seller_may_be_missing():
    h = hit()
    for k in ("review", "seller", "janCode", "inStock", "image"):
        h.pop(k, None)
    o = parse_hit(h, "t")
    assert (o.review_average, o.review_count, o.shop_name, o.shop_code, o.jan, o.availability) == (None,) * 6
    h2 = hit()
    h2["review"] = {"count": 3, "rate": None}
    assert parse_hit(h2, "t").review_average is None and parse_hit(h2, "t").review_count == 3


@pytest.mark.parametrize("bad", [None, [], "x", 5, {}, {"code": ""}, {"code": 5}, {"name": "n", "price": 1}])
def test_parse_hit_unreadable_raises_unexpected_response(bad):
    with pytest.raises(AdapterError) as e:
        parse_hit(bad, "t")
    assert e.value.kind == "unexpected_response"


def test_unreadable_hits_are_counted_and_dropped():
    body = load_fixture("yahoo_search.json")
    body["hits"] = body["hits"][:2] + [{"name": "コード無し"}, "x", None] + body["hits"][2:3]
    ad, _ = make(body)
    offers, count = ad.search("x")
    assert len(offers) == 3 and count == 194
    assert offers.skipped == 3 and ad.last_skipped == 3


@pytest.mark.parametrize("body", [
    {"totalResultsAvailable": 0},
    {"hits": []},
    {"totalResultsAvailable": 1, "hits": "notalist"},
    {"totalResultsAvailable": -1, "hits": []},
    {"totalResultsAvailable": "5", "hits": []},
    {"totalResultsAvailable": True, "hits": []},
    {"code": 400, "message": "bad"},
    [],
])
def test_unexpected_shapes(body):
    ad, _ = make(body)
    with pytest.raises(AdapterError) as e:
        ad.search("x")
    assert e.value.kind == "unexpected_response"


def test_response_that_is_not_a_response_object_is_unexpected_response_not_a_crash():
    ad, _ = make("a plain string")           # 応答が response として読めない形でも、アダプタは AdapterError だけを出す
    with pytest.raises(AdapterError) as e:
        ad.search("x")
    assert e.value.kind == "unexpected_response"


@pytest.mark.parametrize("exc,kind", [
    (http_error(400), "bad_request"),
    (http_error(401), "forbidden"),
    (http_error(403), "forbidden"),
    (http_error(429), "rate_limited"),
    (http_error(500), "server_error"),
    (http_error(503), "server_error"),
    (http_error(404), "http_404"),
    (socket.timeout("t"), "timeout"),
    (TimeoutError("t"), "timeout"),
    (URLError("dns SECRET"), "network_error"),
    (URLError(socket.timeout("t")), "timeout"),
    (ConnectionResetError("x"), "network_error"),
])
def test_error_kinds(exc, kind):
    ad, _ = make(exc)
    with pytest.raises(AdapterError) as e:
        ad.search("x")
    assert e.value.kind == kind


@pytest.mark.parametrize("status,kind", [(302, "http_302"), (403, "forbidden"), (500, "server_error")])
def test_non_200_status(status, kind):
    ad, _ = make(FakeResponse(b"{}", status=status))
    with pytest.raises(AdapterError) as e:
        ad.search("x")
    assert e.value.kind == kind


@pytest.mark.parametrize("body", [b"<html>not json", b"\xff\xfe\x00bad", b"<html>500 Internal"])
def test_invalid_json(body):
    ad, _ = make(body)
    with pytest.raises(AdapterError) as e:
        ad.search("x")
    assert e.value.kind == "invalid_json"


def test_missing_and_bad_credentials_make_no_request():
    opener = FakeOpener(EMPTY)
    with pytest.raises(AdapterError) as e:
        YahooAdapter("", opener=opener).search("x")
    assert e.value.kind == "missing_credentials"
    for bad in ("a\r\nX-Evil: 1", "a b", "a\tb", "a\nb"):
        with pytest.raises(AdapterError) as e:
            YahooAdapter(bad, opener=opener).search("x")
        assert e.value.kind == "invalid_credentials"
    assert opener.requests == []


@pytest.mark.parametrize("kw", ["", "   ", "あ" * 50])
def test_invalid_keyword(kw):
    ad, op = make(EMPTY)
    with pytest.raises(AdapterError) as e:
        ad.search(kw)
    assert e.value.kind == "invalid_request" and op.requests == []


def test_request_shape_and_filters():
    ad, op = make(EMPTY)
    ad.search("貼るカイロ 60枚", page=2, min_price=100, max_price=3000, sort="+itemPrice", availability=1)
    req = op.requests[0]
    u = urlsplit(req.full_url)
    q = parse_qs(u.query)
    assert u.scheme == "https" and u.hostname == "shopping.yahooapis.jp"
    assert u.path == "/ShoppingWebService/V3/itemSearch"
    assert q["appid"] == [CLIENT_ID] and q["query"] == ["貼るカイロ 60枚"]
    assert q["results"] == ["50"] and q["start"] == ["51"]
    assert q["sort"] == ["+price"] and q["in_stock"] == ["true"]
    assert q["price_from"] == ["100"] and q["price_to"] == ["3000"]
    assert op.timeouts[0] and op.timeouts[0] > 0


def test_optional_filters_omitted_and_availability_off():
    ad, op = make(EMPTY)
    ad.search("x", availability=0)
    q = parse_qs(urlsplit(op.requests[0].full_url).query)
    assert "price_from" not in q and "price_to" not in q and "in_stock" not in q
    assert q["start"] == ["1"] and q["sort"] == ["-score"]


@pytest.mark.parametrize("sort,expected", [("standard", "-score"), ("+itemPrice", "+price"), ("-itemPrice", "-price"),
                                           ("-reviewCount", "-review_count"), ("+reviewCount", "-score"),
                                           ("+updateTimestamp", "-score"), ("nonsense", "-score")])
def test_sort_mapping(sort, expected):
    ad, op = make(EMPTY)
    ad.search("x", sort=sort)
    assert parse_qs(urlsplit(op.requests[0].full_url).query)["sort"] == [expected]


def test_request_notes_for_unsupported_sort_and_ng_keyword():
    ad = YahooAdapter(CLIENT_ID)
    assert ad.request_notes(sort="standard") == [] and ad.request_notes(sort="-itemPrice") == []
    assert ad.request_notes(sort="+reviewCount") == ["Yahoo はこの並び順に無いため標準順"]
    assert ad.request_notes(ng_keyword="本体") == ["Yahoo は商品名で除外"]
    assert ad.request_notes(ng_keyword="  ") == []


def test_ng_keyword_is_applied_to_names_and_not_sent():
    body = load_fixture("yahoo_search.json")
    ad, op = make(body)
    offers, count = ad.search("x", ng_keyword="ダルトン　 ロハコ 60枚×4")
    q = parse_qs(urlsplit(op.requests[0].full_url).query)
    assert "ng_keyword" not in q and "NGKeyword" not in q and not any("ng" in k.lower() for k in q)
    assert count == 194                     # api_count は API の値のまま
    names = [o.item_name for o in offers]
    assert all("60枚×4" not in n for n in names) and len(names) < 8
    # 全角・半角・大文字小文字を同じ語として扱う
    body2 = copy.deepcopy(body)
    ad2, _ = make(body2)
    all_offers, _ = ad2.search("x")
    target = all_offers[0].item_name
    word = target.split()[0]
    ad3, _ = make(body2)
    kept, _ = ad3.search("x", ng_keyword=word.upper())
    assert all(word.lower() not in n.lower() for n in [o.item_name for o in kept])


@pytest.mark.parametrize("bad", [dict(hits=0), dict(hits=51), dict(page=0), dict(page=20), dict(page=21), dict(page=-1),
                                 dict(hits=True), dict(page=True)])
def test_bad_paging_rejected_without_request(bad):
    ad, op = make(EMPTY)
    with pytest.raises(AdapterError) as e:
        ad.search("x", **bad)
    assert e.value.kind == "invalid_request" and op.requests == []


def test_last_page_is_19_and_starts_at_901():
    ad, op = make(EMPTY)
    ad.search("x", page=19)
    assert parse_qs(urlsplit(op.requests[0].full_url).query)["start"] == ["901"]


def test_adapter_attributes_for_the_binder():
    ad = YahooAdapter(CLIENT_ID)
    assert (ad.mall, ad.label, ad.max_hits, ad.page_size, ad.max_page) == ("yahoo", "Yahoo!ショッピング", 50, 50, 19)
    assert ad.min_interval_sec >= 2.2 and ad.stop_kinds == ("rate_limited", "server_error")
    assert ad.is_item_url("https://store.shopping.yahoo.co.jp/s/i.html") is True
    assert ad.empty_means_end is False and "1000" in ad.ceiling_note


def test_no_secret_in_exceptions_offers_or_repr():
    cases = [http_error(403), http_error(429), http_error(500), socket.timeout("SECRET"),
             URLError("SECRET"), b"SECRET not json"]
    for c in cases:
        ad, _ = make(c)
        with pytest.raises(AdapterError) as e:
            ad.search("x")
        blob = " ".join([str(e.value), repr(e.value), str(e.value.__cause__),
                         str(e.value.__context__ or "")])
        for s in (CLIENT_ID, "SECRET", "shopping.yahooapis", "appid"):
            assert s not in blob
    ad, _ = make(load_fixture("yahoo_search.json"))
    offers, _ = ad.search("x")
    assert CLIENT_ID not in repr(offers) and "appid" not in repr(offers)
    assert CLIENT_ID not in repr(ad) and CLIENT_ID not in str(ad)


def test_credentials_repr_hides_the_value():
    from shopping.config import YahooCredentials
    c = YahooCredentials("SECRETVALUE")
    assert "SECRETVALUE" not in repr(c) and "SECRETVALUE" not in str(c) and c.present
    assert not YahooCredentials("").present


def test_load_yahoo_credentials_order(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    local = tmp_path / ".env.yahoo.local"
    monkeypatch.delenv(YAHOO_VAR, raising=False)
    assert not load_yahoo_credentials(env, local).present
    local.write_text("YAHOO_CLIENT_ID=from_local\n", encoding="utf-8")
    assert load_yahoo_credentials(env, local).client_id == "from_local"
    env.write_text("RAKUTEN_ACCESS_KEY=x\nYAHOO_CLIENT_ID=from_env_file\n", encoding="utf-8")
    assert load_yahoo_credentials(env, local).client_id == "from_env_file"
    monkeypatch.setenv(YAHOO_VAR, " from_environ ")
    assert load_yahoo_credentials(env, local).client_id == "from_environ"


# ---- 録画（実応答 271 件）の読み取り。無ければ skip（git 管理外。環境変数 YAHOO_POC_RESULTS で場所を差し替え可） ----

@pytest.mark.skipif(not POC_PATH.exists(), reason="Yahoo の実応答の録画（data/yahoo_poc）が無い")
def test_recorded_real_responses_all_become_offers():
    runs = json.loads(POC_PATH.read_text(encoding="utf-8"))
    hits = [h for r in runs for h in r["response"]["hits"]]
    assert len(hits) == 271
    offers = [parse_hit(h, "t") for h in hits]                       # 例外 0
    assert len(offers) == 271 and all(o.mall == "yahoo" and o.mall_item_code for o in offers)
    assert sum(o.item_url_status == "ok" for o in offers) + sum(o.item_url_status == "needs_review" for o in offers) == 271
    assert sum(o.item_url_status == "ok" for o in offers) == 271        # lohaco 形式 5 件を含め、実応答の URL は全部商品ページの形
    assert sum("lohaco.yahoo.co.jp" in o.item_url for o in offers) == 5
    ship = {"included": 0, "unknown": 0}
    for h, o in zip(hits, offers):
        ship[o.shipping_status] += 1
        assert (o.shipping_condition == "conditional_free") == (h["shipping"]["code"] == 3)
    assert ship == {"included": 157, "unknown": 95 + 19}               # code 2＝157、1＝95、3＝19
    assert all(o.mall_unconfirmed == ["price_options_unchecked"] for o in offers)   # taxable 全部 true・condition 全部 new
    assert all(o.condition == "new" for o in offers)
    assert sum(1 for o in offers if o.points_amount) == 271              # point は lyLimited* だけ非 0
    assert all("<" not in (o.caption or "") or "<br" not in (o.caption or "").lower() for o in offers)
    assert sum(1 for o in offers if o.jan is None) == sum(1 for h in hits if not h.get("janCode"))


@pytest.mark.skipif(not POC_PATH.exists(), reason="Yahoo の実応答の録画（data/yahoo_poc）が無い")
def test_recorded_titles_are_readable_by_the_existing_quantity_reader():
    from shopping.caption_quantity import read_offer_quantity
    runs = json.loads(POC_PATH.read_text(encoding="utf-8"))
    offers = [parse_hit(h, "t") for r in runs for h in r["response"]["hits"]]
    high = sum(read_offer_quantity(o).confidence == "high" for o in offers)
    assert high > len(offers) * 0.3      # 数量の読み取りは楽天と同じ関数。Yahoo の商品名でも読める（PoC の実測: 132 件中 high 90）
