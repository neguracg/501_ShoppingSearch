"""WP17 U4: 入口（公開 MCP・stdio MCP・公開 Web・CLI）の Yahoo 対応。Yahoo が無い（鍵なし）時の表示は従来のまま。"""
import asyncio
import re

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from fakes import FakeAdapter, FakeYahoo, make_offer, yoffer
from shopping import credit, mcp_server, service
from shopping.guard import Gate, RateLimiter
from shopping.mcp_server import build_server
from shopping.web import create_app
import cli

KW = "貼るカイロ"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("SHOPPING_MOCK", raising=False)
    monkeypatch.delenv("SHOPPING_LIVE", raising=False)


def two_malls(rak=None, yah=None):
    rak = rak if rak is not None else [make_offer("r60", f"{KW} レギュラー 60枚", 1500, shipping_status="included")]
    yah = yah if yah is not None else [yoffer("y60", f"{KW} レギュラー 60枚", 1380, shipping_status="included", points_amount=14)]
    return {"rakuten": FakeAdapter({(KW, 1): (rak, len(rak))}), "yahoo": FakeYahoo({(KW, 1): (yah, len(yah))})}


def gate_of(adapters):
    return Gate(adapters=adapters, limiter=RateLimiter(limit=1000))


def mcp_call(gate, name, args):
    async def go():
        async with Client(build_server(public=True, gate=gate)) as c:
            return await c.call_tool(name, args)
    r = asyncio.run(asyncio.wait_for(go(), timeout=30))
    assert not r.is_error
    return r.structured_content


def mcp_tools(gate):
    server = build_server(public=True, gate=gate)

    async def go():
        async with Client(server) as c:
            return await c.list_tools()
    res = asyncio.run(asyncio.wait_for(go(), timeout=30))
    return {t.name: t for t in res.tools}, server.instructions


# ---- 公開 MCP ----

def test_public_mcp_with_yahoo_texts_fit_and_mention_malls():
    tools, instr = mcp_tools(gate_of(two_malls()))
    for name in ("search_products", "compare_offers"):
        d = tools[name].description
        assert len(d) <= 2000, (name, len(d))                                  # WP11 の 2000 字ガード
        assert "Yahoo!ショッピング" in d and "malls" in d
        assert "malls" in tools[name].input_schema["properties"]
    assert "楽天市場・Yahoo!ショッピングの商品を検索・比較する" in instr
    assert "Webサービス" not in instr and "credits" in instr               # 使ったモールのクレジット全部（結果の credits）を添える
    assert "選択肢ごとの価格を確かめていない" in instr and "商品ページで確認を促す" in instr
    assert "続きが要るモールだけを malls=['yahoo'] のように指定して start_page=N で呼ぶ" in instr           # 続きの案内（B3）
    assert "続きが要るモールだけ malls で指定して start_page" in tools["search_products"].description


def test_public_mcp_without_yahoo_keeps_the_old_texts():
    tools, instr = mcp_tools(gate_of({"rakuten": FakeAdapter({})}))
    assert instr == mcp_server.INSTRUCTIONS
    for name in ("search_products", "compare_offers"):
        assert "Yahoo" not in tools[name].description
    assert (len(tools["search_products"].description), len(tools["compare_offers"].description)) == (1852, 1968)
    assert "malls" in tools["compare_offers"].input_schema["properties"]         # 引数自体はある（指定すると有効でなければ invalid_request）


def test_public_mcp_result_has_credits_and_operator_when_yahoo_is_used():
    out = mcp_call(gate_of(two_malls()), "compare_offers", {"keywords": [KW], "desired_quantity": 60})
    assert out["ok"] and out["malls"] == ["rakuten", "yahoo"]
    assert out["credit"] == credit.CREDIT_TEXT and out["credit_url"] == credit.CREDIT_URL      # 既存の credit（楽天）は変えない
    assert out["credits"] == ["Supported by Rakuten Developers （https://developers.rakuten.com/）",
                              "Webサービス by Yahoo! JAPAN （https://developer.yahoo.co.jp/sitemap/）"]
    assert "LINEヤフー株式会社とは無関係" in out["operator"]
    assert out["comparison"]["cheapest_order"]["mall"] == "rakuten"
    assert [t["mall"] for t in out["comparison"]["to_check"]] == ["yahoo"]


