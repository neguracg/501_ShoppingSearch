# @owns WP10 単価の外れ値（pricing.mark_unit_price_outliers と 3 入口の表示）の自作確認。独立試験（ブラインド）の代わりではない
"""WP10: 単位価格が同じ比較グループの中央値の 1/10 未満の候補を「要確認」にして、単位価格の最安・必要数量を満たす最安から外す。

判定は pricing.py に 1 つだけ。公開Web・公開MCP・CLI は印（unit_price_outlier）を出すだけ。
N=4・K=10 の根拠は SPEC §8 の注（実 API 99 検索・1429 件の実測表）。
"""
import re

import pytest
from fastapi.testclient import TestClient

import cli
from fakes import FakeAdapter, make_offer
from shopping import service
from shopping.guard import Gate, GuardedAdapter, RateLimiter
from shopping.models import Offer, QuantityInfo
from shopping.pricing import (OUTLIER_MIN_GROUP, OUTLIER_NOTE, OUTLIER_RATIO, QUANTITY_CAVEAT,
                              SPEC_CAVEAT, compare)
from shopping.web import create_app


def mk(code, unit, **kw):
    """単位価格がちょうど unit（100ml あたり円）になる候補。量は 100ml・1個の high を直接入れる。"""
    o = make_offer(code, name=f"水 {code}", price=unit, **kw)
    o.quantity = QuantityInfo(count_total=1, content_amount=100.0, content_dimension="volume",
                              content_unit="ml", confidence="high")
    return o


def flagged(offers):
    return sorted(o.mall_item_code for o in offers if o.unit_price_outlier)


def test_constants_are_the_measured_values():
    assert (OUTLIER_MIN_GROUP, OUTLIER_RATIO) == (4, 10)


# --- 判定（N・K・向き） -----------------------------------------------------------

def test_group_smaller_than_n_is_never_flagged():
    offers = [mk("a", 1000), mk("b", 1000), mk("d", 1)]       # 3 件
    r = compare(offers)
    assert flagged(offers) == [] and r.cheapest_unit_price.mall_item_code == "d"
    assert not any("読み違い" in c for c in r.caveats)


def test_group_of_exactly_n_is_judged():
    offers = [mk("a", 1000), mk("b", 1000), mk("c", 1000), mk("e", 99)]   # 4 件
    r = compare(offers)
    assert flagged(offers) == ["e"] and r.cheapest_unit_price.mall_item_code != "e"


def test_only_below_one_tenth_of_median_is_flagged_and_the_boundary_is_not():
    offers = [mk("a", 1000), mk("b", 1000), mk("c", 1000), mk("d", 1000), mk("edge", 100), mk("low", 99)]
    compare(offers)
    assert flagged(offers) == ["low"]            # ちょうど 1/10 は掛けない（< であって <= ではない）


def test_expensive_side_is_not_flagged():
    offers = [mk(c, 1000) for c in "abcde"] + [mk("hi", 1_000_000)]
    compare(offers)
    assert flagged(offers) == []


def test_members_without_unit_price_do_not_count_toward_n():
    offers = [mk("a", 1000), mk("b", 1000), mk("d", 1), make_offer("np", "水 np", price=None)]
    offers[-1].quantity = offers[0].quantity
    r = compare(offers)                           # 単価の出る候補は 3 件（価格不明の 1 件は数えない）
    assert flagged(offers) == [] and r.cheapest_unit_price.mall_item_code == "d"


@pytest.mark.parametrize("prices", [
    [1, 1, 1, 1, 1], [1, 1, 1, 1000, 1000], [1, 2, 3, 4, 5, 6, 7], [5, 5, 1000, 1000, 1000, 1000],
    [1, 1, 1, 1, 1000, 1000, 1000, 1000], [3, 100000, 100000, 100000, 100000],
])
def test_never_everything_is_flagged_so_a_cheapest_always_remains(prices):
    offers = [mk(f"o{i}", p) for i, p in enumerate(prices)]
    r = compare(offers)
    assert len(flagged(offers)) < len(offers)
    assert r.cheapest_unit_price is not None and not r.cheapest_unit_price.unit_price_outlier


# --- 外し方（最安 4 種のうち数量を使う 2 つだけ） ----------------------------------

def _group_with_outlier():
    # d は単価が桁違いに安い（数量の読み違いの疑い）。商品価格は 99 円で一番安い
    base = [mk("a", 1000), mk("b", 1100), mk("c", 1200), mk("e", 1300), mk("f", 1400)]
    d = make_offer("d", name="水 d", price=99, shipping_status="included")
    d.quantity = QuantityInfo(count_total=1, content_amount=100.0 * 100, content_dimension="volume",
                              content_unit="ml", confidence="high")      # 10000ml → 単価 0.99
    for o in base:
        o.shipping_status, o.shipping_fee = "included", None
    return base + [d]


