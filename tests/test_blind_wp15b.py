# @owns WP15 段B ブラインド試験（項目単位の補完〔長さ〕・包装の数 quantity.packs・basis=袋 の比較・主グループ外の to_check）
"""WP15 段B ブラインド試験（2026-11-21）。根拠は docs/SPEC.md の §7 W4（項目単位の補完）・§7「包装の数」・§7 R9、
§8 Q7・Q16・Q19・Q20・Q21〜Q24・「確認済み」、§10（MCP の指示）、AC15・AC16・AC19・AC20 だけ
（src の実装・実装担当の説明は見ない。入力の題名は SPEC に例がある形と、録画した実題名〔data/wp15b/store.json の
itemName・yumenokoya:39998092 だけ〕）。期待値は全て手計算（式を各試験のコメントに残す）。実装担当は読まない・編集しない。

入口: service.compare_offers / search_products（偽 Adapter。実 API・本番は使わない）と、
mcp_server.INSTRUCTIONS・build_server の tools/list（in-process）。数量の読み取り・補完・価格比較は実物を通す
（業務ロジックは再実装しない）。新しい名前の import は各試験の中で遅延させ、収集は常に通る。

試験している契約:
  AC19・§7 W4  題名が high で個数だけの候補に、説明欄の見出し `長さ` の値を1個あたりの内容量として重ねる
               （数字＋長さの単位で始まる・内容量1つ・個数の記述なし・見出し複数は同じ値・price_varies には補わない）。
               source="title+caption"・caption_evidence・measure_total。`重さ`・`重量`・`幅`・`サイズ`・`内容量：2L` は読まない。
               basis が個・ロールの比較は確認済みのまま・単価は確定値、basis=m の単価だけ仮（measure_from_caption）で
               最安・注文の最安に選ばず to_check に条件つき。
  Q7           自動 basis は題名から読めた内容量だけで過半を判定（補った内容量は個数だけの候補として数える。
               source="caption" の補完は従来どおり数える）。
  §7 包装の数   quantity.packs（F1〜F3・読めない時 []・総数と confidence は不変・キーは常に出す）。
  AC20・Q20    basis=袋: (a) count_unit=袋 と (b) packs に袋がある候補を同じグループで比べる。1袋の中身が基準と一致する
               候補だけ確認済み（基準＝最多の値。同数なら確認済みの最安の注文額が安い方）。食い違い=pack_content_differs
               （order_plans に残り to_check）。それ以外は counter_assumed（order_plans に入らず unknown_offers に残り to_check。
               ①1袋が18本なら ②この商品の1本が1袋なら／この商品1点が1袋なら）。候補ゼロにならない。desired は袋のまま。
  Q19・AC15    basis=個 の主グループと違う数え語の候補は、確認済みの横断比較はせず、主グループの to_check に
               「1個が1枚なら」の条件つきで出す（counter_assumed。cheapest_order には選ばない・数量 none は出さない）。
  R9           yumenokoya 型の題名（捨てた 1 と総数の食い違い）は low のまま。
  §10          INSTRUCTIONS が basis=袋・quantity.packs を案内。compare_offers の説明は 2000 字以内のまま。
  規律8        最安でも counter_assumed・pack_content_differs・measure_from_caption の候補が cheapest_order・
               cheapest_unit_price・cheapest_for_quantity に選ばれない（basis=袋・個・m の3入口）。出力 JSON 全体の走査（AC17）。

保留した観点（SPEC が一意に決めていない。推測で期待値を作らない。報告に書く）:
  基準の同数で希望量が無い時／caveats「数え語が X でない候補: N件」が仮定つきの候補を数えるか（basis=数え語で希望量なしの時）／
  counter_assumed だけの案の conditions[].threshold／Q19 で主グループの to_check に出る別の数え語の案の count_unit／
  `長さ：約100m`／caption_evidence に「シングル」を含むか／packs の形が食い違う複数形の時／`2袋セット` 単独の packs。
未試験: 公開 Web・CLI の表示（Q24「仮」・理由の文）、実 API・本番、HTTP 経由の MCP、題名コーパス 480 件の不変
（tests/test_title_corpus.py が担当）。非機能（性能・互換・セキュリティ）: 該当なし（出力の契約のみ）。変異は既定でやらない。
"""
from __future__ import annotations

import asyncio
import json
import re

import pytest

from fakes import FakeAdapter, make_offer
from shopping import service

NOSLEEP = lambda s: None  # noqa: E731


# --------------------------------------------------------------------------
# 部品
# --------------------------------------------------------------------------

def _cmp(offers, **kw):
    ad = FakeAdapter({("aa", 1): (offers, len(offers))})
    r = service.compare_offers(["aa"], adapter=ad, sleep=NOSLEEP, **kw)
    assert r["ok"], r
    return r["comparison"], r


def _o(code, name, price, ship="included", **kw):
    return make_offer(code, name, price, shipping_status=ship, **kw)


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


def _tc(c, name):
    for p in c["to_check"]:
        if p["name"] == name:
            return p
    raise AssertionError(f"{name!r} が to_check に無い: {[p['name'] for p in c['to_check']]}")


def _tc_names(c):
    return {p["name"] for p in c["to_check"]}


def _ctext(p):
    return " ".join(x["text"] for x in p["conditions"]).replace(",", "")


def _creasons(p):
    return {r for x in p["conditions"] for r in x["reasons"]}


def _unknown_names(c):
    return [o["name"] for o in c["unknown_offers"]]


def _caveats(c):
    return "\n".join(c["caveats"])


def _selected_names(c):
    """数量を使う最安（確認済みだけが選ばれる枠）に選ばれている候補名。"""
    names = set()
    for slot in ("cheapest_unit_price", "cheapest_for_quantity", "cheapest_order"):
        d = c.get(slot)
        if d:
            names.add(d["name"])
    for g in c["groups"]:
        d = g.get("cheapest_unit_price")
        if d:
            names.add(d["name"])
        d = g.get("cheapest_order")
        if d:
            names.add(d["name"])
    return names


def _scan(result):
    # AC17・AC18 の走査（段A の部品を使う。新しい理由語は UNIT_REASONS に足してある）
    from test_blind_wp15 import _scan as scan

    return scan(result)


def _conf(q):
    c = q.confidence
    return getattr(c, "value", c)


# --------------------------------------------------------------------------
# §7 W4・AC19: 項目単位の補完（見出し `長さ`）
# --------------------------------------------------------------------------

ROLL = "トイレットペーパー 12ロール×4パック"          # 題名: 48ロール・high・個数だけ（SPEC の cocodecow 型）
CAP100 = "●長さ：100mシングル●紙幅：108mm●くつろぐ花の香りつき●芯あり"   # cocodecow:10392423 の説明欄の抜粋
ROLL_M = "トイレットペーパー 75m×12ロール"            # 題名から内容量が読める（12ロール・75m/ロール・900m）


