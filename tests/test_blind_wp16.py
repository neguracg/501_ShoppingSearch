# @owns WP16 ブラインド試験（題名 low の出力 readings・low_reason〔AC21〕／low の読みの選択 U2b〔AC22〕／説明欄の各文の読み取りによる内容量の補完 U1〔AC23〕／抽出と採用の分離の不変条件〔AC24〕）
"""WP16 ブラインド試験（2026-11-22）。根拠は docs/SPEC.md の §7 冒頭（抽出と採用を分ける）・§7「題名 low の出力」・
§7 W4（各文の読み取り・U1・U2b・採らない案）、§8 Q7・Q16・Q20・Q21・Q22・Q24・「確認済み」、§10 (7)、
AC21〜AC24（と改訂された AC16・AC19）だけ。src の実装・実装担当の説明は見ない（plans/WP16 は背景として読んだ）。
実題名・説明欄・価格は録画（楽天 API の生応答）から文字列で埋め込み済み（実行時に data/ は読まない）。
期待値は SPEC の記述と手計算（式は各試験のコメント）。実装担当は読まない・編集しない。

入口: service.compare_offers / search_products（偽 Adapter。実 API・本番は使わない）、pricing.compare（Offer 直接）、
quantity.parse_quantity（QuantityInfo.low_reason・readings。SPEC §7 結果の項目名）、mcp_server.INSTRUCTIONS・tools/list、
Web（偽 Adapter の /compare）。数量の読み取り・補完・採用・価格比較は実物を通す（業務ロジックは再実装しない）。
新しい名前・キーの参照は各試験の中で起き、収集（import）は常に通る。

【未確定の契約一覧（SPEC が一意に決めていない。推測で期待値を作らず、緩い断定か保留にした。報告に再掲）】
 O1 S3 型の low（`米 12kg (5kg×2袋)`・`ソーラーパネル 200W×2枚 計500W`）が content_ambiguous か（同じ次元の内容量が食い違う＝字面は当たる／
    それ以外の出口にも読める）。→ 既存試験の「総数 null」は外し、「総数が残るなら low_reason=content_ambiguous」（Q14）だけを断定。
 O2 content_ambiguous・multiple_totals 以外の low_reason のコード名（実装で決める）→ 「空でない文字列」だけ。
 O3 readings.counts・contents の完全な中身と順（捨てた数〔P5 の 1セット 等〕を含むか）、caption_candidates の完全な集合・件数・重複
    → 含む（⊇）の断定だけ。
 O4 U2b の「説明欄の各文の個数」に、個数の無い文（内容量だけの文は既定 1個）が入るか → 個数の記述（数字＋数え語）のある文だけで構成。
 O5 U2b で説明欄の個数が readings.counts の複数に一致する時の挙動 → 試験しない（X4 型の題名は出口が定まらない）。
 O6 quantity_low・U1（measure_from_caption）の to_check の条件文の文言、Web・CLI の理由の文の語（Q24 の文は例示）→ 理由コードと「仮」・「説明欄」の語だけ。
 O7 yumenokoya 型の low の readings.counts に 48ロール 以外（1セット 等）が入るか → 48ロール を含むことだけ。
 O8 caption_candidates の count_total（例: onestep の 50m の文の 12 ロール）→ content_amount・content_dimension・evidence だけ断定。
 O9 U1 の採用前の候補（(iii) 前）を caption_quantity が単体で持つか（read_offer_quantity の出力）→ 単体では試験せず、(iii) の成否の振る舞いで見る。
 O10 CLI の表示（Q24）→ 試験しない。
"""
from __future__ import annotations

import pytest

from fakes import FakeAdapter, make_offer
from shopping import service

NOSLEEP = lambda s: None  # noqa: E731


# --------------------------------------------------------------------------
# 録画の実例（楽天 API の生応答から。data/wp16/store.json）
# --------------------------------------------------------------------------

FUJI_CODE = "f222101-fuji:10001780"
FUJI_NAME = "【ふるさと納税】 スコッティ フラワーパック トイレットペーパー シングル 2倍巻き 12ロール×4パック 計48ロール 芳香 くつろぎの花の香り エンボス加工 ふんわりキープ長巻製法 取替の手間軽減 備蓄 ローリングストック 消耗品 生活用品 生活必需品 富士市 [sf087-007]"
FUJI_CAP = "たっぷり使えて取替の手間を軽減。シングル。 自社独自のふんわりキープ長巻製法による長持ちロール（特許取得）。 くつろぎの花の香りつき。 ■注意事項 ※沖縄および離島へのお届けはできません。 商品説明 名称 スコッティフラワーパック2倍長持ち12ロール（シングル）×4パック 内容 内容量：48ロール(12ロール ×4パック) 種　類：シングル 香り：芳香 ロールサイズ：108mm×100m 原材料：パルプ、紙パックリサイクルパルプ 配送方法 常温 提供元 日本製紙クレシア株式会社 ・ふるさと納税よくある質問はこちら ・寄附申込みのキャンセル、返礼品の変更・返品はできません。あらかじめご了承ください。 【地場産品に該当する理由】 当該返礼品は、区域内において「原料受け入れ、原紙製造、原紙加工、包装、品質管理」まで一連の工程を行っているため。（告示第5条第3号に該当）入金確認後、注文内容確認画面の【注文者情報】に記載のご住所に1週間以内を目途に、お礼の特産品とは別にお送りいたします。 ワンストップ特例申請書に関しましては【希望する】を選択されました方のみ同封させていただきます。"
FUJI_PRICE = 25000

ONESTEP_CODE = "onestep:10446085"
ONESTEP_NAME = "スコッティ フラワーパック 3倍長持ち シングル 48ロール(8ロール×6パック) クレシア『送料無料（一部地域除く）』"
ONESTEP_CAP = "150mの長さでたっぷり使えるトイレットペーパーです。メーカー独自の長巻製法とエンボス加工により、長持ちと柔らかさの両立を実現しました。たっぷり使えて取り替えの手間を軽減します。メーカー従来品と比べて3倍長持ち(※)です。※スコッティ フラワーパック 12ロール 50m シングルと比較。■商品詳細メーカー名：日本製紙クレシアシリーズ名：スコッティ入数：8ロール×6個ロールサイズ：108mm×150m香り：くつろぎの花の香り購入単位：1箱(6個)配送種別：在庫品※リニューアルに伴いパッケージや商品名等が予告なく変更される場合がございますが、予めご了承ください。※モニターの発色具合により色合いが異なる場合がございます。【検索用キーワード】4901750140106 3M9427 クレシア スコッティ フラワーパック 3倍長持ち シングル 8ロール×6個 3倍巻き 3倍巻きシングル 3倍巻シングル 150m トイレットペーパー トイレットロール 芯あり 香り付き くつろぎの花の香り くつろぎ 花の香り 花のかおり フラワーパックシングル トイレットペーパーシングル 3倍シングル 3倍巻きトイレットペーパー 3倍巻トイレットペーパー 3倍巻きペーパー 3倍巻ペーパー 3倍巻きトイレットロール 3倍巻トイレットロール 3倍巻きロール 3倍巻ロール"
ONESTEP_PRICE = 7260

OFFICETRUST_CODE = "officetrust:10053888"
OFFICETRUST_NAME = "スコッティ フラワーパック 3倍長持ち シングル 48ロール(8ロール×6パック) クレシア『送料無料（一部地域除く）』"
OFFICETRUST_CAP = "【必ずお読みください】お届け先の氏名に必ず法人名・屋号を記載ください。なお個人のお客様でもお届け先の氏名が法人名であればご注文いただけます。誤ってお届け先の氏名を個人名でご注文いただいた場合は、キャンセルさせていただきますのでご了承ください。150mの長さでたっぷり使えるトイレットペーパーです。メーカー独自の長巻製法とエンボス加工により、長持ちと柔らかさの両立を実現しました。たっぷり使えて取り替えの手間を軽減します。メーカー従来品と比べて3倍長持ち(※)です。※スコッティ フラワーパック 12ロール 50m シングルと比較。■商品詳細メーカー名：日本製紙クレシアシリーズ名：スコッティ入数：8ロール×6個ロールサイズ：108mm×150m香り：くつろぎの花の香り購入単位：1箱(6個)配送種別：在庫品※リニューアルに伴いパッケージや商品名等が予告なく変更される場合がございますが、予めご了承ください。※モニターの発色具合により色合いが異なる場合がございます。【検索用キーワード】4901750140106 3M9427 クレシア スコッティ フラワーパック 3倍長持ち シングル 8ロール×6個 3倍巻き 3倍巻きシングル 3倍巻シングル 150m トイレットペーパー トイレットロール 芯あり 香り付き くつろぎの花の香り くつろぎ 花の香り 花のかおり フラワーパックシングル トイレットペーパーシングル 3倍シングル 3倍巻きトイレットペーパー 3倍巻トイレットペーパー 3倍巻きペーパー 3倍巻ペーパー 3倍巻きトイレットロール 3倍巻トイレットロール 3倍巻きロール 3倍巻ロール"
OFFICETRUST_PRICE = 7128

