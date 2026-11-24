# @owns WP17 ブラインド試験（Yahoo を混ぜた比較・モールの選択・実アダプタを通した一貫試験）
"""WP17 ブラインド試験の続き（比較 P1〜P5・malls C2/C4/C5/Y6・一貫試験）。根拠・方針は test_blind_wp17.py の冒頭と同じ。"""
from __future__ import annotations

import json

import pytest

from fakes import FakeAdapter, FakeOpener
from shopping import pricing, service
from shopping.adapters.base import AdapterError
from shopping.adapters.yahoo import YahooAdapter

from blind_wp17_support import (
    NOSLEEP,
    SECRET,
    YahooFake,
    _adapters,
    _baseline,
    _cmp,
    _codes,
    _hit,
    _http_err,
    _o,
    _offers_of,
    _plan,
    _rof,
    _tc,
    _walk,
    _yoffer,
)


# ==========================================================================
# 3. 比較（P1〜P5）。service.compare_offers に adapters={"rakuten": FakeAdapter, "yahoo": 偽 Yahoo}
# ==========================================================================
# データセット A（desired_quantity=60・basis=個。全候補が数え語「枚」・送料込み。式は手計算）
#   楽天 r1 : 貼るカイロ 60枚  1800円 → 1個(枚)あたり 1800÷60 = 30.0・確認済み
#   楽天 r2 : 貼るカイロ 120枚 3000円 → 3000÷120 = 25.0・確認済み（注文: n=ceil(60÷120)=1・注文額 3000）
#   Yahoo y1: 貼るカイロ 60枚  900円・points 60 → 900÷60 = 15.0（仮）。注文 n=1・注文額 900（ポイントを引いた 840 ではない）
#   Yahoo y3: 貼るカイロ 60枚 2500円 → 2500÷60 = 41.67（仮）。注文額 2500 > 確認済みの最安 1800 → to_check には出ない
#   → 単価の最安（確認済み）= r2（25.0）、注文の最安（確認済み・注文額最小）= r1（1800）。外れ値: 単価 [15,25,30,41.67]・中央値 27.5 → 15 > 2.75 で無し
R1 = ("r1", "貼るカイロ 60枚 R店", 1800)
R2 = ("r2", "貼るカイロ 120枚 R2店", 3000)


def _data_a(**ykw):
    rak = [_rof(*R1), _rof(*R2)]
    yah = [_yoffer("y1", "貼るカイロ 60枚 Y店", 900, points_amount=60, **ykw),
           _yoffer("y3", "貼るカイロ 60枚 Y3店", 2500)]
    return rak, yah


@pytest.fixture(scope="module")
def mix_a():
    rak, yah = _data_a()
    r, rak_fake, yah_fake = _cmp(rak, yah)
    assert r["ok"], r
    return r["comparison"], r


def test_p1_yahoo_cheaper_candidate_is_not_in_confirmed_slots(mix_a):
    # P1: Yahoo の y1（15.0）は楽天の r2（25.0）・r1（30.0）より安いが、単価の最安・必要数量を満たす最安・注文の最安に入らない
    c, _ = mix_a
    assert c["cheapest_unit_price"]["item_code"] == "r2" and c["cheapest_unit_price"]["mall"] == "rakuten"
    assert c["cheapest_order"]["item_code"] == "r1"
    assert c["cheapest_for_quantity"]["item_code"] == "r1" and c["cheapest_for_quantity"]["mall"] == "rakuten"
    g = c["groups"][0]
    assert g["cheapest_unit_price"]["item_code"] == "r2"
    assert g["cheapest_order"]["item_code"] == "r1"


def test_p1_yahoo_offer_dict_is_provisional(mix_a):
    # P1・Q21: Yahoo の候補は unit_price=null・provisional_unit_price=15.0・status unconfirmed・理由 [price_options_unchecked]
    c, _ = mix_a
    y = _o(c, "y1")
    assert y["mall"] == "yahoo"
    assert y["unit_price"] is None
    assert y["provisional_unit_price"] == pytest.approx(15.0, abs=0.01)
    assert y["unit_price_status"] == "unconfirmed"
    assert list(y["unit_price_unconfirmed_reasons"]) == ["price_options_unchecked"]
    assert y["points_amount"] == 60
    assert y["total_price"] == 900                         # 送料込み（code=2）は price。ポイント 60 を引かない


def test_p1_rakuten_candidates_stay_confirmed(mix_a):
    # 楽天の確認済み候補は素の unit_price のまま（r1 = 30.0・r2 = 25.0）
    c, _ = mix_a
    r1, r2 = _o(c, "r1"), _o(c, "r2")
    assert r1["unit_price"] == pytest.approx(30.0, abs=0.01) and r1["unit_price_status"] == "confirmed"
    assert r2["unit_price"] == pytest.approx(25.0, abs=0.01) and r2["unit_price_status"] == "confirmed"
    assert list(r1["unit_price_unconfirmed_reasons"]) == [] and list(r2["unit_price_unconfirmed_reasons"]) == []


