# HANDOFF — 501_RakutenSearch（2026-11-05 時点）

## 状態
- Phase 1（楽天検索・数量の読み取り・単価比較・MCP・CLI）と Phase 1.5（公開Web と リモートMCP `{BASE}/mcp`）は実装済み。WP2（公開Web）・WP3（数量・比較のカテゴリ非依存化）・WP4（数量読み取りの強化 S1〜S11・W1〜W5）・WP5（数量の信頼度を「解釈の一致」で決める P0〜P4・X1〜X5）・WP6（数え語の直後の境界 P5〜P7）・WP7（P5 の捨てた数の検査の除外を3型の組に限定・コーパス383件・既知の限界 R1〜R3 を SPEC §7 に明記）も実装済み（WP5〜WP7 は verifier の再確認待ち）。**題名の読み取りの規則追加は WP7 で打ち止め**。E2E 80件（実題名）の測定が済み、WP8 で P0 違反（採らなかった候補の取りこぼし）を low に倒す修正と、楽天が HTTP 400 にする『1文字だけの語』の事前検査（keyword_term_too_short）を入れた（打ち止めは P0 違反を low に倒す修正に限って解除。商品の意味の扱いは腱さんの判断待ち）。**master へマージ・push 済み（e95dd04。worktree 撤去済み）**。WP7 は verifier 未レビュー。**2026-11-05 23:10 公開済み**: https://app.negura.website/kaimono/（VPS /opt/apps/kaimono・ホストポート 8014・Tunnel ingress 追加・実 API の比較 200 を確認）。GitHub リポジトリ名は 501_ShoppingSearch に変更済み（ローカルのフォルダ名は旧名のまま。改名キットは下記）。
- 試験: `.venv\Scripts\python -m pytest -q` が全件 green（2919 passed 以上。うちブラインド独立試験 = tests/test_blind_generic_quantity.py 416 件。tester が固定した物で、implementer は読まない・編集しない。実行は件数だけ `-q --tb=no`）。題名コーパス AC-Q1 = tests/test_title_corpus.py（452 件〔WP12 で unseen7 の 31 件を追加。単価不明の上限は 20%→22%。元の 421 件は 18.3% のまま〕＝title_patterns 232・unseen1 71・unseen2 40・unseen3 40・unseen4 7〔E2E 実題名 T1〜T7〕・unseen5 17〔verifier 退行形 B1〜B6〕・unseen6 14〔追加E2E 実題名 E1・E2 と verifier B8〕・unseen7 31〔WP12 実題名 M1〜M4・構成した M5〕。高信頼の誤り 0（焼き鳥 1件は既知の限界 R2 で xfail）・単価不明 77件＝約 18.3%（元の 421 件。452 件では 92 件＝約 20.4%）、2026-11-09 実測。既存 421 件の出力は WP12 の前後で不変）。
- 正本: docs/SPEC.md（AC1〜AC12、公開Web は AC-W1〜W11）、指示書: plans/WP3〜WP9（最新は plans/WP9_ex_real_title_highs.md）、経緯: docs/WORKLOG.md / DECISIONS.md / BUGLOG.md。
- 数量の高信頼は「全ての読み方が同じ総数を指す時だけ」（SPEC §7 P0）。誤読は『偽の最安』ではなく『単価不明』に倒す。数量の規則を足す前に P0〜P7 と矛盾しないか見る（足し算で誤り 16→50 件に悪化した経緯は BUGLOG A1・A1′・A2・A3・A4・A5）。数え語は直後の文字で個数かを決める（P5。語ごとの除外リストを足さない）。単価の丸め・整形は pricing.py が持つ。
- 道具は商品の意味を持たない（SPEC §7・§8）。持つのは「個数×内容量の読み取りと単位換算（quantity.py の UNITS / DISPLAY / COUNTERS 表）」と「含む語・除く語での絞り込み」だけ。仕様の違い（濃縮・層数・型番・色など）は判定せず、数量は商品名からの読み取りで誤ることがある旨とあわせて、caveats に常に2行出す。
- **WP11（worktree wp11-desc-caption・本番未反映・レビュー前）**: ①ツール説明（search_products・compare_offers）に『商品の種類・仕様は判定しない／confidence が high でない・unit_price_outlier の候補は最安・おすすめにしない／送料不明を送料込み最安と呼ばない』を追加（mcp_server._NOT_JUDGED・SPEC §10）。②商品説明文を数量の2つ目の読み取り元にする案を実 API で測り『入れない』が推奨（docs/WORKLOG.md の WP11-2 行。説明文の食い違いの本当の誤りは 12%）。③1 文字の語の誤り文を実際に弾いた語・直前の語につないだ形にした（inputs.too_short_message・SPEC §10 は入力の全文を入れない原則の例外を明記）。④単独の内容量の数字が型番の語（IC6CL80・FAC580）の内側にも現れる時は low（SPEC R8。容量が型番に入る電源・充電器も low になるトレードオフ）。指示書: plans/WP11_tool_desc_and_caption_probe.md。
- **WP12（worktree wp12-new-misreads・本番未反映・レビュー前）**: WP11-2 の実測で見つかった商品名の誤読4種と、日本語に接した型番を low（または個数だけの high）に倒した（SPEC §7 P0 の徹底〔WP12〕①〜⑤・R8。quantity.py だけ）。①範囲の量（体重 4~8kg・お誕生~5,000g）は内容量にしない／範囲の個数（3~5箱）は low／型番の語に付いたサイズ記号の個数（S54枚×4パック(216枚)・M52枚×4個入）を読み飛ばした連結位置は low ②量/単位の分子（42.5mg/L）は内容量にしない ③個数が別の次元の量の鎖に付き、採用する次元の量が個数と別の鎖にある時は low（2000m 2L×6本） ④単位の直後に装飾記号（2M◇）は low ⑤型番の語を『空白・日本語・読点で切った ASCII の連なり』へ広げた（インクIC6CL80・IC6CL80互換80L）。M4 の原因は指示書の疑い（`単4` との結合）ではなく、題名末尾の店の符号 `2M◇` を 2m と読んだこと。実題名は tests/corpus/unseen7_patterns.py（M5 だけ今の API に該当の題名が無く構成）。コーパス 421 件の出力は変わらない。決定済み（オーケストレータ）: 範囲の体重を捨てた結果、`4kg〜8kg` の紙おむつ 38 件が low→個数だけの high になった（個数は正しい）。(a) で決定＝この挙動を採る（範囲を見たら必ず low にする案は採らない）。型番の語に付いたサイズ記号の個数（S54枚・NB60枚）は空白でつないだ形（`S54枚 4パック`）も、捨てた数として総数と食い違えば low（verifier B11）。指示書: plans/WP12_new_misreads.md。
- **WP10（単価の外れ値の網。実装・試験済み・本番未反映）**: 単位価格が出ている候補が 4 件以上ある比較グループで、単位価格が中央値の 1/10 未満の候補（`Offer.unit_price_outlier`）を「数量の読み違いの疑い」として `cheapest_unit_price`・`cheapest_for_quantity` から外す（一覧には残し、公開Web・公開MCP・CLI に要確認の表示、caveats に件数）。判定は `pricing.mark_unit_price_outliers` の1か所。N=4・K=10 は実 API 99 検索・1,429 件の実測表で決めた（SPEC §8「単価の外れ値の N・K」。K=10→20 で誤検知 6→1・取りこぼし +3）。拾えるのは桁違いの誤り（R7 の `ICBK80L 80L×2個` など）で、3 倍程度の誤り（R5）は拾えない。試験 tests/test_wp10_outlier.py（27 件）。

