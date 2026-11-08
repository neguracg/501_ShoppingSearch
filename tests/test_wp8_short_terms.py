# @owns WP8-2 楽天が HTTP 400 にする「1 文字だけの語」の事前検査（inputs.py）を、3 つの入口で固定する自作確認
"""WP8-2: keyword・NGKeyword の空白（半角・全角）区切りの語に、漢字以外の 1 文字の語があると楽天は HTTP 400
（2026-11-06 実測。EcoFlow DELTA 2・単3 a・水 の・水 ２ など）。送る前に弾き、利用者に理由を返す。
語を勝手につなげたり捨てたりはしない。実 API は呼ばない（緑は証明ではない）。

入口: 公開Web（/search・/compare）・公開MCP（search_products・compare_offers）・CLI（cli.run、service 経由）。
"""
import pytest
from fastapi.testclient import TestClient

import cli
from fakes import FakeAdapter, make_offer
from shopping import inputs, service
from shopping.credit import CREDIT_TEXT
from shopping.guard import Gate, GuardedAdapter, RateLimiter
from shopping.inputs import InvalidInput, KeywordTermTooShort, validate
from shopping.web import create_app

from test_mcp_http import RPC_HEADERS

SHORT = ["a", "2", "EcoFlow DELTA 2", "EcoFlow DELTA 2 対応", "単3 a", "水 の", "水 ア", "水 ー", "水 ２", "水 Ａ",
         "水 ！", "水　a"]
FINE = ["EcoFlow DELTA2", "EcoFlow DELTA2 対応", "単3", "水 力", "力", "ab", "水 24", "水　ab", "ＤＥＬＴＡ２",
        "洗濯洗剤 詰め替え"]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("RAKUTEN_APPLICATION_ID", raising=False)
    monkeypatch.delenv("RAKUTEN_ACCESS_KEY", raising=False)
    monkeypatch.delenv("SHOPPING_MOCK", raising=False)


@pytest.mark.parametrize("kw", SHORT)
def test_validate_rejects_a_one_char_term_in_keywords_and_in_ng_keyword(kw):
    with pytest.raises(KeywordTermTooShort) as e:
        validate(keywords=[kw])
    assert e.value.kind == "keyword_term_too_short" and isinstance(e.value, InvalidInput)
    assert "1 文字" in str(e.value) and (len(kw.split()) <= 2 or kw not in str(e.value))   # 入れるのは弾いた語と直前の語だけ。3 語以上の入力の全文は入れない（WP11-3）
    with pytest.raises(KeywordTermTooShort):
        validate(keywords=["洗濯洗剤"], ng_keyword=kw)


@pytest.mark.parametrize("kw", FINE)
def test_validate_accepts_two_char_terms_and_a_single_kanji(kw):
    validate(keywords=[kw])
    validate(keywords=["洗濯洗剤"], ng_keyword=kw)


def test_one_char_terms_in_the_local_filters_are_not_a_rakuten_problem():
    # include_terms・exclude_terms は道具の側の絞り込み（楽天には送らない）ので 1 文字でもよい
    validate(keywords=["洗濯洗剤"], include_terms=["a", "2"], exclude_terms=["の"])


def test_the_judgement_has_one_owner():
    assert inputs.has_too_short_term("EcoFlow DELTA 2") and not inputs.has_too_short_term("EcoFlow DELTA2")
    assert not inputs.has_too_short_term("") and not inputs.has_too_short_term("   ")


# --- 公開Web ----------------------------------------------------------------------------------

def make_env():
    ad = FakeAdapter({("洗濯洗剤", 1): ([make_offer("a", "洗濯洗剤 900g", 500, shipping_status="included")], 1)})
    gate = Gate(GuardedAdapter(ad, sleep=lambda s: None), RateLimiter(limit=1000))
    return TestClient(create_app("", gate), raise_server_exceptions=False), ad


@pytest.mark.parametrize("path", ["/search", "/compare"])
@pytest.mark.parametrize("field", ["q", "ng"])
def test_web_rejects_with_a_reason_and_never_calls_the_api(path, field):
    client, ad = make_env()
    with client:
        params = {"q": "洗濯洗剤"}
        params[field] = "EcoFlow DELTA 2"
        r = client.get(path, params=params)
    assert r.status_code == 400 and "1 文字" in r.text and "DELTA2" in r.text
    assert ad.calls == []


@pytest.mark.parametrize("path", ["/search", "/compare"])
def test_web_passes_the_joined_form(path):
    client, ad = make_env()
    with client:
        r = client.get(path, params={"q": "洗濯洗剤", "ng": "EcoFlow DELTA2"})
    assert r.status_code == 200 and len(ad.calls) == 1


# --- 公開MCP ----------------------------------------------------------------------------------

def mcp(client, tool, args):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    r = client.post("/mcp", json=body, headers=RPC_HEADERS)
    assert r.status_code == 200, r.text
    return r.json()["result"]["structuredContent"]


@pytest.mark.parametrize("tool", ["search_products", "compare_offers"])
@pytest.mark.parametrize("args", [{"keywords": ["EcoFlow DELTA 2"]},
                                  {"keywords": ["洗濯洗剤"], "ng_keyword": "単3 a"}])
def test_mcp_returns_keyword_term_too_short_and_never_calls_the_api(tool, args):
    client, ad = make_env()
    with client:
        d = mcp(client, tool, args)
    assert d["ok"] is False and d["error"]["kind"] == "keyword_term_too_short"
    assert "1 文字" in d["error"]["message"] and d["credit"] == CREDIT_TEXT
    assert ad.calls == []


@pytest.mark.parametrize("tool", ["search_products", "compare_offers"])
def test_mcp_passes_the_joined_form(tool):
    client, ad = make_env()
    with client:
        d = mcp(client, tool, {"keywords": ["洗濯洗剤"], "ng_keyword": "EcoFlow DELTA2"})
    assert d["ok"] is True and len(ad.calls) == 1


# --- CLI・service（運営者用。検査は service に一本化）---------------------------------------------

@pytest.mark.parametrize("argv", [["search", "EcoFlow DELTA 2"], ["compare", "EcoFlow DELTA 2"],
                                  ["search", "洗濯洗剤", "--ng", "単3 a"]])
def test_cli_stops_with_the_kind_and_a_reason(argv, capsys):
    assert cli.run(argv + ["--mock"]) == 1
    err = capsys.readouterr().err
    assert "keyword_term_too_short" in err and "1 文字" in err


def test_cli_passes_the_joined_form(capsys):
    assert cli.run(["search", "EcoFlow DELTA2", "--mock"]) == 0


@pytest.mark.parametrize("fn", [service.search_products, service.compare_offers])
def test_service_never_calls_the_adapter_for_a_one_char_term(fn):
    ad = FakeAdapter({})
    d = fn(["EcoFlow DELTA 2"], adapter=ad, sleep=lambda s: None)
    assert d["ok"] is False and d["error"]["kind"] == "keyword_term_too_short"
    assert ad.calls == []
