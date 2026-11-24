# 調査 2026-11-25 — Yahoo の選択肢価格の根拠・商品ページ取得の規約・応答量（ブリッジ#10 第1段）

出典のブリッジ: neguracg/000_AI-Bridge #10（先行 #9）。コードは変えない調査（実装は SPEC §8 Q25 と tests/test_wp18_shortlist.py）。
実 API は `.env` の既存キーで試験A・Bの2回だけ（鍵・appid は出力・保存物に出していない。応答の生データは git 管理外）。価格・順位は取得時点の値で、固定の期待値にしない。

## A1. Yahoo 商品検索 v3 の応答に、選択肢の有無・選択肢別の価格差の根拠はあるか

**結論: 根拠になる項目は無い。Yahoo の全候補を未確認にする現行の安全策（`price_options_unchecked`）は、根拠なしに外せない。**

- 公式（https://developer.yahoo.co.jp/webapi/shopping/v3/itemsearch.html。2026-11-25 取得）の `hits` 配下: `name` `description` `headLine` `inStock` `url` `code` `condition` `janCode` `releaseDate` `payment` `affiliateRate`、価格は `price`・`taxExcludePrice`・`premiumPrice`・`premiumDiscount*`・`priceLabel{taxable, defaultPrice, discountedPrice, fixedPrice, premiumPrice, periodStart/End}`、他に `point` `shipping{code,name}` `delivery` `image` `review` `genreCategory` `brand` `seller`。選択肢（バリエーション・サブコード）・価格幅（楽天の itemPriceMin/Max に当たる物）の項目は**無い**。リクエスト側にも選択肢で絞る引数は無い。
- 実応答 271 件（data/yahoo_poc。2026-11-24。全 29 キーが 271 件すべてに同じ形で出る）で確認: `price == priceLabel.defaultPrice` が 262 件、`discountedPrice` ありが 9 件（セール）、`fixedPrice` ありが 2 件、`premiumPrice != price` が 4 件。いずれも「選択肢の有無」とは別の意味（セール・会員価格・定価）。サブコード別に同じ `code` が価格違いで複数 hit になる形も無い（異なる `code` 183 件のうち、価格が複数あるものは 0 件。`code` は `<ストア>_<商品>` の商品単位）。
- 文言の手がかり（弱い）: 題名に「選べる・選択・カラー…」の語がある hit は 4 件、説明欄は 58 件（21%）。これは「ある」の弱い目安にしかならず、**語が無いことは「選択肢が無い」の根拠にならない**。
- 実ページとの食い違いの実例（2026-11-25）: 試験B の Yahoo「イエプロ 60枚ミニ」（1380円・n=1・仮単価23円）のページには「バリエーション」の選択欄があり、選択肢として「30枚×2セット」が表示されていた。検索 API の応答だけでは、題名の「60枚」と選択肢の内容が一致するかは分からない。
- 誤判定のリスク: 「根拠が無ければ選択肢なし」と読むと、選択肢で価格が変わる商品を単一価格として確認済み最安に出す（BUGLOG 2026-11-20 の unidy と同じ型。偽の最安）。「説明欄の語があれば選択肢あり」と読むと、取りこぼし（語の無い選択肢商品）と過剰（語だけで選択肢の無い商品）の両方が出る。
- 未確認: Yahoo の「商品コード検索（v3）」に選択肢の情報があるか（公式の該当ページを URL の推測で取得できず、検索でも見つからなかった）。ストア管理側の API（サブコード一覧）は出店者向けで購入側のアプリには使えない見込み（推測）。

## A2. 商品ページの追加取得は規約・robots.txt 上許されるか

**結論: 明示の禁止も許可も見当たらないグレー。「許される」とは断定できないので、アプリには入れない（腱さん判断）。**

| 出典 | 内容（取得は要約ツール経由。条文の全文照合は未了） |
|---|---|
| Yahoo! デベロッパーネットワーク ガイドライン https://developer.yahoo.co.jp/guideline/ | LINEヤフー共通利用規約への追加。特約はクレジット表示・アプリケーション ID・情報送信の3つ。API 以外の手段による取得（スクレイピング）の記述は無い |
| LINEヤフー共通利用規約 https://www.lycorp.co.jp/ja/company/terms/ | クローラー・スクレイピングの明文は無い。第1章 第15条(5)「BOT、チートツール、その他の技術的手段を利用して当社サービスを不正に操作する行為」・サーバーへの過度な負荷の禁止、第2章（ソフトウェア）第3条(5)「合理的に必要相当な数を超える利用、乱用等」の禁止 |
| Yahoo!ショッピング ガイドライン https://shopping.yahoo.co.jp/notice/shopinfo/guidelines/ | 自動アクセス・クローラーの記載なし。第9条: 不適切と判断した利用は停止され得る |
| Web API の商用利用 https://support.yahoo-net.jp/PccDeveloper/s/article/H000011080 | Web サービスは「利用者自身の便宜をはかる非商用目的」で認められる。商用は API の窓口へ相談（本アプリの Client ID は個人・非商用登録＝DECISIONS 2026-11-24） |
| robots.txt https://store.shopping.yahoo.co.jp/robots.txt | Disallow は `/cgi-bin/` `/h_api/` 各 `search.html?…`（strcid・brandid・spec・pt・pf 等）`/syene-bff/…view-history` `…item_image_gallery.html` `…review…` など。商品ページ `/<ストア>/<商品>.html` は対象外。Allow・Crawl-delay・Sitemap 行なし。**原文は取得できず（curl が許可されなかった）要約ツールの出力**＝原文での再確認が要る |

