"""WP2-3: 公開Web（AC-W1〜W8）。実 API は呼ばない（FakeAdapter / MockAdapter）。"""
import re
import threading

import pytest
from fastapi.testclient import TestClient

from fakes import FakeAdapter, make_offer
from shopping.adapters.base import AdapterError
from shopping.adapters.mock import MockAdapter
from shopping.guard import Gate, GuardedAdapter, RateLimiter
from shopping.web import create_app
from shopping.credit import CREDIT_HTML, FRESHNESS_TEXT, OPERATOR_TEXT

SECRET_ID = "APPID-SECRET-1234567890"
SECRET_KEY = "ACCESSKEY-SECRET-abcdef"
CREDIT = '<a href="https://developers.rakuten.com/" target="_blank">Supported by Rakuten Developers</a>'


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def offers():
    return [make_offer("a", "洗濯洗剤 詰め替え 900g×4袋", 2400, shipping_status="included"),
            make_offer("b", "洗濯洗剤 詰め替え 1.5kg", 1500, shipping_status="separate"),
            make_offer("c", "洗濯洗剤 本体 400g", 700, shipping_status="unknown")]


def fake(pages=None):
    return FakeAdapter(pages or {("洗濯洗剤", 1): (offers(), 3)})


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("RAKUTEN_APPLICATION_ID", SECRET_ID)
    monkeypatch.setenv("RAKUTEN_ACCESS_KEY", SECRET_KEY)
    monkeypatch.delenv("SHOPPING_MOCK", raising=False)


def make_client(base="", adapter=None, limiter=None, clock=None):
    clock = clock or Clock()
    ga = GuardedAdapter(adapter or fake(), clock=clock, sleep=clock.sleep)
    gate = Gate(ga, limiter or RateLimiter(limit=1000, clock=clock))
    app = create_app(base, gate)
    return TestClient(app, raise_server_exceptions=False), gate, ga


def attr_urls(html):
    return re.findall(r'(?:href|action|formaction|src)="([^"]*)"', html)


PATHS = ["/", "/search?q=洗濯洗剤", "/compare?q=洗濯洗剤"]


@pytest.mark.parametrize("base", ["", "/kaimono"])
def test_all_routes_ok_and_links_under_base_path(base):
    c, _, _ = make_client(base)
    for p in PATHS:
        r = c.get(base + p)
        assert r.status_code == 200, p
        for u in attr_urls(r.text):
            ok = (u == base or u.startswith(base + "/")
                  or u.startswith("https://developers.rakuten.com/")
                  or u.startswith("https://item.rakuten.co.jp/"))
            assert ok and (base or u != ""), (p, u)
        if base:
            assert all(u.startswith(("/kaimono", "https://")) for u in attr_urls(r.text))
    h = c.get(base + "/healthz")
    assert h.status_code == 200 and h.json() == {"ok": True, "credentials": True}


