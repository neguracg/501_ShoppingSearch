# @owns 説明欄からの数量の抽出（各文の読み取りと caption_candidates）と、比較グループの統計が要らない採用（見出し付きの補完・`長さ`・題名 low の読みの選択 U2b）。題名の読み取り quantity.py は変えない
"""説明欄（itemCaption）の「見出し付きの記述」だけから数量を読み、題名から数量が読めない（confidence=none）候補に補う（WP14 W4）。

WP11-2 の「説明文の全文を 2 つ目の読み取り元にする」案（入れない）とは用途が違う:
  - 全文の照合 … 題名の数量と食い違えば low にするので、説明欄の誤読 1 件ごとに単価不明が 8 件増えた（実測）。
  - ここ    … 見出しの直後の値（入数・入り数・内容量・数量・容量）だけを、題名が none の時だけ補う。題名 high は変えない
              （食い違えば caption_conflict の印と根拠を付けるだけ）。low の題名（題名の中に食い違う数がある）には補わない。
WP16: 抽出と採用を分ける。説明欄を文に分けて各文を題名と同じ parse_quantity で読み（見出しの語に依存しない）、読めた値は全部
`quantity.caption_candidates`（印）に残す。採用は (a) 見出し付きの補完（題名 none・`長さ`。従来どおり）、(b) 題名 low の読みの選択（U2b）、
(c) 題名が個数だけ high の時の内容量（U1。(ii)(i) を通した値を `u1_pending` に置くだけ。(iii) 桁の照合と採用は比較グループの統計が要るので
caption_adopt.py）。採らなかった値が印に残る。
採らない所は語のリストではなく位置・区切りで決める: 「関連キーワード」「本商品の説明ではありません」以降、「はこちら」を含む
記述、見出しの無い文中の数（本品を1～2本・まめカイロ7枚・15点以上）。
補った数量は source="caption"・caption_evidence を持ち、単位価格を出すが確認済みではない（pricing.unconfirmed_reasons が
quantity_from_caption として最安から外す）。CAPTION_FILL_UNIT_PRICE=False にすると印と根拠だけ（quantity.caption_candidate）に縮む。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace

from .models import Offer, QuantityInfo
from .quantity import _counter_table, _norm, _token_re, _unit_table, base_unit, parse_quantity

# 見出し付きの補完（題名 none の数量全体）と caption_conflict の照合に使う見出し。WP16 の各文の読み取りは見出しの語に依存しない（下の read_sentences）
HEADINGS = ("入り数", "入数", "内容量", "数量", "容量")
# 値に「1個あたり」の言い回し（あたり・当たり・当り・につき・ごと）がある時は、総数ではなく単位あたりの説明なので読まない
_PER_UNIT = re.compile(r"あたり|当たり|当り|につき|ごと")
# 補完の形（WP14 W4）: True＝補完した数量（source="caption"・high）として単位価格を出し、グループに並べる。確認済みではないので
# 最安・注文の最安には選ばれず、安い時は to_check に「説明欄『…』の数量が正しければ」の条件つきで出る（誤りの害は条件文の中に閉じる。
# オーケストレータの判断で出荷）。False＝印と根拠だけ（quantity.caption_candidate・caption_evidence。数量は none のまま・単位価格を出さない）。
# 実測では指示書の基準（補完の誤り 10% 超）に当たった（SPEC §7 W4 の実測）が、確認済みにしない前提で完全形を採った。
CAPTION_FILL_UNIT_PRICE = True
VALUE_MAX = 40                                     # 値として読む最大文字数（見出しの直後から）

# 説明欄のここから後ろは本商品の記述ではない（検索用キーワード列・断り書き）。位置で切る
_TAIL = re.compile(r"関連キーワード|本商品の説明ではありません")
_HEAD = "|".join(HEADINGS)
# 見出し: 直前が語の文字でない（購入数・大容量・総内容量 の途中に一致しない）。見出しの直後の閉じ括弧・区切り・空白は読み飛ばす。
# 値は数字（または 約＋数字）で始まる時だけ（数量限定・内容量:本体… の値は読まない）
_HEADING_RE = re.compile(rf"(?<!\w)(?P<head>{_HEAD})[\]】」』)]?[\s:]*(?=約?\s*\d)")
# 項目単位の補完（WP15 段B）の見出し。内容量の見出し（HEADINGS）とは別に持ち、値は「数字＋長さの単位」で始まる時だけ読む
# 見出し `長さ` の補完は U1（各文の読み取り）の形の部分集合として残し、先に当てる（WP16）
ITEM_HEADING = "長さ"
# 見出しの直後は区切り（: ・ / ・ ] ・ 】）・空白・数字の直付けのどれでもよい（長さ25m・長さ 35m・長さ／25m）。使用例の文は下の助詞で止める
_ITEM_RE = re.compile(rf"(?<!\w)(?P<head>{ITEM_HEADING})[\]】」』)]?[\s:/]*(?=約?\s*\d)")
# 値の単位の直後（空白を読み飛ばして）が助詞（長さ30cmにカット・長さ 約30cm のコード付き・100mほど）の文は、内容量の記述ではない
_PARTICLE_AFTER = re.compile(r"\s*(?:に|で|の|を|は|が|ほど|まで|より)")
# 値の終わり: 改行・見出し記号・句点・注記（※）・別の見出し（直前が語の文字でないもの）・「はこちら」
_VALUE_END = re.compile(rf"[\n\r■●◆▼▲★☆【※。]|(?<!\w)(?:{_HEAD})|はこちら")


@dataclass
class CaptionReading:
    info: QuantityInfo                 # 値を parse_quantity で読んだ結果（high のものだけ）
    evidence: str                      # 見出しから値までの原文（NFKC 後）。複数の見出しがあれば " / " でつなぐ
    headings: list[str]


def _clean(caption: str) -> str:
    text = unicodedata.normalize("NFKC", caption)
    m = _TAIL.search(text)
    return text[:m.start()] if m else text


def _has_count(value: str) -> bool:
    """値に「数字＋数え語」（個数の記述）があるか。内容量だけの値（内容量:2L・容量 500ml）は個数が決まらない
    （1本の容量か、ケース全体か）ので読まない。"""
    rx = _token_re(tuple(_unit_table()), tuple(_counter_table()))
    return any(m.group("counter") for m in rx.finditer(_norm(value)))


def _segments(text: str, heading_re: re.Pattern = _HEADING_RE) -> list[tuple[str, str]]:
    """(見出し, 値の原文) の一覧。値は見出しの直後から、区切り・次の見出し・VALUE_MAX 字のいちばん早いところまで。
    値や直前の文に「はこちら」がある記述（別商品への案内）は採らない。"""
    out: list[tuple[str, str]] = []
    heads = list(heading_re.finditer(text))
    for i, m in enumerate(heads):
        start = m.end()
        end = min(len(text), start + VALUE_MAX)
        stop = _VALUE_END.search(text, start, end)
        if stop:
            end = stop.start()
        nxt = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        end = min(end, nxt)
        value = text[start:end].strip()
        # 同じ文（見出しの前後の区切りまで）に「はこちら」があれば別商品への案内
        s0 = max(text.rfind(c, 0, m.start()) for c in "\n。■●◆")
        s1 = min([x for x in (text.find(c, m.end()) for c in "\n。") if x >= 0] or [len(text)])
        if "はこちら" in text[s0 + 1:s1] or not value:
            continue
        out.append((m.group("head"), text[m.start():end].strip()))
    return out


def read_caption(caption: str | None) -> CaptionReading | None:
    """説明欄の見出し付きの記述から数量を読む。読めなければ None。見出しが複数あれば、全部が high で同じ総数・同じ内容量の時だけ
    採る（P0 と同じ一致原則。食い違えば None）。"""
    if not isinstance(caption, str) or not caption:
        return None
    segs = _segments(_clean(caption))
    if not segs:
        return None
    infos: list[QuantityInfo] = []
    for head, raw in segs:
        value = raw[len(head):].lstrip("]】」』) :")
        q = parse_quantity(value)
        if q.confidence != "high" or q.count_total is None or not _has_count(value) or _PER_UNIT.search(value):
            return None
        infos.append(q)
    first = infos[0]
    for q in infos[1:]:
        if (q.count_total, q.content_dimension, q.content_amount) != (first.count_total, first.content_dimension,
                                                                      first.content_amount):
            return None
    return CaptionReading(info=first, evidence=" / ".join(dict.fromkeys(r for _, r in segs)),
                          headings=[h for h, _ in segs])


def read_length(caption: str | None) -> CaptionReading | None:
    """見出し `長さ` の値を 1 個あたりの内容量として読む（WP15 段B。個数だけ high の題名に重ねる）。全部同時に満たす時だけ:
    値が「約＋数字＋長さの単位」で始まり、単位の直後（空白を読み飛ばして）が助詞でない／値の中の単位付きの数が 1 つだけ（m と mm が混ざる値は採らない）／個数の記述が無い／
    単位あたりの言い回しが無い／見出しが複数あれば全部が同じ値。読めなければ None。"""
    if not isinstance(caption, str) or not caption:
        return None
    segs = _segments(_clean(caption), _ITEM_RE)
    if not segs:
        return None
    rx = _token_re(tuple(_unit_table()), tuple(_counter_table()))
    amounts: set[float] = set()
    for head, raw in segs:
        value = _norm(raw[len(head):].lstrip("]】」』) :/"))
        start = re.match(r"約?\s*", value).end()
        first = rx.match(value, start)
        toks = list(rx.finditer(value))
        if (first is None or not first.group("unit") or len(toks) != 1 or _PER_UNIT.search(value)
                or _PARTICLE_AFTER.match(value, first.end())):
            return None
        q = parse_quantity(value)
        if q.confidence != "high" or q.content_dimension != "length" or q.content_amount is None:
            return None
        amounts.add(q.content_amount)
    if len(amounts) != 1:
        return None
    info = QuantityInfo(count_total=1, content_amount=amounts.pop(), content_dimension="length", content_unit="m",
                        confidence="high")
    return CaptionReading(info=info, evidence=" / ".join(dict.fromkeys(r for _, r in segs)), headings=[h for h, _ in segs])


def _conflicts(title_q: QuantityInfo, cap_q: QuantityInfo) -> bool:
    """題名の数量（high）と説明欄の数量が食い違うか。総個数が違う、または同じ次元の総量が違う。"""
    if title_q.count_total != cap_q.count_total:
        return True
    if (title_q.content_dimension and title_q.content_dimension == cap_q.content_dimension
            and title_q.measure_total != cap_q.measure_total):
        return True
    return False


# ---- WP16: 説明欄の各文の読み取り（抽出）----
# 文の区切り: 改行・見出し記号・句点・注記（※）。見出しの区切り `:` でも割る。位置の規則（語のリストは持たない）は split_sentences
_DELIM = re.compile(r"[\n\r■●◆▼▲★☆【】※。]")
_CLOSERS = ")）]】」』"
# 見出しの区切りの `/`（長さ/50m）。日本語の文字の直後で数字の直前の `/` だけ（A/50m・1/2 は割らない）
_SLASH_HEAD = re.compile(r"(?<=[^\x00-\x7f])/(?=\d)")


def _trim_label(seg: str) -> str:
    """`:` の前の断片の末尾は次の見出しの語（スコッティ入数:8ロール×6個ロールサイズ:108mm… の `ロールサイズ`）。
    位置の規則: 断片の最後の「数字＋単位／数え語」の終わり（直後の閉じ括弧を含む）までを値とし、その後ろは次の見出しとして切る。"""
    n = _norm(seg)
    rx = _token_re(tuple(_unit_table()), tuple(_counter_table()))
    last = None
    for m in rx.finditer(n):
        last = m
    if last is None:
        return seg
    end = last.end()
    while end < len(n) and n[end] in _CLOSERS:
        end += 1
    return n[:end]


def split_sentences(caption: str | None) -> list[str]:
    """説明欄 → 文の一覧。区切り: 改行・■●◆▼▲★☆【】※。と見出しの区切り `:`（`/` は上の位置の規則）。「関連キーワード」以降（_clean）と
    「はこちら」を含む空白区切りの塊は採らない（区切りの無い長い run ごとは捨てない。f222101-fuji:10001780 の `ロールサイズ:108mm×100m` が消える）。"""
    if not isinstance(caption, str) or not caption:
        return []
    text = _SLASH_HEAD.sub(":", _clean(caption))
    out: list[str] = []
    for blk in _DELIM.split(text):
        if "はこちら" in blk:
            blk = " ".join(ch for ch in re.split(r"\s+", blk) if "はこちら" not in ch)
        parts = blk.split(":")
        for i, p in enumerate(parts):
            if i < len(parts) - 1:
                p = _trim_label(p)
            p = p.strip()
            if p:
                out.append(p)
    return out


@dataclass
class SentenceReading:
    text: str
    info: QuantityInfo                 # 文を parse_quantity で読んだ結果（high のものだけ）
    counted: bool                      # 文に個数の記述（数字＋数え語）がある（内容量だけの文は count_total=1 になるので個数とは見ない）


def read_sentences(caption: str | None) -> list[SentenceReading]:
    """各文を題名と同じ parse_quantity で読み、high で個数か内容量を持つ物を全部集める（単位あたりの言い回しの文は今の規則のまま読まない）。"""
    out: list[SentenceReading] = []
    for s in split_sentences(caption):
        if _PER_UNIT.search(s):
            continue
        q = parse_quantity(s)
        if q.confidence != "high":
            continue
        counted = _has_count(s) and q.count_total is not None
        if q.content_amounts or counted:
            out.append(SentenceReading(s, q, counted))
    return out


def _candidates(sents: list[SentenceReading]) -> list[tuple[SentenceReading, str | None, dict]]:
    """文ごとの読み → 候補の dict（印の形）。(文, 次元 or None, dict) の一覧で、同じ内容の dict は最初の 1 つだけ残す。
    次元が複数ある文は、最初の次元の dict に個数を付け、後ろの次元は個数なしの dict にする。"""
    seen: set = set()
    out: list[tuple[SentenceReading, str | None, dict]] = []
    for r in sents:
        rows = list((r.info.content_amounts or {}).items()) or [(None, None)]
        for i, (d, a) in enumerate(rows):
            with_count = r.counted and i == 0
            cand = {"count_total": r.info.count_total if with_count else None,
                    "count_unit": r.info.count_unit if with_count else None,
                    "content_amount": a, "content_dimension": d, "evidence": r.text[:80]}
            key = (cand["count_total"], cand["count_unit"], a, d)
            if key not in seen:
                seen.add(key)
                out.append((r, d, cand))
    return out


def consumed(c: dict, count: int | None, fill: dict) -> bool:
    """候補 c の値が、採用した数量（総数 count or None・内容量 fill＝次元→値）で言い尽くされているか（採用した値は印から外す）。"""
    has_count, has_content = c["count_total"] is not None, c["content_dimension"] is not None
    if not (has_count or has_content):
        return False
    if has_count and c["count_total"] != count:
        return False
    if has_content and fill.get(c["content_dimension"]) != round(c["content_amount"], 9):
        return False
    return True


def set_content(q: QuantityInfo, fill: dict[str, float]) -> None:
    """題名に内容量が無い時に、説明欄の内容量（次元→基準単位の値）を重ねる。content_dimension・content_amount は最初の次元。"""
    q.content_amounts = dict(fill)
    dim = next(iter(fill))
    q.content_dimension, q.content_amount, q.content_unit = dim, fill[dim], base_unit(dim)
    q.measure_total = None if q.count_total is None else round(q.count_total * fill[dim], 9)


def _evidence(rows: list[SentenceReading]) -> str:
    return " / ".join(dict.fromkeys(r.text for r in rows))[:200]


def _select_low_reading(q: QuantityInfo, sents: list[SentenceReading]) -> tuple[QuantityInfo, tuple | None, dict]:
    """U2b: 題名 low の読みの選択。説明欄の個数（総数と数え語）が readings.counts のちょうど 1 つと一致する時、その読みを仮の数量にする
    （内容量は、説明欄の値と readings.contents が次元ごとにちょうど 1 つ一致する時だけ）。採った (個数, 内容量) を返す（印から外すため）。"""
    rd = q.readings or {"counts": [], "contents": {}}
    rc = [(c["count"], c["count_unit"]) for c in rd["counts"]]
    counts: list[tuple] = []
    for r in sents:
        if r.counted and (r.info.count_total, r.info.count_unit) not in counts:
            counts.append((r.info.count_total, r.info.count_unit))
    hit = [c for c in counts if c in rc]
    if len(hit) != 1:
        return q, None, {}
    by_dim: dict[str, list[float]] = {}
    for r in sents:
        for d, a in (r.info.content_amounts or {}).items():
            if round(a, 9) not in by_dim.setdefault(d, []):
                by_dim[d].append(round(a, 9))
    fill: dict[str, float] = {}
    for d, vals in by_dim.items():
        read = [round(x, 9) for x in rd["contents"].get(d, [])]
        both = [a for a in vals if a in read]
        if len(both) == 1:
            fill[d] = both[0]
    q = replace(q, count_total=hit[0][0], count_unit=hit[0][1], source="title+caption",
                caption_evidence=_evidence([r for r in sents if r.counted and (r.info.count_total, r.info.count_unit) == hit[0]]))
    if fill:
        set_content(q, fill)
    return q, hit[0], fill


def read_offer_quantity(offer: Offer) -> QuantityInfo:
    """候補の数量（唯一の入口）。題名を parse_quantity で読み、説明欄の値を次のどれかで重ねる（WP16: 抽出は広く・採用は分類）。
    ・題名が none: 見出し付きの記述で数量全体を補う（source="caption"。価格が選択肢で変わる商品には補わない）。
    ・題名が high で個数だけ: 見出し `長さ` の値を 1 個あたりの内容量に重ねる（項目単位。WP15 段B）。補えなければ各文の値のうち U1 の (ii)(i) を
      通った物を採用待ち（u1_pending）にする（(iii) 桁の照合と採用は比較グループの統計が要るので caption_adopt）。題名が high で説明欄の
      見出し付きの値と食い違う時は confidence を変えず caption_conflict と根拠だけ付ける。
    ・題名が low（low_reason が multiple_totals でない・価格が選択肢で変わらない）: 説明欄の個数が題名の読みの 1 つに決まれば仮の数量にする
      （U2b。confidence は low のまま。未確定理由 quantity_low）。
    採らなかった各文の値は caption_candidates に残す（印）。題名が high で内容量もある候補には各文の値を残さない（補う物が無い）。"""
    q = parse_quantity(offer.item_name)
    sents = read_sentences(offer.caption)
    cands = _candidates(sents)
    adopt_count: tuple | None = None
    adopt_fill: dict[str, float] = {}
    pending: dict[str, dict] = {}
    cap = read_caption(offer.caption)
    if q.confidence == "high" and q.count_total is not None and q.content_amount is None and not offer.price_varies:
        item = read_length(offer.caption)         # 項目単位の補完（題名が個数だけ high の時の内容量。価格が選択肢で変わる商品には補わない）
        if item is not None:
            q = replace(q, content_amount=item.info.content_amount, content_dimension="length", content_unit="m",
                        measure_total=round(q.count_total * item.info.content_amount, 9),
                        content_amounts={"length": item.info.content_amount}, source="title+caption",
                        caption_evidence=item.evidence)
            adopt_count, adopt_fill = (q.count_total, q.count_unit), {"length": round(item.info.content_amount, 9)}
        else:
            # U1 (ii)(i): 個数つきの文の内容量は、その文の個数が題名の総数と一致する時だけ候補にする。残った同じ次元の値が 1 通りなら採用待ち
            # 個数つきの文は、文の全次元に効かせる（2 つ目以降の次元の印の dict は個数を持たないので、文の個数で見る。C1）。重複除去の前の文から集める
            by_dim: dict[str, list[tuple[float, str]]] = {}
            for r in sents:
                if r.counted and r.info.count_total != q.count_total:
                    continue
                for d, a in (r.info.content_amounts or {}).items():
                    by_dim.setdefault(d, []).append((round(a, 9), r.text[:80]))
            for d, rows in by_dim.items():
                if len({a for a, _ in rows}) == 1:
                    pending[d] = {"amount": rows[0][0], "evidence": rows[0][1]}
    if q.confidence == "high":
        adopt_count = (q.count_total, q.count_unit)             # 題名の個数と同じ個数だけの値は印に残さない（新しい情報が無い）
        if cap is not None and _conflicts(q, cap.info):
            q.caption_conflict = True
            q.caption_evidence = cap.evidence if q.source == "title" else f"{q.caption_evidence} / {cap.evidence}"
        if q.content_amount is not None and q.source == "title":
            cands = []                                                            # 題名に内容量がある: 各文の値を残さない
    elif q.confidence == "none":
        if cap is not None and not offer.price_varies:
            if CAPTION_FILL_UNIT_PRICE:
                q = replace(cap.info, source="caption", caption_evidence=cap.evidence, packs=[])     # 包装の数は題名だけから（§7）
                adopt_count = (q.count_total, q.count_unit)
                adopt_fill = {d: round(a, 9) for d, a in (q.content_amounts or {}).items()}
            else:
                q.caption_evidence = cap.evidence
                q.caption_candidate = {"count_total": cap.info.count_total, "count_unit": cap.info.count_unit,
                                       "content_amount": cap.info.content_amount, "content_dimension": cap.info.content_dimension}
    elif q.confidence == "low" and q.low_reason != "multiple_totals" and not offer.price_varies:
        q, adopt_count, adopt_fill = _select_low_reading(q, sents)
    q.caption_candidates = [c for _, _, c in cands if not consumed(c, adopt_count[0] if adopt_count else None, adopt_fill)]
    q.u1_pending = pending
    return q