EKURASHI_CODE = "e-kurashi:10041175"
EKURASHI_NAME = "スコッティ トイレットペーパー フラワーパック 3倍長持ち12ロール×4パック(48ロール) シングル/ダブル トイレットロール トイレ紙 トイレ用品 香り付き 3倍巻 日本製 国産 まとめ買い ケース販売 備蓄 新生活 日本製紙クレシア 【送料無料】"
EKURASHI_CAP = "日本製紙クレシア スコッティ トイレットペーパー フラワーパック 3倍長持ち12ロール×4パック(48ロール) シングル/ダブル ロールサイズ シングル：108mm×150mダブル：108mm×75m 材質 パルプ、紙パック等リサイクルパルプ 仕様 ●原産国：日本 商品説明 ●12ロールで36ロール分の長さ●たっぷり使えて取り替えの手間を削減●省スペース化で保管もスッキリ●くつろぎの花の香り付き●12ロール×4パックでのお届け※こちらの商品は、2024年9月24日よりシングルを追加しております※こちらの商品は、2024年11月5日より下記変更をしておりますダブル型番：22770→22778ダブルパッケージ変更 商品補足説明 YAMAZEN ヤマゼン 山善 通販 日本製紙クレシア クレシア スコッティ scottie トイレットペーパー トイレットロール トイレットティシュー トイレティッシュ 紙 シングル ダブル 香り付き 香りつき 3倍 3倍巻き 150m 75m 省スペース 備蓄 防災 新生活 日本製 国産 日用品 消耗品 トイレ用品 まとめ買い ケース販売 S6Z65(S6Z64*4) 96245(96235*4)スコッティ★スタンダード クリネックス★ハイクオリティ クリネックス最高グレード★プレミアム スコッティ★エコロジー商品 衛生用品 ランキング"
EKURASHI_PRICE = 6799

YUMENOKOYA_CODE = "yumenokoya:39998092"
YUMENOKOYA_NAME = "日本製 国産 紙 クレシア スコッティ 2倍巻きフラワーパック シングル 芯あり 100m 1セット（48ロール：12ロール×4パック） 環境に優しい紙パックリサイクルパルプを贅沢に使用した、上質な日本製フラワーパック 芯付きで100mの2倍巻きで、1セットには48ロール（12ロール"
YUMENOKOYA_CAP = "■その他のバリエーション●他のお色、仕様はこちらから■1パック（12ロール） 5セット●上記でお探しのものが見つからない場合はこちらからその他の「当シリーズ」その他の「関連商品」■商品について●リラックスできる花の香付きのシングルタイプ、12ロール×4パック。●取替えの手間が半分でたっぷり使える2倍巻。●省スペースで保管もスッキリ、12ロールで24ロール分。●通常の家庭用ホルダーが使えます。環境に優しい紙パックリサイクルパルプを贅沢に使用した、上質な日本製 国産 フラワーパック 芯付きで100mの2倍巻きで、1セットには48ロール（12ロール×4パック）が入っています 環境に優しい紙パックリサイクルパルプを贅沢に使用した、上質な日本製 国産 フラワーパック 芯付きで100mの2倍巻きで、1セットには48ロール（12ロール×4パック）が入っています■商品スペックタイプ：シングルロールサイズ：幅114mm×長さ100mミシン目：あり香り：あり芯：あり芯径：約38mm材質：パルプ+牛乳パックリサイクルパルプパッケージサイズ：W236×D236×H342mm生産国：日本シリーズ名：スコッティ◇カテゴリー： 生活用品＞インテリア＞雑貨＞日用雑貨＞トイレットペーパー　（キーワード： TCC351105 RDA0003550428 4492000 日用品 文房具 手芸用品 トイレ用品 トイレットペーパー 雑貨 手芸 日用消耗品 ティッシュ 環境に優しい紙パックリサイクルパルプを贅沢に使用した、上質な日本製 国産 フラワーパック 芯付きで100mの2倍巻きで、1セットには48ロール（12ロール×4パック）が入っています)※夢の小屋では売れ筋の人気日本製も激安 の特価でセール 中！ 便利 で機能的！ 耐久性も抜群、厳選した安全と信頼の日本製も格安 割引き！ 全品 低価格にて販売いたしておりますので是非ご覧下さい。環境に優しい紙パックリサイクルパルプを贅沢に使用した、上質な日本製 国産 フラワーパック 芯付きで100mの2倍巻きで、1セットには48ロール（12ロール×4パック）が入っています 日本製 国産 紙 クレシア スコッティ 2倍巻きフラワーパック シングル 芯あり 100m 1セット（48ロール：12ロール×4パック）品番：C15-0016065777■ご購入について●商品の引き当てはご決済順となりますため入れ違いで完売する事がございます。その際にはご返金にて対応させていただきますので、どうか予めご了承下さいませ。●送料無料の商品でございます。なお、沖縄県、離島地域は配送不可となります。（下記、商品説明にて上記への配送が不可の場合はお承りできません）●到着日時のご要望お承りいたします。発注時にご指定出来なかった方はご注文時の「コメント欄」、もしくは商品ページ内の 「お問い合わせ」 よりご要望下さい。本商品のご指定可能なお届け日は、ご注文からおよそ9営業日以降が目安(ご指定が無い場合は最短出荷)となります。また、ご指定可能なお届け時間帯は、午前中、12時〜14時、14時〜16時、16時〜18時、18時〜20時の何れかとなります。特に到着日時のご指定がない場合は最短での出荷となります。※日時指定は到着予定を保証するものではございません。交通状況や配送会社の都合によりご依頼通りに配送ができな場合がございます。●商品画像には、シリーズ商品の一例やセット内容のイメージ画像が含まれている場合がございます。カラー・サイズ・タイプ・セット内容等につきましては、お求めの商品と相違がないか、必ず下記の商品仕様をご確認ください。商品仕様： 日本製紙 クレシア スコッティ 2倍巻きフラワーパック シングル 芯あり 100m 1セット（48ロール：12ロール×4パック）●商品到着後7日以内の初期不良はメールにてご連絡下さい。確認次第、速やかに無償交換にて対応いたします。なお、こちらの商品は、ご注文後のキャンセル・内容変更、ならびに初期不良以外の交換・返品はお受けできません。ご注文の際は、内容を十分ご確認のうえお手続きくださいますようお願いいたします。◇カテゴリー： 生活用品＞インテリア＞雑貨＞日用雑貨＞トイレットペーパー　（キーワード： TCC351105 RDA0003550428 4492000 日用品 文房具 手芸用品 トイレ用品 トイレットペーパー 雑貨 手芸 日用消耗品 ティッシュ 環境に優しい紙パックリサイクルパルプを贅沢に使用した、上質な日本製 国産 フラワーパック 芯付きで100mの2倍巻きで、1セットには48ロール（12ロール×4パック）が入っています)※夢の小屋では売れ筋の人気日本製も激安 の特価でセール 中！ 便利 で機能的！ 耐久性も抜群、厳選した安全と信頼の日本製も格安 割引き！ 全品 低価格にて販売いたしておりますので是非ご覧下さい。"
YUMENOKOYA_PRICE = 9649

KURASHIKENKOU_CODE = "kurashikenkou:10192247"
KURASHIKENKOU_NAME = "＼ランキング1位獲得／【48個】トイレットペーパー ダブル 75m シングル 150m 3倍巻き 備蓄 防災 スコッティ フラワーパック 12ロール×4パック 4ロール×12パック フラワーボックス ちり紙 トイレ クレシア[G0]"
KURASHIKENKOU_CAP = "※2024年8/5 シングル4ロール×12パックが追加になりました ※2026年8/27 シングル12ロール×4パックが追加になりました ※こちらの商品は、予告無くパッケージデザインが変更になる場合がございます。あらかじめご了承のうえ、お買い求めください。 《ダブル4個セット》 12ロールで36ロール分の長さ！※スコッティフラワー12ロールダブルと比較して、1ロールの長さが3倍 たっぷり使えて取り替えの手間が減り、収納もコンパクト クレシア独自の凹凸加工でやわらかく、コンパクトな超長尺トイレットロール 家庭用ホルダー適応サイズ 温水洗浄器でも気持ちよく使っていただけます。 蛍光染料は不使用 ほのかな花の香りつき ●1パック75m12ロール入×4パック ●素材パルプ+紙パック 《ダブル12個セット》 4ロールで12ロール分の長さ！※スコッティフラワー12ロールダブルと比較して、1ロールの長さが3倍 たっぷり使えて取り替えの手間が減り、収納もコンパクト クレシア独自の凹凸加工でやわらかく、コンパクトな超長尺トイレットロール 家庭用ホルダー適応サイズ 温水洗浄器でも気持ちよく使っていただけます。 蛍光染料は不使用 ほのかな花の香りつき ●1パック75m4ロール入×12パック ●素材パルプ+紙パック 《シングル4個セット》 12ロールで36ロール分の長さ（※当社製品比）のトイレットペーパー。1ロールで3ロール分だから、取り替えの手間が減り、収納スペースも1/3にに収まります。クレシア独自のエンボス加工でやわらかく、コンパクトな長尺トイレットロール。ロール幅108mmのエコサイズ＆紙パック等を原料とした高品質パルプも一部使用しており、環境にやさしい商品です。家庭用ホルダー適応サイズ。くつろぎの花の香り付き。 ●1パック150m12ロール入×4パック ●ロール幅 108mm ●素材パルプ+紙パック 《シングル12個セット》4ロールで12ロール分の長さ（※メーカー製品比）のトイレットペーパー。1ロールで3ロール分だから、取り替えの手間が減り、収納スペースも1/3にに収まります。クレシア独自のエンボス加工でやわらかく、コンパクトな長尺トイレットロール。ロール幅108mmのエコサイズ＆紙パック等を原料とした高品質パルプも一部使用しており、環境にやさしい商品です。家庭用ホルダー適応サイズ。くつろぎの花の香り付き。 ●1パック150m4ロール入×12パック ●ロール幅 108mm ●素材パルプ+紙パック ※予告なくリニューアルとなる場合があり、こちらに掲載の情報がパッケージデザイン含め実際の商品と一部異なる場合がございます。予めご了承の上ご注文を頂きますようお願い致します。 消耗品もまとめ買い1 最強翌日配送対象商品に関するご案内 最強翌日配送対象商品・対象地域に該当する場合は最強翌日配送マークがご注文カゴ近くに表示されます。 最強翌日配送可能なお支払方法は【クレジットカード、代金引換、全額ポイント支払い】のみとなります。 下記の場合は最強翌日配送対象外となります。 ・15点以上ご購入いただいた場合 ・時間指定がある場合 ・ご注文時備考欄にご記入がある場合 ・決済処理にお時間を頂戴する場合 ・郵便番号や住所に誤りがある場合 ・最強翌日配送対象外の商品とご一緒にご注文いただいた場合 ・お届け先住所文字数が40文字以上の場合 【48個】トイレットペーパー ダブル トイレットペーパー 3倍巻き トイレットペーパー 送料無料 トイレットペーパー スコッティ トイレットペーパー 3倍巻 トイレットペーパー フラワーパック トイレットペーパー 75m×12ロール トイレットペーパー 4個セット トイレットペーパー スコッティ トイレットペーパー フラワーボックス トイレットペーパー ちり紙 トイレットペーパー トイレ用品 トイレットペーパー 消耗品 トイレットペーパー クレシア トイレットペーパー (検索用： トイレットペーパー トイレットペーパー スコッティ トイレットペーパー ダブル トイレットペーパー 3倍巻き トイレットペーパー 大容量 トイレットペーパー シングル トイレットペーパー 香り付き トイレットペーパー 長持ち トイレットペーパー まとめ買い トイレットペーパー ) 関連キーワード(本商品の説明ではありません) 母の日 父の日 敬老の日 こどもの日 クリスマス バレンタイン ホワイトデー ハロウィン お正月 成人の日 成人式 記念日 誕生日 卒業式 入学式 お歳暮 お中元 春 夏 秋 冬 梅雨 節分 ひな祭り 七夕 十五夜 初詣 年越し 夏祭り 花火大会 結婚祝い 内祝い 出産祝い 快気祝い 還暦祝い 古希 喜寿 傘寿 米寿 卒寿 白寿 百寿 新築祝い 引っ越し祝い 開店祝い 開業祝い 就職祝い 昇進祝い 合格祝い 銀婚式 金婚式 七五三 長寿祝い 御礼 お母さん お父さん 義母 義父 祖父 祖母 おばあちゃん おじいちゃん 娘 息子 彼氏 彼女 恋人 友達 上司 先輩 後輩 同僚 キッズ 子供 幼児 ベビー 赤ちゃん 育児 学生 社会人 シニア 10代 20代 30代 40代 50代 60代 70代 80代 90代 一人暮らし 単身赴任 主婦 主夫 新生活 家族暮らし 子育て 旅行 トラベル ライブ ホームパーティ ビジネス 法人 ギフト プレゼント【置き配規約について】 ＼大容量で超丈夫！／▼▼コストコでも人気商品はコチラ▼ ＼一緒に購入いかがですか？／ ★洗浄力・消臭力重視★ ★時短重視★ ＼人気ティッシュがパッケージリニューアル／持ち運べるサイズもあって便利です♪ 【新発売！】まるで下着！？\"超薄型＆スピード吸収\"大人用紙おむつ ＼こちらもオススメ！／新商品の拭けるトイレマット★ ＼まだまだあります／ 日用消耗品をもっと見たい人はこちら！"
KURASHIKENKOU_PRICE = 5845