def test_ac19_fill_sets_content_from_length_heading():
    # §7 W4・AC19: 題名 12ロール×4=48ロール・high・個数だけ ＋ 説明欄「長さ：100mシングル」
    #   → content_amount=100m・dimension=length・measure_total=48×100=4800・source="title+caption"・根拠つき。
    #   題名の個数と confidence は不変。説明欄の無い同じ題名は補われない。
    c, _ = _cmp([_o("f", ROLL + " F店", 2400, caption=CAP100), _o("p", ROLL + " P店", 2880)])
    q = _by_name(c, ROLL + " F店")["quantity"]
    assert q["count_total"] == 48 and q["count_unit"] == "ロール"
    assert q["confidence"] == "high" and q["title_confidence"] == "high"
    assert q["content_amount"] == pytest.approx(100) and q["content_dimension"] == "length"
    assert q["content_unit"] == "m" and q["measure_total"] == pytest.approx(4800)
    assert q["source"] == "title+caption"
    assert q["caption_evidence"] and "100" in q["caption_evidence"]
    assert not q.get("caption_conflict")
    p = _by_name(c, ROLL + " P店")["quantity"]
    assert p["count_total"] == 48 and p["content_amount"] is None and p["measure_total"] is None
    assert p["source"] != "title+caption"


def test_ac19_title_reading_itself_is_unchanged():
    # §7 W4: 題名の読み取り（quantity.py）は変えない。補完は別の層なので parse_quantity は個数だけのまま。
    from shopping.quantity import parse_quantity

    q = parse_quantity(ROLL)
    assert q.count_total == 48 and q.count_unit == "ロール" and _conf(q) == "high"
    assert q.content_amount is None and q.measure_total is None


@pytest.mark.parametrize(
    "title,caption,amount_m",
    [
        (ROLL, CAP100, 100),
        (ROLL, "長さ:100m", 100),                         # 半角コロン
        (ROLL, "【長さ】100m", 100),                       # 括弧の直後
        (ROLL, "長さ 100m", 100),                         # 空白区切り
        (ROLL, "長さ100m", 100),                          # 区切りなし
        (ROLL, "長さ25m", 25),                            # 数字の直付け（段B レビュー後の確定: 区切り・空白・直付けのどれでも読む）
        (ROLL, "長さ 35m", 35),
        (ROLL, "長さ／25m", 25),                          # 区切りに／・/
        (ROLL, "長さ/25m", 25),
        (ROLL, "長さ：１００ｍ", 100),                     # NFKC 後
        (ROLL, "長さ：100m\n長さ：100m", 100),            # 見出しが複数でも全部が同じ値
        (ROLL, "x" * 300 + "●長さ：100mシングル", 100),   # 読み取りは全文（結果の caption は 200 字で切る）
        ("ラップ 3本", "長さ：25cm", 0.25),                # 単位換算（cm→m）
        ("ラップ 3本", "長さ：200mm", 0.2),                # mm→m
    ],
    ids=["cocodecow", "halfwidth_colon", "bracket", "space", "no_separator", "direct25", "space35", "fullslash",
         "slash", "fullwidth", "same_twice",
         "after_200_chars", "cm", "mm"],
)
def test_ac19_fill_forms(title, caption, amount_m):
    # §7 W4 条件(1)(4)・見出しの書式: 数字＋長さの単位で始まる値は内容量（基準単位 m）にする
    # measure_total = 個数 × 内容量（ROLL は 48、ラップ 3本 は 3）
    n = 48 if title == ROLL else 3
    c, _ = _cmp([_o("f", title + " F店", 2400, caption=caption)])
    q = _by_name(c, title + " F店")["quantity"]
    assert q["source"] == "title+caption", (caption, q)
    assert q["content_amount"] == pytest.approx(amount_m) and q["content_dimension"] == "length"
    assert q["measure_total"] == pytest.approx(n * amount_m)
    assert q["confidence"] == "high" and q["count_total"] == n


@pytest.mark.parametrize(
    "caption",
    [
        "長さ2倍巻の100m",                       # 値が数字＋長さの単位で始まらない（SPEC の例そのもの）
        "長さ：2倍巻の100m",
        "長さ：100m 幅108mm",                    # 内容量が2つ（m と mm が混ざる）
        "長さ：100m 2個入",                      # 値に個数の記述（数字＋数え語）
        "長さ：100m\n長さ：50m",                 # 見出しが複数で食い違う
        "関連キーワード 長さ：100m",             # 関連キーワード以降
        "長さ：100mはこちら",                    # 別商品への案内
        "長さ：100mあたり",                      # 単位あたりの言い回し
        "ロールの長さ：100m",                    # 見出しの直前が語の文字
        "長さ30cmにカット",                      # 単位の直後が助詞（に）= 使用例の文（SPEC の例）
        "長さ 約30cm のコード付き",              # 値が数字で始まらない（約）= 使用例の文（SPEC の例）
        "長さ：100mの",                          # 助詞 の
        "長さ：100m を",                         # 空白を読み飛ばした後の助詞 を
        "長さ：10mまで", "長さ：10mほど", "長さ：10mより", "長さ：10mで", "長さ：10mが", "長さ：10mは",
        "重さ：500g", "重量：500g", "重さ：2kg", "重量：2kg",   # 足さない見出し
        "幅：108mm", "サイズ：108mm",             # 足さない見出し（紙幅を長さと読まない）
        "内容量：2L", "容量：2L",                 # 個数の無い値は題名が個数 high でも読まない
    ],
)
def test_ac19_not_filled_forms(caption):
    # §7 W4・AC19: 補わない形。題名の個数だけが残り、source は title+caption にならない・内容量は None
    c, _ = _cmp([_o("f", ROLL + " F店", 2400, caption=caption)])
    q = _by_name(c, ROLL + " F店")["quantity"]
    assert q["source"] != "title+caption", (caption, q)
    assert q["content_amount"] is None and q["measure_total"] is None, (caption, q)
    assert q["count_total"] == 48 and q["confidence"] == "high"


def test_ac19_not_filled_when_price_varies():
    # §7 W4 条件(5)・AC19: price_varies（価格幅あり）の候補には補わない
    c, _ = _cmp([_o("f", ROLL + " F店", 2400, caption=CAP100, price_min=2400, price_max=2800)])
    o = _by_name(c, ROLL + " F店")
    assert o["price_varies"] is True
    assert o["quantity"]["source"] != "title+caption" and o["quantity"]["content_amount"] is None


