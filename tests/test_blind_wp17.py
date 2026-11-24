# @owns WP17 ブラインド試験（Yahoo!ショッピング対応: 応答の Offer 化・エラー種別・確認済みでない比較・モールの選択）
"""WP17 ブラインド試験（2026-11-24）。根拠は plans/WP17_yahoo_shopping.md の契約 Y1〜Y8・C2・C4・C5・P1〜P5・
「固定するインターフェース」と、docs/SPEC.md の §4・§5・§8（Q11・Q13・Q16・Q21・Q23）だけ。
実装担当の説明・実装中のコードは見ない（今の master の既存コードと tests/fakes.py は読んだ）。実装担当は読まない・編集しない。
期待値は全て手計算か実応答（data/yahoo_poc の Yahoo 商品検索 v3）の項目から導き、各試験のコメントに式を残す。

入口: shopping.adapters.yahoo の parse_hit / is_item_url / YahooAdapter（偽 opener）、
service.compare_offers / search_products / find_regular_item（adapters= に偽 Adapter。実 API・本番は使わない）。
比較（pricing）と数量の読み取りは実物を通す。業務ロジックの再実装はしない（比較の期待値は式つきの手計算）。

構成: 本ファイル＝アダプタ（Y1〜Y8・parse_hit・エラー）。test_blind_wp17_compare.py＝比較・malls・一貫試験。共通部品＝blind_wp17_support.py、
fixture＝fixtures/blind_wp17_yahoo_search.json（実応答の hit 7 件）。

固定するもの（重大領域＝金額: 確認済み・最安・送料・ポイント）:
  Y5  parse_hit: 送料 code の写像・名前の「送料無料」で決めない・ポイントは lyLimitedBonusAmount だけ・価格は price・
      janCode 空→None・condition・taxable・全候補 price_options_unchecked・URL の ok/needs_review（捨てない・改変しない）・説明欄
  Y6  エラー種別（HTTP・timeout・invalid_json・unexpected_response）と、appid・URL・応答本文が例外・repr・str に出ないこと
  Y8  鍵の CR/LF・空白は呼ばない・repr で伏せる
  Y2〜Y4（一部） results/start・sort の写像・ng_keyword をアダプタ内で捨てる・1000 件目の天井
  P1〜P5 Yahoo の候補は unit_price・最安・注文の最安に入らず provisional と to_check に出る・楽天の確認済みの結果は
      Yahoo を混ぜても変わらない・ポイントで総額・単価が下がらない・送料 unknown は total_price を出さない・
      モール／商品コードが違えば別候補・外れ値はモールを混ぜた全体で判定
  C2・C4・C5 malls（未知は invalid_request・API 0 回／["rakuten"] で Yahoo を呼ばない／片方の失敗でもう片方の比較を返す／
      全モール失敗は今のエラー応答／rate_limited・server_error は残りを打ち切る）
  一貫  実 YahooAdapter（偽 opener）＋楽天の偽 Adapter を service.compare_offers に通し、appid・URL が出力 JSON に出ない事と
      Yahoo が確認済みの枠に入らない事を確かめる（設計規律8）

試験していない観点（報告に書く）: 公開 Web・MCP・CLI の表示とクレジット（W1〜W4）・Yahoo の鍵の読み順（Y8 の .env 系）・流量 2.2 秒（Y7）・
モック時の Yahoo 架空データ（C1）・mock_data・並走（C3）の並走そのもの・実 API。契約が決めていない点は「契約の穴」として報告
（cheapest_price / cheapest_total に Yahoo が入るか・全モール失敗の error.kind・per_mall の形など）。非機能（性能・互換）: 該当なし。
セキュリティ（秘密が出ない）は Y6・一貫試験で見る。変異は既定でやらない。
"""

from __future__ import annotations

import socket
from urllib.error import URLError

import pytest

from fakes import FakeOpener, make_offer
from shopping import service
from shopping.adapters.base import AdapterError
from shopping.adapters.yahoo import YahooAdapter, is_item_url, parse_hit

from blind_wp17_support import (
    ENDPOINT,
    FETCHED,
    SECRET,
    _adapter,
    _hit,
    _http_err,
    _no_leak,
    _parse,
    _query,
    _resp,
)


# ==========================================================================
# 1. parse_hit（Y5）
# ==========================================================================