# onestep と officetrust は題名が同一（店だけ違う）。候補の取り違えを避けるため、試験に渡す題名の末尾に店の記号を付ける
# （題名の読み取りには影響しない末尾の1語）
ONE_N = ONESTEP_NAME + " 店A"
OFFI_N = OFFICETRUST_NAME + " 店B"


# --------------------------------------------------------------------------
# 部品
# --------------------------------------------------------------------------

def _cmp(offers, **kw):
    ad = FakeAdapter({("aa", 1): (offers, len(offers))})
    r = service.compare_offers(["aa"], adapter=ad, sleep=NOSLEEP, **kw)
    assert r["ok"], r
    return r["comparison"], r


def _search(offers):
    ad = FakeAdapter({("aa", 1): (offers, len(offers))})
    r = service.search_products(["aa"], adapter=ad, sleep=NOSLEEP)
    assert r["ok"], r
    return r


def _o(code, name, price, ship="included", **kw):
    return make_offer(code, name, price, shipping_status=ship, **kw)


def _offers_of(c):
    return [o for g in c["groups"] for o in g["offers"]] + list(c["unknown_offers"])


def _by_name(c, name):
    for o in _offers_of(c):
        if o["name"] == name:
            return o
    raise AssertionError(f"{name!r} が候補に無い: {[o['name'] for o in _offers_of(c)]}")


def _q(c, name):
    return _by_name(c, name)["quantity"]


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


def _creasons(p):
    return {r for x in p["conditions"] for r in x["reasons"]}


def _ctext(p):
    return " ".join(x["text"] for x in p["conditions"]).replace(",", "")


def _unknown_names(c):
    return [o["name"] for o in c["unknown_offers"]]


def _selected_names(c):
    """数量を使う最安（確認済みだけが選ばれる枠）に選ばれている候補名。"""
    names = set()
    for slot in ("cheapest_unit_price", "cheapest_for_quantity", "cheapest_order"):
        d = c.get(slot)
        if d:
            names.add(d["name"])
    for g in c["groups"]:
        for slot in ("cheapest_unit_price", "cheapest_order"):
            d = g.get(slot)
            if d:
                names.add(d["name"])
    return names


def _scan(result):
    # AC17・AC18 の走査（WP15 の部品。UNIT_REASONS に quantity_low を足した版）
    from test_blind_wp15 import _scan as scan

    return scan(result)


def _conf(q):
    c = q.confidence
    return getattr(c, "value", c)


def _parse(text):
    from shopping.quantity import parse_quantity

    return parse_quantity(text)


def _count_set(readings):
    return {(c["count"], c["count_unit"]) for c in readings["counts"]}


def _amounts(q):
    """caption_candidates の内容量（基準単位）の集合。"""
    return {x["content_amount"] for x in q["caption_candidates"] if x.get("content_amount") is not None}


def _has_amount(q, v):
    return any(abs(a - v) < 1e-9 for a in _amounts(q))


ROLL = "トイレットペーパー 12ロール×4パック"        # 題名: 48ロール・high・個数だけ
ROLL_M = "トイレットペーパー 75m×12ロール"          # 題名由来の内容量 75m（12ロール・900m）


def _tname(i):
    return f"{ROLL_M} T{i}店"


def _tgroup(n=4):
    """題名由来（source=title・high）の長さが 75m の候補 n 件（中央値 75m。価格は 1510, 1520, …）。"""
    return [_o(f"t{i}", _tname(i), 1500 + 10 * i) for i in range(1, n + 1)]


def _fuji(**kw):
    return _o(FUJI_CODE, FUJI_NAME, FUJI_PRICE, caption=FUJI_CAP, **kw)


def _one(**kw):
    return _o(ONESTEP_CODE, ONE_N, ONESTEP_PRICE, caption=ONESTEP_CAP, **kw)


def _offi(**kw):
    return _o(OFFICETRUST_CODE, OFFI_N, OFFICETRUST_PRICE, caption=OFFICETRUST_CAP, **kw)


def _ekura(**kw):
    return _o(EKURASHI_CODE, EKURASHI_NAME, EKURASHI_PRICE, caption=EKURASHI_CAP, **kw)


def _yume(**kw):
    kw.setdefault("caption", YUMENOKOYA_CAP)
    price = kw.pop("price", YUMENOKOYA_PRICE)
    return _o(YUMENOKOYA_CODE, YUMENOKOYA_NAME, price, **kw)


def _kura(price_varies=True, caption=True):
    # 録画: itemPriceMin1=5845・itemPriceMax1=6650（price_varies）。price_varies=False・caption=False は U2a だけを見る構成
    kw = dict(price_min=5845, price_max=6650) if price_varies else {}
    return _o(KURASHIKENKOU_CODE, KURASHIKENKOU_NAME, KURASHIKENKOU_PRICE,
              caption=KURASHIKENKOU_CAP if caption else None, **kw)


# --------------------------------------------------------------------------
# 前提（固定の時点で変更前の製品でも通る。入力の題名が SPEC の想定どおりの読みになることの確認）
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    [FUJI_NAME, ONESTEP_NAME, OFFICETRUST_NAME, EKURASHI_NAME],
    ids=["fuji", "onestep", "officetrust", "ekurashi"],
)
def test_precondition_named_titles_are_count_only_high_48(name):
    # SPEC §7 W4 の名指し: 題名は 48ロール・high・個数だけ（U1 の対象）。題名の読み取りは WP16 で変わらない
    q = _parse(name)
    assert _conf(q) == "high" and q.count_total == 48 and q.count_unit == "ロール"
    assert q.content_amount is None and q.measure_total is None


def test_precondition_group_titles_are_title_derived_75m():
    # §7 W4 (iii): 題名由来の長さ 75m（12ロール・900m）。中央値の分母になる候補
    q = _parse(_tname(1))
    assert _conf(q) == "high" and q.count_total == 12 and q.content_amount == pytest.approx(75)
    assert q.content_dimension == "length" and q.measure_total == pytest.approx(900)


def test_precondition_yumenokoya_and_kurashikenkou_titles_are_low():
    # §7 題名 low の出力: yumenokoya（P5 の捨てた 1セット と 48 の食い違い）・kurashikenkou（内容量 75m/150m の食い違い）は low
    for n in (YUMENOKOYA_NAME, KURASHIKENKOU_NAME):
        assert _conf(_parse(n)) == "low", n


# --------------------------------------------------------------------------
# AC21 題名 low の出力（§7「題名 low の出力」・Q14 の改訂）
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,counts",
    [
        ("トイレットペーパー 12ロール 18ロール", {(12, "ロール"), (18, "ロール")}),   # SPEC の例（multiple_totals）
        ("単3電池 40本 48本", {(40, "本"), (48, "本")}),                               # SPEC の例（multiple_totals）
    ],
    ids=["rolls", "batteries"],
)
def test_ac21_multiple_totals_keeps_total_null_and_exposes_readings(text, counts):
    # AC21・§7: 総数が複数（言い直し・捨てた数の処理の後に残った個数の群が2通り以上）→ low_reason=multiple_totals。
    # 総数・内容量は null のまま（U2a の対象外）。readings.counts に両方の読み。confidence は low のまま。
    q = _parse(text)
    assert _conf(q) == "low"
    assert q.low_reason == "multiple_totals"
    assert q.count_total is None and q.content_amount is None and q.measure_total is None
    assert q.content_dimension is None and q.content_unit is None
    assert counts <= _count_set(q.readings)


