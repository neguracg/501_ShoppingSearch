# 調査 2026-11-25 — 応答量の内訳（第2回）・削減候補・ツール説明の更新（ブリッジ#10 の続き・WP21 前調査）

先行: docs/chousa/2026-11-25_yahoo_options_and_response_size.md（A3＝WP18 前の内訳）。本稿は本番（936c50a。WP19 札・WP20 compact text 後）の応答の内訳。**src は変えていない。** 計測スクリプトは data/wp21/（git 管理外）。

## 0. 測り方（同じデータ）
- 入力は依頼の1件（貼るカイロ 60枚・basis=枚・60〜100・rakuten+yahoo・pages=2・standard・exclude 3語）。**実 API は1回だけ**（`data/wp21/capture.py`。生の検索結果＝候補 127 件を pickle に保存）。以後は保存データから `service.compare_offers` を再計算し、本番 MCP と同じに credits を足して `service.bulk_last`・`pydantic_core.to_json`（compact・UTF-8）で測った（`replay_lib.py`）。
- 再計算の全体は **382,327B**（本番の ChatGPT 実測 378,959B と 0.9% 差。構成も一致: groups 235,055・order_plans 70,846・unknown_offers 32,588・to_check 21,788・shortlist 8,303・caveats 3,162・cheapest_price 2,403・cheapest_unit_price 2,391・cheapest_for_quantity 2,107・cheapest_order 999）。
- 保存物の鍵: 楽天の商品 URL の `rafcid=` にアプリ ID が入る（本番の出力にも出る設計＝#1170）。保存した pickle は**同じ長さの X に置換**して残さず、置換後に全体 382,327B が変わらないことを確認。Yahoo の appid は URL に出ない（`appid` 0 件）。.env の値3つが data/wp21 に残っていないことを機械照合した。

## 1. 内訳（compact JSON の UTF-8 バイト。キー名・区切り込み）
`groups[0]` は 235,055B のうち **offers が 201,495B（全体の 52.7%・97 件）**。残りは札 30,093B（order_plans 25,409＋to_check 4,684。92 本）。

`groups[0].offers` の項目別（97 件分の合計）:

| 項目 | B | 全体比 | メモ |
|---|---|---|---|
| caption（説明欄 200 字まで） | 47,760 | 12.5% | 1 件 約 490B。unknown_offers の分は別に 7,294 |
| quantity（入れ子） | 44,553 | 11.7% | 下表 |
| name | 22,784 | 6.0% | 1 件 約 235B |
| url | 8,733 | 2.3% | |
| fetched_at | 4,656 | 1.2% | 全件ほぼ同じ時刻の文字列を 97 回 |
| unit_price_unconfirmed_reasons | 4,594 | 1.2% | |
| matched_keywords | 4,365 | 1.1% | |
| shop_name | 4,087 | 1.1% | |
| shipping_title_conflict | 3,667 | 1.0% | 多くが null |
| unit_price_label / unit_price_status / item_code / unit_price_dimension | 3,395 / 3,190 / 3,150 / 3,007 | 各 0.8〜0.9% | |
| 残り 22 項目（asuraku_*・sale・points_*・shipping_*・price_*・review_* など） | 約 41,000 | 約 11% | 値が null/false の物が大半 |

`quantity` の中（97 件。合計 44,553B）: caption_candidates 7,409・packs 2,807・title_confidence 2,521・content_dimension 2,429・caption_conflict 2,425・caption_candidate 2,425・caption_evidence 2,337・evidence 2,303・content_amount 2,135 ほか。**値が null/false/[]/{} のキー（キー名と区切りだけ）が候補全体（groups[0]＋unknown 計 113 件）で 26,734B。**

最上位側の中身: order_plans 70,846B（75 件。name 18,573・url 6,878・unit_price_unconfirmed_reasons 3,392・shop_name 3,148 …）、unknown_offers 32,588B（16 件。quantity 9,524・caption 7,294・name 2,381）、to_check 21,788B（17 件。conditions 6,212・name 3,187）。

文字列だけを見た時の大きい物（キー名ごと・全出現の合計）: name 68,881B（309 出現）・caption 55,352B（111）・url 17,120B（217）・shop_name 5,883B・item_code 5,291B・条件文 text 4,874B（22）・fetched_at 3,776B（118 出現・毎回約 32B の同じ時刻）。1 個の文字列で最長は shortlist.reading の 853B（1 回だけ）、次が caption の 540〜580B（200 字の上限）、name は最長 331B。

