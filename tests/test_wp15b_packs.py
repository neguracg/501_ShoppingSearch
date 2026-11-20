# @owns WP15 段B 題名の包装の数 quantity.packs（pack_forms.py）の自作確認。独立試験（ブラインド）の代わりではない
"""包装の数の形 F1〜F3（SPEC §7「包装の数」）。総数・confidence・既存のキーは変えない（題名コーパス 480 件は test_title_corpus）。
題名は 2026-11-21 の実 API（文化たきつけ・カイロ・トイレットペーパー）。"""
import pytest

from fakes import make_offer
from shopping import service
from shopping.caption_quantity import read_offer_quantity
from shopping.quantity import parse_quantity


def pk(unit, count, per_pack, per_unit):
    return [{"unit": unit, "count": count, "per_pack": per_pack, "per_pack_unit": per_unit}]


@pytest.mark.parametrize("title,total,counter,packs", [
    ("文化たきつけ 富士屋 着火剤 18本入 2袋セット", 36, "本", pk("袋", 2, 18, "本")),            # F1（cololo:10000025）
    ("着火剤 18本入り×2袋", 36, "本", pk("袋", 2, 18, "本")),
    ("着火剤 18本入り ×2袋セット", 36, "本", pk("袋", 2, 18, "本")),
    ("着火剤 18本×2袋", 36, "本", pk("袋", 2, 18, "本")),                                         # F2
    ("文化たきつけ 36本（18本×2個セット）", 36, "本", pk("個", 2, 18, "本")),                     # F3（mayfair-17:10014885）
    ("カイロ 240枚（60枚×4袋）", 240, "枚", pk("袋", 4, 60, "枚")),
    ("丸実富士屋商店 文化たきつけ 18本入り ×60個セット", 1080, "本", pk("個", 60, 18, "本")),   # 個を包装語にする
    ("トイレットペーパー 12ロール×4パック", 48, "ロール", pk("パック", 4, 12, "ロール")),
    ("缶詰 24缶入 3箱", 72, "缶", pk("箱", 3, 24, "缶")),
    ("文化たきつけ 60セット入り 1箱", 60, "セット", pk("箱", 1, 60, "セット")),
])
def test_forms_give_the_packs_and_keep_the_total(title, total, counter, packs):
    q = parse_quantity(title)
    assert (q.confidence, q.count_total, q.count_unit) == ("high", total, counter)
    assert q.packs == packs


@pytest.mark.parametrize("title", [
    "文化たきつけ 18本入り",                       # 包装の数が無い
    "トイレットペーパー 48ロール",
    "文化たきつけ 36本 2個パック",                # 総数が決まらない（low）
    "文化たきつけ",                                # none
    "着火剤 18本入 2袋セット 40本",               # 総数と N×M が食い違う（low）
    "水 500ml×24本",
])
def test_no_packs_when_the_form_or_the_total_is_missing(title):
    assert parse_quantity(title).packs == []


def test_number_boundaries_are_not_read():
    q = parse_quantity("着火剤 118本入 2袋セット")           # 直前が数字の位置（18本入 の途中）からは読まない
    assert (q.count_total, q.packs) == (236, pk("袋", 2, 118, "本"))


def test_several_forms_with_the_same_content_make_one_entry():
    q = parse_quantity("文化たきつけ 36本（18本×2個セット） 18本×2個")
    assert (q.confidence, q.count_total) == ("high", 36) and q.packs == pk("個", 2, 18, "本")


def test_the_output_always_has_packs_even_when_empty():
    for title, expected in (("着火剤 18本入 2袋セット", pk("袋", 2, 18, "本")), ("着火剤", [])):
        o = make_offer("x", name=title, price=500)
        o.quantity = read_offer_quantity(o)
        assert service.offer_to_dict(o)["quantity"]["packs"] == expected


def test_packs_come_from_the_title_only_not_from_a_caption_fill():
    """題名が none で説明欄の見出し付きの値から数量を補った候補（source=caption）の packs は空（§7: 包装の数は題名から）。"""
    o = make_offer("x", name="文化たきつけ 着火剤", price=500)
    o.caption = "■数量:18本入×2袋"
    q = read_offer_quantity(o)
    assert (q.source, q.count_total) == ("caption", 36) and q.packs == []
