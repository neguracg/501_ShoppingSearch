# @owns WP15 段B 購入単位のまま比べる basis=数え語（counter_basis.py と pricing.compare の数え語の経路）の自作確認。独立試験（ブラインド）の代わりではない
"""文化たきつけ（basis=袋・desired=30）と、カイロ（basis が個で数え語が複数）。題名・価格は 2026-11-20〜21 の実 API。
確認済みで横並びにするのは 1袋の中身が一致する候補だけ。それ以外は換算の仮定つき（counter_assumed）で to_check に出し、最安に選ばない。"""
import pytest

from fakes import make_offer
from shopping import service
from shopping.caption_quantity import read_offer_quantity
from shopping.pricing import compare, unconfirmed_reasons

COLOLO = "文化たきつけ 富士屋 着火剤 18本入 2袋セット"
MAYFAIR36 = "【送料無料】文化たきつけ 36本（18本×2個セット） 薪用着火剤 焚き火"
FANS10 = "丸実富士屋商店 文化たきつけ 18本入り ×10個セット 着火剤"
P18 = "富士屋 文化たきつけ 18本入り"
T10 = "文化たきつけ10個セット☆木炭・練炭・豆炭・石炭・オガ炭"
MAYFAIR60 = "文化たきつけ 60セット入り 1箱 着火剤 強力着火 灯油系 マッチ1本で簡単着火"


def off(code, name, price, ship="included", shop="shop", lo=None, hi=None):
    o = make_offer(code, name=name, price=price, shipping_status=ship, shop_name=shop)
    o.price_min, o.price_max = lo, hi
    o.quantity = read_offer_quantity(o)
    return o


def by(r, code):
    return next(t for t in r.to_check if t.plan.offer.mall_item_code == code)


def base_set():
    return [off("cololo", COLOLO, 880, shop="cololo"), off("mf36", MAYFAIR36, 590), off("fans10", FANS10, 2330),
            off("p18", P18, 179, ship="separate"), off("n10", T10, 3200), off("yama", "富士屋 文化たきつけ [着火剤]", 168, ship="separate")]


# --- AC20: 候補ゼロにならない・袋のまま比べる -------------------------------------------------------

def test_basis_fukuro_desired_30_is_not_empty_and_compares_in_fukuro():
    r = compare(base_set(), basis="袋", desired_quantity=30)
    assert (r.basis, r.basis_label, r.main_count_unit) == ("袋", "1袋あたり", "袋")
    assert [g.count_unit for g in r.groups] == ["袋"] and [o.mall_item_code for o in r.groups[0].offers] == ["cololo"]
    co = r.cheapest_order
    assert co.offer.mall_item_code == "cololo" and co.n == 15 and co.order_quantity == 30 and co.order_total == 880 * 15
    assert co.confirmed and co.order_unit_price == pytest.approx(440.0)
    assert r.cheapest_unit_price.mall_item_code == "cololo" and r.cheapest_unit_price.unit_price == pytest.approx(440.0)


def test_other_candidates_are_kept_as_conditional_to_check_and_never_cheapest():
    r = compare(base_set(), basis="袋", desired_quantity=30)
    tc = {t.plan.offer.mall_item_code: t for t in r.to_check}
    assert set(tc) == {"yama", "p18", "mf36", "fans10", "n10"}
    for t in tc.values():
        assert "counter_assumed" in t.plan.reasons and not t.plan.confirmed
        assert t.plan.offer.mall_item_code not in [p.offer.mall_item_code for p in r.order_plans]
    # ① 1袋の中身がただ 1 通り（18本）で、count_unit が 本 の候補は「1袋が18本なら」
    assert "1袋が18本なら（根拠: cololo の商品名）" in tc["p18"].conditions[0]["text"]
    assert tc["mf36"].plan.n == 15 and tc["mf36"].plan.order_quantity == 30           # 36本 = 2袋相当
    assert tc["fans10"].plan.n == 3 and "1袋が18本なら" in tc["fans10"].conditions[0]["text"]       # 180本 = 10袋相当 × 3個 = 30袋
    # ② 数量が読めない候補は「この商品1点が1袋なら」。注文個数＝希望量
    assert tc["yama"].plan.n == 30 and tc["yama"].plan.order_total == 168 * 30
    assert tc["yama"].conditions[0]["text"].startswith("この商品1点が1袋なら、送料別。")
    assert tc["yama"].conditions[0]["reasons"] == ["counter_assumed", "shipping_separate"]       # quantity_unknown は仮定に置き換わる


