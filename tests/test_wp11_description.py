# @owns WP11-1 ツール説明（search_products・compare_offers）に入れる注意の文言の自作確認。独立試験の代わりではない
"""WP11-1: AI 向けのツール説明に「商品の種類・仕様は判定しない」「confidence が high でない候補と
unit_price_outlier の候補は最安・おすすめにしない」「送料不明を『送料込み最安』と呼ばない」を入れる。

説明の文は mcp_server.py に1か所（_NOT_JUDGED とツール説明）。stdio と公開は同じ関数で作るので両方で確かめる。
"""
import asyncio

import pytest
from mcp import Client

from fakes import FakeAdapter
from shopping import mcp_server
from shopping.guard import Gate, GuardedAdapter, RateLimiter
from shopping.mcp_server import build_server

SPEC_WORDS = ("本体", "交換部品", "付属品", "純正", "互換", "型番", "世代違い", "単3", "単4", "炭酸", "非炭酸", "詰め替え")


def _descs(server):
    async def go():
        async with Client(server) as c:
            return await c.list_tools()
    tools = asyncio.run(asyncio.wait_for(go(), timeout=30)).tools
    return {t.name: t.description for t in tools}


def _public():
    gate = Gate(GuardedAdapter(FakeAdapter({}), clock=lambda: 0.0, sleep=lambda s: None),
                RateLimiter(limit=1000, clock=lambda: 0.0))
    return build_server(public=True, gate=gate)


@pytest.fixture(params=["stdio", "public"])
def descs(request):
    return _descs(build_server() if request.param == "stdio" else _public())


@pytest.mark.parametrize("name", ["search_products", "compare_offers"])
def test_both_tools_say_the_tool_does_not_judge_kind_or_spec(descs, name):
    d = descs[name]
    assert "判定しない" in d
    for w in SPEC_WORDS:
        assert w in d, w
    assert "include_terms" in d and "exclude_terms" in d and "ng_keyword" in d
    assert "最終回答の前に商品名で照合" in d


@pytest.mark.parametrize("name", ["search_products", "compare_offers"])
def test_both_tools_say_not_high_confidence_is_not_a_pick(descs, name):
    d = descs[name]
    assert "confidence" in d and "high でない" in d
    assert "おすすめ" in d and "商品ページで確認" in d


def test_compare_says_outlier_is_not_a_pick_and_shipping_unknown_is_not_cheapest_with_shipping(descs):
    d = descs["compare_offers"]
    assert "unit_price_outlier が true の候補" in d and "最安・おすすめとして示さない" in d
    assert "送料込み最安" in d and "呼ばない" in d
    assert "1/10" in d                               # WP10 の既存の説明は残っている


def test_the_shared_sentence_lives_in_one_place_and_appears_once_per_tool(descs):
    assert mcp_server._NOT_JUDGED.count("判定しない") == 1
    for name in ("search_products", "compare_offers"):
        assert descs[name].count(mcp_server._NOT_JUDGED) == 1
    if "find_regular_item" in descs:                 # 定番品ツール（stdio のみ）には入れない
        assert mcp_server._NOT_JUDGED not in descs["find_regular_item"]


def test_descriptions_stay_within_a_reasonable_length(descs):
    # 既存の説明は約 1.25〜1.4 千字。追記後も 2 千字以内に収める（長すぎる説明は AI に読まれない）
    for name in ("search_products", "compare_offers"):
        assert len(descs[name]) <= 2000, (name, len(descs[name]))
