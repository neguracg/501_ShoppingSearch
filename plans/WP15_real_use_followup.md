# 指示書 WP15 — 実利用3件の再実行で残った4点（未確定単価・項目単位の補完・購入単位・MCP定義）

## 目的

腱さんの依頼（2026-11-21 00:55「楽天プラグイン改修後の3チャット検証」の CC への追加改修依頼。原文はこの指示書の末尾に引用）。
合否の観点は原文どおり3つ: **「誤った単価を出さなくなったか」「以前落ちた有力候補を拾えたか」「ユーザーが本数換算や引数指定をせずに済むか」**。

## カイシュウ5問

1. 同じ知識の場所: 確認済みの判定＝`pricing.unconfirmed_reasons`/`is_confirmed`（唯一）。候補・注文案の dict＝`service`（`offer_to_dict` 相当・`order_plan_to_dict`）。説明欄の読み取り＝`caption_quantity.read_offer_quantity`（唯一の入口）。数え語の解決＝`inputs.resolve_compare_basis`。ツール説明の文＝`mcp_server._ORDER_GUIDE`/`_SEARCH_GUIDE`/`_ORDER_POINTER`/`_NOT_JUDGED`。表示＝`web_view`・`cli.py`。
2. 同種の既存機能: 未確定の扱いは WP10（外れ値）・WP14 W1（price_varies）・W4（caption）・C（caption_conflict）がすべて同じ `unconfirmed_reasons` を通る。今回の「明細に確定値として残る」は4理由すべてに効かせる（1理由だけ直さない）。出力面は MCP（公開・stdio）・Web・CLI の3つ。
3. 引っ越し: 該当なし。
4. 過去の記録: BUGLOG A1〜A6（題名規則の足し算で誤りが増えた）、WP11-2（説明文の全文照合は入れない）、WP14 W4 実測（補完の誤り 10% 超→確認済みにしない前提で出荷）、WP14 D（捨てた数1の除外は誤り1件で撤回・択一の標識が続く1は外さない変形は 12件・誤り0で未適用）。**題名の規則を足して直さない**のが既定。
5. 所有モジュール: U1＝pricing（判定）＋service（dict）＋表示2つ。U2＝caption_quantity（補完）。yumenokoya の変形だけ quantity.py。U3＝新しく数え語の換算を持つ所（pricing の中に閉じるか、`counter_basis.py` 等の新所有単位。pricing は 576 行で概念が混ざり始めているので**新モジュール推奨**）。U4＝mcp_server・service（dict のキー）。

## 改修前の固定（済み・オーケストレータ）

- 実 API の生応答を録画済み: 作業ツリーの `data/wp15/store.json`（.gitignore 対象。公開リポジトリに入れない。worktree 撤去前に本体の `data/wp15/` へ移す）。
- 録画・再生の道具: `data/wp15/record.py`（`python data/wp15/record.py replay data/wp15/store.json data/wp15/after [case...]` を作業ツリーのルートで実行すると、同じ生応答で compare_offers を流し直す）。改修前の出力は `data/wp15/before/`。`data/wp15/find.py` の TOP 行は最上位を読んでおり誤り（値は `comparison` の下）なので、比較表に使う前に直す。
- 録画済みのケース: カイロ（`貼るカイロ`・basis 個／枚・50〜100・standard／+itemPrice・下限だけ）、文化たきつけ（本 540・袋 30・自動 30）、スコッティ（`スコッティ トイレットペーパー`+シングル・ロール 48・m、`スコッティ シングル 48ロール`）。
- **録画に無い名指しの例**: カイロ「90枚 3箱」とゴダイ（送料別 1,077円・個）は `貼るカイロ` の3ページに出ていない。`record.py` の CASES に検索語を足して（例: `貼るカイロ 90枚`・`使い捨てカイロ 貼る`・`カイロ ゴダイ`）**最初に録画を追加**し、見つけた item_code をこの指示書の末尾に書き足す。見つからなければ構成した Offer で試験し、その旨を報告。

## 作業単位（この順。各単位ごとに commit・WORKLOG 1行。SPEC は同じコミットで直す＝B分類）

### U1 未確定の単価を確定値として出さない（最優先・①）

問題: 確認済みでない候補も dict の `unit_price`・`order_unit_price`・`quantity.confidence="high"` が素の値で出るので、明細を読んだ AI が「11.30円／枚」「25円」と断定する（ランキングからは外れているのに）。

