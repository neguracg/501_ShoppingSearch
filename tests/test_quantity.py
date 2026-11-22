"""WP3-1: 数量の読み取り（個数 × 1個あたり内容量）。カテゴリ非依存。自作の確認（緑は証明ではない）。"""
import pytest

from shopping import quantity
from shopping.quantity import UNITS, parse_quantity


def info(text):
    q = parse_quantity(text)
    return (q.confidence, q.count_total, q.count_unit, q.content_amount, q.content_dimension,
            q.content_unit, q.measure_total)


# --- 3 カテゴリ以上の代表例 ---------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("洗濯洗剤 詰め替え 900g×6", ("high", 6, "個", 900.0, "mass", "g", 5400.0)),
    ("洗濯洗剤 詰め替え 0.9kg×6袋", ("high", 6, "袋", 900.0, "mass", "g", 5400.0)),
    ("単3電池 40本", ("high", 40, "本", None, None, None, None)),
    ("ソーラーパネル 100W×2", ("high", 2, "個", 100.0, "power", "W", 200.0)),
    ("ミネラルウォーター 2L×9本", ("high", 9, "本", 2000.0, "volume", "ml", 18000.0)),
    ("トイレットペーパー 12ロール×4パック", ("high", 48, "ロール", None, None, None, None)),
    ("モバイルバッテリー 10000mAh", ("high", 1, "個", 10000.0, "charge", "mAh", 10000.0)),
    ("ポータブル電源 1.5kWh", ("high", 1, "個", 1500.0, "energy", "Wh", 1500.0)),
    ("ラップ 30cm×50m 3本", ("high", 3, "本", 50.0, "length", "m", 150.0)),
    ("サプリ 120粒×3袋", ("high", 360, "粒", None, None, None, None)),
])
def test_representative_categories(text, expected):
    assert info(text) == expected


@pytest.mark.parametrize("text,count,unit", [
    ("12ロール×4袋", 48, "ロール"), ("12ロール×3パック", 36, "ロール"), ("12R×6", 72, "ロール"),
    ("12ロール x 4パック", 48, "ロール"), ("12ロール入×3", 36, "ロール"),
    ("（12ロール）×4セット", 48, "ロール"), ("１２ロール×４袋", 48, "ロール"), ("12ロール＊6", 72, "ロール"),
    ("12ロール入り 4パック", 48, "ロール"), ("12ロール×4袋×2箱", 96, "ロール"), ("12ロール", 12, "ロール"),
    ("12r×6", 72, "ロール"), ("24本入り×2ケース", 48, "本"), ("100枚入×10箱", 1000, "枚"),
    ("6個セット", 6, "個"), ("3個セット×2", 6, "個"), ("5足組", 5, "足"), ("30回分", 30, "回分"),
    ("500ml×24本×2ケース", 48, "本"), ("2LX6本", 6, "本"), ("12ロールX4パック", 48, "ロール"),
])
def test_count_notation_variants(text, count, unit):
    q = parse_quantity(text)
    assert (q.confidence, q.count_total, q.count_unit) == ("high", count, unit)
    assert q.evidence


def test_count_unit_is_the_inner_one_when_two_levels():
    assert parse_quantity("12ロール×4パック").count_unit == "ロール"
    assert parse_quantity("24本入り×2ケース").count_unit == "本"


def test_content_only_means_one_piece_and_nothing_at_all_is_none():
    q = parse_quantity("ミネラルウォーター 2L")
    assert (q.confidence, q.count_total, q.count_unit, q.measure_total) == ("high", 1, "個", 2000.0)
    q = parse_quantity("おいしいお茶")
    assert q.confidence == "none" and q.count_total is None and q.evidence == ""
    q = parse_quantity("")
    assert q.confidence == "none"
    assert parse_quantity(None).confidence == "none"


def test_no_content_means_measure_total_none():
    q = parse_quantity("単3電池 40本")
    assert q.content_amount is None and q.content_dimension is None and q.measure_total is None


# --- 換算表 ------------------------------------------------------------------------