# 実応答 fixture（tests/fixtures/blind_wp17_yahoo_search.json。data/yahoo_poc の実 hit 7 件。値は実応答の項目から手で写した）:
#  idx code                      price premium ship janCode          lyLimitedBonus(他の point 項目は 0 か ly と同額)
#   0  irisplaza_h264589         1680  1680    2    4905009678921    15
#   1  inskagu-y_1894684         4980  4980    2    4905009678921    45   （240枚入り。0 と同じ JAN）
#   2  rd-lohaco_nw92584         1760  1760    1    4902899480085    16   （lohaco。設定なし）
#   3  sofort_1897140            1680  1680    2    ""               15   （janCode 空文字）
#   4  truetools_tnob-6838360    2658  2280    3    4905009678921    241  （premiumPrice≠price・条件付き送料無料。premium 系 207）
#   5  rd-lohaco_nw92620         6475  6475    2    4902899480085    58
#   6  bestexcel_264589          1720  1720    2    4905009678921    156
FIXTURE_ROWS = [
    # idx, code, price, shipping_status, jan, points, seller_id
    (0, "irisplaza_h264589", 1680, "included", "4905009678921", 15, "irisplaza"),
    (1, "inskagu-y_1894684", 4980, "included", "4905009678921", 45, "inskagu-y"),
    (2, "rd-lohaco_nw92584", 1760, "unknown", "4902899480085", 16, "rd-lohaco"),
    (3, "sofort_1897140", 1680, "included", None, 15, "sofort"),
    (4, "truetools_tnob-6838360", 2658, "unknown", "4905009678921", 241, "truetools"),
    (5, "rd-lohaco_nw92620", 6475, "included", "4902899480085", 58, "rd-lohaco"),
    (6, "bestexcel_264589", 1720, "included", "4905009678921", 156, "bestexcel"),
]


@pytest.mark.parametrize("idx,code,price,ship,jan,points,seller", FIXTURE_ROWS,
                         ids=[r[1] for r in FIXTURE_ROWS])
def test_y5_real_hits_map_to_offer(idx, code, price, ship, jan, points, seller):
    # Y5: code→mall_item_code・price→price（整数）・shipping.code の写像（2=included・1/3=unknown）・janCode（空文字は None）・
    # point.lyLimitedBonusAmount→points_amount（truetools は premium 207 を足さず 241）・seller.sellerId→shop_code・mall="yahoo"
    h = _resp()["hits"][idx]
    o = _parse(h)
    assert o.mall == "yahoo"
    assert o.mall_item_code == code
    assert o.price == price and isinstance(o.price, int) and not isinstance(o.price, bool)
    assert o.item_name == h["name"]
    assert o.shipping_status == ship
    assert o.shipping_fee is None                                 # 送料額は API に無い
    assert o.jan == jan
    assert o.points_amount == points
    assert o.points_rate is None
    assert o.shop_code == seller
    assert o.shop_name == h["seller"]["name"]
    assert o.availability is True                                 # inStock=true
    assert o.review_average == pytest.approx(h["review"]["rate"]) and o.review_count == h["review"]["count"]
    assert o.fetched_at == FETCHED
    assert o.item_url == h["url"] and o.item_url_status == "ok"   # 実 URL は store.shopping／lohaco の商品 URL
    assert o.price_min is None and o.price_max is None and o.price_varies is False   # 楽天の判定を変えない（price_varies は None のまま）
    # 全候補に price_options_unchecked。新品・税込の実 hit はそれだけ（重複なし）
    assert o.mall_unconfirmed == ["price_options_unchecked"]


def test_y5_premium_price_is_not_used():
    # Y5: price を採る。premiumPrice（会員価格 2280）は使わない（truetools: price 2658・premiumPrice 2280）
    h = _resp()["hits"][4]
    assert h["price"] == 2658 and h["premiumPrice"] == 2280         # 前提（実応答）
    assert _parse(h).price == 2658


def test_y5_sale_price_is_price_not_label():
    # Y5: セール中は price（値下げ後）。priceLabel.defaultPrice・premiumPrice・priceLabel.premiumPrice は使わない
    h = _hit(0, price=1400, premiumPrice=1300, priceLabel__defaultPrice=1650, priceLabel__discountedPrice=1400,
             priceLabel__fixedPrice=1650, priceLabel__premiumPrice=1200)
    assert _parse(h).price == 1400


@pytest.mark.parametrize("code,status", [(2, "included"), (1, "unknown"), (3, "unknown")])
def test_y5_shipping_code_mapping(code, status):
    # Y5: shipping.code 2（送料無料）→ included、1（設定なし）・3（条件付き送料無料）→ unknown。shipping_fee は None
    o = _parse(_hit(0, shipping__code=code))
    assert o.shipping_status == status
    assert o.shipping_fee is None


