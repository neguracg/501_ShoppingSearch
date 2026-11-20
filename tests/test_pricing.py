"""WP3-2: 価格比較（basis・グループ・include/exclude・caveat）。カテゴリ非依存。自作の確認（緑は証明ではない）。"""
import pytest

from fakes import make_offer
from shopping.pricing import SPEC_CAVEAT, compare, total_price
from shopping.quantity import parse_quantity


def off(code, name, price, ship="included", fee=None, quantity=True):
    o = make_offer(code, name=name, price=price, shipping_status=ship, shipping_fee=fee)
    if quantity:
        o.quantity = parse_quantity(name)
    return o


def codes(offers):
    return [o.mall_item_code for o in offers]


# 洗剤（質量）・水（容量）・電池（個数のみ）・パネル（電力）・ロール（個数＋長さ）の 5 カテゴリ
DETERGENT = [off("d1", "洗濯洗剤 詰め替え 900g×6", 2700), off("d2", "洗濯洗剤 詰め替え 1.5kg×4袋", 3000),
             off("d3", "洗濯洗剤 詰め替え 400g", 300)]
WATER = [off("w1", "ミネラルウォーター 2L×9本", 1200), off("w2", "ミネラルウォーター 500ml×24本", 1500),
         off("w3", "ミネラルウォーター 2L×6本", 900)]
BATTERY = [off("b1", "単3電池 40本", 2000), off("b2", "単3電池 20本", 1200), off("b3", "単3電池 100本", 4500)]
PANEL = [off("p1", "ソーラーパネル 100W×2", 20000), off("p2", "ソーラーパネル 200W", 30000)]
ROLL = [off("r1", "トイレットペーパー 12ロール×4パック", 1980), off("r2", "トイレットペーパー 12ロール×6", 2800)]


# --- 自動 basis と単価 ---------------------------------------------------------------

def test_mass_auto_basis_groups_different_sizes_together():
    r = compare(DETERGENT)
    assert (r.basis, r.basis_label) == ("g", "100gあたり")
    assert len(r.groups) == 1 and r.groups[0].dimension == "mass" and r.groups[0].basis == "g"
    # d1: 2700/5400g*100=50.0、d2: 3000/6000g*100=50.0、d3: 300/400*100=75.0
    assert codes(r.groups[0].offers) == ["d1", "d2", "d3"]
    assert r.groups[0].offers[0].unit_price == pytest.approx(50.0)
    assert r.groups[0].offers[0].unit_price_label == "100gあたり"
    assert r.cheapest_unit_price.mall_item_code == "d1"      # 同値は商品価格が安い方
    assert r.cheapest_price.mall_item_code == "d3"            # 商品価格最安は別物


def test_volume_auto_basis():
    r = compare(WATER)
    assert (r.basis, r.basis_label) == ("ml", "100mlあたり")
    # w1 1200/18000*100=6.667、w2 1500/12000*100=12.5、w3 900/12000*100=7.5
    assert codes(r.groups[0].offers) == ["w1", "w3", "w2"]


def test_count_only_goes_to_piece_basis():
    r = compare(BATTERY)
    assert (r.basis, r.basis_label) == ("個", "1個あたり")
    assert r.groups[0].dimension == "count"
    assert codes(r.groups[0].offers) == ["b3", "b1", "b2"]   # 45 / 50 / 60
    assert r.groups[0].offers[0].unit_price == pytest.approx(45.0)
    assert r.groups[0].offers[0].unit_price_label == "1個あたり"


def test_power_and_count_with_length():
    r = compare(PANEL)
    assert (r.basis, r.basis_label) == ("W", "1Wあたり")
    assert codes(r.groups[0].offers) == ["p1", "p2"]          # 100 / 150
    r = compare(ROLL)
    assert r.basis == "個"                                     # 長さの記述が無ければ個数で比べる
    assert codes(r.groups[0].offers) == ["r2", "r1"]          # 38.9 / 41.25
    assert r.cheapest_unit_price.mall_item_code == "r2"


def test_length_content_uses_meter():
    o = [off("t1", "ラップ 30cm×50m 3本", 900), off("t2", "ラップ 30cm×20m 2本", 500)]
    r = compare(o)
    assert (r.basis, r.basis_label) == ("m", "1mあたり")
    assert codes(r.groups[0].offers) == ["t1", "t2"]          # 6.0 / 12.5


def test_explicit_basis_overrides_and_alias_is_normalized():
    r = compare(WATER, basis="個")
    assert (r.basis, r.basis_label, r.groups[0].dimension) == ("個", "1個あたり", "count")
    assert codes(r.groups[0].offers) == ["w2", "w1", "w3"]      # 62.5 / 133.3 / 150
    r = compare(WATER, basis="L")
    assert (r.basis, r.basis_label) == ("ml", "100mlあたり")
    r = compare(DETERGENT, basis="kg")
    assert r.basis == "g"
    r = compare(WATER, basis="ML")
    assert r.basis == "ml"


