# @owns WP14 W3 数え語（count_unit）ごとの比較グループと、basis への数え語の指定の自作確認。独立試験（ブラインド）の代わりではない
"""WP14 W3: basis が「個」（数える）の比較は、数え語（本・袋・枚・ロール・個…）ごとにグループを分け、単位価格の最安・注文の最安は
グループをまたいで比べない。basis に数え語の正規名（別名 R など）を指定すると、その数え語の候補だけで比べる。
題名・価格は 2026-11-20 の実 API（文化たきつけ）。"""
import pytest

import cli
from fakes import make_offer
from shopping import service
from shopping.inputs import InvalidInput, check_basis, resolve_compare_basis, validate
from shopping.pricing import COUNT_GROUP_CAVEAT, compare
from shopping.quantity import parse_quantity
from shopping.regulars import RegularsError, _parse_one


def off(code, name, price, ship="included"):
    o = make_offer(code, name=name, price=price, shipping_status=ship)
    o.quantity = parse_quantity(name)
    return o


T18 = "富士屋 文化たきつけ 18本入り"
T36 = ("【在庫有】【まとめ買い】丸実富士屋商店 文化たきつけ 18本入り ×2個セット 着火剤 アウトドア キャンプ レジャー BBQ "
       "バーベキュー オガ炭 備長炭 岩手切炭 との使用がおすすめ")
T10 = "文化たきつけ10個セット☆木炭・練炭・豆炭・石炭・オガ炭・薪用簡単着火剤・屋外用（火おこしグッズ）"
T60 = "文化たきつけ60個セット☆木炭・練炭・豆炭・石炭・オガ炭・薪用簡単着火剤・屋外用（火おこしグッズ）"


def takitsuke():
    return [off("p18", T18, 179, ship="separate"), off("f36", T36, 580), off("c36", "文化たきつけ 富士屋 着火剤 18本入 2袋セット", 880),
            off("n10", T10, 3200), off("n60", T60, 12800)]


def groups(r):
    return {g.count_unit: [o.mall_item_code for o in g.offers] for g in r.groups}


# --- 数え語ごとのグループ ------------------------------------------------------------------------

def test_basis_count_splits_groups_by_count_unit_and_does_not_compare_across():
    r = compare(takitsuke(), basis="個")
    assert set(groups(r)) == {"本", "個"} and set(groups(r)["本"]) == {"p18", "f36", "c36"} and set(groups(r)["個"]) == {"n10", "n60"}
    assert r.groups[0].count_unit == "本"                              # 大きいグループが先
    assert r.cheapest_unit_price is None                               # 本と個は同じ単価順に並べない
    by = {g.count_unit: g for g in r.groups}
    assert by["本"].cheapest_unit_price.mall_item_code == "p18" and by["個"].cheapest_unit_price.mall_item_code == "n60"
    assert any(c == COUNT_GROUP_CAVEAT.format(units="本・個") for c in r.caveats) and "本・個" in COUNT_GROUP_CAVEAT.format(units="本・個")


def test_single_count_unit_keeps_the_top_level_cheapest():
    r = compare([o for o in takitsuke() if o.mall_item_code in ("f36", "c36")], basis="個")
    assert len(r.groups) == 1 and r.groups[0].count_unit == "本"
    assert r.cheapest_unit_price is r.groups[0].cheapest_unit_price and r.cheapest_unit_price.mall_item_code == "f36"
    assert not any("数え方の違う" in c for c in r.caveats)


def test_each_group_gets_its_own_order_section_and_the_top_level_is_empty():
    r = compare(takitsuke(), basis="個", desired_quantity=30)
    by = {g.count_unit: g for g in r.groups}
    assert by["本"].cheapest_order.offer.mall_item_code == "f36" and by["本"].cheapest_order.n == 1
    assert by["個"].cheapest_order.offer.mall_item_code == "n10" and by["個"].cheapest_order.n == 3
    assert r.order_plans == [] and r.cheapest_order is None and r.cheapest_for_quantity is None and r.to_check == []


def test_outliers_are_judged_inside_each_group():
    # 本のグループは 100 円台、個のグループは 1 万円台。全体の中央値で見ると 100 円台が外れ値になるが、グループ内なら外れない
    ho = [off(f"h{i}", f"着火剤 18本入り", 100 + i) for i in range(4)]
    ko = [off(f"k{i}", f"着火剤 10個セット", 12000 + i) for i in range(4)]
    compare(ho + ko, basis="個")
    assert not any(o.unit_price_outlier for o in ho + ko)


