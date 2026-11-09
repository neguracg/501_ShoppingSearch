# 楽天MCP E2E再試験結果｜WP12本番反映後｜全140ケース

- 実施日：2026-11-09（JST）
- 報告書生成：2026-11-09 11:18 JST
- 経路：このChatGPT通常チャット → 接続済み楽天MCP (`search_products`/`compare_offers`) → 楽天ウェブサービス（`mock=false`の本番実データを用いた試行）
- 参照した添付：`00_rerun_2026-11-09_for_chatgpt.md`、`01_E2E機能試験シナリオ_v1_80件.md`、`02_E2E機能試験_全80ケース実行結果_v1.1.md`、`03_追加E2E実データ試験結果_v3_60件.md`、`99_ChatGPTに貼るプロンプト.txt`
- 証跡の注意：以下は**MCP実呼出しの結果から抜粋した返却値**。生の全JSON/全件候補を保存したものではない。価格・検索件数は取得時点に限る。商品URLはMCP返却値であり、ブラウザ到達は別判定。

## 1. 総合判定

**結果：140ケースを判定表に記録。MCP実呼出しで試行したケースは132件、MCP呼出しが不要なケース1件、独立ターン／安全な試験フィクスチャ不足で未実施7件。**

| 区分 | 件数 |
|---|---:|
| 今回 PASS | 88 |
| 今回 BLOCKED | 45 |
| 今回 FAIL | 0 |
| 今回 NOT RUN | 7 |

前回PASSは65件。そのうち今回もPASS=60件、BLOCKED=5件。BLOCKEDを回帰FAILと同一視しない。今回のPASSは、条件に合わない候補を**ChatGPT側で除外し、推奨を控えることによる安全な応答**も含む。価格絶対最安を証明した意味ではない。

### 判定定義

- **PASS**：再試験の観点について返却値とChatGPT側の安全判定が一致した。候補の仕様同定・最安保証まで含むとは限らない。
- **BLOCKED**：十分な商品候補、送料、JAN/SKU、独立した会話ターン等がなく、対象シナリオの全要件を確認できなかった。修正点だけPASSの場合もここに置く。
- **FAIL**：今回のテストでユーザー要求に反する実証済み回答・処理が発生し、AI側の安全な除外でも防げなかった場合。
- **NOT RUN**：外部データでは再現できない独立ターン／攻撃フィクスチャ／障害注入を要するケース。

### 前回PASSから今回BLOCKEDになった5ケース（退行FAILとは区別）

| ケース | 前回 | 今回 | 判定保留の理由 |
|---|---|---|---|
| CH-02 | PASS | BLOCKED | 2回のMCP呼出しでは、別ユーザーターンで規格を保持できるか検証できない |
| CH-03 | PASS | BLOCKED | 150g/100gの別検索は実施したが、独立した追質問の状態遷移を検証できない |
| DN-04 | PASS | BLOCKED | 今回の販促数字指定検索は0件で、対象商品の解析を照合できない |
| PR-06 | PASS | BLOCKED | 6本購入の条件で商品候補0件となり、上限制約を検証できない |
| PR-09 | PASS | BLOCKED | 同額首位商品を今回の取得範囲で確認できず、同率表示を試験できない |

**今回FAIL 0件は「MCPの不具合0件」を意味しない。** 48本の二重計上など既知の誤解析は残っており、外れ値検出またはChatGPT側の除外により危険な最安推奨を防いだケースはPASS/ BLOCKEDとして扱った。

## 2. 環境・版確認

- `compare_offers` のツール定義には WP11の「【注意】このツールは商品の種類・仕様（本体／交換部品・付属品、純正／互換…）を判定しない」が含まれる。さらに `unit_price_outlier` が true の最安推薦を避ける説明も存在。**手動のコネクタ更新操作は実行していない**。参照中のツール定義で反映確認。
- WP12は添付資料の報告では03:14にコミット `761dd6d` を本番反映済み。ただしこちらがサーバのリリース履歴や3,066件の単体テストを独立に監査したわけではない。
- コネクタ返却の形式に `stats.per_keyword[].api_count`（ヒット全量）、`received`（取得した件数）、`next_page` 等を確認。多くのケースは1ページ=30件、重要ケースは2〜3ページとした。検索対象全数を取り切ったわけではない。

## 3. 重点ケース・WP12の実測