- 単価の未確定理由＝`unconfirmed_reasons` のうち**送料以外**（`quantity_from_caption`・`caption_conflict`・`price_varies`・`unit_price_outlier`、U2・U3 で足す理由も）。送料別は単価の誤りではないので対象外（単価はそのまま出す）。
- 候補の dict（groups[].offers・unknown_offers・cheapest_* 等、候補を出す全箇所）: 単価が未確定なら **`unit_price` は null**、計算値は **`provisional_unit_price`**、`unit_price_status`＝`"confirmed"`/`"unconfirmed"`（単価なしは `"unknown"`）、`unit_price_unconfirmed_reasons`。確認済みなら今までどおり `unit_price` に値・`provisional_unit_price` は null。
- 注文案の dict（order_plans・cheapest_order・to_check）: 同様に未確定なら `order_unit_price` null・`provisional_order_unit_price` に値。`order_total` の扱いは U4。
- `caption_conflict` の候補の `quantity.confidence` は出力で `"conflict"` にし、題名の判定は `quantity.title_confidence`（"high"）に残す（内部の QuantityInfo.confidence は変えない＝題名コーパス・ブラインドの数量の出力は不変）。
- 並び（groups の単価順）・外れ値の判定・to_check の閾値は**内部の計算値**で今までどおり（出力のキーだけ変える）。
- Web・CLI: 未確定の単価は「仮 25.00円/枚（選択肢で価格が変わる）」のように仮と理由を付ける。
- MCP の説明: 「`unit_price` が null で `provisional_unit_price` がある候補の単価を確定値として伝えない」を `_ORDER_GUIDE` に1文（説明文 2000 字ガードを守る）。
- 受入: 再生した全ケースの出力 JSON を走査し、`unit_price_unconfirmed_reasons` が空でない候補・案に**素の `unit_price`/`order_unit_price` の数値が 0 件**であること（試験に固定）。unidy:10972223 は `unit_price=null`・`provisional_unit_price=25.0`。

### U2 題名と説明欄を項目単位で補う（②）

- **項目単位の補完**: 題名が high で**個数だけ**（count_total あり・content_amount なし）、説明欄の見出し付きの値が**個数を含まない内容量1つだけ**（例 `長さ：100mシングル`）の時、1個あたりの内容量として重ね、measure_total＝count_total×内容量。cocodecow:10392423（12ロール×4パック）＋`長さ：100m`→48ロール・100m/ロール・4,800m。
- **自動 basis（Q7）の過半の分母は題名由来の内容量だけで数える**（説明欄で補った内容量で 個→m に変わらない）。受入: 再生の `scottie2`・`scottie` で basis が前後不変。
- 既存見出し（内容量・容量）の「個数の無い値」（`内容量：2L`）は、題名が個数 high の時も**対象にしない**（1個あたりかケース全体か決められない＝SPEC W4 の記録のまま）。対象は新しく足す見出しだけ。
- 見出し: `長さ` を足す（依頼の対象）。`重さ`・`重量` は総重量・梱包重量の記述が多いので、33 語の実測で見出し別に誤り率を出し、10% 以下の時だけ足す（`幅`・`サイズ` は足さない＝紙幅 108mm を長さと読まない）。値の次元は1つ（m と mm が混ざる値は採らない）。単位あたりの言い回し・関連キーワード以降・はこちら・別選択肢（`price_varies` には補わない）は W4 のまま除外。見出しが複数あれば同じ値の時だけ。
- 補った内容量は `quantity.source="title+caption"`・`caption_evidence`、未確定理由 `measure_from_caption`（U1 により単価は仮）。題名の個数は確認済みのまま（basis が個・ロールの比較は今までどおり確認済みで出る）。**紙幅などの同一規格は判定しない**（caption の照合は呼び出し側＝§10 のまま）。
- yumenokoya:39998092（`48ロール` と `1セットには…12ロール×4パック` で low）: WP14 D の「択一の標識が続く 1 は外さない変形」（12件・誤り0・未適用）を、実題名を取り直して（WP14 D と同じ 33 検索×3 ページ規模）測り、**誤った high が 0 件なら適用**、1件でも出たら適用しない（WP14 D と同じ撤回基準）。題名コーパス 480 件の出力は不変であること。
- 実測（必須・報告に表）: WP14 W4 と同じ 33 語で、項目単位の補完が起きた件数・人が見て誤り件数。誤りが補完の 10% を超えたら、補完せず `caption_measure_candidate` の印と根拠だけに縮めて報告で止める（W4 と同じ基準。未確定なので害は条件文に閉じるが、基準は守る）。

### U3 購入単位を保ったまま比べる（③）

問題: 「18本入 2袋セット」が 36本 high で、basis=袋 では袋の数が失われ、25件すべて比較不能。カイロの 枚／個 は別グループに分かれ、個で数える安い候補が主候補から漏れる。

