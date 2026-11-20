# @owns WP14 W6 呼び出し側の AI への説明（INSTRUCTIONS・ツール説明）の自作確認。独立試験（ブラインド）の代わりではない
"""希望量の範囲・回答の3点・送料無料ラインを仮定しない・数え方を揃える・仕様の照合・検索語の作り方を、文は1か所（mcp_server の
_ORDER_GUIDE / _SEARCH_GUIDE）で持ち、INSTRUCTIONS と compare_offers（検索語の指示は search_products も）が使う。"""
import asyncio
from pathlib import Path

from mcp import Client

from shopping import mcp_server
from shopping.mcp_server import INSTRUCTIONS, _ORDER_GUIDE, _SEARCH_GUIDE, build_server

PHRASES = ["desired_quantity=下限・desired_quantity_max=上限", "cheapest_order", "to_check", "送料無料ライン（3,980円など）を仮定しない",
           "price_varies", "商品ページで確認", "basis=本・desired_quantity=540", "数え方の違う候補を同じ単価順に並べない",
           "見出し付きの仕様", "同一品と分けて示す", "asuraku_flag"]


def tools():
    async def go():
        async with Client(build_server()) as c:
            return {t.name: t for t in (await c.list_tools()).tools}
    return asyncio.run(asyncio.wait_for(go(), timeout=30))


def test_order_guide_phrases_reach_instructions_and_the_pointer_reaches_compare_offers():
    t = tools()
    for ph in PHRASES:
        assert ph in _ORDER_GUIDE and ph in INSTRUCTIONS, ph
    d = t["compare_offers"].description
    assert mcp_server._ORDER_POINTER in d
    for ph in ("cheapest_order", "to_check", "price_varies", "送料無料ラインを仮定しない", "INSTRUCTIONS"):
        assert ph in d, ph
    assert len(d) <= 2000


def test_search_guide_reaches_search_products_and_instructions():
    t = tools()
    assert "枚数を外した語で sort=standard と sort=+itemPrice の2回" in _SEARCH_GUIDE
    for text in (INSTRUCTIONS, t["search_products"].description):     # compare_offers は説明が 2000 字を超えるので INSTRUCTIONS に任せる
        assert _SEARCH_GUIDE in text


def test_each_sentence_is_written_once_in_the_source():
    src = Path(mcp_server.__file__).read_text(encoding="utf-8")
    for ph in ("送料無料ライン（3,980円など）を仮定しない", "枚数を外した語で sort=standard"):
        assert src.count(ph) == 1, ph


def test_compare_offers_has_the_upper_bound_parameter_and_counter_basis_text():
    t = tools()["compare_offers"]
    assert "desired_quantity_max" in t.input_schema["properties"]
    assert "数え語（本・袋・枚など）も指定でき" in t.description
    assert "order_plans" in t.description and "count_unit" in t.description
