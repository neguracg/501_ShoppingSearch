# @owns WP16（数量の抽出と採用の分離）の自作確認。独立試験（ブラインド）の代わりではない
"""SPEC §7「題名 low の出力」「説明欄の数量による補完」・§8 Q7・Q20・Q21・AC21〜AC24 の自作確認。
題名 low の low_reason・readings・U2a、説明欄の各文の読み取り（caption_candidates）、U1（桁の照合は比較グループの統計）、U2b、
確認済みの集合が変わらないこと、自動 basis が仮の量で反転しないこと、counter_basis の読みの仮定、表示。"""
import pytest

from fakes import make_offer
from shopping import mcp_server, service
from shopping.caption_adopt import adopt_u1_contents
from shopping.caption_quantity import read_offer_quantity, read_sentences, split_sentences
from shopping.pricing import compare, is_confirmed, quantity_marks_text, unconfirmed_reasons
from shopping.quantity import parse_quantity


def offer(code, title, caption="", price=1000, **kw):
    o = make_offer(code, name=title, price=price, shipping_status="included")
    o.caption = caption
    for k, v in kw.items():
        setattr(o, k, v)
    return o


# ---- 題名 low の出力（U2a・readings・low_reason）----

def test_content_ambiguous_keeps_total_and_readings():
    q = parse_quantity("トイレットペーパー 48ロール シングル 75m 150m")
    assert q.confidence == "low" and q.low_reason == "content_ambiguous"
    assert (q.count_total, q.count_unit) == (48, "ロール")
    assert q.content_amount is None and q.content_dimension is None and q.measure_total is None
    assert q.readings == {"counts": [{"count": 48, "count_unit": "ロール"}], "contents": {"length": [75.0, 150.0]}}


def test_multiple_totals_keeps_no_total_but_readings():
    q = parse_quantity("トイレットペーパー 12ロール 18ロール")
    assert q.confidence == "low" and q.low_reason == "multiple_totals" and q.count_total is None
    assert [c["count"] for c in q.readings["counts"]] == [12, 18]


def test_high_and_none_have_no_readings_or_reason():
    for t in ("トイレットペーパー 48ロール", "ティッシュ"):
        q = parse_quantity(t)
        assert q.low_reason is None and q.readings is None


def test_every_low_has_a_reason_and_readings():
    for t in ("洗剤 900g 1.5kg", "単3電池 40本 48本", "水 500ml×24本 2L×12本", "うどん 3玉 5食 ×", "ボールペン 0.5mm 1.0mm 10本 12本"):
        q = parse_quantity(t)
        if q.confidence == "low":
            assert q.low_reason and q.readings is not None


# ---- 説明欄の各文の読み取り ----

def test_sentences_split_on_inline_headings_without_a_heading_list():
    assert split_sentences("スコッティ入数:8ロール×6個ロールサイズ:108mm×100m") == ["スコッティ入数", "8ロール×6個", "108mm×100m"]
    got = {r.text: r for r in read_sentences("■ロールサイズ:108mm×150m ■150mの長さ ■内容量:2L")}
    assert got["108mm×150m"].info.content_amounts == {"length": 150.0}       # 寸法の大きい方（Q15）
    assert got["150mの長さ"].info.content_amounts == {"length": 150.0}
    assert got["2L"].info.content_amounts == {"volume": 2000.0} and not got["2L"].counted


def test_sentences_skip_per_unit_wording_and_related_keywords():
    assert read_sentences("1個あたり500ml") == []
    assert read_sentences("本体です 関連キーワード 100m 20ロール") == []


def test_caption_candidates_marks_values_that_are_not_adopted():
    # 題名 none・見出し付きの値が無い: 各文の値は印だけ（単価に使わない）
    q = read_offer_quantity(offer("a", "トイレットペーパー", "ロールサイズ:108mm×150m"))
    assert q.confidence == "none" and q.count_total is None
    assert q.caption_candidates == [{"count_total": None, "count_unit": None, "content_amount": 150.0,
                                     "content_dimension": "length", "evidence": "108mm×150m"}]
    # 題名 high で内容量もある候補には各文の値を残さない
    assert read_offer_quantity(offer("b", "トイレットペーパー 12ロール 50m", "ロールサイズ:108mm×150m")).caption_candidates == []
    # キーは常にあり、無ければ []
    assert read_offer_quantity(offer("c", "トイレットペーパー 12ロール", "")).caption_candidates == []