- **外側の数（包装の数）を保持**: 題名が `N<数え語>入(り) M<包装語>(セット|パック|入)?` ／ `N<数え語>×M<包装語>`（`18本入 2袋セット`・`36本（18本×2個セット）`・`18本入り×2袋`）で読めた時、総数（36本）に加えて `quantity.packs=[{"unit":"袋","count":2,"per_pack":18,"per_pack_unit":"本"}]` を返す（quantity.py の総数・confidence・既存のキーの出力は**不変**＝キーの追加だけ。読めた形は総数の読み取りと同じ根拠の位置から取る。新しい総数の規則は足さない）。
- **basis に数え語（例 袋）を指定した時**: (a) count_unit がその数え語の候補（今まで通り）＋ (b) `packs` にその数え語がある候補（袋の数＝packs の count）を同じグループで比べる。**確認済みで横並びにするのは 1袋の中身（per_pack・per_pack_unit）が一致する候補どうしだけ**（9本入 2袋 と 18本入 2袋 を同じ「2袋」で確認済みの最安競争に入れない）。基準の per_pack は packs を持つ候補の最多値（同数なら確認済みの最安の注文額が安い方）で、食い違う候補は未確定理由 `pack_content_differs` で to_check（「1袋の中身が違う（9本入）」）。受入に固定。(c) それ以外で数え語が違う候補（本だけ・セット・個 など）と数量 none の候補は捨てずに、**換算の仮定つきで to_check に出す**: 他の候補の packs から「1袋＝18本」がただ1通りに決まる時は「1袋が18本なら」で本の候補を袋に換算（例 180本×3＝30袋相当）、決まらない／数量 none の時は「この商品1点が1袋なら」。未確定理由 `counter_assumed`（U1 により単価は仮。cheapest_order には選ばない）。ヤマキシ 168円（数量 none・送料別）、Mayfair「60セット入り 1箱」もこの扱いで残る（送料の条件と合算した1文。WP14 B3 の書式）。
- **basis 自動（個）で数え語が複数**: 主グループ（Q19）はそのまま。主グループと違う数え語の候補は、**同じ販売単位だと裏付けがある時だけ**主グループに入れる。裏付け＝その候補の説明欄の見出し付きの値に主グループの数え語で**同じ数**がある（例 題名 30個・説明欄 `入数：30枚`）。入れた候補は未確定理由 `counter_from_caption`。裏付けが無い候補は今まで通り別グループで、主グループの cheapest_order より安い時は主グループの to_check に「1個が1枚なら」の条件つきで出す（`counter_assumed`）。ゴダイ（送料別 1,077円・個）が to_check に出ること。
- desired_quantity は basis の数え語で解釈（30袋は 30袋のまま。本への換算を利用者・呼び出し側に求めない）。`文化たきつけ` basis=袋・desired=30 で、cololo「18本入 2袋セット」（15個注文）・Mayfair「36本（18本×2個セット）」は個＝袋の裏付けが無いので to_check、を含め**候補ゼロにならない**こと。
- caveats: 換算の仮定を置いた件数と「1袋＝18本は候補 N件の商品名から」の根拠。
- MCP の説明・SPEC §10(3) の「18本入りを30袋は basis=本・desired=540」を「basis=袋・desired=30 のままでよい」に改める。

### U4 公開 MCP の定義と挙動を揃える（④）

- **定義の層を実測して報告**: (1) ソース (2) 本番 `https://app.negura.website/kaimono/mcp` の `tools/list`（tests/test_mcp_http.py と同じ initialize→tools/list の手順。外部送信の許可が要る場合はオーケストレータに戻す） (3) ChatGPT が持つ定義（腱さんの画面。コネクタの再読込が要るかは腱さんの作業）。本番 6745ea8 に `desired_quantity_max` があるのに ChatGPT に無いなら (3) のキャッシュ。
- 説明文の更新（2000 字ガード内）: `compare_offers` の冒頭「商品名から読んだ数量」を「商品名（足りない項目は説明欄の見出し付きの値）から読んだ数量」に。U1 の `provisional_unit_price`、U3 の basis=数え語のまま比べられること、`desired_quantity_max` の使い方を要点に。`search_products` の quantity の説明も同様。
- **注文額の意味を読める形に**: 注文案に `payment_total`（送料込みの時だけ order_total と同じ値・送料別／不明は null）と `order_total_kind`（`"payment_total"`＝送料込み／`"item_subtotal"`＝送料別・不明の商品小計）を足す。Web・CLI は送料別の注文額を「商品小計（送料別）」と表示。MCP 説明に「order_total_kind が item_subtotal の金額を支払総額と呼ばない」。
- 受入: MCP の in-process 試験で、`tools/list` の compare_offers に `desired_quantity_max` があること、説明が 2000 字以内、「貼るカイロ」・`desired_quantity=50`・`desired_quantity_max=100` で範囲内の注文だけが返る（240枚品が cheapest_order・order_plans に入らない）こと。