def test_ac19_not_filled_when_title_is_low_or_none_or_has_content():
    # §7 W4: 項目単位の補完は題名が high で個数だけの時だけ。
    #  low（題名の中に食い違う数）・none（`長さ` は数量全体の補完の見出しではない）・内容量が題名にある時は補わない。
    low = "トイレットペーパー 12ロール×4パック 5冊"        # X3: 鎖の後ろの積と無関係な数え語付きの数 → low
    none = "トイレットペーパー おすすめ"
    c, _ = _cmp([_o("a", low, 2400, caption=CAP100), _o("b", none, 2400, caption=CAP100),
                 _o("c", ROLL_M + " C店", 1500, caption="長さ：100m")])
    qa = _by_name(c, low)["quantity"]
    assert qa["confidence"] == "low" and qa["source"] != "title+caption" and qa["content_amount"] is None
    qb = _by_name(c, none)["quantity"]
    assert qb["confidence"] == "none" and qb["source"] != "title+caption" and qb["content_amount"] is None
    assert none in _unknown_names(c)
    qc = _by_name(c, ROLL_M + " C店")["quantity"]
    assert qc["content_amount"] == pytest.approx(75) and qc["source"] != "title+caption"   # 題名の 75m のまま
    assert qc["count_total"] == 12 and not qc.get("caption_conflict")


# ---- 価格の比較への効き方（確認済みの扱い）----

def _fill_dataset():
    return [_o("f", ROLL + " F店", 2400, caption=CAP100), _o("p", ROLL + " P店", 2880)]


def test_ac19_count_basis_stays_confirmed_and_unit_price_is_plain():
    # §7 W4 確認済みの扱い・AC19: basis が個・ロールの比較は題名の個数だけで比べるので確認済みのまま・単価は確定値。
    # 自動 basis: 題名の内容量は無い → 個。F 2400÷48=50.0、P 2880÷48=60.0。最安は F。
    c, r = _cmp(_fill_dataset())
    assert c["basis"] == "個"
    f = _by_name(c, ROLL + " F店")
    assert f["unit_price"] == pytest.approx(50.0, abs=0.01) and f["provisional_unit_price"] is None
    assert f["unit_price_status"] == "confirmed" and list(f["unit_price_unconfirmed_reasons"]) == []
    assert _by_name(c, ROLL + " P店")["unit_price"] == pytest.approx(60.0, abs=0.01)
    assert c["cheapest_unit_price"]["name"] == ROLL + " F店"
    _scan(r)


def test_ac19_count_unit_basis_with_desired_is_confirmed_order():
    # basis=ロール・desired=48: F n=1=2400円、P n=1=2880円。F は確認済み（measure_from_caption を持たない）。
    c, r = _cmp(_fill_dataset(), basis="ロール", desired_quantity=48)
    p = _plan(c, ROLL + " F店")
    assert p["confirmed"] is True and "measure_from_caption" not in p["unconfirmed_reasons"]
    assert p["order_total"] == 2400 and p["payment_total"] == 2400 and p["order_total_kind"] == "payment_total"
    assert p["order_unit_price"] == pytest.approx(50.0, abs=0.01)
    assert c["cheapest_order"]["name"] == ROLL + " F店"
    assert p["quantity_source"] == "title+caption"
    _scan(r)


def test_ac19_length_basis_is_provisional_and_never_chosen_cheapest():
    # §7 W4・AC19・規律8: basis=m では補った内容量を使うので未確定（measure_from_caption）。
    # F 2400円・4800m → 1mあたり 0.5（仮）。G（題名 75m×12ロール=900m）1500円 → 1500÷900=1.6667（確認済み）。
    # F の方が安いのに、単位価格の最安は G（F は選ばれない）。P（題名に内容量なし）は単価不明。
    g = ROLL_M + " G店"
    c, r = _cmp(_fill_dataset() + [_o("g", g, 1500)], basis="m")
    f = _by_name(c, ROLL + " F店")
    assert f["unit_price"] is None and f["provisional_unit_price"] == pytest.approx(0.5, abs=0.001)
    assert f["unit_price_status"] == "unconfirmed" and list(f["unit_price_unconfirmed_reasons"]) == ["measure_from_caption"]
    assert f["unit_price_label"] == "1mあたり"
    assert _by_name(c, g)["unit_price"] == pytest.approx(1500 / 900, abs=0.01)
    assert ROLL + " P店" in _unknown_names(c)
    assert c["cheapest_unit_price"]["name"] == g
    assert ROLL + " F店" not in _selected_names(c)
    _scan(r)


def test_ac19_length_basis_order_goes_to_to_check_with_condition():
    # §7 W4・Q16・AC19: basis=m・desired=9600m。F n=ceil(9600÷4800)=2・4800円・注文単価 0.5（仮）、
    # G n=ceil(9600÷900)=11（10.667 を切り上げ）・16500円・9900m。cheapest_order は確認済みの G だけ。
    # F は安い（4800<16500）ので to_check に「説明欄『…』の内容量が正しければ」の前置きで出る。
    g = ROLL_M + " G店"
    c, r = _cmp(_fill_dataset() + [_o("g", g, 1500)], basis="m", desired_quantity=9600)
    assert c["cheapest_order"]["name"] == g
    assert c["cheapest_for_quantity"]["name"] == g
    pg = _plan(c, g)
    assert pg["n"] == 11 and pg["order_total"] == 16500 and pg["confirmed"] is True
    pf = _plan(c, ROLL + " F店")
    assert pf["n"] == 2 and pf["order_total"] == 4800
    assert pf["order_unit_price"] is None and pf["provisional_order_unit_price"] == pytest.approx(0.5, abs=0.001)
    assert pf["unit_price_status"] == "unconfirmed" and list(pf["unit_price_unconfirmed_reasons"]) == ["measure_from_caption"]
    assert pf["confirmed"] is False and "measure_from_caption" in pf["unconfirmed_reasons"]
    assert pf["payment_total"] is None and pf["order_total_kind"] == "unconfirmed_total"
    t = _tc(c, ROLL + " F店")
    assert _creasons(t) == {"measure_from_caption"}
    text = _ctext(t)
    assert "説明欄" in text and "内容量が正しければ" in text and "100" in text
    assert g not in _tc_names(c)
    _scan(r)


# ---- Q7: 自動 basis は題名から読めた内容量だけで判定 ----

def test_q7_filled_content_does_not_flip_auto_basis():
    # Q7・AC19: 高信頼 3 件（補った 2 件＋題名に 75m がある 1 件）。補った内容量を数えると 3/3 が長さで basis=m に
    # なるが、SPEC は補った分を個数だけの候補として数える → 題名由来の長さは 1/3（過半でない）→ 個。
    offers = [_o("f1", ROLL + " F1店", 2400, caption=CAP100), _o("f2", ROLL + " F2店", 2500, caption=CAP100),
              _o("t", ROLL_M + " T店", 1500)]
    c, _ = _cmp(offers)
    assert c["basis"] == "個" and c["basis_label"] == "1個あたり"
    assert _by_name(c, ROLL + " F1店")["quantity"]["source"] == "title+caption"   # 補完そのものは起きている