@pytest.mark.parametrize(
    "text,count,unit,dim,contents",
    [
        ("飲料 500ml 2L ×6本", 6, "本", "volume", [500.0, 2000.0]),                 # 旧 CONFLICT_CASES（U2a で総数を残す）
        ("洗濯洗剤 詰め替え 900g 1000g ×3袋", 3, "袋", "mass", [900.0, 1000.0]),    # 旧 CONFLICT_CASES（U2a で総数を残す）
        (KURASHIKENKOU_NAME, 48, "ロール", "length", [75.0, 150.0]),                 # SPEC の名指し（kurashikenkou:10192247）
    ],
    ids=["beverage", "detergent", "kurashikenkou"],
)
def test_ac21_content_ambiguous_keeps_total_and_nulls_content(text, count, unit, dim, contents):
    # AC21・Q14（改訂）・U2a: 総数が1通りに決まり内容量だけ決まらない（同じ次元の内容量が食い違う）→
    # low_reason=content_ambiguous。総数・数え語を残し、内容量（content_amount・content_dimension・content_unit・
    # measure_total・content_amounts）は null。内容量の候補は readings.contents。confidence は low のまま。
    q = _parse(text)
    assert _conf(q) == "low"
    assert q.low_reason == "content_ambiguous"
    assert q.count_total == count and q.count_unit == unit
    assert q.content_amount is None and q.content_dimension is None and q.content_unit is None
    assert q.measure_total is None and not q.content_amounts
    assert (count, unit) in _count_set(q.readings)
    assert sorted(q.readings["contents"][dim]) == contents


S3_MISMATCH = ["米 12kg (5kg×2袋)", "ソーラーパネル 200W×2枚 計500W", "ドッグフード 8kg(2.5kg×3袋)"]


@pytest.mark.parametrize("text", S3_MISMATCH, ids=["rice", "panel", "dogfood"])
def test_ac21_s3_mismatch_total_is_low_with_content_null(text):
    # S3 の食い違い（総量が個数×小さい方と合わない）は low のまま。内容量・総量は null。
    # 総数が残るのは low_reason=content_ambiguous の時だけ（Q14 改訂）。content_ambiguous か否かは SPEC が決めていない（O1）ので
    # 総数 null は断定しない。low の時は readings・low_reason を必ず出す。
    q = _parse(text)
    assert _conf(q) == "low", text
    assert q.content_amount is None and q.measure_total is None and q.content_dimension is None
    assert isinstance(q.low_reason, str) and q.low_reason
    assert q.readings is not None and "counts" in q.readings and "contents" in q.readings
    if q.count_total is not None:
        assert q.low_reason == "content_ambiguous", text


OTHER_EXIT_LOWS = [
    "洗濯洗剤 900g×6ブロック",                    # S4・P7 未知の数え語
    "石鹸 4ブロック×6個",
    "ウェブカメラ 60P", "ティッシュ 12P",         # X1 単独の NP
    "単3電池 40本 60P",                            # P0（単独の NP と他の個数の食い違い）
    "トイレットペーパー 12ロール×4パック 5冊",     # X3
    "ゼリー 3個入り 3冊",                          # X4
    "素材 1234567890g×2個",                        # S6 桁の上限
    YUMENOKOYA_NAME,                               # P5 の捨てた数（1セット）と 48 の食い違い（SPEC AC22 の例）
]


@pytest.mark.parametrize("text", OTHER_EXIT_LOWS)
def test_ac21_other_low_exits_null_total_and_content_but_have_readings_and_reason(text):
    # AC21: content_ambiguous 以外の low は、題名の読み取りとしては総数・内容量とも null。readings と low_reason
    # （出口ごとのコード。名前は実装で決める＝空でない文字列だけ断定。O2）は常に出す。confidence は low のまま。
    q = _parse(text)
    assert _conf(q) == "low", text
    assert q.count_total is None and q.content_amount is None and q.measure_total is None, text
    assert isinstance(q.low_reason, str) and q.low_reason, text
    assert q.low_reason != "content_ambiguous", text
    assert q.readings is not None and isinstance(q.readings["counts"], list) and isinstance(q.readings["contents"], dict)


def test_ac21_yumenokoya_title_is_not_multiple_totals_and_readings_contain_48_rolls():
    # §7 U2b・AC22: yumenokoya は P5 の出口で multiple_totals ではない（U2b の対象）。readings.counts に 48ロール（O7: 他の読みは断定しない）。
    q = _parse(YUMENOKOYA_NAME)
    assert q.low_reason != "multiple_totals"
    assert (48, "ロール") in _count_set(q.readings)


@pytest.mark.parametrize("text", ["天然水 2L×6本", "洗濯洗剤 900g×6袋", "貼るカイロ 60枚", "おすすめ商品", "量の分からない商品"])
def test_ac21_non_low_has_null_readings_and_reason(text):
    # AC21: low 以外（high・none）は readings・low_reason とも null
    q = _parse(text)
    assert _conf(q) in ("high", "none")
    assert q.readings is None and q.low_reason is None


def test_ac21_search_products_exposes_readings_reason_and_candidates_keys():
    # AC21・§7: search_products の quantity に readings・low_reason・caption_candidates（キーは常に出す。無い時は [] ／ low 以外は
    # readings・low_reason が null）。content_ambiguous は総数・数え語を残し内容量 null・confidence/title_confidence は low。
    names = {"high": "天然水 2L×6本", "none": "おすすめ商品", "multi": "単3電池 40本 48本", "ambig": "飲料 500ml 2L ×6本"}
    r = _search([_o(k, v, 1000) for k, v in names.items()])
    by = {o["name"]: o["quantity"] for o in r["offers"]}
    for n, q in by.items():
        for k in ("readings", "low_reason", "caption_candidates"):
            assert k in q, (n, k)
        assert q["caption_candidates"] == [], n
    for k in ("high", "none"):
        assert by[names[k]]["readings"] is None and by[names[k]]["low_reason"] is None
    m = by[names["multi"]]
    assert m["confidence"] == "low" and m["title_confidence"] == "low" and m["low_reason"] == "multiple_totals"
    assert m["count_total"] is None and (40, "本") in _count_set(m["readings"])
    a = by[names["ambig"]]
    assert a["confidence"] == "low" and a["title_confidence"] == "low" and a["low_reason"] == "content_ambiguous"
    assert a["count_total"] == 6 and a["count_unit"] == "本"
    assert a["content_amount"] is None and a["measure_total"] is None
    assert sorted(a["readings"]["contents"]["volume"]) == [500.0, 2000.0]


def test_ac21_kurashikenkou_real_keeps_48_rolls_content_null_price_varies_provisional():
    # AC21・U2a・名指し: kurashikenkou:10192247（price_varies でもある）は 48ロールを残し内容量 null（readings.contents に 75m・150m）。
    # confidence/title_confidence は low のまま。basis=ロール: 仮の単価（5845÷48=121.77。未確定理由 quantity_low と price_varies）。
    # 価格が選択肢で変わる候補は説明欄を使わない（U2b 対象外）ので source は title+caption にならない。
    c, r = _cmp(_tgroup() + [_kura()], basis="ロール")
    o = _by_name(c, KURASHIKENKOU_NAME)
    q = o["quantity"]
    assert o["price_varies"] is True and o["price_min"] == 5845 and o["price_max"] == 6650
    assert q["count_total"] == 48 and q["count_unit"] == "ロール"
    assert q["content_amount"] is None and q["content_dimension"] is None and q["measure_total"] is None
    assert q["confidence"] == "low" and q["title_confidence"] == "low" and q["low_reason"] == "content_ambiguous"
    assert sorted(q["readings"]["contents"]["length"]) == [75.0, 150.0]
    assert q["source"] != "title+caption"
    assert o["unit_price"] is None and o["provisional_unit_price"] == pytest.approx(5845 / 48, abs=0.01)
    assert o["unit_price_status"] == "unconfirmed"
    assert set(o["unit_price_unconfirmed_reasons"]) == {"quantity_low", "price_varies"}
    assert KURASHIKENKOU_NAME in [x["name"] for g in c["groups"] for x in g["offers"]]
    assert KURASHIKENKOU_NAME not in _selected_names(c)
    _scan(r)


def test_ac21_u2a_pure_provisional_price_by_count_basis_and_unknown_by_content_basis():
    # AC21・U2a: 題名 low（content_ambiguous）・価格幅なし・説明欄なしの構成（kurashikenkou の題名・価格 5845）。
    # basis=ロール・個: 仮の単価（5845÷48=121.77。理由は quantity_low だけ）。confidence は low のまま。
    # basis=m（内容量の次元）: 量が決まらないので単価不明のまま（unknown_offers・単価は全部 null）。
    for basis in ("ロール", "個"):
        c, r = _cmp(_tgroup() + [_kura(price_varies=False, caption=False)], basis=basis)
        o = _by_name(c, KURASHIKENKOU_NAME)
        assert o["unit_price"] is None and o["provisional_unit_price"] == pytest.approx(5845 / 48, abs=0.01), basis
        assert o["unit_price_status"] == "unconfirmed" and list(o["unit_price_unconfirmed_reasons"]) == ["quantity_low"], basis
        assert o["quantity"]["confidence"] == "low" and o["quantity"]["title_confidence"] == "low", basis
        assert KURASHIKENKOU_NAME not in _unknown_names(c), basis
        assert KURASHIKENKOU_NAME not in _selected_names(c), basis
        _scan(r)
    c, r = _cmp(_tgroup() + [_kura(price_varies=False, caption=False)], basis="m")
    o = _by_name(c, KURASHIKENKOU_NAME)
    assert KURASHIKENKOU_NAME in _unknown_names(c)
    assert o["unit_price"] is None and o["provisional_unit_price"] is None and o["unit_price_status"] == "unknown"
    assert o["quantity"]["content_amount"] is None
    _scan(r)


