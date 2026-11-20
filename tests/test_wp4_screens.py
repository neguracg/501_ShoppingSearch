"""WP4-3: S8（UTF-8 128 バイト）・S9（一覧でも含む/除く語）・S10（指数表記なし・小さな単価）の固定。
implementer の自作の確認（緑は証明ではない）。実 API は呼ばない。入口×項目のセルは test_wp4_cells.py。"""
import json

import pytest
from fastapi.testclient import TestClient

from fakes import FakeAdapter, FakeOpener, make_offer
from shopping import inputs, service
from shopping.adapters import rakuten
from shopping.adapters.base import AdapterError
from shopping.guard import Gate, GuardedAdapter, RateLimiter
from shopping.pricing import compare
from shopping.pricing import format_unit_price
from shopping.quantity import format_amount
from shopping.web import create_app
from test_wp4_cells import Clock, VALID, make_env, mcp, offers  # noqa: F401  (環境変数は cells 側の autouse と同じ)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "APPID-SECRET-1234567890")
    monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "ACCESSKEY-SECRET-abcdef")
    monkeypatch.delenv("SHOPPING_MOCK", raising=False)


# --- S8: 長さの判定は Gate とアダプタで同じ関数 -----------------------------------------------------

def test_s8_adapter_and_gate_share_one_function_and_reject_before_any_network():
    assert rakuten.fits_limit is inputs.fits_limit
    op = FakeOpener({"count": 0, "Items": []})
    ad = rakuten.RakutenAdapter("id", "key", opener=op)
    for kw, ng in [("あ" * 43, None), ("x" * 129, None), ("洗剤", "あ" * 43), ("洗剤", "x" * 129)]:
        with pytest.raises(AdapterError) as e:
            ad.search(kw, ng_keyword=ng)
        assert str(e.value) and "invalid_request" in str(e.value)
    assert op.requests == []
    ad.search("あ" * 42, ng_keyword="x" * 128)                   # ちょうど上限は通る
    assert len(op.requests) == 1


def test_s8_screen_text_says_42_zenkaku_chars():
    client, _ = make_env()
    html = client.get("/").text
    assert "全角42文字（半角128文字）" in html and "全角64文字" not in html


# --- S9: 一覧でも含む語・除く語を使う。basis は一覧では使わない旨を出す -------------------------------

def test_s9_service_search_applies_include_and_exclude_terms():
    ad = FakeAdapter({("洗濯洗剤", 1): (offers(), 3)})
    d = service.search_products(["洗濯洗剤"], include_terms=["詰め替え"], adapter=ad)
    assert [o["item_code"] for o in d["offers"]] == ["a", "b"] and "含む語で除外: 1件" in d["notes"]
    d = service.search_products(["洗濯洗剤"], exclude_terms=["900g"], adapter=ad)
    assert [o["item_code"] for o in d["offers"]] == ["b", "c"] and "除く語で除外: 1件" in d["notes"]
    d = service.search_products(["洗濯洗剤"], include_terms=["2L"], adapter=ad)      # 数字境界は compare と同じ
    assert d["offers"] == []
    d = service.search_products(["洗濯洗剤"], include_terms=[1], adapter=ad)
    assert d["ok"] is False and d["error"]["kind"] == "invalid_request"


def test_s9_web_search_filters_and_explains_that_basis_is_unused():
    client, ad = make_env(limit=1000)
    r = client.get("/search", params={"q": "洗濯洗剤", "include": "詰め替え", "exclude": "1.5kg"})
    assert r.status_code == 200 and "900g×4袋" in r.text and "本体" not in r.text and "1.5kg" not in r.text
    assert "含む語で除外" in r.text
    r = client.get("/search", params={"q": "洗濯洗剤", "basis": "g"})
    assert r.status_code == 200 and "比べる単位は一覧では使っていません" in r.text
    assert "比べる単位は一覧では使っていません" not in client.get("/search", params={"q": "洗濯洗剤"}).text
    assert "「一覧で見る」では使いません" in client.get("/").text


def test_s9_mcp_search_accepts_include_exclude_terms():
    client, _ = make_env(limit=1000)
    with client:
        rejected, d = mcp(client, "search_products", dict(VALID, include_terms=["詰め替え"],
                                                         exclude_terms=["1.5kg"]))
    assert not rejected and [o["item_code"] for o in d["offers"]] == ["a"]


def test_s9_cli_search_accepts_include_exclude(capsys):
    import cli
    assert cli.run(["search", "洗濯洗剤", "--mock", "--json", "--include", "詰め替え", "--exclude", "本体"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["offers"] and all(
        "詰め替え" in o["name"] and "本体" not in o["name"] for o in data["offers"])


# --- S10: 指数表記を使わない・小さな単価は桁を増やす ---------------------------------------------------

@pytest.mark.parametrize("x,text", [
    (1000000, "1,000,000"), (1e6, "1,000,000"), (1e12, "1,000,000,000,000"), (900, "900"),
    (5400.0, "5,400"), (0.5, "0.5"), (1500.25, "1,500.25"), (0.000001, "0.000001"), (0, "0"),
])
def test_s10_format_amount_has_no_exponent(x, text):
    assert format_amount(x) == text


@pytest.mark.parametrize("x,text", [
    (55.5555, "55.56"), (0.5, "0.50"), (0.004, "0.004"), (0.0004, "0.0004"), (0.00004, "0.0000"),
    (1234567.891, "1,234,567.89"), (0.0049, "0.005"),
])
def test_s10_format_unit_price_adds_digits_when_significant_digits_vanish(x, text):
    assert format_unit_price(x) == text


def test_s10_json_unit_price_keeps_significant_digits_and_screens_show_no_exponent():
    from shopping.web_view import _qty
    big = make_offer("big", "モバイルバッテリー 1000000mAh", 400)
    d = service.compare_offers(["xx"], basis="mAh", adapter=FakeAdapter({("xx", 1): ([big], 1)}))
    one = d["comparison"]["groups"][0]["offers"][0]
    assert one["unit_price"] == pytest.approx(0.0004, abs=1e-9) and one["unit_price"] != 0.0
    text = _qty(one)
    assert "1,000,000mAh" in text and "e+" not in text and "0.0004円" in text
    import cli
    assert "1,000,000mAh" in cli._qty(one) and "e+" not in cli._qty(one)
    # WP14 W2: 同じ商品を n 個買う案になったので、「満たす候補がない」文言は上限で範囲に収まらない時に出る（数の整形は同じ）
    c = compare([make_offer("a", "水 300ml", 100)], desired_quantity=1e6, desired_quantity_max=1e6 + 1)
    assert any("必要数量 1,000,000ml 以上" in cv and "e+" not in cv for cv in c.caveats)