@pytest.mark.parametrize("text,dim,unit,amount", [
    ("500ml", "volume", "ml", 500), ("500mL", "volume", "ml", 500), ("500cc", "volume", "ml", 500),
    ("2L", "volume", "ml", 2000), ("1.5リットル", "volume", "ml", 1500), ("２ｌ", "volume", "ml", 2000),
    ("900g", "mass", "g", 900), ("1.2kg", "mass", "g", 1200), ("500mg", "mass", "g", 0.5),
    ("30m", "length", "m", 30), ("50cm", "length", "m", 0.5), ("100mm", "length", "m", 0.1),
    ("1.5km", "length", "m", 1500), ("20メートル", "length", "m", 20),
    ("100W", "power", "W", 100), ("1.2kW", "power", "W", 1200), ("100ワット", "power", "W", 100),
    ("5000mAh", "charge", "mAh", 5000), ("2Ah", "charge", "mAh", 2000),
    ("300Wh", "energy", "Wh", 300), ("2kWh", "energy", "Wh", 2000),
])
def test_unit_table_conversion(text, dim, unit, amount):
    q = parse_quantity("商品 " + text)
    assert q.confidence == "high" and q.content_dimension == dim and q.content_unit == unit
    assert q.content_amount == pytest.approx(amount) and q.count_total == 1


def test_adding_a_row_to_the_table_adds_a_unit(monkeypatch):
    assert parse_quantity("チョコ 5oz").content_amount is None
    monkeypatch.setitem(UNITS, "oz", ("mass", 28.35))
    q = parse_quantity("チョコ 5oz")
    assert q.content_dimension == "mass" and q.content_amount == pytest.approx(141.75)
    monkeypatch.setitem(quantity.COUNTERS, "杯", "杯")
    assert parse_quantity("コーヒー 20杯×2").count_total == 40


def test_longer_unit_wins_over_shorter_prefix():
    assert parse_quantity("10000mAh").content_unit == "mAh"
    assert parse_quantity("5kWh").content_amount == 5000
    assert parse_quantity("20kg").content_amount == 20000
    assert parse_quantity("5mm").content_amount == pytest.approx(0.005)


def test_unit_inside_a_word_is_not_a_unit():
    assert parse_quantity("2LED電球").confidence == "none"
    assert parse_quantity("3Lサイズ 3枚").content_amount is None
    assert parse_quantity("Tシャツ 3Lサイズ 3枚").count_total == 3
    assert parse_quantity("SH-12M 3個").count_total == 3 and parse_quantity("SH-12M 3個").content_amount is None


# --- ×でつなぐ、寸法 ----------------------------------------------------------------

@pytest.mark.parametrize("text,amount", [
    ("ラップ 30cm×50m", 50), ("ラップ 幅45cm×長さ100m", 100), ("ホース 20m×1cm", 20),
    ("テープ 50mm×25m", 25), ("マット 34×85cm", 0.85),
])
def test_dimension_notation_takes_the_larger_one(text, amount):
    q = parse_quantity(text)
    assert q.confidence == "high" and q.content_dimension == "length"
    assert q.content_amount == pytest.approx(amount) and q.count_total == 1


def test_bare_number_before_times_is_not_a_count():
    q = parse_quantity("マット 34×85cm")
    assert q.count_total == 1
    q = parse_quantity("×6")
    assert q.confidence == "none"


def test_bare_number_after_content_or_count_multiplies():
    assert parse_quantity("900g×6").count_total == 6
    assert parse_quantity("12ロール×4").count_total == 48
    assert parse_quantity("24本入り×2").count_total == 48


# --- 数量にしない表記 ---------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "ポイント10倍", "最大50%OFF", "送料無料", "1000円ポッキリ", "10%OFFクーポン", "ポイント最大5倍 送料無料",
    "2,980円", "先着100個限定", "3個以上で送料無料",
])
def test_promo_and_price_are_not_quantities(text):
    assert parse_quantity("商品名 " + text).confidence == "none"


