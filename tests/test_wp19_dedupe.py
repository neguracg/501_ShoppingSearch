# @owns WP19 応答の重複（主グループ groups[0] の order_plans・to_check が最上位と同じ中身の複製）を札（ref）にした形の自作確認。独立試験（ブラインド）の代わりではない
"""WP19（SPEC §8 Q26）: 最上位の order_plans・to_check は主グループ（groups[0]）の物と同じ list。同じ中身を両方に完全に写すと
応答の 23〜30% が複製になる（ブリッジ#10 第2段）ので、groups[0] 側は最上位の要素を指す札（ref・mall・item_code・name・n）だけにする。
候補・情報は捨てない（札の先＝最上位で全項目が読める）。確認済みの判定・並び・条件文・閾値は変えない。"""
import json
import re

import pytest

from fakes import make_offer, yoffer
from shopping import service
from shopping.pricing import compare
from shopping.quantity import parse_quantity


def q(o):
    o.quantity = parse_quantity(o.item_name)
    return o


def rk(code, name, price, **kw):
    return q(make_offer(code, name=name, price=price, shipping_status=kw.pop("ship", "included"), **kw))


def yh(code, name, price, **kw):
    return q(yoffer(code, name=name, price=price, shipping_status=kw.pop("ship", "included"), **kw))


def market():
    return [rk("bc", "貼るカイロ 60枚 ミニ 使い捨て", 1610),
            yh("ie", "貼るカイロ 60枚 ミニ イエプロ", 1380),
            yh("ue", "貼るカイロ 60枚 ミニ ウエノ電器", 1380),
            yh("viva", "貼るカイロ 60枚 ビバホーム", 1362, ship="unknown"),
            rk("unidy", "貼るカイロ 60枚 ゆにでのこづち", 1500, price_min=1500, price_max=1720),
            yh("high", "貼るカイロ 60枚 高い店", 2400)]


def takitsuke():
    t36 = "【在庫有】丸実富士屋商店 文化たきつけ 18本入り ×2個セット 着火剤 アウトドア"
    return [rk("p18", "富士屋 文化たきつけ 18本入り", 179, ship="separate"), rk("f36", t36, 580),
            rk("c36", "文化たきつけ 富士屋 着火剤 18本入 2袋セット", 880),
            rk("n10", "文化たきつけ10個セット☆木炭・練炭・豆炭", 3200), rk("n60", "文化たきつけ60個セット☆木炭・練炭・豆炭", 12800)]


def build(offers, **kw):
    kw.setdefault("desired_quantity", 60)
    kw.setdefault("desired_quantity_max", 100)
    kw.setdefault("basis", "枚")
    c = compare(offers, **kw)
    return c, service._comparison_to_dict(c)


_REF = re.compile(r"^comparison\.(order_plans|to_check)\[(\d+)\]$")


def resolve(d, ref):
    m = _REF.match(ref)
    assert m, ref
    return d[m.group(1)][int(m.group(2))]


def size(x):
    return len(json.dumps(x, ensure_ascii=False, separators=(",", ":")).encode())


def test_main_group_lists_are_refs_to_the_top_level_and_resolve_to_the_same_dicts_as_before():
    c, d = build(market())
    g0 = d["groups"][0]
    assert c.groups[0].order_plans is c.order_plans and c.groups[0].to_check is c.to_check     # 前提: 同じ物
    assert len(g0["to_check"]) == len(d["to_check"]) >= 4 and len(g0["order_plans"]) == len(d["order_plans"]) >= 4
    for key, objs, conv in (("to_check", c.groups[0].to_check, service.to_check_to_dict),
                            ("order_plans", c.groups[0].order_plans, service.order_plan_to_dict)):
        for ref, obj in zip(g0[key], objs):
            old_form = conv(obj)                                   # WP18 までの groups[0] の要素（全キー）
            got = resolve(d, ref["ref"])
            assert got == old_form                                 # 札の先に全項目（価格・送料・数量・確認状態・理由・条件文・URL）
            assert (ref["mall"], ref["item_code"], ref["name"], ref["n"]) == (got["mall"], got["item_code"], got["name"], got["n"])
            assert set(ref) == {"ref", "mall", "item_code", "name", "n"}           # 札は中身を写さない（複製に戻らない）