def test_p1_yahoo_plan_is_unconfirmed_and_has_no_payment_total(mix_a):
    # P1・Q23・P4: y1 の注文案は確認済みでない・order_total=900（n=1。ポイント 60 を引かない）・
    # payment_total=null・kind=unconfirmed_total（送料込みで単価未確定）・注文の単価は仮 15.0
    c, _ = mix_a
    p = _plan(c, "y1")
    assert p["confirmed"] is False
    assert list(p["unconfirmed_reasons"]) == ["price_options_unchecked"]
    assert p["n"] == 1 and p["order_total"] == 900
    assert p["payment_total"] is None and p["order_total_kind"] == "unconfirmed_total"
    assert p["order_unit_price"] is None
    assert p["provisional_order_unit_price"] == pytest.approx(15.0, abs=0.01)
    assert p["unit_price_status"] == "unconfirmed"
    assert list(p["unit_price_unconfirmed_reasons"]) == ["price_options_unchecked"]


def test_p1_p3_yahoo_cheaper_candidate_is_in_to_check(mix_a):
    # P1: Yahoo の y1（注文額 900 < 確認済みの最安 1800）は to_check に出る。y3（2500 > 1800）は to_check に出ない（order_plans には残る）。
    # P3: 注文案はモールを混ぜた全体で作る（r1・r2・y1・y3 が同じ order_plans に並ぶ）
    c, _ = mix_a
    assert _tc(c, "y1") is not None
    assert _tc(c, "y3") is None
    assert _codes(c["order_plans"]) == {"r1", "r2", "y1", "y3"}
    assert _plan(c, "y3")["confirmed"] is False and _plan(c, "y3")["order_total"] == 2500
    assert _codes(c["groups"][0]["to_check"]) == _codes(c["to_check"])


def test_p2_to_check_text_asks_to_confirm_price_on_yahoo_page(mix_a):
    # P2: to_check の条件文「Yahoo!ショッピングの商品ページで、選んだ色・サイズ・数量の価格が〈価格〉円のままか確認」（価格＝900）
    c, _ = mix_a
    conds = _tc(c, "y1")["conditions"]
    assert len(conds) == 1
    text = conds[0]["text"]
    assert "Yahoo!ショッピングの商品ページ" in text
    assert "選んだ色・サイズ・数量の価格が" in text
    assert "900円のまま" in text
    assert "確認" in text


def test_p4_points_do_not_reduce_total_or_unit_price():
    # P4: ポイントは総額から引かない。points_amount=500（価格 900 に対し）でも total_price=900・注文額 900・仮の単価 15.0
    rak, _ = _data_a()
    yah = [_yoffer("y1", "貼るカイロ 60枚 Y店", 900, points_amount=500)]
    r, _, _ = _cmp(rak, yah)
    c = r["comparison"]
    y = _o(c, "y1")
    assert y["points_amount"] == 500
    assert y["total_price"] == 900
    assert y["provisional_unit_price"] == pytest.approx(15.0, abs=0.01)     # 400÷60 = 6.67 ではない
    assert _plan(c, "y1")["order_total"] == 900
    assert c["cheapest_unit_price"]["item_code"] == "r2" and c["cheapest_order"]["item_code"] == "r1"


def test_p3_rakuten_confirmed_results_unchanged_by_yahoo(mix_a):
    # 楽天の確認済み候補の結果は Yahoo を混ぜても変わらない（楽天だけ＝adapter= の経路と比べる）。
    # 比べる対象: 3 つの最安の枠・楽天 2 件の候補 dict・楽天 2 件の注文案 dict
    c, _ = mix_a
    base = _baseline([_rof(*R1), _rof(*R2)])["comparison"]
    for slot in ("cheapest_unit_price", "cheapest_order", "cheapest_for_quantity"):
        assert c[slot] == base[slot], slot
    for code in ("r1", "r2"):
        assert _o(c, code) == _o(base, code)
        assert _plan(c, code) == _plan(base, code)