def test_q7_title_derived_content_still_decides_and_filled_stays_in_denominator():
    # Q7: 題名由来の長さ 3 件 → 3/3 → m（対照）。補った 1 件を足しても分母は 4・題名由来 3/4 > 1/2 → m のまま。
    t = [_o(f"t{i}", ROLL_M + f" T{i}店", 1500 + i) for i in (1, 2, 3)]
    c0, _ = _cmp(t)
    assert c0["basis"] == "m"
    c1, _ = _cmp(t + [_o("f", ROLL + " F店", 2400, caption=CAP100)])
    assert c1["basis"] == "m"
    f = _by_name(c1, ROLL + " F店")
    assert f["unit_price_status"] == "unconfirmed" and "measure_from_caption" in f["unit_price_unconfirmed_reasons"]
    # 補った 2 件 + 題名由来 2 件 = 2/4 はちょうど半数 → 個（過半を超えない）
    c2, _ = _cmp(t[:2] + [_o("f1", ROLL + " F1店", 2400, caption=CAP100), _o("f2", ROLL + " F2店", 2500, caption=CAP100)])
    assert c2["basis"] == "個"


def test_q7_title_none_caption_fill_still_counts():
    # Q7: source="caption"（題名が none の補完）は従来どおり数える。水 2 件（題名なし・説明欄「内容量：500ml×24本」）
    # ＋題名 2L×6本 の 3 件が全部 volume → ml。数えないなら 1/3 で 個 になる。
    offers = [_o("a", "天然水 おすすめ A店", 3000, caption="内容量：500ml×24本"),
              _o("b", "天然水 おすすめ B店", 3200, caption="内容量：500ml×24本"),
              _o("c", "天然水 2L×6本 C店", 2400)]
    c, _ = _cmp(offers)
    assert _by_name(c, "天然水 おすすめ A店")["quantity"]["source"] == "caption"
    assert c["basis"] == "ml"


# ---- R9: 題名の読み取りの変形は採らない ----

YUMENOKOYA = ("日本製 国産 紙 クレシア スコッティ 2倍巻きフラワーパック シングル 芯あり 100m 1セット（48ロール：12ロール×4パック）"
              " 環境に優しい紙パックリサイクルパルプを贅沢に使用した、上質な日本製フラワーパック 芯付きで100mの2倍巻きで、"
              "1セットには48ロール（12ロール")


def test_r9_yumenokoya_type_title_stays_low():
    # §7 R9: 捨てた 1 と総数が食い違う題名（yumenokoya:39998092 の録画した題名）は low のまま・単価不明。
    # 説明欄の見出し `長さ` があっても low には補わない。
    from shopping.quantity import parse_quantity

    q = parse_quantity(YUMENOKOYA)
    assert _conf(q) == "low" and q.count_total is None and q.measure_total is None
    cap = "■商品スペックタイプ：シングルロールサイズ：幅114mm×長さ100mミシン目：あり香り：あり"
    c, r = _cmp([_o("y", YUMENOKOYA, 9649, caption=cap)])
    o = _by_name(c, YUMENOKOYA)
    assert YUMENOKOYA in _unknown_names(c)
    assert o["quantity"]["confidence"] == "low" and o["quantity"]["source"] != "title+caption"
    assert o["unit_price_status"] == "unknown" and o["unit_price"] is None and o["provisional_unit_price"] is None
    _scan(r)


# --------------------------------------------------------------------------
# §7 包装の数 quantity.packs
# --------------------------------------------------------------------------

def _packs_by_search(titles):
    """search_products の出力の quantity（キーは常に出す）を題名ごとに返す。"""
    offers = [_o(f"s{i}", t, 1000 + i) for i, t in enumerate(titles)]
    ad = FakeAdapter({("aa", 1): (offers, len(offers))})
    r = service.search_products(["aa"], adapter=ad, sleep=NOSLEEP)
    assert r["ok"], r
    return {o["name"]: o["quantity"] for o in r["offers"]}


def _pk(p):
    return (p["unit"], p["count"], p["per_pack"], p["per_pack_unit"])


PACK_CASES = [
    # F1: N<数え語>入(り) [×] M<包装語> [セット|パック|入]
    ("文化たきつけ 富士屋 着火剤 18本入 2袋セット", 36, "本", [("袋", 2, 18, "本")]),
    ("文化たきつけ 18本入り×2袋", 36, "本", [("袋", 2, 18, "本")]),
    ("文化たきつけ 18本入り ×10個セット", 180, "本", [("個", 10, 18, "本")]),
    # F2: N<数え語>×M<包装語> [セット|パック|入]
    ("文化たきつけ 18本×2袋", 36, "本", [("袋", 2, 18, "本")]),
    # F3: T<数え語>（N<数え語>×M<包装語> [セット|パック]）。括弧の外 T が N×M と等しい時だけ
    ("文化たきつけ 36本（18本×2個セット）", 36, "本", [("個", 2, 18, "本")]),
    ("着火剤 240枚（60枚×4袋）", 240, "枚", [("袋", 4, 60, "枚")]),
    # 形が複数あっても全部が同じ内容なら 1 要素
    ("文化たきつけ 18本入 2袋セット 36本（18本×2袋）", 36, "本", [("袋", 2, 18, "本")]),
]


@pytest.mark.parametrize("title,total,cunit,packs", PACK_CASES, ids=[c[0][:24] for c in PACK_CASES])
def test_packs_forms_f1_f2_f3(title, total, cunit, packs):
    # §7 包装の数: 総数は変えず（high のまま）packs を足す。形は F1〜F3。unit=包装語の正規名・count=包装の数・
    # per_pack=1包装あたりの数・per_pack_unit=その数え語。
    q = _packs_by_search([title])[title]
    assert q["count_total"] == total and q["count_unit"] == cunit
    assert q["confidence"] == "high" and q["title_confidence"] == "high"
    assert [_pk(p) for p in q["packs"]] == packs


@pytest.mark.parametrize(
    "title",
    [
        "文化たきつけ 富士屋",                          # none
        "ゼリー 3個入り 3冊",                           # low（P0）
        "お茶 24本",                                    # 包装の数なし
        "天然水 500ml×24本",                            # 内容量×個数は包装の数ではない
        "洗濯洗剤 詰め替え 900g×6袋",
        "文化たきつけ 18本入 2袋セット 40本",            # 言い直しの総数が N×M と食い違う → low → []
    ],
)
def test_packs_empty_when_unreadable_or_not_high(title):
    # §7 包装の数: 読めない・総数が low／none の時は []（キーは常に出す）。
    q = _packs_by_search([title])[title]
    assert "packs" in q and list(q["packs"]) == []


def test_packs_key_is_always_present_in_compare_output_and_json_safe():
    # §7: packs は search_products にも compare_offers の各候補（groups・unknown_offers）にも常にある（list）。
    titles = [t for t, *_ in PACK_CASES[:3]] + ["文化たきつけ 富士屋", "お茶 24本"]
    c, r = _cmp([_o(f"k{i}", t, 1000 + i) for i, t in enumerate(titles)])
    json.dumps(r, ensure_ascii=False)
    for o in _offers_of(c):
        assert isinstance(o["quantity"]["packs"], list), o["name"]


