# @owns WP18 上位の見取り図（comparison.shortlist）と結果のキー順（結論が先・件数の多い一覧が後）の自作確認。独立試験（ブラインド）の代わりではない
"""WP18（SPEC §8 Q25）: 確認済みの最安と並べて、確認済みでないが安くなり得る候補をモールを問わず上位に出す。
確認済みの判定・cheapest_order の選び方・to_check の並びと条件は変えない（回帰）。キー順は件数の多い一覧を最後へ。
価格・題名は 2026-11-24 の実 API（貼るカイロ 60枚）の形。"""
import json

import pytest
from fastapi.testclient import TestClient

from fakes import FakeAdapter, make_offer, yoffer
from shopping import service
from shopping.pricing import compare
from shopping.quantity import parse_quantity
from test_mcp_http import data, make_app, rpc


def q(o):
    o.quantity = parse_quantity(o.item_name)
    return o


def rk(code, name, price, **kw):
    return q(make_offer(code, name=name, price=price, shipping_status=kw.pop("ship", "included"), **kw))


def yh(code, name, price, **kw):
    return q(yoffer(code, name=name, price=price, shipping_status=kw.pop("ship", "included"), **kw))


def market():
    """楽天の確認済み 1610 円と、それより安い Yahoo 3 件（選択肢別の価格が未確認）・楽天の価格幅あり 1 件・高い Yahoo 1 件。"""
    return [rk("bc", "貼るカイロ 60枚 ミニ 使い捨て", 1610),
            yh("ie", "貼るカイロ 60枚 ミニ イエプロ", 1380),
            yh("ue", "貼るカイロ 60枚 ミニ ウエノ電器", 1380),
            yh("viva", "貼るカイロ 60枚 ビバホーム", 1362, ship="unknown"),
            rk("unidy", "貼るカイロ 60枚 ゆにでのこづち", 1500, price_min=1500, price_max=1720),
            yh("high", "貼るカイロ 60枚 高い店", 2400)]


def cmp_dict(offers, **kw):
    kw.setdefault("desired_quantity", 60)
    kw.setdefault("desired_quantity_max", 100)
    kw.setdefault("basis", "枚")
    return service._comparison_to_dict(compare(offers, **kw))


def test_shortlist_puts_cheaper_unconfirmed_yahoo_next_to_confirmed_rakuten():
    c = cmp_dict(market())
    sl = c["shortlist"]
    assert c["cheapest_order"]["item_code"] == "bc" and sl["confirmed_cheapest"]["mall"] == "rakuten"
    assert sl["confirmed_cheapest"]["order_total"] == 1610 and sl["confirmed_cheapest"]["payment_total"] == 1610
    cands = sl["unconfirmed_candidates"]
    assert {x["mall"] for x in cands} >= {"yahoo"}                        # モールを問わず（Yahoo が埋もれない）
    ycands = [x for x in cands if x["mall"] == "yahoo"]
    assert ycands and all(x["order_total"] < 1610 for x in cands)          # 確認済みの最安より安い物だけ
    top = ycands[0]                                                        # 観測価格・仮単価・理由・逆転条件が揃う
    assert top["price"] == 1362 or top["price"] == 1380
    assert top["provisional_order_unit_price"] == pytest.approx(top["order_total"] / 60)
    assert "price_options_unchecked" in top["unconfirmed_reasons"]
    assert top["conditions"] and all(isinstance(c["text"], str) and c["text"] for c in top["conditions"])
    assert top["order_total_kind"] in ("unconfirmed_total", "item_subtotal")


def test_shortlist_is_a_copy_of_to_check_head_and_discards_nothing():
    c = cmp_dict(market())
    tc, sl = c["to_check"], c["shortlist"]
    assert sl["unconfirmed_count"] == len(tc) >= 4
    assert [x["name"] for x in sl["unconfirmed_candidates"]] == [t["name"] for t in tc[:5]]     # 並びは to_check のまま
    for x, t in zip(sl["unconfirmed_candidates"], tc):
        assert x["order_total"] == t["order_total"] and x["unconfirmed_reasons"] == t["unconfirmed_reasons"]
        assert x == t                                                        # 全キーそのまま（conditions も同じ）
    # 候補は捨てない: shortlist に出ない分も to_check・groups に全部ある
    assert {o["item_code"] for g in c["groups"] for o in g["offers"]} == {"bc", "ie", "ue", "viva", "unidy", "high"}


def test_shortlist_is_limited_to_top_five_but_counts_all():
    offers = [rk("bc", "貼るカイロ 60枚 ミニ", 1610)] + [yh(f"y{i}", f"貼るカイロ 60枚 店{i}", 1000 + i) for i in range(9)]
    sl = cmp_dict(offers)["shortlist"]
    assert len(sl["unconfirmed_candidates"]) == service.SHORTLIST_TOP == 5
    assert sl["unconfirmed_count"] == 9
    totals = [x["order_total"] for x in sl["unconfirmed_candidates"]]
    assert totals == sorted(totals)


def test_shortlist_without_confirmed_has_null_best_and_lists_unconfirmed():
    offers = [yh("a", "貼るカイロ 60枚 A", 1380), yh("b", "貼るカイロ 60枚 B", 1500)]
    c = cmp_dict(offers)
    assert c["cheapest_order"] is None and c["shortlist"]["confirmed_cheapest"] is None
    assert [x["item_code"] for x in c["shortlist"]["unconfirmed_candidates"]] == ["a", "b"]


