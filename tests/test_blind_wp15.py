# @owns WP15 段A ブラインド試験（未確定の単価を確定値として出さない・注文額の種類・題名の判定の出力）
"""WP15 段A ブラインド試験（2026-11-21）。根拠は docs/SPEC.md の §8 Q21〜Q24・Q14・Q16・Q3・Q8、§7 の
caption_conflict、§10（MCP の説明）、AC13・AC16・AC17・AC18・AC-W9 だけ（src と実装担当の説明は見ない）。
期待値は全て手計算（式を各試験のコメントに残す）。実装担当は読まない・編集しない。

入口: service.compare_offers / search_products / find_regular_item（偽 Adapter。実 API・本番は使わない）と、
mcp_server.build_server の tools/list（in-process）。数量の読み取りと価格比較は実物を通す（業務ロジックは再実装しない）。

試験している契約:
  Q21  未確定の単価（quantity_from_caption・caption_conflict・price_varies・unit_price_outlier）の候補は
       dict の unit_price=null・provisional_unit_price=計算値・unit_price_status="unconfirmed"・
       unit_price_unconfirmed_reasons=[理由]。確認済みは unit_price=値・provisional=null・"confirmed"・[]。
       単価なしは全 null・"unknown"・[]。送料別・不明だけなら素の値のまま。
  Q22  quantity.confidence は caption_conflict の候補だけ "conflict"。title_confidence に題名の判定。
       それ以外は title_confidence == confidence。
  Q23  注文案: order_unit_price / provisional_order_unit_price・unit_price_status・unit_price_unconfirmed_reasons
       （単価の理由だけ。送料を含まない）・payment_total（送料込み＝included の時だけ order_total と同値。
       送料別・不明は null）・order_total_kind（payment_total / item_subtotal）。既存の confirmed・
       unconfirmed_reasons（送料を含む全理由）は不変。
  AC17 出力 JSON の全枠の走査。 AC18 注文額の種類。
  不変 並び・外れ値の判定・cheapest_*・to_check の閾値は内部の計算値のまま。
  AC-W9 tools/list の compare_offers に desired_quantity_max があり、説明は 2000 字以内。

試験していない観点（報告に書く）: 公開 Web・CLI の表示（Q24「仮」・「商品小計（送料別）」）、search_products の
説明の言い回し（SPEC が文言を一意に指定していない）、unit_price の丸め桁数（±0.01 の許容で見る）、
実 API・本番、HTTP 経由の MCP。非機能（性能・互換・セキュリティ）: 該当なし（出力キーの契約のみ）。
変異は既定でやらない。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fakes import FakeAdapter, make_offer
from shopping import service

NOSLEEP = lambda s: None  # noqa: E731

UNIT_REASONS = {"quantity_from_caption", "caption_conflict", "price_varies", "unit_price_outlier"}
OFFER_KEYS = {"unit_price", "provisional_unit_price", "unit_price_status", "unit_price_unconfirmed_reasons"}
PLAN_KEYS = {"order_unit_price", "provisional_order_unit_price", "unit_price_status",
             "unit_price_unconfirmed_reasons", "payment_total", "order_total_kind"}


# --------------------------------------------------------------------------
# 部品
# --------------------------------------------------------------------------

def _cmp(offers, **kw):
    """service.compare_offers を偽 Adapter で通す。戻りは (comparison dict, 全体 dict)。"""
    ad = FakeAdapter({("aa", 1): (offers, len(offers))})
    r = service.compare_offers(["aa"], adapter=ad, sleep=NOSLEEP, **kw)
    assert r["ok"], r
    return r["comparison"], r


def _o(code, name, price, ship="included", **kw):
    return make_offer(code, name, price, shipping_status=ship, **kw)


def _walk(x, path="$"):
    """(path, dict) を再帰で全部出す。"""
    if isinstance(x, dict):
        yield path, x
        for k, v in x.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _walk(v, f"{path}[{i}]")


def _offers_of(c):
    return [o for g in c["groups"] for o in g["offers"]] + list(c["unknown_offers"])


def _by_name(c, name):
    for o in _offers_of(c):
        if o["name"] == name:
            return o
    raise AssertionError(f"{name!r} が候補に無い: {[o['name'] for o in _offers_of(c)]}")


def _plan(c, name):
    for p in c["order_plans"]:
        if p["name"] == name:
            return p
    raise AssertionError(f"{name!r} が注文案に無い: {[p['name'] for p in c['order_plans']]}")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_offer_dict(path, d):
    """Q21 の4キーの一貫性（候補の dict）。"""
    assert OFFER_KEYS <= set(d), (path, sorted(OFFER_KEYS - set(d)))
    st = d["unit_price_status"]
    rs = list(d["unit_price_unconfirmed_reasons"])
    assert st in ("confirmed", "unconfirmed", "unknown"), (path, st)
    if st == "unconfirmed":
        assert d["unit_price"] is None, (path, "未確定なのに素の unit_price が出ている", d["unit_price"])
        assert _num(d["provisional_unit_price"]), path
        assert rs and set(rs) <= UNIT_REASONS, (path, rs)   # 送料の理由は単価の理由に入らない
    elif st == "confirmed":
        assert _num(d["unit_price"]) and d["provisional_unit_price"] is None and rs == [], path
    else:
        assert d["unit_price"] is None and d["provisional_unit_price"] is None and rs == [], path
    if rs:
        assert d["unit_price"] is None, (path, "AC17: 理由があるのに素の unit_price")


def _check_plan_dict(path, d):
    """Q21・Q23 の注文案の dict の一貫性。"""
    assert PLAN_KEYS <= set(d), (path, sorted(PLAN_KEYS - set(d)))
    st = d["unit_price_status"]
    rs = list(d["unit_price_unconfirmed_reasons"])
    if st == "unconfirmed":
        assert d["order_unit_price"] is None, (path, "AC17: 未確定なのに素の order_unit_price")
        assert _num(d["provisional_order_unit_price"]), path
        assert rs and set(rs) <= UNIT_REASONS, (path, rs)
    else:
        assert st == "confirmed", (path, st)
        assert _num(d["order_unit_price"]) and d["provisional_order_unit_price"] is None and rs == [], path
    if rs:
        assert d["order_unit_price"] is None, (path, rs)
    # Q23: 注文額の種類（送料込み＝shipping_status が included の時だけ支払総額）
    if d["shipping_status"] == "included":
        assert d["order_total_kind"] == "payment_total" and d["payment_total"] == d["order_total"], path
    else:
        assert d["order_total_kind"] == "item_subtotal" and d["payment_total"] is None, (path, d["shipping_status"])


def _scan(result):
    """AC17・AC18: 出力 JSON 全体を走査して、全ての候補 dict・注文案 dict の一貫性を確かめる。
    戻りは {"offer": [(path, status)...], "plan": [...]}（走査が空振りでないことを呼び出し側が確かめる）。"""
    json.dumps(result, ensure_ascii=False)  # JSON 化できる
    seen = {"offer": [], "plan": []}
    for path, d in _walk(result):
        if "order_unit_price" in d or "provisional_order_unit_price" in d or "order_total_kind" in d:
            # 注文案（order_plans・cheapest_order・to_check・groups[].order_plans）
            _check_plan_dict(path, d)
            seen["plan"].append((path, d["unit_price_status"]))
        elif "unit_price" in d or "unit_price_status" in d:
            # 候補（groups[].offers・unknown_offers・cheapest_*）
            _check_offer_dict(path, d)
            seen["offer"].append((path, d["unit_price_status"]))
    return seen


def _paths(seen, kind, status):
    return [p for p, s in seen[kind] if s == status]


# --------------------------------------------------------------------------
# データセット（手計算）
# --------------------------------------------------------------------------
# 貼るカイロ（枚）。desired=60 枚・basis=個（主グループ＝枚）。
#   C  : 60枚 1800円 送料込み・確認済み → 1個あたり 1800÷60 = 30.0
#   V  : 60枚 1500円 送料込み・価格幅 1500〜1720（price_varies）→ 1500÷60 = 25.0（仮）
#   CAP: 題名に数量なし・説明欄「内容量：30枚」・1200円 → 補完 30 枚 → 1200÷30 = 40.0（仮・quantity_from_caption）
#        注文は n=2（60枚）= 2400円 → 注文の単価 2400÷60 = 40.0
#   X  : 題名 60枚 1800円・説明欄「内容量：120枚」→ 食い違い（caption_conflict）→ 題名の数量で 1800÷60 = 30.0（仮）
#   O  : 60枚 90円 → 90÷60 = 1.5。5 件の単価の中央値は 30.0。1.5 < 30÷10=3 → 外れ値（unit_price_outlier）
#   N  : 量の分からない商品 → 単価なし（unknown）
#   L  : ゼリー 3個入り 3冊 → 数え語の候補が衝突して low（単価なし）
C_NAME = "貼るカイロ 60枚 C店"
V_NAME = "貼るカイロ 60枚 V店"
CAP_NAME = "カイロ おすすめ"
X_NAME = "貼るカイロ 60枚 X店"
O_NAME = "貼るカイロ 60枚 O店"
N_NAME = "量の分からない商品 N"
L_NAME = "ゼリー 3個入り 3冊"


def _all_offers():
    return [
        _o("c", C_NAME, 1800),
        _o("v", V_NAME, 1500, price_min=1500, price_max=1720),
        _o("cap", CAP_NAME, 1200, caption="内容量：30枚"),
        _o("x", X_NAME, 1800, caption="内容量：120枚"),
        _o("o", O_NAME, 90),
        _o("n", N_NAME, 700),
        _o("l", L_NAME, 900),
    ]


@pytest.fixture(scope="module")
def mix():
    c, r = _cmp(_all_offers(), basis="個", desired_quantity=60)
    return c, r


# --------------------------------------------------------------------------
# Q21: 候補 dict の単価の振り分け（4 つの未確定理由・確認済み・単価なし）
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,reason,provisional",
    [
        (V_NAME, "price_varies", 25.0),            # 1500÷60
        (CAP_NAME, "quantity_from_caption", 40.0),  # 1200÷30
        (X_NAME, "caption_conflict", 30.0),         # 1800÷60（題名の数量）
        (O_NAME, "unit_price_outlier", 1.5),        # 90÷60
    ],
    ids=["price_varies", "quantity_from_caption", "caption_conflict", "unit_price_outlier"],
)
def test_q21_unconfirmed_unit_price_is_provisional(mix, name, reason, provisional):
    # SPEC §8 Q21・AC17: 未確定の理由（送料以外）がある候補は unit_price=null・計算値は provisional_unit_price
    c, _ = mix
    o = _by_name(c, name)
    assert o["unit_price"] is None
    assert o["provisional_unit_price"] == pytest.approx(provisional, abs=0.01)
    assert o["unit_price_status"] == "unconfirmed"
    assert list(o["unit_price_unconfirmed_reasons"]) == [reason]
    assert o["unit_price_label"]  # 仮の値にも表示単位は付く（Q21 末尾）


def test_q21_confirmed_candidate_keeps_plain_unit_price(mix):
    # Q21: 確認済み（C）は unit_price=値（1800÷60=30.0）・provisional=null・confirmed・[]
    c, _ = mix
    o = _by_name(c, C_NAME)
    assert o["unit_price"] == pytest.approx(30.0, abs=0.01)
    assert o["provisional_unit_price"] is None
    assert o["unit_price_status"] == "confirmed" and list(o["unit_price_unconfirmed_reasons"]) == []


@pytest.mark.parametrize("name", [N_NAME, L_NAME], ids=["quantity_unknown", "quantity_low"])
def test_q21_q8_unknown_unit_price_is_all_null(mix, name):
    # Q8・Q21: 単価なし（unknown_offers）は unit_price=null・provisional=null・"unknown"・[]
    c, _ = mix
    assert name in [o["name"] for o in c["unknown_offers"]]
    o = _by_name(c, name)
    assert o["unit_price"] is None and o["provisional_unit_price"] is None
    assert o["unit_price_status"] == "unknown" and list(o["unit_price_unconfirmed_reasons"]) == []


def test_q21_outlier_flag_and_internal_order_unchanged(mix):
    # Q14・Q21: 外れ値の印・並び（groups の単価の安い順）は内部の計算値のまま。出力で unit_price が null の候補も
    # 内部の値の位置に残る（O 1.5 < V 25 < C・X 30 < CAP 40）。件数も 5 のまま。
    c, _ = mix
    assert _by_name(c, O_NAME)["unit_price_outlier"] is True
    assert _by_name(c, C_NAME)["unit_price_outlier"] is False
    g = c["groups"][0]
    names = [o["name"] for o in g["offers"]]
    assert set(names) == {C_NAME, V_NAME, CAP_NAME, X_NAME, O_NAME}
    assert names[0] == O_NAME and names[1] == V_NAME and names[-1] == CAP_NAME
    keys = [o["unit_price"] if o["unit_price"] is not None else o["provisional_unit_price"] for o in g["offers"]]
    assert keys == sorted(keys)


def test_q21_outlier_judged_on_internal_value_including_provisional_candidates():
    # Q14・Q21: 外れ値の判定は「出力で unit_price が null になる候補も含めて」数える。単価が出ている候補が 4 件以上
    # の時だけ判定するので、C1 30.0・C2 31.67（1900÷60）・V 25.0（仮）・O 1.5 の 4 件目に V を数えないと印が付かない。
    # 中央値 = (25+30)/2 = 27.5 → 1/10 = 2.75。O の 1.5 は未満 → 外れ値。V・C1・C2 は外れ値でない。
    c, _ = _cmp([
        _o("c1", "貼るカイロ 60枚 C1店", 1800),
        _o("c2", "貼るカイロ 60枚 C2店", 1900),
        _o("v", V_NAME, 1500, price_min=1500, price_max=1720),
        _o("o", O_NAME, 90),
    ])
    assert _by_name(c, O_NAME)["unit_price_outlier"] is True
    assert _by_name(c, O_NAME)["provisional_unit_price"] == pytest.approx(1.5, abs=0.01)
    for n in ("貼るカイロ 60枚 C1店", "貼るカイロ 60枚 C2店", V_NAME):
        assert _by_name(c, n)["unit_price_outlier"] is False
    assert any("1/10" in cv or "数量の読み違い" in cv for cv in c["caveats"])  # §8 外れ値の caveats は不変


def test_q21_shipping_only_unconfirmed_keeps_plain_unit_price():
    # Q21: 送料別・不明は単価の誤りではない → 素の unit_price のまま・confirmed・[]。
    # 「天然水 2L×6本」= 12000ml。3000円 → 100mlあたり 3000÷12000×100 = 25.0。
    c, _ = _cmp([_o("a", "天然水 2L×6本 A店", 3000, ship="separate"),
                 _o("b", "天然水 2L×6本 B店", 3000, ship="unknown")], basis="ml")
    for n in ("天然水 2L×6本 A店", "天然水 2L×6本 B店"):
        o = _by_name(c, n)
        assert o["unit_price"] == pytest.approx(25.0, abs=0.01), n
        assert o["provisional_unit_price"] is None
        assert o["unit_price_status"] == "confirmed" and list(o["unit_price_unconfirmed_reasons"]) == []


def test_q21_multiple_reasons_list_only_unit_reasons_not_shipping():
    # Q21: price_varies ∧ 送料別 → 単価の理由は ["price_varies"] だけ（送料の理由は含まない）。1500÷60 = 25.0。
    c, _ = _cmp([_o("v", V_NAME, 1500, ship="separate", price_min=1500, price_max=1720)])
    o = _by_name(c, V_NAME)
    assert o["unit_price"] is None and o["provisional_unit_price"] == pytest.approx(25.0, abs=0.01)
    assert o["unit_price_status"] == "unconfirmed"
    assert list(o["unit_price_unconfirmed_reasons"]) == ["price_varies"]


def test_q21_two_unit_reasons_are_both_listed():
    # Q21: 単価の理由が複数（price_varies ∧ caption_conflict）なら両方並ぶ。
    # 題名 60枚 1500円・価格幅あり・説明欄「内容量：120枚」→ 食い違い。1500÷60 = 25.0。
    c, _ = _cmp([_o("vx", "貼るカイロ 60枚 VX店", 1500, price_min=1500, price_max=1720, caption="内容量：120枚")])
    o = _by_name(c, "貼るカイロ 60枚 VX店")
    assert o["unit_price"] is None and o["unit_price_status"] == "unconfirmed"
    assert set(o["unit_price_unconfirmed_reasons"]) == {"price_varies", "caption_conflict"}
    assert o["provisional_unit_price"] == pytest.approx(25.0, abs=0.01)


# --------------------------------------------------------------------------
# Q22: quantity.confidence / title_confidence
# --------------------------------------------------------------------------

def test_q22_conflict_only_for_caption_conflict(mix):
    # Q22: caption_conflict の候補だけ quantity.confidence="conflict"。題名の判定は title_confidence（high）。
    # caption_conflict・caption_evidence は従来どおり。
    c, _ = mix
    q = _by_name(c, X_NAME)["quantity"]
    assert q["confidence"] == "conflict" and q["title_confidence"] == "high"
    assert q["caption_conflict"] is True and q["caption_evidence"]
    assert q["count_total"] == 60  # 題名の数量は変わらない


@pytest.mark.parametrize(
    "name,conf",
    [(C_NAME, "high"), (V_NAME, "high"), (O_NAME, "high"), (CAP_NAME, "high"), (N_NAME, "none"), (L_NAME, "low")],
    ids=["confirmed", "price_varies", "outlier", "caption_fill", "none", "low"],
)
def test_q22_title_confidence_equals_confidence_except_conflict(mix, name, conf):
    # Q22: caption_conflict 以外は title_confidence = confidence（キーは常に出す。補完候補も同じ。
    # 価格幅・外れ値の候補の confidence は high のまま＝"conflict" にしない）。
    c, _ = mix
    q = _by_name(c, name)["quantity"]
    assert q["confidence"] == conf and q["title_confidence"] == conf
    assert q.get("caption_conflict") in (False, None)


def test_q22_caption_fill_source_and_evidence(mix):
    # Q22・AC16: 補完候補は source="caption"・confidence="high"・title_confidence="high"・caption_evidence あり
    c, _ = mix
    q = _by_name(c, CAP_NAME)["quantity"]
    assert q["source"] == "caption" and q["confidence"] == "high" and q["title_confidence"] == "high"
    assert q["caption_evidence"] and "30" in q["caption_evidence"]


# --------------------------------------------------------------------------
# Q23・AC18: 注文案
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,reason,provisional,n,total",
    [
        (V_NAME, "price_varies", 25.0, 1, 1500),          # 1500÷60
        (CAP_NAME, "quantity_from_caption", 40.0, 2, 2400),  # n=ceil(60÷30)=2・2400÷60
        (X_NAME, "caption_conflict", 30.0, 1, 1800),      # 1800÷60
        (O_NAME, "unit_price_outlier", 1.5, 1, 90),       # 90÷60
    ],
    ids=["price_varies", "quantity_from_caption", "caption_conflict", "unit_price_outlier"],
)
def test_q23_unconfirmed_plan_has_provisional_order_unit_price(mix, name, reason, provisional, n, total):
    # Q23: 未確定の案は order_unit_price=null・provisional_order_unit_price=計算値・"unconfirmed"・単価の理由
    c, _ = mix
    p = _plan(c, name)
    assert p["n"] == n and p["order_total"] == total
    assert p["order_unit_price"] is None
    assert p["provisional_order_unit_price"] == pytest.approx(provisional, abs=0.01)
    assert p["unit_price_status"] == "unconfirmed" and list(p["unit_price_unconfirmed_reasons"]) == [reason]
    # 既存の confirmed・unconfirmed_reasons（全理由）は不変
    assert p["confirmed"] is False and reason in p["unconfirmed_reasons"]


def test_q23_confirmed_plan_and_cheapest_order(mix):
    # Q23: 確認済みの案（C: n=1・1800円・1800÷60=30.0）は order_unit_price=値。cheapest_order は確認済みなので必ず値を持つ
    c, _ = mix
    p = _plan(c, C_NAME)
    assert p["order_unit_price"] == pytest.approx(30.0, abs=0.01) and p["provisional_order_unit_price"] is None
    assert p["unit_price_status"] == "confirmed" and list(p["unit_price_unconfirmed_reasons"]) == []
    assert p["confirmed"] is True and list(p["unconfirmed_reasons"]) == []
    co = c["cheapest_order"]
    assert co["name"] == C_NAME and co["order_unit_price"] == pytest.approx(30.0, abs=0.01)
    assert co["unit_price_status"] == "confirmed"


def test_q23_plan_order_and_to_check_membership_unchanged_by_masking(mix):
    # Q23: 並び（量の指定＝注文額の安い順）・cheapest_order・to_check の候補は内部の計算値のまま。
    # 注文額: O 90 < V 1500 < C 1800 = X 1800 < CAP 2400。cheapest_order は確認済みの C（C 以外に確認済みは無い）。
    c, _ = mix
    totals = [p["order_total"] for p in c["order_plans"]]
    assert totals == sorted(totals)
    assert c["order_plans"][0]["name"] == O_NAME
    assert c["order_plans"][-1]["name"] == CAP_NAME
    assert c["cheapest_order"]["name"] == C_NAME
    tc = {t["name"] for t in c["to_check"]}
    assert {V_NAME, O_NAME} <= tc          # C より安い未確定候補は to_check に出る
    assert C_NAME not in tc and CAP_NAME not in tc


def test_q23_to_check_entries_carry_new_keys_and_conditions(mix):
    # Q23: to_check[] も同名のキーを持つ（未確定なので素の order_unit_price は null）。conditions は従来どおり。
    c, _ = mix
    t = {x["name"]: x for x in c["to_check"]}[V_NAME]
    assert t["order_unit_price"] is None and t["provisional_order_unit_price"] == pytest.approx(25.0, abs=0.01)
    assert t["unit_price_status"] == "unconfirmed" and list(t["unit_price_unconfirmed_reasons"]) == ["price_varies"]
    conds = t["conditions"]
    assert conds and all({"reason", "reasons", "threshold", "text"} <= set(x) for x in conds)


@pytest.mark.parametrize(
    "ship,kind,payment",
    [("included", "payment_total", 4200), ("separate", "item_subtotal", None), ("unknown", "item_subtotal", None)],
)
def test_ac18_order_total_kind(ship, kind, payment):
    # AC18・Q23: 天然水 2L×6本 4200円（12000ml）・desired=10000ml → n=1・order_total=4200。
    # 送料込み（included）だけ payment_total=4200・kind=payment_total。送料別・不明は payment_total=null・item_subtotal。
    c, _ = _cmp([_o("a", "天然水 2L×6本 A店", 4200, ship=ship)], basis="ml", desired_quantity=10000)
    (p,) = c["order_plans"]
    assert p["shipping_status"] == ship and p["n"] == 1 and p["order_total"] == 4200
    assert p["order_total_kind"] == kind and p["payment_total"] == payment
    # 送料別・不明は単価の誤りではない → 注文の単価は素の値（4200÷12000×100 = 35.0）
    assert p["order_unit_price"] == pytest.approx(35.0, abs=0.01) and p["provisional_order_unit_price"] is None
    assert p["unit_price_status"] == "confirmed" and list(p["unit_price_unconfirmed_reasons"]) == []
    assert (p["confirmed"] is True) == (ship == "included")


def test_ac18_mixed_shipping_plans_each_have_own_kind_and_to_check_threshold_unchanged():
    # AC18・Q16: a 4200円 送料別・b 5000円 送料込み・desired=10000ml。cheapest_order=b（5000）。
    # b: payment_total=5000・payment_total 種別。a は to_check（4200 < 5000）で item_subtotal・条件の閾値 5000-4200=800（不変）。
    a, b = "天然水 2L×6本 A店", "天然水 2L×6本 B店"
    c, _ = _cmp([_o("a", a, 4200, ship="separate"), _o("b", b, 5000)], basis="ml", desired_quantity=10000)
    assert c["cheapest_order"]["name"] == b
    assert c["cheapest_order"]["payment_total"] == 5000 and c["cheapest_order"]["order_total_kind"] == "payment_total"
    (t,) = c["to_check"]
    assert t["name"] == a and t["order_total_kind"] == "item_subtotal" and t["payment_total"] is None
    assert t["order_total"] == 4200
    assert len(t["conditions"]) == 1 and t["conditions"][0]["threshold"] == 800
    assert "shipping_separate" in t["conditions"][0]["reasons"]
    assert [p["name"] for p in c["order_plans"]] == [a, b]  # 注文額 4200 < 5000


def test_q23_combined_reasons_threshold_unchanged_and_masked_unit():
    # Q16・Q23: V（送料別 ∧ 価格幅あり・1500円）と C（1800円・送料込み）。to_check は V 1 件・条件 1 つ・閾値 1800。
    # V の単価の理由は ["price_varies"] だけ（送料を含まない）・unconfirmed_reasons（全理由）は両方。
    c, _ = _cmp(
        [_o("v", V_NAME, 1500, ship="separate", price_min=1500, price_max=1720), _o("c", C_NAME, 1800)],
        basis="個", desired_quantity=60,
    )
    assert c["cheapest_order"]["name"] == C_NAME
    (t,) = c["to_check"]
    assert t["name"] == V_NAME
    assert len(t["conditions"]) == 1 and t["conditions"][0]["threshold"] == 1800
    assert set(t["conditions"][0]["reasons"]) >= {"price_varies", "shipping_separate"}
    assert list(t["unit_price_unconfirmed_reasons"]) == ["price_varies"]
    assert set(t["unconfirmed_reasons"]) >= {"price_varies", "shipping_separate"}
    assert t["order_unit_price"] is None and t["provisional_order_unit_price"] == pytest.approx(25.0, abs=0.01)
    assert t["payment_total"] is None and t["order_total_kind"] == "item_subtotal"


def test_q23_range_order_uses_internal_value_and_cheapest_order_is_confirmed():
    # Q23: 範囲指定の並びと cheapest_order の選びは内部の計算値のまま。
    # a 100本 4000円: n=1・4000÷100=40.0。b 60本 2300円: n=2・120本・4600÷120=38.33。
    # V 100本 3000円（価格幅 3000〜3500）: n=1・3000÷100=30.0（仮）。範囲 100〜120 → 注文の単価順 [V, b, a]。
    # V は未確定なので cheapest_order にならず（b）、V の素の order_unit_price は null・仮が 30.0。
    a, b, v = "単3電池 100本 A店", "単3電池 60本 B店", "単3電池 100本 V店"
    offers = [_o("a", a, 4000), _o("b", b, 2300), _o("v", v, 3000, price_min=3000, price_max=3500)]
    c, _ = _cmp(offers, basis="個", desired_quantity=100, desired_quantity_max=120)
    assert [p["name"] for p in c["order_plans"]] == [v, b, a]
    assert c["cheapest_order"]["name"] == b
    assert c["cheapest_order"]["order_unit_price"] == pytest.approx(4600 / 120, abs=0.01)
    pv = _plan(c, v)
    assert pv["order_unit_price"] is None and pv["provisional_order_unit_price"] == pytest.approx(30.0, abs=0.01)
    # 量の指定（上限なし）は注文額の安い順: V 3000 < a 4000 < b 4600
    c2, _ = _cmp(offers, basis="個", desired_quantity=100)
    assert [p["name"] for p in c2["order_plans"]] == [v, a, b]
    assert c2["cheapest_order"]["name"] == a


# --------------------------------------------------------------------------
# AC17: 出力 JSON の全枠の走査
# --------------------------------------------------------------------------

def test_ac17_scan_compare_offers_every_slot(mix):
    # AC17: groups・unknown_offers・cheapest_*・order_plans・cheapest_order・to_check を走査して、理由のある候補・案に
    # 素の単価が 0 件。走査が空振りでない（各枠に未確定／単価なしの dict が実際にある）ことも確かめる。
    c, r = mix
    seen = _scan(r)
    unc = _paths(seen, "offer", "unconfirmed")
    for slot in ("groups[", "cheapest_price", "cheapest_total"):
        assert any(slot in p for p in unc), (slot, unc)
    assert any("unknown_offers" in p for p in _paths(seen, "offer", "unknown"))
    assert any("order_plans" in p for p in _paths(seen, "plan", "unconfirmed"))
    assert any("to_check" in p for p in _paths(seen, "plan", "unconfirmed"))
    assert any("cheapest_order" in p for p in _paths(seen, "plan", "confirmed"))
    # 数量を使う最安は確認済みしか選ばれない → 値がある
    for slot in ("cheapest_unit_price", "cheapest_for_quantity"):
        d = c[slot]
        assert d is not None and d["unit_price_status"] == "confirmed" and _num(d["unit_price"]), slot
    # 最安の価格・総額の枠は外れ値 O（90円）。素の単価を持たない
    assert c["cheapest_price"]["name"] == O_NAME and c["cheapest_price"]["unit_price"] is None
    assert c["cheapest_total"]["name"] == O_NAME and c["cheapest_total"]["unit_price"] is None
    assert c["cheapest_price"]["provisional_unit_price"] == pytest.approx(1.5, abs=0.01)


def test_ac17_cheapest_unit_price_slot_is_confirmed_candidate(mix):
    # Q14・AC13: 外れ値・価格幅・補完・食い違いは数量を使う最安に選ばれない → C（30.0）が最安
    c, _ = mix
    assert c["cheapest_unit_price"]["name"] == C_NAME
    assert c["cheapest_unit_price"]["unit_price"] == pytest.approx(30.0, abs=0.01)
    assert c["cheapest_for_quantity"]["name"] == C_NAME


def test_ac17_group_level_cheapest_is_scanned_if_present(mix):
    # Q21: groups[].cheapest_unit_price があるなら同じ 4 キーを持つ（_scan が全 dict を見ている。ここは存在確認だけ）
    c, _ = mix
    for g in c["groups"]:
        if g.get("cheapest_unit_price"):
            _check_offer_dict("groups[].cheapest_unit_price", g["cheapest_unit_price"])


def test_ac17_unidy_like_price_range_candidate():
    # AC17 の例: 選択肢の価格幅 1500〜1720 円の「貼るカイロ 60枚」は unit_price=null・provisional=25.0・unconfirmed。
    # 価格幅 price_min・price_max・price_varies は従来どおり出る（AC13）。
    c, r = _cmp([_o("u", "貼るカイロ 60枚 unidy", 1500, price_min=1500, price_max=1720)])
    o = _by_name(c, "貼るカイロ 60枚 unidy")
    assert o["unit_price"] is None and o["provisional_unit_price"] == pytest.approx(25.0, abs=0.01)
    assert o["unit_price_status"] == "unconfirmed"
    assert o["price_varies"] is True and o["price_min"] == 1500 and o["price_max"] == 1720
    assert c["cheapest_unit_price"] is None  # 確認済みが無い＝偽の最安を出さない
    _scan(r)


def test_ac17_no_pricing_when_only_confirmed_offers():
    # AC17: 確認済みだけの比較は従来どおり（unit_price=値・provisional=null・confirmed）。送料別・不明も素の値。
    c, r = _cmp([_o("a", "天然水 2L×6本 A店", 3000), _o("b", "天然水 2L×6本 B店", 3300, ship="separate"),
                 _o("c", "天然水 2L×6本 C店", 3600, ship="unknown")], basis="ml", desired_quantity=10000)
    seen = _scan(r)
    assert not _paths(seen, "offer", "unconfirmed") and not _paths(seen, "plan", "unconfirmed")
    assert _by_name(c, "天然水 2L×6本 A店")["unit_price"] == pytest.approx(25.0, abs=0.01)   # 3000÷12000×100
    assert _by_name(c, "天然水 2L×6本 B店")["unit_price"] == pytest.approx(27.5, abs=0.01)   # 3300÷12000×100
    assert _by_name(c, "天然水 2L×6本 C店")["unit_price"] == pytest.approx(30.0, abs=0.01)   # 3600÷12000×100


def test_ac17_scan_search_products_candidates():
    # Q21: search_products は比較を通らず単価を計算しない → 全候補が unit_price=null・provisional=null・"unknown"・[]。
    # 価格幅ありの候補も同じ。quantity.title_confidence は confidence と同値（Q22）。
    offers = [_o("a", "貼るカイロ 60枚 A店", 1800), _o("v", V_NAME, 1500, price_min=1500, price_max=1720),
              _o("n", N_NAME, 700)]
    ad = FakeAdapter({("aa", 1): (offers, 3)})
    r = service.search_products(["aa"], adapter=ad, sleep=NOSLEEP)
    assert r["ok"] and r["returned"] == 3
    seen = _scan(r)
    assert len(seen["offer"]) >= 3 and all(s == "unknown" for _, s in seen["offer"])
    for o in r["offers"]:
        assert o["unit_price"] is None and o["provisional_unit_price"] is None
        assert o["unit_price_status"] == "unknown" and list(o["unit_price_unconfirmed_reasons"]) == []
        assert o["quantity"]["title_confidence"] == o["quantity"]["confidence"]


def test_ac17_scan_find_regular_item(tmp_path):
    # AC17: 定番品の結果（comparison を含む）にも同じ走査。理由のある候補・案に素の単価なし。
    reg = tmp_path / "regulars.json"
    reg.write_text(json.dumps([{"id": "r1", "name": "カイロ", "keywords": ["aa"], "include_terms": [],
                                "exclude_terms": [], "basis": "個", "desired_quantity": 60}], ensure_ascii=False),
                   encoding="utf-8")
    ad = FakeAdapter({("aa", 1): (_all_offers(), 7)})
    r = service.find_regular_item("r1", regulars_path=reg, adapter=ad, sleep=NOSLEEP)
    assert r["ok"], r
    seen = _scan(r)
    assert _paths(seen, "offer", "unconfirmed") and _paths(seen, "plan", "unconfirmed")
    assert _paths(seen, "offer", "unknown")


# --------------------------------------------------------------------------
# MCP: tools/list（in-process）。AC-W9・§10
# --------------------------------------------------------------------------

def _tools():
    from mcp import Client

    from shopping.mcp_server import build_server

    async def go():
        async with Client(build_server()) as c:
            return {t.name: t for t in (await c.list_tools()).tools}

    return asyncio.run(asyncio.wait_for(go(), timeout=30))


def test_mcp_compare_offers_has_desired_quantity_max_and_description_within_2000():
    # AC-W9・§8: tools/list の compare_offers に desired_quantity_max があり、説明は 2000 字以内（WP11 のガード維持）
    t = _tools()["compare_offers"]
    assert "desired_quantity_max" in t.input_schema["properties"]
    assert len(t.description) <= 2000, len(t.description)
    assert "desired_quantity_max" in t.description  # 使い方を要点に入れる（§10 ツール説明の文言）


def test_mcp_search_products_description_within_limit():
    # WP11 のガード（説明 2000 字以内）が search_products にも効いている
    t = _tools()["search_products"]
    assert len(t.description) <= 2000, len(t.description)


def test_mcp_compare_offers_description_new_wording():
    # §10（WP15）: 冒頭の「商品名から読んだ数量」は「商品名（足りない時は説明欄の見出し付きの値）から読んだ数量」。
    # 未確定の単価は仮の値（provisional_unit_price）の扱いを要点に入れる。『quantity.confidence が high でない候補は
    # 最安・おすすめとして示さない』（WP11-1 (2)。Q22 で conflict も含む）は両ツールの説明に残る。
    ts = _tools()
    t = ts["compare_offers"]
    assert "商品名（足りない時は説明欄の見出し付きの値）から読んだ数量" in t.description
    assert "provisional_unit_price" in t.description
    for name in ("compare_offers", "search_products"):
        assert "high でない" in ts[name].description, name


def test_mcp_instructions_carry_provisional_and_subtotal_sentences():
    # §10 (5)(6): INSTRUCTIONS（_ORDER_GUIDE）に、unit_price が null で provisional_unit_price がある候補の単価を
    # 確定値として伝えない・理由（unit_price_unconfirmed_reasons）を添える／order_total_kind が item_subtotal の金額を
    # 支払総額と呼ばない（支払総額は payment_total がある時だけ）。
    from shopping.mcp_server import INSTRUCTIONS

    for ph in ("provisional_unit_price", "unit_price_unconfirmed_reasons", "order_total_kind", "item_subtotal",
               "payment_total"):
        assert ph in INSTRUCTIONS, ph
