"""WP17 U3: 楽天と Yahoo を混ぜた比較（P1〜P5）。Yahoo の候補は確認済みにならず、provisional と to_check に出る。"""
import pytest

from fakes import FakeAdapter, FakeYahoo, make_offer, yoffer
from shopping import pricing, service
from shopping.models import Offer
from shopping.orchestrator import Limits
from shopping.pricing import compare, total_price, unconfirmed_reasons, unit_price_reasons

KW = "貼るカイロ"


def run(rak, yah, **kw):
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("limits", Limits(min_interval_sec=0))
    adapters = {"rakuten": FakeAdapter({(KW, 1): (rak, len(rak))}), "yahoo": FakeYahoo({(KW, 1): (yah, len(yah))})}
    return service.compare_offers([KW], adapters=adapters, **kw)


def rk(code, name, price, ship="included", **kw):
    return make_offer(code, name, price, shipping_status=ship, **kw)


def test_unconfirmed_reasons_include_mall_words_and_unit_price_reasons_too():
    o = yoffer("y1", "貼るカイロ 60枚", 1000, shipping_status="included")
    o.quantity = service.read_offer_quantity(o)
    assert "price_options_unchecked" in unconfirmed_reasons(o)
    assert unit_price_reasons(unconfirmed_reasons(o)) == ["price_options_unchecked"]
    assert unit_price_reasons(unconfirmed_reasons(o, shipping=True)) == ["price_options_unchecked"]
    o2 = yoffer("y2", "貼るカイロ 60枚", 1000, shipping_status="unknown",
                mall_unconfirmed=["price_options_unchecked", "price_tax_unknown", "condition_not_new"])
    o2.quantity = o.quantity
    assert unconfirmed_reasons(o2, shipping=True) == ["price_options_unchecked", "price_tax_unknown", "condition_not_new", "shipping_unknown"]
    plain = make_offer("r1", "貼るカイロ 60枚", 1000)
    plain.quantity = o.quantity
    assert unconfirmed_reasons(plain) == []                      # 楽天は変わらない


def test_yahoo_candidate_never_becomes_the_confirmed_cheapest():
    out = run([rk("r60", "貼るカイロ レギュラー 60枚", 1500)], [yoffer("y60", "貼るカイロ レギュラー 60枚", 1380, shipping_status="included")],
              desired_quantity=60)
    c = out["comparison"]
    assert c["cheapest_unit_price"]["mall"] == "rakuten"          # 安い Yahoo ではなく、確認済みの楽天
    assert c["cheapest_for_quantity"]["mall"] == "rakuten"
    assert c["cheapest_order"]["mall"] == "rakuten" and c["cheapest_order"]["payment_total"] == 1500
    y = next(o for g in c["groups"] for o in g["offers"] if o["mall"] == "yahoo")
    assert y["unit_price"] is None and y["provisional_unit_price"] is not None
    assert y["unit_price_status"] == "unconfirmed" and y["unit_price_unconfirmed_reasons"] == ["price_options_unchecked"]
    assert y["total_price"] == 1380 and y["shipping_status"] == "included"      # 送料込みの総額は出る（確認済みではない）
    tc = c["to_check"]
    assert [t["mall"] for t in tc] == ["yahoo"] and tc[0]["confirmed"] is False
    assert tc[0]["unconfirmed_reasons"] == ["price_options_unchecked"]
    assert tc[0]["payment_total"] is None and tc[0]["order_total_kind"] == "unconfirmed_total"
    assert tc[0]["conditions"][0]["text"] == "Yahoo!ショッピングの商品ページで、選んだ色・サイズ・数量の価格が1,380円のままか確認"
    assert tc[0]["conditions"][0]["reasons"] == ["price_options_unchecked"]
    assert any("Yahoo!ショッピング" in cv and "選択肢" in cv for cv in c["caveats"])


def test_to_check_only_when_yahoo_would_be_cheaper_than_the_confirmed_best():
    out = run([rk("r60", "貼るカイロ レギュラー 60枚", 1500)], [yoffer("y60", "貼るカイロ レギュラー 60枚", 1800, shipping_status="included")],
              desired_quantity=60)
    assert out["comparison"]["to_check"] == []                    # 確認済みの最安より高い Yahoo は出さない（今の to_check の定義のまま）


def test_without_a_confirmed_candidate_the_cheapest_yahoo_is_listed_for_checking():
    out = run([], [yoffer("y60", "貼るカイロ レギュラー 60枚", 1380, shipping_status="included")], desired_quantity=60)
    c = out["comparison"]
    assert c["cheapest_unit_price"] is None and c["cheapest_order"] is None and c["cheapest_for_quantity"] is None
    assert [t["item_code"] for t in c["to_check"]] == ["y60"]
    assert any("確認済み" in cv for cv in c["caveats"])


def test_shipping_unknown_yahoo_has_no_total_and_both_conditions_are_in_one_text():
    out = run([rk("r60", "貼るカイロ レギュラー 60枚", 1500)], [yoffer("y60", "貼るカイロ レギュラー 60枚", 900, shipping_status="unknown")],
              desired_quantity=60)
    y = next(o for g in out["comparison"]["groups"] for o in g["offers"] if o["mall"] == "yahoo")
    assert y["total_price"] is None and y["shipping_status"] == "unknown"
    t = out["comparison"]["to_check"][0]
    assert t["unconfirmed_reasons"] == ["price_options_unchecked", "shipping_unknown"]
    text = t["conditions"][0]["text"]
    assert "Yahoo!ショッピングの商品ページで、選んだ色・サイズ・数量の価格が900円のままか確認" in text and "送料" in text