def test_invalid_basis_raises():
    with pytest.raises(ValueError):
        compare(WATER, basis="ふしぎ")


def test_majority_rule_is_strictly_more_than_half_of_high():
    mixed = [off("a", "洗剤 900g", 500), off("b", "洗剤 500g", 300), off("c", "電池 10本", 100),
             off("d", "電池 20本", 200)]
    assert compare(mixed).basis == "個"                       # ちょうど半数は「個」
    mixed.append(off("e", "洗剤 400g", 250))
    assert compare(mixed).basis == "g"                        # 3/5 で過半
    # 分母は high のみ（読めない候補は数えない）
    mixed += [off("x", "詳細は商品ページ", 100), off("y", "ご確認ください", 100), off("z", "ほか", 100)]
    assert compare(mixed).basis == "g"


# --- 単価不明 -------------------------------------------------------------------------

def test_dimension_mismatch_and_unreadable_go_to_unknown():
    offers = [off("a", "洗剤 900g×2", 1000), off("w", "水 2L×6本", 800), off("u", "洗剤 要確認", 500),
              off("l", "洗剤 900g 1.5kg", 400)]
    r = compare(offers, basis="g")
    assert codes(r.groups[0].offers) == ["a"] and r.cheapest_unit_price.mall_item_code == "a"
    assert sorted(codes(r.unknown_offers)) == ["l", "u", "w"]
    assert all(o.unit_price is None and o.unit_price_label is None for o in r.unknown_offers)
    assert any("単価を出せない候補: 3件" in c for c in r.caveats)
    assert r.cheapest_price.mall_item_code == "l"             # 商品価格の最安には単価不明も含める


def test_no_unknown_no_unknown_caveat():
    assert not any("単価を出せない" in c for c in compare(DETERGENT).caveats)


def test_all_unknown_has_no_group():
    r = compare([off("u", "要確認", 100)], basis="ml")
    assert r.groups == [] and codes(r.unknown_offers) == ["u"] and r.cheapest_unit_price is None


def test_compare_ranks_with_unrounded_values():
    a = off("a", "水 3本", 1000)    # 333.333...
    b = off("b", "水 3本", 1001)    # 333.666...
    c = off("c", "水 6本", 2000)    # 333.333...（a と同値）
    r = compare([b, c, a])
    assert r.cheapest_unit_price.mall_item_code in ("a", "c") and codes(r.groups[0].offers)[-1] == "b"


# --- 数量の取得元 ---------------------------------------------------------------------

def test_prefilled_quantity_is_used_and_missing_is_parsed():
    o = off("a", "洗剤 900g×6", 2700)
    o.quantity.count_total = 12          # 呼び出し側の値を優先
    o.quantity.measure_total = 10800.0
    n = off("n", "洗剤 900g×6", 2700, quantity=False)
    r = compare([o, n], basis="g")
    assert o.unit_price == pytest.approx(25.0) and n.unit_price == pytest.approx(50.0)
    assert n.quantity is not None and n.quantity.count_total == 6


# --- include / exclude ----------------------------------------------------------------

def test_include_and_exclude_terms_with_notes():
    offers = [off("a", "洗濯洗剤 詰め替え 濃縮 900g", 300), off("b", "洗濯洗剤 本体 900g", 400),
              off("c", "洗濯洗剤 詰め替え 業務用 5kg", 1500), off("d", "柔軟剤 詰め替え 900g", 350)]
    r = compare(offers, include_terms=["洗濯洗剤", "詰め替え"], exclude_terms=["業務用"])
    assert sorted(codes(r.groups[0].offers)) == ["a"]
    assert "含む語で除外: 2件" in r.notes and "除く語で除外: 1件" in r.notes
    r = compare(offers)
    assert r.notes == []
    r = compare(offers, include_terms=["詰め替え"])
    assert r.notes == ["含む語で除外: 1件"]
    r = compare(offers, exclude_terms=["zzz"])
    assert r.notes == []


def test_terms_match_by_nfkc_and_case_and_name_only():
    o = off("a", "ＡＢＣ洗剤 ９００ｇ", 100)
    o.caption = "詰め替え"
    assert compare([o], include_terms=["abc洗剤"]).groups
    assert not compare([o], include_terms=["詰め替え"]).groups     # 説明文は見ない


def test_filtered_out_offers_do_not_affect_cheapest_or_shipping():
    offers = [off("a", "洗剤 900g", 1000), off("bad", "洗剤 訳あり 900g", 100, ship="unknown")]
    r = compare(offers, exclude_terms=["訳あり"])
    assert r.cheapest_price.mall_item_code == "a" and r.cheapest_total.mall_item_code == "a"


# --- 常設 caveat ----------------------------------------------------------------------

