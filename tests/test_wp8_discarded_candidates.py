# @owns WP8-1「採らなかった候補の検査」（SPEC §7 P0 の徹底）の機構ごとの自作確認。独立試験（ブラインド）の代わりではない
"""WP8-1: 題名に現れた「数字＋計量単位・数え語」のうち、読まずに捨てた物も P0 の候補に含める。
採用した総数・内容量と食い違えば low、同じ数なら言い直しなので high のまま。

機構（語のリストではなく、トークン化で候補から落ちる経路ごと）:
  M1 先頭に書かれた個数（【48本】）と、後ろの空白だけでつないだ鎖（48本 2ケース）で総数の候補が食い違う
  M2 「最大／最小」の後ろの量・個数（最大700g）は上限の記述で採らないが、採用した内容量・個数と食い違う
  M3 区切り（_ /）の後ろの択一（シングル_55m・1本/3本セット）と、直前の量に続くハイフンの範囲（500g-1kg）
  M4 直前の量・個数にそのまま続く数字（500ml24本・30m12Rダブル）を型番として黙って捨てない
  M5 計量値の付く先頭の「1<数え語>」や「から／以下／以内／未満／MAX」の後ろを黙って捨てず、択一・範囲の候補にする
     （1個 または 3個・1個〜3個・3個から・1kgから選べる・MAX1kg）
  退行固定: 「/」の後ろの 1<数え語>（480ml/1個）・後置の「1ケースN本入り」・「最大N回分」は従来どおり high
どの機構にも、各3件以上の別の言い回しを入れる。真値どおり high のまま残る形も同じ表で固定する。
"""
import pytest

from shopping.quantity import parse_quantity

LOW = {
    "M1": [
        "【24本】 炭酸水 500ml 24本 2ケース",
        "【12個】 洗剤 詰め替え 400ml 12個 3パック",
        "【30枚】 マスク 30枚 2パック",
        "【6缶】 ビール 350ml 6缶 4ケース",
    ],
    "M2": [
        "ナッツ 最大1kg 500g 小分け",
        "洗剤 最大2L 1L つめかえ",
        "ラップ 50m 最大100m",
        "コーヒー 200g 3袋 最大6袋",
        "水 500ml 24本 最大2ケース",
    ],
    "M3": [
        "洗剤 500ml 24本 ダブル_1L",
        "洗剤 500g 5袋 プレーン_1kg",
        "歯磨き粉 150g 2個/4個セット",
        "ハミガキ 100g 1本/2本/3本セット",
        "お米 5kg/10kg 選べる",
        "トイレットペーパー 12ロール 55m/30m",
        "ナッツ 500g-1kg 選べる",
        "お茶 500ml/24本入り",
        "洗剤 400ml 2個/1個",
        "洗剤 400ml 1個/3個/5個",
    ],
    "M5": [
        "歯磨き粉 150g 1個 または 3個 セット",
        "歯磨き粉 150g 1個 又は 3個",
        "洗剤 400ml 1個 or 2個",
        "歯磨き粉 150g 1本入り or 3本入り",
        "歯磨き粉 150g 1個〜3個",
        "歯磨き粉 150g 1個～3個",
        "洗剤 400ml 1個 もしくは 3個",
        "ナッツ 700g MAX 1kg",
        "ナッツ 500g 1kgから選べる",
        "洗剤 400ml 3個から",
        "歯磨き粉 150g 1本 3本 から選択",
        "ナッツ 700g MAX1kg",
        "ナッツ 500g 2kg以下",
        "洗剤 400ml 6個以内",
    ],
    "M4": [
        "水 500ml24本",
        "水 2L6本",
        "洗剤 200g5袋",
        "コアレス トイレットペーパー30m12Rダブル",
    ],
}

