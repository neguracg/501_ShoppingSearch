# 買い物リサーチツール / 501_RakutenSearch

個人の買い物を効率化する汎用の商品検索・比較ツール。特定の商品ジャンルに限定しない。
楽天市場の公式 API から商品を集め、商品名から個数と内容量（例: 洗剤 900g×6、水 2L×9本、電池 40本、パネル 100W×2）を読み取って単価を比べ、購入候補と商品固有 URL を返す。購入操作はしない。
道具は商品の意味を持たない: 持つのは「数量の読み取りと単位換算」と「語による絞り込み（含む語・除く語）」だけで、濃縮/通常・層数・色・型番などの仕様の違いは判定しない（呼び出し側の AI と利用者が判断する）。
仕様の正本は [docs/SPEC.md](docs/SPEC.md)。

## 現在の状態（Phase 1）

- 実装済み: 楽天検索 Adapter、複数キーワード検索（重複排除・流量制限）、数量正規化、単価・総額の比較、定番品マスタ、MCP サーバー（stdio）、CLI、公開Web（Phase 1.5）。
- 試験: モック・フィクスチャで自動試験（`pytest`）。**実 API を使った通し確認（AC12）は手動で別途行う**。pytest からは実 API を呼ばない。
- **ChatGPT からの実接続は未検証**（公開リモートMCP `{BASE}/mcp` は in-process 試験とローカル uvicorn で確認済み。ChatGPT への登録は下の手順で腱さんが行う）。
- **楽天ウェブサービス規約への対応**: 第10条(10)「特定の人のみがアクセスできる環境での使用」に適合させるため、楽天に登録するアプリは誰でも開ける公開Webアプリ（search / compare のみ・ログイン無し）とする。普段使い（ブラウザ・ChatGPT・Claude 等の AI）は公開アプリ（Web と `{BASE}/mcp`）に一本化し、ローカルの CLI・stdio MCP は運営者による開発・試験用（既定はモック）。定番品は利用者側（AI の記憶・指示やローカル）で持ち、サーバーには置かない。方針は [docs/SPEC.md](docs/SPEC.md) §11。公開アプリを装う方法は採らない。
- Phase 2 以降（Yahoo!ショッピング・Amazon・ヨドバシ、横断検索）は未着手。

## セットアップ

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

実 API を使う時だけ、リポジトリ直下の `.env`（git 管理外）に次の2つを書く。値はコミット・表示しない。

```
RAKUTEN_APPLICATION_ID=...
RAKUTEN_ACCESS_KEY=...
```

環境変数が優先、無ければ `.env`。モックだけなら認証情報は不要。

## 使い方（公開Web）

本番: https://app.negura.website/kaimono/ （ログイン無し・誰でも使える。search / compare のみで、定番品は出さない）。

ローカルで動かす（モック。実 API を呼ばない）:

```
set PYTHONPATH=src
set SHOPPING_MOCK=1
set BASE_PATH=/kaimono
.venv\Scripts\python -m uvicorn shopping.web:app --port 8000
```

`http://127.0.0.1:8000/kaimono/` を開く。`BASE_PATH` を空にすると `/` 直下で動く。実 API を使う時は `SHOPPING_MOCK` を外し、`.env` か環境変数に認証情報を置く（ブラウザには渡さない）。

- 流量保護（楽天 API のクォータを守る）: API 呼び出しはプロセス全体で 1 秒 1 回に直列化、同じ条件は最大 10 分キャッシュ、IP ごとに 20 回/分まで（超えると 429 の案内画面）。`RATE_LIMIT_PER_MIN` で回数を変えられる。
- 全ページのフッターに楽天のクレジット（Supported by Rakuten Developers）と運営者の責任表示を出す。結果から出るリンクは楽天の商品ページだけ。
- ヘルスチェック: `{BASE_PATH}/healthz`（API は呼ばない）。認証情報が無いと 503（`credentials=false`）で、本番での鍵の入れ忘れを unhealthy として検知する。モック運用（`SHOPPING_MOCK=1`）は鍵が要らないので 200。
- 入力検査: 検索語・含む語・除く語・楽天側の除外語はそれぞれ 1〜5 語、1 語は UTF-8 で 128 バイト以内（全角42文字・半角128文字。楽天の上限「半角128文字」を安全側に解釈。S8）まで。価格は 0〜10,000,000。`sort` は楽天公式の値、`basis` は単位表の値だけ。弾いた入力は楽天 API の枠も IP 別回数も消費しない。
- `GET {BASE_PATH}/mcp` は 405（stateless・JSON 応答のため SSE を開かない。`POST` だけ受ける）。