def test_public_mcp_rakuten_only_result_has_no_credits_key():
    out = mcp_call(gate_of({"rakuten": FakeAdapter({(KW, 1): ([make_offer("r", f"{KW} 60枚", 1500)], 1)})}),
                   "search_products", {"keywords": [KW]})
    assert out["ok"] and "credits" not in out and out["operator"] == credit.OPERATOR_SHORT and out["credit"] == credit.CREDIT_TEXT


def test_public_mcp_malls_select_and_reject():
    gate = gate_of(two_malls())
    out = mcp_call(gate, "search_products", {"keywords": [KW], "malls": ["rakuten"]})
    assert out["malls"] == ["rakuten"] and all(o["mall"] == "rakuten" for o in out["offers"]) and "credits" not in out
    ads = two_malls()
    out = mcp_call(gate_of(ads), "search_products", {"keywords": [KW], "malls": ["amazon"]})
    assert out["ok"] is False and out["error"]["kind"] == "invalid_request" and ads["rakuten"].calls == [] and ads["yahoo"].calls == []
    only = {"rakuten": FakeAdapter({})}
    out = mcp_call(gate_of(only), "compare_offers", {"keywords": [KW], "malls": ["yahoo"]})
    assert out["ok"] is False and out["error"]["kind"] == "invalid_request" and only["rakuten"].calls == []
    out = mcp_call(gate_of(two_malls()), "compare_offers", {"keywords": [KW], "malls": []})
    assert out["ok"] is False and out["error"]["kind"] == "invalid_request"


def test_public_mcp_one_mall_failing_still_answers():
    ads = two_malls()
    from shopping.adapters.base import AdapterError
    ads["yahoo"] = FakeYahoo({(KW, 1): AdapterError("rate_limited")})
    out = mcp_call(gate_of(ads), "compare_offers", {"keywords": [KW]})
    assert out["ok"] and any("Yahoo!ショッピングは rate_limited で取得できなかった（楽天だけで比較）" == n for n in out["notes"])
    assert out["credits"][1].startswith("Webサービス by Yahoo!")      # 使おうとしたモールのクレジット


def test_stdio_mcp_default_is_mock_with_both_malls():
    async def go():
        async with Client(build_server()) as c:
            return await c.call_tool("compare_offers", {"keywords": [KW], "desired_quantity": 60})
    out = asyncio.run(asyncio.wait_for(go(), timeout=30)).structured_content
    assert out["ok"] and out["mock"] is True and out["malls"] == ["rakuten", "yahoo"]
    assert {o["mall"] for g in out["comparison"]["groups"] for o in g["offers"]} == {"rakuten", "yahoo"}


# ---- 公開 Web ----

def client_of(adapters):
    return TestClient(create_app("", gate_of(adapters)), raise_server_exceptions=False)


def test_web_footer_and_links_with_both_malls():
    r = client_of(two_malls()).get("/compare", params={"q": KW})
    assert r.status_code == 200
    html = r.text
    assert credit.CREDIT_HTML in html
    assert '<a href="https://developer.yahoo.co.jp/sitemap/">Webサービス by Yahoo! JAPAN</a>' in html       # 公式のまま
    assert "LINEヤフー株式会社とは関係ありません" in html and "楽天グループとは関係ありません" in html
    assert "楽天市場・Yahoo!ショッピングの商品を検索し" in html
    links = re.findall(r'href="(https://[^"]*)" target="_blank"', html)
    assert "https://store.shopping.yahoo.co.jp/s/y60.html" in links and "https://item.rakuten.co.jp/shop/r60/" in links
    assert "Yahoo!ショッピングの商品ページを開く" in html and "楽天市場の商品ページを開く" in html
    assert "Yahoo!ショッピング ／" in html                                                # 候補にモール名


def test_web_rakuten_only_footer_is_exactly_the_old_one():
    r = client_of({"rakuten": FakeAdapter({(KW, 1): ([make_offer("r", f"{KW} 60枚", 1500)], 1)})}).get("/search", params={"q": KW})
    assert credit.CREDIT_HTML in r.text and "Yahoo" not in r.text and "LINEヤフー" not in r.text
    assert credit.OPERATOR_TEXT in r.text and credit.FRESHNESS_TEXT in r.text
    assert "楽天側の除外語" in client_of({"rakuten": FakeAdapter({})}).get("/").text


