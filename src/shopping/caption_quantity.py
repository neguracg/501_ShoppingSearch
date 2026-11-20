# @owns 説明欄の見出し付き記述からの数量の補完（題名が none の時の数量全体・題名が個数だけ high の時の内容量 `長さ`。題名の読み取り quantity.py は変えない）
"""説明欄（itemCaption）の「見出し付きの記述」だけから数量を読み、題名から数量が読めない（confidence=none）候補に補う（WP14 W4）。

WP11-2 の「説明文の全文を 2 つ目の読み取り元にする」案（入れない）とは用途が違う:
  - 全文の照合 … 題名の数量と食い違えば low にするので、説明欄の誤読 1 件ごとに単価不明が 8 件増えた（実測）。
  - ここ    … 見出しの直後の値（入数・入り数・内容量・数量・容量）だけを、題名が none の時だけ補う。題名 high は変えない
              （食い違えば caption_conflict の印と根拠を付けるだけ）。low の題名（題名の中に食い違う数がある）には補わない。
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
from .quantity import _counter_table, _norm, _token_re, _unit_table, parse_quantity

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


def read_offer_quantity(offer: Offer) -> QuantityInfo:
    """候補の数量（唯一の入口）。題名を parse_quantity で読み、題名が none の時だけ説明欄の見出し付きの記述で補う
    （source="caption"。価格が選択肢で変わる商品には補わない）。題名が high で個数だけの時は、見出し `長さ` の値を 1 個あたりの内容量に重ねる
    （項目単位。source="title+caption"。WP15 段B）。題名が high で説明欄と食い違う時は confidence を変えず caption_conflict と根拠だけ付ける。"""
    q = parse_quantity(offer.item_name)
    if q.confidence == "high" and q.count_total is not None and q.content_amount is None and not offer.price_varies:
        item = read_length(offer.caption)         # 項目単位の補完（題名が個数だけ high の時の内容量。価格が選択肢で変わる商品には補わない）
        if item is not None:
            q = replace(q, content_amount=item.info.content_amount, content_dimension="length", content_unit="m",
                        measure_total=round(q.count_total * item.info.content_amount, 9),
                        content_amounts={"length": item.info.content_amount}, source="title+caption",
                        caption_evidence=item.evidence)
    cap = read_caption(offer.caption)
    if cap is None:
        return q
    if q.confidence == "none":
        if offer.price_varies:
            return q       # 選択肢で価格が変わる商品の説明欄は選択肢の1つの記述でしかない（実測: 補完の誤りはすべてこの形）
        if CAPTION_FILL_UNIT_PRICE:
            return replace(cap.info, source="caption", caption_evidence=cap.evidence, packs=[])     # 包装の数は題名だけから（§7）
        q.caption_evidence = cap.evidence
        q.caption_candidate = {"count_total": cap.info.count_total, "count_unit": cap.info.count_unit,
                               "content_amount": cap.info.content_amount, "content_dimension": cap.info.content_dimension}
        return q
    if q.confidence == "high" and _conflicts(q, cap.info):
        q.caption_conflict = True
        q.caption_evidence = cap.evidence if q.source == "title" else f"{q.caption_evidence} / {cap.evidence}"
    return q