## 2. 同じ商品の情報が何か所に出ているか
候補は 113 品（groups[0].offers 97＋unknown 16）。同じ (mall, item_code) が出る場所の数: **1 か所 30 品・3 か所 71 品（offers＋order_plans＋札）・5 か所 7 品・6 か所 4 品・7 か所 1 品**。場所は groups[0].offers・unknown_offers・order_plans・to_check・cheapest_price・cheapest_unit_price（最上位と groups[0] の2か所）・cheapest_for_quantity・cheapest_order（最上位・groups[0]・shortlist の3か所）・shortlist.unconfirmed_candidates・札（groups[0].order_plans・to_check。ref は除く）。

重複の計り方: 出現の順（offers→unknown→cheapest_*→order_plans→cheapest_order→to_check→shortlist→札）に、**同じ品の同じ項目で値も同じ**もの（キー＋値のバイト）を、最初の1回を除いて数えた。

| 場所 | 重複 B | 主な中身 |
|---|---|---|
| order_plans（最上位。75 件） | 49,298 | offers と同じ name・url・shop_name・url_status・price_*・unit_price_label・reasons |
| 札（groups[0] の order_plans・to_check） | 26,731 | name・mall・item_code・n（ref は除く） |
| to_check | 12,194 | 同上＋order_plans と同じ n の分 |
| shortlist（confirmed 980＋candidates 6,360） | 7,340 | to_check・order_plans の複写（WP18 の設計） |
| cheapest_price / cheapest_unit_price / cheapest_for_quantity | 2,384 / 2,367 / 2,081 | offers の全項目の複写 |
| groups[0].cheapest_unit_price | 2,367 | 最上位 cheapest_unit_price と同じ |
| cheapest_order（最上位）/ groups[0].cheapest_order | 980 / 980 | order_plans の同じ案の複写 |
| **合計** | **106,722（全体の 27.9%）** | 札を除くと 79,991（20.9%） |

項目別: name 46,806（196 出現）・url 9,178（104）・item_code 6,237・unit_price_unconfirmed_reasons 4,555・shop_name 4,396・unit_price_label 3,384・unit_price_status 3,190・mall 3,160・shipping_status 3,005・caption 2,237（4 出現のみ＝説明欄は複写されにくい）。
別の見方: **同じ文字列（40B 以上・同じキー名）が 2 回以上出る分の余り**は 77,264B。最も多い: 同じ name 285B が 16 回（余り 4,275B）、同じ caption 509B が 6 回（余り 2,545B、別の品が同じ売り場の同じ説明を持つ）。

## 3. 削減候補（同じデータで後処理を当てた実測。候補・注文案を1件も捨てない前提）
各候補を `data/wp21/sim.py` の後処理として service の出力関数に差し込み、(a) バイト数、(b) **ブラインド試験 tests/test_blind_*.py（829 件。素の状態で全通過）をそのまま流した結果**、(c) 自作の隣接試験（test_regulars_service・test_wp15b_caption_length・test_wp14・test_wp18_shortlist・test_wp19_dedupe・test_wp20・test_mcp*・test_web*・test_service*。素で 319 通過）を測った。差し込みは src 外（pytest プラグイン）で、リポジトリのファイルは変えていない。