def test_basis_counter_keeps_every_assumed_candidate_even_when_it_is_not_cheaper():
    """Q20: 仮定を置いた候補は捨てずに全部 to_check（Q19 の主グループ外の数え語だけ『より安くなり得る時』）。"""
    r = compare(base_set() + [off("big", "文化たきつけ 100個セット", 99999)], basis="袋", desired_quantity=30)
    big = by(r, "big")
    assert big.plan.order_total == 99999 * 1 and big.conditions[0]["threshold"] is None     # 100袋相当 1個。確認済みの 13,200 円より高いが残る
    assert "この商品の1個が1袋なら" in big.conditions[0]["text"]
    assert not any("数え語が 袋 でない候補" in c for c in r.caveats)                     # 仮定つきで出した候補は数えない（量が読める big は条件なしで残る）


def test_unreadable_quantity_candidates_are_listed_only_when_they_could_be_cheaper():
    """量が読めない候補（none・low。low も none と同じ扱い）は『この商品1点が1袋なら』の注文額が確認済みの最安より安くなり得る時だけ to_check。
    出さない候補は unknown_offers に残り、caveats に件数と理由が出る。"""
    low = off("mf60", MAYFAIR60, 9710, ship="separate")                    # mayfair-17:10014877。『マッチ1本で』の 1 で low
    assert low.quantity.confidence == "low"
    # low は題名に読めた個数の読み（60セット）を仮定にする。1箱＝60袋なら 1個 9,710円で確認済みの 13,200円より安い→条件つきで出る（R1）
    r = compare(base_set() + [low], basis="袋", desired_quantity=30)
    t = by(r, "mf60")
    assert t.plan.n == 1 and t.plan.order_quantity == 60 and t.plan.reasons == ["counter_assumed", "shipping_separate"]
    assert t.conditions[0]["text"].startswith("この商品が60セットで、1セットが1袋なら（題名に食い違う数がある）、送料別。")
    assert "mf60" in [o.mall_item_code for o in r.unknown_offers]
    # 高すぎて安くなり得ない low は出さない
    r2 = compare(base_set() + [off("lowhigh", MAYFAIR60, 99999, ship="separate")], basis="袋", desired_quantity=30)
    assert "lowhigh" not in {x.plan.offer.mall_item_code for x in r2.to_check}
    assert any("確認済みの最安より安くなり得ない候補: 1件" in c for c in r2.caveats)
    # 読みが複数ある low は、安くなり得る読みのうち最安の注文額の 1 つだけを出す
    multi = off("multi", "着火剤 12ロール 24ロール", 300)
    assert multi.quantity.confidence == "low"
    rm = compare(base_set() + [multi], basis="袋", desired_quantity=30)
    tm = [x for x in rm.to_check if x.plan.offer.mall_item_code == "multi"]
    assert len(tm) == 1 and tm[0].plan.n == 2 and "24ロールで" in tm[0].conditions[0]["text"]
    # 確認済みが 1 件も無い時は全部出す（Q16）
    only_low = compare([low, off("yama", "富士屋 文化たきつけ [着火剤]", 168, ship="separate")], basis="袋", desired_quantity=30)
    assert {t.plan.offer.mall_item_code for t in only_low.to_check} == {"mf60", "yama"}


def test_caveat_names_the_count_of_assumptions_and_the_ground():
    r = compare(base_set(), basis="袋", desired_quantity=30)
    assert len(r.to_check) == 5
    text = next(c for c in r.caveats if "換算を仮定" in c)
    assert f"{len(r.to_check)}件" in text and "1袋＝18本は候補 1件の商品名から" in text


def test_no_assumption_without_a_desired_quantity():
    r = compare(base_set(), basis="袋")
    assert r.to_check == [] and r.cheapest_order is None
    assert [o.mall_item_code for o in r.groups[0].offers] == ["cololo"]
    assert any("数え語が 袋 でない候補" in c for c in r.caveats)