## 試験・検証の順（金額ロジック＝重大領域）

**2段に分ける**（測定で撤回があり得る単位の SPEC・ブラインド試験を先に固定しない）。

- **段A（U1＋U4）**: SPEC 改訂 → tester → implementer → verifier → 本番反映（腱さん承認不要の運用アプリではない＝公開ツール。従来どおりデプロイ）。
- **段B（U2・yumenokoya の変形・U3）**: 実測（再生と 33 語）→ 結果で規則を確定 → SPEC 改訂 → tester → implementer → verifier。

各段の手順:
1. SPEC 改訂（文書のみで commit）。**改訂前に `unit_price`・`confidence`・`order_total`・`caption`・`basis=本`・`540` を SPEC・README・tests で grep し、ぶつかる行を全部直す**。最低限、段A: §8 price_varies の項と AC13 の「単価は表示価格で出す」、Q3・Q8・Q14 の `unit_price` の意味、Q16 の dict キー（`provisional_order_unit_price`・`payment_total`・`order_total_kind`）、§10、AC17（未確定単価）・AC18（注文額の種類）を新設。段B: §7 W4 と AC16 の「題名 none の時だけ」「個数の無い値は読まない」、Q7、Q19、Q20 の例（basis=本・540）と AC15、AC19・AC20 を新設。
2. tester がブラインド試験を SPEC から更新（implementer は読まない・編集しない）。
3. implementer が実装。各単位で `.venv\Scripts\python -m pytest -q` 全件と題名コーパス 480 件（不変）。
4. 再生（`record.py replay`）で before／after を並べた表: ケースごとに「何を推薦し、何を保留し、なぜか」。名指しの例（unidy:10972223・cocodecow:10392423・yumenokoya:39998092・cololo:10000025・mayfair-17:10014877・mayfair-17:10014885・yamakishi:10059276・90枚3箱・ゴダイ）の前後。U1 の受入走査は groups・unknown_offers・cheapest_* の全枠・注文案・`search_products` の quantity・定番品（regulars）を含める。
5. verifier の独立レビュー。

録画の控え: `store.json` と `before\` は取り直せないので、作業ツリーの `data/wp15/`（.gitignore 対象）へ複写済み。

## 腱さんの依頼の原文（引用）

```text
楽天商品比較プラグインの改修後、3チャットの再実行と現行MCPの追試で以下が残った。優先順に改修してほしい。設計・実装方式は任せる。

① 数量矛盾・選択肢価格未確定時の単価
カイロ「90枚 3箱」は説明欄との不整合を検知しても270枚・high・11.30円/枚が残る。unidy:10972223 は1,500〜1,720円を検知して最安から除外したが、明細にはunit_price=25が残る。商品明細・ランキング・チャット回答を通して、未確定単価を確定値として扱わせない。

② タイトルと説明欄を項目単位で補完
https://item.rakuten.co.jp/cocodecow/rj2228/
タイトルで12ロール×4＝48ロール、説明に「長さ：100mシングル」がある。期待は48ロール・100m/ロール・合計4,800m。紙幅108mmの同一規格判定は別扱い。
yumenokoya:39998092 も「48ロール」と「12ロール×4パック」の整合を拾えずlowのまま。使用例、関連商品、別選択肢の数値は混ぜない。

③ 購入単位を維持
文化たきつけは「30袋＝540本」と呼び出すと比較できるが、basis=袋・desired_quantity=30では25件中候補ゼロ。「18本入 2袋セット」のような商品で外側の袋数と中身の本数を保持し、袋指定のまま注文比較できるようにする。ヤマキシ168円、Mayfair「60セット入り 1箱」も、根拠が不足するなら確認条件つきで残す。カイロの枚・個は同一販売単位だと裏付けられる候補だけ横断比較する。

④ 公開MCP定義と実挙動を同期
このセッションの公開引数にdesired_quantity_maxがなく、説明もタイトル解析のみの旧内容。通常の新規チャットから「貼るカイロ50〜100枚」で上限が伝わり、範囲内で送料込み単価・注文総額を比較できることを確認する。送料別のorder_totalは商品小計だと読み取れるようにする。

受入は固定した実例で改修前後を比較し、最後に通常チャットから再実行。「誤った単価を出さなくなったか」「以前落ちた有力候補を拾えたか」「ユーザーが本数換算や引数指定をせずに済むか」で結果を報告してほしい。
```

## 見つけた item_code（録画追加後に書き足す）

- （implementer が追記）