def test_ac21_u2a_order_goes_to_to_check_never_cheapest_order():
    # AC21・規律8・Q16: basis=ロール・desired=48。T は n=48÷12=4 → 4×1510=6040（最安の確認済み＝T1）。
    # kurashikenkou（U2a の仮の数量 48ロール）は n=1・5845円・注文の単価 5845÷48=121.77（仮）で T より安い →
    # cheapest_order に選ばれず to_check に出る（quantity_low）。注文額の種類は送料込みで単価が未確定 → unconfirmed_total。
    c, r = _cmp(_tgroup() + [_kura(price_varies=False, caption=False)], basis="ロール", desired_quantity=48)
    assert c["cheapest_order"]["name"] == _tname(1) and c["cheapest_order"]["order_total"] == 6040
    p = _plan(c, KURASHIKENKOU_NAME)
    assert p["n"] == 1 and p["order_total"] == 5845
    assert p["confirmed"] is False and "quantity_low" in p["unconfirmed_reasons"]
    assert p["order_unit_price"] is None and p["provisional_order_unit_price"] == pytest.approx(5845 / 48, abs=0.01)
    assert p["unit_price_status"] == "unconfirmed" and p["payment_total"] is None and p["order_total_kind"] == "unconfirmed_total"
    t = _tc(c, KURASHIKENKOU_NAME)
    assert "quantity_low" in _creasons(t)
    assert KURASHIKENKOU_NAME not in _selected_names(c)
    _scan(r)


# --------------------------------------------------------------------------
# AC22 low の読みの選択（U2b）
# --------------------------------------------------------------------------

def test_ac22_yumenokoya_real_is_48_rolls_100m_provisional_quantity_low():
    # AC22・U2b・名指し: yumenokoya:39998092（題名は low。説明欄に `12ロール×4パック`・`幅114mm×長さ100m`）→
    # 48ロール・100m（仮）。source="title+caption"・caption_evidence・confidence/title_confidence は low のまま。
    # measure_total=48×100=4800。basis=ロール: 9649÷48=201.02（仮）、basis=m: 9649÷4800=2.01（仮）。理由は quantity_low。
    c, r = _cmp(_tgroup() + [_yume()], basis="ロール")
    q = _q(c, YUMENOKOYA_NAME)
    assert q["count_total"] == 48 and q["count_unit"] == "ロール"
    assert q["content_amount"] == pytest.approx(100) and q["content_dimension"] == "length" and q["content_unit"] == "m"
    assert q["measure_total"] == pytest.approx(4800)
    assert q["source"] == "title+caption" and q["caption_evidence"]
    assert q["confidence"] == "low" and q["title_confidence"] == "low"
    o = _by_name(c, YUMENOKOYA_NAME)
    assert o["unit_price"] is None and o["provisional_unit_price"] == pytest.approx(9649 / 48, abs=0.01)
    assert o["unit_price_status"] == "unconfirmed" and "quantity_low" in o["unit_price_unconfirmed_reasons"]
    assert YUMENOKOYA_NAME not in _unknown_names(c)
    _scan(r)
    c, r = _cmp(_tgroup() + [_yume()], basis="m")
    o = _by_name(c, YUMENOKOYA_NAME)
    assert o["unit_price"] is None and o["provisional_unit_price"] == pytest.approx(9649 / 4800, abs=0.01)
    assert o["unit_price_status"] == "unconfirmed" and "quantity_low" in o["unit_price_unconfirmed_reasons"]
    assert o["unit_price_label"] == "1mあたり"
    _scan(r)


def test_ac22_yumenokoya_is_never_chosen_cheapest_even_when_cheapest():
    # AC22・規律8: 仮の数量の候補は最安でも cheapest_* に選ばれず、安ければ to_check に出る。
    # （価格だけ構成: 3000円。録画は 9649円で T より高い）basis=ロール・desired=48: yumenokoya n=1=3000円 < T1 n=4=6040円。
    # basis=m・desired=4800: yumenokoya n=1=3000円（4800m）< T1 n=ceil(4800÷900)=6 → 9060円。
    for basis, desired, t_total in (("ロール", 48, 6040), ("m", 4800, 9060)):
        c, r = _cmp(_tgroup() + [_yume(price=3000)], basis=basis, desired_quantity=desired)
        assert c["cheapest_order"]["name"] == _tname(1) and c["cheapest_order"]["order_total"] == t_total, basis
        p = _plan(c, YUMENOKOYA_NAME)
        assert p["n"] == 1 and p["order_total"] == 3000 and p["confirmed"] is False, basis
        assert "quantity_low" in p["unconfirmed_reasons"], basis
        assert "quantity_low" in _creasons(_tc(c, YUMENOKOYA_NAME)), basis
        assert YUMENOKOYA_NAME not in _selected_names(c), basis
        if basis == "m":
            assert c["cheapest_unit_price"]["name"] == _tname(1)          # 仮の 0.625円/m（3000÷4800）の方が安いが選ばれない
        _scan(r)


def test_ac22_not_applied_when_price_varies():
    # AC22: price_varies の候補（録画の価格を選択肢つきに構成: 9649〜12000）には U2b を使わない。数量は低信頼のまま補わず、
    # 説明欄の値は caption_candidates に残る（100m の文）。
    c, r = _cmp(_tgroup() + [_yume(price_min=9649, price_max=12000)], basis="ロール")
    o = _by_name(c, YUMENOKOYA_NAME)
    q = o["quantity"]
    assert o["price_varies"] is True
    assert q["source"] != "title+caption" and q["count_total"] is None and q["content_amount"] is None
    assert YUMENOKOYA_NAME in _unknown_names(c)
    assert _has_amount(q, 100)
    _scan(r)


@pytest.mark.parametrize(
    "title,caption,count_in_caption",
    [
        ("トイレットペーパー 12ロール 18ロール", "■内容量：12ロール", (12, "ロール")),   # AC22 構成例（multiple_totals）
        ("単3電池 40本 48本", "■内容量：40本", (40, "本")),
    ],
    ids=["rolls", "batteries"],
)
def test_ac22_multiple_totals_title_is_not_completed_even_if_caption_matches_a_reading(title, caption, count_in_caption):
    # AC22・§7 U2b: low_reason=multiple_totals の題名は、説明欄の個数が readings.counts の1つと一致しても補わない。
    # 数量は null のまま（単価不明）、説明欄の値は caption_candidates に残る。
    c, r = _cmp([_o("m", title, 1200, caption=caption)])
    q = _q(c, title)
    assert q["confidence"] == "low" and q["low_reason"] == "multiple_totals"
    assert q["count_total"] is None and q["source"] != "title+caption"
    assert title in _unknown_names(c)
    assert any(x.get("count_total") == count_in_caption[0] and x.get("count_unit") == count_in_caption[1]
               for x in q["caption_candidates"])
    _scan(r)


def test_ac22_content_ambiguous_title_caption_count_mismatch_is_not_completed():
    # AC22: 読みと一致しない説明欄の個数（6本 に対して 24本）は補わず caption_candidates に残す。
    # 総数 6本 は題名の U2a のまま（24本にならない）・内容量は null。
    t = "飲料 500ml 2L ×6本"
    c, r = _cmp([_o("d", t, 1200, caption="■内容量：24本")])
    q = _q(c, t)
    assert q["count_total"] == 6 and q["count_unit"] == "本" and q["content_amount"] is None
    assert q["source"] != "title+caption"
    assert any(x.get("count_total") == 24 for x in q["caption_candidates"])
    _scan(r)


def test_ac22_content_ambiguous_title_caption_picks_content_when_exactly_one_matches():
    # AC22・U2b: content_ambiguous の題名（読み: 6本・volume 500/2000ml）で、説明欄の文 `500ml×6本` の個数が readings.counts の
    # ちょうど1つ（6本）と一致し、内容量 500ml が readings.contents.volume のちょうど1つと一致 → 500ml を仮に入れる。
    # measure_total=6×500=3000・source="title+caption"・caption_evidence・confidence は low のまま・理由 quantity_low。
    # basis=ml: 1200円÷3000ml×100=40.0（仮）、basis=本: 1200÷6=200（仮）。
    t = "飲料 500ml 2L ×6本"
    for basis, expect in (("ml", 40.0), ("本", 200.0)):
        c, r = _cmp([_o("d", t, 1200, caption="■内容量：500ml×6本")], basis=basis)
        o = _by_name(c, t)
        q = o["quantity"]
        assert q["count_total"] == 6 and q["count_unit"] == "本"
        assert q["content_amount"] == pytest.approx(500) and q["content_dimension"] == "volume"
        assert q["measure_total"] == pytest.approx(3000)
        assert q["source"] == "title+caption" and q["caption_evidence"]
        assert q["confidence"] == "low" and q["title_confidence"] == "low"
        assert o["unit_price"] is None and o["provisional_unit_price"] == pytest.approx(expect, abs=0.01), basis
        assert list(o["unit_price_unconfirmed_reasons"]) == ["quantity_low"], basis
        _scan(r)


def test_ac22_content_not_picked_when_caption_value_matches_no_reading():
    # AC22: 説明欄の内容量 200ml は readings.contents（500・2000ml）のどれとも一致しない → 内容量は補わない（null のまま）。
    # 個数 6本 は読みと一致するので仮の数量としては 6本 のまま。値は caption_candidates に残る。
    t = "飲料 500ml 2L ×6本"
    c, _ = _cmp([_o("d", t, 1200, caption="■内容量：200ml×6本")])
    q = _q(c, t)
    assert q["content_amount"] is None and q["measure_total"] is None
    assert q["count_total"] == 6
    assert _has_amount(q, 200)