# ---- U1: 題名が個数だけ high の候補の内容量（桁の照合は比較グループ）----

def group_of(n_title=4, median_m=75):
    return [offer(f"t{i}", f"トイレットペーパー シングル {median_m}m 12ロール", "", 1000 + i) for i in range(n_title)]


def target(caption, price=4000, **kw):
    return offer("tgt", "トイレットペーパー シングル 48ロール", caption, price, **kw)


def adopt(o, group):
    return compare(group + [o], basis="m").groups, o


def test_u1_adopts_when_unique_and_same_magnitude_and_marks_provisional():
    t = target("ロールサイズ:108mm×100m")
    q0 = read_offer_quantity(t)
    assert q0.content_amount is None and q0.u1_pending == {"length": {"amount": 100.0, "evidence": "108mm×100m"}}   # 抽出だけでは採らない
    c = compare(group_of() + [t], basis="m")
    q = t.quantity
    assert (q.source, q.content_amount, q.content_dimension, q.measure_total) == ("title+caption", 100.0, "length", 4800.0)
    assert q.caption_candidates == [] and q.caption_evidence == "108mm×100m"
    assert unconfirmed_reasons(t) == ["measure_from_caption"]
    assert t.unit_price == pytest.approx(4000 / 4800) and c.cheapest_unit_price.mall_item_code != "tgt"


def test_u1_magnitude_check_rejects_sheet_size_and_keeps_candidate():
    t = target("シートサイズ:206×220mm")
    compare(group_of() + [t], basis="m")
    assert t.quantity.content_amount is None and t.quantity.u1_adopted == []
    assert [(c["content_amount"], c["content_dimension"]) for c in t.quantity.caption_candidates] == [(0.22, "length")]


def test_u1_needs_four_title_sourced_values_in_the_group():
    t = target("ロールサイズ:108mm×100m")
    compare(group_of(3) + [t], basis="m")
    assert t.quantity.content_amount is None and t.quantity.caption_candidates


def test_u1_group_stat_ignores_adopted_and_provisional_quantities():
    g = group_of(3)
    other = target("ロールサイズ:108mm×100m")          # 題名由来ではない（補う側）は統計に数えない
    t = target("ロールサイズ:108mm×100m")
    compare(g + [other, t], basis="m")
    assert t.quantity.content_amount is None


def test_u1_multiple_values_are_not_adopted_and_stay_as_candidates():
    t = target("シングル 150m ■ダブル 75m")        # 別々の文（同じ文に 2 つあると題名と同じく low になり読まれない）
    compare(group_of() + [t], basis="m")
    assert t.quantity.content_amount is None
    assert sorted(c["content_amount"] for c in t.quantity.caption_candidates) == [75.0, 150.0]


def test_u1_counted_sentence_must_match_the_title_total():
    # (ii) 『12ロール 50m シングルと比較』は 12≠48 なので 50m を内容量の候補にしない。150m は採る。50m は印に残る
    t = target("■ロールサイズ:108mm×150m ※スコッティ フラワーパック 12ロール 50m シングルと比較")
    compare(group_of() + [t], basis="m")
    q = t.quantity
    assert q.content_amount == 150.0
    assert q.caption_candidates == [{"count_total": 12, "count_unit": "ロール", "content_amount": 50.0,
                                     "content_dimension": "length", "evidence": "スコッティ フラワーパック 12ロール 50m シングルと比較"}]


def test_u1_counted_sentence_with_the_same_total_gives_its_content():
    # 個数だけ high の題名で、説明欄の文が同じ総数＋内容量（`12本×500ml`）なら (ii) を通って内容量の候補（監査 A14）
    grp = [offer(f"w{i}", "水 12本 500ml", "", 1000 + i) for i in range(4)]
    t = offer("tgt", "水 12本", "内容量:12本×500ml", 900)
    compare(grp + [t], basis="ml")
    assert (t.quantity.content_amount, t.quantity.content_dimension, t.quantity.source) == (500.0, "volume", "title+caption")
    assert unconfirmed_reasons(t) == ["measure_from_caption"] and t.quantity.caption_candidates == []


def test_u1_not_for_price_varies_and_not_after_the_length_heading():
    t = target("ロールサイズ:108mm×100m", price_min=3000, price_max=5000)
    compare(group_of() + [t], basis="m")
    assert t.quantity.content_amount is None and t.quantity.caption_candidates
    t2 = target("●長さ：100mシングル●ロールサイズ:108mm×150m")        # 見出し 長さ が先に当たる
    compare(group_of() + [t2], basis="m")
    assert t2.quantity.content_amount == 100.0 and t2.quantity.u1_adopted == []