def test_y5_shipping_code_3_is_conditional_free():
    # Y5: 3 は shipping_condition="conditional_free"。1・2 では出さない
    assert _parse(_hit(0, shipping__code=3)).shipping_condition == "conditional_free"
    for code in (1, 2):
        assert _parse(_hit(0, shipping__code=code)).shipping_condition != "conditional_free"


@pytest.mark.parametrize("code", [0, 4, 99])
def test_y5_shipping_other_codes_are_unknown(code):
    # Y5: 「その他」→ unknown（送料込みにしない）。shipping_fee は None
    o = _parse(_hit(0, shipping__code=code))
    assert o.shipping_status == "unknown" and o.shipping_fee is None


@pytest.mark.parametrize("code,name,status", [
    (1, "送料無料 貼るカイロ 60枚 レギュラー", "unknown"),         # 名前は送料無料でも code=1（設定なし）→ unknown
    (3, "【送料無料】貼るカイロ 60枚", "unknown"),                   # 条件付き。名前の文字で included にしない
    (1, "貼るカイロ 60枚 送料込み", "unknown"),
    (2, "貼るカイロ 60枚 送料別途", "included"),                      # 名前が送料別でも code=2 → included（フラグを正とする）
], ids=["code1_name_free", "code3_name_free", "code1_name_komi", "code2_name_separate"])
def test_y5_shipping_is_decided_by_code_not_name(code, name, status):
    # Y5: 名前の文字（「送料無料」）で決めない
    o = _parse(_hit(0, shipping__code=code, name=name))
    assert o.shipping_status == status
    assert o.shipping_fee is None


def test_y5_points_amount_is_only_ly_limited_bonus():
    # Y5: points_amount＝point.lyLimitedBonusAmount だけ。amount(7)・bonusAmount(9)・premiumAmount(11)・premiumBonusAmount(13)・
    # lyLimitedPremiumBonusAmount(30) は足さない・使わない（期待値 20。足すと 90 になる）
    h = _hit(0, point__amount=7, point__bonusAmount=9, point__lyLimitedBonusAmount=20, point__premiumAmount=11,
             point__premiumBonusAmount=13, point__lyLimitedPremiumBonusAmount=30)
    o = _parse(h)
    assert o.points_amount == 20
    assert o.points_rate is None


def test_y5_points_zero_ly_does_not_leak_other_fields():
    # Y5: lyLimitedBonusAmount=0 のとき、他の項目（7+9+11+13+30）が points_amount に漏れない（0 か None。契約は 0/None を決めていない）
    h = _hit(0, point__amount=7, point__bonusAmount=9, point__lyLimitedBonusAmount=0, point__premiumAmount=11,
             point__premiumBonusAmount=13, point__lyLimitedPremiumBonusAmount=30)
    assert _parse(h).points_amount in (0, None)


@pytest.mark.parametrize("jan,expected", [("", None), ("4905009678921", "4905009678921")])
def test_y5_jan_empty_string_is_none(jan, expected):
    # Y5: janCode 空文字 → None。値はそのまま
    assert _parse(_hit(0, janCode=jan)).jan == expected


@pytest.mark.parametrize("cond", ["used", "refurbished"])
def test_y5_condition_not_new(cond):
    # Y5: condition が new でない時は未確定理由 condition_not_new・出力に condition（value そのまま）
    o = _parse(_hit(0, condition=cond))
    assert "condition_not_new" in o.mall_unconfirmed
    assert o.condition == cond
    assert "price_options_unchecked" in o.mall_unconfirmed


def test_y5_condition_new_has_no_condition_reason():
    assert "condition_not_new" not in _parse(_hit(0, condition="new")).mall_unconfirmed


@pytest.mark.parametrize("taxable", [False, None])
def test_y5_taxable_not_true_is_tax_unknown(taxable):
    # Y5: priceLabel.taxable が true でない時は price_tax_unknown（false も null も）
    o = _parse(_hit(0, priceLabel__taxable=taxable))
    assert "price_tax_unknown" in o.mall_unconfirmed
    assert "price_options_unchecked" in o.mall_unconfirmed


def test_y5_taxable_true_has_no_tax_reason():
    assert "price_tax_unknown" not in _parse(_hit(0, priceLabel__taxable=True)).mall_unconfirmed


