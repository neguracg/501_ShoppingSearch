# 指示書 WP17 — Yahoo!ショッピング対応（楽天との横断比較）（2026-11-24）

## 目的と出典（言い換えない）

- 腱さん 2026-11-24（ChatGPT 経由のブリッジ #9 に記載の本人決定）: 既存の楽天市場商品検索・最安値比較プラグインを Yahoo!ショッピングにも対応させ、**楽天と Yahoo を同じ買い物要件で横断比較できるようにする。従来の楽天機能・精度は維持する。**
- 腱さん 2026-11-24 18:33「着手して」。
- ブリッジ #9 の要件・観測（§5〜§7）は GitHub neguracg/000_AI-Bridge Issue #9 が原文。下の「契約」はそれを SPEC に落とす時のオーケストレータの決定。
- 公開アプリ（公開MCP・公開Web）に Yahoo を載せるかは**腱さんの判断待ち（消込表 #1169）**。本 WP は手元で完成させ、本番の `.env` に `YAHOO_CLIENT_ID` を入れない・`ops/push_env_keys` を実行しない・デプロイしない。**鍵が無ければ Yahoo は自動で無効**（下の C1）なので、master へのマージは本番に影響しない形にする。

## 方針（5行）

1. Yahoo 固有の知識は `adapters/yahoo.py` だけに置く（SPEC §3「adapter を足すだけで済む形」）。楽天固有で adapters の外に漏れている値（hits 上限・ページ天井・流量・sort の値・URL 判定・クレジット・SOURCE）は、モールごとの設定としてアダプタ側へ寄せる。
2. service は「モール → アダプタ」の辞書を受け、モールごとに検索（モールごとの流量・直列化）してから、既存の数量・比較（pricing）に**混ぜて**渡す。比較の判定（確認済み・最安・注文案）は既存の1か所（`pricing.unconfirmed_reasons`）のまま。
3. Yahoo の API で分からない事（選択肢ごとの価格・税抜表示・中古）は、アダプタが Offer に「未確定の理由」として載せ、`unconfirmed_reasons` が拾う。**確認済みの定義は広げない**（Yahoo の候補は今の情報では確認済みにならない＝下の P1）。
4. 片方のモールの失敗は、もう片方の結果を消さない（モール別のエラーを stats と notes に出す）。
5. 楽天だけを指定した時（`malls=["rakuten"]`）と Yahoo の鍵が無い時の出力は、今の楽天の出力と同じ（追加の項目を除き値が変わらない）。

## 着手前5問（オーケストレータの答え。現物で確かめ、違えば報告）

1. 同じ知識を持つ場所: 楽天の上限・流量・URL 判定・クレジット・送料フラグの文言が inputs.py（MAX_HITS・MAX_PAGES・SORTS・too_short）、orchestrator.py（min_interval 1.0・MAX_PAGES）、guard.py（MIN_INTERVAL_SEC）、web.py（HITS・healthz・失敗文）、web_view.py（`is_item_url` 直 import・文言）、credit.py、service.py（SOURCE・送料食い違いの文言・429 文言・paging 文言）、mcp_server.py（説明文）、cli.py に散っている。モールごとの値はアダプタのクラス属性（`mall`・`label`・`max_hits`・`max_page`・`min_interval_sec`・`is_item_url`・`credit`）に集め、外はそれを引く。
2. 同種の既存機能: search_products・compare_offers・find_regular_item（定番品）・公開 Web の検索・公開/stdio MCP・CLI の6入口すべてが新しい `malls` を通る。定番品は手元専用なので Yahoo を含めてよい。
3. 引っ越しではない（新規アダプタ＋既存の束ね）。
4. 過去の似た改修: WP14 W1（price_varies を未確定に）・WP15 段A（provisional_*）・BUGLOG の送料（postageFlag）・WP8 の 1文字語 HTTP 400。WORKLOG・BUGLOG を `price_varies`・`shipping`・`429`・`credit` で検索してから書く。
5. 所有モジュール: モール固有＝adapters/<mall>.py（`@owns` を付ける）、モールの束ね＝新設 `malls.py`（どのモールが有効か・アダプタの生成・モール別の検索の並走。`@owns モールの選択と束ね`）、確認済みの判定＝pricing.unconfirmed_reasons（不変の1か所）、クレジット＝credit.py。