def test_web_yahoo_url_in_unexpected_shape_gets_no_link():
    bad = yoffer("y1", f"{KW} 60枚", 1000)
    bad.item_url, bad.item_url_status = "https://store.shopping.yahoo.co.jp/s/", "ok"      # 形が違うのに ok と書かれても、モールごとの形で再判定
    rak = make_offer("r1", f"{KW} 60枚", 1000)
    rak.item_url = "https://store.shopping.yahoo.co.jp/s/y.html"                           # 楽天の候補に Yahoo の形の URL は出さない
    html = client_of(two_malls([rak], [bad])).get("/search", params={"q": KW}).text
    assert 'href="https://store.shopping.yahoo.co.jp' not in html


def test_web_search_shows_both_malls_and_busy_message():
    html = client_of(two_malls()).get("/search", params={"q": KW}).text
    assert html.count("商品ページを開く") == 2
    from shopping.adapters.base import AdapterError
    bad = {"rakuten": FakeAdapter({(KW, 1): AdapterError("http_429")}), "yahoo": FakeYahoo({(KW, 1): AdapterError("rate_limited")})}
    r = client_of(bad).get("/search", params={"q": KW})
    assert r.status_code == 503 and "モール側が混雑しています" in r.text
    r1 = client_of({"rakuten": FakeAdapter({(KW, 1): AdapterError("http_429")})}).get("/search", params={"q": KW})
    assert r1.status_code == 503 and "楽天側が混雑しています" in r1.text


def test_web_healthz_ignores_yahoo(monkeypatch):
    monkeypatch.setattr("shopping.web.load_credentials", lambda: type("C", (), {"present": True})())
    r = client_of(two_malls()).get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True, "credentials": True}


# ---- CLI（入口から通す 1 本: モックで --malls rakuten,yahoo） ----

def test_cli_malls_rakuten_yahoo_mock_through(capsys):
    assert cli.run(["compare", KW, "--malls", "rakuten,yahoo", "--desired-quantity", "60", "--mock"]) == 0
    out = capsys.readouterr().out
    assert "[Yahoo!ショッピング]" in out and "楽天市場: 取得 2 件" in out and "Yahoo!ショッピング: 取得 4 件" in out
    assert "クレジット: Webサービス by Yahoo! JAPAN （https://developer.yahoo.co.jp/sitemap/）" in out
    assert "クレジット: Supported by Rakuten Developers" in out
    assert "条件: Yahoo!ショッピングの商品ページで、選んだ色・サイズ・数量の価格が" in out
    assert "★ 注文の最安（確認済み・注文額が最小）: 1個 = 60 / 注文額 1,500円" in out


def test_cli_single_mall_and_default(capsys):
    assert cli.run(["search", KW, "--malls", "yahoo", "--mock", "--json"]) == 0
    import json
    d = json.loads(capsys.readouterr().out)
    assert d["malls"] == ["yahoo"] and d["sources"] == ["Yahoo!ショッピング（Yahoo! JAPAN Webサービス）"]
    assert all(o["mall"] == "yahoo" for o in d["offers"]) and d["returned"] == 4
    assert cli.run(["search", KW, "--malls", "rakuten", "--mock", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["malls"] == ["rakuten"] and "credits" not in d and d["returned"] == 2
    assert cli.run(["search", KW, "--mock", "--json"]) == 0              # 省略＝有効な全モール（モックは両方）
    assert json.loads(capsys.readouterr().out)["malls"] == ["rakuten", "yahoo"]


@pytest.mark.parametrize("arg", ["amazon", "rakuten,amazon", "", ","])
def test_cli_unknown_malls_is_invalid_request(arg, capsys):
    assert cli.run(["search", KW, "--malls", arg, "--mock"]) == 1
    assert "invalid_request" in capsys.readouterr().err


def test_cli_live_without_yahoo_key_rejects_yahoo_and_never_calls_it(capsys, monkeypatch):
    monkeypatch.setattr("shopping.service.load_credentials",
                        lambda *a, **k: __import__("shopping.config", fromlist=["x"]).RakutenCredentials("", ""))
    assert cli.run(["search", KW, "--live", "--malls", "yahoo"]) == 1
    assert "invalid_request" in capsys.readouterr().err
    assert cli.run(["search", KW, "--live"]) == 1                            # 楽天は鍵なしで止まる（Yahoo の鍵も無いので楽天だけ）
    assert "missing_credentials" in capsys.readouterr().err