def test_outlier_leaves_unit_price_and_quantity_slots_but_not_price_and_total():
    offers = _group_with_outlier()
    r = compare(offers, desired_quantity=100)
    assert flagged(offers) == ["d"]
    assert r.cheapest_unit_price.mall_item_code == "a"                    # d は外れる
    assert r.cheapest_for_quantity.mall_item_code == "a"                  # d(99円)は数量を満たすが外れる
    assert r.cheapest_price.mall_item_code == "d"                         # 数量を使わない 2 つは変えない
    assert r.cheapest_total.mall_item_code == "d"


def test_outlier_stays_in_the_group_list_with_its_flag_and_original_order():
    r = compare(_group_with_outlier())
    got = r.groups[0].offers
    assert [o.mall_item_code for o in got][0] == "d"                      # 単価の安い順のまま・消さない
    assert got[0].unit_price_outlier is True and all(not o.unit_price_outlier for o in got[1:])


def test_outlier_is_never_the_cheapest_order_but_is_listed_in_to_check():
    # WP14 W2（Q10 の変更）: 同じ商品を n 個買う案になったので、「外れ値だけが満たす」形は無い。外れ値は最安に選ばず to_check に条件つきで出す
    offers = _group_with_outlier()
    r = compare(offers, desired_quantity=5000)
    assert r.cheapest_for_quantity.mall_item_code == "a" and r.cheapest_order.offer.mall_item_code == "a"
    checks = [t for t in r.to_check if t.plan.offer.mall_item_code == "d"]
    assert checks and checks[0].conditions[0]["reason"] == "unit_price_outlier"


def test_flag_is_reset_on_every_compare():
    offers = _group_with_outlier()
    compare(offers)
    assert offers[-1].unit_price_outlier
    compare([o for o in offers if o.mall_item_code in "def"])             # 3 件だけで比べ直す（N 未満）
    assert not offers[-1].unit_price_outlier


# --- caveats の件数行 ---------------------------------------------------------------

def test_caveat_line_has_the_count_and_sits_before_the_two_standing_lines():
    r = compare(_group_with_outlier())
    line = [c for c in r.caveats if "読み違いの疑い" in c]
    assert line == ["単価が他の候補の 1/10 未満で、数量の読み違いの疑いがある候補: 1件"
                    "（単位価格の最安・必要数量を満たす最安から外しています）"]
    assert r.caveats[-2:] == [SPEC_CAVEAT, QUANTITY_CAVEAT]
    assert r.caveats.index(line[0]) < len(r.caveats) - 2


def test_caveat_count_is_the_number_of_flagged_candidates():
    offers = [mk(c, 1000) for c in "abcdefg"] + [mk("x", 5), mk("y", 7)]
    r = compare(offers)
    assert flagged(offers) == ["x", "y"]
    assert any(c.startswith("単価が他の候補の 1/10 未満") and "2件" in c for c in r.caveats)


def test_no_caveat_when_nothing_is_flagged():
    r = compare([mk(c, 1000 + i) for i, c in enumerate("abcdef")])
    assert not any("読み違い" in c for c in r.caveats)


# --- 実題名の形（R7）で網に掛かる ------------------------------------------------------

def test_r7_chain_form_is_caught_by_the_net():
    names = [("w1", "ミネラルウォーター 500ml×24本", 1500), ("w2", "ミネラルウォーター 2L×6本", 1100),
             ("w3", "天然水 2L×9本", 1500), ("w4", "天然水 500ml×48本", 2600),
             ("w5", "ミネラルウォーター 1L×12本", 1300),
             ("bad", "水 ICBK80L 80L×2個", 1500)]            # R7: 型番内の 80L が鎖の一部で現れる（量は 160,000ml と読まれる）
    offers = [make_offer(c, n, p) for c, n, p in names]
    r = compare(offers)
    bad = next(o for o in offers if o.mall_item_code == "bad")
    assert bad.quantity.confidence == "high" and bad.quantity.measure_total == 160000.0   # 規則では塞げない形
    assert bad.unit_price_outlier and r.cheapest_unit_price.mall_item_code != "bad"


# --- service の返却（3 入口が使う形） ---------------------------------------------------

def test_offer_dict_carries_the_flag_for_every_offer():
    offers = _group_with_outlier()
    c = service._comparison_to_dict(compare(offers))
    flags = {o["item_code"]: o["unit_price_outlier"] for o in c["groups"][0]["offers"]}
    assert flags == {"d": True, "a": False, "b": False, "c": False, "e": False, "f": False}
    assert c["cheapest_unit_price"]["unit_price_outlier"] is False
    assert c["cheapest_price"]["unit_price_outlier"] is True              # 商品価格最安には印が付いて見える
    assert service.offer_to_dict(make_offer("z"))["unit_price_outlier"] is False   # 一覧（search）の候補は False


# --- 3 入口（公開Web・CLI・公開MCP）。同じ品揃えで印と caveats が出る ----------------------

def water_pages():
    offers = [make_offer("w1", "ミネラルウォーター 500ml×24本", 1500, shipping_status="included"),
              make_offer("w2", "ミネラルウォーター 2L×6本", 1100, shipping_status="included"),
              make_offer("w3", "天然水 2L×9本", 1500, shipping_status="included"),
              make_offer("w4", "天然水 500ml×48本", 2600, shipping_status="included"),
              make_offer("w5", "ミネラルウォーター 1L×12本", 1300, shipping_status="included"),
              make_offer("bad", "水 ICBK80L 80L×2個", 1500, shipping_status="included")]
    return {("水", 1): (offers, len(offers))}