- 判断の理由: ①robots.txt は商品ページを禁じていない ②規約は自動取得を名指しで禁じても許してもいない（BOT による不正操作・過度な負荷・乱用は禁止）③API の利用許諾は非商用の登録で、API 外のページ取得まで許すと読める記述は無い ④公開アプリは誰でも検索でき、サーバーの自動取得が利用者の操作数だけ増える（過度な負荷の側）。購入者ログイン・カート・注文の操作は一切していない。
- 技術的な試行（規約上問題なさそうな範囲で 1 件ずつ・匿名・各 1 リクエスト。WebFetch 経由で表示テキストの要約のみ。生 HTML・埋め込み JSON は未確認）:
  - Yahoo「イエプロ 60枚ミニ」（試験B の 1380円）: ページは取得でき、表示価格 1,380円・送料無料（東京都）・「バリエーション」の選択欄（選択肢「30枚×2セット」の 1 件が見え、選択肢ごとの価格は表示テキストに出ていない）。
  - Yahoo「ビバホーム 60枚」（1362円）: 選択欄なし・表示価格 1,362円・**送料 660円（東京都）・同一ストア 7,000円以上で送料無料**。to_check の条件「注文全体の送料が 248円未満ならこちらが安い」に対し、実送料 660円なので逆転しない（ページで確かめられる事実）。
  - 分かったこと: 表示価格・送料・選択欄の有無は取れる。選択肢別の価格は画面の操作（選択）で出る形に見え、取れる保証は無い（未確認）。取得できても数量・色の一致や在庫は別に照合が要る。
- 規約上可能と判断できた場合の方式案（実装はしない）: 上位の逆転し得る候補（`shortlist` の数件）だけを、1 候補 1 回・間隔を空けて・ユーザー操作 1 回につき上限件数付きで取得し、確認できた時だけ根拠付きで確認済みに上げる。取得不能・不一致・不明は今のまま未確認。

## A3. 応答量の実測（compare_offers。試験A・B と同じ入力。実 API・2026-11-25・WP18 の実装前の形）

入力は ブリッジ#10 の試験A（keywords=["貼るカイロ"]・include=["貼る"]・exclude 2語・basis=枚・60〜100・malls 両方・sort=+itemPrice・pages=3）と試験B（"貼るカイロ 60枚"・basis=枚・60〜100・pages=2・standard・exclude 3語）。応答は MCP が返す JSON と同じ（service.compare_offers の dict に公開 MCP が足すクレジットを除く）。

| | 試験A | 試験B |
|---|---|---|
| 取得 | 楽天 90/4089・Yahoo 150/9347（5.2 秒） | 楽天 60/124・Yahoo 75/75（2.7 秒） |
| 応答のバイト数（UTF-8・空白なし） | **911,033** | **457,502** |
| 概算トークン（日本語 1 字≒0.7〜1・ASCII 3〜4 字≒1 の幅。実トークナイザでは未測定） | 約 22〜30 万 | 約 11〜15 万 |

どのキーが何割か（`comparison` 配下。残りは notes・stats・credits など合計 1% 未満）:

| キー | 試験A | 試験B |
|---|---|---|
| groups（全候補の明細） | 325,313 B（35.7%） | 303,942 B（66.4%） |
| unknown_offers（数量が読めない候補の明細） | 310,915 B（34.1%） | 40,115 B（8.8%） |
| to_check（逆転し得る候補と条件） | 239,070 B（26.2%・185 件） | 28,407 B（6.2%・22 件） |
| order_plans（希望量の注文案） | 25,671 B（2.8%・28 件） | 71,321 B（15.6%・76 件） |
| caveats | 3,142 B（0.3%） | 3,152 B（0.7%） |

重複している情報:
- **最上位の複製**: グループが 1 つの時、最上位の `order_plans`・`to_check`・`cheapest_*` は `groups[0]` の中身と同じ（試験A で `order_plans==groups[0].order_plans`・`to_check==groups[0].to_check` を確認）。複製の分が A 268,665 B（29.5%）・B 106,706 B（23.3%）。
- **候補が出る場所の数**: 同じ候補が groups.offers・order_plans（最上位）・groups[].order_plans・to_check（最上位）・groups[].to_check に出る。5 か所に出る候補が A 28 件・B 10 件、3 か所が A 157 件・B 78 件。
- 1 件ごとの中身（明細）: A の unknown_offers は quantity 77.7KB・caption 67.0KB・name 19.8KB が大半。B の groups の offers は caption 46.6KB・quantity 43.3KB・name 21.5KB。to_check は `conditions` が A 70.5KB（29%）・B 8.0KB。
- **順序**: 実装前は `groups` が先頭（1,467 B 目）・`unknown_offers`（A 326,790 B 目）・`caveats` は A 906,565 B 目・B 453,450 B 目（応答のほぼ末尾）、`notes` は末尾。ChatGPT の「ツール出力が大幅に切り詰められた」（#10）が先頭側を残して末尾を切る型なら、`to_check`・`caveats`・`notes`（結論側）が先に失われる。**ただし ChatGPT 側の切り詰めの位置・上限は未確認（推測）**。

WP18 で入れた物（SPEC §8 Q25・AC27）: 値は変えずキーの順だけ結論が先（実 API 再実行・空白なしの同じ測り方で、caveats は A で 14,043 B 目・B で 18,350 B 目、`groups` は A 282,002 B 目・B 120,710 B 目。結論側が先頭から約 2 万バイト以内に入る）にし、`comparison.shortlist`（A 7,233 B・B 8,057 B＝全体の 0.8〜1.8%）を足した。再実行では取得の揺れで全体が A 918,279 B・B 462,174 B になった。出力の削減（重複の除去・要約モード・明細の絞り込み）は候補を減らし得るので入れていない。

## 論点（腱さんの承認待ち）
報告の本文（ワーカーの返答）を参照。Yahoo のガード解除・確定条件の変更・出力の削減はいずれも未実施。
