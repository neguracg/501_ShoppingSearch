# @owns WP11-3 「1 文字だけの語」の誤り文（inputs.too_short_message）が実際に弾いた語を示し、3 入口で同じ文面になることの自作確認
"""WP11-3: 誤り文の例が固定（DELTA 2）だったのを、実際に弾いた語と直前の語につないだ形に変える。

直前の語が無い（先頭の語が 1 文字）時は「語を 2 文字以上に」だけ。入力の全文は入れない（直前の語は 20 文字まで）。
"""
import pytest
from fastapi.testclient import TestClient

import cli
from fakes import FakeAdapter
from shopping import inputs, service
from shopping.guard import Gate, GuardedAdapter, RateLimiter
from shopping.inputs import KeywordTermTooShort, check_term_lengths, validate
from shopping.web import create_app

from test_mcp_http import RPC_HEADERS


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("RAKUTEN_APPLICATION_ID", raising=False)
    monkeypatch.delenv("RAKUTEN_ACCESS_KEY", raising=False)
    monkeypatch.delenv("SHOPPING_MOCK", raising=False)


def msg(texts, label="検索語"):
    with pytest.raises(KeywordTermTooShort) as e:
        check_term_lengths(texts, label)
    return str(e.value)


def test_message_names_the_rejected_term_and_the_joined_form():
    m = msg(["ヌプシジャケット L"])
    assert "『L』" in m and "『ヌプシジャケット L』は『ヌプシジャケットL』" in m
    assert "DELTA" not in m and "EcoFlow" not in m          # 固定の例は出ない
    assert m.startswith("検索語に、") and "漢字 1 文字は可" in m and "2 文字以上" in m


def test_message_uses_the_term_just_before_the_first_bad_one():
    m = msg(["EcoFlow DELTA 2 対応 a"])
    assert "『2』" in m and "『DELTA 2』は『DELTA2』" in m
    assert "EcoFlow DELTA 2 対応" not in m                    # 語全体（入力の全文）は入れない


def test_full_width_space_and_the_label_are_kept():
    m = msg("洗剤　ａ", "除外語（楽天側）")
    assert m.startswith("除外語（楽天側）に、") and "『ａ』" in m and "『洗剤 ａ』は『洗剤ａ』" in m


def test_first_term_alone_has_no_join_suggestion():
    for text in ("L", "L ジャケット", "a b"):
        m = msg([text])
        assert "『" + text.split()[0] + "』" in m and "2 文字以上にしてください" in m
        assert "つなげ" not in m and "のように" not in m


def test_the_first_bad_item_in_a_list_is_the_one_reported():
    m = msg(["洗濯洗剤", "水 の", "単3 a"])
    assert "『の』" in m and "『a』" not in m


def test_long_previous_term_is_cut_to_its_tail_and_control_chars_are_dropped():
    long_prev = "あ" * 30 + "ヌプシ"
    m = msg([long_prev + " L"])
    assert "あ" * 21 not in m and "…" + "あ" * 17 + "ヌプシ L" in m
    m2 = msg(["ab\x00\x1bcd L"])
    assert "\x00" not in m2 and "\x1b" not in m2 and "abcd L" in m2


def test_validate_and_service_give_the_same_text():
    with pytest.raises(KeywordTermTooShort) as a:
        validate(keywords=["ヌプシジャケット L"])
    d = service.search_products(["ヌプシジャケット L"], adapter=FakeAdapter({}), sleep=lambda s: None)
    assert d["error"]["kind"] == "keyword_term_too_short" and d["error"]["message"] == str(a.value)


def test_ng_keyword_uses_its_own_label():
    with pytest.raises(KeywordTermTooShort) as a:
        validate(keywords=["洗濯洗剤"], ng_keyword="ヌプシジャケット L")
    assert str(a.value).startswith("除外語（楽天側）に、") and "『ヌプシジャケットL』" in str(a.value)


def make_env():
    ad = FakeAdapter({})
    gate = Gate(GuardedAdapter(ad, sleep=lambda s: None), RateLimiter(limit=1000))
    return TestClient(create_app("", gate), raise_server_exceptions=False), ad


def test_three_entrances_show_the_same_message(capsys):
    expect = msg(["ヌプシジャケット L"])
    client, ad = make_env()
    with client:
        web = client.get("/search", params={"q": "ヌプシジャケット L"})
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "compare_offers", "arguments": {"keywords": ["ヌプシジャケット L"]}}}
        mcp = client.post("/mcp", json=body, headers=RPC_HEADERS).json()["result"]["structuredContent"]
    assert web.status_code == 400 and expect in web.text           # 公開Web
    assert mcp["error"]["kind"] == "keyword_term_too_short" and mcp["error"]["message"] == expect   # 公開MCP
    assert cli.run(["search", "ヌプシジャケット L", "--mock"]) == 1                                   # CLI
    assert expect in capsys.readouterr().err
    assert ad.calls == []
