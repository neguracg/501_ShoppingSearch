# @owns 各モールのウェブサービス規約から来る表示文言（クレジット・運営者の責任表示・価格在庫の注意）。Web と MCP・CLI が同じ文言を使う
"""公式のクレジット（楽天: https://webservice.rakuten.co.jp/guide/credit ・Yahoo: https://developer.yahoo.co.jp/attribution/）は改変しない。
Yahoo は使うモールに含まれる時だけ出す（楽天だけの時の文言は従来のまま）。"""
from __future__ import annotations

import os

CREDIT_HTML = (
    '<!-- Rakuten Web Services Attribution Snippet FROM HERE -->\n'
    '<a href="https://developers.rakuten.com/" target="_blank">Supported by Rakuten Developers</a>\n'
    '<!-- Rakuten Web Services Attribution Snippet TO HERE -->'
)
CREDIT_TEXT = "Supported by Rakuten Developers"
CREDIT_URL = "https://developers.rakuten.com/"
YAHOO_CREDIT_HTML = '<a href="https://developer.yahoo.co.jp/sitemap/">Webサービス by Yahoo! JAPAN</a>'
YAHOO_CREDIT_TEXT = "Webサービス by Yahoo! JAPAN"
YAHOO_CREDIT_URL = "https://developer.yahoo.co.jp/sitemap/"
OPERATOR_TEXT = ("このサイトは個人開発者 negura が作成・運営しており、内容の責任は運営者にあります。"
                 "楽天グループとは関係ありません。")
YAHOO_OPERATOR_TEXT = "LINEヤフー株式会社とは関係ありません。"
OPERATOR_SHORT = "個人開発者 negura が運営（楽天グループとは無関係）"
YAHOO_OPERATOR_SHORT = "個人開発者 negura が運営（楽天グループ・LINEヤフー株式会社とは無関係）"
FRESHNESS_TEXT = "価格・在庫は検索時点のもの。購入前に楽天市場の商品ページで確認してください。"
MULTI_FRESHNESS_TEXT = "価格・在庫は検索時点のもの。購入前に各モールの商品ページで確認してください。"
DEFAULT_PUBLIC_BASE_URL = "https://app.negura.website/kaimono/"

# モール名 → (テキスト, URL, HTML)。順番は楽天が先
_CREDITS = {"rakuten": (CREDIT_TEXT, CREDIT_URL, CREDIT_HTML),
            "yahoo": (YAHOO_CREDIT_TEXT, YAHOO_CREDIT_URL, YAHOO_CREDIT_HTML)}


def _has_yahoo(malls) -> bool:
    return "yahoo" in (malls or ())


def public_base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL") or DEFAULT_PUBLIC_BASE_URL


def credits_list(malls) -> list[str]:
    """使ったモールのクレジット（テキスト＋URL）の一覧。楽天が先。MCP・CLI の結果の credits。"""
    return [f"{_CREDITS[m][0]} （{_CREDITS[m][1]}）" for m in _CREDITS if m in (malls or ())]


def credit_html(malls=("rakuten",)) -> str:
    """Web のフッター。楽天のクレジットに並べて、Yahoo を使う時は Yahoo のクレジット（目立たせない・色を変えない）。"""
    return "\n".join(_CREDITS[m][2] for m in _CREDITS if m == "rakuten" or m in (malls or ()))


def operator_text(malls=("rakuten",)) -> str:
    return OPERATOR_TEXT + (YAHOO_OPERATOR_TEXT if _has_yahoo(malls) else "")


def operator_short(malls=("rakuten",)) -> str:
    return YAHOO_OPERATOR_SHORT if _has_yahoo(malls) else OPERATOR_SHORT


def freshness_text(malls=("rakuten",)) -> str:
    return MULTI_FRESHNESS_TEXT if _has_yahoo(malls) else FRESHNESS_TEXT


def mcp_credit_fields(malls=None) -> dict:
    """リモートMCP のツール結果に必ず入れる項目。credit・credit_url は従来どおり楽天。使ったモールに Yahoo を含む時は credits（一覧）も入れる。"""
    out = {"credit": CREDIT_TEXT, "credit_url": CREDIT_URL, "operator": operator_short(malls),
           "web": public_base_url()}
    if _has_yahoo(malls):
        out["credits"] = credits_list(malls)
    return out
