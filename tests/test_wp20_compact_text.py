# @owns WP20 MCP の結果の content[0].text を空白なしの compact JSON にした形（structuredContent と同じ内容・同じキー順）の自作確認。独立試験（ブラインド）の代わりではない
"""WP20: SDK（mcp 2.3.0）は dict の結果を text にする時 indent=2 で整形する（空白だけで約 45% 大きい）。アプリ側で CallToolResult を返し、
text を compact JSON（日本語はそのまま UTF-8）にする。structuredContent は dict のまま。内容・キー順は text と同じ（情報は1バイトも減らない）。"""
import asyncio
import json

import pytest
from mcp import Client

from fakes import FakeAdapter, make_offer
from shopping.guard import Gate, GuardedAdapter, RateLimiter
from shopping.mcp_server import as_tool_result, build_server


def gate():
    offers = [make_offer("a", "貼るカイロ 60枚 A店", 1800, shipping_status="included"),
              make_offer("b", "貼るカイロ 60枚 B店", 1500, shipping_status="included", price_min=1500, price_max=1720)]
    ad = FakeAdapter({("貼るカイロ", 1): (offers, 2)})
    return Gate(GuardedAdapter(ad, clock=lambda: 0.0, sleep=lambda s: None), RateLimiter(limit=1000, clock=lambda: 0.0))


def call(name, args, **kw):
    async def go():
        async with Client(build_server(public=True, gate=gate())) as c:
            return await c.call_tool(name, args)
    return asyncio.run(asyncio.wait_for(go(), timeout=30))


def keys_in_order(x, path=""):
    """全ての dict のキー順（パス付き）を平らに並べる。順序まで比べるため。"""
    out = []
    if isinstance(x, dict):
        for k, v in x.items():
            out.append(f"{path}/{k}")
            out += keys_in_order(v, f"{path}/{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            out += keys_in_order(v, f"{path}[{i}]")
    return out


@pytest.mark.parametrize("name,args", [
    ("compare_offers", {"keywords": ["貼るカイロ"], "basis": "枚", "desired_quantity": 60, "desired_quantity_max": 100}),
    ("compare_offers", {"keywords": ["貼るカイロ"]}),
    ("search_products", {"keywords": ["貼るカイロ"]}),
])
def test_text_is_compact_json_with_the_same_content_and_key_order_as_structured_content(name, args):
    r = call(name, args)
    assert not r.is_error and len(r.content) == 1 and r.content[0].type == "text"
    text, sc = r.content[0].text, r.structured_content
    assert sc["ok"] is True
    assert "\n" not in text and text.startswith('{"ok":true,"')                         # 整形の改行・字下げが無い
    assert text == json.dumps(sc, ensure_ascii=False, separators=(",", ":"))          # compact・日本語は UTF-8 のまま・同じキー順
    assert json.loads(text) == sc
    assert keys_in_order(json.loads(text)) == keys_in_order(sc)                         # キー順（入れ子の中まで）が同じ
    assert "\\u" not in text and "貼るカイロ" in text                                    # 日本語を \\uXXXX にしていない


def test_text_is_smaller_than_the_indented_form_by_whitespace_only():
    r = call("compare_offers", {"keywords": ["貼るカイロ"], "basis": "枚", "desired_quantity": 60})
    sc = r.structured_content
    indented = json.dumps(sc, ensure_ascii=False, indent=2)
    assert len(r.content[0].text.encode()) < len(indented.encode()) * 0.85
    assert json.loads(indented) == json.loads(r.content[0].text)                        # 空白の違いだけ（内容は同じ）


def test_error_result_text_is_compact_too_and_not_flagged_as_error():
    r = call("compare_offers", {"keywords": []})
    assert r.structured_content["ok"] is False and r.content[0].text == json.dumps(r.structured_content, ensure_ascii=False, separators=(",", ":"))


def test_as_tool_result_keeps_structured_dict_and_falls_back_to_str_for_odd_values():
    out = as_tool_result({"b": 1, "a": {"z": [1, 2], "y": "日本語"}})
    assert out.structured_content == {"b": 1, "a": {"z": [1, 2], "y": "日本語"}}
    assert out.content[0].text == '{"b":1,"a":{"z":[1,2],"y":"日本語"}}'


def test_output_schema_is_unchanged_for_the_tools():
    async def go():
        async with Client(build_server(public=True, gate=gate())) as c:
            return {t.name: t for t in (await c.list_tools()).tools}
    tools = asyncio.run(asyncio.wait_for(go(), timeout=30))
    for t in tools.values():
        assert t.output_schema is not None and t.output_schema.get("type") == "object"
