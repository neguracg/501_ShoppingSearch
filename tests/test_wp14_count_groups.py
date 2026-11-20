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
    assert r.main_count_unit == "本" and r.cheapest_unit_price.mall_item_code == "p18"   # 最上位は主グループ（候補数が最多の 本）の最安
    by = {g.count_unit: g for g in r.groups}
    assert by["本"].cheapest_unit_price.mall_item_code == "p18" and by["個"].cheapest_unit_price.mall_item_code == "n60"
    assert any(c == COUNT_GROUP_CAVEAT.format(main="本", others="個 2件") for c in r.caveats)


def test_single_count_unit_keeps_the_top_level_cheapest():
    r = compare([o for o in takitsuke() if o.mall_item_code in ("f36", "c36")], basis="個")
    assert len(r.groups) == 1 and r.groups[0].count_unit == "本"
    assert r.cheapest_unit_price is r.groups[0].cheapest_unit_price and r.cheapest_unit_price.mall_item_code == "f36"
    assert not any("数え方の違う" in c for c in r.caveats)


def test_each_group_gets_its_own_order_section_and_the_top_level_is_the_main_group():
    r = compare(takitsuke(), basis="個", desired_quantity=30)
    by = {g.count_unit: g for g in r.groups}
    assert by["本"].cheapest_order.offer.mall_item_code == "f36" and by["本"].cheapest_order.n == 1
    assert by["個"].cheapest_order.offer.mall_item_code == "n10" and by["個"].cheapest_order.n == 3
    assert r.main_count_unit == "本" and r.cheapest_order is by["本"].cheapest_order
    assert r.order_plans == by["本"].order_plans and r.to_check == by["本"].to_check
    assert r.cheapest_for_quantity.mall_item_code == "f36"


def _grp(prefix, name, n, price=1000, ship="included"):
    return [off(f"{prefix}{i}", name, price + i, ship=ship) for i in range(n)]


def test_main_group_is_the_one_with_most_unit_prices_then_confirmed_then_cheapest():
    a = _grp("h", "着火剤 18本入り", 3) + _grp("k", "着火剤 10個セット", 2)
    assert compare(a, basis="個").main_count_unit == "本"
    # 同数なら確認済みの多い方（個側の 2 件は送料込みのまま、本側は価格幅ありで確認済みでない）
    b = _grp("h", "着火剤 18本入り", 2)
    for o in b:
        o.price_min, o.price_max = 100, 2000
    assert compare(b + _grp("k", "着火剤 10個セット", 2), basis="個").main_count_unit == "個"
    # それも同じなら最安が安い方
    c = _grp("h", "着火剤 18本入り", 2, price=900) + _grp("k", "着火剤 10個セット", 2, price=500)
    assert compare(c, basis="個").main_count_unit == "個"
    # 最後は数え語の順（決定的）
    d = _grp("h", "着火剤 18本入り", 1, price=500) + _grp("k", "着火剤 10個セット", 1, price=500)
    assert compare(d, basis="個").main_count_unit == compare(list(reversed(d)), basis="個").main_count_unit


def test_counter_basis_main_group_is_that_counter_and_non_count_basis_has_none():
    assert compare(takitsuke(), basis="個").main_count_unit == "本"
    r = compare(takitsuke(), basis="個")
    assert "個 2件" in r.caveats[[i for i, c in enumerate(r.caveats) if "比べていません" in c][0]]
    assert compare(takitsuke(), basis="本").main_count_unit == "本"
    assert compare([off("w", "水 500ml×24本", 1500)]).main_count_unit is None


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
    # c36（18本入 2袋セット）は SPEC §8 Q20（WP15 段B）で packs の 2袋 を持つ候補として袋で比べられる。ここは袋の裏付けが無い 4 件だけ
    r = compare([o for o in takitsuke() if o.mall_item_code != "c36"], basis="袋", desired_quantity=30)
    assert r.groups == [] and r.cheapest_order is None
    assert len(r.unknown_offers) == 4        # 単価は出さない。換算の仮定つきで to_check に残る（counter_assumed。Q20）
    assert {t.plan.offer.mall_item_code for t in r.to_check} == {"p18", "f36", "n10", "n60"}
    assert all("counter_assumed" in t.plan.reasons for t in r.to_check)
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


def test_main_group_is_first_in_groups_even_when_not_the_largest():
    # 主グループ（単位価格が出た候補数が最多）が groups の先頭に来る（Q19）
    r = compare(takitsuke(), basis="個")
    assert r.groups[0].count_unit == r.main_count_unit == "本"
    many_bags = [off(f"b{i}", "着火剤 5袋セット", 500 + i) for i in range(2)] + [off("h", "着火剤 18本入り", 300)]
    r = compare(many_bags, basis="個")
    assert r.main_count_unit == "袋" and r.groups[0].count_unit == "袋"


def test_desired_with_several_groups_says_which_counting_was_used():
    r = compare(takitsuke(), basis="個", desired_quantity=30)
    c = next(c for c in r.caveats if "主グループの数え方" in c)
    assert "希望量 30 は主グループの数え方［本］として扱いました" in c and "別の数え方なら basis に数え語を指定" in c
    r = compare(takitsuke(), basis="個", desired_quantity=30, desired_quantity_max=60)
    assert any("希望量 30〜60 は主グループの数え方［本］" in c for c in r.caveats)
    two = takitsuke() + [off("b1", "着火剤 5袋セット", 500)]
    c = next(c for c in compare(two, basis="個", desired_quantity=30).caveats if "主グループの数え方" in c)
    assert "袋で数えるなら basis=袋 を指定" in c
    assert not any("主グループの数え方" in c for c in compare(takitsuke(), basis="個").caveats)        # 希望量が無い時は出さない
    assert not any("主グループの数え方" in c for c in compare(takitsuke(), basis="本", desired_quantity=30).caveats)
