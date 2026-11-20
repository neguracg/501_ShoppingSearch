# @owns 数え語（袋・本・枚…）で比べる時の購入単位の換算（包装の数・1袋の中身の一致・換算の仮定とその条件文の素材）
"""basis が数え語の比較（SPEC §8 Q20・Q19）の「どの候補を何袋と数えるか」だけを決める。単価・注文案・並びは pricing が組む
（ここは Offer と数え語から、数・基準・仮定の文を返す純粋な関数）。

比べる候補（basis=袋）:
  (a) count_unit が袋の候補（個数＝袋の総数。従来どおり）
  (b) quantity.packs に袋がある候補（数＝packs[].count。「18本入 2袋セット」は 2袋）
確認済みで横並びにするのは 1袋の中身（per_pack・per_pack_unit）が基準と一致する (b) だけ。基準＝(b) の中で最も多い中身
（同数なら確認済みの候補の最安の注文額が安い方）。食い違う候補は pack_content_differs。
それ以外の候補（本だけ・セット・個・量が読めない）は捨てず、換算の仮定つき（counter_assumed）で to_check に出す:
  ① (b) の中身がただ 1 通りで、その候補の count_unit が中身の数え語と同じ → 「1袋が18本なら」（袋の数＝総数÷中身）
  ② それ以外 → 「この商品の1本が1袋なら」（袋の数＝その商品の総数）。量が読めない候補は「この商品1点が1袋なら」（注文個数＝希望量）
basis が個の時に主グループと違う数え語の候補は「1個が1枚なら」（総数をそのまま主グループの数え語の数とみなす）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Offer


@dataclass
class Assumption:
    """換算の仮定。amount＝この仮定での 1 個あたりの量（basis の数え語の数）、text＝条件文の前置き（「1袋が18本なら」）。"""
    offer: Offer
    amount: float
    text: str
    keep: bool = False        # True＝確認済みの最安との比較をせず必ず to_check に残す（量が読めて換算できる候補。Q20）。False＝より安くなり得る時だけ

def counted_as(o: Offer, counter: str) -> str | None:
    """候補を basis=数え語 でどう数えるか。"count"（count_unit が数え語。a）／"pack"（packs に数え語がある。b）／None。"""
    q = o.quantity
    if q is None or q.confidence != "high" or q.count_total is None:
        return None
    if q.count_unit == counter:
        return "count"
    return "pack" if pack_of(o, counter) is not None else None


def pack_of(o: Offer, counter: str) -> dict | None:
    q = o.quantity
    if q is None or q.confidence != "high":
        return None
    return next((p for p in (q.packs or []) if p.get("unit") == counter), None)


def content_key(pack: dict) -> tuple[int, str]:
    return (pack["per_pack"], pack["per_pack_unit"])


def content_text(key: tuple[int, str]) -> str:
    return f"{key[0]}{key[1]}入"


def choose_base(pack_offers: list[Offer], counter: str, desired: float | None, confirmed) -> tuple[int, str] | None:
    """(b) の候補の 1袋の中身の基準。最も多い中身、同数なら確認済みの候補の最安の注文額（希望量が無ければ価格）が安い方。
    confirmed(o) は送料以外の確認済みの判定（pricing.unconfirmed_reasons が空か）。"""
    if not pack_offers:
        return None
    by: dict[tuple[int, str], list[Offer]] = {}
    for o in pack_offers:
        by.setdefault(content_key(pack_of(o, counter)), []).append(o)

    def cheapest(offers: list[Offer]) -> float:
        ok = [o for o in offers if confirmed(o)] or offers
        out = []
        for o in ok:
            if o.price is None:
                continue
            n = 1 if desired is None else max(1, math.ceil(round(desired / pack_of(o, counter)["count"], 9)))
            out.append(n * o.price)
        return min(out) if out else float("inf")
    return min(by, key=lambda k: (-len(by[k]), cheapest(by[k]), k))


def differs_text(o: Offer, counter: str) -> str:
    """食い違う 1袋の中身の前置き（to_check の条件文）。"""
    return f"1{counter}の中身が違う（{content_text(content_key(pack_of(o, counter)))}）。"


def unique_content(pack_offers: list[Offer], counter: str) -> tuple[int, str] | None:
    """(b) の候補の 1袋の中身が全部同じ 1 通りならそれ。"""
    keys = {content_key(pack_of(o, counter)) for o in pack_offers}
    return next(iter(keys)) if len(keys) == 1 else None


def _source_text(pack_offers: list[Offer]) -> str:
    first = pack_offers[0]
    name = first.shop_name or first.shop_code or first.mall_item_code
    return f"{name} の商品名" if len(pack_offers) == 1 else f"{name} ほか {len(pack_offers) - 1}件の商品名"


def assume_for_counter(others: list[Offer], pack_offers: list[Offer], counter: str) -> tuple[list[Assumption], str | None]:
    """basis=数え語 で (a)(b) に入らない候補（others）の換算の仮定。(仮定の一覧, ①の根拠の説明 or None)。
    price が無い候補は対象外。量が読めない候補（none・low）は 1 点 = 1<数え語>。"""
    base = unique_content(pack_offers, counter) if pack_offers else None
    out: list[Assumption] = []
    used_base = False
    for o in others:
        if o.price is None:
            continue
        q = o.quantity
        if q is not None and q.caption_candidate is not None:
            continue                       # 説明欄に見出し付きの数量がある（印と根拠だけの形。CAPTION_FILL_UNIT_PRICE=False）候補は caveats で案内済み
        if q is not None and q.confidence == "high" and q.count_total:
            if base is not None and q.count_unit == base[1] and q.count_total % base[0] == 0:
                note = f"（根拠: {_source_text(pack_offers)}）"
                out.append(Assumption(o, q.count_total / base[0], f"1{counter}が{base[0]}{base[1]}なら{note}", keep=True))
                used_base = True
            else:
                out.append(Assumption(o, float(q.count_total), f"この商品の1{q.count_unit}が1{counter}なら", keep=True))
        else:
            out.append(Assumption(o, 1.0, f"この商品1点が1{counter}なら"))
    why = (f"1{counter}＝{base[0]}{base[1]}は候補 {len(pack_offers)}件の商品名から（{_source_text(pack_offers)}）"
           if used_base and base is not None else None)
    return out, why


def assume_for_main(others: list[Offer], main_unit: str) -> list[Assumption]:
    """basis が個で、主グループの数え語（main_unit。枚）と違う数え語の候補（個）の換算の仮定。総数をそのまま主グループの数え語の数とみなす
    （「1個が1枚なら」）。量が読めない候補はグループに入らないので対象外。"""
    out: list[Assumption] = []
    for o in others:
        q = o.quantity
        if o.price is None or q is None or q.confidence != "high" or not q.count_total:
            continue
        out.append(Assumption(o, float(q.count_total), f"1{q.count_unit}が1{main_unit}なら"))
    return out


def caveat(assumptions: list[Assumption], counter: str, why: str | None) -> str | None:
    """換算の仮定を置いた件数と根拠（caveats の 1 文）。"""
    if not assumptions:
        return None
    base = (f"。{why}" if why else "")
    return (f"数え語の換算を仮定して to_check に出した候補: {len(assumptions)}件"
            f"（確認済みではない。最安には選ばず、各候補の条件文の仮定が正しければ比べられる）{base}")