| # | 候補 | 削れる B（382,327 から） | 失う情報・参照の危険 | 当たる試験（模擬の実測） |
|---|---|---|---|---|
| 1 | **caption を、題名で数量が確定し、説明欄を数量の根拠・食い違い・候補に使っていない候補では出さない**（`quantity.confidence=high` かつ `source=title` かつ `caption_evidence`・`caption_conflict`・`caption_candidate` なし。この入力では 113 件中 108 件が該当） | **54,701（−14.3%）** → 327,626 | AI が説明欄の本文（用途・同梱・バリエーションの手がかり・注意書き）を読めなくなる。数量の根拠は `quantity.evidence`・題名のまま。説明欄が必要な候補（数量が確定しない・食い違い）は残る。参照（ref・item_code）は無関係 | ブラインド **0 件**（829 通過）。自作 0 件（regulars_service の caption==200 の試験も通る＝上限は変えない）。SPEC の caption の記述と、Web・CLI が `caption` を読むか（同じ `offer_to_dict` を使う）を実装前に要確認。B 分類（出力の変更） |
| 1' | caption を 100 字に短縮（同じ候補全部） | 26,993（−7.1%） | 先頭 100 字だけ。条件の分け方が無く全候補で一律に失う | ブラインド 0 件。**自作 1 件**: test_regulars_service::test_search_products_caption_truncated（長さ==200） |
| 2 | 既定値（null/false/[]/{}）のキーのうち、**ブラインド試験が一度も名指しせず、SPEC が必須としないキーだけ**を省く（offers の asuraku_closing_time・asuraku_flag・points_rate・sale・shipping_fee・shipping_title_conflict・unit_price_dimension と quantity.caption_candidate） | 17,360（−4.5%） → 364,967 | 情報は失わない（キー無し＝null と読む）。AI が「キーが無い」を「不明」と読み違える危険は小さい。Web・CLI は `.get`・jinja で許容（要確認） | ブラインド 0 件・自作 0 件。SPEC に「常に出す」と書いたキー（packs・caption_candidates 等）は対象外 |
| 3 | groups[0] の札を `{ref, item_code}` だけに（name・mall・n を落とす） | 23,794（−6.2%） | 札だけでは何の商品か読めず、ref を引かないと分からない（WP19 で name を残した理由）。最上位の同じ要素へは今のまま辿れる | ブラインド **1 件**: test_blind_wp15b::test_q19_other_group_keeps_its_own_result_and_none_is_not_assumed（`groups[].to_check` の `p["name"]`）。自作 1 件: test_wp19_dedupe。SPEC Q26・AC28 を改訂 |
| 4 | order_plans・to_check の識別項目（name・url・shop_name・url_status・price_min/max/varies）を落として offers を引かせる | 40,414（−10.6%） → 341,913 | **最上位は結論側で AI が最初に読む場所**。name・url が無いと回答の組み立てに offers の全走査が要る＝参照を解決できず取り違える危険が最大 | ブラインド **34 件**（test_q23_*・test_ac18_*・test_ac20_*・test_q19_*・test_ac21_/22_/23_ ほか。plans の name・価格を直接読む） |
| 5 | cheapest_* の複製を札に（5a: groups[0].cheapest_unit_price・cheapest_order だけ。5b: 最上位の cheapest_price/unit_price/for_quantity も） | 5a 3,181（−0.8%）／5b 6,578（−1.7%） | 最安の欄が札だけになり、先頭で読める 4 種の最安の価格が見えなくなる | ブラインド 5a **18 件**・5b **26 件**（test_ac17_*・test_ac19_/20_*・test_guarantee_unconfirmed_never_selected_across_three_entrances・test_ac21〜24_*） |
| 参考 | 既定値のキーを全て省く（上の 2 を超えて） | 62,116（−16.2%）。offers だけ 27,932・quantity だけ 27,633 | 項目の有無が候補ごとに変わる。AC17 のキー一貫性（Q21 の4キー）を自分で破る | ブラインド **67 件**（quantity だけで 57 件・offers だけで 6 件） |

組み合わせ: **1＋2 で 310,266B（−72,061B・−18.8%）。ブラインド 829 件＋自作の隣接 151 件が全通過**（模擬）。1＋2＋quantity の既定値省略は 285,558B だがブラインド 57 件に当たる。

### 推奨（1 つ）: 候補 1（caption の条件付き省略）
- 理由: 候補を1件も減らさず、確定判定・ref・並びに触れず、**ブラインド試験に当たらない**（829 通過）うえ、単独で 14.3% 削れる最大の物。条件（題名で確定・説明欄が根拠に使われていない）で絞るので、説明欄が要る候補は残る。コードは `offer_to_dict` の1箇所の条件分岐＋SPEC の caption の記述の改訂で済み、設計の変更ではない。候補 2 は情報を失わないが 4.5% と小さいので、同じ変更に便乗させるかは別判断。
- 小さい効果に大きな設計変更はしない観点で外した物: 3（−6.2% で札の意味が弱くなる）・4・5（ブラインドに多数当たり、効果に釣り合わない）。
- **デメリット（直した時に失う物）**: 説明欄を AI が読めなくなる＝「ふるさと納税」「選べる枚数」など題名に出ない手がかりを AI が拾えなくなる（その種の判定はアプリ側にも無い）。Yahoo の選択肢の手がかりも説明欄にある場合がある（先行調査 A1: 説明欄に選択系の語がある hit は 21%）。
- **効果の限界**: 1＋2 でも約 31 万 B で桁は変わらない。ChatGPT 側の切り詰めの位置・上限は未確認（推測）で、削っても「切られなくなる」とは言えない。groups[0].offers（201,495B）は ref の行き先なので、全量保持の前提では 2 割弱が実質の下限。
- この入力の偏り: 題名に「60枚」と書かれた候補が大半（108/113）なので caption の省略率が高い。数量が曖昧な検索語では省略が減る（効果は検索ごとに変わる）。実測は 1 データだけ。