def test_p5_unknown_shipping_candidate_has_no_total_price():
    # P5・Q11: 送料 unknown（Yahoo code=1）の候補は total_price を出さない。送料不明の候補があるので cheapest_total も断定しない（None）・
    # caveats に「送料」。注文案は payment_total=null・kind=item_subtotal・unconfirmed_reasons に shipping_unknown。
    # 単価の未確定理由には送料を含めない。注文額 800 < 1800 なので to_check に出る
    rak = [_rof(*R1), _rof(*R2)]
    yah = [_yoffer("y2", "貼るカイロ 60枚 Y2店", 800, ship="unknown")]
    r, _, _ = _cmp(rak, yah)
    c = r["comparison"]
    y = _o(c, "y2")
    assert y["shipping_status"] == "unknown" and y["total_price"] is None
    assert y["provisional_unit_price"] == pytest.approx(800 / 60, abs=0.01)      # 13.33
    assert list(y["unit_price_unconfirmed_reasons"]) == ["price_options_unchecked"]
    assert c["cheapest_total"] is None
    assert any("送料" in x for x in c["caveats"])
    p = _plan(c, "y2")
    assert p["payment_total"] is None and p["order_total_kind"] == "item_subtotal"
    assert {"price_options_unchecked", "shipping_unknown"} <= set(p["unconfirmed_reasons"])
    assert list(p["unit_price_unconfirmed_reasons"]) == ["price_options_unchecked"]
    assert c["cheapest_order"]["item_code"] == "r1"
    assert _tc(c, "y2") is not None


@pytest.mark.parametrize("word", ["price_options_unchecked", "price_tax_unknown", "condition_not_new"])
def test_p1_each_mall_unconfirmed_word_makes_unit_price_provisional(word):
    # P1: 理由の語 3 つ（price_options_unchecked・price_tax_unknown・condition_not_new）のどれか 1 つだけでも、
    # 単価の未確定理由に含まれ（unit_price=null・provisional・その語）、最安・注文の最安に入らず to_check に出る
    rak = [_rof(*R1), _rof(*R2)]
    yah = [_yoffer("yw", "貼るカイロ 60枚 W店", 900, unconf=(word,))]
    r, _, _ = _cmp(rak, yah)
    c = r["comparison"]
    y = _o(c, "yw")
    assert y["unit_price"] is None and y["unit_price_status"] == "unconfirmed"
    assert y["provisional_unit_price"] == pytest.approx(15.0, abs=0.01)
    assert list(y["unit_price_unconfirmed_reasons"]) == [word]
    assert c["cheapest_unit_price"]["item_code"] == "r2"
    assert c["cheapest_order"]["item_code"] == "r1"
    p = _plan(c, "yw")
    assert p["confirmed"] is False and list(p["unconfirmed_reasons"]) == [word]
    assert p["payment_total"] is None and p["order_unit_price"] is None
    assert _tc(c, "yw") is not None


def test_p1_three_words_together_all_listed():
    rak = [_rof(*R1), _rof(*R2)]
    words = ["price_options_unchecked", "price_tax_unknown", "condition_not_new"]
    yah = [_yoffer("yw", "貼るカイロ 60枚 W店", 900, unconf=words)]
    r, _, _ = _cmp(rak, yah)
    y = _o(r["comparison"], "yw")
    assert sorted(y["unit_price_unconfirmed_reasons"]) == sorted(words)
    assert y["unit_price"] is None


def test_p1_pricing_functions_include_mall_unconfirmed_words():
    # P1: pricing.unconfirmed_reasons(offer) が offer.mall_unconfirmed の語を含み、unit_price_reasons も同じ語を単価の未確定に含める
    o = _yoffer("yz", "貼るカイロ 60枚 Z店", 900, unconf=("price_tax_unknown", "condition_not_new"))
    reasons = pricing.unconfirmed_reasons(o)
    assert {"price_tax_unknown", "condition_not_new"} <= set(reasons)
    assert {"price_tax_unknown", "condition_not_new"} <= set(pricing.unit_price_reasons(reasons))
    assert pricing.is_confirmed(o) is False


def test_p3_outlier_is_judged_over_mixed_candidates():
    # P3: 外れ値の網（N=4・K=10）はモールを混ぜた候補全体で計算する。
    # 楽天 3 件 6000/6120/6240 円（60枚）→ 単価 100.0・102.0・104.0。楽天だけなら 3 件で N=4 に満たず外れ値なし。
    # Yahoo 300円（60枚）→ 5.0 を混ぜると 4 件になり、5.0 < 中央値(≈101)/10 → Yahoo の候補に外れ値の印
    rak = [_rof("ra", "貼るカイロ 60枚 A店", 6000), _rof("rb", "貼るカイロ 60枚 B店", 6120), _rof("rc", "貼るカイロ 60枚 C店", 6240)]
    base = _baseline(rak)["comparison"]
    assert all(o["unit_price_outlier"] is False for o in _offers_of(base))
    yah = [_yoffer("yq", "貼るカイロ 60枚 Y店", 300)]
    r, _, _ = _cmp(rak, yah)
    c = r["comparison"]
    y = _o(c, "yq")
    assert y["unit_price_outlier"] is True
    assert sorted(y["unit_price_unconfirmed_reasons"]) == ["price_options_unchecked", "unit_price_outlier"]
    assert y["unit_price"] is None and y["provisional_unit_price"] == pytest.approx(5.0, abs=0.01)
    assert all(_o(c, k)["unit_price_outlier"] is False for k in ("ra", "rb", "rc"))
    assert c["cheapest_unit_price"]["item_code"] == "ra"


