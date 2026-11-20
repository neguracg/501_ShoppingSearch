# @owns WP14 W2 希望量を注文する組み合わせ（order_plans・cheapest_order・to_check・desired_quantity_max の検査）の自作確認。独立試験（ブラインド）の代わりではない
"""WP14 W2: 同じ商品を n 個注文する案（n = ceil(下限 / 1個の量)・上限があれば注文量 <= 上限）。
確認済み（数量が題名から high・価格が選択肢で変わらない・外れ値でない・送料込み）の中の最安を cheapest_order に、
注文額が安いのに確認済みでない候補を to_check に条件つきで出す。送料無料ライン（3,980円）は仮定しない。
題名・価格は 2026-11-20 の実 API（貼るカイロ）。"""
import pytest

import cli
from fakes import make_offer
from shopping import service
from shopping.inputs import InvalidInput, check_desired_range, validate
from shopping.models import QuantityInfo
from shopping.pricing import SHIPPING_LINE_CAVEAT, compare
from shopping.quantity import parse_quantity


def off(code, name, price, ship="included", fee=None, lo=None, hi=None):
    o = make_offer(code, name=name, price=price, shipping_status=ship, shipping_fee=fee)
    o.quantity = parse_quantity(name)
    o.price_min, o.price_max = lo, hi
    return o


def piece(code, per, price, ship="included"):
    """1 個あたり per（m）の high を直接入れた候補。端数の割り算（0.9 / 0.3）の確認用。"""
    o = make_offer(code, name=f"ひも {code}", price=price, shipping_status=ship)
    o.quantity = QuantityInfo(count_total=1, content_amount=per, content_dimension="length",
                              content_unit="m", confidence="high")
    return o


IRIS60 = "【公式】カイロ 貼る レギュラー 60枚 ぽかぽか家族 PKN-60HR アイリスオーヤマ貼るカイロ"
UNIDY60 = "【ポイント10倍】カイロ 貼るカイロ レギュラー 60枚 使い捨てカイロ まとめ買い アイリスオーヤマ ぽかぽか家族"


def kairo():
    return [off("iris60", IRIS60, 1720), off("iris30", "【公式】カイロ 貼る レギュラー 30枚入り PKN-30HR", 1280),
            off("unidy60", UNIDY60, 1500, lo=1500, hi=1720),
            off("sep60", "カイロ 貼る 60枚 送料別の店", 1300, ship="separate")]


def plan_of(plans, code):
    return next(p for p in plans if p.offer.mall_item_code == code)


# --- n・注文量・注文額・上限 ---------------------------------------------------------------

def test_n_is_ceil_of_lower_bound_over_one_unit_amount():
    r = compare(kairo(), basis="個", desired_quantity=50)
    assert plan_of(r.order_plans, "iris60").n == 1 and plan_of(r.order_plans, "iris60").order_total == 1720
    p = plan_of(r.order_plans, "iris30")
    assert (p.n, p.order_quantity, p.order_total) == (2, 60, 2560)
    assert p.order_unit_price == pytest.approx(2560 / 60)             # 注文額 / 注文量


def test_order_plans_are_sorted_by_order_total_and_never_mix_products():
    r = compare(kairo(), basis="個", desired_quantity=50)
    totals = [p.order_total for p in r.order_plans]
    assert totals == sorted(totals)
    assert all(isinstance(p.offer.mall_item_code, str) for p in r.order_plans)   # 1 案 = 1 商品


@pytest.mark.parametrize("desired,per,expected_n", [(0.9, 0.3, 3), (0.6, 0.2, 3), (1.1, 0.1, 11), (0.3, 0.1, 3), (2.4, 0.8, 3)])
def test_ratio_is_rounded_before_ceil(desired, per, expected_n):
    r = compare([piece("a", per, 100)], basis="m", desired_quantity=desired)
    assert r.order_plans[0].n == expected_n                           # 0.9/0.3=3.0000000000000004 でも 3


def test_upper_bound_removes_plans_over_it_and_says_so():
    r = compare(kairo(), basis="個", desired_quantity=50, desired_quantity_max=70)
    codes = {p.offer.mall_item_code for p in r.order_plans}
    assert codes == {"iris60", "iris30", "unidy60", "sep60"}          # 60 と 30x2=60 は収まる
    r = compare(kairo(), basis="個", desired_quantity=50, desired_quantity_max=59)
    assert r.order_plans == [] and r.cheapest_order is None
    assert any("必要数量" in c and "注文の組み合わせがない" in c for c in r.caveats)
    r = compare(kairo() + [off("big", "カイロ 貼る 480枚", 7000)], basis="個", desired_quantity=50, desired_quantity_max=100)
    assert "big" not in {p.offer.mall_item_code for p in r.order_plans}
    assert any("上限" in c and "1件" in c for c in r.caveats)


