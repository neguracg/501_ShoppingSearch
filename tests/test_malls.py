"""WP17 U2: モールの選択と束ね（malls.py）・orchestrator のモール別の上限・service の malls 引数・Gate。"""
import copy
import threading

import pytest

from fakes import FakeAdapter, make_offer
from shopping import malls, service
from shopping.adapters.base import AdapterError
from shopping.adapters.mock import MockAdapter, MockYahooAdapter
from shopping.adapters.rakuten import RakutenAdapter
from shopping.adapters.yahoo import YahooAdapter
from shopping.config import YahooCredentials
from shopping.guard import Gate, GuardedAdapter, RateLimiter
from shopping.inputs import InvalidInput, check_malls
from shopping.models import Offer
from shopping.orchestrator import Limits, search_many

NOSLEEP = dict(sleep=lambda s: None, limits=Limits(min_interval_sec=0))


def yoffer(code, name="商品", price=1000, **kw):
    return Offer(mall="yahoo", mall_item_code=code, item_name=name, price=price,
                 item_url=f"https://store.shopping.yahoo.co.jp/s/{code}.html", item_url_status="ok",
                 mall_unconfirmed=["price_options_unchecked"], **kw)


class FakeYahoo(FakeAdapter):
    """Yahoo のモール属性（1 ページ 50 件固定・19 ページまで・rate_limited/server_error で打ち切り）を持つ偽物。"""
    mall = "yahoo"
    label = "Yahoo!ショッピング"
    short_label = "Yahoo"
    page_size = 50
    max_hits = 50
    max_page = 19
    min_interval_sec = 2.2
    stop_kinds = ("rate_limited", "server_error")
    empty_means_end = False
    ceiling_note = "Yahoo は 1000 件目まで"

    def request_notes(self, *, sort="standard", ng_keyword=None):
        return YahooAdapter.request_notes(self, sort=sort, ng_keyword=ng_keyword)


def rk(pages):
    return FakeAdapter(pages)