def test_tax_and_condition_reasons_have_conditions_and_unit_texts():
    yah = yoffer("y60", "貼るカイロ レギュラー 60枚", 900, shipping_status="included",
                 mall_unconfirmed=["price_options_unchecked", "price_tax_unknown", "condition_not_new"])
    out = run([rk("r60", "貼るカイロ レギュラー 60枚", 1500)], [yah], desired_quantity=60)
    t = out["comparison"]["to_check"][0]
    assert t["unconfirmed_reasons"] == ["price_options_unchecked", "price_tax_unknown", "condition_not_new"]
    text = t["conditions"][0]["text"]
    assert "税込" in text and "状態" in text and "900円" in text
    y = next(o for g in out["comparison"]["groups"] for o in g["offers"] if o["mall"] == "yahoo")
    assert y["unit_price_unconfirmed_reasons"] == ["price_options_unchecked", "price_tax_unknown", "condition_not_new"]
    assert any("税込" in cv for cv in out["comparison"]["caveats"]) and any("新品でない" in cv for cv in out["comparison"]["caveats"])
    assert pricing.unit_price_reason_text(y["unit_price_unconfirmed_reasons"]) == "選択肢ごとの価格を確かめていない・税込・税抜が不明・新品でない可能性"


def test_same_jan_and_name_in_two_malls_are_two_candidates_and_points_are_not_subtracted():
    r = rk("same", "貼るカイロ レギュラー 60枚", 1500, jan="4905009678921")
    y = yoffer("same", "貼るカイロ レギュラー 60枚", 1500, jan="4905009678921", shipping_status="included", points_amount=500)
    out = run([r], [y])
    offers = [o for g in out["comparison"]["groups"] for o in g["offers"]]
    assert sorted(o["mall"] for o in offers) == ["rakuten", "yahoo"]
    yo = next(o for o in offers if o["mall"] == "yahoo")
    assert yo["points_amount"] == 500 and yo["total_price"] == 1500 and yo["price"] == 1500     # ポイントは総額から引かない
    assert yo["provisional_unit_price"] == pytest.approx(25.0, abs=0.01)                          # 単価にも使わない


def test_outlier_net_and_groups_use_the_mixed_candidates():
    rak = [rk(f"r{i}", f"貼るカイロ レギュラー {60}枚", 1500 + i * 10) for i in range(3)]
    yah = [yoffer("y1", "貼るカイロ レギュラー 60枚", 1550, shipping_status="included"),
           yoffer("y2", "貼るカイロ レギュラー 60枚", 20, shipping_status="included")]       # 桁違いに安い（読み違いの疑い）
    out = run(rak, yah)
    offers = {o["item_code"]: o for g in out["comparison"]["groups"] for o in g["offers"]}
    assert len(out["comparison"]["groups"]) == 1 and len(offers) == 5          # モールで分けない
    assert offers["y2"]["unit_price_outlier"] is True                             # 楽天 3 + Yahoo 1 の中央値（N=4）で判定された
    assert all(offers[f"r{i}"]["unit_price_outlier"] is False for i in range(3))


def test_rakuten_only_comparison_is_unchanged_by_the_new_fields():
    out = run([rk("r60", "貼るカイロ レギュラー 60枚", 1500)], [], desired_quantity=60)
    o = out["comparison"]["groups"][0]["offers"][0]
    assert o["points_amount"] is None and o["shipping_condition"] is None and o["condition"] is None and o["sale"] is None
    assert o["unit_price"] == 25.0 and out["comparison"]["cheapest_order"]["payment_total"] == 1500
    assert not any("Yahoo" in cv for cv in out["comparison"]["caveats"])


def test_offer_to_dict_exposes_yahoo_reference_fields():
    y = yoffer("y1", "貼るカイロ 60枚", 1000, shipping_condition="conditional_free", condition="used", points_amount=15,
               sale={"discounted_price": 1000, "period_end": "2026-12-01"})
    d = service.offer_to_dict(y)
    assert (d["points_amount"], d["shipping_condition"], d["condition"]) == (15, "conditional_free", "used")
    assert d["sale"] == {"discounted_price": 1000, "period_end": "2026-12-01"} and d["mall"] == "yahoo"


def test_shipping_title_conflict_uses_the_malls_own_name():
    y = yoffer("y1", "貼るカイロ 送料別 60枚", 1000, shipping_status="included")
    assert "Yahoo!ショッピングのデータでは送料込み" in service.shipping_title_conflict(y)
    r = make_offer("r1", "貼るカイロ 送料別 60枚", 1000, shipping_status="included")
    assert "楽天のデータでは送料込み" in service.shipping_title_conflict(r)
    note = service._shipping_conflict_note([r, y])
    assert "楽天・Yahoo!ショッピング" in note


def test_total_price_for_yahoo_follows_the_shipping_status_only():
    assert total_price(yoffer("a", "x", 500, shipping_status="included")) == 500
    assert total_price(yoffer("b", "x", 500, shipping_status="unknown")) is None
    assert isinstance(Offer.__dataclass_fields__["mall_unconfirmed"].default_factory(), list)