def test_ac22_counter_assumed_for_low_candidate_without_provisional_quantity():
    # AC22・Q20: 仮の数量が付かなかった low の候補（説明欄なしの yumenokoya）の同じ数え語の読み（48ロール）は、
    # basis=ロール で「この商品が48ロールなら」の仮定（counter_assumed）として to_check に出る。注文案・cheapest_order には入らない。
    # 確認済み X は 12ロール×4パック 12000円（n=1・48ロール）。yumenokoya の仮定: n=1・9649円 < 12000 → to_check。
    x = "トイレットペーパー 12ロール×4パック X店"
    c, r = _cmp([_o("x", x, 12000), _yume(caption=None)], basis="ロール", desired_quantity=48)
    assert c["cheapest_order"]["name"] == x
    assert YUMENOKOYA_NAME in _unknown_names(c)
    assert YUMENOKOYA_NAME not in [p["name"] for p in c["order_plans"]]
    t = _tc(c, YUMENOKOYA_NAME)
    assert "counter_assumed" in _creasons(t)
    assert "48" in _ctext(t)
    assert YUMENOKOYA_NAME not in _selected_names(c)
    _scan(r)


# --------------------------------------------------------------------------
# AC23 説明欄の各文の読み取りによる内容量の補完（U1）
# --------------------------------------------------------------------------

NAMED_U1 = [
    (FUJI_CODE, FUJI_NAME, FUJI_CAP, FUJI_PRICE, 100),
    (ONESTEP_CODE, ONE_N, ONESTEP_CAP, ONESTEP_PRICE, 150),
    (OFFICETRUST_CODE, OFFI_N, OFFICETRUST_CAP, OFFICETRUST_PRICE, 150),
]


@pytest.mark.parametrize("code,name,cap,price,amount", NAMED_U1, ids=["fuji", "onestep", "officetrust"])
def test_ac23_named_examples_adopt_content_as_provisional_but_count_basis_stays_confirmed(code, name, cap, price, amount):
    # AC23・U1・名指し: 題名が high・個数だけ（48ロール）・価格幅なし・題名由来の長さ 75m が 4 件（(iii) の 1/10〜10倍＝7.5〜750m に収まる）。
    # 説明欄の各文から 100m（fuji）／150m（onestep・officetrust。`12ロール 50m シングルと比較` の 50m は (ii) で落ちる）を仮の内容量にする:
    # source="title+caption"・caption_evidence・measure_total=48×値。confidence は high のまま（題名は変えない）。
    # basis=ロール（題名の個数だけで比べる）の単価は確認済みのまま（price÷48）。
    c, r = _cmp(_tgroup() + [_o(code, name, price, caption=cap)], basis="ロール")
    o = _by_name(c, name)
    q = o["quantity"]
    assert q["count_total"] == 48 and q["count_unit"] == "ロール" and q["confidence"] == "high"
    assert q["content_amount"] == pytest.approx(amount) and q["content_dimension"] == "length" and q["content_unit"] == "m"
    assert q["measure_total"] == pytest.approx(48 * amount)
    assert q["source"] == "title+caption" and q["caption_evidence"] and str(amount) in q["caption_evidence"]
    assert o["unit_price_status"] == "confirmed" and o["unit_price"] == pytest.approx(price / 48, abs=0.01)
    assert list(o["unit_price_unconfirmed_reasons"]) == []
    _scan(r)


def test_ac23_onestep_unadopted_50m_note_remains_as_candidate_and_adopted_value_does_not():
    # AC23・§7 W4: onestep:10446085 は 150m を採用し、`スコッティ フラワーパック 12ロール 50m シングルと比較` の 50m が
    # caption_candidates に残る（採用した 150m は残らない）。候補の形のキー: count_total・count_unit・content_amount・content_dimension・evidence。
    c, _ = _cmp(_tgroup() + [_one()], basis="ロール")
    q = _q(c, ONE_N)
    assert q["content_amount"] == pytest.approx(150)
    assert _has_amount(q, 50) and not _has_amount(q, 150)
    cand = next(x for x in q["caption_candidates"] if x.get("content_amount") == pytest.approx(50))
    for k in ("count_total", "count_unit", "content_amount", "content_dimension", "evidence"):
        assert k in cand, k
    assert cand["content_dimension"] == "length" and "50m" in cand["evidence"]


def test_ac23_length_basis_is_provisional_never_cheapest_and_ekurashi_stays_unknown():
    # AC23・Q21・規律8: basis=m。U1 の仮の内容量を使う単価は仮（measure_from_caption）で最安に選ばれない。
    # fuji 25000÷4800=5.21、onestep 7260÷7200=1.01、officetrust 7128÷7200=0.99（T の 1510÷900=1.68 より安い2件も選ばれず、
    # 単位価格の最安は確認済みの T1）。e-kurashi（補われない）は単価不明。
    offers = _tgroup() + [_fuji(), _one(), _offi(), _ekura()]
    c, r = _cmp(offers, basis="m")
    for name, v in ((FUJI_NAME, 25000 / 4800), (ONE_N, 7260 / 7200), (OFFI_N, 7128 / 7200)):
        o = _by_name(c, name)
        assert o["unit_price"] is None and o["provisional_unit_price"] == pytest.approx(v, abs=0.011), name
        assert o["unit_price_status"] == "unconfirmed" and list(o["unit_price_unconfirmed_reasons"]) == ["measure_from_caption"], name
        assert o["unit_price_label"] == "1mあたり", name
        assert name not in _selected_names(c), name
    assert c["cheapest_unit_price"]["name"] == _tname(1)
    assert EKURASHI_NAME in _unknown_names(c)
    assert _by_name(c, EKURASHI_NAME)["unit_price_status"] == "unknown"
    _scan(r)


def test_ac23_length_basis_order_goes_to_to_check_with_condition():
    # AC23・Q16: basis=m・desired=7200m。officetrust n=1（7200m）・7128円、onestep n=1・7260円、fuji n=ceil(7200÷4800)=2・50000円、
    # T n=7200÷900=8・12080円（T1。確認済みの最安）。officetrust・onestep は T1 より安いので to_check に出る
    # （measure_from_caption・「説明欄」の前置き）、fuji は高いので出ない。cheapest_order は T1 だけ。
    offers = _tgroup() + [_fuji(), _one(), _offi()]
    c, r = _cmp(offers, basis="m", desired_quantity=7200)
    assert c["cheapest_order"]["name"] == _tname(1) and c["cheapest_order"]["order_total"] == 12080
    p = _plan(c, OFFI_N)
    assert p["n"] == 1 and p["order_total"] == 7128 and p["confirmed"] is False
    assert p["order_unit_price"] is None and p["provisional_order_unit_price"] == pytest.approx(7128 / 7200, abs=0.011)
    assert "measure_from_caption" in p["unconfirmed_reasons"]
    for n in (OFFI_N, ONE_N):
        t = _tc(c, n)
        assert "measure_from_caption" in _creasons(t)
        assert "説明欄" in _ctext(t)
    assert FUJI_NAME not in _tc_names(c)
    assert {OFFI_N, ONE_N, FUJI_NAME}.isdisjoint(_selected_names(c))
    _scan(r)


def test_ac23_ekurashi_multiple_values_are_candidates_not_adopted():
    # AC23・U1 (i)・名指し: e-kurashi:10041175 は説明欄にシングル 150m・ダブル 75m の2通り → 補わず caption_candidates に 150m・75m。
    # basis=ロール の単価は確認済みのまま（6799÷48=141.65）。
    c, r = _cmp(_tgroup() + [_ekura()], basis="ロール")
    o = _by_name(c, EKURASHI_NAME)
    q = o["quantity"]
    assert q["count_total"] == 48 and q["confidence"] == "high"
    assert q["content_amount"] is None and q["measure_total"] is None and q["source"] != "title+caption"
    assert _has_amount(q, 150) and _has_amount(q, 75)
    assert o["unit_price_status"] == "confirmed" and o["unit_price"] == pytest.approx(6799 / 48, abs=0.01)
    assert "measure_from_caption" not in o["unit_price_unconfirmed_reasons"]
    _scan(r)


def test_ac23_price_varies_candidate_is_not_adopted_but_keeps_the_value_as_candidate():
    # AC23・§7 W4: price_varies の候補（onestep に価格幅 7260〜8000 を構成）には U1 を採用しない。値は caption_candidates の印だけ。
    c, r = _cmp(_tgroup() + [_one(price_min=7260, price_max=8000)], basis="ロール")
    o = _by_name(c, ONE_N)
    q = o["quantity"]
    assert o["price_varies"] is True
    assert q["content_amount"] is None and q["measure_total"] is None and q["source"] != "title+caption"
    assert _has_amount(q, 150)
    _scan(r)


def test_ac23_search_products_never_adopts_u1_and_shows_values_as_candidates():
    # AC23・§7 W4: search_products は比較グループが無いので U1 の採用は起きず、対象の値は全部 caption_candidates に出る
    # （fuji 100m・onestep 150m と 50m・e-kurashi 150m と 75m）。題名の読み取りのまま（48ロール・high・内容量 null）。
    r = _search([_fuji(), _one(), _ekura()])
    by = {o["name"]: o["quantity"] for o in r["offers"]}
    for n in (FUJI_NAME, ONE_N, EKURASHI_NAME):
        q = by[n]
        assert q["count_total"] == 48 and q["confidence"] == "high"
        assert q["content_amount"] is None and q["measure_total"] is None and q["source"] != "title+caption", n
    assert _has_amount(by[FUJI_NAME], 100)
    assert _has_amount(by[ONE_N], 150) and _has_amount(by[ONE_N], 50)
    assert _has_amount(by[EKURASHI_NAME], 150) and _has_amount(by[EKURASHI_NAME], 75)


