# @owns WP15 段A（U1 未確定の単価は仮の値・U4 注文額の種類と公開MCPの定義）の自作確認。独立試験（ブラインド）の代わりではない
"""未確定の単価（説明欄から補った数量・題名と説明欄の食い違い・選択肢で価格が変わる・外れ値）は、出力 dict で
unit_price=null・provisional_unit_price=計算値。送料別・不明だけは単価をそのまま出す。注文案は payment_total・order_total_kind を持つ。
SPEC §8 Q21〜Q24・AC17・AC18。内部の Offer.unit_price・並び・最安の選び方は変えない。"""
import asyncio
import json

import pytest
from mcp import Client

import cli
from fakes import FakeAdapter, make_offer
from shopping import service, web_view
from shopping.guard import Gate, GuardedAdapter, RateLimiter
from shopping.mcp_server import build_server
from shopping.models import QuantityInfo
from shopping.pricing import compare, unit_price_reasons, unit_price_text
from shopping.quantity import parse_quantity


def off(code, name, price, ship="included", lo=None, hi=None, mutate=None):
    o = make_offer(code, name=name, price=price, shipping_status=ship)
    o.quantity = parse_quantity(name)
    o.price_min, o.price_max = lo, hi
    if mutate:
        mutate(o)
    return o


def conflict(o):
    o.quantity.caption_conflict = True
    o.quantity.caption_evidence = "入数：30枚"


def from_caption(o):
    o.quantity = QuantityInfo(count_total=30, count_unit="枚", confidence="high", source="caption",
                              caption_evidence="入数：30枚")


def kairo():
    return [off("ok60", "カイロ 貼る 60枚", 1500),
            off("varies", "カイロ 貼る 60枚 まとめ買い", 1500, lo=1500, hi=1720),
            off("conf", "カイロ 貼る 90枚 3箱", 1000, mutate=conflict),
            off("cap", "カイロ 貼る 送料込み", 800, mutate=from_caption),
            off("sep", "カイロ 貼る 60枚 送料別の店", 1300, ship="separate"),
            off("none", "カイロ 貼るタイプ", 500)]


def walk_offers(d):
    """compare_offers の dict から候補 dict を全部集める。"""
    c = d["comparison"]
    out = list(c["unknown_offers"])
    for g in c["groups"]:
        out += g["offers"] + ([g["cheapest_unit_price"]] if g["cheapest_unit_price"] else [])
    out += [c[k] for k in ("cheapest_price", "cheapest_unit_price", "cheapest_total", "cheapest_for_quantity") if c[k]]
    return out


def walk_plans(c):
    plans = list(c["order_plans"]) + list(c["to_check"]) + ([c["cheapest_order"]] if c["cheapest_order"] else [])
    for g in c["groups"]:
        plans += g["order_plans"] + g["to_check"] + ([g["cheapest_order"]] if g["cheapest_order"] else [])
    return plans


def by_code(items, code):
    return next(i for i in items if i["item_code"] == code)


def compared(code, offers=None):
    offers = offers or kairo()
    compare(offers, basis="個")
    return next(o for o in offers if o.mall_item_code == code)


# --- U1: 候補の dict -----------------------------------------------------------------------------

def test_unit_price_reasons_drops_only_shipping():
    assert unit_price_reasons(["shipping_separate", "price_varies", "shipping_unknown", "caption_conflict"]) == ["price_varies", "caption_conflict"]
    assert unit_price_reasons(["shipping_separate"]) == []


def test_each_unconfirmed_reason_makes_the_offer_price_provisional():
    d = service._comparison_to_dict(compare(kairo(), basis="個"))
    flat = {o["item_code"]: o for g in d["groups"] for o in g["offers"]}
    assert flat["ok60"]["unit_price"] == 25 and flat["ok60"]["provisional_unit_price"] is None
    assert flat["ok60"]["unit_price_status"] == "confirmed" and flat["ok60"]["unit_price_unconfirmed_reasons"] == []
    v = flat["varies"]                                   # 1,500 / 60 = 25.0（unidy:10972223 の型）
    assert v["unit_price"] is None and v["provisional_unit_price"] == 25.0
    assert v["unit_price_status"] == "unconfirmed" and v["unit_price_unconfirmed_reasons"] == ["price_varies"]
    assert flat["conf"]["unit_price"] is None and flat["conf"]["provisional_unit_price"] is not None
    assert flat["conf"]["unit_price_unconfirmed_reasons"] == ["caption_conflict"]
    assert flat["cap"]["unit_price"] is None and flat["cap"]["unit_price_unconfirmed_reasons"] == ["quantity_from_caption"]
    # 送料別だけ: 単価はそのまま（送料は単価の誤りではない）
    assert flat["sep"]["unit_price"] is not None and flat["sep"]["unit_price_status"] == "confirmed"
    # 単価なし
    u = by_code(d["unknown_offers"], "none")
    assert (u["unit_price"], u["provisional_unit_price"], u["unit_price_status"], u["unit_price_unconfirmed_reasons"]) == (None, None, "unknown", [])