def test_packs_does_not_decide_the_total():
    # §7: 包装の数だけで総数は決めない。packs の足された題名でも、総数・count_unit は題名の読み取りのまま。
    # F1 の「18本入 2袋セット」は 36本（18×2）。packs の count（2）を総数にしない。
    from shopping.quantity import parse_quantity

    q = parse_quantity("文化たきつけ 富士屋 着火剤 18本入 2袋セット")
    assert q.count_total == 36 and q.count_unit == "本" and _conf(q) == "high"
    assert hasattr(q, "packs")  # QuantityInfo の項目（§7）。形（dict か値か）は出力 JSON の側で確かめる


# --------------------------------------------------------------------------
# AC20・Q20: basis=袋（購入単位のまま比較）
# --------------------------------------------------------------------------
# 名前（SPEC の例と同じ形）:
B1 = "文化たきつけ 富士屋 着火剤 18本入 2袋セット"      # (b): 2袋・1袋18本。36本 high
B2 = "文化たきつけ 18本×2袋"                           # (b): 2袋・1袋18本
B3 = "文化たきつけ 9本入 2袋セット"                    # (b): 2袋・1袋9本（中身が違う）
B4 = "文化たきつけ 9本入 2袋セット B店"                 # (b): 2袋・1袋9本
A1 = "文化たきつけ 30袋"                               # (a): count_unit=袋・30袋
G10 = "文化たきつけ 18本入り ×10個セット"              # 180本。packs の包装語は個（袋の裏付けなし）
M36 = "文化たきつけ 36本（18本×2個セット）"             # 36本。packs の包装語は個
H18 = "文化たきつけ 18本入り"                          # 18本（packs なし）
Y0 = "文化たきつけ 富士屋"                             # 数量 none
M60 = "文化たきつけ 60セット入り 1箱"                   # 数え語セット


def _d1(**extra):
    # basis=袋・desired=30。(b) B1 880円・B2 900円（送料込み）。それ以外（袋の裏付けなし）は G10 2330円（込み）・
    # M36 590円（込み）・H18 327円（送料別）・Y0 168円（送料別・数量 none）。
    offers = [_o("b1", B1, 880), _o("b2", B2, 900), _o("g10", G10, 2330), _o("m36", M36, 590),
              _o("h18", H18, 327, ship="separate"), _o("y0", Y0, 168, ship="separate")]
    offers += list(extra.get("more", []))
    return _cmp(offers, basis="袋", desired_quantity=30)


@pytest.fixture(scope="module")
def d1():
    return _d1()


def test_ac20_b_candidates_are_compared_in_one_group_by_bag_count(d1):
    # Q20 (b)・AC20: packs に袋がある B1・B2 は袋の数（2袋）で比べる。単位価格＝価格÷袋の数: B1 880÷2=440.0、
    # B2 900÷2=450.0（ラベル「1袋あたり」）。同じグループ・確認済み（1袋の中身が一致 18本）。
    c, r = d1
    g = [g for g in c["groups"] if {o["name"] for o in g["offers"]} >= {B1, B2}]
    assert len(g) == 1 and {o["name"] for o in g[0]["offers"]} == {B1, B2}
    b1, b2 = _by_name(c, B1), _by_name(c, B2)
    assert b1["unit_price"] == pytest.approx(440.0, abs=0.01) and b2["unit_price"] == pytest.approx(450.0, abs=0.01)
    assert b1["unit_price_label"] == "1袋あたり"
    assert b1["unit_price_status"] == "confirmed" and b2["unit_price_status"] == "confirmed"
    assert c["main_count_unit"] == "袋"
    assert c["cheapest_unit_price"]["name"] == B1


def test_ac20_desired_is_in_bags_and_cheapest_order(d1):
    # Q20: desired=30 は袋のまま（本に換算しない）。B1 n=ceil(30÷2)=15・15袋×2=30袋・13200円（単価 440.0）、
    # B2 n=15・13500円（450.0）。cheapest_order は確認済みの安い方 B1。order_plans は (a)(b) だけ。
    c, _ = d1
    p1, p2 = _plan(c, B1), _plan(c, B2)
    assert p1["n"] == 15 and p1["order_quantity"] == 30 and p1["order_total"] == 13200
    assert p1["order_unit_price"] == pytest.approx(440.0, abs=0.01) and p1["confirmed"] is True
    assert p1["payment_total"] == 13200 and p1["order_total_kind"] == "payment_total"
    assert p2["n"] == 15 and p2["order_total"] == 13500 and p2["order_unit_price"] == pytest.approx(450.0, abs=0.01)
    assert c["cheapest_order"]["name"] == B1 and c["cheapest_for_quantity"]["name"] == B1
    assert [p["name"] for p in c["order_plans"]] == [B1, B2]     # 注文額の安い順・counter_assumed は入らない


def test_ac20_not_zero_candidates_and_all_others_kept_in_to_check(d1):
    # AC20: 候補ゼロにならない。袋の裏付けの無い候補（G10・M36・H18・Y0）は捨てず to_check に残る（counter_assumed）。
    # ① (b) の 1袋の中身は B1・B2 とも 18本でただ1通り → 本の候補で総数が 18 で割り切れるものは「1袋が18本なら」で換算。
    #   G10: 180本=10袋相当 → n=ceil(30÷10)=3（540本=30袋相当）・2330×3=6990円・仮の単価 6990÷30=233.0
    #   M36: 36本=2袋相当 → n=15・590×15=8850円・8850÷30=295.0
    #   H18: 18本=1袋相当 → n=30・327×30=9810円（送料別）・9810÷30=327.0
    # ② Y0（数量 none）は「この商品1点が1袋なら」: 注文個数＝希望量 30点・168×30=5040円（送料別）・5040÷30=168.0
    c, _ = d1
    assert _tc_names(c) == {G10, M36, H18, Y0}
    exp = {G10: (3, 6990, 233.0, "included"), M36: (15, 8850, 295.0, "included"),
           H18: (30, 9810, 327.0, "separate"), Y0: (30, 5040, 168.0, "separate")}
    for name, (n, total, prov, ship) in exp.items():
        t = _tc(c, name)
        assert t["n"] == n and t["order_total"] == total, name
        assert t["order_quantity"] == 30, name                                    # 30袋相当
        assert t["order_unit_price"] is None and t["provisional_order_unit_price"] == pytest.approx(prov, abs=0.01), name
        assert t["unit_price_status"] == "unconfirmed" and list(t["unit_price_unconfirmed_reasons"]) == ["counter_assumed"], name
        assert t["confirmed"] is False and "counter_assumed" in t["unconfirmed_reasons"], name
        assert "counter_assumed" in _creasons(t), name
        assert t["shipping_status"] == ship and t["payment_total"] is None, name
        assert t["order_total_kind"] == ("unconfirmed_total" if ship == "included" else "item_subtotal"), name
    # 条件文の前置き
    for name in (G10, M36, H18):
        assert "1袋が18本なら" in _ctext(_tc(c, name)), name
    assert "この商品1点が1袋なら" in _ctext(_tc(c, Y0))
    # 送料別は送料の条件と合算した 1 文（Q16・B3）: X=cheapest_order の注文額 13200。閾値は 13200−注文額
    for name, th in ((H18, 3390), (Y0, 8160)):
        t = _tc(c, name)
        assert len(t["conditions"]) == 1 and "送料" in _ctext(t) and str(th) in _ctext(t), name
        assert "shipping_separate" in _creasons(t)


