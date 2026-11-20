# @owns WP14 W4 説明欄の見出し付きの記述からの数量の補完（caption_quantity.py と、それを使う service・pricing）の自作確認。独立試験（ブラインド）の代わりではない
"""WP14 W4: 見出し（入数・入り数・内容量・数量・容量）の直後の値だけを、題名が none の時だけ補う。題名の読み取り（quantity.py）は変えない。
説明欄の抜粋は 2026-11-20 の実 API（実測表は docs/WORKLOG.md の WP14 W4 の行）。"""
import pytest

import cli
from fakes import make_offer
from shopping import service
from shopping.caption_quantity import read_caption, read_offer_quantity
from shopping.pricing import compare
from shopping.quantity import parse_quantity

COLOLO_TITLE = "文化たきつけ☆木炭・練炭・豆炭・石炭・オガ炭・薪用簡単着火剤・屋外用（火おこしグッズ）"
COLOLO_CAPTION = ("商品情報 商品の説明 ■気をつけて頂きたいこと：本品は煙と臭いが出ます。屋外での調理、暖房燃料としてのご利用がおすすめです。 "
                  "主な仕様 ■数量:18本入り ■材質：木材繊維質・灯油 ■使用方法：木炭・練炭・豆炭等にの下に本品を1～2 本、"
                  "石油・オイルコークス等には2～3本 程度置いて着火します。")
UNIDY_CAPTION = ("10枚はこちら 30枚はこちら 60枚はこちら 温活セット… 貼るカイロ30枚 まめカイロ7枚 くつ下用カイロ 15足 "
                 "●入数60枚 15点以上ご購入 関連キーワード(本商品の説明ではありません) カイロ 入数 100枚 内容量 200枚")


def offer(title, caption, price=500, lo=None, hi=None):
    o = make_offer("x", name=title, price=price, shipping_status="included")
    o.caption, o.price_min, o.price_max = caption, lo, hi
    return o


# --- 補う（題名が none）---------------------------------------------------------------------------

def test_real_cololo_caption_fills_18_hon_with_the_evidence():
    q = read_offer_quantity(offer(COLOLO_TITLE, COLOLO_CAPTION))
    assert (q.confidence, q.count_total, q.count_unit, q.source) == ("high", 18, "本", "caption")
    assert q.caption_evidence == "数量:18本入り"
    assert parse_quantity(COLOLO_TITLE).confidence == "none"           # 題名側の出力は変わらない


@pytest.mark.parametrize("caption,count,unit,content", [
    ("■数量:18本入り", 18, "本", None),
    ("■数量：18本入り", 18, "本", None),                               # 全角コロン
    ("【内容量】 6個 ブラック", 6, "個", None),                         # 括弧つきの見出し
    ("入数 6個（各色1） 対応機種 ・EP-707A", 6, "個", None),             # 実: IC6CL80L
    ("内容量:7L×6個 ●重量：約3kg", 6, "個", 7000.0),                    # 実: 猫砂
    ("内容量25枚(個別包装)", 25, "枚", None),                           # 区切りなし
    ("内容量 350mg×90粒(約3ヶ月分) 原材料", 90, "粒", 0.35),             # 実: サプリ
    ("入り数 12本 ■材質", 12, "本", None),
])
def test_headings_and_separators(caption, count, unit, content):
    r = read_caption(caption)
    assert r is not None and (r.info.count_total, r.info.count_unit) == (count, unit) and r.info.content_amount == content


# --- 採らない所（位置・区切りで除外）----------------------------------------------------------------

def test_headingless_numbers_other_products_and_tail_are_not_read():
    assert read_caption("10枚はこちら 30枚はこちら 60枚はこちら 貼るカイロ30枚 まめカイロ7枚 15足") is None
    assert read_caption("本品を1～2 本、石油には2～3本 程度置いて着火します") is None
    # 見出しの無い文中の数は読まないが、見出しの値（入数60枚）は読む。15点以上・「関連キーワード」以降は読まない
    r = read_caption(UNIDY_CAPTION)
    assert r is not None and (r.info.count_total, r.info.count_unit) == (60, "枚")
    assert "100" not in r.evidence and "200" not in r.evidence


def test_headings_inside_longer_words_and_non_numeric_values_are_not_headings():
    for text in ("購入数 3個まで", "大容量500mlタイプ", "総内容量 24本", "数量限定 100個 セール", "内容量:本体のみ 1個",
                 "容量オーバー 5個"):
        assert read_caption(text) is None, text


def test_this_sentence_with_hakochira_is_another_product():
    assert read_caption("入数60枚はこちら 入数30枚はこちら") is None
    r = read_caption("入数60枚はこちら ●入数30枚")
    assert r is not None and r.info.count_total == 30


def test_measure_only_and_per_unit_values_are_not_a_total():
    for text in ("内容量:2L", "容量 500ml", "内容量 1本あたり50g", "容量 :1袋あたり 6L", "内容量:5L(1本当たり)"):
        assert read_caption(text) is None, text