Docker（VPS 用）: `Dockerfile` と `docker-compose.prod.yml`（サービス `kaimono`、external network `internal`、ポート公開なし）。VPS 上の `.env`（git 管理外・600）に `BASE_PATH=/kaimono` `PUBLIC_BASE_URL=https://app.negura.website/kaimono/`（末尾スラッシュ付き） `APP_ENV=production` `RAKUTEN_APPLICATION_ID` `RAKUTEN_ACCESS_KEY` を置く（`.env.example` は秘密ファイル保護の設定で作れないため、キー名はここを正本とする）。起動・反映は VPS 上の `/opt/apps/_tools/deploy_app.sh kaimono` を `nohup setsid` でデタッチ起動する（直の `docker compose up` はフックが遮断）。イメージには `requirements.txt`（本番用）だけを入れる。試験用の `pytest` と `httpx` は `requirements-dev.txt`。

## ChatGPT のチャットから使う（リモートMCP）

公開Web と同じサーバーに MCP エンドポイントがある: `https://app.negura.website/kaimono/mcp`（Streamable HTTP・認証なし）。ツールは `search_products` と `compare_offers` の 2 つだけ（定番品は出さない）。流量保護は Web と共通で、結果にはクレジット（Supported by Rakuten Developers）が必ず入る。

ChatGPT への登録手順（2026-11 時点。画面名は変わりうる）:

1. 設定 → アプリとコネクタ → 詳細設定 → 開発者モードを ON
2. 作成（コネクタを追加）
3. URL に `https://app.negura.website/kaimono/mcp` を入力、認証は「なし」にして作成
4. チャットで「楽天で洗濯洗剤の詰め替えを探して。100gあたりの最安を比べて」「単3電池を1本あたりで比べて」「ミネラルウォーター2Lを100mlあたりで」のように頼む（含む語・除く語・比べる単位は AI が指定する）

Claude・Codex など他の MCP クライアントも同じ URL を登録すればよい。ローカル確認: 上の uvicorn を起動し `http://127.0.0.1:8000/kaimono/mcp` を登録する。

## 使い方（CLI）

```
.venv\Scripts\python cli.py search "洗濯洗剤 詰め替え" "単3電池" --mock
.venv\Scripts\python cli.py search "ミネラルウォーター" --include 2L --exclude 箱 --mock
.venv\Scripts\python cli.py compare "洗濯洗剤 詰め替え" --include 詰め替え --exclude 本体 --basis g --desired-quantity 5000 --mock
.venv\Scripts\python cli.py compare "洗濯洗剤 詰め替え" --basis g --desired-quantity 5000 --desired-quantity-max 12000 --mock
.venv\Scripts\python cli.py compare "単3電池" --basis 個 --mock
.venv\Scripts\python cli.py compare "ミネラルウォーター" --include 2L --basis ml --mock
.venv\Scripts\python cli.py regular detergent-refill --regulars examples\regulars.sample.json --mock
```

- **既定は架空データ**（`src/shopping/mock_data.json`。洗剤・電池・水・ソーラーパネル・トイレットペーパーの架空商品）で、API を呼ばない。実 API を呼ぶのは `--live`（または環境変数 `SHOPPING_LIVE=1`）を明示した時だけ（運営者の開発・試験用。SPEC §11）。`--mock` は互換のため残してある。
- `--json` で整形済み JSON。キーワードは 1 回 5 個まで、`--pages` は語ごとに取るページ数（既定 3＝90 件・1〜100）、`--start-page` は取り始めるページ（既定 1）。ヒットの全量（API件数）と取得範囲・続きのページ（`--start-page N`）が表示される（例: 4 ページ目から 10 ページ分は `--start-page 4 --pages 10`）。楽天は 100 ページ目（3000 件/語）までしか返さないので `--start-page` + `--pages` - 1 は 100 以下。1 回の取得が 80 秒を超えそうなら途中で止めて続きのページを返す。`search` の `--max-results` を省略すると取得した全件を表示する、リクエスト間隔は 1 秒以上。
- 比較は「商品価格」「単位価格」「支払総額」「必要数量を満たす最安」を分けて出す。送料が不明な候補があると支払総額の最安は断定せず、理由を表示する。単価は `--basis`（個・ml・g・m・W・mAh・Wh。L・kg などの別名も可。省略で自動）あたりで出し、その量を読み取れない候補は「単価不明」として最安判定から外す。`--include` は商品名に全部含む語、`--exclude` は含んだら外す語（`search` でも `compare` でも使える。数字で始まる/終わる語は別の数の途中には一致しない: `2L` は `12L`・`1.2L` に一致しない）。`--basis` は `compare` だけで使う（一覧では使わない）。数量は「N回分」を個数に数えず、「水 24本 (500ml×24)」のような言い直しを二重に掛けず、9桁を超える数や表にない数え語が個数の位置にある商品は単価不明（low）に倒す（SPEC §7）。仕様の違い（濃縮・層数・型番・色など）は判定しないので、結果の商品名で確認する。