SECRET_ID, SECRET_KEY = "APPID-SECRET-1234567890", "ACCESSKEY-SECRET-abcdef"
CAVEAT_PART = "単価が他の候補の 1/10 未満で、数量の読み違いの疑いがある候補: 1件"


@pytest.fixture
def _env(monkeypatch):
    monkeypatch.setenv("RAKUTEN_APPLICATION_ID", SECRET_ID)
    monkeypatch.setenv("RAKUTEN_ACCESS_KEY", SECRET_KEY)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.negura.website/kaimono")
    monkeypatch.delenv("SHOPPING_MOCK", raising=False)


def make_app(adapter):
    t = [1000.0]

    def clock():
        return t[0]

    def sleep(s):
        t[0] += s
    gate = Gate(GuardedAdapter(adapter, clock=clock, sleep=sleep), RateLimiter(limit=1000, clock=clock))
    return create_app("/kaimono", gate)


def test_web_compare_shows_the_mark_on_the_card_and_the_caveat(_env):
    c = TestClient(make_app(FakeAdapter(water_pages())), raise_server_exceptions=False)
    html = c.get("/kaimono/compare?q=水").text
    assert html.count("要確認: " + OUTLIER_NOTE) == 1                       # 外れ値のカード 1 枚だけ
    assert CAVEAT_PART in html
    card = html[html.index("水 ICBK80L 80L×2個") - 200:html.index("水 ICBK80L 80L×2個") + 900]
    assert "要確認" in card
    # 単価最安の欄は外れ値ではない候補（★の下のカードに bad が来ない）
    best = html[html.index("の単価が最安"):html.index("支払総額が最安")]
    assert "ICBK80L" not in best and "要確認" not in best


def test_web_without_outlier_has_no_mark(_env):
    pages = water_pages()
    pages[("水", 1)] = (pages[("水", 1)][0][:5], 5)
    c = TestClient(make_app(FakeAdapter(pages)), raise_server_exceptions=False)
    html = c.get("/kaimono/compare?q=水").text
    assert "要確認:" not in html and "読み違いの疑い" not in html


def test_cli_compare_shows_the_mark_and_the_caveat(monkeypatch, capsys):
    monkeypatch.setattr(service, "make_adapter", lambda *a, **k: FakeAdapter(water_pages()))
    assert cli.run(["compare", "水", "--pages", "1"]) == 0
    out = capsys.readouterr().out
    assert out.count("※要確認: " + OUTLIER_NOTE) == 1
    assert "  - " + CAVEAT_PART in out
    star = [ln for ln in out.splitlines() if ln.startswith("★ 単位価格が最安")][0]
    assert "ICBK80L" not in star
    assert "ICBK80L" not in out.split("★ 商品価格が最安")[1].split("★ 単位価格が最安")[1]


def test_cli_json_has_the_flag(monkeypatch, capsys):
    import json
    monkeypatch.setattr(service, "make_adapter", lambda *a, **k: FakeAdapter(water_pages()))
    assert cli.run(["compare", "水", "--pages", "1", "--json"]) == 0
    c = json.loads(capsys.readouterr().out)["comparison"]
    assert [o["item_code"] for o in c["groups"][0]["offers"] if o["unit_price_outlier"]] == ["bad"]


def _rpc(tc, args):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "compare_offers", "arguments": args}}
    r = tc.post("/kaimono/mcp", json=body, headers={"Accept": "application/json, text/event-stream",
                                                    "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    return r.json()["result"]["structuredContent"]


def test_public_mcp_returns_the_flag_and_caveat_and_describes_it(_env):
    with TestClient(make_app(FakeAdapter(water_pages()))) as tc:
        d = _rpc(tc, {"keywords": ["水"], "pages": 1})
        lst = tc.post("/kaimono/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                      headers={"Accept": "application/json, text/event-stream",
                               "Content-Type": "application/json"}).json()["result"]["tools"]
    c = d["comparison"]
    assert [o["item_code"] for o in c["groups"][0]["offers"] if o["unit_price_outlier"]] == ["bad"]
    assert c["cheapest_unit_price"]["item_code"] != "bad"
    assert any(CAVEAT_PART in x for x in c["caveats"])
    desc = next(t["description"] for t in lst if t["name"] == "compare_offers")
    assert "unit_price_outlier" in desc and "1/10" in desc and "商品ページ" in desc


def test_stdio_tool_description_also_explains_the_flag():
    import asyncio
    from mcp import Client
    from shopping.mcp_server import build_server

    async def go():
        async with Client(build_server()) as c:
            return await c.list_tools()
    tools = asyncio.run(asyncio.wait_for(go(), timeout=30)).tools
    desc = next(t.description for t in tools if t.name == "compare_offers")
    assert "unit_price_outlier" in desc
