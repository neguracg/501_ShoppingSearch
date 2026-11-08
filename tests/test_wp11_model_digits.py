# @owns WP11-4 単独の内容量の数字が型番の語の内側にも現れる時は low（quantity._standalone_measure_digits_in_model）の自作確認。独立試験の代わりではない
"""WP11-4: WP9 の E1 は「同じ量（数字＋単位）が型番の語の内側にもある」形だけを見る。型番が IC6CL80（単位なし）だと
`80L` が 80,000ml の high のまま残った（ChatGPT 再試験。実題名は 2026-11-09 に実 API から取り直した全文）。

E1 を「単独で立つ内容量の数字が、同じ題名の型番の語（英字の後ろに数字が続く ASCII の語）の内側に数字として現れる時も low」に
広げる。鎖の一部の量（PET500ml 500ml×24本）は掛けない（WP9 B8）。1 桁の数字は同一性の根拠にしない。
"""
import pytest

from shopping.quantity import MODEL_DIGITS_MIN, parse_quantity

# 実題名（2026-11-09 実 API。検索語: エプソン IC6CL80 純正インク 6色パック・エプソン80l・エプソン インク 80L 純正）
REAL_LOW = [
    "エプソン 純正インク IC6CL80M 6色パック（黒のみ80L） インクカートリッジ【EPSON】",
    "EPSON｜エプソン IC6CL80 純正プリンターインク とうもろこし(標準容量) 6色パック[とうもろこし エプソン80l IC6CL80]",
    "EPSON｜エプソン IC6CL80M 純正プリンターインク とうもろこし(ブラックのみ増量) 6色パック[とうもろこし エプソン80l IC6CL80M]",
]

# 同じ機構の別の形（型番に単位が付かない。数字が同じ）
VARIANTS_LOW = [
    "インク IC6CL80 80L 6色パック",
    "エプソン80l IC6CL80",
    "洗剤 SK-500 500ml 詰め替え",
    "米 KG-5000 5000g 国産",
    "ポータブル電源 1000Wh EP-1000",
    "ポータブル電源 1000Wh MES-TR1000 大容量",
    "ゴミ袋 GP45 45L 黒",
]

# 掛けない形
STAY_HIGH = [
    ("サントリー 天然水 PET500ml 500ml×24本", 24, 500.0),     # 鎖の一部の量（WP9 B8）
    ("KP-500ml 500ml 6本", 6, 500.0),
    ("UHA-30g 30g 3袋", 3, 30.0),
    ("インク IC6CL80 80L×2個", 2, 80000.0),                   # 鎖の一部（SPEC R7。WP10 の外れ値の網で拾う）
    ("ナッツ 1kg No.1 国産", 1, 1000.0),                       # 1 桁の数字は根拠にしない
    ("水 2L H2O 天然水", 1, 2000.0),
    ("洗剤 900g LR6 詰め替え", 1, 900.0),
    ("インク IC6CL80 100L", 1, 100000.0),                      # 数字が違う
    ("水 500ml 500ml", 1, 500.0),                              # 量の語どうしは型番ではない（500ml は先頭が数字）
    ("水 2L 2リットル ラベルレス", 1, 2000.0),
    ("トイレットペーパー 60m ダブル 12ロール", 12, 60.0),
]


@pytest.mark.parametrize("title", REAL_LOW + VARIANTS_LOW)
def test_standalone_measure_digits_inside_a_model_word_is_low(title):
    q = parse_quantity(title)
    assert q.confidence == "low", q
    assert q.count_total is None and q.measure_total is None


@pytest.mark.parametrize("title,count,amount", STAY_HIGH)
def test_other_forms_stay_high(title, count, amount):
    q = parse_quantity(title)
    assert q.confidence == "high" and q.count_total == count and q.content_amount == amount, q


def test_the_digits_minimum_is_two():
    assert MODEL_DIGITS_MIN == 2


def test_the_rule_does_not_apply_without_a_standalone_measure():
    # 量が無い・個数だけの題名は E1・WP11-4 の対象外（従来どおり）
    q = parse_quantity("エプソン ICBK80L 純正 インク 3個")
    assert q.confidence == "high" and q.count_total == 3
    assert parse_quantity("エプソン IC6CL80 純正インク").confidence != "high"


def test_unicode_variants_of_the_same_number_are_the_same():
    # 全角の数字・大文字小文字は正規化されて同じ数字として扱う
    assert parse_quantity("インク ＩＣ６ＣＬ８０ ８０Ｌ 6色").confidence == "low"
    assert parse_quantity("インク ic6cl80 80l 6色").confidence == "low"