## 次にやること（順番）
0. **WP8〜WP12 は本番反映済み（本番 761dd6d・2026-11-09 03:14）**: WP8＝E2E 80件の数量の誤読6件と半角1文字の語の HTTP 400、WP9＝追加E2E 60件の型番 80L・構成品の個数、WP10＝単価が群の中央値の 1/10 未満の候補を『要確認』にして単位価格の最安・必要数量の最安から外す網（N=4・K=10、根拠は SPEC §8）。WP11＝ツール説明の強化・1文字の語の誤り文に実際の語・型番の数字と同じ数字の単独の量を low（商品説明文の照合は実測の結果入れない）。WP12（商品名の新しい誤読4種＋日本語に接した型番）は実装済み・本番未反映・レビュー待ち（上の WP12 の項）。残りは、腱さんの ChatGPT で E2E 全件の再実施（消込表 #935）。商品の種類・仕様の扱いは #934 の回答待ち。2〜5倍の誤読（R5・約4倍の二重計上）はこの網でも拾えない（既知の限界）。
1. ChatGPT（Plus）からの実接続（消込表 #923。腱さん）。
2. 実題名での高信頼の誤り率の測定（公開アプリで10検索語程度。high の個数・総量を目視）と、WP7 の verifier レビュー。
3. フォルダ改名 501_RakutenSearch → 501_ShoppingSearch（消込表 #926。他セッションが止まっている時に）。キットは `C:\Claude\102_ClaudeUnyou\unyou\rename-501_ShoppingSearch\`。腱さんがアプリを完全終了 → `rename-folder.bat` → YES。その後 `POST-RENAME-TODO.md` を消し込む（GitHub 側は改名済み）。
4. Uptime Kuma に `http://kaimono:8000/kaimono/healthz` の監視を追加（ブラウザ操作・腱さん）。

## 待ち（腱さん・別セッション）
- 消込表 #923 / #926 / #927 の回答待ち（内容は消込表を正とする）。
- 再デプロイ: VPS 上の `/opt/apps/_tools/deploy_app.sh kaimono` を `nohup setsid` でデタッチ起動（README）。本番の `.env` に `RAKUTEN_APPLICATION_ID` / `RAKUTEN_ACCESS_KEY` が入っていないと `/healthz` が 503 になる。
- ChatGPT（Plus）から `https://app.negura.website/kaimono/mcp` への実接続は未検証（登録手順は README）。
- 実 API を使った WP3 後の通し確認（AC12 相当）は未実施。CLI は既定がモックなので `cli.py compare ... --live` を手動で 1 回行う。

## 注意
- リポジトリは public、docs/ は GitHub Pages で公開。認証情報・接続元IP・個人の購入リストを書かない（.env と data/ は管理外）。
- CLI と stdio MCP の既定はモック。実 API は CLI の `--live`、stdio MCP の `SHOPPING_LIVE=1` を明示した時だけ。公開Web は実 API が既定。
- 実装者の commit 帰属行は "Sonnet 5.5"（実際の実行モデル）。