def test_ac23_pricing_compare_entry_adopts_with_group_statistics():
    # AC23・§7 W4: 採用は pricing が行う。pricing.compare（Offer 直接）でも同じ（題名由来 4 件の統計で onestep の 150m を採用）。
    # 3 件なら採らない（比較グループの統計が足りない）。Offer.quantity が補われ、未確定理由に measure_from_caption（basis=m）。
    from shopping import pricing

    res = pricing.compare(_tgroup(4) + [_one()], basis="m")
    o = next(x for g in res.groups for x in g.offers if x.item_name == ONE_N)
    assert o.quantity.content_amount == pytest.approx(150) and o.quantity.source == "title+caption"
    assert "measure_from_caption" in pricing.unconfirmed_reasons(o)
    res3 = pricing.compare(_tgroup(3) + [_one()], basis="m")
    o3 = next(x for x in list(res3.unknown_offers) + [y for g in res3.groups for y in g.offers] if x.item_name == ONE_N)
    assert o3.quantity.content_amount is None and o3.quantity.source != "title+caption"


@pytest.mark.parametrize(
    "value,adopted",
    [
        ("100", True),            # 75m の 1/10〜10倍（7.5〜750m）の内側
        ("750", True),            # 上限ちょうど（10倍以下）
        ("7.5", True),            # 下限ちょうど（1/10 以上）
        ("751", False),           # 上限の外
        ("7.4", False),           # 下限の外
        ("1000", False),
    ],
    ids=["mid", "upper_edge", "lower_edge", "above", "below", "far_above"],
)
def test_ac23_magnitude_check_boundaries_against_group_median(value, adopted):
    # AC23 (iii)・境界値: 題名由来の長さ 75m が 4 件（中央値 75m）。説明欄 `ロールサイズ:108mm×<値>m`（Q15 で大きい方）が
    # 中央値の 1/10 以上 10 倍以下の時だけ仮の内容量にする。外れる値は採らず caption_candidates に残す。
    cap = f"●ロールサイズ:108mm×{value}m●香りつき"
    c, _ = _cmp(_tgroup(4) + [_o("x", ROLL + " X店", 2400, caption=cap)], basis="ロール")
    q = _q(c, ROLL + " X店")
    v = float(value)
    if adopted:
        assert q["content_amount"] == pytest.approx(v) and q["source"] == "title+caption", value
        assert q["measure_total"] == pytest.approx(48 * v)
    else:
        assert q["content_amount"] is None and q["source"] != "title+caption", value
        assert _has_amount(q, v), value


def test_ac23_sheet_size_is_not_adopted_and_stays_candidate():
    # AC23 構成例: 説明欄 `シートサイズ:206×220mm`（同じ次元の大きい方 220mm=0.22m）は中央値 75m の 1/10 未満 → 採らず caption_candidates に 0.22。
    c, _ = _cmp(_tgroup(4) + [_o("x", ROLL + " X店", 2400, caption="●シートサイズ:206×220mm●芯あり")], basis="ロール")
    q = _q(c, ROLL + " X店")
    assert q["content_amount"] is None and q["source"] != "title+caption"
    assert _has_amount(q, 0.22)


@pytest.mark.parametrize(
    "cap,adopted",
    [
        ("●セット内容：48ロール 100m●芯あり", True),     # 個数つきの文の個数 48 が題名の総数 48 と一致 → 候補になる
        ("●セット内容：24ロール 100m●芯あり", False),    # 24≠48 → 内容量の候補にしない（caption_candidates へ）
    ],
    ids=["count_equal", "count_differs"],
)
def test_ac23_count_bearing_sentence_must_match_title_total(cap, adopted):
    # AC23 (ii): 個数つきの文（同じ文に数字＋数え語がある）の内容量は、その文の個数が題名の総数と一致する時だけ候補にする。
    c, _ = _cmp(_tgroup(4) + [_o("x", ROLL + " X店", 2400, caption=cap)], basis="ロール")
    q = _q(c, ROLL + " X店")
    if adopted:
        assert q["content_amount"] == pytest.approx(100) and q["source"] == "title+caption"
    else:
        assert q["content_amount"] is None and q["source"] != "title+caption"
        assert _has_amount(q, 100)


def test_ac23_fewer_than_four_title_derived_values_is_not_adopted():
    # AC23 (iii): 題名由来がその次元に 4 件未満（3 件）のグループでは採らない（4 件なら採る＝名指しの試験）。値は caption_candidates。
    c, _ = _cmp(_tgroup(3) + [_one()], basis="ロール")
    q = _q(c, ONE_N)
    assert q["content_amount"] is None and q["source"] != "title+caption"
    assert _has_amount(q, 150)


def test_ac23_heading_filled_or_other_nonqualifying_offers_do_not_count_toward_the_four():
    # AC23 (iii): 題名由来（source=title・high）だけが分母。見出し `長さ` で補った候補（source=title+caption）3 件は数えない。
    # 題名由来 3 件＋補った 1 件＝4 件に見えるが題名由来は 3 件 → 採らない。
    heading = _o("h", ROLL + " H店", 2400, caption="●長さ：75m●芯あり")
    c, _ = _cmp(_tgroup(3) + [heading, _one()], basis="ロール")
    assert _q(c, ROLL + " H店")["source"] == "title+caption"           # 前提: 見出しの補完は起きている
    q = _q(c, ONE_N)
    assert q["content_amount"] is None and q["source"] != "title+caption"


def test_ac23_group_is_the_set_remaining_after_term_filters():
    # AC23 (iii): 比較グループ＝語の絞り込み（include/exclude）の後に残った候補の集まり。題名由来 4 件のうち 1 件を exclude_terms で
    # 外すと 3 件 → 採らない。外さなければ（同じ構成）採る。
    offers = [_o(f"t{i}", _tname(i) + (" 別売り" if i == 4 else ""), 1500 + 10 * i) for i in range(1, 5)] + [_one()]
    c, _ = _cmp(offers, basis="ロール")
    assert _q(c, ONE_N)["content_amount"] == pytest.approx(150)
    c, _ = _cmp(offers, basis="ロール", exclude_terms=["別売り"])
    q = _q(c, ONE_N)
    assert q["content_amount"] is None and q["source"] != "title+caption"


def test_ac23_heading_length_fill_comes_first_and_u1_is_not_applied_after_it():
    # AC23・§7 W4: 見出し `長さ` の補完（AC19）は先に当たる。`長さ：100m` で補えた候補には U1 を当てない（別の行の 150m は採らない）。
    cap = "長さ：100m\nロールサイズ:108mm×150m"
    c, _ = _cmp(_tgroup(4) + [_o("x", ROLL + " X店", 2400, caption=cap)], basis="ロール")
    q = _q(c, ROLL + " X店")
    assert q["content_amount"] == pytest.approx(100) and q["source"] == "title+caption"


def test_ac23_title_content_is_never_overwritten_by_caption_sentences():
    # AC23: 題名に内容量がある候補（75m×12ロール）には説明欄の別の値（150m）を重ねない。
    t = f"{ROLL_M} Y店"
    c, _ = _cmp(_tgroup(4) + [_o("y", t, 1600, caption="●ロールサイズ:108mm×150m")], basis="ロール")
    q = _q(c, t)
    assert q["content_amount"] == pytest.approx(75) and q["source"] != "title+caption"


def test_ac23_caption_conflict_is_not_extended_to_bare_sentences_but_headings_still_conflict():
    # §7 W4「採らない案」②: 見出しの無い素の文の個数（12ロール）が題名の総数 48 と食い違っても caption_conflict にしない
    # （confidence は high のまま・確認済み）。見出し付き `入数：24ロール` の食い違いは従来どおり conflict。
    c, r = _cmp([_o("a", ROLL + " A店", 2400, caption="●単品の12ロール入りもあります●芯あり"),
                 _o("b", ROLL + " B店", 2400, caption="●入数：24ロール●芯あり")], basis="ロール")
    a = _by_name(c, ROLL + " A店")
    assert not a["quantity"].get("caption_conflict") and a["quantity"]["confidence"] == "high"
    assert a["unit_price_status"] == "confirmed"
    b = _by_name(c, ROLL + " B店")
    assert b["quantity"]["caption_conflict"] is True and b["quantity"]["confidence"] == "conflict"
    _scan(r)


def test_ac23_title_none_is_not_completed_from_bare_sentences_but_headed_value_still_fills():
    # §7 W4「採らない案」①: 題名 none の候補の個数補完を各文の読み取りに広げない。見出しの無い文の個数は caption_candidates の印だけ
    # （none のまま・単価不明）。見出し付き `内容量：12ロール` は従来どおり補完（source="caption"）。
    t = "トイレットペーパー おすすめ"
    c, _ = _cmp([_o("a", t + " A店", 1200, caption="●12ロール入りです●芯あり"),
                 _o("b", t + " B店", 1200, caption="●内容量：12ロール●芯あり")])
    qa = _q(c, t + " A店")
    assert qa["confidence"] == "none" and qa["source"] != "caption" and qa["count_total"] is None
    assert (t + " A店") in _unknown_names(c)
    assert any(x.get("count_total") == 12 for x in qa["caption_candidates"])
    qb = _q(c, t + " B店")
    assert qb["source"] == "caption" and qb["count_total"] == 12


# --------------------------------------------------------------------------
# AC24 抽出と採用の分離の不変条件
# --------------------------------------------------------------------------

def _mixed():
    """WP16 の全経路を含む構成（U1 の採用・U1 の非採用・U2a・U2b）。"""
    return _tgroup(4) + [_fuji(), _one(), _offi(), _ekura(), _yume(), _kura()]


