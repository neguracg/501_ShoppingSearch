# @owns 公開Webアプリの HTTP 入口（ルーティング・入力検査・BASE_PATH・エラー画面）。流量保護は guard、画面は web_view に委譲
"""公開Web（FastAPI）。誰でも開ける・ログイン無し。楽天 API を呼ぶのはこのサーバーだけで、
アクセスキー・アプリIDはブラウザへ一切渡さない。search / compare のみ（定番品は出さない）。
{BASE}/mcp にリモートMCP（Streamable HTTP・認証なし・2 ツール）を同居させ、Web と同じ Gate を通す。

起動: PYTHONPATH=src BASE_PATH=/kaimono uvicorn shopping.web:app
"""
from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import service
from .config import load_credentials
from .guard import Gate, RateLimited, client_ip_var, pick_client_ip
from .inputs import MAX_PRICE, InvalidInput
from .mcp_server import build_server
from .orchestrator import Limits
from .web_view import BASIS_UNUSED_NOTE, group_title, render

PAGES = 1
HITS = 30                      # 楽天の hits 上限（出典: 楽天 IchibaItem Search 仕様）。Web は 1 ページ分を画面に出す
WEB_GROUP_OFFERS_MAX = 10      # 比較画面の各グループ・不明候補の表示件数（画面の表示仕様。MCP・CLI は切らない）

_SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                                "base-uri 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}
# 利用者に見せる失敗の種別（例外本文・URL・キーは出さない）
_BUSY_KINDS = {"http_429", "rate_limited", "server_error", "timeout", "busy", "network_error"}


def normalize_base_path(value: str | None) -> str:
    v = (value or "").strip()
    if v in ("", "/"):
        return ""
    return "/" + v.strip("/")


def _page(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
    base = request.app.state.base
    return HTMLResponse(render(name, base, **ctx), status_code=status, headers=_SECURITY_HEADERS)


def _message(request: Request, status: int, heading: str, *paragraphs: str, headers=None):
    resp = _page(request, "message.html", status, heading=heading, paragraphs=list(paragraphs))
    for k, v in (headers or {}).items():
        resp.headers[k] = v
    return resp


def _client_ip(request: Request) -> str:
    return pick_client_ip(request.headers.get("cf-connecting-ip"),
                          request.client.host if request.client else None)


def parse_keywords(q: str | None) -> list[str]:
    """改行・カンマ区切り。語数・長さの検査は guard.Gate.admit（inputs）が持つ。"""
    return [p.strip() for p in re.split(r"[\n\r,，、]+", q or "") if p.strip()]


def parse_terms(raw: str | None) -> list[str] | None:
    """含む語・除く語: 空白・カンマ区切り。"""
    parts = [p for p in re.split(r"[\s,，、]+", raw or "") if p]
    return parts or None


def _parse_price(raw: str | None, label: str) -> int | None | str:
    if raw is None or raw.strip() == "":
        return None
    t = raw.strip().replace(",", "").replace("，", "")
    if not (t.isascii() and t.isdecimal() and len(t) <= 12) or int(t) > MAX_PRICE:   # 桁数を先に切る（巨大な数字列で int() を重くしない）
        return f"{label}は 0〜{MAX_PRICE:,} の整数で入力してください。"
    return int(t)


class _McpMiddleware:
    """{BASE}/mcp への HTTP を MCP の ASGI アプリへ渡し、呼び出し元 IP を guard に伝える。"""

    def __init__(self, app, mcp_app, path: str):
        self.app = app
        self.mcp_app = mcp_app
        self.path = path

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].rstrip("/") == self.path:
            if scope.get("method") != "POST":
                # stateless・JSON 応答なので SSE ストリーム（GET）や セッション終了（DELETE）は提供しない
                await Response(status_code=405, headers={"Allow": "POST"})(scope, receive, send)
                return
            headers = dict(scope.get("headers") or [])
            ip = pick_client_ip(headers.get(b"cf-connecting-ip", b"").decode("latin-1") or None,
                                (scope.get("client") or (None,))[0])
            token = client_ip_var.set(ip)
            try:
                await self.mcp_app(dict(scope, path=self.path), receive, send)
            finally:
                client_ip_var.reset(token)
            return
        await self.app(scope, receive, send)


