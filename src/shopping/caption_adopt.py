# @owns 説明欄の内容量の採用（U1 (iii) 桁の照合。比較グループの題名由来の内容量の統計。抽出は caption_quantity）
"""題名が個数だけ high の候補に、説明欄の各文から抽出した 1個あたり内容量を採用する（SPEC §7 W4・WP16 U1 の (iii)）。

抽出（caption_quantity.read_offer_quantity）は値を `u1_pending`（(ii) 個数つきの文はその個数が題名の総数と一致・(i) 同じ次元の値が 1 通り
を通った物）と `caption_candidates`（印）に出すだけで、採否は決めない。ここは比較グループの統計が要る (iii) だけを判定する
（抽出と採用の分離。pricing.compare が語の絞り込みの後に 1 回呼ぶ）:
  (iii) 値が、同じ比較グループの題名由来（source="title"・high）の 1個あたり内容量の中央値の 1/ratio 以上 ratio 倍以下。
        題名由来がその次元に min_group 件未満なら採らない。min_group・ratio は WP10 の外れ値の N・K と同じ物差しで、値は pricing が渡す。
採った次元は仮の内容量（未確定理由 measure_from_caption。pricing.unconfirmed_reasons）。採らなかった値は caption_candidates に残る。
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

from .caption_quantity import consumed, set_content
from .models import Offer


def title_content_stats(offers: list[Offer]) -> dict[str, tuple[float, int]]:
    """比較グループの題名由来の 1個あたり内容量: 次元 → (中央値, 件数)。題名由来＝source が title（補った内容量・題名 low の仮の数量は数えない）で high。"""
    vals: dict[str, list[float]] = defaultdict(list)
    for o in offers:
        q = o.quantity
        if q is not None and q.confidence == "high" and q.source == "title":
            for d, a in (q.content_amounts or {}).items():
                vals[d].append(a)
    return {d: (median(v), len(v)) for d, v in vals.items()}


def adopt_u1_contents(offers: list[Offer], *, min_group: int, ratio: float) -> int:
    """offers（語の絞り込み後の比較グループ）の採用待ち（u1_pending）に (iii) を当てて、通った次元を仮の内容量にする。採用した候補の数を返す。
    呼び出し側が、前の採用の残り（u1_adopted のある候補）は読み直してから呼ぶ（採用は 1 回だけ。やり直しは読み直し）。"""
    stats = title_content_stats(offers)
    n = 0
    for o in offers:
        q = o.quantity
        if q is None or not q.u1_pending or q.u1_adopted:
            continue
        fill: dict[str, float] = {}
        for d, p in q.u1_pending.items():
            st = stats.get(d)
            if st is not None and st[1] >= min_group and st[0] / ratio <= p["amount"] <= st[0] * ratio:
                fill[d] = p["amount"]
        if not fill:
            continue
        set_content(q, fill)
        q.source = "title+caption"
        ev = " / ".join(dict.fromkeys(q.u1_pending[d]["evidence"] for d in fill))
        q.caption_evidence = f"{q.caption_evidence} / {ev}" if q.caption_conflict and q.caption_evidence else ev
        q.caption_candidates = [c for c in q.caption_candidates if not consumed(c, q.count_total, fill)]
        q.u1_adopted = list(fill)
        n += 1
    return n