def test_u1_basis_count_stays_confirmed_and_compare_twice_is_stable():
    t = target("ロールサイズ:108mm×100m")
    grp = group_of()
    compare(grp + [t], basis="ロール")
    assert is_confirmed(t) and t.unit_price == pytest.approx(4000 / 48)
    compare(grp + [t], basis="m")                   # 同じ候補で 2 回目（基準が違う）。採用は 1 回で、読み直しても同じ
    assert t.quantity.content_amount == 100.0 and unconfirmed_reasons(t) == ["measure_from_caption"]
    compare([t], basis="m")                         # 比較グループが違う（題名由来 0 件）時は採らない（前の採用を引きずらない）
    assert t.quantity.content_amount is None


def test_u1_measure_from_caption_applies_to_every_filled_dimension():
    # 補った次元が 2 つ（長さと質量）の候補は、2 つ目の次元の basis で比べても未確定（AC24 (2)）
    grp = [offer(f"g{i}", "ふきん シングル 12個 75m 100g", "", 900 + i) for i in range(4)]
    t = offer("tgt", "ふきん シングル 12個", "ロールサイズ:108mm×100m ■内容量:150g", 1200)
    compare(grp + [t], basis="g")
    assert set(t.quantity.content_amounts) == {"length", "mass"} and t.unit_price_dimension == "mass"
    assert unconfirmed_reasons(t) == ["measure_from_caption"]


def test_search_results_never_adopt_u1_they_only_mark():
    q = read_offer_quantity(target("ロールサイズ:108mm×100m"))
    assert q.content_amount is None and q.caption_candidates[0]["content_amount"] == 100.0


# ---- U2b: 題名 low の読みの選択 ----

YU = ("日本製 国産 紙 クレシア スコッティ 2倍巻きフラワーパック シングル 芯あり 100m 1セット（48ロール：12ロール×4パック） "
      "環境に優しい紙パックリサイクルパルプを贅沢に使用した、上質な日本製フラワーパック 芯付きで100mの2倍巻きで、1セットには48ロール（12ロール")      # yumenokoya:39998092（2026-11-22 の録画）


def test_u2b_yumenokoya_like_picks_48_rolls_100m_as_provisional():
    o = offer("yu", YU, "●12ロール×4パック。●芯付きで100mの2倍巻き。")
    t = parse_quantity(YU)
    assert t.confidence == "low" and t.low_reason == "dropped_count"
    o.quantity = q = read_offer_quantity(o)
    assert q.confidence == "low" and q.low_reason == t.low_reason
    assert (q.count_total, q.count_unit, q.content_amount, q.source) == (48, "ロール", 100.0, "title+caption")
    assert unconfirmed_reasons(o) == ["quantity_low"]


def test_u2b_not_for_multiple_totals_or_price_varies():
    t = "トイレットペーパー 12ロール 18ロール"
    q = read_offer_quantity(offer("m", t, "12ロール入り"))
    assert q.count_total is None and q.caption_candidates                       # 説明欄の 12ロール は読みの1つと一致するが補わない
    assert read_offer_quantity(offer("p", "トイレットペーパー 48ロール シングル 75m 150m", "48ロール 75m", price_min=1, price_max=2)).content_amount is None


def test_u2b_ambiguous_match_is_not_adopted():
    q = read_offer_quantity(offer("a", "トイレットペーパー 12ロール 18ロール", "12ロール 18ロール"))
    assert q.count_total is None


def test_u2a_content_ambiguous_with_content_chosen_by_caption():
    o = offer("k", "トイレットペーパー 48ロール シングル 75m 150m", "シングル 48ロール 150m")
    q = read_offer_quantity(o)
    assert (q.count_total, q.content_amount, q.content_dimension, q.measure_total) == (48, 150.0, "length", 7200.0)
    assert q.confidence == "low" and q.source == "title+caption"


# ---- 比較: 仮の単価・確認済みの集合・自動 basis・読みの仮定 ----