def test_without_upper_bound_a_big_pack_is_a_plan_but_not_cheapest():
    r = compare(kairo() + [off("big", "カイロ 貼る 480枚", 7000)], basis="個", desired_quantity=50)
    assert plan_of(r.order_plans, "big").n == 1
    assert r.cheapest_order.offer.mall_item_code == "iris60"


def test_no_upper_limit_on_the_number_of_units():
    r = compare([off("p", "ペン 1本", 100)], basis="個", desired_quantity=5000)
    assert r.order_plans[0].n == 5000 and r.cheapest_order.order_total == 500_000


# --- 確認済みの最安 --------------------------------------------------------------------------

def test_cheapest_order_is_confirmed_only_and_cheapest_for_quantity_follows_it():
    r = compare(kairo(), basis="個", desired_quantity=50)
    assert r.cheapest_order.offer.mall_item_code == "iris60"          # unidy60(幅あり)・sep60(送料別)はもっと安いが確認済みでない
    assert r.cheapest_for_quantity is r.cheapest_order.offer
    assert r.cheapest_order.confirmed and r.cheapest_order.reasons == []


def test_no_desired_quantity_means_no_plans():
    r = compare(kairo(), basis="個")
    assert r.order_plans == [] and r.cheapest_order is None and r.to_check == [] and r.cheapest_for_quantity is None


def test_known_shipping_fee_is_added_once_and_counts_as_confirmed():
    r = compare([off("s", "カイロ 貼る 30枚", 1000, ship="separate", fee=500)], basis="個", desired_quantity=60)
    p = r.order_plans[0]
    assert (p.n, p.order_total) == (2, 2500) and p.confirmed        # 2個 2000 + 送料 500（1 注文に 1 回）


# --- 逆転し得る候補（to_check）と条件 ----------------------------------------------------------

def test_to_check_lists_cheaper_unconfirmed_with_conditions():
    r = compare(kairo(), basis="個", desired_quantity=50)
    by = {t.plan.offer.mall_item_code: t for t in r.to_check}
    assert set(by) == {"unidy60", "sep60"}
    sep = by["sep60"].conditions[0]
    assert sep["reason"] == "shipping_separate" and sep["threshold"] == 1720 - 1300       # 送料が 420円未満なら安い
    assert "420円未満" in sep["text"]
    var = by["unidy60"].conditions[0]
    assert var["reason"] == "price_varies" and var["threshold"] == 1719                   # 60枚の選択肢が 1,719円以下なら安い
    assert "60枚" in var["text"] and "1,719円以下" in var["text"]


def test_to_check_price_varies_threshold_uses_n():
    offers = [off("iris60", IRIS60, 1720), off("unidy60", UNIDY60, 1500, lo=1500, hi=1720)]
    r = compare(offers, basis="個", desired_quantity=120)           # 2 個ずつ: 3440 対 3000
    c = r.to_check[0].conditions[0]
    assert r.order_plans[0].offer.mall_item_code == "unidy60" and r.cheapest_order.offer.mall_item_code == "iris60"
    assert c["threshold"] == (3440 - 1) // 2 == 1719               # 2p < 3440 を満たす最大の整数


def test_conditions_say_the_threshold_assumes_the_other_checks_pass():
    offers = [off("iris60", IRIS60, 1720), off("both", UNIDY60, 1300, ship="separate", lo=1300, hi=1720)]
    r = compare(offers, basis="個", desired_quantity=50)
    conds = r.to_check[0].conditions
    assert {c["reason"] for c in conds} == {"shipping_separate", "price_varies"}
    assert all("ほかの確認事項も満たす場合" in c["text"] for c in conds)


def test_to_check_has_no_count_limit_and_group_caveats_name_the_count_unit():
    many = [off(f"s{i}", "カイロ 貼る 60枚", 1000 + i, ship="separate") for i in range(25)] + [off("c", IRIS60, 2500)]
    r = compare(many, basis="個", desired_quantity=50)
    assert len(r.to_check) == 25
    two = [off("a", "カイロ 60枚", 1500, ship="separate"), off("b", "文化たきつけ 18本入り", 300, ship="separate")]
    r = compare(two, basis="個", desired_quantity=18)
    assert any(c.startswith("［本］確認済み") for c in r.caveats) and any(c.startswith("［枚］確認済み") for c in r.caveats)


def test_unconfirmed_not_cheaper_than_the_best_is_not_listed():
    offers = [off("iris60", IRIS60, 1720), off("sep", "カイロ 貼る 60枚", 1800, ship="separate")]
    r = compare(offers, basis="個", desired_quantity=50)
    assert r.to_check == []