# --- 1袋の中身が違う候補 ----------------------------------------------------------------------------

def test_pack_content_differs_is_unconfirmed_and_kept_in_order_plans_and_to_check():
    offers = [off("a18", COLOLO, 880), off("b18", "富士屋 着火剤 18本入×2袋セット", 900), off("c9", "着火剤 9本入 2袋セット", 300)]
    r = compare(offers, basis="袋", desired_quantity=30)
    c9 = next(o for o in r.groups[0].offers if o.mall_item_code == "c9")
    assert c9.pack_content_differs and unconfirmed_reasons(c9) == ["pack_content_differs"]
    assert r.cheapest_order.offer.mall_item_code == "a18"                      # 9本入 は安くても最安に選ばない
    assert r.cheapest_unit_price.mall_item_code == "a18"
    assert [p.offer.mall_item_code for p in r.order_plans] == ["c9", "a18", "b18"]
    t = by(r, "c9")
    assert t.conditions[0]["reasons"] == ["pack_content_differs"] and t.conditions[0]["text"].startswith("1袋の中身が違う（9本入）。")
    d = service._comparison_to_dict(r)
    c9d = next(o for o in d["groups"][0]["offers"] if o["item_code"] == "c9")
    assert c9d["unit_price"] is None and c9d["provisional_unit_price"] == pytest.approx(150.0)
    assert c9d["unit_price_unconfirmed_reasons"] == ["pack_content_differs"]


def test_the_base_and_its_count_are_in_the_caveats_and_the_differs_sentence():
    offers = [off("a18", COLOLO, 880), off("b18", "富士屋 着火剤 18本入×2袋セット", 900), off("c9", "着火剤 9本入 2袋セット", 300)]
    r = compare(offers, basis="袋", desired_quantity=30)
    cav = next(c for c in r.caveats if "中身の基準" in c)
    assert "基準＝18本入（2件の商品名から）" in cav and "利用者が欲しい中身とは限らない" in cav
    assert by(r, "c9").conditions[0]["text"].startswith("1袋の中身が違う（9本入）。基準＝18本入（2件の商品名から）。")


def test_the_base_is_the_most_common_content_and_ties_go_to_the_cheaper_confirmed():
    r = compare([off("n9", "着火剤 9本入 2袋セット", 300), off("n18", COLOLO, 880)], basis="袋", desired_quantity=30)
    flagged = {o.mall_item_code for o in r.groups[0].offers if o.pack_content_differs}
    assert flagged == {"n18"}                                                  # 同数: 最安の注文額が安い 9本入 が基準
    r = compare([off("n9", "着火剤 9本入 2袋セット", 300), off("n18", COLOLO, 880), off("m18", "着火剤 18本入 2袋セット", 900)],
                basis="袋", desired_quantity=30)
    assert {o.mall_item_code for o in r.groups[0].offers if o.pack_content_differs} == {"n9"}     # 多い方が基準


def test_two_different_contents_mean_no_unique_content_so_assumption_two_is_used():
    r = compare([off("n9", "着火剤 9本入 2袋セット", 300), off("n18", COLOLO, 880), off("p18", P18, 179)], basis="袋", desired_quantity=30)
    text = by(r, "p18").conditions[0]["text"]
    assert text.startswith("この商品の1本が1袋なら") and "18本なら" not in text


def test_a_count_unit_candidate_is_counted_by_its_total_not_by_packs():
    r = compare([off("f", "着火剤 5袋", 500), off("c", COLOLO, 880)], basis="袋", desired_quantity=10)
    f = next(o for o in r.groups[0].offers if o.mall_item_code == "f")
    assert f.unit_price == pytest.approx(100.0) and not f.pack_content_differs        # (a) は 1袋の中身を比べない


# --- 注文案・並び -----------------------------------------------------------------------------------

def test_conditions_combine_money_reasons_in_one_sentence():
    r = compare(base_set(), basis="袋", desired_quantity=30)
    t = by(r, "p18")
    assert t.conditions[0]["reason"] == "counter_assumed+shipping_separate" and len(t.conditions) == 1
    assert t.conditions[0]["text"].count("送料が") == 1 and t.conditions[0]["threshold"] == 13200 - t.plan.order_total