def test_internal_values_are_unchanged():
    offers = kairo()
    compare(offers, basis="個")
    internal = {o.mall_item_code: o for o in offers}
    assert internal["varies"].unit_price == pytest.approx(25.0)      # 内部の計算値は変えない（並び・外れ値の判定に使う）
    assert internal["conf"].quantity.confidence == "high"


def test_outlier_offer_is_provisional():
    members = [off(f"n{i}", f"カイロ 貼る 60枚 {i}", 1500 + i) for i in range(4)]
    members.append(off("cheap", "カイロ 貼る 60枚 激安", 100))
    d = service._comparison_to_dict(compare(members, basis="個"))
    cheap = by_code(d["groups"][0]["offers"], "cheap")
    assert cheap["unit_price_outlier"] and cheap["unit_price"] is None
    assert cheap["unit_price_unconfirmed_reasons"] == ["unit_price_outlier"]


def test_quantity_confidence_is_conflict_only_for_caption_conflict_and_title_confidence_keeps_the_title():
    d = service._comparison_to_dict(compare(kairo(), basis="個"))
    offers = [x for g in d["groups"] for x in g["offers"]]
    c = by_code(offers, "conf")["quantity"]
    assert c["confidence"] == "conflict" and c["title_confidence"] == "high" and c["caption_conflict"] is True
    for code in ("ok60", "varies", "cap", "sep"):
        q = by_code(offers, code)["quantity"]
        assert q["confidence"] == q["title_confidence"] == "high"
    q = by_code(d["unknown_offers"], "none")["quantity"]
    assert q["confidence"] == q["title_confidence"] == "none"


def test_sort_and_cheapest_choice_still_use_the_internal_value():
    d = service._comparison_to_dict(compare(kairo(), basis="個"))
    vals = [(o["unit_price"] if o["unit_price"] is not None else o["provisional_unit_price"]) for o in d["groups"][0]["offers"]]
    assert vals == sorted(vals)                                  # 並びは未確定の値も含めて内部の計算値の順
    cu = d["cheapest_unit_price"]
    assert cu["unit_price_status"] == "confirmed" and cu["unit_price"] is not None


# --- U1: 注文案・AC17 の走査 ----------------------------------------------------------------------

def test_order_plans_follow_the_same_split_and_total_kind():
    d = service._comparison_to_dict(compare(kairo(), basis="個", desired_quantity=50, desired_quantity_max=100))
    plans = walk_plans(d)
    assert plans
    for p in plans:
        assert {"payment_total", "order_total_kind", "provisional_order_unit_price", "unit_price_status",
                "unit_price_unconfirmed_reasons", "order_unit_price"} <= set(p)
        if p["unit_price_unconfirmed_reasons"]:
            assert p["order_unit_price"] is None and p["provisional_order_unit_price"] is not None
            assert p["unit_price_status"] == "unconfirmed"
        else:
            assert p["order_unit_price"] is not None and p["provisional_order_unit_price"] is None
            assert p["unit_price_status"] == "confirmed"
        if p["confirmed"]:                                            # 確認済みの案だけ支払総額（レビュー B1）
            assert p["order_total_kind"] == "payment_total" and p["payment_total"] == p["order_total"]
        elif p["shipping_status"] == "included":
            assert p["order_total_kind"] == "unconfirmed_total" and p["payment_total"] is None
        else:
            assert p["order_total_kind"] == "item_subtotal" and p["payment_total"] is None
    v = by_code(d["order_plans"], "varies")
    assert v["order_unit_price"] is None and v["provisional_order_unit_price"] == 25.0
    assert v["order_total_kind"] == "unconfirmed_total" and v["payment_total"] is None and v["order_total"] == 1500   # 価格幅の最小の価格×n を支払総額にしない
    s = by_code(d["order_plans"], "sep")                          # 送料別だけの案: 単価はそのまま・注文額は商品小計
    assert s["order_unit_price"] is not None and s["order_total_kind"] == "item_subtotal"
    assert s["unconfirmed_reasons"] == ["shipping_separate"] and s["unit_price_unconfirmed_reasons"] == []
    if d["cheapest_order"]:
        assert d["cheapest_order"]["order_unit_price"] is not None and d["cheapest_order"]["order_total_kind"] == "payment_total"