def pages_of(total, per_page, make, keyword="a", upto=None):
    """total 件のヒットを per_page 件ずつ返す pages 表。"""
    out = {}
    n_pages = -(-total // per_page)
    for p in range(1, (upto or n_pages) + 1):
        n = min(per_page, total - (p - 1) * per_page)
        out[(keyword, p)] = ([make(f"{keyword}{p}-{i}") for i in range(n)], total)
    return out


# ---- default_adapters / select / check_malls ----

def test_default_adapters_by_kind(monkeypatch):
    both = malls.default_adapters(MockAdapter())
    assert list(both) == ["rakuten", "yahoo"] and isinstance(both["yahoo"], MockYahooAdapter)
    assert list(malls.default_adapters(MockAdapter(data_path=__file__))) == ["rakuten"]      # データを差し替えたモックは楽天だけ
    assert list(malls.default_adapters(FakeAdapter({}))) == ["rakuten"]
    real = RakutenAdapter("a", "b")
    assert list(malls.default_adapters(real)) == ["rakuten"]                                  # 鍵が無ければ楽天だけ（従来どおり）
    monkeypatch.setattr(malls, "load_yahoo_credentials", lambda *a, **k: YahooCredentials("CID"))
    got = malls.default_adapters(real)
    assert list(got) == ["rakuten", "yahoo"] and isinstance(got["yahoo"], YahooAdapter) and got["rakuten"] is real
    assert "CID" not in repr(got)


def test_service_make_adapters_follows_make_adapter_and_mock_flag(monkeypatch):
    assert list(service.make_adapters(mock=True)) == ["rakuten", "yahoo"]
    monkeypatch.setattr(service, "make_adapter", lambda *a, **k: FakeAdapter({}))
    assert list(service.make_adapters(local_tool=True)) == ["rakuten"]


def test_select_order_and_validation():
    ads = {"rakuten": FakeAdapter({}), "yahoo": FakeYahoo({})}
    assert list(malls.select(ads, None)) == ["rakuten", "yahoo"]
    assert list(malls.select(ads, ["yahoo", "rakuten"])) == ["rakuten", "yahoo"]        # 楽天が先
    assert list(malls.select(ads, ["yahoo", "yahoo"])) == ["yahoo"]
    assert list(malls.select(ads, "rakuten")) == ["rakuten"]
    for bad in ([], ["amazon"], ["rakuten", "amazon"], [1], 5, [""], ["Yahoo"], ()):
        with pytest.raises(InvalidInput):
            malls.select(ads, bad)
    with pytest.raises(InvalidInput):
        malls.select({"rakuten": FakeAdapter({})}, ["yahoo"])           # 鍵が無く無効なモールは補わない


def test_check_malls_message_does_not_echo_long_input():
    with pytest.raises(InvalidInput) as e:
        check_malls(["x" * 500], ["rakuten"])
    assert len(str(e.value)) < 200


def test_registry_lookups():
    assert malls.label("yahoo") == "Yahoo!ショッピング" and malls.label("rakuten") == "楽天市場"
    assert malls.short_label("rakuten") == "楽天" and malls.label("zzz") == "zzz"
    assert malls.is_item_url("rakuten", "https://item.rakuten.co.jp/s/i/") is True
    assert malls.is_item_url("yahoo", "https://store.shopping.yahoo.co.jp/s/i.html") is True
    assert malls.is_item_url("yahoo", "https://item.rakuten.co.jp/s/i/") is False       # 他のモールの形では ok にしない
    assert malls.is_item_url("zzz", "https://item.rakuten.co.jp/s/i/") is False


# ---- orchestrator: モール別の上限 ----

def run_y(pages, keywords=("a",), **kw):
    ad = FakeYahoo(pages)
    offers, stats = search_many(ad, list(keywords), **{**NOSLEEP, **kw})
    return ad, offers, stats


def test_yahoo_page_size_is_fixed_50_whatever_hits_is():
    ad, offers, stats = run_y(pages_of(120, 50, yoffer), hits=30, max_pages=3)
    assert [kw["hits"] for _, kw in ad.calls] == [50, 50, 50] or [kw["hits"] for _, kw in ad.calls] == [50, 50, 50][:len(ad.calls)]
    assert len(offers) == 120 and stats.per_keyword[0].api_count == 120
    assert stats.per_keyword[0].mall == "yahoo" and stats.per_mall[0].mall == "yahoo"


def test_yahoo_stops_at_page_19_with_truncated_and_no_next_page():
    ad, offers, stats = run_y(pages_of(5000, 50, yoffer, upto=19), max_pages=22, start_page=1)
    s = stats.per_keyword[0]
    assert [kw["page"] for _, kw in ad.calls] == list(range(1, 20))        # 20 ページ目は呼ばない
    assert s.truncated is True and s.next_page is None and s.last_page == 19 and s.remaining == 0
    assert stats.stopped_reason is None and stats.per_mall[0].truncated is True


def test_yahoo_start_page_beyond_ceiling_makes_no_call():
    ad, offers, stats = run_y({}, start_page=30, max_pages=3)
    s = stats.per_keyword[0]
    assert ad.calls == [] and offers == []
    assert s.truncated is True and s.next_page is None and s.error is None and s.pages_fetched == 0


def test_yahoo_range_crossing_the_ceiling_is_clipped():
    ad, offers, stats = run_y(pages_of(5000, 50, yoffer, upto=19), start_page=18, max_pages=5)
    assert [kw["page"] for _, kw in ad.calls] == [18, 19]
    assert stats.per_keyword[0].truncated is True and stats.per_keyword[0].next_page is None


def test_rakuten_ceiling_behaviour_is_unchanged():
    ad = FakeAdapter(pages_of(5000, 30, make_offer, upto=100))
    _, stats = search_many(ad, ["a"], max_pages=100, **NOSLEEP)
    s = stats.per_keyword[0]
    assert len(ad.calls) == 100 and s.truncated is False and s.next_page is None and s.mall == "rakuten"


@pytest.mark.parametrize("kind", ["rate_limited", "server_error"])
def test_yahoo_stop_kinds_abort_the_rest_of_the_mall(kind):
    pages = {("a", 1): AdapterError(kind)}
    ad, _, stats = run_y(pages, keywords=("a", "b"))
    assert len(ad.calls) == 1 and stats.stopped_reason == kind.replace("server_error", "server_error")
    assert stats.per_mall[0].error == kind and stats.per_mall[0].stopped_reason == kind


def test_yahoo_forbidden_continues_with_next_keyword():
    pages = {("a", 1): AdapterError("forbidden"), ("b", 1): ([yoffer("b1")], 1)}
    ad, offers, stats = run_y(pages, keywords=("a", "b"))
    assert len(ad.calls) == 2 and len(offers) == 1 and stats.stopped_reason is None
    assert stats.per_keyword[0].error == "forbidden" and stats.per_mall[0].error is None


def test_empty_page_is_not_the_end_for_yahoo_but_is_for_rakuten():
    pages = {("a", 1): ([], 200), ("a", 2): ([yoffer("a2")], 200)}       # ng_keyword で全部捨てたページ
    ad, offers, _ = run_y(pages, max_pages=2)
    assert len(ad.calls) == 2 and len(offers) == 1
    rpages = {("a", 1): ([], 200), ("a", 2): ([make_offer("a2")], 200)}
    rad = FakeAdapter(rpages)
    search_many(rad, ["a"], max_pages=2, **NOSLEEP)
    assert len(rad.calls) == 1


def test_skipped_hits_are_counted_per_mall():
    from shopping.adapters.yahoo import HitList
    lst = HitList([yoffer("a1")])
    lst.skipped = 4
    ad, _, stats = run_y({("a", 1): (lst, 1)})
    assert stats.per_mall[0].skipped == 4 and stats.per_mall[0].fetched == 1


# ---- search_malls ----

def test_two_malls_run_in_parallel_and_are_merged():
    gate = threading.Barrier(2, timeout=5)

    class Waiting(FakeAdapter):
        def search(self, keyword, **kw):
            gate.wait()                # 2 モールが同時に search に入らないとここで止まる＝並走している
            return super().search(keyword, **kw)

    r = Waiting({("a", 1): ([make_offer("r1"), make_offer("r2")], 2)})
    y = Waiting({("a", 1): ([yoffer("y1")], 1)})
    y.mall, y.page_size, y.max_hits, y.max_page = "yahoo", 50, 50, 19
    offers, stats = malls.search_malls({"rakuten": r, "yahoo": y}, ["a"], **NOSLEEP)
    assert [o.mall for o in offers] == ["rakuten", "rakuten", "yahoo"]
    assert [(s.mall, s.keyword) for s in stats.per_keyword] == [("rakuten", "a"), ("yahoo", "a")]
    assert [(m.mall, m.fetched, m.api_count, m.error, m.truncated) for m in stats.per_mall] == [
        ("rakuten", 2, 2, None, False), ("yahoo", 1, 1, None, False)]
    assert stats.total_received == 3 and stats.unique_offers == 3


def test_same_code_in_two_malls_stays_two_candidates():
    r = FakeAdapter({("a", 1): ([make_offer("same")], 1)})
    y = FakeYahoo({("a", 1): ([yoffer("same")], 1)})
    offers, stats = malls.search_malls({"rakuten": r, "yahoo": y}, ["a"], **NOSLEEP)
    assert len(offers) == 2 and stats.duplicates_removed == 0


def test_one_mall_failing_keeps_the_other():
    r = FakeAdapter({("a", 1): AdapterError("http_403")})
    y = FakeYahoo({("a", 1): ([yoffer("y1")], 1)})
    offers, stats = malls.search_malls({"rakuten": r, "yahoo": y}, ["a"], **NOSLEEP)
    assert [o.mall for o in offers] == ["yahoo"]
    assert stats.per_mall[0].error == "http_403" and stats.per_mall[1].error is None


def test_single_mall_returns_the_same_stats_as_search_many():
    r = FakeAdapter({("a", 1): ([make_offer("r1")], 1)})
    offers, stats = malls.search_malls({"rakuten": r}, ["a"], **NOSLEEP)
    assert len(offers) == 1 and len(stats.per_mall) == 1 and stats.per_mall[0].mall == "rakuten"


def test_invalid_range_raises_before_any_call():
    r, y = FakeAdapter({}), FakeYahoo({})
    with pytest.raises(ValueError):
        malls.search_malls({"rakuten": r, "yahoo": y}, ["a"], max_pages=3, start_page=99, **NOSLEEP)
    assert r.calls == [] and y.calls == []


def test_interval_is_per_mall_and_never_lowered():
    slept = []
    r = FakeAdapter({("a", 1): ([make_offer("r1")], 90), ("a", 2): ([make_offer("r2")], 90)})
    y = FakeYahoo({("a", 1): ([yoffer("y1")], 90), ("a", 2): ([yoffer("y2")], 90)})
    y.max_page = 19
    # 既定の Limits（1.0 秒）: 楽天は 1.0 のまま、Yahoo は 2.2 秒
    malls.search_malls({"rakuten": r}, ["a"], max_pages=2, hits=30, sleep=slept.append)
    assert slept == [1.0]
    slept.clear()
    malls.search_malls({"yahoo": y}, ["a"], max_pages=2, hits=30, sleep=slept.append)
    assert slept == [2.2]
    slept.clear()
    malls.search_malls({"rakuten": r}, ["a"], max_pages=2, hits=30, sleep=slept.append, limits=Limits(min_interval_sec=0.5))
    assert slept == [0.5]                          # 楽天の値は従来どおり（引き上げない）
    slept.clear()
    malls.search_malls({"yahoo": y}, ["a"], max_pages=2, hits=30, sleep=slept.append, limits=Limits(min_interval_sec=0))
    assert slept == [0]                            # 公開面（GuardedAdapter が直列化）は 0 のまま


# ---- service ----

def svc(keywords=("ab",), **kw):
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("limits", Limits(min_interval_sec=0))
    return service.search_products(list(keywords), **kw)


def test_adapter_argument_means_single_mall_dict():
    r = FakeAdapter({("ab", 1): ([make_offer("r1")], 1)})
    out = svc(adapter=r)
    assert out["ok"] and out["malls"] == ["rakuten"] and out["source"] == service.SOURCE
    assert "sources" not in out and "credits" not in out
    r2 = FakeAdapter({("ab", 1): ([make_offer("r1")], 1)})
    out2 = svc(adapters={"rakuten": r2})
    assert out2["offers"] == out["offers"] and out2["notes"] == out["notes"] and out2["stats"]["per_mall"] == out["stats"]["per_mall"]


def test_both_malls_output_fields_and_credits():
    r = FakeAdapter({("ab", 1): ([make_offer("r1")], 1)})
    y = FakeYahoo({("ab", 1): ([yoffer("y1")], 1)})
    out = svc(adapters={"rakuten": r, "yahoo": y})
    assert out["malls"] == ["rakuten", "yahoo"]
    assert out["sources"] == [service.SOURCE, "Yahoo!ショッピング（Yahoo! JAPAN Webサービス）"]
    assert out["source"] == " / ".join(out["sources"])
    assert out["credits"] == ["Supported by Rakuten Developers （https://developers.rakuten.com/）",
                              "Webサービス by Yahoo! JAPAN （https://developer.yahoo.co.jp/sitemap/）"]
    assert [o["mall"] for o in out["offers"]] == ["rakuten", "yahoo"]
    assert [m["mall"] for m in out["stats"]["per_mall"]] == ["rakuten", "yahoo"]
    assert [k["mall"] for k in out["stats"]["per_keyword"]] == ["rakuten", "yahoo"]
    assert {"mall", "fetched", "api_count", "error", "truncated"} <= set(out["stats"]["per_mall"][0])


def test_malls_argument_selects_and_unknown_makes_no_call():
    r = FakeAdapter({("ab", 1): ([make_offer("r1")], 1)})
    y = FakeYahoo({("ab", 1): ([yoffer("y1")], 1)})
    out = svc(adapters={"rakuten": r, "yahoo": y}, malls=["rakuten"])
    assert out["malls"] == ["rakuten"] and y.calls == [] and "credits" not in out
    for bad in (["amazon"], [], ["yahoo", "amazon"]):
        r2, y2 = FakeAdapter({}), FakeYahoo({})
        out = svc(adapters={"rakuten": r2, "yahoo": y2}, malls=bad)
        assert out["ok"] is False and out["error"]["kind"] == "invalid_request"
        assert r2.calls == [] and y2.calls == []
    r3 = FakeAdapter({})
    out = svc(adapters={"rakuten": r3}, malls=["yahoo"])           # 鍵が無く無効なモール。鍵から補わない
    assert out["ok"] is False and out["error"]["kind"] == "invalid_request" and r3.calls == []
    out = svc(adapter=r3, malls=["yahoo"])
    assert out["error"]["kind"] == "invalid_request"


def test_one_mall_failing_note_and_comparison_continues():
    r = FakeAdapter({("ab", 1): ([make_offer("r1", "洗剤 900g", 500)], 1)})
    y = FakeYahoo({("ab", 1): AdapterError("rate_limited")})
    out = svc(adapters={"rakuten": r, "yahoo": y})
    assert out["ok"] and len(out["offers"]) == 1
    assert "Yahoo!ショッピングは rate_limited で取得できなかった（楽天市場だけで比較）" in out["notes"]
    assert any("Yahoo!ショッピングの流量制限" in n for n in out["notes"])
    r2 = FakeAdapter({("ab", 1): AdapterError("http_403")})
    y2 = FakeYahoo({("ab", 1): ([yoffer("y1")], 1)})
    out2 = svc(adapters={"rakuten": r2, "yahoo": y2})
    assert "楽天市場は http_403 で取得できなかった（Yahoo!ショッピングだけで比較）" in out2["notes"]


def test_all_malls_failing_returns_the_first_malls_kind():
    r = FakeAdapter({("ab", 1): AdapterError("http_403")})
    y = FakeYahoo({("ab", 1): AdapterError("rate_limited")})
    out = svc(adapters={"rakuten": r, "yahoo": y})
    assert out["ok"] is False and out["error"]["kind"] == "http_403"
    out = svc(adapters={"yahoo": FakeYahoo({("ab", 1): AdapterError("server_error")})})
    assert out["error"]["kind"] == "server_error"


def test_yahoo_request_notes_and_ceiling_note_and_skipped_note():
    from shopping.adapters.yahoo import HitList
    lst = HitList([yoffer("y1")])
    lst.skipped = 2
    y = FakeYahoo({("ab", p): (lst if p == 1 else [yoffer(f"y{p}")], 5000) for p in range(1, 20)})
    out = svc(adapters={"yahoo": y}, sort="+reviewCount", ng_keyword="ほげ", pages=19)
    notes = out["notes"]
    assert "Yahoo はこの並び順に無いため標準順" in notes and "Yahoo は商品名で除外" in notes
    assert "Yahoo は 1000 件目まで" in notes
    assert "Yahoo!ショッピングの応答のうち、読めない 2 件を捨てた。" in notes
    assert out["stats"]["per_keyword"][0]["next_page"] is None and out["stats"]["per_mall"][0]["truncated"] is True


def test_rakuten_only_notes_keep_the_old_wording():
    r = FakeAdapter({("ab", 1): ([make_offer("r1")], 90), ("ab", 2): AdapterError("http_429")})
    out = svc(adapter=r, pages=2, paging_notes=True)
    assert "出典: " + service.SOURCE in out["notes"]
    assert "楽天APIの流量制限(429)で残りの検索を打ち切った。時間をおいて再実行すること。" in out["notes"]
    assert not any("取得できなかった" in n for n in out["notes"])      # 1 モールだけの検索に「〇〇だけで比較」の注記は出さない
    r2 = FakeAdapter({("ab", 1): AdapterError("http_429")})
    out2 = svc(adapter=r2)
    assert out2["ok"] is False and out2["error"]["kind"] == "http_429"


# ---- Gate / GuardedAdapter ----

def test_gate_holds_per_mall_guards_and_validates_malls():
    r, y = FakeAdapter({}), FakeYahoo({})
    gate = Gate(r, RateLimiter(limit=1000), adapters={"yahoo": y})
    assert list(gate.adapters) == ["rakuten", "yahoo"] and gate.adapter is gate.adapters["rakuten"]
    assert gate.adapters["rakuten"] is not gate.adapters["yahoo"]
    assert all(isinstance(a, GuardedAdapter) for a in gate.adapters.values())
    gate.admit("1.1.1.1", keywords=["洗剤"], malls=["yahoo"])
    for bad in (["amazon"], [], ["rakuten", "x"]):
        with pytest.raises(InvalidInput):
            gate.admit("1.1.1.1", keywords=["洗剤"], malls=bad)
    only = Gate(r, RateLimiter(limit=1000))
    assert list(only.adapters) == ["rakuten"]
    with pytest.raises(InvalidInput):
        only.admit("1.1.1.1", keywords=["洗剤"], malls=["yahoo"])
    g2 = Gate(adapters={"yahoo": y, "rakuten": r}, limiter=RateLimiter(limit=1000))
    assert g2.adapter.mall == "rakuten"
    with pytest.raises(ValueError):
        Gate()


def test_rejected_malls_do_not_consume_the_rate_limit():
    limiter = RateLimiter(limit=1)
    gate = Gate(FakeAdapter({}), limiter)
    with pytest.raises(InvalidInput):
        gate.admit("2.2.2.2", keywords=["洗剤"], malls=["yahoo"])
    gate.admit("2.2.2.2", keywords=["洗剤"])          # 弾いた入力は回数を消費しない


def test_guarded_adapter_relays_mall_attributes_and_interval():
    g = GuardedAdapter(FakeYahoo({}))
    assert (g.mall, g.label, g.max_page, g.page_size, g.stop_kinds) == ("yahoo", "Yahoo!ショッピング", 19, 50,
                                                                         ("rate_limited", "server_error"))
    assert g._min_interval == 2.2 and g.request_notes(sort="x") == ["Yahoo はこの並び順に無いため標準順"]
    plain = GuardedAdapter(FakeAdapter({}))
    assert plain._min_interval == 1.0 and plain.max_page == 100 and plain.stop_kinds == ("http_429",)
    assert GuardedAdapter(FakeAdapter({}), min_interval=0.3)._min_interval == 0.3
    assert GuardedAdapter(MockAdapter()).is_mock is True and GuardedAdapter(MockYahooAdapter()).is_mock is True
    assert GuardedAdapter(RakutenAdapter("a", "b")).is_mock is False


def test_guarded_cache_keeps_skipped_count():
    from shopping.adapters.yahoo import HitList
    lst = HitList([yoffer("y1")])
    lst.skipped = 3
    g = GuardedAdapter(FakeYahoo({("a", 1): (lst, 1)}), clock=lambda: 0.0, sleep=lambda s: None)
    first, _ = g.search("a", page=1)
    second, _ = g.search("a", page=1)           # キャッシュから
    assert getattr(first, "skipped", 0) == 3 and getattr(second, "skipped", 0) == 3 and g.api_calls == 1


# ---- モック ----

def test_mock_yahoo_adapter_behaves_like_the_real_one():
    m = MockYahooAdapter()
    offers, count = m.search("カイロ")
    assert count == len(offers) == 4         # 訳あり（中古）も在庫あり
    assert all(o.mall == "yahoo" and o.item_url_status == "ok" and "price_options_unchecked" in o.mall_unconfirmed for o in offers)
    used = [o for o in m.search("カイロ 訳あり")[0]]
    assert used and used[0].condition == "used" and "condition_not_new" in used[0].mall_unconfirmed
    assert m.search("洗濯洗剤")[0] == []      # 既存のモックの商品系統とは重ならない
    asc = [o.price for o in m.search("カイロ", sort="+itemPrice")[0]]
    assert asc == sorted(asc)
    assert m.search("カイロ", min_price=1000, max_price=2000)[0][0].price == 1380
    assert [o.item_name for o in m.search("カイロ", ng_keyword="120枚")[0]] and \
        all("120枚" not in o.item_name for o in m.search("カイロ", ng_keyword="120枚")[0])
    for bad in (dict(page=0), dict(page=20), dict(hits=0), dict(hits=51)):
        with pytest.raises(AdapterError):
            m.search("カイロ", **bad)


def test_mock_default_cli_style_run_includes_both_malls():
    out = service.compare_offers(["貼るカイロ"], adapters=service.make_adapters(mock=True))
    assert out["ok"] and out["mock"] is True and out["malls"] == ["rakuten", "yahoo"]
    assert {o["mall"] for g in out["comparison"]["groups"] for o in g["offers"]} == {"rakuten", "yahoo"}