def test_p3_same_jan_other_mall_or_other_code_is_a_separate_candidate():
    # P3: 同じ JAN でも、モール・商品コードが違えば別候補。60枚と 240枚が 1 つにならない（それぞれ自分の数量で単価）。
    # 楽天 rj60: 60枚 1800円 → 30.0（確認済み）／Yahoo yj240: 240枚入り 4800円 → 20.0（仮）／Yahoo yj60: 60枚 1680円 → 28.0（仮）
    jan = "4905009678921"
    rak = [_rof("rj60", "貼るカイロ 60枚 J店", 1800, jan=jan)]
    yah = [_yoffer("yj240", "貼るカイロ 240枚入り Y店", 4800, jan=jan),
           _yoffer("yj60", "貼るカイロ 60枚 Y店", 1680, jan=jan)]
    r, _, _ = _cmp(rak, yah)
    c = r["comparison"]
    assert _codes(_offers_of(c)) == {"rj60", "yj240", "yj60"}
    assert _o(c, "rj60")["quantity"]["count_total"] == 60
    assert _o(c, "yj240")["quantity"]["count_total"] == 240
    assert _o(c, "yj60")["quantity"]["count_total"] == 60
    assert _o(c, "rj60")["unit_price"] == pytest.approx(30.0, abs=0.01)
    assert _o(c, "yj240")["provisional_unit_price"] == pytest.approx(20.0, abs=0.01)
    assert _o(c, "yj60")["provisional_unit_price"] == pytest.approx(28.0, abs=0.01)
    assert c["cheapest_unit_price"]["item_code"] == "rj60"          # 確認済みは楽天の 1 件だけ


def test_p3_same_item_code_in_two_malls_is_kept_twice():
    # P3: 重複排除は (mall, mall_item_code)。モールが違えば同じ商品コードでも別候補（2 件とも残る）
    rak = [_rof("dup", "貼るカイロ 60枚 D店", 1800)]
    yah = [_yoffer("dup", "貼るカイロ 60枚 D店", 1800)]
    r, _, _ = _cmp(rak, yah)
    ds = [o for o in _offers_of(r["comparison"]) if o["item_code"] == "dup"]
    assert sorted(o["mall"] for o in ds) == ["rakuten", "yahoo"]


def test_p1_yahoo_only_never_has_a_confirmed_best():
    # P1: Yahoo だけを指定（malls=["yahoo"]）しても確認済みにならない: 単価の最安・必要数量を満たす最安・注文の最安は None。
    # 確認済みの最安が無いので、Yahoo の注文案は全部 to_check に出る（Q16「確認済みが 1 件も無い時は全部出す」）。楽天は呼ばない
    rak, yah_offers = _data_a()
    r, rak_fake, yah_fake = _cmp(rak, yah_offers, malls=["yahoo"])
    assert r["ok"], r
    c = r["comparison"]
    assert rak_fake.calls == [] and yah_fake.calls
    assert c["cheapest_unit_price"] is None
    assert c["cheapest_order"] is None
    assert c["cheapest_for_quantity"] is None
    assert {"y1", "y3"} <= _codes(c["to_check"])
    assert _codes(_offers_of(c)) == {"y1", "y3"}
    assert all(o["unit_price"] is None for o in _offers_of(c))


# ==========================================================================
# 4. malls（C2・C4・C5・Y6 の打ち切り）
# ==========================================================================

def _regulars(tmp_path):
    p = tmp_path / "regulars.json"
    p.write_text(json.dumps({"regulars": [{"id": "r", "name": "n", "include_terms": [], "exclude_terms": [],
                                           "basis": "個", "desired_quantity": 60, "keywords": ["aa"],
                                           "known_urls": []}]}), encoding="utf-8")
    return p


BAD_MALLS = [["amazon"], ["rakuten", "amazon"], ["yahoo", "amazon"], [""]]


@pytest.mark.parametrize("malls", BAD_MALLS, ids=["amazon", "rakuten+amazon", "yahoo+amazon", "empty_name"])
def test_c2_unknown_mall_is_invalid_request_with_zero_calls_compare(malls):
    # C2: 未知のモールを指定したら invalid_request・API 呼び出し 0 回（両モールとも）
    rak, yah = _data_a()
    r, rak_fake, yah_fake = _cmp(rak, yah, malls=malls)
    assert r["ok"] is False and r["error"]["kind"] == "invalid_request"
    assert rak_fake.calls == [] and yah_fake.calls == []