def test_every_candidate_and_every_field_is_still_readable_somewhere():
    offers = market()
    c, d = build(offers)
    assert {o["item_code"] for g in d["groups"] for o in g["offers"]} | {o["item_code"] for o in d["unknown_offers"]} \
        == {o.mall_item_code for o in offers}
    top_codes = {p["item_code"] for p in d["order_plans"]}
    assert {r["item_code"] for r in d["groups"][0]["order_plans"]} == top_codes
    for t in d["to_check"]:                                        # 条件文・未確認理由・URL・価格は最上位の to_check に全部ある
        assert t["conditions"] and t["unconfirmed_reasons"] and t["url"] and t["price"] is not None
    # 展開した（札を元の dict に戻した）形は、WP18 までの形と同じ（情報の欠落なし）
    expanded = json.loads(json.dumps(d))
    for g in expanded["groups"][:1]:
        g["order_plans"] = [resolve(d, r["ref"]) for r in g["order_plans"]]
        g["to_check"] = [resolve(d, r["ref"]) for r in g["to_check"]]
    assert expanded["groups"][0]["to_check"] == [service.to_check_to_dict(t) for t in c.groups[0].to_check]
    assert expanded["groups"][0]["order_plans"] == [service.order_plan_to_dict(p) for p in c.groups[0].order_plans]


def test_duplicate_is_gone_response_is_smaller_and_top_level_is_unchanged():
    c, d = build(market())
    expanded = json.loads(json.dumps(d))
    g = expanded["groups"][0]
    g["order_plans"] = [resolve(d, r["ref"]) for r in g["order_plans"]]
    g["to_check"] = [resolve(d, r["ref"]) for r in g["to_check"]]
    assert size(d) < size(expanded) * 0.9                           # 複製を札にした分、小さい（この小さな例は候補の明細が大半。実 API は 23〜30%）
    assert d["order_plans"] == [service.order_plan_to_dict(p) for p in c.order_plans]    # 最上位は従来どおり全項目
    assert d["to_check"] == [service.to_check_to_dict(t) for t in c.to_check]
    assert d["cheapest_order"] == service.order_plan_to_dict(c.cheapest_order)


def test_group_cheapest_order_and_cheapest_unit_price_stay_full_dicts():
    _, d = build(market())
    g0 = d["groups"][0]
    assert g0["cheapest_order"] == d["cheapest_order"] and "ref" not in g0["cheapest_order"]
    assert g0["cheapest_unit_price"] == d["cheapest_unit_price"]


def test_other_count_unit_groups_keep_their_own_full_plans_and_only_the_main_group_gets_refs():
    c, d = build(takitsuke(), basis="個", desired_quantity=30, desired_quantity_max=None)
    assert len(d["groups"]) == 2 and d["main_count_unit"] == d["groups"][0]["count_unit"]
    g0, g1 = d["groups"]
    assert c.groups[1].order_plans is not c.order_plans
    assert all("ref" in x for x in g0["order_plans"] + g0["to_check"])
    assert g1["order_plans"] and all("ref" not in x and "order_total_kind" in x for x in g1["order_plans"])      # 他のグループは全項目のまま
    assert all("ref" not in x and "conditions" in x for x in g1["to_check"])


def test_group_plans_helper_falls_back_when_lists_are_not_the_same_object():
    top = [object()]
    assert service._group_plans(list(top), top, [{"mall": "x"}], "to_check") is None      # 同じ中身でも別の list なら札にしない
    assert service._group_plans([], [], [], "to_check") is None
    assert service._group_plans(top, top, [{"mall": "x", "item_code": "a", "name": "n", "n": 2}], "to_check") \
        == [{"ref": "comparison.to_check[0]", "mall": "x", "item_code": "a", "name": "n", "n": 2}]


def test_unit_price_mode_without_desired_quantity_has_no_refs():
    _, d = build(market(), desired_quantity=None, desired_quantity_max=None)
    assert d["groups"][0]["order_plans"] == [] and d["groups"][0]["to_check"] == []


def test_judgement_is_unchanged_confirmed_cheapest_and_order_of_to_check():
    c, d = build(market())
    assert d["cheapest_order"]["item_code"] == "bc" and d["cheapest_unit_price"]["item_code"] == "bc"
    assert [t["item_code"] for t in d["to_check"]] == [t.plan.offer.mall_item_code for t in c.to_check]
    assert [r["item_code"] for r in d["groups"][0]["to_check"]] == [t["item_code"] for t in d["to_check"]]
    keys = list(d)
    assert keys.index("cheapest_order") < keys.index("shortlist") < keys.index("caveats") < keys.index("to_check") < keys.index("groups")


def test_web_group_offers_max_still_cuts_offers_only():
    c = compare(market(), desired_quantity=60, desired_quantity_max=100, basis="枚")
    d = service._comparison_to_dict(c, group_offers_max=2)
    assert len(d["groups"][0]["offers"]) == 2 and d["groups"][0]["count"] == len(c.groups[0].offers)
    assert len(d["groups"][0]["to_check"]) == len(d["to_check"])


def test_instructions_and_tool_description_explain_refs_within_2000_chars(monkeypatch):
    from shopping import mcp_server
    assert "ref" in mcp_server._ORDER_GUIDE and "groups[0]" in mcp_server._ORDER_GUIDE
    for malls in (["rakuten"], ["rakuten", "yahoo"]):
        text = mcp_server.instructions_for(malls)
        assert "comparison.to_check[" in text