def create_app(base_path: str | None = None, gate: Gate | None = None) -> FastAPI:
    base = normalize_base_path(os.environ.get("BASE_PATH") if base_path is None else base_path)
    gate = gate or Gate(adapters=service.make_adapters())      # 有効なモール（楽天。Yahoo は鍵がある時だけ）
    mcp_path = f"{base}/mcp"
    # stateless・JSON 応答（Cloudflare Tunnel 越しに SSE の長時間接続へ頼らない）。
    # host を localhost 以外にして DNS rebinding 保護（localhost 限定）を自動有効にしない。
    mcp_app = build_server(public=True, gate=gate).streamable_http_app(
        streamable_http_path=mcp_path, json_response=True, stateless_http=True, host="0.0.0.0")

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = FastAPI(title="買い物リサーチ", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.add_middleware(_McpMiddleware, mcp_app=mcp_app, path=mcp_path)
    app.state.base = base
    app.state.gate = gate
    router = APIRouter()

    def unit_price_cards(c: dict) -> list:
        """単価が最安の欄。数え語のグループが複数ある時（WP14 W3）は主グループ（main_count_unit）の最安で、見出しに数え語を出す
        （数え方の違う候補は比べない。caveats に件数）。"""
        unit = f"［{c['main_count_unit']}］" if len(c["groups"]) > 1 and c.get("main_count_unit") else ""
        return [(f"{c['basis_label']}{unit}の単価が最安", c["cheapest_unit_price"])]

    def run(request: Request, mode: str, q, ng, min_price, max_price, include=None, exclude=None,
            basis=None):
        form = {"q": q or "", "ng": ng or "", "min_price": min_price or "", "max_price": max_price or "",
                "include": include or "", "exclude": exclude or "", "basis": basis or ""}
        keywords = parse_keywords(q)
        lo = _parse_price(min_price, "価格の下限")
        hi = _parse_price(max_price, "価格の上限")
        ng_word = (ng or "").strip()
        inc, exc_terms = parse_terms(include), parse_terms(exclude)
        basis_arg = (basis or "").strip() or None
        problem = lo if isinstance(lo, str) else hi if isinstance(hi, str) else None
        if problem:
            return _message(request, 400, "入力を確認してください", problem)
        try:
            gate.admit(_client_ip(request), keywords=keywords, ng_keyword=ng_word or None,
                       min_price=lo, max_price=hi, include_terms=inc, exclude_terms=exc_terms,
                       basis=basis_arg, pages=PAGES)
        except InvalidInput as exc:
            return _message(request, 400, "入力を確認してください", str(exc))
        except RateLimited as exc:
            return _message(request, 429, "少し待ってからもう一度お試しください",
                            "短い時間にたくさんの検索がありました。しばらくしてからもう一度お試しください。",
                            headers={"Retry-After": str(exc.retry_after)})
        common = dict(ng_keyword=ng_word or None, min_price=lo, max_price=hi, pages=PAGES, hits=HITS,
                      adapters=gate.adapters, sleep=lambda s: None, limits=Limits(min_interval_sec=0),
                      paging_notes=False)
        if mode == "compare":
            result = service.compare_offers(keywords, inc, exc_terms, None, basis_arg,
                                            group_offers_max=WEB_GROUP_OFFERS_MAX, **common)
        else:
            result = service.search_products(keywords, max_results=HITS * len(gate.adapters), include_terms=inc,
                                             exclude_terms=exc_terms, **common)
        if not result.get("ok"):
            kind = (result.get("error") or {}).get("kind", "")
            if kind in _BUSY_KINDS:
                return _message(request, 503, "楽天側が混雑しています",
                                "楽天市場からの応答が得られませんでした。しばらくしてからもう一度お試しください。",
                                headers={"Retry-After": "30"})
            if kind == "invalid_request":
                return _message(request, 400, "入力を確認してください", "検索条件を確認してください。")
            return _message(request, 503, "検索できませんでした",
                            "現在検索できません。しばらくしてからもう一度お試しください。")
        notes = list(result["notes"])
        if mode == "search" and basis_arg:
            notes.append(BASIS_UNUSED_NOTE)        # S9: 一覧では比べる単位を使わない
        ctx = dict(mode=mode, keywords=result["keywords"], mock=result["mock"],
                   notes=notes, form=form)
        if mode == "compare":
            c = result["comparison"]
            ctx.update(caveats=c["caveats"], basis_label=c["basis_label"],
                       cheapest=[("商品価格が最安", c["cheapest_price"]),
                                 *unit_price_cards(c),
                                 ("支払総額が最安（送料が分かる場合のみ）", c["cheapest_total"])],
                       groups=[dict(g, title=group_title(g, c["basis_label"])) for g in c["groups"]],
                       unknown_offers=c["unknown_offers"], unknown_count=c["unknown_count"])
        else:
            ctx.update(offers=result["offers"])
        return _page(request, "results.html", **ctx)

    @router.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return _page(request, "index.html", form={"q": "", "ng": "", "min_price": "", "max_price": "",
                                                  "include": "", "exclude": "", "basis": ""})

    @router.get("/search", response_class=HTMLResponse)
    def search(request: Request, q: str | None = None, ng: str | None = None,
               min_price: str | None = None, max_price: str | None = None,
               include: str | None = None, exclude: str | None = None, basis: str | None = None):
        return run(request, "search", q, ng, min_price, max_price, include, exclude, basis)

    @router.get("/compare", response_class=HTMLResponse)
    def compare(request: Request, q: str | None = None, ng: str | None = None,
                min_price: str | None = None, max_price: str | None = None,
                include: str | None = None, exclude: str | None = None, basis: str | None = None):
        return run(request, "compare", q, ng, min_price, max_price, include, exclude, basis)

    @router.get("/healthz")
    def healthz():
        # 楽天 API は呼ばない。秘密の値は出さず、設定の有無だけ返す。鍵が無いのに起動している本番を
        # unhealthy（503）にして検知する（モック運用は鍵を要さないので 200）
        present = load_credentials().present
        ok = present or bool(getattr(gate.adapter, "is_mock", False))
        return JSONResponse({"ok": ok, "credentials": present}, status_code=200 if ok else 503)

    app.include_router(router, prefix=base)
    if base:
        @app.get(base, include_in_schema=False)
        def base_no_slash():
            return RedirectResponse(f"{base}/", status_code=308)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return _message(request, 404, "ページが見つかりません", "URL を確認してください。")
        return _message(request, exc.status_code, "リクエストを処理できません", "操作をやり直してください。")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        # 例外本文・URL・キーを出さない
        return _message(request, 500, "エラーが発生しました", "しばらくしてからもう一度お試しください。")

    return app


app = create_app()