def test_shortlist_is_null_when_no_desired_quantity_so_unit_price_mode_is_unchanged():
    c = cmp_dict(market(), desired_quantity=None, desired_quantity_max=None)
    assert c["shortlist"] is None and c["to_check"] == [] and c["cheapest_order"] is None


def test_no_judgement_changed_confirmed_and_cheapest_are_the_same_as_before():
    """確認済みの判定・最安の選び方（回帰）: Yahoo は全件未確認なので、安くても cheapest_order・cheapest_unit_price に選ばれない。"""
    c = cmp_dict(market())
    assert c["cheapest_order"]["item_code"] == "bc" and c["cheapest_unit_price"]["item_code"] == "bc"
    assert c["cheapest_for_quantity"]["item_code"] == "bc"
    for p in c["order_plans"]:
        if p["mall"] == "yahoo":
            assert p["confirmed"] is False and p["payment_total"] is None and p["order_unit_price"] is None
    # 並べるだけ: shortlist の各候補は未確認で、確認済みにならない
    assert all("price_options_unchecked" in x["unconfirmed_reasons"] or "price_varies" in x["unconfirmed_reasons"]
               for x in c["shortlist"]["unconfirmed_candidates"])


def test_comparison_keys_put_conclusions_before_bulk_lists():
    keys = list(cmp_dict(market()))
    for first in ("cheapest_order", "shortlist", "caveats", "notes"):
        for bulk in ("to_check", "order_plans", "groups", "unknown_offers"):
            assert keys.index(first) < keys.index(bulk), (first, bulk)
    assert keys.index("groups") < keys.index("unknown_offers")
    assert set(keys) == {"basis", "basis_label", "main_count_unit", "cheapest_price", "cheapest_unit_price", "cheapest_total",
                         "cheapest_for_quantity", "cheapest_order", "shortlist", "caveats", "notes", "to_check",
                         "order_plans", "groups", "unknown_count", "unknown_offers"}      # 追加は shortlist だけ・消したキーは無い


def test_bulk_last_moves_only_bulk_keys_and_keeps_other_order():
    out = service.bulk_last({"ok": True, "comparison": {"x": 1}, "notes": ["n"], "credits": [1], "offers": [1], "z": 0})
    assert list(out) == ["ok", "notes", "credits", "z", "comparison", "offers"]
    assert out["comparison"] == {"x": 1}


def test_service_compare_result_has_notes_and_stats_before_comparison():
    ad = FakeAdapter({("貼るカイロ", 1): (market(), 6)})
    r = service.compare_offers(["貼るカイロ"], desired_quantity=60, desired_quantity_max=100, basis="枚",
                               adapter=ad, pages=1, sleep=lambda s: None)
    keys = list(r)
    assert keys[-1] == "comparison" and keys.index("notes") < keys.index("comparison") and keys.index("stats") < keys.index("comparison")
    assert r["comparison"]["shortlist"]["confirmed_cheapest"]["item_code"] == "bc"


def test_service_search_result_puts_offers_last():
    ad = FakeAdapter({("貼るカイロ", 1): (market(), 6)})
    r = service.search_products(["貼るカイロ"], adapter=ad, pages=1, sleep=lambda s: None)
    assert list(r)[-1] == "offers" and list(r).index("notes") < list(r).index("offers")


def test_mcp_result_orders_credit_notes_and_conclusions_before_the_big_lists():
    """公開 MCP が返す結果（JSON のテキストの順）で、クレジット・notes・shortlist・caveats が groups より前に出る（切り詰めに強い）。"""
    app, _ = make_app("/kaimono", adapter=FakeAdapter({("貼るカイロ", 1): (market(), 6)}))
    with TestClient(app) as tc:
        resp = rpc(tc, "/kaimono", "compare_offers", {"keywords": ["貼るカイロ"], "pages": 1, "basis": "枚",
                                                         "desired_quantity": 60, "desired_quantity_max": 100})
        d = data(resp)
    assert d["ok"]
    top = list(d)
    assert top[-1] == "comparison"
    for k in ("credit", "credits", "notes", "stats"):
        if k in d:
            assert top.index(k) < top.index("comparison"), k
    text = json.dumps(d, ensure_ascii=False)
    for first in ('"shortlist"', '"caveats"', '"cheapest_order"'):
        assert text.index(first) < text.index('"groups"')
    assert text.index('"credit') < text.index('"comparison"')
    assert d["comparison"]["shortlist"]["unconfirmed_candidates"][0]["mall"] == "yahoo"


def test_instructions_tell_the_caller_to_read_shortlist_first_and_description_is_not_grown():
    import asyncio

    from mcp import Client

    from shopping import mcp_server
    for text in (mcp_server.INSTRUCTIONS, mcp_server._ORDER_GUIDE):
        assert "shortlist" in text and "unconfirmed_candidates" in text and "conditions" in text
        assert "別のモールの未確認の安い候補を落とさず" in text

    async def go():
        async with Client(mcp_server.build_server()) as c:
            return {t.name: t for t in (await c.list_tools()).tools}
    d = asyncio.run(asyncio.wait_for(go(), timeout=30))["compare_offers"].description
    assert len(d) <= 2000 and "shortlist" not in d          # ツール説明（2000 字ガード）は増やさず INSTRUCTIONS にだけ足す
