# @owns WP14 W1 選択肢で価格が変わる印（adapter の価格幅・pricing の確認済み判定・3 入口の表示）の自作確認。独立試験（ブラインド）の代わりではない
"""WP14 W1: 楽天応答の itemPriceMin/Max で Offer.price_varies を立て、数量を使う最安（単位価格の最安）から外す。
実題名・実応答の値は 2026-11-20 の実 API（貼るカイロ）。URL のクエリ・鍵は入れない。"""
import pytest

import cli
from fakes import make_offer
from shopping import service
from shopping.adapters.rakuten import parse_item
from shopping.pricing import PRICE_VARIES_NOTE, compare, is_confirmed, unconfirmed_reasons

UNIDY_NAME = ("【ポイント10倍★〜25日9:59】 ＼温活セット発売中／カイロ 貼るカイロ レギュラー 60枚 使い捨てカイロ "
              "まとめ買い 使い捨て 貼る 貼るタイプ アイリスオーヤマカイロ アイリスオーヤマ ぽかぽか家族【割振】")
IRIS_NAME = ("【公式】カイロ 貼る レギュラー 60枚 ぽかぽか家族 PKN-60HR アイリスオーヤマ貼るカイロ レギュラーサイズ "
             "使い捨てカイロ 使い捨て あったかグッズ 冷え 防寒 寒さ対策 腰 脇 背中 冬 持ち運び 運動 レジャー スポーツ 【nichi】")


def item(code="unidy:10972223", name=UNIDY_NAME, price=1500, **kw):
    d = {"itemName": name, "itemCode": code, "itemPrice": price,
         "itemUrl": f"https://item.rakuten.co.jp/{code.replace(':', '/')}/", "postageFlag": 0, "availability": 1}
    d.update(kw)
    return d


def parse(**kw):
    return parse_item(item(**kw), "2026-11-20T10:00:00+09:00")


# --- adapter: 価格幅 ----------------------------------------------------------------

def test_real_unidy_range_marks_price_varies():
    o = parse(itemPriceMin1=1500, itemPriceMax1=1720, itemPriceMin2=1500, itemPriceMax2=1720,
              itemPriceMin3=1500, itemPriceMax3=1720, itemPriceBaseField="item_price_min3")
    assert (o.price, o.price_min, o.price_max, o.price_varies) == (1500, 1500, 1720, True)


@pytest.mark.parametrize("lo,hi,varies", [(840, 11800, True), (4980, 8980, True), (1500, 8980, True),
                                          (2981, 2981, False), (7180, 7180, False)])
def test_other_real_ranges(lo, hi, varies):
    o = parse(itemPriceMin3=lo, itemPriceMax3=hi)
    assert o.price_varies is varies


def test_missing_or_partial_range_is_not_varies():
    assert parse().price_varies is False and parse().price_min is None
    assert parse(itemPriceMin3=1500).price_varies is False           # max が無い
    assert parse(itemPriceMin3="x", itemPriceMax3="y").price_varies is False
    assert parse(itemPriceMin3=True, itemPriceMax3=2000).price_varies is False


def test_range_falls_back_3_then_1_then_2():
    o = parse(itemPriceMin1=100, itemPriceMax1=200, itemPriceMin2=100, itemPriceMax2=300)
    assert (o.price_min, o.price_max) == (100, 200)                  # 3 が無ければ 1 を先に
    o = parse(itemPriceMin2=100, itemPriceMax2=300)
    assert (o.price_min, o.price_max) == (100, 300)
    o = parse(itemPriceMin3=5, itemPriceMax3=9, itemPriceMin1=100, itemPriceMax1=200)
    assert (o.price_min, o.price_max) == (5, 9)


def test_string_prices_and_asuraku():
    o = parse(itemPriceMin3="1500", itemPriceMax3="1720", asurakuFlag=1, asurakuClosingTime="14")
    assert o.price_varies and o.asuraku_flag is True and o.asuraku_closing_time == "14"
    o = parse(asurakuFlag=0, asurakuClosingTime="")
    assert o.asuraku_flag is False and o.asuraku_closing_time is None
    assert parse().asuraku_flag is None