def test_base_path_without_slash_redirects_and_unprefixed_is_404():
    c, _, _ = make_client("/kaimono")
    r = c.get("/kaimono", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/kaimono/"
    assert c.get("/").status_code == 404 and c.get("/healthz").status_code == 404


def test_index_has_form_with_both_modes():
    c, _, _ = make_client("/kaimono")
    html = c.get("/kaimono/").text
    assert 'formaction="/kaimono/search"' in html and 'formaction="/kaimono/compare"' in html
    for name in ("q", "ng", "min_price", "max_price", "include", "exclude", "basis"):
        assert f'name="{name}"' in html
    for unit in ("個", "ml", "g", "m", "W", "mAh", "Wh"):
        assert f'<option value="{unit}"' in html


def test_footer_credit_operator_and_freshness_on_every_page():
    assert CREDIT in CREDIT_HTML
    c, _, _ = make_client("/kaimono", limiter=RateLimiter(limit=1))
    pages = [c.get("/kaimono" + p) for p in PATHS[:2]]          # 2 件目で 429 になる想定
    pages += [c.get("/kaimono/search"), c.get("/kaimono/nothing")]  # 400 と 404
    c2, _, _ = make_client("/kaimono", adapter=fake({("洗濯洗剤", 1): AdapterError("http_429")}))
    pages.append(c2.get("/kaimono/search?q=洗濯洗剤"))      # 503
    pages.append(c.get("/kaimono/compare?q=洗濯洗剤"))
    assert {p.status_code for p in pages} >= {200, 400, 404, 429, 503}
    for r in pages:
        assert CREDIT_HTML in r.text, r.status_code
        assert OPERATOR_TEXT in r.text and FRESHNESS_TEXT in r.text


def test_external_links_only_rakuten():
    c, _, _ = make_client("/kaimono")
    for p in PATHS:
        html = c.get("/kaimono" + p).text
        hosts = set(re.findall(r'https?://([^/"\'\s<]+)', html))
        assert hosts <= {"item.rakuten.co.jp", "developers.rakuten.com"}, (p, hosts)
        assert "github" not in html.lower()


def test_item_link_opens_new_tab_noopener_and_non_rakuten_url_is_not_linked():
    bad = make_offer("z", "洗濯洗剤 詰め替え 900g", 900)
    bad.item_url = "https://evil.example.com/x"
    bad.item_url_status = "needs_review"
    c, _, _ = make_client("/kaimono", adapter=fake({("洗濯洗剤", 1): ([bad] + offers(), 4)}))
    html = c.get("/kaimono/search?q=洗濯洗剤").text
    assert 'target="_blank" rel="noopener"' in html
    assert "evil.example.com" not in html


def test_compare_shows_caveats_notes_groups_and_label_split():
    c, _, _ = make_client("/kaimono")
    html = c.get("/kaimono/compare?q=洗濯洗剤").text
    assert "断定できない理由・注意" in html and "送料が不明" in html
    assert "注意・出典" in html and "楽天市場" in html
    assert "100gあたり" in html and "洗濯洗剤 詰め替え 1.5kg" in html     # 単位あたりの比較（基準は表示に出る）
    assert "仕様の違い（濃縮・層数・型番・色など）は判定していません" in html   # 常設の注意


def test_compare_with_mixed_count_units_shows_the_main_group_card_and_human_caveat():
    # WP14 W3: basis 個で 本 と 個 が混ざる時。画面は主グループ（候補数が最多の 本）の最安を出し、数え方の違う候補は比べない
    mixed = [make_offer("a", "文化たきつけ 18本入り", 179, shipping_status="included"),
             make_offer("b", "文化たきつけ 18本入り ×2個セット", 580, shipping_status="included"),
             make_offer("c", "文化たきつけ10個セット", 3200, shipping_status="included")]
    c, _, _ = make_client("", adapter=fake({("文化たきつけ", 1): (mixed, 3)}))
    r = c.get("/compare?q=文化たきつけ&basis=個")
    assert r.status_code == 200
    html = r.text
    assert "1個あたり［本］の単価が最安" in html
    assert "数え方の違う候補（個 1件）は比べていません" in html and "主グループ［本］" in html
    assert "［本］" in html and "［個］" in html                      # グループの見出し
    assert "該当なし" not in html.split("単価が最安", 1)[1].split("支払総額が最安", 1)[0]    # 単価の欄は空ではない


def test_search_fixed_pages_and_hits():
    ad = fake()
    c, _, _ = make_client("", adapter=ad)
    c.get("/search?q=洗濯洗剤&pages=3&hits=5")
    assert ad.calls and all(kw.get("page") == 1 and kw.get("hits") == 30 for _, kw in ad.calls)


def test_web_screen_has_no_paging_notes_and_charges_one_per_search():
    pages = {("洗濯洗剤", 1): ([make_offer(f"x{i}", f"洗濯洗剤 {i} 900g", 1000 + i, shipping_status="included")
                              for i in range(30)], 500)}
    clock = Clock()
    lim = RateLimiter(limit=3, clock=clock)
    c, _, _ = make_client("", adapter=fake(pages), limiter=lim)
    for path in ("/search", "/compare", "/search"):                # Web も MCP も 1 回=1 回分
        r = c.get(path + "?q=洗濯洗剤")
        assert r.status_code == 200 and "start_page" not in r.text and "続きは" not in r.text
    assert c.get("/search?q=洗濯洗剤").status_code == 429


def test_web_compare_screen_still_shows_only_10_per_group():
    pages = {("洗濯洗剤", 1): ([make_offer(f"x{i}", f"洗濯洗剤 {i} 900g", 1000 + i, shipping_status="included")
                              for i in range(25)], 25)}
    c, _, _ = make_client("", adapter=fake(pages))
    html = c.get("/compare?q=洗濯洗剤").text
    assert "（25件）" in html and "ほか 15 件は省略しています" in html      # 画面の出力は従来どおり 10 件


def test_multiple_keywords_split_by_newline_and_comma_max_five():
    ad = fake()
    c, _, _ = make_client("", adapter=ad)
    assert c.get("/search", params={"q": "あい\nうえ,おか、きく"}).status_code == 200
    assert [k for k, _ in ad.calls] == ["あい", "うえ", "おか", "きく"]
    assert c.get("/search", params={"q": "11,22,33,44,55,66"}).status_code == 400


@pytest.mark.parametrize("params", [
    {}, {"q": "  "}, {"q": "x" * 129}, {"q": "あ" * 43}, {"q": "aa", "min_price": "abc"},
    {"q": "aa", "max_price": "-5"}, {"q": "aa", "ng": "x" * 129}, {"q": "aa", "ng": "aa bb cc dd ee ff"},
    {"q": "aa", "min_price": "①②"}, {"q": "aa", "max_price": "²"}, {"q": "aa", "min_price": "１２３"},
    {"q": "aa", "max_price": "10000001"}, {"q": "aa", "max_price": "9" * 5000},
])
@pytest.mark.parametrize("path", ["/search", "/compare"])
def test_invalid_input_is_400_and_does_not_call_api(path, params):
    ad = fake()
    c, gate, ga = make_client("", adapter=ad)
    assert c.get(path, params=params).status_code == 400
    assert ad.calls == [] and ga.api_calls == 0


@pytest.mark.parametrize("params", [{"q": "aa", "include": "x" * 129}, {"q": "aa", "exclude": "a b c d e f"},
                                    {"q": "aa", "basis": "ふしぎ"}, {"q": "aa", "basis": "x" * 500},
                                    {"q": "aa", "include": "あ" * 43}])
def test_invalid_compare_options_are_400_and_do_not_call_api(params):
    ad = fake()
    c, _, ga = make_client("", adapter=ad)
    r = c.get("/compare", params=params)
    assert r.status_code == 400 and ad.calls == [] and ga.api_calls == 0


def test_limit_text_matches_the_checked_limit_and_input_never_echoed():
    c, _, _ = make_client("")
    r = c.get("/search", params={"q": "あ" * 43})
    assert r.status_code == 400 and "全角42文字（半角128文字）" in r.text and "あ" * 43 not in r.text
    assert c.get("/search", params={"q": "あ" * 42}).status_code == 200      # ちょうど上限は通る
    assert c.get("/search", params={"q": "x" * 128}).status_code == 200


def test_rejected_input_does_not_consume_the_ip_budget():
    clock = Clock()
    c, _, _ = make_client("", limiter=RateLimiter(limit=2, clock=clock), clock=clock)
    h = {"CF-Connecting-IP": "203.0.113.50"}
    for _ in range(5):
        assert c.get("/search", params={"q": "aa", "min_price": "abc"}, headers=h).status_code == 400
        assert c.get("/search", params={"q": "あ" * 43}, headers=h).status_code == 400
    assert c.get("/search", params={"q": "洗濯洗剤"}, headers=h).status_code == 200
    assert c.get("/search", params={"q": "洗濯洗剤"}, headers=h).status_code == 200


def test_price_and_ng_are_passed_through():
    ad = fake()
    c, _, _ = make_client("", adapter=ad)
    c.get("/search", params={"q": "紙", "ng": "訳あり", "min_price": "1,000", "max_price": "5000"})
    kw = ad.calls[0][1]
    assert kw["ng_keyword"] == "訳あり" and kw["min_price"] == 1000 and kw["max_price"] == 5000


# --- AC-W5/W6 流量保護 ---

def test_rate_limit_per_ip_returns_429_and_other_ip_still_ok():
    clock = Clock()
    c, _, _ = make_client("/kaimono", limiter=RateLimiter(limit=3, clock=clock), clock=clock)
    h = {"CF-Connecting-IP": "203.0.113.5"}
    codes = [c.get("/kaimono/search?q=洗濯洗剤", headers=h).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    r = c.get("/kaimono/search?q=洗濯洗剤", headers=h)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and "少し待って" in r.text
    assert c.get("/kaimono/search?q=洗濯洗剤", headers={"CF-Connecting-IP": "203.0.113.9"}).status_code == 200
    clock.t += 61
    assert c.get("/kaimono/search?q=洗濯洗剤", headers=h).status_code == 200


def test_rate_limit_ignores_invalid_forwarded_ip_header():
    clock = Clock()
    c, _, _ = make_client("", limiter=RateLimiter(limit=1, clock=clock), clock=clock)
    h = {"CF-Connecting-IP": "not-an-ip"}
    assert c.get("/search?q=洗濯洗剤", headers=h).status_code == 200
    h2 = {"CF-Connecting-IP": "also-bad"}
    assert c.get("/search?q=洗濯洗剤", headers=h2).status_code == 429  # 同じ接続元として数える


def test_healthz_and_index_are_not_rate_limited():
    c, _, _ = make_client("", limiter=RateLimiter(limit=1))
    for _ in range(5):
        assert c.get("/healthz").status_code == 200 and c.get("/").status_code == 200


def test_cache_second_identical_search_does_not_call_adapter():
    ad = fake()
    c, _, ga = make_client("", adapter=ad)
    c.get("/search?q=洗濯洗剤")
    c.get("/compare?q=洗濯洗剤")
    c.get("/search?q=洗濯洗剤")
    assert len(ad.calls) == 1 and ga.api_calls == 1


def test_cache_key_includes_filters():
    ad = fake()
    c, _, _ = make_client("", adapter=ad)
    c.get("/search?q=洗濯洗剤")
    c.get("/search?q=洗濯洗剤&max_price=1000")
    assert len(ad.calls) == 2


@pytest.mark.parametrize("kind,status", [("http_429", 503), ("timeout", 503), ("busy", 503),
                                         ("http_403", 503), ("missing_credentials", 503)])
def test_adapter_errors_become_friendly_pages_without_leaking(kind, status):
    c, _, _ = make_client("/kaimono", adapter=fake({("洗濯洗剤", 1): AdapterError(kind)}))
    for p in ("/search", "/compare"):
        r = c.get("/kaimono" + p + "?q=洗濯洗剤")
        assert r.status_code == status
        for leak in (kind, SECRET_ID, SECRET_KEY, "Traceback", "AdapterError"):
            assert leak not in r.text
    r = c.get("/kaimono/search?q=洗濯洗剤")
    assert ("混雑" in r.text) == (kind in ("http_429", "timeout", "busy"))


def test_unexpected_exception_is_generic_500_without_detail():
    class Boom(FakeAdapter):
        def search(self, keyword, **kw):
            raise RuntimeError(f"secret {SECRET_KEY}")

    c, _, _ = make_client("", adapter=Boom({}))
    r = c.get("/search?q=aa")
    assert r.status_code == 500 and SECRET_KEY not in r.text and CREDIT_HTML in r.text


# --- AC-W2 / W8 ---

def test_no_secret_values_anywhere_in_responses_and_no_cookies():
    c, _, _ = make_client("/kaimono")
    for p in PATHS + ["/healthz", "/search", "/nothing"]:
        r = c.get("/kaimono" + p)
        assert SECRET_ID not in r.text and SECRET_KEY not in r.text
        assert SECRET_ID not in str(r.headers) and SECRET_KEY not in str(r.headers)
        assert "set-cookie" not in r.headers


def test_no_regular_items_or_login_surface():
    c, _, _ = make_client("/kaimono")
    for p in ("/regular", "/regulars", "/login", "/find_regular_item", "/mcp-regular"):
        assert c.get("/kaimono" + p).status_code in (404, 405)
    html = c.get("/kaimono/").text
    assert "定番" not in html and "password" not in html.lower()
    assert "<script" not in html


def test_security_headers_and_no_external_assets():
    c, _, _ = make_client("")
    r = c.get("/")
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert "<link" not in r.text and "<script" not in r.text and "@import" not in r.text


def test_mock_mode_notes_and_guarded_mock_detection(monkeypatch):
    clock = Clock()
    ga = GuardedAdapter(MockAdapter(), clock=clock, sleep=clock.sleep)
    assert ga.is_mock
    app = create_app("", Gate(ga, RateLimiter(limit=100, clock=clock)))
    c = TestClient(app)
    r = c.get("/search", params={"q": "洗濯洗剤"})
    assert r.status_code == 200 and "架空" in r.text


def test_healthz_is_503_without_credentials_and_does_not_call_api(monkeypatch):
    # C6: 本番で鍵の入れ忘れを unhealthy で検知する
    monkeypatch.delenv("RAKUTEN_APPLICATION_ID")
    monkeypatch.delenv("RAKUTEN_ACCESS_KEY")
    monkeypatch.setattr("shopping.web.load_credentials",
                        lambda: type("C", (), {"present": False})())
    ad = fake()
    c, _, _ = make_client("", adapter=ad)
    r = c.get("/healthz")
    assert r.status_code == 503 and r.json() == {"ok": False, "credentials": False} and ad.calls == []


def test_healthz_is_200_in_mock_mode_even_without_credentials(monkeypatch):
    # モック運用（SHOPPING_MOCK=1）は鍵を要さない
    monkeypatch.setattr("shopping.web.load_credentials", lambda: type("C", (), {"present": False})())
    clock = Clock()
    gate = Gate(GuardedAdapter(MockAdapter(), clock=clock, sleep=clock.sleep), RateLimiter(limit=100))
    r = TestClient(create_app("", gate)).get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True, "credentials": False}


# --- WP3: 含む語・除く語・比べる単位 ---

def test_compare_passes_include_exclude_basis_and_shows_notes():
    c, _, _ = make_client("")
    html = c.get("/compare", params={"q": "洗濯洗剤", "include": "詰め替え", "exclude": "1.5kg",
                                     "basis": "g"}).text
    assert "洗濯洗剤 詰め替え 900g×4袋" in html
    assert "洗濯洗剤 詰め替え 1.5kg" not in html and "洗濯洗剤 本体 400g" not in html
    assert "含む語で除外: 1件" in html and "除く語で除外: 1件" in html


def test_compare_basis_alias_and_piece_basis():
    c, _, _ = make_client("")
    assert "100mlあたり" not in c.get("/compare", params={"q": "洗濯洗剤", "basis": "個"}).text
    assert "1個あたり" in c.get("/compare", params={"q": "洗濯洗剤", "basis": "個"}).text
    assert "100gあたり" in c.get("/compare", params={"q": "洗濯洗剤", "basis": "kg"}).text


@pytest.mark.parametrize("basis", ["ふしぎ", "1個"])
def test_compare_invalid_basis_is_400_and_does_not_call_api(basis):
    ad = fake()
    c, _, _ = make_client("", adapter=ad)
    assert c.get("/compare", params={"q": "洗濯洗剤", "basis": basis}).status_code == 400
    assert ad.calls == []