def test_ac20_counter_assumed_never_selected_and_stay_unknown(d1):
    # Q20・規律8: 一番安く見える候補（Y0 5040円・H18 9810円は B1 の 13200円より安い）でも cheapest_order・
    # cheapest_unit_price・cheapest_for_quantity に選ばれない。order_plans に入らず、unknown_offers に従来どおり残る
    # （単価を出さない: unit_price=null・provisional=null・"unknown"）。
    c, r = d1
    assert not (_selected_names(c) & {G10, M36, H18, Y0})
    assert not ({p["name"] for p in c["order_plans"]} & {G10, M36, H18, Y0})
    assert set(_unknown_names(c)) == {G10, M36, H18, Y0}
    for n in (G10, M36, H18, Y0):
        o = _by_name(c, n)
        assert o["unit_price"] is None and o["provisional_unit_price"] is None and o["unit_price_status"] == "unknown"
    _scan(r)   # AC17: 理由のある候補・案に素の単価が 0 件・注文額の種類の一貫性


def test_ac20_caveats_report_assumption_count_and_basis_of_one_bag(d1):
    # Q20: caveats に、換算の仮定を置いた件数（4件）と、①の根拠「1袋＝18本は候補 2件の商品名から」を出す。
    c, _ = d1
    assumption = [x for x in c["caveats"] if "仮定" in x]
    assert assumption and any("4件" in x for x in assumption), c["caveats"]
    assert "1袋＝18本" in _caveats(c) and any("2件" in x and "1袋＝18本" in x for x in c["caveats"]), c["caveats"]


def test_ac20_no_desired_keeps_old_unknown_behaviour_for_non_bag_candidates():
    # Q20: 希望量が無い時は換算する数が無い。(b) は袋の数で比べ、袋の裏付けの無い候補は単価を出さず unknown に残る。
    # B1 880÷2=440.0。order_plans・to_check は空（Q16）。
    c, _ = _cmp([_o("b1", B1, 880), _o("g10", G10, 2330), _o("y0", Y0, 168)], basis="袋")
    assert _by_name(c, B1)["unit_price"] == pytest.approx(440.0, abs=0.01)
    assert set(_unknown_names(c)) == {G10, Y0}
    assert list(c["order_plans"]) == [] and c["cheapest_order"] is None and list(c["to_check"]) == []


def test_ac20_not_empty_when_no_bag_candidate_exists():
    # AC20: 袋の候補が 1 件も無くても候補ゼロにならない（文化たきつけ basis=袋・desired=30 の型）。確認済みが無いので
    # 確認済みでない案を全部 to_check に出し（閾値なし）、cheapest_order は null。② 1袋の中身は決まらない。
    #   H18: 18本=18袋相当 → n=ceil(30÷18)=2・327×2=654円。G10: 180袋相当 → n=1・2330円。Y0: n=30・5040円。
    c, r = _cmp([_o("g10", G10, 2330), _o("h18", H18, 327, ship="separate"), _o("y0", Y0, 168, ship="separate")],
                basis="袋", desired_quantity=30)
    assert c["cheapest_order"] is None and c["cheapest_unit_price"] is None
    assert _tc_names(c) == {G10, H18, Y0}
    assert (_tc(c, H18)["n"], _tc(c, H18)["order_total"]) == (2, 654)
    assert (_tc(c, G10)["n"], _tc(c, G10)["order_total"]) == (1, 2330)
    assert (_tc(c, Y0)["n"], _tc(c, Y0)["order_total"]) == (30, 5040)
    assert "この商品の1本が1袋なら" in _ctext(_tc(c, H18)) and "この商品の1本が1袋なら" in _ctext(_tc(c, G10))
    assert "この商品1点が1袋なら" in _ctext(_tc(c, Y0))
    assert all(x["threshold"] is None for t in c["to_check"] for x in t["conditions"])   # 確認済みが無い時は閾値なし
    _scan(r)


MAYFAIR = ("文化たきつけ 60セット入り 1箱 着火剤 強力着火 灯油系 マッチ1本で簡単着火 焚き火・薪ストーブ・BBQ用 丸実富士屋商店")


def test_ac20_mayfair_low_title_reaches_to_check_with_reading_as_assumption():
    # Q20（レビュー R1）・AC20・C5: Mayfair 型の題名（『マッチ1本で』の 1 で low。実題名）は、題名に読めた個数の読み
    # 60セット を仮定にする。「この商品が60セットで、1セットが1袋なら」→ 袋の数＝60・n=ceil(30÷60)=1・9710円（送料別）。
    # 9710円 < cheapest_order の 13200円 → to_check に必ず出る（空振りで通さない）。閾値 13200−9710=3490（送料の条件と合算した1文）。
    # 条件文に「題名に食い違う数がある」。order_plans に入らず cheapest_order に選ばれず、unknown_offers に残る。
    c, r = _d1(more=[_o("m60", MAYFAIR, 9710, ship="separate")])
    t = _tc(c, MAYFAIR)
    text = _ctext(t)
    assert t["n"] == 1 and t["order_total"] == 9710 and t["shipping_status"] == "separate"
    assert "counter_assumed" in _creasons(t) and list(t["unit_price_unconfirmed_reasons"]) == ["counter_assumed"]
    assert "60セット" in text and "1セットが1袋なら" in text and "食い違う数がある" in text
    assert len(t["conditions"]) == 1 and "送料" in text and "3490" in text
    assert t["order_unit_price"] is None and t["payment_total"] is None and t["order_total_kind"] == "item_subtotal"
    assert MAYFAIR in _unknown_names(c) and MAYFAIR not in {p["name"] for p in c["order_plans"]}
    assert MAYFAIR not in _selected_names(c)
    _scan(r)


def test_ac20_unreadable_candidates_appear_only_when_they_could_be_cheaper():
    # Q20（量が読めない候補）: 仮定の注文額が cheapest_order（13200円）より安くなり得る時だけ to_check。
    #   MAYFAIR 90000円（n=1・90000円）・Y0 1000円（none・n=30・30000円）は 13200 を超えるので出ない。
    #   unknown_offers には残る（件数と理由は caveats）。比較として Y0 168円（5040円）は出る（d1 の試験）。
    c, _ = _d1(more=[_o("m60", MAYFAIR, 90000, ship="separate")])
    assert MAYFAIR not in _tc_names(c) and MAYFAIR in _unknown_names(c)
    offers = [_o("b1", B1, 880), _o("y0", Y0, 1000, ship="separate")]
    c2, _ = _cmp(offers, basis="袋", desired_quantity=30)
    assert Y0 not in _tc_names(c2) and Y0 in _unknown_names(c2) and c2["cheapest_order"]["name"] == B1


# ---- 1袋の中身の食い違い（pack_content_differs）----