def scan_unconfirmed_with_plain_price(obj, path="$"):
    """AC17: unit_price_unconfirmed_reasons が空でない dict に、素の unit_price / order_unit_price の数値があれば列挙する。"""
    bad = []
    if isinstance(obj, dict):
        if obj.get("unit_price_unconfirmed_reasons"):
            for k in ("unit_price", "order_unit_price"):
                if isinstance(obj.get(k), (int, float)):
                    bad.append((path, k))
        for k, v in obj.items():
            bad += scan_unconfirmed_with_plain_price(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad += scan_unconfirmed_with_plain_price(v, f"{path}[{i}]")
    return bad


def test_ac17_scan_over_mock_outputs_finds_no_plain_unconfirmed_price():
    adapter = service.make_adapter(mock=True)
    outs = [service.compare_offers(["洗濯洗剤 詰め替え"], desired_quantity=5000, desired_quantity_max=100000, basis="g", adapter=adapter),
            service.compare_offers(["貼るカイロ"], basis="個", desired_quantity=50, desired_quantity_max=100, adapter=adapter),
            service.compare_offers(["洗濯洗剤 詰め替え"], adapter=adapter),
            service.search_products(["洗濯洗剤 詰め替え"], adapter=adapter)]
    for o in outs:
        assert o["ok"] and scan_unconfirmed_with_plain_price(o) == []


def test_scan_detects_a_plain_value():
    assert scan_unconfirmed_with_plain_price({"a": [{"unit_price": 5, "unit_price_unconfirmed_reasons": ["price_varies"]}]})


def test_search_products_candidates_are_unknown_not_plain_price():
    r = service.search_products(["洗濯洗剤 詰め替え"], adapter=service.make_adapter(mock=True))
    for o in r["offers"]:
        assert o["unit_price"] is None and o["provisional_unit_price"] is None and o["unit_price_status"] == "unknown"
        assert o["quantity"]["title_confidence"] == o["quantity"]["confidence"]


def test_regular_item_goes_through_the_same_split(tmp_path):
    reg = tmp_path / "regulars.json"
    reg.write_text(json.dumps({"regulars": [{"id": "w", "name": "洗剤", "keywords": ["洗濯洗剤 詰め替え"], "basis": "g",
                                              "include_terms": [], "exclude_terms": []}]}), encoding="utf-8")
    r = service.find_regular_item("w", regulars_path=str(reg), adapter=service.make_adapter(mock=True))
    assert r["ok"] and scan_unconfirmed_with_plain_price(r) == []
    assert all("unit_price_status" in o for o in walk_offers(r))


# --- 表示（Web・CLI） -----------------------------------------------------------------------------

def test_unit_price_text_marks_provisional_with_reason():
    offers = kairo()
    compare(offers, basis="個")
    by = {o.mall_item_code: service.offer_to_dict(o) for o in offers}
    assert unit_price_text(by["varies"]) == "仮 1個あたり 25.00円（選択肢で価格が変わる）"
    assert unit_price_text(by["ok60"]) == "1個あたり 25.00円"
    assert unit_price_text(by["none"]) is None


def test_unit_price_text_has_no_leading_space_without_label():
    assert unit_price_text({"unit_price": 5.0}) == "5.00円"
    assert unit_price_text({"unit_price": None, "provisional_unit_price": 5.0, "unit_price_unconfirmed_reasons": ["price_varies"]}) == "仮 5.00円（選択肢で価格が変わる）"
    assert unit_price_text({"unit_price": None, "provisional_unit_price": None}) is None


def test_web_and_cli_show_provisional_and_keep_conflict_quantity_visible():
    offers = kairo()
    compare(offers, basis="個")
    by = {o.mall_item_code: service.offer_to_dict(o) for o in offers}
    for text in (web_view._qty(by["conf"]), cli._qty(by["conf"])):
        assert "仮" in text and "食い違い" in text and "数量要確認" not in text
    assert "仮" in web_view._qty(by["varies"]) and "選択肢で価格が変わる" in web_view._qty(by["varies"])
    assert "仮" in cli._qty(by["varies"])
    assert "仮" not in cli._qty(by["ok60"]) and "仮" not in web_view._qty(by["ok60"])


def test_cli_plan_line_says_item_subtotal_for_separate_shipping():
    d = service._comparison_to_dict(compare(kairo(), basis="個", desired_quantity=50, desired_quantity_max=100))
    sep = cli._plan_line(by_code(d["order_plans"], "sep"))
    assert "商品小計（送料別・不明）" in sep and "注文額" not in sep
    var = cli._plan_line(by_code(d["order_plans"], "varies"))
    assert "注文額（仮） 1,500円" in var and "単価 仮" in var
    ok = cli._plan_line(by_code(d["order_plans"], "ok60"))
    assert "注文額 1,500円" in ok and "（仮）" not in ok and "商品小計" not in ok


def kairo_adapter():
    """貼るカイロの録画に近い構成（題名・価格・選択肢の幅は WP14 の実測の型）。240枚品は希望量の上限 100 を超える。"""
    plain = [off("ok60", "カイロ 貼る 60枚", 1500), off("varies", "カイロ 貼る 60枚 まとめ買い", 1500, lo=1500, hi=1720),
             off("sep", "カイロ 貼る 60枚 送料別の店", 1300, ship="separate"), off("big240", "カイロ 貼る 240枚", 3000)]
    for o in plain:
        o.quantity = None                              # service が題名から読む
    return FakeAdapter({("貼るカイロ", 1): (plain, len(plain))})


def test_web_page_marks_provisional_unit_price():
    from fastapi.testclient import TestClient
    from shopping.web import create_app
    plain = [off("ok60", "カイロ 貼る 60枚", 1500), off("varies", "カイロ 貼る 60枚 まとめ買い", 1500, lo=1500, hi=1720)]
    for o in plain:
        o.quantity = None
    gate = Gate(GuardedAdapter(FakeAdapter({("カイロ", 1): (plain, 2)}), clock=lambda: 0.0, sleep=lambda s: None),
                RateLimiter(limit=1000, clock=lambda: 0.0))
    html = TestClient(create_app("", gate)).get("/compare?q=カイロ&basis=個").text
    assert "仮 1個あたり 25.00円（選択肢で価格が変わる）" in html
    assert "／1個あたり 25.00円" in html and html.count("仮 1個あたり") >= 1


def test_cli_prints_item_subtotal_and_provisional(capsys, monkeypatch):
    monkeypatch.setattr(service, "make_adapter", lambda *a, **k: kairo_adapter())
    assert cli.run(["compare", "貼るカイロ", "--basis", "個", "--desired-quantity", "50", "--desired-quantity-max", "100"]) == 0
    out = capsys.readouterr().out
    assert "商品小計（送料別・不明）" in out
    assert "仮 1個あたり 25.00円（選択肢で価格が変わる）" in out
    assert "240枚" not in out.split("希望量")[1]      # 範囲外の案は注文案に出ない


# --- U4: 公開MCP ----------------------------------------------------------------------------------

def _tools():
    async def go():
        async with Client(build_server()) as c:
            return {t.name: t for t in (await c.list_tools()).tools}
    return asyncio.run(asyncio.wait_for(go(), timeout=30))


def test_compare_offers_definition_has_range_param_and_text_within_2000():
    t = _tools()
    c = t["compare_offers"]
    assert "desired_quantity_max" in c.input_schema["properties"]
    assert "商品名（足りない時は説明欄の見出し付きの値）から読んだ数量" in c.description
    assert "provisional_unit_price" in c.description and "item_subtotal" in c.description
    assert len(c.description) <= 2000 and len(t["search_products"].description) <= 2000
    assert "商品名（足りない時は説明欄の見出し付きの値）から読んだ数量" in t["search_products"].description


def test_instructions_carry_the_provisional_and_item_subtotal_sentences():
    from shopping.mcp_server import INSTRUCTIONS, _ORDER_GUIDE
    for ph in ("provisional_unit_price", "unit_price_unconfirmed_reasons", "item_subtotal", "unconfirmed_total", "payment_total",
               "groups・unknown_offers は件数で切らず全件返す"):
        assert ph in _ORDER_GUIDE and ph in INSTRUCTIONS


def test_range_call_through_public_mcp_returns_only_orders_within_range():
    gate = Gate(GuardedAdapter(kairo_adapter(), clock=lambda: 0.0, sleep=lambda s: None), RateLimiter(limit=1000, clock=lambda: 0.0))

    async def go():
        async with Client(build_server(public=True, gate=gate)) as c:
            r = await c.call_tool("compare_offers", {"keywords": ["貼るカイロ"], "basis": "個", "desired_quantity": 50,
                                                      "desired_quantity_max": 100})
            return r.structured_content or {}
    d = asyncio.run(asyncio.wait_for(go(), timeout=30))
    assert d["ok"] and d["desired_quantity_max"] == 100
    plans = walk_plans(d["comparison"])
    assert plans and {p["item_code"] for p in plans} == {"ok60", "varies", "sep"}      # 240枚品（big240）は入らない
    assert all(50 <= p["order_quantity"] <= 100 for p in plans)
    assert d["comparison"]["cheapest_order"]["item_code"] == "ok60"
    assert scan_unconfirmed_with_plain_price(d) == []
    by = {p["item_code"]: p for p in d["comparison"]["order_plans"]}
    assert by["varies"]["order_unit_price"] is None and by["varies"]["provisional_order_unit_price"] == 25.0
    assert by["sep"]["order_total_kind"] == "item_subtotal" and by["sep"]["payment_total"] is None
    assert by["varies"]["order_total_kind"] == "unconfirmed_total" and by["varies"]["payment_total"] is None
    assert by["ok60"]["order_total_kind"] == "payment_total" and by["ok60"]["payment_total"] == 1500
