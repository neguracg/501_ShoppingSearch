# @owns 題名の包装の数（外側の数。「18本入 2袋セット」の 2袋）の形 F1〜F3 の読み取り（総数・confidence は決めない）
"""題名の外側の数（包装の数）を捨てずに保持する（WP15 段B。SPEC §7「包装の数」）。

形は 3 つだけ（実題名 33 語で 10.4%）:
  F1  N<数え語>入(り) [×] M<包装語> [セット|パック|入]     18本入 2袋セット・18本入り×2袋
  F2  N<数え語>×M<包装語> [セット|パック|入]               18本×2袋
  F3  T<数え語>（N<数え語>×M<包装語> [セット|パック]）     36本（18本×2個セット）・240枚（60枚×4袋）
読むのは、題名の総数（quantity.py が決めた high の総数）が N×M と一致する時だけ（F3 は T も一致）。総数の規則はここに足さない。
形が複数あれば全部が同じ内容の時だけ 1 要素にし、食い違えば []（P0 と同じ一致原則）。
表（数え語・包装語）は quantity.py が持つので、呼び出し側（parse_quantity）が渡す。"""
from __future__ import annotations

import functools
import re

NUM = r"(\d{1,6})"
SEP = r"\s*"


@functools.lru_cache(maxsize=4)
def _forms(counter_keys: tuple[str, ...], pack_keys: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    c = "|".join(re.escape(k) for k in sorted(counter_keys, key=lambda w: (-len(w), w)))
    p = "|".join(re.escape(k) for k in sorted(pack_keys, key=lambda w: (-len(w), w)))
    tail = rf"(?:{SEP}(?:セット|パック|入))?(?![a-z0-9])"
    f1 = re.compile(rf"(?<![\d.,]){NUM}{SEP}({c}){SEP}入り?{SEP}[×x*]?{SEP}{NUM}{SEP}({p}){tail}")
    f2 = re.compile(rf"(?<![\d.,]){NUM}{SEP}({c}){SEP}[×x*]{SEP}{NUM}{SEP}({p}){tail}")
    f3 = re.compile(rf"(?<![\d.,]){NUM}{SEP}({c}){SEP}[（(]{SEP}{NUM}{SEP}({c}){SEP}[×x*]{SEP}{NUM}{SEP}({p}){SEP}(?:セット|パック)?{SEP}[）)]")
    return f1, f2, f3


def read_packs(norm_title: str, total: int, counters: dict[str, str], pack_words) -> list[dict]:
    """norm_title は NFKC＋casefold 済みの題名（括弧を残したもの）。total は題名の high の総数。counters は数え語の別名→正規名、
    pack_words は包装語の集合（正規化済み）。[{"unit","count","per_pack","per_pack_unit"}]（0 件か 1 件）。"""
    f1, f2, f3 = _forms(tuple(counters), tuple(pack_words))
    found: list[tuple] = []
    for m in f3.finditer(norm_title):
        t, c1, n, c2, k, p = m.groups()
        if int(t) == int(n) * int(k) == total and counters.get(c1, c1) == counters.get(c2, c2):
            found.append((p, int(k), int(n), c2))
    for rx in (f1, f2):
        for m in rx.finditer(norm_title):
            n, c, k, p = m.groups()
            if int(n) * int(k) == total:
                found.append((p, int(k), int(n), c))
    entries = {(counters.get(p, p), k, n, counters.get(c, c)) for p, k, n, c in found}
    if len(entries) != 1:
        return []
    unit, count, per_pack, per_unit = entries.pop()
    return [{"unit": unit, "count": count, "per_pack": per_pack, "per_pack_unit": per_unit}]