def test_y5_all_reasons_together():
    # Y5: 理由は重なる。中古・税抜表示の疑い・選択肢未確認の 3 語がちょうど 1 回ずつ（順序は問わない）
    o = _parse(_hit(0, condition="used", priceLabel__taxable=False))
    assert sorted(o.mall_unconfirmed) == ["condition_not_new", "price_options_unchecked", "price_tax_unknown"]


@pytest.mark.parametrize("i", range(7))
def test_y5_every_yahoo_candidate_has_price_options_unchecked(i):
    # Y5: 全 Yahoo 候補に price_options_unchecked（確認済みの定義を広げない＝Yahoo は今の情報では確認済みにならない）
    assert "price_options_unchecked" in _parse(_hit(i)).mall_unconfirmed


OK_URLS = [
    "https://store.shopping.yahoo.co.jp/colorfulbox/308409.html",
    "https://lohaco.yahoo.co.jp/store/h-lohaco/item/nw92584/",
]
REVIEW_URLS = [
    "https://store.shopping.yahoo.co.jp/colorfulbox/",                       # ストアのトップ（商品 URL でない）
    "https://lohaco.yahoo.co.jp/store/h-lohaco/",                            # ロハコのストアのトップ
    "https://shopping.yahoo.co.jp/search?p=%E3%82%AB%E3%82%A4%E3%83%AD",     # 検索画面
    "https://shopping.yahoo.co.jp/products/abc123",                          # 商品比較ページ
    "https://store.shopping.yahoo.co.jp.evil.example/seller/item.html",      # ホストの偽装
    "https://evil.example/store.shopping.yahoo.co.jp/seller/item.html",      # パスに紛れ込ませる
    "https://store.shopping.yahoo.co.jp@evil.example/seller/item.html",      # userinfo の偽装
    "http://store.shopping.yahoo.co.jp/seller/item.html",                    # https でない
    "https://item.rakuten.co.jp/shop/item/",                                 # 他モールの URL
]


@pytest.mark.parametrize("url", OK_URLS)
def test_y5_item_url_ok(url):
    # Y5: store.shopping…/<seller>/<item>.html と lohaco の item URL は ok。URL は応答のまま
    assert is_item_url(url) is True
    o = _parse(_hit(0, url=url))
    assert o.item_url == url and o.item_url_status == "ok"


@pytest.mark.parametrize("url", REVIEW_URLS)
def test_y5_item_url_needs_review_but_kept(url):
    # Y5: それ以外は needs_review。捨てない・作らない・改変しない（item_url は応答のまま・候補は残る）
    assert is_item_url(url) is False
    o = _parse(_hit(0, url=url))
    assert o.item_url == url
    assert o.item_url_status == "needs_review"
    assert o.mall_item_code == "irisplaza_h264589"          # 候補として残っている


def test_y5_item_url_empty_is_not_item_url():
    assert is_item_url("") is False


def test_y5_caption_headline_first_then_description_text():
    # Y5: caption＝description の HTML を文字にした物（<br> を改行・他のタグを除去・実体参照を戻す）＋headLine を先頭に 1 行
    h = _hit(0, headLine="寒い季節に大活躍", description="内容量：60枚<br>素材/鉄粉<br>注意&amp;確認 <b>太字</b>&quot;引用&quot;")
    cap = _parse(h).caption
    assert cap is not None
    lines = cap.splitlines()
    assert lines[0] == "寒い季節に大活躍"
    assert "内容量：60枚" in lines and "素材/鉄粉" in lines            # <br> が改行になっている（別の行）
    assert "<br" not in cap and "<b>" not in cap and "</b>" not in cap
    assert "太字" in cap                                              # タグだけ除いて中身は残す
    assert "注意&確認" in cap and "&amp;" not in cap                  # 実体参照を戻す
    assert '"引用"' in cap and "&quot;" not in cap


def test_y5_review_and_availability_fields():
    # Y5: review.rate/count→review_average/count・inStock→availability（false も false のまま）
    o = _parse(_hit(0, inStock=False, review__rate=3.5, review__count=9))
    assert o.availability is False
    assert o.review_average == pytest.approx(3.5) and o.review_count == 9


def test_y5_hit_without_code_is_unexpected_response():
    # 固定するインターフェース: 読めない hit は AdapterError("unexpected_response")（code は必須）
    h = _hit(0)
    del h["code"]
    with pytest.raises(AdapterError) as ei:
        _parse(h)
    assert ei.value.kind == "unexpected_response"