def test_the_unit_price_label_stays_per_item_for_the_generic_count_basis():
    r = compare(takitsuke(), basis="個")
    assert {o.unit_price_label for g in r.groups for o in g.offers} == {"1個あたり"}      # Q4。数え語は groups[].count_unit


# --- basis に数え語 -------------------------------------------------------------------------------

def test_basis_counter_compares_only_that_count_unit():
    r = compare(takitsuke(), basis="本", desired_quantity=540)
    assert (r.basis, r.basis_label) == ("本", "1本あたり")
    assert len(r.groups) == 1 and r.groups[0].count_unit == "本" and r.groups[0].basis == "本"
    assert {o.mall_item_code for o in r.groups[0].offers} == {"p18", "f36", "c36"}
    assert {o.mall_item_code for o in r.unknown_offers} == {"n10", "n60"}               # 数え語が違う候補は比べない
    assert any("数え語が 本 でない候補: 2件" in c for c in r.caveats)
    assert r.cheapest_unit_price.mall_item_code == "p18"                          # 9.94円/本。単位価格は送料を見ない
    assert r.cheapest_order.offer.mall_item_code == "f36" and r.cheapest_order.n == 15      # 36本 x 15 = 540本・8,700円
    assert r.cheapest_order.order_total == 580 * 15


@pytest.mark.parametrize("alias,canonical", [("本", "本"), ("袋", "袋"), ("枚", "枚"), ("ロール", "ロール"), ("R", "ロール"),
                                             ("roll", "ロール"), ("P", "パック"), ("缶", "缶")])
def test_counter_names_and_aliases_resolve(alias, canonical):
    assert resolve_compare_basis(alias) == (canonical, "count", canonical)
    check_basis(alias)
    validate(keywords=["あい"], basis=alias)


def test_existing_basis_values_are_unchanged():
    assert resolve_compare_basis("個") == ("個", "count", None)
    assert resolve_compare_basis("L") == ("ml", "volume", None)
    assert resolve_compare_basis("kg") == ("g", "mass", None)


@pytest.mark.parametrize("bad", ["ふしぎ", "コ", "pcs", "ヶ", "ダース", 5, "本数"])
def test_other_values_are_still_invalid(bad):
    with pytest.raises(ValueError):
        resolve_compare_basis(bad)
    with pytest.raises(InvalidInput):
        check_basis(bad)


def test_basis_counter_with_no_matching_candidates_says_so():
    r = compare(takitsuke(), basis="袋", desired_quantity=30)
    assert r.groups == [] and r.cheapest_order is None
    assert len(r.unknown_offers) == 5 and any("数え語が 袋 でない候補: 5件" in c for c in r.caveats)
    assert any("必要数量" in c and "30" in c for c in r.caveats)


def test_regular_master_accepts_a_counter_basis():
    reg = _parse_one({"id": "a", "name": "A", "keywords": ["文化たきつけ"], "basis": "本", "desired_quantity": 540}, 0)
    assert reg.basis == "本"
    with pytest.raises(RegularsError):
        _parse_one({"id": "a", "name": "A", "keywords": ["x1"], "basis": "ふしぎ"}, 0)


# --- service / CLI --------------------------------------------------------------------------------

def test_service_groups_carry_count_unit_and_sections():
    r = service.compare_offers(["洗濯洗剤 詰め替え"], basis="個", desired_quantity=2, adapter=service.make_adapter(mock=True))
    assert r["ok"]
    for g in r["comparison"]["groups"]:
        assert {"count_unit", "cheapest_unit_price", "order_plans", "cheapest_order", "to_check"} <= set(g)


def test_cli_prints_the_group_count_unit(capsys):
    assert cli.run(["compare", "電池", "--basis", "個", "--desired-quantity", "10", "--mock"]) == 0
    out = capsys.readouterr().out
    assert "［" in out and "注文の最安" in out


def test_service_invalid_basis_message_mentions_counters():
    r = service.compare_offers(["洗濯洗剤"], basis="ふしぎ", adapter=service.make_adapter(mock=True))
    assert not r["ok"] and "数え語" in r["error"]["message"]


def test_web_group_titles_differ_by_count_unit():
    from shopping.web_view import group_title
    c = service._comparison_to_dict(compare(takitsuke(), basis="個"))
    titles = [group_title(g, c["basis_label"]) for g in c["groups"]]
    assert len(set(titles)) == 2 and "［本］" in titles[0]