# 内容量・個数を複数の言い方で書いた（言い直し）形は、同じ数なので high のまま
HIGH = [
    ("トイレットペーパー 12ロール×4パック(48ロール)", 48, None),
    ("水 500ml×24本", 24, 500.0),
    ("水 24本 (500ml×24)", 24, 500.0),
    ("米 200g×5袋", 5, 200.0),
    ("水 500ml 24本", 24, 500.0),
    ("洗剤 500ml 12本入り 2ケース 12本入り", 24, 500.0),
    ("ティッシュ 5箱 ×12パック 60箱", 60, None),
    ("ナッツ 最大500g 500g", 1, 500.0),
    ("水 2L 6本 最大6本", 6, 2000.0),
    ("ケーブル USB-C 1m 2本セット", 2, 1.0),
    ("SH-12M ケーブル 3本セット 1m", 3, 1.0),
    ("お茶 500ml/本 24本", 24, 500.0),
    ("【選べるセット品】乾電池 単3 単4 40本セット", 40, None),
    # B1: 「/」の後ろの 1<数え語> は単位あたりの説明
    ("洗剤 詰替 480ml/1個 3個セット", 3, 480.0),
    ("お茶 500ml 24本入/1ケース", 24, 500.0),
    ("ビール 350ml 24缶/1ケース", 24, 350.0),
    ("コーヒー 200g/1袋 3袋セット", 3, 200.0),
    ("お米 5kg/1袋 2袋セット", 2, 5000.0),
    ("水 2L×6本/1ケース", 6, 2000.0),
    ("ゴミ袋 ラップ 30cm×50m/1本 3本", 3, 50.0),
    ("ティッシュ 150組×5箱/1パック", 750, None),
    ("サプリ 60粒/1袋 約30日分", 60, None),
    # B2: 空白でつないだ鎖の後ろの「1ケースN本入り」（単位あたりの説明）と、回分の上限
    ("水 500ml 24本 2ケース 1ケース24本入り", 48, 500.0),
    ("麦茶 600ml 24本 2ケース 1ケース24本入", 48, 600.0),
    ("ビール 350ml 24缶 2ケース 1ケース24缶入", 48, 350.0),
    ("水 500ml×24本 2ケース(48本) ※1ケース24本入り", 48, 500.0),
    ("プロテイン 1kg 最大33回分", 1, 1000.0),
    ("プロテイン 1kg 約33回分", 1, 1000.0),
    # B4: 先頭の 1<数え語> と後ろの個数のあいだに、択一の標識でない語（販促語・商品語）が挟まる
    ("洗剤 400ml 1個 送料無料 3個セット", 3, 400.0),
    ("洗剤 400ml 1本 詰め替え用 3本セット", 3, 400.0),
    ("歯磨き粉 150g 1本 日本製 3本セット", 3, 150.0),
    ("水 500ml 1本 ミネラル 24本", 24, 500.0),
    ("お茶 1本 500ml おいしい 24本入り ケース", 24, 500.0),
    ("トイレットペーパー 1ロール25m ダブル 12ロール入り 香りなし", 12, 25.0),
    ("トイレットペーパー 1ロール(25m) シングル 12ロール", 12, 25.0),
    # B5: 個数 1 の「から」は最小購入数
    ("洗剤 500ml 12個 1個から購入可", 12, 500.0),
    ("洗剤 500ml 12個 1本から注文OK", 12, 500.0),
    ("ティッシュ 150組 5箱 1箱から購入できます", 750, None),
    ("マスク 50枚 1箱から 送料無料", 50, None),
    # B6: max/min は語の一部（Climax・vitamin）や空白を挟む独立語（Pepsi MAX 500ml）では上限にしない。内容量を失わない
    ("Climax 100g 2個", 2, 100.0),
    ("マルチ vitamin 90粒 3袋", 270, None),
    ("Vitamin 500mg 120粒 2個", 240, 0.5),
    ("Pepsi MAX 500ml 24本", 24, 500.0),
    ("アミノ酸 MIN 100g 3袋", 3, 100.0),
    # 先頭の 1<数え語> が単位あたりの説明（計量値付き・直後に続く鎖）
    ("トイレットペーパー 1ロール30m 12ロール入り", 12, 30.0),
    ("トイレットペーパー 12ロール 1ロール30m", 12, 30.0),
    ("洗剤 400ml 1個 3個セット", 3, 400.0),
]


@pytest.mark.parametrize("mech,title", [(m, t) for m, ts in LOW.items() for t in ts])
def test_discarded_candidate_that_disagrees_with_the_adopted_value_is_low(mech, title):
    q = parse_quantity(title)
    assert q.confidence == "low", (mech, title, q)
    # WP16 U2a（SPEC Q14 改訂）: 内容量だけが決まらない low（content_ambiguous）は総数を残す。内容量・総量は null のまま
    assert q.measure_total is None and q.content_amount is None
    assert q.count_total is None or q.low_reason == "content_ambiguous"


@pytest.mark.parametrize("title,count,amount", HIGH)
def test_restated_or_unrelated_forms_stay_high(title, count, amount):
    q = parse_quantity(title)
    assert q.confidence == "high" and q.count_total == count and q.content_amount == amount, q


def test_each_mechanism_has_at_least_three_variants():
    assert all(len(v) >= 3 for v in LOW.values())


# 実題名 T1〜T7（E2E 80件・2026-11-06）。corpus/unseen4_patterns.py と同じ題名で、低信頼の向きを直接固定する
def test_e2e_real_titles_t1_to_t6_are_low_and_t7_stays_high():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).parent / "corpus" / "unseen4_patterns.py"
    spec = importlib.util.spec_from_file_location("unseen4", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    titles = [t for t, _ in mod.P]
    assert len(titles) == 7
    for t in titles[:6]:
        assert parse_quantity(t).confidence == "low", t
    q = parse_quantity(titles[6])
    assert q.confidence == "high" and q.count_total == 40
