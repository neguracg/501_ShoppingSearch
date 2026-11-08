# @owns WP12 商品名の誤読4種（範囲・量/単位・次元違いの鎖・装飾記号）と日本語に接した型番の自作確認。独立試験の代わりではない
"""WP12: WP11-2 の実測（実 API 893 件）で見つかった、商品名の読みで高信頼のまま誤る形（SPEC §7 P0 の徹底・R8）。
実題名は tests/corpus/unseen7_patterns.py に全文で固定した。ここは各機構の別の言い回し（ヨコテン）と、掛けない形。

  M1 範囲の端の量（4~8kg・お誕生~5,000g）は内容量にしない／範囲の個数（3~5箱）は low／型番の語に付いた個数
     （S54枚×4パック）を読み飛ばした連結位置の個数は low（P6）
  M2 量/単位（mg/L・mg/kg）の分子は内容量にしない（分母が計量単位。個数の分母 480ml/1個 と同じ次元の択一 5kg/10kg は除く）
  M3 内容量が個数と同じ鎖に無く、個数が別の次元の量の鎖に付く時は low（2000m 2L×6本）
  M4 単位の直後に装飾記号がつながる量（2M◇）は low
  M5 型番の語を ASCII の連なりへ広げる（インクIC6CL80・IC6CL80互換80L・IC6CL80、80L）
"""
import pytest

from shopping.quantity import parse_quantity

# ---- M1 範囲 ----
# 範囲の量は採らず、個数だけ high（内容量は読まない）
RANGE_MEASURE_COUNT_ONLY = [
    ("おむつ テープ 54枚×4パック 6〜11kg", 216),
    ("おむつ パンツ 体重9～14kg 40枚×3袋", 120),
    ("おむつ 新生児 お誕生～3,000g 70枚×6パック(420枚)", 420),
    ("紙おむつ 12~17kg 36枚×4パック", 144),
    ("おむつ 4~8kg テープ 62枚×4個入", 248),
]
# 範囲の個数・採用した内容量と食い違う範囲の量は low
RANGE_LOW = [
    "ティッシュ 3~5箱セット",
    "お試し 3〜5個入り 洗剤 500ml",
    "洗剤 500ml 3〜5個",
    "トイレットペーパー ダブル 30〜60ロール 定期便",
    "ミルク 800g×2缶 4〜8kg",
]
# 型番の語に付いたサイズ記号の個数（S54枚）を読み飛ばした連結位置の個数は low
MODEL_PREFIXED_COUNT_LOW = [
    "おむつ S54枚×4パック 新生児",
    "おむつ M52枚×4個入",
    "おむつ L44枚×3パック(132枚)",
    "ティッシュ SS200組×5箱",
    "トイレットペーパー NB12R×4パック",
]
# 掛けない形
RANGE_STAY_HIGH = [
    ("おむつ S 54枚×4パック 新生児", 216, None),
    ("ティッシュ 200組×5箱", 1000, None),
    ("トイレットペーパー 12R×4パック", 48, None),
    ("ミルク 800g×2缶 0~12ヶ月", 2, 1600.0),                 # 12ヶ月は数え語の表の例外（月）。範囲の個数にしない
    ("お米 5kg 〜お買い得〜 2袋", 2, 10000.0),                # 波線で挟んだ飾り
    ("〜500ml〜 ミネラルウォーター 24本", 24, 12000.0),
    ("お得〜2L×6本 お茶", 6, 12000.0),                       # 波線が語に付いても、直後に ×数 が続く鎖の量は範囲にしない
]

# ---- M2 量/単位 ----
RATE_NUMERATOR_HIGH = [
    ("炭酸水 500ml×24本 シリカ 50mg/L", 24, 12000.0),
    ("水 1.5L×8本 ミネラル 120mg/L", 8, 12000.0),
    ("ドリンク 100ml×30本 カフェイン 50mg/kg", 30, 3000.0),
    ("炭酸水 42.5mg/L 500ml×24本", 24, 12000.0),
    ("ミネラルウォーター 硬度 300mg/L 2L×6本", 6, 12000.0),
]
RATE_STAY = [
    ("洗剤 480ml/1個", "high"),               # 個数の分母
    ("お米 5kg/10kg 選べる", "low"),          # 同じ次元の分母は択一（WP8 M3）
]

