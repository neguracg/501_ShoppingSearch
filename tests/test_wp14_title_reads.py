# @owns WP14 W5(a)(b) 題名の読み取り（途中切れの末尾・N<数え語> M個パック）の自作確認。独立試験（ブラインド）の代わりではない
"""W5(a): × の鎖の言い直しが題名の途中切れで末尾に単独で残っても食い違いにしない（既存の挙動の確認）。
W5(b): N<数え語> M個パック／M個セット（内側に 入 も × も無い）は合計か 1 つあたりか決まらないので low。"""
import pytest

from shopping.quantity import parse_quantity


# --- (b) -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "文化たきつけ 36本 2個パック 薪用着火剤 焚き火 薪ストーブ 暖炉",       # 実: formira88:10754141 は 72 本 high だった
    "文化たきつけ 36本 2個セット",
    "コピー用紙 500枚 2個セット",
    "洗剤 12袋 3個ケース",
    "ペン 12本 5個パック",
    "2個パック 36本",                                                    # 外側が先の並び
])
def test_n_counter_then_m_ko_container_is_low(text):
    assert parse_quantity(text).confidence == "low"


@pytest.mark.parametrize("text,total", [
    ("文化たきつけ 18本入り×2個セット", 36),
    ("単3 4本入 3パック", 12),
    ("コピー用紙 500枚 5冊", 2500),
    ("36本入り 2個パック", 72),                  # 内側に 入 がある
    ("1箱 24本入り 2個パック", 48),
    ("洗剤 400ml 1個 3個セット", 3),             # 1 は 1 個あたりの説明（WP8）
    ("36本 2パック", 72),                         # 個＋容器語の複合ではない（従来の容器語の連結）
])
def test_forms_outside_the_composite_are_unchanged(text, total):
    q = parse_quantity(text)
    assert q.confidence == "high" and q.count_total == total


# --- (a) ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "スコッティ 100m 1セット（48ロール：12ロール×4パック）には48ロール（12ロール",
    "トイレットペーパー 48ロール 12ロール×4パック 12ロール",
    "トイレットペーパー 12ロール×4パック（48ロール）（12ロール",
    "水 24本 500ml×12本×2ケース 12本",
])
def test_lone_restatement_of_the_chain_inner_count_at_the_end_is_not_a_mismatch(text):
    q = parse_quantity(text)
    assert q.confidence == "high" and q.count_total in (24, 48)


def test_a_lone_count_without_a_chain_is_still_a_mismatch():
    assert parse_quantity("トイレットペーパー 48ロール（12ロール").confidence == "low"