@pytest.mark.parametrize("bad", [None, "x", 1, []], ids=["none", "str", "int", "list"])
def test_y5_non_dict_hit_is_unexpected_response(bad):
    with pytest.raises(AdapterError) as ei:
        parse_hit(bad, FETCHED)
    assert ei.value.kind == "unexpected_response"


def test_models_new_offer_fields_default():
    # 固定するインターフェース: Offer に mall_unconfirmed（既定 []）・points_amount・shipping_condition・condition（既定 None）。
    # 楽天の候補の出力 dict にもキーがある（値は None）
    o = make_offer("x1")
    assert o.mall_unconfirmed == [] and o.points_amount is None
    assert o.shipping_condition is None and o.condition is None
    assert make_offer("x2").mall_unconfirmed is not o.mall_unconfirmed       # 既定のリストを共有しない
    d = service.offer_to_dict(o)
    assert d["points_amount"] is None and d["shipping_condition"] is None and d["condition"] is None


# ==========================================================================
# 2. YahooAdapter.search（Y1〜Y4・Y8）と エラー（Y6）
# ==========================================================================

def test_y1_request_shape():
    # Y1: GET・appid=Client ID（クエリ）・エンドポイント。リダイレクト追従の無効化は実装側（ここでは見ない）
    ad, op = _adapter(_resp())
    ad.search("貼るカイロ")
    assert len(op.requests) == 1
    req = op.requests[0]
    assert req.get_method() == "GET"
    assert req.full_url.startswith(ENDPOINT + "?")
    q = _query(req)
    assert q["appid"] == [SECRET]
    assert "貼るカイロ" in sum(q.values(), [])                    # 検索語が（パラメータ名は契約外）クエリに入る


def test_search_returns_offers_and_api_count():
    # 実応答の totalResultsAvailable（76）が api_count。hit 7 件が Offer 7 件（契約は api_count の項目名を書いていない＝穴）
    ad, _ = _adapter(_resp())
    offers, count = ad.search("貼るカイロ")
    assert len(offers) == 7 and count == 76
    assert [o.mall_item_code for o in offers] == [r[1] for r in FIXTURE_ROWS]
    assert all(o.mall == "yahoo" for o in offers)


def test_search_empty_hits_is_valid():
    # 0 件は正常（Yahoo は hits=[] で返す）
    ad, _ = _adapter({"totalResultsAvailable": 0, "totalResultsReturned": 0, "firstResultsPosition": 1, "hits": []})
    offers, count = ad.search("ないもの")
    assert offers == [] and count == 0


def test_y5_unreadable_hit_is_dropped_not_fatal():
    # Y5: hit 単位で読めない物（code なし）は数えて捨て、応答全体は失敗にしない。他の 6 件は残る
    data = _resp()
    del data["hits"][2]["code"]
    ad, _ = _adapter(data)
    offers, _ = ad.search("貼るカイロ")
    assert [o.mall_item_code for o in offers] == [r[1] for r in FIXTURE_ROWS if r[0] != 2]


@pytest.mark.parametrize("body", [[], {}, {"hits": "x"}, {"hits": {"a": 1}}, "just a string"],
                         ids=["list", "no_hits", "hits_str", "hits_dict", "str"])
def test_y5_wrong_overall_shape_is_unexpected_response(body):
    # Y5: 応答全体の形が違う時だけ unexpected_response
    ad, op = _adapter(body)
    with pytest.raises(AdapterError) as ei:
        ad.search("貼るカイロ")
    assert ei.value.kind == "unexpected_response"
    assert len(op.requests) == 1


@pytest.mark.parametrize("page,start", [(1, "1"), (2, "51"), (3, "101")])
def test_y2_results_and_start(page, start):
    # Y2: 1 ページ＝results=50・start=(page-1)*50+1
    ad, op = _adapter(_resp())
    ad.search("貼るカイロ", page=page)
    q = _query(op.requests[0])
    assert q["results"] == ["50"] and q["start"] == [start]


@pytest.mark.parametrize("sort,expected", [
    ("standard", "-score"), ("+itemPrice", "+price"), ("-itemPrice", "-price"), ("-reviewCount", "-review_count"),
    ("+updateTimestamp", "-score"),                                  # 写像に無い値は -score
])
def test_y3_sort_mapping(sort, expected):
    # Y3: 公開の引数（楽天の値）を Yahoo の値へ写す。それ以外は -score（"+" は URL では %2B。parse_qs で戻して比べる）
    ad, op = _adapter(_resp())
    ad.search("貼るカイロ", sort=sort)
    assert _query(op.requests[0])["sort"] == [expected]