@pytest.mark.parametrize("malls", BAD_MALLS, ids=["amazon", "rakuten+amazon", "yahoo+amazon", "empty_name"])
def test_c2_unknown_mall_is_invalid_request_with_zero_calls_search(malls):
    rak, yah = _data_a()
    rf, yf = _adapters(rak, yah)
    r = service.search_products(["aa"], adapters={"rakuten": rf, "yahoo": yf}, malls=malls, sleep=NOSLEEP)
    assert r["ok"] is False and r["error"]["kind"] == "invalid_request"
    assert rf.calls == [] and yf.calls == []


@pytest.mark.parametrize("malls", BAD_MALLS, ids=["amazon", "rakuten+amazon", "yahoo+amazon", "empty_name"])
def test_c2_unknown_mall_is_invalid_request_with_zero_calls_regular(malls, tmp_path):
    rak, yah = _data_a()
    rf, yf = _adapters(rak, yah)
    r = service.find_regular_item("r", regulars_path=_regulars(tmp_path), adapters={"rakuten": rf, "yahoo": yf},
                                  malls=malls, sleep=NOSLEEP)
    assert r["ok"] is False and r["error"]["kind"] == "invalid_request"
    assert rf.calls == [] and yf.calls == []


def test_c2_default_is_all_enabled_malls():
    # C2: malls 省略＝有効な全モール。両方の Adapter が呼ばれ、候補に両モールが出る
    rak, yah = _data_a()
    r, rak_fake, yah_fake = _cmp(rak, yah)
    assert rak_fake.calls and yah_fake.calls
    assert {o["mall"] for o in _offers_of(r["comparison"])} == {"rakuten", "yahoo"}


def test_c2_malls_rakuten_does_not_call_yahoo():
    # C2: malls=["rakuten"] の時、Yahoo アダプタは呼ばれない。候補は楽天だけ。
    # 出力は楽天だけの今の経路（adapter=）と値が同じ（候補・注文案・最安の枠・caveats・source）
    rak, yah = _data_a()
    r, rak_fake, yah_fake = _cmp(rak, yah, malls=["rakuten"])
    assert r["ok"], r
    assert yah_fake.calls == [] and rak_fake.calls
    c = r["comparison"]
    assert {o["mall"] for o in _offers_of(c)} == {"rakuten"}
    base = _baseline([_rof(*R1), _rof(*R2)])
    bc = base["comparison"]

    def proj(cc):
        return ([(o["item_code"], o["price"], o["unit_price"], o["provisional_unit_price"], o["unit_price_status"],
                  tuple(o["unit_price_unconfirmed_reasons"]), o["total_price"]) for o in _offers_of(cc)],
                [(p["item_code"], p["order_total"], p["confirmed"], tuple(p["unconfirmed_reasons"])) for p in cc["order_plans"]],
                [(cc[k] or {}).get("item_code") for k in ("cheapest_price", "cheapest_unit_price", "cheapest_total",
                                                          "cheapest_for_quantity")],
                (cc["cheapest_order"] or {}).get("item_code"), list(cc["caveats"]), cc["basis"])
    assert proj(c) == proj(bc)
    assert r["source"] == base["source"]
    assert _codes(c["to_check"]) == _codes(bc["to_check"]) == set()


def test_c2_search_products_malls_rakuten_and_default():
    rak, yah = _data_a()
    rf, yf = _adapters(rak, yah)
    r = service.search_products(["aa"], adapters={"rakuten": rf, "yahoo": yf}, malls=["rakuten"], sleep=NOSLEEP)
    assert r["ok"] and yf.calls == [] and {o["mall"] for o in r["offers"]} == {"rakuten"}
    rf, yf = _adapters(rak, yah)
    r = service.search_products(["aa"], adapters={"rakuten": rf, "yahoo": yf}, sleep=NOSLEEP)
    assert r["ok"] and r["returned"] == 4
    assert {o["mall"] for o in r["offers"]} == {"rakuten", "yahoo"}
    y = next(o for o in r["offers"] if o["item_code"] == "y1")
    assert y["points_amount"] == 60 and y["unit_price"] is None


def test_c4_stats_have_mall_in_per_keyword_and_per_mall():
    # C4: stats.per_keyword[] の各行に mall。stats.per_mall に両モール（行の項目名は mall 以外は契約が決めていない）
    rak, yah = _data_a()
    r, _, _ = _cmp(rak, yah)
    st = r["stats"]
    assert st["per_keyword"] and all("mall" in row for row in st["per_keyword"])
    assert {row["mall"] for row in st["per_keyword"]} == {"rakuten", "yahoo"}
    assert "per_mall" in st
    assert {row["mall"] for row in st["per_mall"]} == {"rakuten", "yahoo"}


