# @owns WP15 段B U2 項目単位の補完（題名が個数だけ high の時の見出し `長さ`）の自作確認。独立試験（ブラインド）の代わりではない
"""cocodecow:10392423（2026-11-21 の実 API）の抜粋で、題名の個数 48 ロールに説明欄の `長さ：100mシングル` を内容量として重ねる。
補った内容量を使う basis（m）の単価だけが仮、個数だけで比べる basis（ロール）は確認済みのまま、自動 basis は題名の内容量だけで判定する。"""
import pytest

from fakes import make_offer
from shopping import service
from shopping.caption_quantity import read_offer_quantity
from shopping.pricing import compare, unconfirmed_reasons
from shopping.quantity import parse_quantity

TITLE = "ココデカウ クレシア スコッティ フラワーパック 2倍長持ち シングル 12ロール×4パック"
CAPTION = ("【商品説明】取り替えの手間が半分のたっぷり使えるシングル100メートル。省スペースで保管もスッキリ。"
           "【仕様】●長さ：100mシングル●紙幅：108mm●くつろぐ花の香りつき●芯あり●注文単位：1箱（12ロール×4パック）"
           "【備考】※メーカーの都合により、パッケージ・仕様等は予告なく変更になる場合がございます。")


def offer(code="x", title=TITLE, caption=CAPTION, price=4350, lo=None, hi=None):
    o = make_offer(code, name=title, price=price, shipping_status="included")
    o.caption, o.price_min, o.price_max = caption, lo, hi
    return o


def test_cocodecow_is_48_rolls_100m_per_roll_4800m():
    q = read_offer_quantity(offer())
    assert (q.count_total, q.count_unit, q.confidence) == (48, "ロール", "high")
    assert (q.content_amount, q.content_dimension, q.content_unit, q.measure_total) == (100.0, "length", "m", 4800.0)
    assert q.source == "title+caption" and q.caption_evidence == "長さ:100mシングル"
    assert q.content_amounts == {"length": 100.0}
    assert parse_quantity(TITLE).content_amount is None                     # 題名の読み取りは変わらない


@pytest.mark.parametrize("caption", [
    "●長さ：100m●",                       # 全角コロン
    "【長さ】100m",
    "●長さ：約100m●",
    "●長さ：10000cm●",                    # 単位が違っても m に換算して同じ
])
def test_other_forms_of_the_heading_value_are_read(caption):
    q = read_offer_quantity(offer(caption=caption))
    assert (q.source, q.content_amount, q.content_dimension) == ("title+caption", 100.0, "length")


@pytest.mark.parametrize("caption", [
    "●長さ2倍巻の100m●",                  # 値が数字＋長さの単位で始まらない
    "長さ 約30cm のコード付き",            # 見出しの直後に区切りが無い（使用例の文）
    "長さ 100m",
    "●長さ：30cmにカット●",               # 単位の直後が助詞
    "●長さ：100mほど●", "●長さ：100mまで●", "●長さ：100mより●", "●長さ：100mの●", "●長さ：100mで●",
    "●長さ：100m（幅114mm）●",            # 単位付きの数が2つ（m と mm）
    "●長さ：100m×2巻●",                  # 個数の記述
    "●長さ：1ロールあたり100m●",          # あたり（かつ数字で始まらない）
    "●長さ：100mあたり●",
    "●内容量：100m●",                     # 見出しが違う（長さだけ）
    "●重さ：100g●", "●重量：100g●", "●幅：108mm●", "●サイズ：108mm●",
    "●ロールの長さ：100m●",              # 見出しの直前が語の文字
    "100m 長さ",                           # 値が見出しの前
    "●長さ：50m●●長さ：100m●",           # 見出しが複数で食い違う
    "●長さ：100m はこちら●",
])
def test_not_filled(caption):
    q = read_offer_quantity(offer(caption=caption))
    assert q.source == "title" and q.content_amount is None


def test_related_keywords_tail_is_not_read():
    q = read_offer_quantity(offer(caption="商品説明 関連キーワード 長さ：100m"))
    assert q.source == "title" and q.content_amount is None


def test_same_value_twice_is_read():
    q = read_offer_quantity(offer(caption="●長さ：100m●仕様 長さ：100m"))
    assert q.content_amount == 100.0 and q.source == "title+caption"