- **希望量の注文（WP14）**: `--desired-quantity`（下限）と `--desired-quantity-max`（上限・任意）で、同じ商品を n 個注文する組み合わせを比べる。確認済み（数量が商品名から読め・価格が選択肢で変わらず・外れ値でなく・送料込み）の中の最安の注文（`cheapest_order`）と、逆転し得る候補とその条件（`to_check`。送料が X円未満なら・商品名の数量の選択肢が X円以下なら・説明欄の数量が正しければ）を出す。送料無料ライン（3,980円など）は仮定しない。`--basis` には数え語（本・袋・枚・ロール など）も指定でき、その数え語の候補だけで比べる（省略または個では数え語ごとのグループに分かれ、数え方の違う候補は同じ単価順に並べない）。題名から数量が読めない候補に説明欄の見出し付きの記述（入数・内容量・数量・容量）がある時は、その数量の候補と根拠を印として返す（単価・最安・注文案には使わない。`caption_quantity.CAPTION_FILL_UNIT_PRICE` を True にすると補完した数量として単価を出す完全形になる）。

## 使い方（MCP サーバー）

ツールは `search_products` / `compare_offers` / `find_regular_item` の3つ。stdio で起動する。`compare_offers` は `desired_quantity`（希望量の下限）と `desired_quantity_max`（上限・任意）を受け、注文の組み合わせを `comparison.order_plans`・`cheapest_order`・`to_check` に返す（公開の `{BASE}/mcp` も同じ）。

```
set PYTHONPATH=src
rem 既定はモック（API を呼ばない）。実 API は set SHOPPING_LIVE=1 を明示した時だけ
.venv\Scripts\python -m shopping.mcp_server
```

MCP クライアント側の設定例（コマンドと環境変数の指定。クライアントごとに書式は異なる）:

```
command: <このリポジトリ>\.venv\Scripts\python.exe
args:    -m shopping.mcp_server
env:     PYTHONPATH=<このリポジトリ>\src   （既定はモック。実 API を使う時だけ SHOPPING_LIVE=1 を足す）
```

## 定番品マスタ

`data/regulars.json`（git 管理外。個人の購入リストのため）に置く。見本は `examples/regulars.sample.json`（洗剤・電池・水の3カテゴリ）。項目は `include_terms` / `exclude_terms` / `basis` / `desired_quantity` / `keywords` など（`required_spec` と `unit` は廃止）。価格・在庫は保存せず、検索のたびに取り直す。置き場は環境変数 `SHOPPING_REGULARS_PATH` でも指定できる。

## 試験

```
.venv\Scripts\python -m pytest -q
```

## 説明ページ

GitHub Pagesで master ブランチの /docs を公開。
公開URL（2026-11-04にブラウザー表示確認済み）: https://neguracg.github.io/501_RakutenSearch/
静的ページのソース: docs/index.html

## 秘密情報

APIキー・アプリID・接続元IP・商品データ・個人情報をコミットしない。
楽天 API を呼ぶのはサーバー側だけで、アクセスキー・アプリIDをブラウザ（公開ページの HTML・JS）へ渡さない。`docs/`（静的説明ページ）から API は呼ばない。`docs/` は公開されるため認証情報や個人の購入リストを書かない。
`preflight.py` / `check_connection.py` は接続確認用の単発プローブ（商品データや認証情報を出力しない）。