## 契約（SPEC へ反映する。B 分類＝SPEC を同じコミットで更新）

### Y. Yahoo アダプタ（adapters/yahoo.py・SPEC 新節「5b. Yahoo!ショッピング Adapter」）

- Y1 エンドポイント `https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch`、GET、`appid`=Client ID（クエリ。**URL に秘密が入るので URL を例外・ログ・戻り値に一切出さない**。リダイレクトは追わない＝楽天と同じ `_NoRedirect`）。
- Y2 1ページ＝`results=50`、`start=(page-1)*50+1`。`start+results ≤ 1000` を越えるページは呼ばない（Yahoo の上限。max_page=20）。越えた時は stats でそのモールの `truncated`・`next_page=null`・注記「Yahoo は 1000 件目まで」。全体を invalid_request にしない。
- Y3 sort の写像（公開の引数は今の楽天の値のまま）: `standard`→`-score`、`+itemPrice`→`+price`、`-itemPrice`→`-price`、`-reviewCount`→`-review_count`。それ以外は `-score` で呼び、注記「Yahoo はこの並び順に無いため標準順」。
- Y4 `min_price`/`max_price`→`price_from`/`price_to`。availability=1（在庫あり）→`in_stock=true`。`ng_keyword` は Yahoo に該当の引数が無いので、**アダプタ内で商品名に除外語を含む候補を捨てる**（注記「Yahoo は商品名で除外」。api_count は API の値のまま）。
- Y5 応答 → Offer:
  - mall="yahoo"、mall_item_code=`code`（必須。無ければその hit だけ捨てずに unexpected_response…ではなく、**hit 単位で読めない物は数えて捨て、注記に件数**。応答全体の形が違う時だけ unexpected_response）、item_name=`name`、price=`price`（整数）、item_url=`url`、shop_name=`seller.name`、shop_code=`seller.sellerId`、jan=`janCode`（空文字は None）、review_average/count=`review.rate`/`review.count`、availability=`inStock`、caption=`description` の HTML を文字にした物（`<br>` を改行、他のタグを除去、実体参照を戻す）＋`headLine` を先頭に1行、fetched_at=JST。
  - 送料: `shipping.code` 2（送料無料）→ `included`。1（設定なし）・3（条件付き送料無料）・その他 → `unknown`（3 は `shipping_condition="conditional_free"` を出力に出す）。**名前の文字（「送料無料」）で決めない**。shipping_fee は None。
  - ポイント: `point.lyLimitedBonusAmount`（ストアポイント・期間限定）を `points_amount`（円相当の参考値）として出力に出すだけ。総額・単価・最安に使わない。premium 系・旧 amount/bonusAmount は使わない（足さない）。points_rate は None。
  - 価格: `price` を採る（セール中は値下げ後。`priceLabel.discountedPrice`・`periodEnd` は出力の `sale` に参考で出してよい）。`premiumPrice`（会員価格）は使わない。`priceLabel.taxable` が true でない時は Offer に未確定理由 `price_tax_unknown`。
  - 中古: `condition` が `new` でない時は未確定理由 `condition_not_new`、出力に `condition`。
  - 選択肢の価格: Yahoo の検索 API には楽天の itemPriceMin/Max に当たる項目が無い。**全 Yahoo 候補に未確定理由 `price_options_unchecked`**（price_varies は None のまま＝楽天の判定を変えない）。
  - URL: `https://store.shopping.yahoo.co.jp/<seller>/<item>.html` と `https://lohaco.yahoo.co.jp/store/<store>/item/<item>/` を ok、それ以外は needs_review（捨てない・作らない・改変しない）。
- Y6 エラー種別: 400→`bad_request`、401・403→`forbidden`（Yahoo は流量超過でも 403 を返し得る）、429→`rate_limited`、500・503→`server_error`（流量超過で HTML の 500 が返る事がある）、timeout・network・invalid_json・unexpected_response は楽天と同じ語。応答本文・URL・appid を例外に入れない。`rate_limited` と `server_error` はそのモールの残りの検索を打ち切る（再試行ループしない）。
- Y7 流量: Yahoo は 1 リクエストごとに 2.2 秒以上空ける（公式の「1分30回」と「1秒1回」の厳しい方に余裕）。公開面では Yahoo 用の GuardedAdapter（プロセス全体で直列化）を楽天と別に持つ。
- Y8 鍵: `YAHOO_CLIENT_ID`。読む順は 環境変数 → `.env` → `.env.yahoo.local`（ローカルの PoC 用。ASCII 1行 `YAHOO_CLIENT_ID=<値>`）。値は repr で伏せる。CR/LF・空白入りは invalid_credentials で呼ばない。