def test_multiple_headings_must_agree_and_a_mismatch_is_not_read():
    r = read_caption("入数 48本 内容量 48本")
    assert r is not None and r.info.count_total == 48 and r.headings == ["入数", "内容量"]
    assert read_caption("入数 48本 内容量 24本") is None
    assert read_caption("内容量：500ml 入数：24本入り") is None           # 個数の無い値と有る値は一致しない（保守側）


def test_low_value_is_not_used():
    assert read_caption("数量 3~5個") is None                           # 範囲は題名と同じく low


# --- 補う条件 ------------------------------------------------------------------------------------------

def test_only_none_titles_are_filled_low_is_left_and_high_is_unchanged():
    low = offer("ノートPC 2台 3台 5台まとめ", "数量:10台")
    assert parse_quantity(low.item_name).confidence == "low"
    assert read_offer_quantity(low).confidence == "low" and read_offer_quantity(low).source == "title"
    high = offer("文化たきつけ 18本入り", "■数量:18本入り")
    q = read_offer_quantity(high)
    assert (q.confidence, q.count_total, q.source, q.caption_conflict) == ("high", 18, "title", False)


def test_price_varies_candidates_are_not_filled():
    # 実測: 補完の誤りはすべて「価格が選択肢で変わる商品の説明欄」（猫砂 PFC-7L PFC-18L PFC-14L の 7L×6袋 など）
    o = offer("猫砂 PFC-7L PFC-18L PFC-14L", "■内容量7L×6袋■材質", price=3480, lo=3480, hi=5080)
    assert read_offer_quantity(o).confidence == "none"
    o2 = offer("猫砂 PFC-7L PFC-18L PFC-14L", "■内容量7L×6袋■材質", price=3480, lo=3480, hi=3480)
    assert read_offer_quantity(o2).confidence == "high"


def test_title_high_conflict_keeps_confidence_and_marks_the_evidence():
    o = offer("文化たきつけ10個セット☆木炭・練炭", "主な仕様 ■数量:18本入り×10個 ■材質")      # 実: cololo:10000071
    q = read_offer_quantity(o)
    assert (q.confidence, q.count_total, q.count_unit, q.source) == ("high", 10, "個", "title")
    assert q.caption_conflict is True and q.caption_evidence == "数量:18本入り×10個"
    same = read_offer_quantity(offer("文化たきつけ 18本×10個", "■数量:18本入り×10個"))
    assert same.caption_conflict is False


def test_no_caption_or_non_string_is_a_noop():
    for cap in (None, "", 5):
        o = offer("文化たきつけ", None)
        o.caption = cap
        assert read_offer_quantity(o).confidence == "none"


# --- 比較への効き方 ------------------------------------------------------------------------------------

def test_caption_filled_candidate_is_listed_with_a_price_but_never_confirmed_cheapest():
    plain = offer("文化たきつけ 18本入り", None, price=1200)
    plain.mall_item_code = "plain"
    cap = offer(COLOLO_TITLE, COLOLO_CAPTION, price=490)
    cap.mall_item_code = "cap"
    r = compare([plain, cap], basis="本")
    assert {o.mall_item_code for o in r.groups[0].offers} == {"plain", "cap"}
    capo = next(o for o in r.groups[0].offers if o.mall_item_code == "cap")
    assert capo.unit_price == pytest.approx(490 / 18)                    # 単位価格は出す
    assert r.cheapest_unit_price.mall_item_code == "plain"                # 確認済みではないので最安に選ばない
    assert any("説明欄の見出し付きの記述から補った候補: 1件" in c for c in r.caveats)
    r = compare([plain, cap], basis="本", desired_quantity=18)
    assert r.cheapest_order.offer.mall_item_code == "plain"
    cond = r.to_check[0].conditions[0]
    assert cond["reason"] == "quantity_from_caption" and "数量:18本入り" in cond["text"]


def test_conflict_count_caveat_and_service_dict():
    a = offer("文化たきつけ10個セット☆木炭", "■数量:18本入り×10個")
    r = compare([a], basis="個")
    assert any("食い違う候補: 1件" in c for c in r.caveats)
    d = service.offer_to_dict(a)
    assert d["quantity"]["caption_conflict"] is True and d["quantity"]["source"] == "title"
    assert "caption_evidence" in d["quantity"]


def test_service_annotates_with_the_caption_for_search_and_compare():
    class Ad:
        mall = "rakuten"
        def search(self, keyword, **kw):
            return [offer(COLOLO_TITLE, COLOLO_CAPTION)], 1
    for fn in (service.search_products, service.compare_offers):
        r = fn(["文化たきつけ"], adapter=Ad(), pages=1, sleep=lambda s: None)
        offers = r["offers"] if fn is service.search_products else r["comparison"]["groups"][0]["offers"]
        assert offers[0]["quantity"]["source"] == "caption" and offers[0]["quantity"]["count_total"] == 18


def test_cli_marks_caption_quantity():
    o = offer(COLOLO_TITLE, COLOLO_CAPTION)
    o.quantity = read_offer_quantity(o)
    text = cli._qty(service.offer_to_dict(o))
    assert "説明欄の記述から補完" in text and "数量:18本入り" in text