## 4. ChatGPT のツール説明が旧来の文面だった件（本番の tools/list）
本番の公開 MCP を VPS 内から読み取りだけで確認（`data/wp21/tools_list_remote.sh`・`initialize_remote.sh`。2026-11-25 午後。936c50a 稼働中）。
- **tools/list の compare_offers の説明（1,996 字）**: `shortlist` は **0 回**、`札` 1 回・`ref` 1 回（「groups[0] の注文案は最上位への札 ref」）。`to_check` 3・`order_plans` 2・`cheapest_order` 4。**`shortlist` は WP18 から説明には入れず（2000 字制限）、INSTRUCTIONS（initialize の instructions。4,388 字）にだけ書いている**: `shortlist` 2・`confirmed_cheapest` 1・`unconfirmed_candidates` 1・`札` 1。つまり説明に shortlist が無いのは仕様どおりで、旧版の証拠ではない。**ref の言及（WP19 以降の説明）が ChatGPT の表示に無かった**のが、旧版の表示だった根拠になる（旧版＝WP19 前の説明には札・ref の語が無い。この表示そのものは私は見ておらず、報告の記述に依る）。
- **ChatGPT のコネクタがいつ更新するか**: OpenAI の公式（Apps SDK「Connect from ChatGPT」の *Refresh metadata* 節）は、ツール名・説明・スキーマ・注釈などを変えた後はサーバーをデプロイし、ChatGPT の接続の設定で **Refresh を選んで**メタデータの変更を確かめ、**新しい会話**でテストし直す、という手動の手順を示す。適用範囲は「ChatGPT に直接つないだカスタム MCP サーバー」と明記。開発者モードの公式ガイドは、設定でアプリを refresh すると「新しいツール・説明・サーバー指示（instructions）」を MCP サーバーから取り込むと書く。**自動で再取得する時期（間隔・新規会話ごと・何時間か）についての記述は、どちらにも無い（未確認）**。リフレッシュを呼ぶ公開 API は無く、機能要望が出ている段階（コミュニティ投稿）。
- 結論: ChatGPT が表示したツール説明が旧文面で、呼び出しの応答は新形式だったのは、**ツールの呼び出しは稼働中のサーバーへ届くが、ツール説明・instructions はコネクタ登録時か最後の Refresh 時の写しを使う**ことと整合する（公式が自動更新を保証していない以上、デプロイ後に腱さんのコネクタで **Refresh する**のが確実。**自動更新の有無・間隔は未確認**）。INSTRUCTIONS の更新（shortlist の読み方）も Refresh で入る（公式ガイドが「server instructions」も refresh 対象と書く）。
- 出典: https://developers.openai.com/apps-sdk/deploy/connect-chatgpt （Refresh metadata 節。2026-11-25 取得）／ https://developers.openai.com/api/docs/guides/developer-mode （Manage tools 節。同日）／ https://community.openai.com/t/feature-request-public-api-for-refreshing-a-developer-mcp-apps-actions-in-chatgpt/1395374 （検索結果の見出しのみ。本文は未取得）。

## 5. 残った不確実
- 計測は 1 データ（127 件）。件数・題名で caption の省略率・重複量は変わる。
- 削減候補の「当たる試験」は、出力の後処理を差し込んだ模擬の実測（src 無変更）。実装すると SPEC・自作試験の改訂は別に要る。候補 1 は SPEC の caption 記述と AC を実装前に読み直す（本調査では条文は未照合）。
- ChatGPT の切り詰め位置・トークン上限、説明の自動更新の間隔: 未確認。