def test_promo_does_not_disturb_real_quantity():
    q = parse_quantity("ポイント10倍 洗濯洗剤 900g×6 最大50%OFF 送料無料")
    assert (q.confidence, q.count_total, q.measure_total) == ("high", 6, 5400)


def test_equivalents_and_per_unit_descriptions_are_not_counted():
    assert parse_quantity("12ロール（24ロール分）").count_total == 12
    assert parse_quantity("12ロール×4袋 通常の96ロール相当").count_total == 48
    q = parse_quantity("12ロール×4袋 1ロールあたり 25m")
    assert q.count_total == 48 and q.content_amount == 25
    q = parse_quantity("12ロール×4袋 1ロール30m")
    assert (q.count_total, q.content_amount, q.measure_total) == (48, 30, 1440)
    q = parse_quantity("ミネラルウォーター 24本 100mlあたり0.5円")
    assert q.count_total == 24 and q.content_amount is None


# --- 矛盾・曖昧 --------------------------------------------------------------------

def test_conflicting_counts_are_low_and_everything_is_none():
    for text in ["電池 48本 送料無料 72本", "12ロール×4袋 / 12ロール×6袋", "お試し1個 or 3個セット"]:
        q = parse_quantity(text)
        assert q.confidence == "low" and q.count_total is None and q.measure_total is None
        assert q.content_amount is None and q.content_dimension is None and q.content_unit is None
        assert q.evidence


def test_conflicting_content_same_dimension_is_low():
    q = parse_quantity("洗剤 900g 1.5kg")
    # WP16 U2a（SPEC Q14 改訂）: 内容量だけが決まらない low は題名に個数の読みがある時だけ総数・数え語を残す（content_ambiguous）。
    # 個数の読みが無く既定の 1個 になる形は総数を残さない（B1・C4。readings は出る）。内容量は null のまま
    assert q.confidence == "low" and q.low_reason == "content_ambiguous" and q.count_total is None and q.content_amount is None
    assert q.readings["counts"] == [] and q.readings["contents"]["mass"] == [900.0, 1500.0]
    q = parse_quantity("水 500ml×24本 2L×12本")
    assert q.confidence == "low"


def test_same_values_repeated_are_not_a_conflict():
    assert parse_quantity("12ロール×4袋 合計48ロール").count_total == 48
    assert parse_quantity("12ロール×4袋 1袋12ロール入り").count_total == 48
    assert parse_quantity("水 2L×6本 2000ml").content_amount == 2000
    assert parse_quantity("1箱24本入り").count_total == 24


def test_different_dimensions_are_not_a_contradiction_first_one_is_used():
    q = parse_quantity("モバイルバッテリー 10000mAh 22.5W")
    assert q.confidence == "high" and q.content_dimension == "charge"


def test_implausible_count_is_low():
    assert parse_quantity("9999999個").confidence == "low"


def test_content_is_attached_wherever_it_appears():
    a = parse_quantity("ダブル 30m 12ロール×4パック")
    b = parse_quantity("12ロール×4パック ダブル 30m")
    assert (a.count_total, a.content_amount, a.measure_total) == (48, 30, 1440)
    assert (b.count_total, b.content_amount, b.measure_total) == (48, 30, 1440)
    q = parse_quantity("ミネラルウォーター 2L ペットボトル 9本")
    assert q.count_total == 9 and q.content_amount == 2000


def test_does_not_match_inside_words():
    assert parse_quantity("12 RICH PAPER").confidence == "none"
    assert parse_quantity("max2x3 BOX").confidence == "none"


def test_hostile_huge_numbers_never_raise():
    # 出店者が書く商品名は信用しない: 巨大な数字列で float が inf になって int() が落ちない
    for text in ["9" * 400 + "個", "洗剤 " + "9" * 400 + "g×6", "1" * 5000 + "ml", "12ロール×" + "9" * 50]:
        assert parse_quantity(text).confidence in ("none", "high", "low")
    assert parse_quantity("1,000ml×3").content_amount == 1000