def test_free_shipping_line_is_not_assumed():
    offers = [off("sep", "カイロ 貼る 60枚×5", 5000, ship="separate"), off("unk", "カイロ 貼る 60枚×6", 6000, ship="unknown")]
    r = compare(offers, basis="個", desired_quantity=300)           # 注文額は 3,980円を超える
    assert r.cheapest_order is None                                # 送料込みにしない
    assert {p.offer.mall_item_code for p in r.order_plans} == {"sep", "unk"}
    assert all(not p.confirmed for p in r.order_plans)
    assert SHIPPING_LINE_CAVEAT in r.caveats and "000013788" in SHIPPING_LINE_CAVEAT
    assert [t.plan.offer.mall_item_code for t in r.to_check] == ["sep", "unk"]           # 確認済みが無い時は安い順に全部


def test_no_confirmed_lists_conditional_candidates_cheapest_first_and_says_what_is_missing():
    offers = [off("a", "カイロ 60枚", 1500, lo=1500, hi=1720), off("b", "カイロ 60枚", 1300, ship="separate")]
    r = compare(offers, basis="個", desired_quantity=60)
    assert r.cheapest_order is None and [t.plan.offer.mall_item_code for t in r.to_check] == ["b", "a"]
    assert any("確認済み" in c and "送料別 1件" in c and "選択肢で価格が変わる 1件" in c for c in r.caveats)
    assert all(c["threshold"] is None for t in r.to_check for c in t.conditions)


def test_caption_source_candidate_goes_to_to_check_with_the_evidence():
    cheap = off("cap", "カイロ 使い捨て", 900)
    cheap.quantity = QuantityInfo(count_total=18, count_unit="本", confidence="high", source="caption",
                                  caption_evidence="■数量:18本入り")
    r = compare([off("a", "カイロ 18本入り", 1200), cheap], basis="個", desired_quantity=18)
    assert r.cheapest_order.offer.mall_item_code == "a"
    cond = r.to_check[0].conditions[0]
    assert cond["reason"] == "quantity_from_caption" and "■数量:18本入り" in cond["text"]
    assert r.cheapest_unit_price.mall_item_code == "a"             # 単位価格の最安にも選ばない


def test_outlier_is_to_check_with_a_note():
    offers = [off(c, "水 500ml×24本", 1500) for c in "abcd"] + [off("z", "水 500ml×24本", 100)]
    offers[-1].quantity = QuantityInfo(count_total=24, count_unit="本", content_amount=50000.0, content_dimension="volume",
                                       content_unit="ml", confidence="high")
    r = compare(offers, basis="ml", desired_quantity=12000)
    assert r.cheapest_order.offer.mall_item_code == "a"
    assert r.to_check[0].conditions[0]["reason"] == "unit_price_outlier"


# --- 入力の検査 ----------------------------------------------------------------------------------

@pytest.mark.parametrize("lower,upper", [(10, 5), (None, 5), (10, 0), (10, True), (10, float("inf")), (10, "20"), (10, -1)])
def test_bad_range_is_invalid(lower, upper):
    with pytest.raises(InvalidInput):
        check_desired_range(lower, upper)
    with pytest.raises(ValueError):
        compare([], desired_quantity=lower, desired_quantity_max=upper)


@pytest.mark.parametrize("lower,upper", [(10, 10), (10, None), (None, None), (50, 100.5)])
def test_valid_range(lower, upper):
    check_desired_range(lower, upper)
    validate(keywords=["貼るカイロ"], desired_quantity=lower, desired_quantity_max=upper)


def test_public_validate_rejects_bad_upper():
    with pytest.raises(InvalidInput):
        validate(keywords=["貼るカイロ"], desired_quantity=50, desired_quantity_max=10)


# --- service / CLI --------------------------------------------------------------------------------

def test_service_dict_has_plans_and_conditions():
    r = service.compare_offers(["洗濯洗剤 詰め替え"], desired_quantity=5000, desired_quantity_max=100000, basis="g",
                               adapter=service.make_adapter(mock=True))
    assert r["ok"] and r["desired_quantity_max"] == 100000
    c = r["comparison"]
    assert {"order_plans", "cheapest_order", "to_check", "cheapest_for_quantity"} <= set(c)
    for p in c["order_plans"]:
        assert {"item_code", "n", "order_quantity", "order_total", "order_unit_price", "confirmed", "unconfirmed_reasons"} <= set(p)
    bad = service.compare_offers(["洗濯洗剤"], desired_quantity=50, desired_quantity_max=10, adapter=service.make_adapter(mock=True))
    assert not bad["ok"] and bad["error"]["kind"] == "invalid_request"


def test_cli_prints_orders_and_conditions(capsys):
    assert cli.run(["compare", "洗濯洗剤 詰め替え", "--basis", "g", "--desired-quantity", "5000",
                    "--desired-quantity-max", "20000", "--mock"]) == 0
    out = capsys.readouterr().out
    assert "注文の最安" in out and "希望量 5,000〜20,000" in out
