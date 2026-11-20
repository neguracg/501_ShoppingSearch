# @owns WP13（WP14 W5(c)）宣言された総数 → 内容量 → 個数の鎖（2304 本の誤読）の自作確認。独立試験（ブラインド）の代わりではない
"""先頭の単独の個数が、内容量より後ろの個数の鎖（2 つ以上）の積と一致するなら宣言された総数の言い直し（鎖の乗数にしない）。食い違えば low。
実題名 D1〜D3 は tests/corpus/unseen8_patterns.py に全文で固定。ここは機構ごとの別の言い回し（区切り × x *・空白、数え語 本・袋・ロール・缶・個、
括弧あり/なし、計/合計 あり/なし）と、不変の形。"""
import pytest

from shopping.quantity import parse_quantity


def hi(text):
    q = parse_quantity(text)
    assert q.confidence == "high", (text, q)
    return q


@pytest.mark.parametrize("text,total,measure", [
    # 区切り
    ("天然水 48本 500ml×24本×2ケース", 48, 24000),
    ("天然水 48本 500ml x 24本 x 2ケース", 48, 24000),
    ("天然水 48本 500ml * 24本 * 2ケース", 48, 24000),
    ("天然水 48本 500ml 24本 2ケース", 48, 24000),
    ("天然水 48本 500ml 24本入り 2ケース", 48, 24000),
    # 括弧・前置き
    ("天然水 [48本] [500ml 24本入り 2ケース]", 48, 24000),
    ("天然水 【48本】500ml×24本×2ケース", 48, 24000),
    ("天然水 合計48本 500ml×24本×2ケース", 48, 24000),
    ("天然水 計48本 500ml×24本×2箱", 48, 24000),
    # 数え語
    ("洗剤 12袋 900g×6袋×2セット", 12, 10800),
    ("洗剤 12袋 900g 6袋入り 2セット", 12, 10800),
    ("缶コーヒー 48缶 185g×24缶×2ケース", 48, 8880),
    ("缶コーヒー 48缶 185g 24缶入り 2ケース", 48, 8880),
    ("お菓子 60個 30g×12個×5袋", 60, 1800),
    ("トイレットペーパー 96ロール 30m 12ロール×8パック", 96, 2880),
    ("トイレットペーパー 96ロール 30m×12ロール×8パック", 96, 2880),
    # 指示書 WP13 の表
    ("24本 500ml 12本×2ケース", 24, 12000),
    ("12本 2L×6本×2ケース", 12, 24000),
    ("洗剤 6袋 900ml×3袋×2セット", 6, 5400),
])
def test_declared_total_equal_to_the_chain_product_is_the_total(text, total, measure):
    q = hi(text)
    assert q.count_total == total and q.measure_total == pytest.approx(measure)


@pytest.mark.parametrize("text", [
    "天然水 48本 500ml×12本×2ケース",
    "天然水 48本 500ml 12本入り 2ケース",
    "洗剤 6袋 900g×4袋×2セット",
    "缶 24缶 185g×12缶×3ケース",
    "トイレットペーパー 96ロール 30m 12ロール×4パック",
    "天然水 48本 500ml 24本×3ケース",
])
def test_declared_total_that_disagrees_with_the_chain_is_low(text):
    assert parse_quantity(text).confidence == "low"


@pytest.mark.parametrize("text,total", [
    ("40本 10本×4パック", 40),                    # 内容量が無い（WP8 の捨てた数の検査）
    ("48本 500ml 48本", 48), ("48本 500ml", 48), ("48本入 500ml×48本", 48),
    ("600mL × 24本 2ケース", 48), ("500ml 24本入り 2ケース", 48), ("2L 12本 6本×2ケース", 12),
    ("PET500ml 500ml×24本", 24), ("500ml×24本", 24), ("12ロール×4パック(48ロール)", 48),
    ("水 6本 500ml×4", 24),                       # 後ろが単独の個数は従来の掛け算（S2）
    ("3個入り 400ml×3セット", 9),                  # 先頭に 入 が付く（P4）
    ("ハンドタオル 2枚組 34cm×35cm ×2セット", 4),   # 後ろが単独の容器語（P4）
])
def test_unchanged_forms(text, total):
    assert hi(text).count_total == total


def test_wp8_t3_stays_low():
    assert parse_quantity("【48本】天然水 500ml 48本 2ケース").confidence == "low"