@pytest.mark.parametrize("offers,kw", [
    (DETERGENT, {}), (BATTERY, {}), ([], {}), (DETERGENT, dict(include_terms=["zzz"])),
    (WATER, dict(basis="個")), ([off("u", "要確認", 1)], {}),
])
def test_standing_caveat_is_always_present(offers, kw):
    r = compare(offers, **kw)
    assert SPEC_CAVEAT in r.caveats
    assert SPEC_CAVEAT == "仕様の違い（濃縮・層数・型番・色など）は判定していません。商品名で確認してください。"


# --- 送料 -----------------------------------------------------------------------------

@pytest.mark.parametrize("ship,fee,price,expected", [
    ("included", None, 1000, 1000), ("included", 500, 1000, 1000), ("separate", 500, 1000, 1500),
    ("separate", None, 1000, None), ("unknown", None, 1000, None), ("included", None, None, None),
])
def test_total_price(ship, fee, price, expected):
    assert total_price(make_offer("a", price=price, shipping_status=ship, shipping_fee=fee)) == expected


def test_unknown_shipping_blocks_cheapest_total_with_reason():
    r = compare([off("a", "電池 20本", 1500), off("b", "電池 20本", 1000, ship="unknown")])
    assert r.cheapest_total is None and any("送料" in c for c in r.caveats)
    r = compare([off("a", "電池 20本", 1500), off("b", "電池 20本", 1000, ship="separate")])
    assert r.cheapest_total is None


def test_cheapest_total_when_all_known_and_no_shipping_caveat():
    r = compare([off("a", "電池 20本", 1500), off("b", "電池 20本", 1000, ship="separate", fee=800),
                 off("c", "電池 20本", 1400, ship="separate", fee=50)])
    assert r.cheapest_total.mall_item_code == "c"
    assert not any("送料" in c for c in r.caveats)


# --- 必要数量 -------------------------------------------------------------------------

def test_desired_quantity_is_in_basis_unit():
    r = compare(WATER, desired_quantity=15000)                  # ml
    assert r.cheapest_for_quantity.mall_item_code == "w1"       # 18000ml だけが満たす
    r = compare(WATER, desired_quantity=12000)
    assert r.cheapest_for_quantity.mall_item_code == "w3"       # 12000 以上で価格最小（900）
    r = compare(WATER, basis="L", desired_quantity=12000)       # 別名でも基準単位(ml)で解釈
    assert r.cheapest_for_quantity.mall_item_code == "w3"
    # WP14 W2（SPEC §8 Q10 の変更）: 同じ商品を n 個買って足りる。上限を付ければ範囲に収まる注文が無いことがある
    r = compare(WATER, desired_quantity=99999)
    assert r.cheapest_for_quantity is not None and r.cheapest_order.n >= 2
    r = compare(WATER, desired_quantity=99999, desired_quantity_max=100000)   # どの商品の n 個も 108,000ml になる
    assert r.cheapest_for_quantity is None and any("必要数量" in c for c in r.caveats)


def test_desired_quantity_picks_lowest_price_and_piece_basis():
    r = compare(BATTERY, desired_quantity=20)
    assert r.cheapest_for_quantity.mall_item_code == "b2"       # 20本以上で最も安い
    r = compare(BATTERY, desired_quantity=1000)                  # WP14 W2: 100本を 10 個（45,000円）が最安
    assert r.cheapest_for_quantity.mall_item_code == "b3" and r.cheapest_order.n == 10


def test_desired_quantity_ignores_unreadable_and_says_so():
    r = compare([off("x", "要確認", 10), off("b", "電池 40本", 2000)], desired_quantity=40)
    assert r.cheapest_for_quantity.mall_item_code == "b"
    assert any("必要数量の判定に使っていない" in c for c in r.caveats)


@pytest.mark.parametrize("bad", [0, -1, True, "5"])
def test_bad_desired_quantity_raises(bad):
    with pytest.raises(ValueError):
        compare(DETERGENT, desired_quantity=bad)


def test_no_desired_quantity_means_none():
    assert compare(BATTERY).cheapest_for_quantity is None


# --- 空・価格なし ---------------------------------------------------------------------

def test_empty_input_shape():
    r = compare([])
    assert r.groups == [] and r.unknown_offers == [] and r.cheapest_price is None
    assert r.cheapest_unit_price is None and r.cheapest_total is None and r.cheapest_for_quantity is None
    assert (r.basis, r.basis_label) == ("個", "1個あたり")
    assert "比較できる候補がない" in r.caveats


def test_offers_without_price_are_not_ranked():
    r = compare([off("a", "電池 20本", None), off("b", "電池 20本", 1000)])
    assert r.cheapest_price.mall_item_code == "b" and r.cheapest_unit_price.mall_item_code == "b"
    assert any("価格が不明" in c for c in r.caveats)
    assert codes(r.groups[0].offers) == ["b", "a"] and r.groups[0].offers[1].unit_price is None
