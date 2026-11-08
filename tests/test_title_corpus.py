"""AC-Q1: 実在らしい題名コーパス（tests/corpus/ の title_patterns 232件・unseen1_patterns 71件・unseen2_patterns 40件・unseen3_patterns 40件・unseen4_patterns 7件（E2E 実題名 T1〜T7）・unseen5_patterns 17件（verifier 退行形 B1〜B6）・unseen6_patterns 14件（追加E2E 実題名 E1・E2 と verifier B8）・unseen7_patterns 31件（WP12 実題名 M1〜M4・構成した M5・真値どおり high のまま残る形）
＝計452件。verifier 作成の真値つき。unseen7 は実装担当が題名の読みだけで固定）の回帰。

採点は tests/corpus/compare.py の grade と同じ規則:
  - 高信頼（high）で真値と違う（WRONG）・曖昧な題名を高信頼で返す（RISK）・例外（EXC）は 0 件であること。
  - 単価不明（low / none。安全側）は全体の 22% 以下（WP12 で 20%→22%。unseen7 は単価不明が正の題名を 15 件含む。元の 421 件は 18.3% のまま。指示書 WP12）。
真値は勝手に直さない。真値が SPEC と矛盾すると判断した題名は XFAIL に理由つきで載せる（strict: 直ったら気づく）。
自作の確認であり、独立試験（ブラインド）の代わりではない。
"""
import importlib.util
from collections import Counter
from pathlib import Path

import pytest

from shopping.quantity import parse_quantity

CORPUS_FILES = {"title_patterns": 232, "unseen1_patterns": 71, "unseen2_patterns": 40,
                "unseen3_patterns": 40,
                "unseen4_patterns": 7, "unseen5_patterns": 17, "unseen6_patterns": 14, "unseen7_patterns": 31}


def _load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / "corpus" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.P


CORPUS = [pair for name in CORPUS_FILES for pair in _load(name)]

MAX_UNKNOWN_RATIO = 0.22

# 真値が SPEC と矛盾する題名（真値は変えない）。題名 → 理由
XFAIL: dict[str, str] = {
    # 既知の限界 R2（SPEC §7）: 「串」は数え語の表に無く、「1本50g」だけを読んで 1 本×50g の high にしてしまう
    "焼き鳥 国産 鶏もも串 20串 冷凍 BBQ キャンプ 焼くだけ 1本50g 業務用":
        "R2: 表に無い数え語（串）の個数が落ち、別の数え語（1本50g）が個数の根拠になる",
}


def grade(truth, title):
    """OK / UNK（安全側の単価不明）/ WRONG / RISK / EXC。"""
    try:
        q = parse_quantity(title)
    except Exception:       # noqa: BLE001 - 例外で落ちること自体が不合格
        return "EXC"
    if q.confidence != "high":
        return "UNK"
    kind = truth[0]
    cnt, meas, dim = q.count_total, q.measure_total, q.content_dimension
    if kind == "LOW":
        return "RISK"
    if kind == "AMB":
        return "OK" if cnt in truth[1] else "WRONG"
    if kind == "c":
        return "OK" if cnt == truth[1] else "WRONG"
    if kind == "cm":
        if cnt != truth[1]:
            return "WRONG"
        if dim != truth[2] or meas is None or abs(meas - truth[3]) > 1e-6 * max(1, truth[3]):
            return "WRONG"
        return "OK"
    raise AssertionError(f"unknown truth kind: {truth!r}")


def _case(title, truth):
    marks = []
    if title in XFAIL:
        marks.append(pytest.mark.xfail(reason=XFAIL[title], strict=True))
    return pytest.param(title, truth, marks=marks, id=title[:40])


def test_corpus_is_the_expected_size_and_xfail_titles_exist():
    assert {n: len(_load(n)) for n in CORPUS_FILES} == CORPUS_FILES
    assert len(CORPUS) == 452
    titles = {t for t, _ in CORPUS}
    assert set(XFAIL) <= titles


@pytest.mark.parametrize("title,truth", [_case(t, tr) for t, tr in CORPUS])
def test_ac_q1_no_high_confidence_error(title, truth):
    assert grade(truth, title) in ("OK", "UNK")


def test_ac_q1_unknown_unit_price_is_at_most_22_percent():
    counts = Counter(grade(tr, t) for t, tr in CORPUS)
    assert counts["UNK"] / len(CORPUS) <= MAX_UNKNOWN_RATIO, dict(counts)


def test_ac_q1_high_confidence_errors_are_zero_outside_xfail():
    bad = [t for t, tr in CORPUS if t not in XFAIL and grade(tr, t) in ("WRONG", "RISK", "EXC")]
    assert bad == []