def _d2(extra=()):
    # B1 880・B2 900（18本入 2袋）と B3 500（9本入 2袋）。G10・M36 も入れる。basis=袋・desired=30。
    offers = [_o("b1", B1, 880), _o("b2", B2, 900), _o("b3", B3, 500), _o("g10", G10, 2330), _o("m36", M36, 590)]
    return _cmp(offers + list(extra), basis="袋", desired_quantity=30)


def test_ac20_pack_content_differs_is_kept_in_plans_and_to_check():
    # Q20・AC20: 基準＝(b) の最多の値 18本（B1・B2 の 2 件。B3 は 1 件）。B3 は 9本入 → pack_content_differs。
    # 単価は仮（B3 は 2袋・n=15・500×15=7500円・7500÷30=250.0）。order_plans に残り、to_check に
    # 「1袋の中身が違う（9本入）。…」。cheapest_order・cheapest_unit_price は確認済みの B1（440）で、安い B3（250）は選ばれない。
    c, r = _d2()
    p3 = _plan(c, B3)
    assert p3["n"] == 15 and p3["order_total"] == 7500 and p3["order_quantity"] == 30
    assert p3["confirmed"] is False and "pack_content_differs" in p3["unconfirmed_reasons"]
    assert p3["order_unit_price"] is None and p3["provisional_order_unit_price"] == pytest.approx(250.0, abs=0.01)
    assert p3["unit_price_status"] == "unconfirmed" and list(p3["unit_price_unconfirmed_reasons"]) == ["pack_content_differs"]
    assert c["cheapest_order"]["name"] == B1 and c["cheapest_unit_price"]["name"] == B1
    assert B3 not in _selected_names(c)
    t = _tc(c, B3)
    assert "pack_content_differs" in _creasons(t)
    assert "1袋の中身が違う" in _ctext(t) and "9本" in _ctext(t)
    # 独立レビュー B2: 条件文に基準の中身と件数「基準＝18本入（2件の商品名から）」。caveats にも基準・件数と多数決の旨
    assert "基準＝18本入" in _ctext(t) and "2件" in _ctext(t)
    base = [x for x in c["caveats"] if "基準" in x and "18本" in x]
    assert base and any("2件" in x for x in base), c["caveats"]
    assert any("多数決" in x for x in c["caveats"]), c["caveats"]
    o3 = _by_name(c, B3)
    assert o3["unit_price"] is None and o3["provisional_unit_price"] == pytest.approx(250.0, abs=0.01)
    assert list(o3["unit_price_unconfirmed_reasons"]) == ["pack_content_differs"]
    for n in (B1, B2):
        assert _plan(c, n)["confirmed"] is True
    _scan(r)


def test_ac20_when_one_bag_content_is_not_unique_assumption_falls_back_to_this_product():
    # Q20 ①②: (b) の 1袋の中身が 18本と 9本の 2 通り → ① は使えず ② 「この商品の1本が1袋なら」。
    #   G10: 180本 → 180袋相当 → n=ceil(30÷180)=1・2330円。M36: 36袋相当 → n=1・590円。
    c, _ = _d2()
    for name, total in ((G10, 2330), (M36, 590)):
        t = _tc(c, name)
        assert t["n"] == 1 and t["order_total"] == total
        assert "この商品の1本が1袋なら" in _ctext(t) and "1袋が18本なら" not in _ctext(t)
        assert "counter_assumed" in _creasons(t)


def test_ac20_base_is_the_majority_value_not_the_cheapest():
    # Q20: 基準＝最多の値。9本入が 2 件（B3 500円・B4 520円）、18本入が 1 件（B1 300円・最安）→ 基準は 9本。
    # 18本入の B1 が食い違い扱い（n=15・4500円・仮 150.0）で cheapest_order にならない。cheapest_order は確認済みの B3（7500円）。
    c, _ = _cmp([_o("b1", B1, 300), _o("b3", B3, 500), _o("b4", B4, 520)], basis="袋", desired_quantity=30)
    p1 = _plan(c, B1)
    assert p1["order_total"] == 4500 and p1["confirmed"] is False and "pack_content_differs" in p1["unconfirmed_reasons"]
    assert p1["provisional_order_unit_price"] == pytest.approx(150.0, abs=0.01)
    assert _plan(c, B3)["confirmed"] is True and _plan(c, B4)["confirmed"] is True
    assert c["cheapest_order"]["name"] == B3
    t = _tc(c, B1)
    assert "1袋の中身が違う" in _ctext(t) and "18本" in _ctext(t)


def test_ac20_tie_is_broken_by_cheapest_confirmed_order_amount():
    # Q20: 同数（18本入・9本入が 1 件ずつ）なら、確認済みの候補の最安の注文額が安い方が基準。
    # 9本入 B3 n=15・7500円 < 18本入 B1 13200円 → 基準は 9本。B1 は食い違い（order_plans に残り単価は仮）。
    # cheapest_order は B3。B1（13200円）は B3 より高いので to_check には出ない。
    c, _ = _cmp([_o("b1", B1, 880), _o("b3", B3, 500)], basis="袋", desired_quantity=30)
    assert c["cheapest_order"]["name"] == B3
    p1 = _plan(c, B1)
    assert p1["confirmed"] is False and "pack_content_differs" in p1["unconfirmed_reasons"]
    assert _plan(c, B3)["confirmed"] is True
    assert B1 not in _tc_names(c)


def test_ac20_a_candidates_are_not_counted_as_content_mismatch():
    # Q20: (a)（count_unit=袋）は 1袋の中身を書いていないので食い違いに数えない（従来どおり確認済み）。
    # A1 30袋 15000円: n=1・30袋・15000円・単価 500.0。B1・B2・B3 と同じグループ。cheapest_order は B1（13200円）。
    c, _ = _cmp([_o("a1", A1, 15000), _o("b1", B1, 880), _o("b2", B2, 900), _o("b3", B3, 500)],
                basis="袋", desired_quantity=30)
    pa = _plan(c, A1)
    assert pa["n"] == 1 and pa["order_quantity"] == 30 and pa["order_total"] == 15000
    assert pa["confirmed"] is True and list(pa["unconfirmed_reasons"]) == []
    assert pa["order_unit_price"] == pytest.approx(500.0, abs=0.01)
    g = [g for g in c["groups"] if A1 in {o["name"] for o in g["offers"]}]
    assert len(g) == 1 and {o["name"] for o in g[0]["offers"]} == {A1, B1, B2, B3}
    assert c["cheapest_order"]["name"] == B1
    assert B3 in _tc_names(c) and A1 not in _tc_names(c)


# --------------------------------------------------------------------------
# Q19・AC15: 主グループと違う数え語の候補（ゴダイ型）
# --------------------------------------------------------------------------
P1 = "貼るカイロ 30枚 P1店"
P2 = "貼るカイロ 60枚 P2店"
GD = "貼るカイロ 30個 ゴダイ店"
NN = "量の分からないカイロ"


