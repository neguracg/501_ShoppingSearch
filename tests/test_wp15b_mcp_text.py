# @owns WP15 段B 呼び出し側の AI への指示（購入単位・項目単位の補完）が INSTRUCTIONS だけに足されることの自作確認。独立試験（ブラインド）の代わりではない
"""段B の指示は _ORDER_GUIDE（INSTRUCTIONS）にだけ足し、compare_offers の説明（2000 字ガード）は増やさない（SPEC §10）。"""
import asyncio

from mcp import Client

from shopping import mcp_server
from shopping.mcp_server import INSTRUCTIONS, _ORDER_GUIDE, build_server

PHRASES = ["basis=袋・desired=30 のままでよい", "quantity.packs", "counter_assumed", "pack_content_differs",
           "本への換算を利用者・呼び出し側に求めない", "title+caption", "measure_from_caption"]


def test_stage_b_guidance_is_in_instructions_and_the_old_conversion_advice_is_gone():
    for ph in PHRASES:
        assert ph in _ORDER_GUIDE and ph in INSTRUCTIONS, ph
    assert "basis=本・desired_quantity=540" not in INSTRUCTIONS


def test_compare_offers_description_is_not_grown_for_stage_b():
    async def go():
        async with Client(build_server()) as c:
            return {t.name: t for t in (await c.list_tools()).tools}
    d = asyncio.run(asyncio.wait_for(go(), timeout=30))["compare_offers"].description
    assert len(d) <= 2000 and mcp_server._ORDER_POINTER in d
    assert not any(p in d for p in ("counter_assumed", "pack_content_differs", "title+caption"))