def test_to_check_is_sorted_by_order_total_and_the_range_form_uses_the_unit_price():
    r = compare(base_set(), basis="袋", desired_quantity=20, desired_quantity_max=40)
    totals = [(t.plan.order_total * 1.0 / t.plan.order_quantity) for t in r.to_check]
    assert totals == sorted(totals)
    assert r.cheapest_order.offer.mall_item_code == "cololo"


def test_service_dict_gives_the_assumed_plan_a_provisional_price_with_the_counter_label():
    r = compare(base_set(), basis="袋", desired_quantity=30)
    d = service._comparison_to_dict(r)
    t = next(x for x in d["to_check"] if x["item_code"] == "yama")
    assert t["order_unit_price"] is None and t["provisional_order_unit_price"] == pytest.approx(168.0)
    assert t["unit_price_label"] == "1袋あたり" and t["unit_price_unconfirmed_reasons"] == ["counter_assumed"]
    assert t["order_total_kind"] == "item_subtotal" and t["payment_total"] is None
    assert [u["item_code"] for u in d["unknown_offers"] if u["item_code"] == "yama"] == ["yama"]       # unknown_offers には従来どおり残る


def test_basis_hon_still_works_the_old_way():
    r = compare(base_set(), basis="本", desired_quantity=540)
    assert {o.mall_item_code for o in r.groups[0].offers} == {"cololo", "mf36", "fans10", "p18"}
    assert r.cheapest_order.confirmed
    # basis=本 でも数え語が違う候補（n10 の 10個セット）は、Q20 のとおり換算の仮定つきで必ず to_check に残る。量が読めない yama（168円×540点）は安くなり得ないので出ない
    assert {t.plan.offer.mall_item_code for t in r.to_check if "counter_assumed" in t.plan.reasons} == {"n10"}


# --- 数え語が複数のグループ（basis が個）: 主グループと違う数え語 -----------------------------------

def kairo():
    return [off("m1", "貼るカイロ 30枚入", 600), off("m2", "貼るカイロ 60枚入", 1500), off("m3", "貼るカイロ 10枚入", 300),
            off("g1", "ぬくぬく日和 貼る 10個", 165, ship="separate"), off("g2", "ホッカイロ 60個", 5000), off("none1", "カイロ 貼る", 100)]


def test_other_count_unit_goes_to_the_main_group_to_check_with_one_ko_is_one_mai():
    r = compare(kairo(), desired_quantity=50)
    assert r.main_count_unit == "枚" and r.cheapest_order.offer.mall_item_code == "m1"
    codes = {t.plan.offer.mall_item_code for t in r.to_check}
    assert "g1" in codes and "g2" not in codes                                 # 5,000 円×1 は高い。数量 none の none1 は仮定を置かない
    t = by(r, "g1")
    assert t.conditions[0]["text"].startswith("1個が1枚なら、送料別。") and t.plan.reasons == ["counter_assumed", "shipping_separate"]
    assert t.plan.n == 5 and t.plan.order_quantity == 50 and t.plan.label == "1枚あたり"
    assert "g1" not in [p.offer.mall_item_code for p in r.order_plans]
    by_unit = {g.count_unit: g for g in r.groups}
    assert by_unit["個"].cheapest_order.offer.mall_item_code in ("g1", "g2")     # 個のグループ自身の結果は従来どおり


def test_cross_count_unit_assumption_never_wins_and_old_behaviour_stays_for_the_group_results():
    r = compare(kairo(), desired_quantity=50)
    assert r.cheapest_order.confirmed and r.cheapest_order.offer.mall_item_code != "g1"
    d = service._comparison_to_dict(r)
    g1 = next(x for x in d["to_check"] if x["item_code"] == "g1")
    assert g1["provisional_order_unit_price"] is not None and g1["order_unit_price"] is None
    assert any("換算を仮定" in c for c in d["caveats"])


def test_no_cross_unit_assumption_without_a_desired_quantity_or_with_one_group():
    assert compare(kairo()).to_check == []
    only_mai = compare([o for o in kairo() if o.mall_item_code.startswith("m")], desired_quantity=50)
    assert not any("counter_assumed" in t.plan.reasons for t in only_mai.to_check)