def test_y4_price_range_and_in_stock():
    # Y4: min_price/max_price→price_from/price_to・availability=1→in_stock=true
    ad, op = _adapter(_resp())
    ad.search("貼るカイロ", min_price=500, max_price=3000, availability=1)
    q = _query(op.requests[0])
    assert q["price_from"] == ["500"] and q["price_to"] == ["3000"] and q["in_stock"] == ["true"]


def test_y4_ng_keyword_is_applied_inside_adapter():
    # Y4: ng_keyword は Yahoo に引数が無いので、アダプタ内で商品名に除外語を含む候補を捨てる。api_count は API の値のまま。
    # fixture idx3（sofort_1897140）の商品名に「まとめ買い」がある
    data = _resp()
    assert "まとめ買い" in data["hits"][3]["name"] and not any("まとめ買い" in h["name"] for i, h in enumerate(data["hits"]) if i != 3)
    ad, _ = _adapter(data)
    offers, count = ad.search("貼るカイロ", ng_keyword="まとめ買い")
    assert [o.mall_item_code for o in offers] == [r[1] for r in FIXTURE_ROWS if r[0] != 3]
    assert count == 76


def test_y5_clock_makes_jst_fetched_at():
    from datetime import datetime, timedelta, timezone
    jst = timezone(timedelta(hours=9))
    op = FakeOpener(_resp())
    ad = YahooAdapter(SECRET, opener=op, clock=lambda: datetime(2026, 11, 24, 10, 0, 0, tzinfo=jst))
    offers, _ = ad.search("貼るカイロ")
    assert all(o.fetched_at == "2026-11-24T10:00:00+09:00" for o in offers)


@pytest.mark.parametrize("code,kind", [
    (400, "bad_request"), (401, "forbidden"), (403, "forbidden"), (429, "rate_limited"),
    (500, "server_error"), (503, "server_error"),
])
def test_y6_http_status_kinds(code, kind):
    # Y6: 400→bad_request・401/403→forbidden・429→rate_limited・500/503→server_error（HTML の 500 本文でも）。
    # 例外・repr・str に appid・URL・本文が出ない。1 回で諦める（再試行しない）
    ad, op = _adapter(_http_err(code))
    with pytest.raises(AdapterError) as ei:
        ad.search("貼るカイロ")
    assert ei.value.kind == kind
    assert len(op.requests) == 1
    _no_leak(ei.value)


@pytest.mark.parametrize("exc", [
    TimeoutError("t " + SECRET),
    URLError(socket.timeout("t " + SECRET)),
], ids=["timeout", "urlerror_timeout"])
def test_y6_timeout(exc):
    ad, op = _adapter(exc)
    with pytest.raises(AdapterError) as ei:
        ad.search("貼るカイロ")
    assert ei.value.kind == "timeout"
    assert len(op.requests) == 1
    _no_leak(ei.value)


def test_y6_invalid_json():
    ad, op = _adapter(b"<html>Server Busy " + SECRET.encode() + b"</html>")
    with pytest.raises(AdapterError) as ei:
        ad.search("貼るカイロ")
    assert ei.value.kind == "invalid_json"
    _no_leak(ei.value)


def test_y6_adapter_error_never_carries_secret_in_any_kind():
    # Y6: どの種別でも kind だけを持つ（str(exc) == kind）
    for resp in (_http_err(403), _http_err(429), _http_err(503), TimeoutError(), b"nope"):
        ad, _ = _adapter(resp)
        with pytest.raises(AdapterError) as ei:
            ad.search("貼るカイロ")
        assert str(ei.value) == ei.value.kind
        _no_leak(ei.value)


@pytest.mark.parametrize("cid", ["abc\ndef", "abc\r", "abc def", "abc\tdef"], ids=["lf", "cr", "space", "tab"])
def test_y8_bad_client_id_is_not_sent(cid):
    # Y8: CR/LF・空白入りは invalid_credentials で呼ばない（HTTP ヘッダー・クエリへの混入を防ぐ）
    ad, op = _adapter(_resp(), client_id=cid)
    with pytest.raises(AdapterError) as ei:
        ad.search("貼るカイロ")
    assert ei.value.kind == "invalid_credentials"
    assert op.requests == []


def test_y8_repr_hides_client_id():
    ad = YahooAdapter(SECRET)
    assert SECRET not in repr(ad) and SECRET not in str(ad)