def _q19(g_price, g_ship, with_none=True):
    # 主グループ＝枚（2 件）、個（1 件）。desired=60（basis 個）。
    #   P1 30枚 1300円: n=2・2600円。P2 60枚 2400円: n=1・2400円 → cheapest_order=P2（40.0/枚）。
    #   GD 30個: n=2・g_price×2。
    offers = [_o("p1", P1, 1300), _o("p2", P2, 2400), _o("gd", GD, g_price, ship=g_ship)]
    if with_none:
        offers.append(_o("nn", NN, 500))
    return _cmp(offers, desired_quantity=60)


@pytest.mark.parametrize("ship", ["included", "separate"])
def test_q19_other_counter_candidate_goes_to_main_to_check_with_assumption(ship):
    # Q19・AC15: 個 の GD（1000円・n=2・2000円 < P2 の 2400円）は、確認済みの横断比較はせず（cheapest_order は P2・
    # cheapest_unit_price は 枚 の最安）、主グループの to_check に「1個が1枚なら」の条件つきで出る。
    # 単価は仮 2000÷60=33.33。送料別なら送料の条件と合算した 1 文（閾値 2400−2000=400）。
    c, r = _q19(1000, ship)
    assert c["main_count_unit"] == "枚"
    assert c["cheapest_order"]["name"] == P2 and c["cheapest_for_quantity"]["name"] == P2
    assert c["cheapest_unit_price"]["name"] == P2
    assert GD not in {c[k]['name'] for k in ('cheapest_order', 'cheapest_unit_price', 'cheapest_for_quantity')}
    t = _tc(c, GD)
    assert t["n"] == 2 and t["order_total"] == 2000 and t["order_quantity"] == 60
    assert "counter_assumed" in _creasons(t) and "1個が1枚なら" in _ctext(t)
    assert t["order_unit_price"] is None and t["provisional_order_unit_price"] == pytest.approx(2000 / 60, abs=0.01)
    assert t["unit_price_status"] == "unconfirmed" and list(t["unit_price_unconfirmed_reasons"]) == ["counter_assumed"]
    assert t["payment_total"] is None
    if ship == "separate":
        assert len(t["conditions"]) == 1 and "送料" in _ctext(t) and "400" in _ctext(t)
        assert t["order_total_kind"] == "item_subtotal"
    else:
        assert t["order_total_kind"] == "unconfirmed_total"
    assert any("仮定" in x and "1件" in x for x in c["caveats"]), c["caveats"]
    _scan(r)


def test_q19_other_group_keeps_its_own_result_and_none_is_not_assumed():
    # Q19: 個 のグループ自身の結果（groups[].order_plans・cheapest_order）は従来どおり。数量 none（NN）は個数が無いので
    # 仮定を置かず、どの to_check にも出ない（unknown_offers に残る）。
    c, _ = _q19(1000, "included")
    g = [g for g in c["groups"] if g.get("count_unit") == "個"]
    assert len(g) == 1 and {o["name"] for o in g[0]["offers"]} == {GD}
    assert GD in str(g[0]["cheapest_order"]["name"]) and g[0]["cheapest_order"]["n"] == 2
    assert NN in _unknown_names(c) and NN not in _tc_names(c)
    assert NN not in {p["name"] for g2 in c["groups"] for p in g2.get("to_check", [])}


def test_q19_other_counter_candidate_not_cheaper_is_not_listed():
    # Q19: 出す条件は Q16 の to_check と同じ（主グループの cheapest_order より安くなり得る時）。
    # GD 5000円（送料別）: n=2・10000円 ≥ 2400円 → 出ない。
    c, _ = _q19(5000, "separate")
    assert GD not in _tc_names(c)
    assert c["cheapest_order"]["name"] == P2


# --------------------------------------------------------------------------
# 規律8: 全入口の反例（最安でも未確定の候補は選ばれない）と §10
# --------------------------------------------------------------------------

def test_guarantee_unconfirmed_never_selected_across_three_entrances():
    # 規律8（金額の保証）: basis=袋（counter_assumed・pack_content_differs）・basis=個（counter_assumed）・
    # basis=m（measure_from_caption）の 3 入口で、最安でも確認済みでない候補は数量を使う最安の枠に選ばれない。
    # 正常な確認済みの候補（B1 など）は選ばれる（反例だけを落とす）。
    c1, r1 = _d2()
    assert not (_selected_names(c1) & {B3, G10, M36}) and c1["cheapest_order"]["name"] == B1
    c2, r2 = _q19(1000, "included")
    assert GD not in {c2["cheapest_order"]["name"], c2["cheapest_unit_price"]["name"]}
    g = ROLL_M + " G店"
    c3, r3 = _cmp(_fill_dataset() + [_o("g", g, 1500)], basis="m", desired_quantity=9600)
    assert ROLL + " F店" not in {c3["cheapest_order"]["name"], c3["cheapest_unit_price"]["name"],
                                 c3["cheapest_for_quantity"]["name"]}
    assert c3["cheapest_order"]["name"] == g
    for r in (r1, r2, r3):
        _scan(r)


def test_mcp_instructions_guide_bag_basis_and_packs():
    # §10 (3)（WP15 段B）: 「18本入りを30袋」は basis=袋・desired=30 のままでよい（本への換算を求めない）。
    # 道具が袋の数と 1 袋の中身（quantity.packs）で比べる。段B の指示は INSTRUCTIONS だけに足す。
    from shopping.mcp_server import INSTRUCTIONS

    assert "basis=袋" in INSTRUCTIONS and "quantity.packs" in INSTRUCTIONS
    assert not ("basis=本" in INSTRUCTIONS and "540" in INSTRUCTIONS)   # 旧: 本・540 への換算を求める指示


def test_mcp_compare_offers_description_stays_within_2000():
    # §10: 段B の指示は _ORDER_POINTER（compare_offers の説明）を増やさない。2000 字ガード（WP11）を維持。
    from mcp import Client

    from shopping.mcp_server import build_server

    async def go():
        async with Client(build_server()) as c:
            return {t.name: t for t in (await c.list_tools()).tools}

    ts = asyncio.run(asyncio.wait_for(go(), timeout=30))
    for name in ("compare_offers", "search_products"):
        assert len(ts[name].description) <= 2000, (name, len(ts[name].description))


def test_ac20_json_scan_has_no_plain_unit_price_for_new_reasons():
    # AC17 の拡張: 新しい未確定理由（measure_from_caption・counter_assumed・pack_content_differs）の候補・案に
    # 素の unit_price・order_unit_price が 0 件。理由は単価の理由に数える（送料は含まない）。走査が空振りでないことも確かめる。
    c, r = _d2()
    seen = _scan(r)
    unc = [p for p, s in seen["plan"] if s == "unconfirmed"]
    assert unc and any("to_check" in p for p in unc)
    assert any(s == "unconfirmed" for _, s in seen["offer"])          # B3（pack_content_differs）の候補 dict
    assert re.search(r"unknown", " ".join(s for _, s in seen["offer"]))  # G10・M36 の unknown_offers