YAHOO_FAIL_KINDS = ["rate_limited", "server_error", "forbidden", "bad_request", "timeout"]


@pytest.mark.parametrize("kind", YAHOO_FAIL_KINDS)
def test_c5_yahoo_failure_keeps_rakuten_comparison(kind):
    # C5: 片方のモール（Yahoo）が失敗しても、もう片方（楽天）の結果で比較が返る（楽天だけの比較と同じ最安・同じ候補）
    rak, _ = _data_a()
    rf = FakeAdapter({("aa", 1): (rak, len(rak))})
    yf = YahooFake({("aa", 1): AdapterError(kind)})
    r = service.compare_offers(["aa"], adapters={"rakuten": rf, "yahoo": yf}, desired_quantity=60, basis="個",
                               sleep=NOSLEEP)
    assert r["ok"] is True, r
    c = r["comparison"]
    base = _baseline([_rof(*R1), _rof(*R2)])["comparison"]
    assert {o["mall"] for o in _offers_of(c)} == {"rakuten"}
    assert c["cheapest_unit_price"] == base["cheapest_unit_price"] and c["cheapest_order"] == base["cheapest_order"]
    assert c["cheapest_unit_price"]["item_code"] == "r2" and c["cheapest_order"]["item_code"] == "r1"


def test_c5_note_names_the_failed_mall_and_kind():
    # C5: notes に「Yahoo!ショッピングは〈種別〉で取得できなかった（楽天だけで比較）」
    rak, _ = _data_a()
    rf = FakeAdapter({("aa", 1): (rak, len(rak))})
    yf = YahooFake({("aa", 1): AdapterError("rate_limited")})
    r = service.compare_offers(["aa"], adapters={"rakuten": rf, "yahoo": yf}, desired_quantity=60, basis="個",
                               sleep=NOSLEEP)
    assert r["ok"] is True
    hits = [n for n in r["notes"] if "Yahoo!ショッピング" in n and "取得できなかった" in n]
    assert hits, r["notes"]
    assert any("rate_limited" in n for n in hits)
    assert any("楽天だけで比較" in n for n in hits)


def test_c4_per_mall_records_the_failure():
    # C4: stats.per_mall の yahoo の行にそのモールのエラー種別が残る（楽天の行は残る）
    rak, _ = _data_a()
    rf = FakeAdapter({("aa", 1): (rak, len(rak))})
    yf = YahooFake({("aa", 1): AdapterError("rate_limited")})
    r = service.compare_offers(["aa"], adapters={"rakuten": rf, "yahoo": yf}, desired_quantity=60, basis="個",
                               sleep=NOSLEEP)
    rows = {row["mall"]: row for row in r["stats"]["per_mall"]}
    assert set(rows) == {"rakuten", "yahoo"}
    assert "rate_limited" in json.dumps(rows["yahoo"], ensure_ascii=False)
    assert "rate_limited" not in json.dumps(rows["rakuten"], ensure_ascii=False)


def test_c5_rakuten_failure_keeps_yahoo_candidates_but_never_confirms_them():
    # C5: 楽天が失敗して Yahoo だけが残っても比較は返る。Yahoo の候補は確認済みの枠に入らない（P1）。notes に楽天の失敗の種別
    _, yah = _data_a()
    rf = FakeAdapter({("aa", 1): AdapterError("http_403")})
    yf = YahooFake({("aa", 1): (yah, len(yah))})
    r = service.compare_offers(["aa"], adapters={"rakuten": rf, "yahoo": yf}, desired_quantity=60, basis="個",
                               sleep=NOSLEEP)
    assert r["ok"] is True, r
    c = r["comparison"]
    assert _codes(_offers_of(c)) == {"y1", "y3"}
    assert c["cheapest_unit_price"] is None and c["cheapest_order"] is None and c["cheapest_for_quantity"] is None
    assert any("http_403" in n for n in r["notes"])


def test_c5_all_malls_failed_is_the_error_response():
    # C5: 全モールが失敗した時だけ今のエラー応答（ok=false・error.kind・message）。比較は返さない。
    # kind はどちらかのモールの失敗種別（どちらか／どう選ぶかは契約が決めていない＝穴）
    rf = FakeAdapter({("aa", 1): AdapterError("http_429")})
    yf = YahooFake({("aa", 1): AdapterError("rate_limited")})
    r = service.compare_offers(["aa"], adapters={"rakuten": rf, "yahoo": yf}, desired_quantity=60, basis="個",
                               sleep=NOSLEEP)
    assert r["ok"] is False
    assert r["error"]["kind"] in {"http_429", "rate_limited"}
    assert isinstance(r["error"]["message"], str) and r["error"]["message"]
    assert "comparison" not in r