def test_price_varies_candidate_is_not_filled():
    q = read_offer_quantity(offer(lo=4350, hi=8700))
    assert q.source == "title" and q.content_amount is None


def test_title_with_its_own_content_amount_or_not_high_is_not_filled():
    assert read_offer_quantity(offer(title="トイレットペーパー 12ロール 50m")).source == "title"
    low = read_offer_quantity(offer(title="トイレットペーパー 12ロール 24ロール"))
    assert low.confidence != "high" and low.source == "title"
    none = read_offer_quantity(offer(title="トイレットペーパー 長持ち"))
    assert none.confidence == "none" and none.source == "title"


def test_caption_conflict_still_marked_after_the_item_fill():
    caption = "●長さ：100m●●数量：12ロール●"
    q = read_offer_quantity(offer(caption=caption))
    assert q.source == "title+caption" and q.caption_conflict is True
    assert "長さ:100m" in q.caption_evidence and "数量:12ロール" in q.caption_evidence


def _compare(basis, offers=None, **kw):
    offers = offers or [offer("a"), offer("b", title="シングル 48ロール", caption="", price=4000)]
    return compare(offers, basis=basis, **kw)


def test_basis_roll_keeps_the_title_count_confirmed_and_the_unit_price_final():
    c = _compare("ロール", desired_quantity=48)
    a = next(o for g in c.groups for o in g.offers if o.mall_item_code == "a")
    assert unconfirmed_reasons(a) == [] and a.unit_price == pytest.approx(4350 / 48)
    d = service._comparison_to_dict(c)
    ao = next(o for o in d["groups"][0]["offers"] if o["item_code"] == "a")
    assert ao["unit_price"] == pytest.approx(90.62) and ao["unit_price_status"] == "confirmed"


def test_basis_m_makes_the_unit_price_provisional_and_not_the_cheapest():
    o_a = offer("a")
    o_b = offer("b", title="シングル 12ロール 50m", caption="", price=9000)
    c = compare([o_a, o_b], basis="m", desired_quantity=4800)
    a = next(o for g in c.groups for o in g.offers if o.mall_item_code == "a")
    assert a.unit_price == pytest.approx(4350 / 4800) and unconfirmed_reasons(a) == ["measure_from_caption"]
    assert c.cheapest_unit_price.mall_item_code == "b"                       # a の方が安いが仮なので最安に選ばない
    d = service._comparison_to_dict(c)
    ad = next(o for o in d["groups"][0]["offers"] if o["item_code"] == "a")
    assert ad["unit_price"] is None and ad["provisional_unit_price"] == pytest.approx(0.91)
    assert ad["unit_price_unconfirmed_reasons"] == ["measure_from_caption"]
    tc = d["to_check"]
    assert [t["item_code"] for t in tc] == ["a"]
    assert tc[0]["conditions"][0]["reasons"] == ["measure_from_caption"]
    assert "説明欄『長さ:100mシングル』の内容量が正しければ" in tc[0]["conditions"][0]["text"]
    assert any("長さ" in c_ for c_ in d["caveats"])


def test_auto_basis_ignores_the_filled_content_amount():
    """題名から内容量が読めた候補が過半でない時、補った内容量で個→m に変わらない。"""
    offers = [offer(str(i), price=4000 + i) for i in range(3)] + [offer("t", title="シングル 12ロール 50m", caption="", price=900)]
    c = compare(offers)
    assert c.basis == "個"                       # 題名の内容量は 1/4 だけ（補った 3 件を数えると m）


def test_auto_basis_still_follows_title_amounts():
    offers = [offer(str(i), title=f"シングル 12ロール 50m {i}", caption="", price=900 + i) for i in range(3)] + [offer("a")]
    assert compare(offers).basis == "m"


def test_search_products_quantity_shows_the_source():
    q = service.offer_to_dict(_annotated(offer()))["quantity"]
    assert q["source"] == "title+caption" and q["content_amount"] == 100.0 and q["title_confidence"] == "high"


def _annotated(o):
    o.quantity = read_offer_quantity(o)
    return o


def test_cli_and_web_mark_the_filled_content_amount():
    import cli
    from shopping import web_view
    d = service.offer_to_dict(_annotated(offer()))
    for text in (cli._qty(d), web_view._qty(d)):
        assert "48ロール × 100m" in text and "内容量を説明欄から補った・確認済みではない: 長さ:100mシングル" in text
