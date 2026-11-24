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
    # 呼び出し側が読むのは structuredContent でなくテキスト（content[0].text）の可能性もある: そちらも同じ順
    body = resp.json()["result"]["content"][0]["text"]
    for first in ('"shortlist"', '"caveats"', '"cheapest_order"', '"notes"'):
        assert body.index(first) < body.index('"groups"'), first
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


# --- レビュー B1・B2・空括弧（2026-11-25 の追加）-----------------------------------------------

def weak_market():
    """B1 の再現: 楽天の確認済み 1610 円・楽天『10個セット』6 件（basis=枚では数え語が違う＝換算の仮定 counter_assumed・100〜105 円）・Yahoo 60枚 1500 円 1 件。"""
    return ([rk("bc", "貼るカイロ 60枚 ミニ", 1610)]
            + [rk(f"set{i}", f"貼るカイロ 10個セット 店{i}", 100 + i) for i in range(6)]
            + [yh("y60", "貼るカイロ 60枚 Yahoo店", 1500)])


def test_b1_a_cheaper_yahoo_candidate_is_not_pushed_out_by_five_weak_rakuten_assumptions():
    c = cmp_dict(weak_market())
    tc = c["to_check"]
    assert [t["mall"] for t in tc[:5]] == ["rakuten"] * 5 and all("counter_assumed" in t["unconfirmed_reasons"] for t in tc[:5])
    assert any(t["mall"] == "yahoo" for t in tc[5:])                         # 実装前は to_check の 6 件目以降＝shortlist の外
    cands = c["shortlist"]["unconfirmed_candidates"]
    assert [t["item_code"] for t in cands[:5]] == [t["item_code"] for t in tc[:5]]      # 先頭 5 件は to_check の順のまま（並べ替えない）
    assert [t["mall"] for t in cands].count("yahoo") == 1 and cands[5]["mall"] == "yahoo"     # 出ないモールの先頭の 1 件が足される
    assert cands[5] == next(t for t in tc if t["mall"] == "yahoo")                          # そのモールの to_check 内の最初の候補
    assert len(cands) == 6 <= service.SHORTLIST_TOP + 2 and c["shortlist"]["unconfirmed_count"] == len(tc)
    assert c["cheapest_order"]["item_code"] == "bc"                                         # 判定は不変


def test_b1_no_extra_when_every_mall_is_already_in_the_top_five_and_one_extra_per_missing_mall_only():
    offers = [rk("bc", "貼るカイロ 60枚 ミニ", 1610)] + [yh(f"y{i}", f"貼るカイロ 60枚 店{i}", 1000 + i) for i in range(9)]
    assert len(cmp_dict(offers)["shortlist"]["unconfirmed_candidates"]) == 5      # Yahoo だけなら従来どおり 5 件
    both = cmp_dict(market())["shortlist"]["unconfirmed_candidates"]
    assert {t["mall"] for t in both} == {"rakuten", "yahoo"} and len(both) <= service.SHORTLIST_TOP + 2


def test_b2_reading_and_instructions_say_assumption_candidates_can_be_pricier_than_the_confirmed_cheapest():
    from shopping import mcp_server
    sl = cmp_dict(market())["shortlist"]
    assert "counter_assumed" in sl["reading"] and "conditions を読んで" in sl["reading"] and "先頭の 1 件" in sl["reading"]
    assert "換算の仮定で残した候補は確認済みの最安より高いこともある" in mcp_server._ORDER_GUIDE
    # 実際の動き: 換算の仮定の候補は確認済みの最安より高くても to_check に残る（判定は不変）
    offers = [rk("bc", "貼るカイロ 60枚 ミニ", 1610), rk("big", "貼るカイロ 10個セット 高い店", 99999)]
    c = cmp_dict(offers)
    assert [t["item_code"] for t in c["to_check"]] == ["big"] and c["to_check"][0]["order_total"] > 1610
    assert c["shortlist"]["unconfirmed_candidates"][0]["item_code"] == "big"


def test_empty_parentheses_never_appear_in_to_check_conditions():
    """to_check の条件文の『商品名の数量（）』。題名 low（数量が読めない）で換算の仮定＋価格幅の案は、仮定が置いた数量（60枚）を入れる。"""
    lows = [rk("lo1", "貼るカイロ 60枚 30枚 お得", 1280, price_min=1280, price_max=1700),
            rk("lo2", "貼るカイロ 60セット入り 1箱", 1280, price_min=1280, price_max=1700),
            rk("lo3", "貼るカイロ 60枚 30枚 送料別", 1280, ship="separate", price_min=1280, price_max=1700)]
    c = cmp_dict([rk("bc", "貼るカイロ 60枚 ミニ", 1610)] + lows)
    texts = [cc["text"] for t in c["to_check"] for cc in t["conditions"]]
    assert texts and not any("（）" in x or "。なら" in x or "（、" in x for x in texts), texts
    low = next(t for t in c["to_check"] if t["item_code"] == "lo1")
    assert "商品名の数量（60枚）の選択肢の価格" in low["conditions"][0]["text"]


def test_condition_label_falls_back_to_no_parentheses_when_no_quantity_is_known():
    from shopping import pricing
    from shopping.pricing import OrderPlan

    # 数量の読みが何も無い案（題名からも換算の仮定からも）: 括弧ごと省く
    o = rk("none", "貼るカイロ ミニ", 1280, price_min=1280, price_max=1700)
    plan = OrderPlan(offer=o, n=1, order_quantity=60.0, order_total=1280, order_unit_price=21.3, label="1枚あたり",
                     shipping_status="included", count_unit=None, reasons=["price_varies"], notes={})
    best = OrderPlan(offer=rk("bc", "貼るカイロ 60枚", 1610), n=1, order_quantity=60.0, order_total=1610,
                     order_unit_price=26.8, label="1枚あたり", shipping_status="included", count_unit="枚", reasons=[], notes={})
    text = pricing._conditions(plan, best)[0]["text"]
    assert "（）" not in text and "商品名の数量の選択肢の価格が" in text