# ---- M3 次元違いの鎖 ----
DIM_MISMATCH_LOW = [
    "お茶 2000m 2L×6本",
    "水 500g 500ml×24本",
    "お米 2kg 2L×6本",
    "水 1000m 1L×12本",
    "水 30m 500ml×24本",
    "お茶 2m 500ml×24本",
]
DIM_STAY_HIGH = [
    ("ポータブル電源 1000Wh 1000W", 1, 1000.0),          # どちらにも個数が付かない
    ("モバイルバッテリー 10000mAh 22.5W", 1, 10000.0),
    ("【2m 2本組】60W対応 USB充電ケーブル", 2, 4.0),      # 個数が付く量が採用する次元
]

# ---- M4 装飾記号 ----
DECORATED_LOW = [
    "乾電池 単4 20本 2M◇ 送料込",
    "単3 4本×10パック 3m★ 送料無料",
    "ケーブル 5本 2m◆ 黒",
    "水 500ml×24本 1L☆ 送料無料",
    "乾電池 単3 40本 1.5m▲ 送料込",
]
DECORATED_STAY_HIGH = [
    ("水 500ml×24本 送料無料★", 24, 12000.0),            # 量の直後でなく数え語の直後・文末
    ("ケーブル 2m 3本 ★送料無料", 3, 6.0),
    ("水 500ml※24本", 24, 12000.0),                      # ※ は注記（記号 So ではない）
    ("乾電池 単4 40本 ◇送料込", 40, None),               # 記号が量に付かない
]

# ---- M5 日本語に接した型番 ----
JP_MODEL_LOW = [
    "エプソン純正インクIC6CL80 増量 80L",
    "IC6CL80互換80L",
    "エプソン IC6CL80、80L",
    "インクIC6CL80互換 80L 6色",
    "エプソン用IC6CL80L互換 80L",
    "洗剤 詰め替え SK-500互換 500ml",
    "米 KG5000国産 5000g",
    "ポータブル電源 1000Wh 日本語EP1000",
]
JP_MODEL_STAY_HIGH = [
    ("インク IC6CL80 100L", 1, 100000.0),                # 数字が違う
    ("水 2L H2O 天然水", 1, 2000.0),                      # 1 桁
    ("日焼け止め SPF50+ PA++++ 50g", 1, 50.0),            # ASCII の記号でつながる語は従来どおり1語（型番の語にならない）
    ("サントリー 天然水 PET500ml 500ml×24本", 24, 12000.0),  # 鎖の一部の量（WP9 B8）
]


@pytest.mark.parametrize("title,count", RANGE_MEASURE_COUNT_ONLY)
def test_m1_range_measure_is_not_the_content(title, count):
    q = parse_quantity(title)
    assert (q.confidence, q.count_total, q.content_amount) == ("high", count, None)


@pytest.mark.parametrize("title", RANGE_LOW + MODEL_PREFIXED_COUNT_LOW)
def test_m1_range_count_and_skipped_link_count_are_low(title):
    assert parse_quantity(title).confidence != "high"


@pytest.mark.parametrize("title,count,total", RANGE_STAY_HIGH + RATE_NUMERATOR_HIGH + DIM_STAY_HIGH
                         + DECORATED_STAY_HIGH + JP_MODEL_STAY_HIGH)
def test_forms_that_must_stay_high(title, count, total):
    q = parse_quantity(title)
    assert q.confidence == "high" and q.count_total == count and q.measure_total == total, q


@pytest.mark.parametrize("title,confidence", RATE_STAY)
def test_m2_count_denominator_and_same_dimension_alternative_unchanged(title, confidence):
    assert parse_quantity(title).confidence == confidence


@pytest.mark.parametrize("title", DIM_MISMATCH_LOW)
def test_m3_count_attached_to_a_different_dimension_is_low(title):
    assert parse_quantity(title).confidence == "low"


def test_m3_a_basis_dimension_that_carries_the_count_is_still_read():
    # 比べる単位に容量を指定しても、既定の次元は変わらない。指定した次元（個数が付く量）を使う時は従来どおり読める
    q = parse_quantity("お茶 2000m 2L×6本", "ml")
    assert (q.confidence, q.count_total, q.measure_total) == ("high", 6, 12000.0)


@pytest.mark.parametrize("title", DECORATED_LOW)
def test_m4_quantity_glued_to_a_decorative_symbol_is_low(title):
    assert parse_quantity(title).confidence == "low"


@pytest.mark.parametrize("title", JP_MODEL_LOW)
def test_m5_model_word_attached_to_japanese_is_a_model_word(title):
    assert parse_quantity(title).confidence != "high"