@pytest.mark.parametrize("kind,calls", [("rate_limited", 1), ("server_error", 1), ("bad_request", 2)])
def test_y6_rate_limited_and_server_error_stop_the_mall(kind, calls):
    # Y6: rate_limited と server_error はそのモールの残りの検索を打ち切る（再試行しない。2 語目の "bb" を呼ばない＝呼び出し 1 回）。
    # それ以外（bad_request）はその語だけ失敗で次の語へ進む（2 回）
    rak, _ = _data_a()
    rf = FakeAdapter({("aa", 1): (rak, len(rak)), ("bb", 1): (rak, len(rak))})
    yf = YahooFake({("aa", 1): AdapterError(kind), ("bb", 1): ([], 0)})
    r = service.compare_offers(["aa", "bb"], adapters={"rakuten": rf, "yahoo": yf}, desired_quantity=60, basis="個",
                               sleep=NOSLEEP, pages=2)
    assert r["ok"] is True, r
    assert len(yf.calls) == calls, yf.calls


def test_y2_page_beyond_yahoo_ceiling_is_not_called_and_not_invalid():
    # Y2: 1000 件の天井（max_page=20）を越えるページは呼ばない。全体を invalid_request にしない。notes に「1000 件目まで」。
    # （page 20 を呼ぶかは契約の式〔start+results ≤ 1000〕と max_page=20 が食い違う＝穴なので、20 以下であることだけを見る）
    rak, _ = _data_a()
    pages = {("aa", p): ([_yoffer(f"yp{p}", f"貼るカイロ 60枚 P{p}店", 900 + p)], 5000) for p in range(1, 26)}
    rf = FakeAdapter({("aa", 1): (rak, len(rak))})
    yf = YahooFake(pages)
    r = service.compare_offers(["aa"], adapters={"rakuten": rf, "yahoo": yf}, desired_quantity=60, basis="個",
                               sleep=NOSLEEP, pages=25)
    assert r["ok"] is True, r
    assert yf.calls and max(kw["page"] for _, kw in yf.calls) <= 20
    assert any("1000" in n for n in r["notes"]), r["notes"]


# ==========================================================================
# 5. 一貫試験: 実 YahooAdapter（偽 opener）＋楽天の偽 Adapter を service に通す（設計規律8）
# ==========================================================================

def _live_like_response():
    """実応答の形の hit 4 件（名前だけ数量が確実に読める合成名。他の項目は実 hit の形のまま）。
    ys_a1: 送料込み(2)・points 60・900円／ys_a2: 設定なし(1)・800円／ys_a3: 条件付き(3)・850円／ys_a4: 送料込み・2500円"""
    spec = [("ys_a1", "貼るカイロ 60枚 Y店A", 900, 2, 60), ("ys_a2", "貼るカイロ 60枚 Y店B", 800, 1, 40),
            ("ys_a3", "貼るカイロ 60枚 Y店C", 850, 3, 30), ("ys_a4", "貼るカイロ 60枚 Y店D", 2500, 2, 100)]
    hits = []
    for i, (code, name, price, ship, pt) in enumerate(spec):
        hits.append(_hit(0, code=code, name=name, price=price, premiumPrice=price - 50, shipping__code=ship,
                         point__lyLimitedBonusAmount=pt, janCode="",
                         url=f"https://store.shopping.yahoo.co.jp/ysx/{code}.html", index=i + 1))
    return {"totalResultsAvailable": len(hits), "totalResultsReturned": len(hits), "firstResultsPosition": 1,
            "request": {"query": "aa"}, "hits": hits}


def _run_e2e(yahoo_response):
    rak = FakeAdapter({("aa", 1): ([_rof(*R1), _rof(*R2)], 2)})
    op = FakeOpener(yahoo_response)
    ya = YahooAdapter(SECRET, opener=op)
    r = service.compare_offers(["aa"], adapters={"rakuten": rak, "yahoo": ya}, desired_quantity=60, basis="個",
                               sleep=NOSLEEP, pages=1)
    return r, op