### C. モールの選択（malls.py・service・各入口）

- C1 有効なモール: 楽天は今のまま必須（鍵が無ければ今の挙動）。Yahoo は鍵がある時だけ有効。モック時は両方モック（mock_data に Yahoo の架空データを数件。`mall="yahoo"`）。
- C2 `malls` 引数（search_products・compare_offers・find_regular_item・MCP 2ツール・CLI `--malls rakuten,yahoo`・Web の選択は付けず有効な全部）: 省略＝有効な全モール。無効・未知のモールを指定したら invalid_request（API 呼び出し 0 回）。
- C3 モールごとに順番に検索せず、**モール単位で並走**（スレッド1本ずつ。モール内は今の直列・流量のまま）。Cloudflare の 80 秒に収める。
- C4 出力: 候補ごとの `mall` は既にある。stats にモール別の要約 `per_mall`（mall・取得件数・api_count の和・エラー・truncated）を足し、`per_keyword[]` の各行に `mall` を足す。最上位の `source` は今の文字列を楽天だけの時は変えず、2モールの時は `sources`（一覧）を足す。
- C5 片方のモールのエラー: もう片方の結果で比較を続け、notes に「Yahoo!ショッピングは〈種別〉で取得できなかった（楽天だけで比較）」。全モールが失敗した時だけ今のエラー応答。
- C6 入力検査: 今の inputs.validate は変えない（1文字語の検査・sort の値・pages の上限 100 は楽天の制約で、指定が楽天を含む時に効く。Yahoo だけを指定した時も同じ検査で構わない＝より厳しい側）。

### P. 比較・確認済み（pricing。ブラインド試験の対象）

- P1 `unconfirmed_reasons` は Offer の `mall_unconfirmed`（アダプタが付けた理由の一覧）をそのまま足す。理由の語: `price_options_unchecked`・`price_tax_unknown`・`condition_not_new`。**`unit_price_reasons` も同じ語を単価の未確定に含める**（選択肢の価格が未確認＝単価も仮）。→ Yahoo の候補は `unit_price`・`cheapest_unit_price`・`cheapest_for_quantity`・`cheapest_order`・`payment_total` に入らず、`provisional_unit_price`（理由つき）と `to_check` に出る。
- P2 to_check の条件文: `price_options_unchecked` の時「Yahoo!ショッピングの商品ページで、選んだ色・サイズ・数量の価格が〈価格〉円のままか確認」。送料 unknown（設定なし・条件付き）は今の shipping_unknown の文。
- P3 外れ値の網（N=4・K=10）・比較グループ・注文案は、モールを混ぜた候補全体で計算する（モールで分けない）。同じ JAN・同じ商品名でも、モール・店・商品コードが違えば別候補（重複排除は今の `(mall, mall_item_code)`）。
- P4 ポイントは総額から引かない。`points_amount` は候補の参考値。
- P5 送料: `included`（Yahoo code=2）だけが送料込み。unknown の候補は `total_price` を出さない（今の total_price のまま）。

### W. 表示・規約（credit.py・web_view.py・mcp_server.py）

- W1 Yahoo のクレジット（公式・無改変）: Web のフッターは楽天のクレジットに並べて `<a href="https://developer.yahoo.co.jp/sitemap/">Webサービス by Yahoo! JAPAN</a>`（目立たせない・色を変えない）。MCP・CLI の結果は Yahoo を含む時 `credits`（一覧）に `Webサービス by Yahoo! JAPAN （https://developer.yahoo.co.jp/sitemap/）` を入れる。既存の `credit`（楽天）は変えない。INSTRUCTIONS の「回答末尾にクレジット」を、使ったモールのクレジット全部に。運営者表示に「LINEヤフー株式会社とは関係ありません」。
- W2 Web の外部リンクは各モールの商品 URL だけ（`_safe_url` はモールごとの `is_item_url`）。候補にモール名を表示。
- W3 ツール説明・INSTRUCTIONS を「楽天市場・Yahoo!ショッピング」にし、`malls` の使い方と「Yahoo の候補は選択肢ごとの価格を確かめていないので、最安は『候補』として扱い商品ページで確認を促す」を1文。WP11 の 2000 字ガードは維持。
- W4 healthz は今のまま（楽天の鍵）。Yahoo の鍵の有無は healthz を落とさない。