def test_quantity_low_is_provisional_and_never_cheapest_or_confirmed():
    hi = offer("ok", "トイレットペーパー 48ロール シングル", "", 3000)
    lo = offer("low", "トイレットペーパー 48ロール シングル 75m 150m", "", 1500)
    c = compare([hi, lo], basis="ロール", desired_quantity=48)
    assert unconfirmed_reasons(lo) == ["quantity_low"] and lo.unit_price == pytest.approx(1500 / 48)
    assert c.cheapest_unit_price.mall_item_code == "ok" and c.cheapest_order.offer.mall_item_code == "ok"
    assert [t.plan.offer.mall_item_code for t in c.to_check] == ["low"]
    assert "題名に食い違う数がある" in c.to_check[0].conditions[0]["text"] and "48ロール" in c.to_check[0].conditions[0]["text"]
    d = service._comparison_to_dict(c)
    od = next(o for g in d["groups"] for o in g["offers"] if o["item_code"] == "low")
    assert od["unit_price"] is None and od["provisional_unit_price"] == pytest.approx(31.25)
    assert od["unit_price_unconfirmed_reasons"] == ["quantity_low"]
    assert od["quantity"]["confidence"] == "low" and od["quantity"]["title_confidence"] == "low"
    assert od["quantity"]["low_reason"] == "content_ambiguous"
    assert od["quantity"]["readings"]["contents"] == {"length": [75.0, 150.0]}


def test_quantity_low_with_unknown_basis_dimension_stays_unknown():
    lo = offer("low", "トイレットペーパー 48ロール シングル 75m 150m", "", 1500)
    c = compare([lo], basis="m")
    assert lo.unit_price is None and c.unknown_offers == [lo]


def test_confirmed_set_does_not_change_when_low_quantities_become_provisional():
    items = [offer(f"h{i}", "トイレットペーパー 12ロール 75m", "", 1000 + i) for i in range(5)]
    low = offer("low", "トイレットペーパー 48ロール シングル 75m 150m", "", 1500)
    compare(items, basis="個")
    before = {o.mall_item_code for o in items if is_confirmed(o)}
    compare(items + [low], basis="個")
    assert {o.mall_item_code for o in items + [low] if is_confirmed(o)} == before        # 仮の単価が付いた low は確認済みに入らない
    assert low.unit_price is not None and not is_confirmed(low)


def test_auto_basis_is_decided_by_title_quantities_only():
    # 題名由来は m が過半（3/5）。仮の数量（U2a の個数だけ・説明欄から補った個数）が加わっても基準は m のまま
    base = [offer(f"m{i}", "トイレットペーパー 12ロール 75m", "", 1000) for i in range(3)] + \
           [offer(f"c{i}", "トイレットペーパー 12ロール", "", 1000) for i in range(2)]
    extra = [offer(f"l{i}", "トイレットペーパー 48ロール シングル 75m 150m", "", 1000) for i in range(4)] + \
            [offer(f"cap{i}", "トイレットペーパー", "内容量:12ロール", 1000) for i in range(4)]
    assert compare(base).basis == "m"
    assert compare(base + extra).basis == "m"


def test_counter_basis_uses_a_low_reading_with_the_same_counter_as_is():
    ok = offer("ok", "トイレットペーパー 48ロール シングル", "", 3000)
    low = offer("low", "トイレットペーパー 12ロール 18ロール", "", 800)              # multiple_totals。仮の数量は付かない
    c = compare([ok, low], basis="ロール", desired_quantity=48)
    assert low.unit_price is None
    texts = [t.conditions[0]["text"] for t in c.to_check if t.plan.offer is low]
    assert texts and ("この商品が12ロールなら" in texts[0] or "この商品が18ロールなら" in texts[0])


# ---- 表示・指示 ----

def test_marks_and_provisional_display():
    o = offer("k", "トイレットペーパー 48ロール シングル 75m 150m", "")
    o.quantity = q = read_offer_quantity(o)
    d = service.offer_to_dict(o)
    assert d["quantity"]["caption_candidates"] == [] and d["quantity"]["readings"]["counts"] == [{"count": 48, "count_unit": "ロール"}]
    txt = quantity_marks_text(d["quantity"])
    assert "48ロール" in txt and "75m" in txt and "確定値ではない" in txt
    assert q.low_adopted


def test_order_guide_says_marks_are_candidates_and_description_stays_within_2000():
    assert "quantity.readings" in mcp_server._ORDER_GUIDE and "quantity_low" in mcp_server._ORDER_GUIDE
    assert len(mcp_server._ORDER_POINTER) < 2000