def test_e2e_real_adapter_through_service_keeps_yahoo_out_of_confirmed_slots():
    r, op = _run_e2e(_live_like_response())
    assert r["ok"], r
    assert any(SECRET in req.full_url for req in op.requests)          # 前提: appid は URL に載って送られた（以下の「出ない」が空振りでない）
    c = r["comparison"]
    # 楽天の確認済みの結果は Yahoo を混ぜても変わらない（r2=25.0・注文は r1=1800）
    assert c["cheapest_unit_price"]["item_code"] == "r2" and c["cheapest_order"]["item_code"] == "r1"
    assert c["cheapest_for_quantity"]["item_code"] == "r1"
    ys = {code: _o(c, code) for code in ("ys_a1", "ys_a2", "ys_a3", "ys_a4")}
    for code, y in ys.items():
        assert y["mall"] == "yahoo"
        assert y["unit_price"] is None and y["unit_price_status"] == "unconfirmed", code
        assert "price_options_unchecked" in y["unit_price_unconfirmed_reasons"], code
    # 単価（仮）: 900÷60=15.0・800÷60=13.33・850÷60=14.17・2500÷60=41.67
    assert ys["ys_a1"]["provisional_unit_price"] == pytest.approx(15.0, abs=0.01)
    assert ys["ys_a2"]["provisional_unit_price"] == pytest.approx(13.33, abs=0.01)
    # 送料: code=2 だけ included（total_price=price。ポイントは引かない）。1・3 は unknown で total_price なし
    assert (ys["ys_a1"]["shipping_status"], ys["ys_a1"]["total_price"]) == ("included", 900)
    assert (ys["ys_a4"]["shipping_status"], ys["ys_a4"]["total_price"]) == ("included", 2500)
    for code in ("ys_a2", "ys_a3"):
        assert ys[code]["shipping_status"] == "unknown" and ys[code]["total_price"] is None, code
    assert ys["ys_a3"]["shipping_condition"] == "conditional_free"
    assert ys["ys_a1"]["points_amount"] == 60 and ys["ys_a2"]["points_amount"] == 40
    assert c["cheapest_total"] is None                                      # 送料不明の候補があるので支払総額の最安は断定しない
    # 注文案: Yahoo は全て確認済みでなく payment_total なし。ys_a1 の注文額は 900（ポイント 60 を引かない）
    for code in ys:
        p = _plan(c, code)
        assert p["confirmed"] is False and p["payment_total"] is None, code
        assert p["order_unit_price"] is None, code
    assert _plan(c, "ys_a1")["order_total"] == 900 and _plan(c, "ys_a1")["order_total_kind"] == "unconfirmed_total"
    assert _plan(c, "ys_a2")["order_total_kind"] == "item_subtotal"
    assert _tc(c, "ys_a1") is not None and _tc(c, "ys_a4") is None
    # 全入口の走査（AC17 型）: 未確定理由のある候補・案に素の単価が出ていない
    for d in _walk(r):
        if d.get("unit_price_unconfirmed_reasons"):
            assert d.get("unit_price") is None and d.get("order_unit_price") is None, d.get("item_code")
        if str(d.get("item_code", "")).startswith("ys_") and "payment_total" in d:
            assert d["payment_total"] is None
    # 秘密: appid の値・URL は出力 JSON のどこにも出ない
    dumped = json.dumps(r, ensure_ascii=False)
    assert SECRET not in dumped and "yahooapis" not in dumped and "appid" not in dumped.lower()


@pytest.mark.parametrize("code", [403, 429, 503])
def test_e2e_yahoo_http_error_does_not_leak_and_keeps_rakuten(code):
    # Y6・C5: 実アダプタの HTTP エラーでも、appid・URL・本文は出力 JSON に出ず、楽天の比較は返る。notes に Yahoo の失敗
    rak = FakeAdapter({("aa", 1): ([_rof(*R1), _rof(*R2)], 2)})
    ya = YahooAdapter(SECRET, opener=FakeOpener(_http_err(code)))
    r = service.compare_offers(["aa"], adapters={"rakuten": rak, "yahoo": ya}, desired_quantity=60, basis="個",
                               sleep=NOSLEEP, pages=1)
    assert r["ok"] is True, r
    assert r["comparison"]["cheapest_order"]["item_code"] == "r1"
    assert any("Yahoo!ショッピング" in n for n in r["notes"]), r["notes"]
    dumped = json.dumps(r, ensure_ascii=False)
    assert SECRET not in dumped and "yahooapis" not in dumped and "appid" not in dumped.lower()
    assert "<html>" not in dumped                                      # 応答本文（HTML）も出さない


def test_e2e_all_failed_response_does_not_leak():
    rak = FakeAdapter({("aa", 1): AdapterError("http_429")})
    ya = YahooAdapter(SECRET, opener=FakeOpener(_http_err(429)))
    r = service.compare_offers(["aa"], adapters={"rakuten": rak, "yahoo": ya}, sleep=NOSLEEP, pages=1)
    assert r["ok"] is False
    dumped = json.dumps(r, ensure_ascii=False)
    assert SECRET not in dumped and "yahooapis" not in dumped and "appid" not in dumped.lower()