def test_ac24_wp16_provisional_quantities_never_become_confirmed_and_confirmed_set_is_unchanged():
    # AC24 (1): basis=ロール の構成例。WP16 の前後で変わらない側: T×4・fuji・onestep・officetrust・e-kurashi は題名の個数だけで
    # 確認済み・確定の単価（価格÷個数 = T は ÷12、他は ÷48）。仮の数量が付いた yumenokoya（U2b）・kurashikenkou（U2a）は確認済みにならない
    # （quantity_low）。単位価格の最安は確認済みの T1（1510÷12=125.83。kurashikenkou の仮 121.77 の方が安いが選ばれない）。
    c, r = _cmp(_mixed(), basis="ロール")
    plain = [(_tname(i), 1500 + 10 * i, 12) for i in range(1, 5)] + [
        (FUJI_NAME, FUJI_PRICE, 48), (ONE_N, ONESTEP_PRICE, 48), (OFFI_N, OFFICETRUST_PRICE, 48),
        (EKURASHI_NAME, EKURASHI_PRICE, 48)]
    for name, price, n in plain:
        o = _by_name(c, name)
        assert o["unit_price_status"] == "confirmed" and o["unit_price"] == pytest.approx(price / n, abs=0.01), name
        assert o["provisional_unit_price"] is None and list(o["unit_price_unconfirmed_reasons"]) == [], name
    for name in (YUMENOKOYA_NAME, KURASHIKENKOU_NAME):
        o = _by_name(c, name)
        assert o["unit_price_status"] == "unconfirmed" and "quantity_low" in o["unit_price_unconfirmed_reasons"], name
        assert o["unit_price"] is None and o["quantity"]["confidence"] == "low", name
        assert name not in _selected_names(c), name
    assert c["cheapest_unit_price"]["name"] == _tname(1)
    _scan(r)


def test_ac24_wp16_u1_candidates_are_unconfirmed_wherever_the_added_content_is_used():
    # AC24 (1)(2): basis=m では U1 の仮の内容量を使う候補（fuji・onestep・officetrust）と U2b の yumenokoya が未確定で、
    # 単位価格の最安・注文の最安に選ばれない。kurashikenkou（U2a・内容量 null）は単価不明。T×4 は確認済み。
    c, r = _cmp(_mixed(), basis="m", desired_quantity=4800)
    for n in (FUJI_NAME, ONE_N, OFFI_N, YUMENOKOYA_NAME):
        o = _by_name(c, n)
        assert o["unit_price_status"] == "unconfirmed" and o["unit_price"] is None, n
        assert n not in _selected_names(c), n
    assert KURASHIKENKOU_NAME in _unknown_names(c)
    for i in range(1, 5):
        assert _by_name(c, _tname(i))["unit_price_status"] == "confirmed"
    assert c["cheapest_unit_price"]["name"] == _tname(1) and c["cheapest_order"]["name"] == _tname(1)
    _scan(r)


def test_ac24_measure_from_caption_applies_to_every_filled_dimension():
    # AC24 (2): 2 次元（体積 450ml・質量 400g）を U1 で補った候補は、2 つ目の次元（g）の basis で比べても未確定（measure_from_caption）。
    # 体積の題名由来 4 件・質量の題名由来 4 件（各中央値 450・400）。対象は `ボディソープ 3個`＋説明欄 `容量は450mlです。重さは400gです。`。
    # basis=g: 900÷(3×400)×100=75.0（仮）、basis=ml: 900÷(3×450)×100=66.67（仮）、basis=個: 900÷3=300（確認済み）。
    tgt = "ボディソープ 3個 T店"
    offers = ([_o(f"a{i}", f"ボディソープ 450ml×3個 A{i}店", 1000 + i) for i in range(1, 5)]
              + [_o(f"b{i}", f"ボディソープ 400g×3個 B{i}店", 800 + i) for i in range(1, 5)]
              + [_o("t", tgt, 900, caption="容量は450mlです。重さは400gです。")])
    c, r = _cmp(offers, basis="個")
    q = _q(c, tgt)
    assert q["content_amounts"]["volume"] == pytest.approx(450) and q["content_amounts"]["mass"] == pytest.approx(400)
    assert q["source"] == "title+caption"
    o = _by_name(c, tgt)
    assert o["unit_price_status"] == "confirmed" and o["unit_price"] == pytest.approx(300, abs=0.01)
    for basis, expect in (("g", 75.0), ("ml", 900 / 1350 * 100)):
        c, r = _cmp(offers, basis=basis)
        o = _by_name(c, tgt)
        assert o["unit_price_status"] == "unconfirmed" and "measure_from_caption" in o["unit_price_unconfirmed_reasons"], basis
        assert o["unit_price"] is None and o["provisional_unit_price"] == pytest.approx(expect, abs=0.01), basis
        assert tgt not in _selected_names(c), basis
        _scan(r)


def test_ac24_auto_basis_counts_only_title_derived_amounts():
    # AC24 (3)・Q7: 題名由来の体積 4 件（ボディソープ 450ml×3個）と個数だけの題名 5 件（説明欄 `容量は450mlです` で U1 が体積を
    # 補う）。補った量を数えると 9/9 が体積で basis=ml になるが、題名由来だけなら 4/9（過半でない）→ 個。補完そのものは起きている（前提）。
    offers = ([_o(f"a{i}", f"ボディソープ 450ml×3個 A{i}店", 1000 + i) for i in range(1, 5)]
              + [_o(f"c{i}", f"ボディソープ 3個 C{i}店", 900 + i, caption="容量は450mlです。") for i in range(1, 6)])
    c, r = _cmp(offers)
    q = _q(c, "ボディソープ 3個 C1店")
    assert q["content_amount"] == pytest.approx(450) and q["source"] == "title+caption"     # 前提: U1 の補完は起きている
    assert c["basis"] == "個" and c["basis_label"] == "1個あたり"
    _scan(r)


def test_ac24_u2a_and_u2b_provisional_amounts_do_not_flip_auto_basis():
    # AC24 (3)・Q7: 題名由来の個数だけ 3 件（水 6本）に、U2b で 500ml を補った low の題名 4 件（`飲料 500ml 2L ×6本`＋`内容量：500ml×6本`）。
    # 仮の量（U2a・U2b）を数えると体積が 4/7 で過半になり得るが、題名由来だけなら体積 0/3 → 個。補完は起きている（前提）。
    low = "飲料 500ml 2L ×6本"
    offers = ([_o(f"w{i}", f"天然水 6本 W{i}店", 1000 + i) for i in range(1, 4)]
              + [_o(f"l{i}", f"{low} L{i}店", 1200 + i, caption="■内容量：500ml×6本") for i in range(1, 5)])
    c, _ = _cmp(offers)
    q = _q(c, f"{low} L1店")
    assert q["content_amount"] == pytest.approx(500) and q["source"] == "title+caption"      # 前提: U2b の補完は起きている
    assert c["basis"] == "個"


def test_ac24_caption_filled_none_title_is_not_counted_in_auto_basis():
    # AC24 (3)・Q7（WP16 の改訂）: source="caption"（題名 none の見出し付き補完）は自動 basis の多数決に数えない
    # （旧 WP15 段B の試験は「従来どおり数える」だった。Q7 の改訂で反転）。題名由来: 水 2L×6本（体積）1 件・電池 40本（個数だけ）1 件
    # ＋題名 none で `内容量：500ml×24本` を補った 3 件。数えるなら 4/5 が体積で ml、数えないなら 1/2（ちょうど半数）→ 個。
    offers = [_o("c", "天然水 2L×6本 C店", 2400), _o("d", "単3電池 40本 D店", 1000)] + [
        _o(f"n{i}", f"天然水 おすすめ N{i}店", 3000 + i, caption="内容量：500ml×24本") for i in range(1, 4)]
    c, _ = _cmp(offers)
    assert _q(c, "天然水 おすすめ N1店")["source"] == "caption"                            # 前提: 補完は起きている
    assert c["basis"] == "個"


def test_ac24_order_guide_has_the_wp16_sentence_and_compare_description_stays_within_2000():
    # AC24 (4)・§10 (7): `_ORDER_GUIDE`（INSTRUCTIONS）に「quantity.readings・quantity.caption_candidates は候補で確定値ではない／
    # quantity_low の単価は仮」の指示がある。compare_offers の説明（2000 字ガード・AC-W9）は増やさず 2000 字以内のまま。
    from shopping import mcp_server

    guide = mcp_server._ORDER_GUIDE
    for tok in ("readings", "caption_candidates", "quantity_low"):
        assert tok in guide, tok
        assert tok in mcp_server.INSTRUCTIONS, tok
    assert "確定値" in guide
    from test_blind_wp15 import _tools

    t = _tools()["compare_offers"]
    assert len(t.description) <= 2000, len(t.description)


def test_ac24_web_shows_quantity_low_unit_price_as_provisional_with_reason(monkeypatch):
    # AC24 (4)・Q24: Web は quantity_low の単価を「仮」と理由付きで出す（素の確定値として出さない）。
    # 構成: kurashikenkou の題名（U2a）＋T×4、basis=ロール。理由の文は O6 のとおり「食い違」の語だけ断定。
    from fastapi.testclient import TestClient

    from shopping.guard import Gate, GuardedAdapter, RateLimiter
    from shopping.web import create_app

    monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "APPID-TEST-0000000000")
    monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "ACCESSKEY-TEST-abcdef")
    monkeypatch.delenv("SHOPPING_MOCK", raising=False)

    class Clock:
        t = 1000.0

        def __call__(self):
            return self.t

        def sleep(self, s):
            self.t += s

    clock = Clock()
    offers = _tgroup() + [_kura(price_varies=False, caption=False)]
    ga = GuardedAdapter(FakeAdapter({("aa", 1): (offers, len(offers))}), clock=clock, sleep=clock.sleep)
    gate = Gate(ga, RateLimiter(limit=1000, clock=clock))
    client = TestClient(create_app("", gate), raise_server_exceptions=False)
    resp = client.get("/compare", params={"q": "aa", "basis": "ロール"})
    assert resp.status_code == 200
    html = resp.text
    assert "仮" in html
    assert "食い違" in html