| 検証対象 | 主要な返却値 | 判定・制限 |
|---|---|---|
| TP-01/TP-07 | `30m12R`、紙幅109mmの2商品とも `confidence=low`、`measure_total=null` | **修正点PASS**。送料込みで条件完全一致した最安の確定はBLOCKED。 |
| WT-07/SR-10 | `【48本】...48本 2ケース`と`【12本】...12本 2ケース`がlow/null | **修正点PASS**。 |
| DN-03/DN-05 | `150g 1本/3本/5本`がlow/null。確定3本品は450g/high | **修正点PASS**。 |
| FD-01 | `最大700g...1kgより少ない`がlow/null | **修正点PASS**。 |
| EL-11/EX-003/EX-007/EX-043 | 不正な1文字語を `keyword_term_too_short` と理由付きで返す。DELTA2／ヌプシジャケットLへ修正再検索成功 | **WP8の入力防御PASS**。別製品・付属品の混入と比較対象の不足はBLOCKED。 |
| EX-001/EX-040 | `ICBK80L`対象low/null、80000mLと確定しない | **修正点PASS**。 |
| EX-009 | `本体+バッテリ2個+充電器`がlow/null | **修正点PASS**。 |
| EX-017 | `6.5L/8L/.../50L`選択式がlow/null | **修正点PASS**。 |
| WP12：メリーズ | `S54枚×4パック(216枚)...4〜8kg`：low/null | **修正点PASS**（取得できた題名の1種類）。 |
| WP12：誤単位 | 指定語 `2000m 2L×6本` で再検索したが当該誤植を含む実商品は見つからず | **BLOCKED**。通常の `2000ml` の6本セットは12000mL/high。 |
| WP12：IC6CL80 | `...エプソン80l IC6CL80`：[商品](https://item.rakuten.co.jp/biccamera/4988617194069/) がlow/null | **修正点PASS**（前回は80000mL/high）。 |
| WP12：PET500ml | [天然水 PET500ml×24本](https://item.rakuten.co.jp/drink-next/4965346250112-241/)：`count_total=24`、`measure_total=12000mL`、high | **修正点PASS**。2ケース48本との区別も正しい。 |

## 4. 全140ケース｜前回／今回の比較

判定表の「MCP返却値・URL」には検索条件下で観測できた**代表例**を記載。各ケースの全候補は掲載していない。完全一致や送料込み最安が未証明のケースはBLOCKED。

| ケース | 試験名 | 前回 | 今回 | MCP返却値・直接商品URL・ChatGPT側判定 |
|---|---|---|---|---|
| TP-01 | 30m×12ロール／ダブルの厳密一致 | FAIL | **BLOCKED** | API 13+69、受信73。30m12Rと幅109mm商品はいずれもconfidence=low/単価null（修正PASS）。送料込み12ロール限定の全候補最安は未確定。　[商品1](https://item.rakuten.co.jp/kaumall/31736480/) [商品2](https://item.rakuten.co.jp/enetwakuwaku/7299982/) |
| TP-02 | シングル・ダブル混入 | FAIL | **PASS** | API 509+70、受信60。ダブルとシングルは商品名照合で別扱い。ダブル96ロールの例は2880m/high。シングルを回答の候補から除外。　[商品1](https://item.rakuten.co.jp/ebest/fg00000833867/) |
| TP-03 | 1ロールの長さ違い | BLOCKED | **PASS** | API 509+752、受信60。30mと50mを同一の一ロール規格として推奨しない。30m×96ロール=2880m/highを確認。　[商品1](https://item.rakuten.co.jp/ebest/fg00000833867/) |
| TP-04 | 12ロール×複数パック | PASS | **PASS** | API 1+2、受信3。12×4=48ロール・1440m/high、12×3=36ロール・1080m/high。数量計算一致。　[商品1](https://item.rakuten.co.jp/nagomishop-ra/t00076/) [商品2](https://item.rakuten.co.jp/yumenokoya/c02-ds-2359925/) |
| TP-05 | 長さ単価とロール単価の区別 | PASS | **PASS** | API 509、受信30。30m×96ロール=2880m/high。1m単価と1ロール単価を別計算。単袋12ロールとケースを混同しない。　[商品1](https://item.rakuten.co.jp/ebest/fg00000833867/) |
| TP-06 | 長さ表記の揺れ | PASS | **PASS** | API 2+509、受信32。30メートル／30m表記を同じ長さとして扱い、選択式は確定候補から外す。　[商品1](https://item.rakuten.co.jp/ebest/fg00000833867/) |
| TP-07 | 紙幅・芯・エンボスの差 | FAIL | **BLOCKED** | API 70+16、受信76。幅109mmを0.109mにしない（low/null）ことを確認。紙幅・香り・芯など詳細仕様が未確定の候補は保留。　[商品1](https://item.rakuten.co.jp/enetwakuwaku/7299982/) |
| TP-08 | 販促数字を数量に誤認しない | PASS | **PASS** | API 5、受信5。ポイント5倍の販促表記をロール数に算入せず、30m×12ロール=360m/high。　[商品1](https://item.rakuten.co.jp/papyruscompany/2026-3157x5p/) |
| TP-09 | 1袋とケース単位の区別 | PASS | **PASS** | API 2+78、受信32。96ロール(12×8)=2880m/highを単品12ロールと区別。送料不明を含め総額最安は断定しない。　[商品1](https://item.rakuten.co.jp/corelex/corelex30m12rw/) |
| TP-10 | 対象規格がヒットしない場合 | PASS | **PASS** | API 0、受信0。無香料かつ無漂白の完全一致を確認できず、代替品を創作しない。　URLなし（該当品未取得／対象外） |
| DN-01 | 150gと100gの除外 | PASS | **PASS** | API 275、受信30。exclude_termsで100g/クール/寄付を15件除外。通常150g/highの商品を確認。　[商品1](https://item.rakuten.co.jp/breeze-8910/4987107676399-t/) |
| DN-02 | 通常とクールを区別 | BLOCKED | **BLOCKED** | API 275+127、受信60。通常／クールをタイトルで区別。JANで全候補のSKU確定まで未確認。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| DN-03 | 150g×3の解釈 | FAIL | **PASS** | API 6+4、受信10。150g×3の確定品450g/high、1/3/5本選択式はlow/null（修正PASS）。　[商品1](https://item.rakuten.co.jp/papamama/4987107676399s3/) [商品2](https://item.rakuten.co.jp/f141500-sagamihara/110162-30076454/) |
| DN-04 | 販促文中の2個・3個 | PASS | **BLOCKED** | API 0、受信0。販促2個／3個表記の対象商品が再取得できず退行判定不可。　URLなし（該当品未取得／対象外） |
| DN-05 | 選択式商品の誤確定防止 | FAIL | **PASS** | API 2、受信2。1/3/5本から選択する寄付商品low/null、単価最安から除外。　[商品1](https://item.rakuten.co.jp/f141500-sagamihara/110162-30076454/) |
| DN-06 | 単品から10本まで比較 | BLOCKED | **PASS** | API 22+4+6+6+4、受信42。10本セット1500g/highなどを取得。送料と仕様を確認しない推奨はしない。　[商品1](https://item.rakuten.co.jp/papamama/4987107676399s10/) |
| DN-07 | JANを使った区別 | BLOCKED | **BLOCKED** | API 275+128、受信60。通常とクールの製品名は判別。JAN対応は全件検証未了。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| DN-08 | 最安が送料別の場合 | PASS | **PASS** | API 275、受信30。商品価格最安と送料込み総額最安を別扱い。送料不明ありcheapest_total=null。　[商品1](https://item.rakuten.co.jp/breeze-8910/4987107676399-t/) |
| WT-01 | 500mL×24本 | FAIL | **PASS** | API 3528、受信30。先頭48本24Lは24本条件から除外。24本12L商品を別規格とし、48本最安を24本最安と呼ばない。　[商品1](https://item.rakuten.co.jp/lifedrinkcompany/ayamizu-500-48/) [商品2](https://item.rakuten.co.jp/rakutenoriginal-daily/ro-b-001/) |
| WT-02 | 2L×6本と500mL×24本 | PASS | **PASS** | API 2187+3528、受信60。2L×6本=12L/high。500ml×24本も12Lだが容器別規格として扱う。　[商品1](https://item.rakuten.co.jp/rakutensokuhaimart/4902102113632/) |
| WT-03 | 24本×2ケース | FAIL | **PASS** | API 849、受信30。24本×2=48本24L。選択式24本/48本を確定品として採用しない。　[商品1](https://item.rakuten.co.jp/arimas/310791/) |
| WT-04 | 炭酸水と非炭酸水 | FAIL | **PASS** | API 3834、受信30。炭酸／スパークリング／ソーダの語で12件除外。残った48本も24本指定と別規格。　[商品1](https://item.rakuten.co.jp/lifedrinkcompany/ayamizu-500-48/) |
| WT-05 | お茶と水を別商品扱い | FAIL | **PASS** | API 3528、受信30。水以外（茶／スポーツ飲料）を除外する扱い。容器本数は別途照合。　[商品1](https://item.rakuten.co.jp/lifedrinkcompany/ayamizu-500-48/) |
| WT-06 | L/mL表記の正規化 | BLOCKED | **PASS** | API 14547+32、受信60。0.5Lと500mLを換算可能。ただし48本と24本は同一SKUとしては扱わない。　[商品1](https://item.rakuten.co.jp/lifedrinkcompany/ayamizu-500-48/) |
| WT-07 | 総容量での希望数量 | FAIL | **BLOCKED** | API 967+3393、受信120。48本二重計上の対象はlow/null（修正PASS）。希望24L/必要注文数の送料含む総額比較は不確定。　[商品1](https://item.rakuten.co.jp/yytakuhaibin/83004166/) |
| WT-08 | 単位が違うジュースの混入 | FAIL | **PASS** | API 95、受信30。600mL商品と500/525mLを別規格扱い。2304本への誤解析商品はunit_price_outlier=trueで推奨除外。　[商品1](https://item.rakuten.co.jp/f222267-makinohara/131-37/) |
| EL-01 | ソーラーパネル500W厳密一致 | FAIL | **BLOCKED** | API 29、受信29。候補にポータブル電源が混入。500Wソーラーパネル本体の確定推奨は行わない。　[商品1](https://item.rakuten.co.jp/yesper/vt-jump1500x/) |
| EL-02 | 500Wと500Whの区別 | FAIL | **PASS** | API 146+33、受信60。WとWhは別次元。ポータブル電源等を除外し、仕様が確認できるパネルのみ検討。　[商品1](https://item.rakuten.co.jp/trust-nine/pluginsolar1500w/) |
| EL-03 | 2枚×250Wの扱い | BLOCKED | **BLOCKED** | API 0+6、受信6。250W×2枚と500W単枚の対比に必要な実商品が不足。545W商品を500W単枚と偽らない。　[商品1](https://item.rakuten.co.jp/lvyuan/545w31pcs/) |
| EL-04 | 500Wヒーターの除外 | FAIL | **BLOCKED** | API 146+5207+5709、受信90。商品名フィルタで60件除外。照明／ヒーター等をパネルとして推薦しないが、用途の確定比較は未了。　[商品1](https://item.rakuten.co.jp/trust-nine/pluginsolar1500w/) |
| EL-05 | 定格/最大/入力の差 | FAIL | **BLOCKED** | API 15、受信15。定格出力500Wのパネル証跡不足。ポータブル電源の入力Wをパネル定格と扱わない。　[商品1](https://item.rakuten.co.jp/yesper/vt-jump1500x/) |
| EL-06 | WとWhの価格単価 | FAIL | **BLOCKED** | API 33、受信30。500Wh指定に500W出力表示の商品が混入。容量Whの裏付けがない候補を除外。　[商品1](https://item.rakuten.co.jp/refun/062190/) |
| EL-07 | Ah/mAhとWh変換制限 | PASS | **PASS** | API 2597、受信30。20000mAh/highを取得。電圧条件未確定なのでWhの換算を断定しない。　[商品1](https://item.rakuten.co.jp/zian/10000038/) |
| EL-08 | 充電器65Wと65W相当 | BLOCKED | **BLOCKED** | API 2836、受信30。65W表記は取得したが単一ポート最大か合計かの商品仕様を確定できない。　[商品1](https://item.rakuten.co.jp/being/65w-d/) |
| EL-09 | 切替式電力表記 | PASS | **PASS** | API 29、受信29。500/1000W切替表記のヒーターは固定500W品と分離。　[商品1](https://item.rakuten.co.jp/kadecoco/4963505160784/) |
| EL-10 | 60W相当LEDと消費電力 | PASS | **PASS** | API 5244、受信30。60W相当LEDは実消費60Wではないと明示、異なる仕様を混ぜない。　[商品1](https://item.rakuten.co.jp/irisplaza-r/110903/) |
| EL-11 | 型番一致と似た型番 | FAIL | **BLOCKED** | 事前バリデーションkeyword_term_too_shortで『2』を指摘。DELTA2へ修正して5件受信。ただしアダプターが主でパネル互換性を確認できず。　[商品1](https://item.rakuten.co.jp/natuarc/s-b0bt9blp9g-20240515/) |
| EL-12 | 容量条件と出力条件の併存 | FAIL | **BLOCKED** | API 18、受信18。充電器(600W)混入。1000Wh以上かつ定格1000W以上の双方確認できる電源は未確定。　[商品1](https://item.rakuten.co.jp/irodoriss/ird-1xxnugx2gmjx3qpq/) |
| BT-01 | 単3/単4の除外 | FAIL | **PASS** | API 1403、受信30。単4/単四/充電池除外20件。単3アルカリ40本/highを取得。　[商品1](https://item.rakuten.co.jp/ossis/alkaline-aa-40/) |
| BT-02 | 20本×2・10本×4 | FAIL | **PASS** | API 26+9、受信35。10本×4パック=40本/highの確定品を取得、20本×2と同じ総本数として計算。　[商品1](https://item.rakuten.co.jp/onko/10004010/) |
| BT-03 | 充電池/使い捨て区別 | FAIL | **PASS** | API 27、受信27。充電／ニッケル水素表記9件除外。使い捨てアルカリ電池に絞る。　[商品1](https://item.rakuten.co.jp/yumenokoya/c02-ds-2617446/) |
| BT-04 | 本数不明の処理 | PASS | **PASS** | API 7、受信7。電池ボックス50個は単3電池ではないと判定し除外。入り数不明の電池に単価を付けない。　[商品1](https://item.rakuten.co.jp/marutomi-kyouzai/dw746553-50/) |
| BT-05 | 同一規格で必要数 | FAIL | **BLOCKED** | API 1403+280、受信60。60本/high候補は存在。必要数充足は確認できるが、別送料の支払総額最安は未確定。　[商品1](https://item.rakuten.co.jp/kounotorinodvd/t3x10p-10/) |
| FD-01 | 食品100gと1kg | FAIL | **PASS** | API 1+189、受信61。『最大700g…1kgより少ない』はlow/null（修正PASS）。1kgとして推奨しない。　[商品1](https://item.rakuten.co.jp/bokunotamatebakoya/h11000178/) |
| FD-02 | コーヒー200g×5 | PASS | **PASS** | API 195、受信30。200g×5袋=1000g/high。粉／豆の仕上がり指定を別確認。　[商品1](https://item.rakuten.co.jp/gourmetcoffee/3544/) |
| FD-03 | 粉と豆の区別 | BLOCKED | **BLOCKED** | API 271、受信30。豆のまま/粉の選択商品混在。粉末品を豆のまま品と断定せず、商品仕様照合を保留。　[商品1](https://item.rakuten.co.jp/coffee-takamura/4993199671518/) |
| FD-04 | サイズが異なる洗剤セット | FAIL | **BLOCKED** | API 2、受信2。900mL×3袋の数量は2700mL/highだが例は浴室洗剤で洗濯洗剤ではない。AI側で用途違い除外。　[商品1](https://item.rakuten.co.jp/yoikenkou/103-4560309810305-3/) |
| FD-05 | 濃縮／通常タイプ | FAIL | **BLOCKED** | API 1574、受信30。濃縮『柔軟剤』も混在。洗濯洗剤の濃縮／通常の使用量同等性は未検証。　[商品1](https://item.rakuten.co.jp/jism/4902135322537-73-30000839-n/) |
| FD-06 | 洗剤のmlとg | PASS | **PASS** | API 439+154、受信60。1Lと1kgを密度なしで相互換算しない。　[商品1](https://item.rakuten.co.jp/kenko-depart/46340n/) |
| FD-07 | 1本600mLで2本セット | FAIL | **BLOCKED** | API 115、受信30。600mL×2指定に600mL単品が混在。AIが不適合として除外したため1.2L確定購入品は未取得。　[商品1](https://item.rakuten.co.jp/beisia/4902050210483/) |
| PR-01 | 送料込み／送料別 | PASS | **PASS** | API 275、受信30。送料別/不明を送料込み総額最安と混同しない（cheapest_total=null）。　[商品1](https://item.rakuten.co.jp/breeze-8910/4987107676399-t/) |
| PR-02 | タイトル送料無料とAPI不一致 | BLOCKED | **BLOCKED** | API 99、受信30。『送料無料』文言と送料フラグの矛盾を判定できる反例は本ケースでは未確認。　[商品1](https://item.rakuten.co.jp/nitirakuya/4987107673947-3/) |
| PR-03 | 送料不明で最安断定禁止 | PASS | **PASS** | API 275、受信30。送料不明を含みcheapest_total=null。総額最安を断定しない。　[商品1](https://item.rakuten.co.jp/breeze-8910/4987107676399-t/) |
| PR-04 | ポイントを本体価格から控除しない | BLOCKED | **PASS** | API 6、受信6。ポイント10倍の広告と販売価格を分離。現金値引として差し引かない。　[商品1](https://item.rakuten.co.jp/lens-deli/r-4987107676399/) |
| PR-05 | クーポンを無条件に適用しない | PASS | **PASS** | API 2、受信2。3%OFFクーポンは取得条件未確定として税込表示価格から無条件控除しない。　[商品1](https://item.rakuten.co.jp/drugpure/so_4987107676399/) |
| PR-06 | 購入数制限 | PASS | **BLOCKED** | API 0、受信0。指定の6本購入条件の商品候補を取得できず、購入上限の充足を未判定。　URLなし（該当品未取得／対象外） |
| PR-07 | 希望数量を満たす最安総額 | FAIL | **BLOCKED** | API 1931+1403+6、受信66。40本単品は存在。20本×2など買い合わせと別送料を合わせた総額は未確定。　[商品1](https://item.rakuten.co.jp/ossis/alkaline-aa-40/) |
| PR-08 | ふるさと納税品の除外 | PASS | **PASS** | API 275、受信30。ふるさと納税2件を除外、通常購入品に絞る。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| PR-09 | 同額候補 | PASS | **BLOCKED** | API 275、受信30。同額首位の存在を今回の抽出範囲で確定できず、恣意的な同率・単独首位を断定しない。　[商品1](https://item.rakuten.co.jp/breeze-8910/4987107676399-t/) |
| PR-10 | 在庫切れ混入 | BLOCKED | **BLOCKED** | API 275、受信30。実在候補は取得したが商品ページで注文可能か在庫の最終確定は未検証。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| PR-11 | 検索価格範囲 | PASS | **PASS** | API 56、受信30。min=2195円,max=2980円で指定上限3000円以下を満足。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| PR-12 | 価格境界 | PASS | **PASS** | API 9404、受信30。実価格1000～1840円で境界1000円以上2000円以下を満足。　[商品1](https://item.rakuten.co.jp/bp-shop/10017803-ko3/) |
| SR-01 | 複数キーワード統合 | PASS | **PASS** | API 275+17、受信47、重複3件除外して44商品。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| SR-02 | 表記揺れスペース | PASS | **PASS** | API 670+670、受信60、重複22件除外して38商品。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| SR-03 | ヒット0件 | PASS | **PASS** | API 0、受信0。架空の商品を提示しない。　URLなし（該当品未取得／対象外） |
| SR-04 | 検索条件が足りない | FAIL | **PASS** | API 10、受信10。『安いソーラーパネル』には測定工具のソーラーパネルという語もヒット。定格出力/用途未指定を明示し、購入候補として推奨しない。　[商品1](https://item.rakuten.co.jp/tatsumax/397-9377/) |
| SR-05 | 品名だけの検索 | PASS | **PASS** | API 51153、受信30（取得1ページ）。件数・容量など追加条件を利用者指定と偽らない。　[商品1](https://item.rakuten.co.jp/iseki-elec/10000349/) |
| SR-06 | 除外語 | PASS | **PASS** | API 275、受信30、クール/100gを14件除外。通常150gを確認。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| SR-07 | 検索上限と網羅性 | PASS | **PASS** | API 275+17+0、受信107、重複15除外後92。3ページ/語、続きページあり、全検索絶対最安と断定しない。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| SR-08 | 商品固有URL | PASS | **PASS** | API 1403、受信30。候補ごとにitem.rakuten.co.jp直URLを返す。　[商品1](https://item.rakuten.co.jp/ossis/alkaline-aa-40-free/) |
| SR-09 | 検索日付と出典 | PASS | **PASS** | API 275、受信30、fetched_at=2026-11-09T11:04:28+09:00。楽天ウェブサービス実データ。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| SR-10 | 比較不能を正しく報告 | FAIL | **PASS** | API 407+785、受信120。12本×2ケースの二重計上商品はlow/nullでランキング外（修正PASS）。送料不明も総額に使わない。　[商品1](https://item.rakuten.co.jp/yytakuhaibin/83004275/) |
| CH-01 | 通常チャットからツール実行 | PASS | **PASS** | API 1740、受信30。ChatGPT通常チャットから実MCP呼出し、個別URL・価格を取得。　[商品1](https://item.rakuten.co.jp/biccamera/4903301186403/) |
| CH-02 | 追質問で同一規格維持 | PASS | **BLOCKED** | 初回と追質問を想定して2回MCPを呼び、指定規格を維持。ただし独立したユーザーの次ターンの挙動そのものは未試験。　[商品1](https://item.rakuten.co.jp/corelex/fuwahana12r/) |
| CH-03 | 追質問で規格変更 | PASS | **BLOCKED** | 150gと100gを各1回検索。後者では100g品を取得。ただし独立した追質問ターンの状態保持は未試験。　[商品1](https://item.rakuten.co.jp/seikatsuzakka-plus1/4987107676443/) |
| CH-04 | 曖昧な依頼時の明示 | FAIL | **PASS** | API 35684、安価順30件の先頭はLEGOソーラーパネル模様の部品45円。実際の発電用パネルでないためAI側で除外。　[商品1](https://item.rakuten.co.jp/starbrick37/30350bpb105/) |
| CH-05 | 不要なツール実行の抑制 | PASS | **PASS** | 説明質問「単価＝価格÷数量」は実検索不要。MCPを呼ばず回答可能（仕様どおり）。　URLなし（該当品未取得／対象外） |
| CH-06 | 会話にない価格を創作しない | PASS | **PASS** | API 275、受信30。今回のリアルタイム返却を使用。商品価格2195円は送料別・数量制限あり。全店舗の最安とは断定しない。　[商品1](https://item.rakuten.co.jp/breeze-8910/4987107676399-t/) |
| CH-07 | 再検索と鮮度 | PASS | **PASS** | 同じ検索を2回実行し、fetched_at 11:04:56 と11:04:57の相違を確認。先頭商品URL・価格一致。　[商品1](https://item.rakuten.co.jp/pc-goodmedia/20151215-000010/) |
| CH-08 | MCP検索結果に含まれる指示の無視 | BLOCKED | **BLOCKED** | API 22766、受信30。『別サイトに送信せよ』等の攻撃文は取得した商品説明中には見つからず、実攻撃フィクスチャなし。　[商品1](https://item.rakuten.co.jp/f222071-fujinomiya/a-10-07/) |
| EX-001 | エプソン ICBK80L純正 と ICBK80純正 | FAIL | **PASS** | API 394+624、受信120。ICBK80L/80Lの対象はlow/null。型番を80000mLとして確定しなくなった。　[商品1](https://item.rakuten.co.jp/kazamidori/4988617193994/) |
| EX-002 | ダイキンMC55Z空気清浄機本体と交換フィルター | FAIL | **PASS** | API 0+8、受信8。MCPの単価首位は3180円の『交換フィルター』で本体ではない。AI側で除外、本体の最安は未確定。　[商品1](https://item.rakuten.co.jp/isinlive/kafp097a4-kad109a4-rakuten-b/) |
| EX-003 | EcoFlow DELTA 2本体 vs DELTA 3本体 | BLOCKED | **BLOCKED** | 『DELTA 2』でkeyword_term_too_short（HTTP 400に至らず）。修正『DELTA2』は0件、『DELTA3』6件。どちらも完全な本体比較は未成立。　[商品1](https://item.rakuten.co.jp/autobacs-ec/4895251626408/) |
| EX-004 | エプソンICBK80L純正と互換インク | FAIL | **PASS** | API 394、受信30。MCP候補の互換インク2本360円を『純正』からAI側で除外。無条件の純正最安提示を避ける。　[商品1](https://item.rakuten.co.jp/seasky/18000222/) |
| EX-005 | Jackeryポータブル電源1000 New新品と中古 | FAIL | **BLOCKED** | API 39+28、受信58。MCPの単価首位は1500 New (1536Wh)、1000 Newではない。AI側で除外、1000 New新品の最安は未確定。　[商品1](https://item.rakuten.co.jp/jackery-japan/21-0001-000354/) |
| EX-006 | マキタTD173DRGXB黒/TD173DRGXOオリーブ | BLOCKED | **BLOCKED** | API 57+120、受信60。黒とオリーブを型番で区別できる候補あり。ただし選択式SKUの購入時確定保証なし。　[商品1](https://item.rakuten.co.jp/nakakitadenki/makita-td173drgx/) |
| EX-007 | ヌプシジャケットLとXL | BLOCKED | **BLOCKED** | 『ヌプシジャケット L』でkeyword_term_too_short（『L』を正しく特定）。『ヌプシジャケットL/XL』へ修正すると9/2件。選択式の確定SKU未確認。　[商品1](https://item.rakuten.co.jp/vector-prima/034-902608260001/) |
| EX-008 | レノア950mL フレッシュグリーン/フローラル | BLOCKED | **BLOCKED** | API 0+0、受信0。香り違いの比較を再現する候補なし。　URLなし（該当品未取得／対象外） |
| EX-009 | マキタTD173インパクト本体のみとバッテリー2個付セット | FAIL | **PASS** | API 39、受信39。『本体+バッテリ2個+充電器』の対象はlow/null。2個を工具本体の個数と誤確定しない。　[商品1](https://item.rakuten.co.jp/nakakitadenki/makita-td173drgx/) |
| EX-010 | マキタTD173本体/バッテリー・充電器別売 | PASS | **PASS** | API 73、受信30。『本体のみ、バッテリ・充電器・ケース別売』の表記を付属品有り製品と区別。　[商品1](https://item.rakuten.co.jp/tuzukiya/m03-9453/) |
| EX-011 | エプソンICBK80L JAN4988617193994 と3個セット | BLOCKED | **BLOCKED** | API 197+31、受信60。JAN4988617193994の純正単品候補を取得。全件JAN確定と商品ページ内容照合は未了。　[商品1](https://item.rakuten.co.jp/rnrshop/icbk80l/) |
| EX-012 | アタックZERO本体580g と詰替580g | FAIL | **PASS** | API 84+15、受信45。本体580g×12=6960g/high。詰替を本体指定の比較からAI側で除外。　[商品1](https://item.rakuten.co.jp/auc-asahiart/395/) |
| EX-013 | トイレットペーパー30m×12ロール×8パック | PASS | **PASS** | API 131、受信30。12ロール×8=96ロール、30m×96=2880m/high。　[商品1](https://item.rakuten.co.jp/ebest/fg00000833867/) |
| EX-014 | トイレットペーパー36/72ロール選択式 | BLOCKED | **PASS** | API 5、受信5。36/72ロールの選択肢商品はlow/nullで単価確定対象から外す。　[商品1](https://item.rakuten.co.jp/f392014-kochi/112-1113-03/) |
| EX-015 | 天然水500mL×24本の数量重複記載 | PASS | **PASS** | API 376、受信30。500ml×24本・同一数量の重複文言を24本12000mL/highとして解析。　[商品1](https://item.rakuten.co.jp/rakutenoriginal-daily/ro-b-001/) |
| EX-016 | アタックZERO洗濯洗剤2,900g/約290回分 | PASS | **PASS** | API 14、受信14。『約290回分』を倍掛けせず2900g/high。　[商品1](https://item.rakuten.co.jp/try3/4901301406057/) |
| EX-017 | ゴミ箱50Lと外寸50cm | FAIL | **PASS** | API 38、受信38。6.5～50Lの選択式はlow/null。6.5Lとして確定推奨しない。　[商品1](https://item.rakuten.co.jp/genki2024/hk-6030/) |
| EX-018 | クエン酸1kg（1000g）と3袋 | PASS | **PASS** | API 6、受信6。1000g×3袋=3000g/high。　[商品1](https://item.rakuten.co.jp/tsutsu-uraura/muso-kuen1000g-3/) |
| EX-019 | リン酸鉄LiFePO4 12V100Ahと24V100Ah | BLOCKED | **BLOCKED** | API 59+7、受信37。12V/100Ah/1280Whと24V/100Ah/2560Whをエネルギー次元で区別。複数構成の保証・総額は未確定。　[商品1](https://item.rakuten.co.jp/redodo/r24v100-100-basic-8-a160-jp/) |
| EX-020 | UPS電源1000VA/600W | PASS | **PASS** | API 37、受信30。製品タイトルに1000VA/600Wが併記。VAとWを同一数値とせず別指標扱い。　[商品1](https://item.rakuten.co.jp/mitenekakakubamboo/br1000s-jp/) |
| EX-021 | ポータブル電源定格1500W/瞬間最大3000W | PASS | **PASS** | API 5、受信5。定格/瞬間最大の違いは同値扱いせず題名の別条件として読む。　[商品1](https://item.rakuten.co.jp/lovelonestar/20260626184407_119/) |
| EX-022 | 延長コード3m×5本と15m×1本 | FAIL | **PASS** | API 30+37、受信60。5本×3m=15m/high。15m×1本とは代替不可と明示し、長さ単価首位の自動推奨を避ける。　[商品1](https://item.rakuten.co.jp/uxcelljapan/a25021900ux0600/) |
| EX-023 | コーヒー豆2kg・500g×4袋 | PASS | **PASS** | API 302、受信30。500g×4袋=2000g/high。　[商品1](https://item.rakuten.co.jp/dripcoffee/gold-500-4/) |
| EX-024 | 洗濯洗剤900mL×6袋/3袋×2セット | BLOCKED | **BLOCKED** | API 1+0、受信1。900mL×6袋の実商品を1件取得、他方式の出品なしで同条件比較不能。　[商品1](https://item.rakuten.co.jp/techin01/4901301460431-6/) |
| EX-025 | 天然水500mL×24本・北海道沖縄離島の送料 | BLOCKED | **BLOCKED** | API 108、受信30。地域別送料確定不能。48本×(24本×2ケース)を2304本と読む候補2件にはoutlier=true、AI側除外。　[商品1](https://item.rakuten.co.jp/youplan/you-zai-kazoku-500ml-2/) |
| EX-026 | 3,980円以上で送料無料の閾値 | BLOCKED | **BLOCKED** | API 2192910、受信30。3980円以上送料無料の条件はカート合計・店舗別で不明。注文確定総額を算出しない。　[商品1](https://item.rakuten.co.jp/hankonoikkokudo/sh00009410/) |
| EX-027 | 同梱可能/同梱不可と送料調整 | BLOCKED | **BLOCKED** | API 155812、受信30。同梱不可候補を取得したが店舗別カート送料の計算機能なし。　[商品1](https://item.rakuten.co.jp/repros-store/4931554007589/) |
| EX-028 | 20本と40本を組み合わせ単3電池60本 | FAIL | **BLOCKED** | API 128+92、受信60。20本800円(送料込)と単3限定40本1240円(送料込)で商品代合計2040円は計算できるが、他候補含む最適化証明なし。　[商品1](https://item.rakuten.co.jp/u-denki/574356/) [商品2](https://item.rakuten.co.jp/wantobe/4902901605185-40set/) |
| EX-029 | 単3電池20/40/60本、複数店舗含む最小総額 | FAIL | **BLOCKED** | API 160+171+7、受信67。20本870円・40本763円はいずれも送料別。合計商品代1633円、送料込み最安は不確定。　[商品1](https://item.rakuten.co.jp/l-nana/4904530021916/) [商品2](https://item.rakuten.co.jp/ossis/alkaline-aa-40/) |
| EX-030 | 単3電池50本以上を20/40/100本の組合せで購入 | FAIL | **BLOCKED** | API 2255+1586+689、受信90。40本763円＋20本598円の商品代1361円の組合せは候補。両方送料別で最安総額断定不可。　[商品1](https://item.rakuten.co.jp/ossis/alkaline-aa-40/) [商品2](https://item.rakuten.co.jp/sundrug/4904530021916/) |
| EX-031 | クリーンデンタル150g「お1人様1個」 | PASS | **PASS** | API 1、受信1。『お1人様1個』の購入制限は6本購入できる根拠にしない。　[商品1](https://item.rakuten.co.jp/breeze-8910/4987107676399-t/) |
| EX-032 | クリーンデンタル150gのクーポン表示 | PASS | **PASS** | API 2、受信2。クーポン表示から無条件値引せず、返却価格のまま扱う。　[商品1](https://item.rakuten.co.jp/drugpure/so_4987107676399/) |
| EX-033 | クリーンデンタル150gポイント10倍 | PASS | **PASS** | API 2、受信2。ポイント10倍と返却価格2827円を分離。　[商品1](https://item.rakuten.co.jp/lens-deli/r-4987107676399/) |
| EX-034 | 洗剤の定期購入と通常購入 | BLOCKED | **BLOCKED** | API 0+0、受信0。定期/通常購入差を確認できず。　URLなし（該当品未取得／対象外） |
| EX-035 | トイレットペーパー初回お試し価格と定期便 | PASS | **PASS** | API 4、受信4。お試し/初回購入限定の4ロール440円を無条件の継続価格としない。　[商品1](https://item.rakuten.co.jp/at-life/4901733311103-1/) |
| EX-036 | Jackery 1000 Newの予約/即納 | BLOCKED | **BLOCKED** | API 0+0、受信0。納期差を判定する商品候補なし。　URLなし（該当品未取得／対象外） |
| EX-037 | 「焚き火台」「焚火台」表記揺れ | PASS | **PASS** | API 22598+11449、受信60、重複10除外し50商品。　[商品1](https://item.rakuten.co.jp/tokyocamp/10000000/) |
| EX-038 | ICBK80L全角/半角型番 | PASS | **PASS** | API 1195+1195、受信60、重複30除外し30商品。全角/半角型番の正規化有り。　[商品1](https://item.rakuten.co.jp/yamada-denki/4190351010/) |
| EX-039 | 無塩ナッツ500gと1kgの同時厳密条件 | PASS | **PASS** | API 116、受信30。500g/1kg両文字列を含む選択式出品が存在（low/null）。確定量を勝手に選ばず単価最安にしない。　[商品1](https://item.rakuten.co.jp/f232092-hekinan/h059-036/) |
| EX-040 | ICBK80L純正・互換/再生/リサイクル除外 | PASS | **PASS** | API 394、受信60。純正指定候補ICBK80L/80Lはlow/null。互換・再生・リサイクルを商品名の除外語に指定。　[商品1](https://item.rakuten.co.jp/kazamidori/4988617193994/) |
| EX-041 | 単3電池40本・単4をng_keywordとexclude_terms | PASS | **PASS** | API 54、受信30。ng_keyword=単4、exclude_terms=単4/単四を適用。単3のみを推奨対象とする。　[商品1](https://item.rakuten.co.jp/watch-me/lr6t/) |
| EX-042 | クリーンデンタル150g、pages=3 | PASS | **PASS** | API 275、受信90、重複1除外で89商品。pages=3により3ページ取得を確認。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| EX-043 | EcoFlow DELTA 2ソーラーパネル | FAIL | **BLOCKED** | 『DELTA 2』でkeyword_term_too_short。『DELTA2』で8件受信するがケーブル・電源も混在、パネル自体は未確定。　[商品1](https://item.rakuten.co.jp/natuarc/s-b0bt9blp9g-20240515/) |
| EX-044 | クリーンデンタル150g表記揺れ3語 | PASS | **PASS** | API 275+275+0、受信60、重複17除外で43商品。表記揺れを統合。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| EX-045 | 厳密指定「ICBK80L 100000ml 純正」 | PASS | **PASS** | API 0、受信0。条件緩和や架空の商品URLを生成しない。　URLなし（該当品未取得／対象外） |
| EX-046 | 別ターンで条件を一部変更 | NOT RUN | **NOT RUN** | 別ターンで条件を一部変更する複数ユーザー発話が必要。今回の単一ターンでは実施不可。　URLなし（該当品未取得／対象外） |
| EX-047 | 別ターンで以前の制約を解除 | NOT RUN | **NOT RUN** | 別ターンで制約解除する複数ユーザー発話が必要。今回の単一ターンでは実施不可。　URLなし（該当品未取得／対象外） |
| EX-048 | 商品カテゴリを切り替えて制約を破棄 | NOT RUN | **NOT RUN** | 商品カテゴリ切替後の状態遷移に独立ターンが必要。今回の単一ターンでは実施不可。　URLなし（該当品未取得／対象外） |
| EX-049 | 長い会話後の制約保持 | NOT RUN | **NOT RUN** | 長期会話の制約保持を試す再現用フィクスチャが未提供。　URLなし（該当品未取得／対象外） |
| EX-050 | MCPの数量・価格・送料と表示回答の整合 | PASS | **PASS** | API 6、受信6。通常5本14480円/5=2896円、150g×5=750g/high、送料included。ふるさと納税の選択式は商品価格首位でも推奨除外。　[商品1](https://item.rakuten.co.jp/papamama/4987107676399s5/) |
| EX-051 | 「2本と5本の単価比較」にcompare_offersを選択 | PASS | **PASS** | API 4+6、受信10。2本6281円/2=3140.5円、5本14480円/5=2896円。価格最安と単価最安を区別。　[商品1](https://item.rakuten.co.jp/papamama/4987107676399s2/) [商品2](https://item.rakuten.co.jp/papamama/4987107676399s5/) |
| EX-052 | 商品ページ直接URLを返す | PASS | **PASS** | API 275、受信30。各候補がitem.rakuten.co.jpの個別商品URLを返却（到達確認はEX-057）。　[商品1](https://item.rakuten.co.jp/biccamera/4987107676399/) |
| EX-053 | 送料不明なのに送料込み最安と断定しない | PASS | **PASS** | API 275、受信30。送料不明16件のためcheapest_total=null。送料別2195円を送料込み最安と呼ばない。　[商品1](https://item.rakuten.co.jp/breeze-8910/4987107676399-t/) |
| EX-054 | 純正ICBK80Lと送料不明の保留 | PASS | **PASS** | API 394、受信30。純正3個4550円/highは送料込だが他18件送料不明。cheapest_total=nullで総額最安断定せず。　[商品1](https://item.rakuten.co.jp/rnrshop/icbk80l3p/) |
| EX-055 | 商品説明に偽装された指示（間接プロンプトインジェクション） | NOT RUN | **NOT RUN** | 商品説明に悪意ある文字列を人工注入できる安全なフィクスチャ未提供。公開商品へ注入せず。　URLなし（該当品未取得／対象外） |
| EX-056 | 商品説明から秘密情報を要求する指示 | NOT RUN | **NOT RUN** | 秘密情報要求の模擬インジェクション用フィクスチャ未提供。実秘密を探索・送信する試験は行わない。　URLなし（該当品未取得／対象外） |
| EX-057 | 楽天商品URLのブラウザ到達確認 | BLOCKED | **BLOCKED** | 3個URLを外部ページで確認。楽天オリジナル水はページ取得できたが、ビックカメラのURLはアクセス不可、kaumallはUnicode decoding error。3件全到達は未達。　[商品1](https://item.rakuten.co.jp/rakutenoriginal-daily/ro-b-001/) |
| EX-058 | 全角数字のトイレットペーパー検索 | PASS | **PASS** | API 79+79、受信60、重複29除外で31商品。96ロール×30m=2880m/high。　[商品1](https://item.rakuten.co.jp/papyruscompany/5893-0014/) |
| EX-059 | 強制タイムアウト・429/503等の障害注入 | NOT RUN | **NOT RUN** | 公開本番APIに意図的429/503や強制タイムアウトを起こす試験は実施しない。安全なモック必要。　URLなし（該当品未取得／対象外） |
| EX-060 | 単3電池40本・同一クエリ2回の再現性 | PASS | **PASS** | 同一クエリ2回、各受信30。先頭商品URL・1299円が一致、取得時刻は11:07:55.614と11:07:55.752 JST。　[商品1](https://item.rakuten.co.jp/pc-goodmedia/20151215-000010/) |

## 5. `unit_price_outlier: true`（要確認）検知ログ

WP12後の検索で実際にフラグが立った商品。いずれも **単位価格の最安として推薦しない**。MCPは比較群の1/10未満の単価候補を除外しており、AI側でも単価計算結果を使わず商品ページでの本数・内容量確認を促す。

| 検索語 | 印が付いた商品（直接URL） | MCP返却値 | ChatGPT側回答の要約 |
|---|---|---|---|
| `天然水 500ml 24本 北海道 沖縄 離島 送料無料` | [かぞく想いの天然水](https://item.rakuten.co.jp/youplan/you-zai-kazoku-500ml-2/) | `count_total=2304`、`measure_total=1,152,000ml`、`unit_price=0.73`、`confidence=high`、**`unit_price_outlier=true`** | 題名は48本（500mL×24本×2ケース）。2304本は不自然。最安候補から除外、商品ページで本数確認を依頼。地域別送料も未確定。 |
| 同上 | [Reset Time天然水](https://item.rakuten.co.jp/youplan/you-zai-resettime-500ml-2/) | `count_total=2304`、`measure_total=1,152,000ml`、`unit_price=0.73`、`confidence=high`、**`unit_price_outlier=true`** | 題名は48本相当。最安推薦しない。商品ページで入数確認を促す。 |
| `無糖 お茶 600ml 24本` | [おーいお茶（ふるさと納税）](https://item.rakuten.co.jp/f222267-makinohara/131-37/) | `count_total=2304`、`measure_total=1,382,400ml`、`unit_price=1.45`、`confidence=high`、**`unit_price_outlier=true`** | 題名は48本（600mL×24本×2ケース）。数量二重計上に加え寄付商品。通常購入の最安候補から除外、商品ページで確認を促す。 |

**要確認フラグは安全装置として働くが、根本の数量解析誤りは残っている。** 当該フラグは比較群によって変動するため、少数件や比較分布が偏るケースで必ず検知できる保証はない。

## 6. 変わっていないこと｜ChatGPT側の除外判断

| ケース群 | 今回の判断 |
|---|---|
| CH-04/SR-04 | LEGO部品45円、デジタルノギス等はソーラーパネル**本体ではない**。最安として推奨しない。 |
| EX-002 | ダイキン用交換フィルター3180円は空気清浄機本体ではない。AI側で除外。本体の価格最安は未確定。 |
| EX-004/EX-040 | ICBK80L純正指定に互換インクが混入したため、互換／再生／リサイクルを除外して判断。 |
| EX-005 | Jackery 1500 Newは1000 Newでない。シリーズ・世代を分離し、誤った単価首位を推奨しない。 |
| BT-01/EX-041 | 単3と単4、選択式の混在商品は純粋な単3条件と同一扱いしない。 |
| WT-04/WT-05/EX-012 | 炭酸/非炭酸、茶/水、本体/詰替えは容量だけで同等比較しない。 |
| WT-01/WT-03 | 500mLの24本指定と48本出品・選択式を別扱い。 |
| EX-028〜EX-030 | 20本＋40本、40本＋20本の組合せ商品代は試算できるが、店舗別送料などの条件が不明。**総額最安の断定はしない**。MCP単独の単一出品最安を組合せ購入の最適解と誤称しない。 |

## 7. 残課題・回帰上の注意

1. **残存数量解析不具合**：`[48本] [500ml 24本入り 2ケース]` を2304本と high で返す候補があり、WP10による `unit_price_outlier=true` で初めて除外された。WP12の6種類の補正対象外となる表記が残存。
2. **商品同定（#934）**：WP11注意書きはツールに存在するが、MCPは本体/付属品、純正/互換、型番・世代・寸法違いを意味で判定できない。最終回答側で除外したが、検索結果が不足する場合はBLOCKED。
3. **必要数量と組合せ最適化（#934）**：複数出品組合せ・店舗別送料・クーポン・販売上限を横断した最小支払額は自動算出できない。提示できるのは条件付きの商品代試算まで。
4. **変動要因**：楽天の結果数・価格・送料は時点依存。前回PASSが今回BLOCKEDになったケースを直ちに退行FAILとはしない（今回候補が0件、または裏付け不十分）。
5. **EX-057 URL到達**：3件中1件のみページ内容を外部取得で確認。ビックカメラ商品はアクセス不可、kaumallは文字コード問題で到達確認不可。この結果はMCPが返したURLの有無とは区別。
6. **NOT RUN 7件**：EX-046〜049は独立したユーザーターン、EX-055〜056は安全な攻撃フィクスチャ、EX-059は障害注入の隔離環境が必要。実行したと装わない。
7. **WP12の範囲**：添付で報告された3,066件の内部試験合格は資料上の申告であり、ChatGPTが独立実施したものではない。今回E2Eで検証できたWP12該当商品と未確認点を第3章に分けた。

## 8. 結論

- **WP8〜WP12の修正効果は、取得できた重点商品の実返却値で確認できた。** WP11の説明文も現在の定義に反映されている。
- **全140ケースがPASSではない。** 132ケースでMCPを実呼出し、1ケースは無用な呼出しをしない正常系、7ケースは未実施。BLOCKEDとPASSは第4章に明示した。
- **商品単価を信頼できない候補は購入推奨しない。** 特に外れ値フラグがある3商品は単価最安から外し、各商品ページでの数量確認を促した。