# --- pricing: 数量を使う最安から外す --------------------------------------------------

def kairo_offers(varies_price=1500):
    a = parse(itemPriceMin3=varies_price, itemPriceMax3=1720)          # 60枚 1500 円。幅あり
    b = parse_item(item("irisplaza-r:10091104", IRIS_NAME, 1720, itemPriceMin3=1720, itemPriceMax3=1720), "t")
    c = parse_item(item("irisplaza-r:10091105", "【公式】カイロ 貼る レギュラー 30枚入り 貼るカイロ", 1280,
                        itemPriceMin3=1280, itemPriceMax3=1280), "t")
    return [a, b, c]


def test_price_varies_candidate_is_not_cheapest_unit_price_but_stays_listed():
    r = compare(kairo_offers(), basis="個")
    assert r.cheapest_unit_price.mall_item_code == "irisplaza-r:10091104"      # 1720/60=28.7 < 1280/30=42.7。25.0円の unidy は幅ありで外す
    codes = [o.mall_item_code for g in r.groups for o in g.offers]
    assert "unidy:10972223" in codes
    unidy = next(o for g in r.groups for o in g.offers if o.mall_item_code == "unidy:10972223")
    assert unidy.unit_price == pytest.approx(1500 / 60) and unidy.price_varies   # 表示価格で単価は出す
    assert r.cheapest_price.mall_item_code == "irisplaza-r:10091105" or r.cheapest_price.price == 1280
    assert any("選択肢によって価格が変わる候補: 1件" in c for c in r.caveats)


def test_cheapest_unit_price_without_the_range_would_have_been_unidy():
    plain = kairo_offers()
    plain[0].price_min = plain[0].price_max = None
    r = compare(plain, basis="個")
    assert r.cheapest_unit_price.mall_item_code == "unidy:10972223"
    assert not any("選択肢によって価格が変わる" in c for c in r.caveats)


def test_cheapest_price_is_still_the_fact_even_if_varies():
    offers = kairo_offers()
    offers[2].price = 3000
    r = compare(offers, basis="個")
    assert r.cheapest_price.mall_item_code == "unidy:10972223"        # 事実として最小の表示価格


def test_confirmed_predicate_reasons():
    offers = kairo_offers()
    compare(offers)
    assert unconfirmed_reasons(offers[0]) == ["price_varies"]
    assert is_confirmed(offers[1]) and is_confirmed(offers[2])
    o = make_offer("x", "電池 40本", 100)                              # 数量未解析
    assert unconfirmed_reasons(o) == ["quantity_unknown"]
    offers[1].shipping_status = "separate"
    assert unconfirmed_reasons(offers[1], shipping=True) == ["shipping_separate"]
    assert is_confirmed(offers[1])                                    # 単価の最安では送料を見ない


# --- service / CLI / Web の表示 -------------------------------------------------------

def test_offer_dict_carries_range_and_cli_marks_it():
    offers = kairo_offers()
    compare(offers)
    d = service.offer_to_dict(offers[0])
    assert (d["price_min"], d["price_max"], d["price_varies"]) == (1500, 1720, True)
    assert d["asuraku_flag"] is None
    line = cli._offer_line(d)
    assert PRICE_VARIES_NOTE in line and "1,500円〜1,720円" in line
    assert PRICE_VARIES_NOTE not in cli._offer_line(service.offer_to_dict(offers[1]))


def test_web_card_marks_price_varies():
    from shopping.web_view import render
    offers = kairo_offers()
    compare(offers)
    html = render("results.html", "", mode="compare", keywords=["貼るカイロ"], mock=False,
                  caveats=[], basis_label="1個あたり",
                  cheapest=[("単位価格が最安", service.offer_to_dict(offers[0]))], groups=[], notes=[], stats=None,
                  form={}, unknown=[], unknown_count=0, shown_max=10, warnings=[])
    assert PRICE_VARIES_NOTE in html