## 固定するインターフェース（ブラインド試験と実装の両方がこれに合わせる）

- `from shopping.adapters.yahoo import YahooAdapter, parse_hit, is_item_url`
  - `YahooAdapter(client_id: str, *, opener=None, clock=None)`。`.mall == "yahoo"`。`.search(keyword, *, page=1, hits=50, ng_keyword=None, min_price=None, max_price=None, sort="standard", availability=1) -> (list[Offer], api_count)`。opener は楽天と同じ（`opener.open(request, timeout=...)` が応答を返す。tests/fakes.py の FakeOpener がそのまま使える形）。
  - `parse_hit(hit: dict, fetched_at: str) -> Offer`（hit 1件の変換。読めない hit は AdapterError("unexpected_response")）。
- `Offer` に追加: `mall_unconfirmed: list[str]`（既定 []）・`points_amount: int | None`・`shipping_condition: str | None`・`condition: str | None`。
- service の各関数に `adapters: dict[str, MarketplaceAdapter] | None = None` と `malls: list[str] | None = None` を追加。既存の `adapter=` は `{adapter.mall: adapter}` と同じ意味で残す（既存試験を変えない）。
- 出力 dict（offer_to_dict）に `points_amount`・`shipping_condition`・`condition` を足す（楽天は None）。`unconfirmed_reasons` の語は `provisional_*` の理由と to_check に今の形で出る。
- `pricing.unconfirmed_reasons(offer)` が `offer.mall_unconfirmed` の語を含む。

## 作業単位（主担当 implementer 1本・worktree。単位ごとにコミット＋WORKLOG 1行）

- U1 アダプタ（Y1〜Y8）＋ `tests/test_yahoo_adapter.py`（楽天のアダプタ試験の型。手作りの小さな fixture `tests/fixtures/yahoo_search.json`〔実応答から 6〜8 件を抜き、appid は無い〕）＋録画の読み取り試験（`data/yahoo_poc/Yahoo_PoC_Results.json` があれば 271 件を全部 Offer にして例外 0・URL の ok/needs_review の件数・送料の写像の件数を確かめる。無ければ skip）。
- U2 モールの束ね（malls.py・service・orchestrator・guard・C1〜C6）。楽天固有値をアダプタの属性へ寄せる。
- U3 pricing（P1〜P5）・service の出力（points_amount・shipping_condition・condition・sale・per_mall・sources）。
- U4 入口（MCP・Web・CLI・credit・W1〜W4）・`ops/push_env_keys`（YAHOO_CLIENT_ID も送れるように。**実行しない**）・README のキー名。
- U5 SPEC（§2 の Phase 2 の状態・§3・§4・新 §5b・§6・§8・§10・§11）と HANDOFF の同期。
- U6 実 API の手元確認（`cli.py compare ... --live --malls rakuten,yahoo` を「貼るカイロ」「文化たきつけ」の2回だけ。結果は data/wp17/ へ。appid が出力・ログに無い事を grep で確かめる）。

## 試験（関門）

- 編集中: 変えたファイルの試験だけ。
- 完了時: `tests/test_yahoo_adapter.py`・アダプタ・orchestrator・service・pricing・mcp・web・cli の試験＋ブラインド（`tests/test_blind_wp17.py`。tester が固定。**implementer は読まない・編集しない。実行は件数だけ `-q --tb=no`**）＋入口から通す1本（CLI のモックで `--malls rakuten,yahoo`）。全件はオーケストレータが統合前に1回流す。
- 楽天の回帰: `malls=["rakuten"]` と鍵なしの時、既存試験が変更なしで通ること（既存の試験の期待値を書き換えて通すのは禁止。書き換えが要る時は理由を報告）。

## やらないこと

- 本番反映・本番 `.env`・`push_env_keys` の実行（#1169 の回答待ち）。
- Yahoo の商品詳細 API・商品ページの取得（選択肢の価格確認）。JAN 検索の公開引数。Amazon 等。
- `.env.yahoo.local` の削除・上書き・中身の表示。
