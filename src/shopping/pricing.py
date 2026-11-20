# @owns 語による絞り込み・基準単位あたりの単価・支払総額・最安判定（比較グループ分け・断定できない理由の明示）・確認済みの判定・希望量を注文する組み合わせ（order_plans・cheapest_order・to_check）
"""価格比較。商品の意味（仕様の違い）は判定しない。読み取った数量（個数×内容量）から、
指定または自動で決めた基準（basis）あたりの単価を出し、送料不明のときは総額最安を断定しない。"""
from __future__ import annotations

import math
from collections import Counter
from statistics import median
from dataclasses import dataclass, field

from . import counter_basis
from .caption_quantity import read_offer_quantity
from .inputs import check_desired_range, resolve_compare_basis
from .models import Offer
from .quantity import DISPLAY, _norm, base_unit, format_amount

SPEC_CAVEAT = "仕様の違い（濃縮・層数・型番・色など）は判定していません。商品名で確認してください。"
QUANTITY_CAVEAT = "数量は商品名からの読み取りで、誤ることがあります。購入前に商品ページで確認してください。"

# 単価の外れ値（WP10。SPEC §8）。単位価格が出ている候補が OUTLIER_MIN_GROUP 件以上ある時だけ、単位価格の中央値の
# 1/OUTLIER_RATIO 未満の候補を「数量の読み違いの疑い」として単位価格の最安・必要数量を満たす最安から外す。
# 値（N=4・K=10）の根拠は SPEC §8「単価の外れ値の N・K」（実 API 99 検索・1429 件の実測表）。
OUTLIER_MIN_GROUP = 4
OUTLIER_RATIO = 10
OUTLIER_NOTE = "単価が他の候補と桁違いに安い。数量の読み違いの疑い。商品ページで確認"


# 選択肢で価格が変わる候補（WP14 W1。SPEC §8）。表示価格（itemPrice）は最小の選択肢の価格で、商品名の数量の選択肢の
# 価格とは限らない。単位価格・注文の最安には選ばず、一覧には残す
PRICE_VARIES_NOTE = "選択肢によって価格が変わる。表示価格は商品名の数量の選択肢の価格とは限らない。商品ページで確認"


def unconfirmed_reasons(o: Offer, *, shipping: bool = False) -> list[str]:
    """「確認済み」でない理由（空なら確認済み）。単位価格の最安・注文の最安・to_check が呼ぶ唯一の判定（WP14）。
    確認済み＝数量が商品名から high ∧ 説明欄の見出し付きの数量と食い違わない ∧ 補った内容量を価格の比較に使わない ∧ 1袋の中身が基準と一致する
    ∧ 選択肢で価格が変わらない ∧ 外れ値でない（∧ shipping=True の時は送料が確定）。
    理由の語: quantity_unknown / caption_conflict / price_varies / unit_price_outlier / quantity_from_caption / measure_from_caption /
    pack_content_differs / shipping_separate / shipping_unknown（counter_assumed は注文案の換算の仮定で、案の側が足す。counter_basis.py）。"""
    reasons: list[str] = []
    q = o.quantity
    if q is None or q.confidence != "high":
        reasons.append("quantity_unknown")
    elif getattr(q, "source", "title") == "title+caption":
        # 項目単位の補完（WP15 段B）。題名の個数は確認済みのまま。補った内容量を使う basis（単価の次元＝内容量の次元）の時だけ未確定
        if o.unit_price_dimension is not None and o.unit_price_dimension == q.content_dimension:
            reasons.append("measure_from_caption")
    elif getattr(q, "source", "title") != "title":
        reasons.append("quantity_from_caption")
    if q is not None and q.caption_conflict:
        reasons.append("caption_conflict")
    if o.pack_content_differs:
        reasons.append("pack_content_differs")
    if o.price_varies:
        reasons.append("price_varies")
    if o.unit_price_outlier:
        reasons.append("unit_price_outlier")
    if shipping and total_price(o) is None:
        reasons.append("shipping_separate" if o.shipping_status == "separate" else "shipping_unknown")
    return reasons


def is_confirmed(o: Offer, *, shipping: bool = False) -> bool:
    return not unconfirmed_reasons(o, shipping=shipping)


# 単価の未確定理由（WP15。SPEC §8 Q21）。unconfirmed_reasons のうち送料以外。送料別・不明は単価の誤りではない。
# 出力の dict が単価を素の値で出すか仮の値で出すかの唯一の判定（service が呼ぶ）。理由の集合は別に持たない（送料の語だけを除く）
_SHIPPING_REASONS = ("shipping_separate", "shipping_unknown")


def unit_price_reasons(reasons: list[str]) -> list[str]:
    """unconfirmed_reasons（送料を含んでよい）から単価を未確定にする理由だけを取る。"""
    return [r for r in reasons if r not in _SHIPPING_REASONS]


# 仮の単価に添える理由の文（WP15 Q24。Web・CLI の表示用。理由の語の意味はここ1か所）
UNIT_PRICE_REASON_TEXT = {
    "quantity_from_caption": "説明欄から補った数量",
    "caption_conflict": "題名と説明欄の数量が食い違う",
    "price_varies": "選択肢で価格が変わる",
    "unit_price_outlier": "他の候補より桁違いに安い。数量の読み違いの疑い",
    "quantity_unknown": "数量が商品名から読めない",
    "measure_from_caption": "説明欄から補った内容量",
    "counter_assumed": "数え語の換算を仮定",
    "pack_content_differs": "1袋の中身が違う",
}


def unit_price_reason_text(reasons: list[str]) -> str:
    return "・".join(UNIT_PRICE_REASON_TEXT.get(r, r) for r in reasons)


def unit_price_text(d: dict, key: str = "unit_price") -> str | None:
    """出力 dict（service が作る候補・注文案）の単価の表示文（Web・CLI 共通）。確認済みは「1個あたり 25.00円」、
    未確定は「仮 1個あたり 25.00円（選択肢で価格が変わる）」、単価なしは None。key は候補なら unit_price、注文案なら order_unit_price。"""
    label = d.get("unit_price_label") or ""
    if d.get(key) is not None:
        return " ".join(x for x in (label, f"{format_unit_price(d[key])}円") if x)
    prov = d.get(f"provisional_{key}")
    if prov is None:
        return None
    body = " ".join(x for x in ("仮", label, f"{format_unit_price(prov)}円") if x)
    return f"{body}（{unit_price_reason_text(d.get('unit_price_unconfirmed_reasons') or [])}）"


def unit_price_digits(x: float) -> int:
    """単価の小数桁数（唯一の実装）。通常は 2 桁。2 桁で 0.00 になってしまう小さな正の値は有効数字が出るまで
    増やす（最大 4 桁。S10）。"""
    for digits in (2, 3):
        if x <= 0 or round(x, digits) != 0:
            return digits
    return 4


def round_unit_price(x: float | None) -> float | None:
    """JSON など数値で出す単価の丸め（桁数は unit_price_digits）。"""
    return None if x is None else round(x, unit_price_digits(x))


def format_unit_price(x: float) -> str:
    """単価の表示（円）。桁数は unit_price_digits。"""
    return f"{x:,.{unit_price_digits(x)}f}"


@dataclass
class OrderPlan:
    """同じ商品を n 個注文する案（WP14 W2）。異なる商品の混ぜ合わせはしない。"""
    offer: Offer
    n: int                            # 注文個数 = ceil(下限 / 1個の量)
    order_quantity: float             # n × 1個の量（basis の単位）
    order_total: int                  # n × 価格（送料額が分かる時だけ送料を足す）。送料別・不明は商品代だけ
    order_unit_price: float           # order_total ÷ order_quantity（表示単位あたりの円）
    shipping_status: str
    reasons: list[str] = field(default_factory=list)      # 確認済みでない理由（unconfirmed_reasons。空なら確認済み）
    count_unit: str | None = None
    # 数え語の換算（WP15 段B。counter_basis.py）: reason → 条件文の前置き（counter_assumed「1袋が18本なら」・pack_content_differs）、
    # 単価のラベル（他の数え語の候補を主グループの数え語で換算した案は、候補自身のラベルではなく主グループの「1枚あたり」）
    notes: dict = field(default_factory=dict)
    label: str | None = None

    @property
    def confirmed(self) -> bool:
        return not self.reasons


@dataclass
class ToCheck:
    """逆転し得る候補（確認済みの最安より注文額が安いが確認済みでない注文案）とその条件。"""
    plan: OrderPlan
    conditions: list[dict]            # [{"reason": 理由の語, "text": 条件の文, "threshold": 数値 or None}]


@dataclass
class ComparisonGroup:
    basis: str                        # "ml" "g" "m" "W" "mAh" "Wh" "個"
    dimension: str                    # volume / mass / length / power / charge / energy / count
    offers: list[Offer]               # 単位価格の安い順（算出不能は末尾）
    count_unit: str | None = None     # 数え語（basis が個の時だけ。本・袋・枚…。WP14 W3）
    cheapest_unit_price: Offer | None = None
    order_plans: list[OrderPlan] = field(default_factory=list)
    cheapest_order: OrderPlan | None = None
    to_check: list[ToCheck] = field(default_factory=list)


@dataclass
class Comparison:
    basis: str
    basis_label: str
    groups: list[ComparisonGroup]
    unknown_offers: list[Offer]       # basis の量が読めない候補（単価なし）
    cheapest_price: Offer | None
    cheapest_unit_price: Offer | None
    cheapest_total: Offer | None
    cheapest_for_quantity: Offer | None
    caveats: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # WP14 W2: 希望量を注文する組み合わせ（グループが1つの時だけ最上位に出る。複数ある時は groups[] の中）
    order_plans: list[OrderPlan] = field(default_factory=list)
    cheapest_order: OrderPlan | None = None
    to_check: list[ToCheck] = field(default_factory=list)
    main_count_unit: str | None = None       # 最上位の最安・注文を出した主グループの数え語（basis が個以外は None）


def total_price(offer: Offer) -> int | None:
    """included→price、separate かつ fee あり→price+fee、他は None。"""
    if offer.price is None:
        return None
    if offer.shipping_status == "included":
        return offer.price
    if offer.shipping_status == "separate" and offer.shipping_fee is not None:
        return offer.price + offer.shipping_fee
    return None


def _terms(value) -> list[str]:
    if value is None:
        return []
    items = [value] if isinstance(value, str) else list(value)
    return [t for t in (_norm(x).strip() for x in items if isinstance(x, str)) if t]


def _is_digit(c: str) -> bool:
    return "0" <= c <= "9"


def _blocked_before(name: str, i: int) -> bool:
    """name[i] の直前が数字、または小数点・千区切りで数字につながっている（別の数の途中）か。"""
    if i == 0:
        return False
    prev = name[i - 1]
    return _is_digit(prev) or (prev in ".," and i > 1 and _is_digit(name[i - 2]))


def _blocked_after(name: str, j: int) -> bool:
    """name[j] 以降が数字、または小数点（＋数字）・千区切り（,ddd）で続く（別の数の途中）か。"""
    if j >= len(name):
        return False
    nxt = name[j]
    if _is_digit(nxt):
        return True
    if nxt == "." and j + 1 < len(name):
        return _is_digit(name[j + 1])
    if nxt == ",":
        tail = name[j + 1:j + 4]
        return len(tail) == 3 and tail.isascii() and tail.isdigit()
    return False


def term_in_name(term: str, name: str) -> bool:
    """正規化済みの語が正規化済みの商品名に含まれるか。語が数字で始まる/終わる時は、その前/後ろに数字や
    小数点・千区切りが続く位置（別の数の途中）には一致させない（2L は 12L・1.2L に、500mAh は 1500mAh に
    一致しない。S7・W5）。"""
    start = 0
    while True:
        i = name.find(term, start)
        if i < 0:
            return False
        j = i + len(term)
        if not ((_is_digit(term[0]) and _blocked_before(name, i))
                or (_is_digit(term[-1]) and _blocked_after(name, j))):
            return True
        start = i + 1


def filter_by_terms(offers: list[Offer], include_terms=None, exclude_terms=None
                    ) -> tuple[list[Offer], list[str]]:
    """語による絞り込み（商品名で判定。含む語 → 除く語の順）。(残った候補, 外した件数の notes)。
    比較（compare）と一覧（search）で同じ実装を使う。"""
    kept = list(offers)
    notes: list[str] = []
    inc, exc = _terms(include_terms), _terms(exclude_terms)
    if inc:
        after = [o for o in kept if all(term_in_name(t, _norm(o.item_name)) for t in inc)]
        if len(kept) != len(after):
            notes.append(f"含む語で除外: {len(kept) - len(after)}件")
        kept = after
    if exc:
        after = [o for o in kept if not any(term_in_name(t, _norm(o.item_name)) for t in exc)]
        if len(kept) != len(after):
            notes.append(f"除く語で除外: {len(kept) - len(after)}件")
        kept = after
    return kept, notes


def _amount(offer: Offer, dimension: str):
    """basis の次元での量（count なら個数、それ以外は内容量×個数）。読めない/high でなければ None。
    名前に複数の次元が書かれていれば、basis の次元の内容量を使う（先頭の次元とは限らない。S5）。"""
    q = offer.quantity
    if q is None or q.confidence != "high":
        return None
    if dimension == "count":
        amount = q.count_total
    elif q.content_dimension == dimension:
        amount = q.measure_total
    else:
        per = (q.content_amounts or {}).get(dimension)
        amount = None if per is None or q.count_total is None else round(per * q.count_total, 9)
    return amount if amount is not None and amount > 0 else None


def _auto_basis(offers: list[Offer]) -> tuple[str, str]:
    high = [o for o in offers if o.quantity is not None and o.quantity.confidence == "high"]
    # 内容量の次元は題名から読めたものだけで数える（説明欄の見出し `長さ` で補った内容量〔title+caption〕は数えない。WP15 段B・Q7）
    dims = Counter(o.quantity.content_dimension for o in high
                   if o.quantity.content_dimension in DISPLAY and o.quantity.source != "title+caption")
    if dims:
        dim, n = dims.most_common(1)[0]
        if n * 2 > len(high):
            return base_unit(dim), dim
    return "個", "count"


def mark_unit_price_outliers(members: list[Offer]) -> list[Offer]:
    """単位価格が出ている候補（同じ比較グループ）のうち、中央値の 1/OUTLIER_RATIO 未満のものに
    unit_price_outlier を立てて返す。件数が OUTLIER_MIN_GROUP 未満なら何もしない。判定の実装はここだけ
    （表示側は印を出すだけ）。高すぎる側は最安の誤りにならないので扱わない。"""
    ranked = [o for o in members if o.unit_price is not None and not o.unit_price_outlier]
    if len(ranked) < OUTLIER_MIN_GROUP:
        return []
    limit = median(o.unit_price for o in ranked) / OUTLIER_RATIO
    flagged = [o for o in ranked if o.unit_price < limit]
    for o in flagged:
        o.unit_price_outlier = True
    return flagged


# ---- 希望量を注文する組み合わせ（WP14 W2。SPEC §8） ----

SHIPPING_LINE_CAVEAT = ("送料無料ライン（3,980円など）は仮定していません。送料別・送料不明の候補は、注文額がそのラインを超えても"
                        "送料込みにしていません（ラインを超えても送料がかかる商品がある: 楽天公式 FAQ "
                        "https://ichiba.faq.rakuten.net/detail/000013788 ）。送料額・発送目安は API に無いので商品ページで確認してください。")
CAPTION_NOTE = "題名から数量が読めず、説明欄の見出し付きの記述から補完した数量。確認済みではない"
MEASURE_NOTE = "題名の個数に、説明欄の見出し『長さ』の値を1個あたりの内容量として重ねた。確認済みではない"


def _qty_label(o: Offer) -> str:
    q = o.quantity
    if q is None or q.count_total is None:
        return ""
    return f"{format_amount(q.count_total)}{q.count_unit}"          # 内容量は付けない（10枚×0.096m のような読み取りの癖を条件文に持ち込まない）


def _assumed_reasons(reasons: list[str]) -> list[str]:
    """換算の仮定を置いた案の理由（counter_basis.py）。数量が読めない（quantity_unknown）は仮定で置き換え、送料の理由の前に counter_assumed を入れる。"""
    base = [r for r in reasons if r != "quantity_unknown"]
    ship = [r for r in base if r in _SHIPPING_REASONS]
    return [r for r in base if r not in _SHIPPING_REASONS] + ["counter_assumed"] + ship


def _order_plan(o: Offer, amount: float, mult: float, desired: float, desired_max: float | None,
                count_unit: str | None, *, assumed: str | None = None, notes: dict | None = None,
                label: str | None = None) -> tuple[OrderPlan | None, str | None]:
    """候補 o を同じ商品で n 個注文する案。(案, 除外理由 "range" / None)。比は丸めてから切り上げる
    （0.9 ÷ 0.3 = 3.0000000000000004 で n を 4 にしない）。注文個数に上限は置かない（出典が無い。注文額の最安が選ぶ）。"""
    n = max(1, math.ceil(round(desired / amount, 9)))
    quantity = round(n * amount, 9)
    if desired_max is not None and quantity > round(desired_max, 9):
        return None, "range"
    total = n * o.price
    if o.shipping_status == "separate" and o.shipping_fee is not None:
        total += o.shipping_fee                     # 送料額が分かる時だけ（楽天の検索 API では常に不明）。1 注文に 1 回
    reasons = unconfirmed_reasons(o, shipping=True)
    notes = dict(notes or {})
    if assumed:                                     # 換算の仮定つき（to_check にだけ出す案。counter_basis.py）
        reasons = _assumed_reasons(reasons)
        notes["counter_assumed"] = assumed
    return OrderPlan(offer=o, n=n, order_quantity=quantity, order_total=total,
                     order_unit_price=total * mult / quantity, shipping_status=o.shipping_status,
                     reasons=reasons, count_unit=count_unit, notes=notes, label=label), None


def _unit_raw(p: OrderPlan) -> float:
    """注文の単価（円 / 基準単位 1。表示倍率を掛ける前）。範囲指定の最安の比較に使う（WP14 B1）。"""
    return p.order_total / p.order_quantity


_MONEY = ("shipping_separate", "shipping_unknown", "price_varies")


def _conditions(plan: OrderPlan, best: OrderPlan | None, by_unit: bool = False) -> list[dict]:
    """確認済みでない理由から「こうなら逆転する」条件を 1 つの文にまとめる（WP14 B3）。best は確認済みの最安の注文案（無ければ None）。
    金額に関わる理由（送料別・不明／選択肢で価格が変わる）は合算の条件にする: この案の（選択肢の価格×n＋送料）が X 円未満なら安い。
    X は、量を指定した時は best の注文額、範囲指定（by_unit）の時は best の注文の単価をこの案の注文量に換算した額。
    説明欄由来・題名との食い違い・外れ値は「〜が正しければ」を前置きする。条件は 1 つの dict（reason は理由を + でつなぐ）。"""
    o, q = plan.offer, plan.offer.quantity
    ev = getattr(q, "caption_evidence", None) or ""
    money = [r for r in plan.reasons if r in _MONEY]
    pre: list[str] = []
    for r in plan.reasons:
        if r == "caption_conflict":
            pre.append(f"題名の数量と説明欄『{ev}』の数量のどちらが正しいか商品ページで確認し、")
        elif r == "quantity_from_caption":
            pre.append(f"説明欄『{ev}』の数量が正しければ（{CAPTION_NOTE}）、")
        elif r == "measure_from_caption":
            pre.append(f"説明欄『{ev}』の内容量が正しければ（{MEASURE_NOTE}）、")
        elif r == "counter_assumed":
            pre.append(f"{plan.notes.get(r, '')}、")
        elif r == "pack_content_differs":
            pre.append(plan.notes.get(r, "1袋の中身が違う。"))
        elif r == "unit_price_outlier":
            pre.append(f"{OUTLIER_NOTE}。数量が正しければ、")
    # 逆転できる上限額 X（この案の総額が X 円未満なら確認済みの最安より安い）
    limit = None
    if best is not None:
        # 比で丸める（浮動小数の誤差で整数が +ε になり ceil が 1 円ずれるのを防ぐ。n の計算と同じ流儀）
        limit = round(_unit_raw(best) * plan.order_quantity, 9) if by_unit else best.order_total
        if limit <= plan.order_total:
            limit = None
    threshold = None
    body = ""
    if money:
        label = _qty_label(o)
        has_ship = any(r.startswith("shipping") for r in money)
        has_var = "price_varies" in money
        kind = "送料別" if "shipping_separate" in money else "送料不明"
        basis_txt = "（単価換算: 確認済みの最安の注文の単価 × この案の注文量）" if by_unit else ""
        if limit is not None:
            x = math.ceil(limit)
            if has_ship and has_var:
                threshold = x
                body = (f"商品名の数量（{label}）の選択肢の価格×{plan.n}個＋送料の合計が {x:,}円未満ならこちらが安い{basis_txt}"
                        f"（{kind}。価格幅 {o.price_min:,}〜{o.price_max:,}円・表示価格 {o.price:,}円は最小の選択肢の価格。送料額は API に無いので商品ページで確認）")
            elif has_ship:
                threshold = x - plan.order_total
                body = (f"{kind}。注文全体の送料が {threshold:,}円未満ならこちらが安い（{plan.n}個で商品代 {plan.order_total:,}円。"
                        f"送料額は API に無いので商品ページで確認）{basis_txt}")
            else:
                threshold = max(x - 1, 0) // plan.n if not by_unit else math.ceil(limit / plan.n) - 1
                body = (f"商品名の数量（{label}）の選択肢の価格が {threshold:,}円以下ならこちらが安い{basis_txt}"
                        f"（価格幅 {o.price_min:,}〜{o.price_max:,}円。表示価格 {o.price:,}円は最小の選択肢の価格）")
        else:
            if has_ship and has_var:
                body = f"{kind}で選択肢の価格も変わる。商品名の数量（{label}）の選択肢の価格と送料が確定すれば確認済みになる（価格幅 {o.price_min:,}〜{o.price_max:,}円）"
            elif has_ship:
                body = f"{kind}。送料が確定すれば確認済みになる（送料額は API に無いので商品ページで確認）"
            else:
                body = f"商品名の数量（{label}）の選択肢の価格が確認できれば確認済みになる（価格幅 {o.price_min:,}〜{o.price_max:,}円）"
    if money:
        text = "".join(pre) + body
    else:                                         # 金額に関わる理由が無い時は、それぞれ単独の文
        alone = {"caption_conflict": f"題名の数量と説明欄『{ev}』の数量が食い違う。どちらが正しいか商品ページで確認"
                                     "（説明欄が 1 パックあたりの記述のこともある）",
                 "quantity_from_caption": f"説明欄『{ev}』の数量が正しければ（{CAPTION_NOTE}）",
                 "measure_from_caption": f"説明欄『{ev}』の内容量が正しければ（{MEASURE_NOTE}）",
                 "counter_assumed": f"{plan.notes.get('counter_assumed', '')}、この商品を{plan.n}個注文すると "
                                    f"{format_amount(plan.order_quantity)}{plan.count_unit or ''}相当・{plan.order_total:,}円"
                                    "（換算の仮定。商品ページで確認）",
                 "pack_content_differs": plan.notes.get("pack_content_differs", "1袋の中身が違う。")
                                         + "基準と中身が違うので同じ最安競争にしていない。商品ページで確認",
                 "unit_price_outlier": OUTLIER_NOTE}
        text = "。".join(alone[r] for r in plan.reasons if r in alone)
    if not plan.reasons:
        return []
    return [{"reason": "+".join(plan.reasons), "reasons": list(plan.reasons), "threshold": threshold, "text": text}]


def _cheaper(p: OrderPlan, best: OrderPlan | None, by_unit: bool) -> bool:
    """確認済みの最安 best より安くなり得る案か（best が無ければ全部）。量の指定は注文額、範囲指定は注文の単価（WP14 B1）。"""
    if best is None:
        return True
    return _unit_raw(p) < _unit_raw(best) if by_unit else p.order_total < best.order_total


def _plan_order(by_unit: bool):
    """案の並び（量の指定は注文額・単価・コード、範囲指定は注文の単価・注文額・コード）。"""
    if by_unit:
        return lambda p: (_unit_raw(p), p.order_total, p.offer.mall_item_code)
    return lambda p: (p.order_total, p.order_unit_price, p.offer.mall_item_code)


def add_assumed_to_check(to_check: list[ToCheck], best: OrderPlan | None, assumptions, mult: float, desired: float,
                         desired_max: float | None, count_unit: str | None, label: str | None) -> list[ToCheck]:
    """換算の仮定つきの候補（counter_basis.Assumption）を to_check に足す（並べ直して返す）。a.keep の候補は必ず出し、
    keep でない候補（basis が個で主グループと違う数え語。basis=数え語 で量が読めない候補。Q19・Q20）は確認済みの最安 best より安くなり得る時だけ出す。
    cheapest_order・order_plans には入れない。"""
    by_unit = desired_max is not None
    key = _plan_order(by_unit)
    per_offer: dict[int, list[OrderPlan]] = {}            # 1 つの候補に仮定が複数ある時（low の題名の読みが複数）は、出せる案のうち最安の 1 つだけ
    for a in assumptions:
        plan, _ = _order_plan(a.offer, a.amount, mult, desired, desired_max, count_unit, assumed=a.text, label=label)
        if plan is not None and (a.keep or _cheaper(plan, best, by_unit)):
            per_offer.setdefault(id(a.offer), []).append(plan)
    extra = [ToCheck(p, _conditions(p, best, by_unit)) for p in (min(ps, key=key) for ps in per_offer.values())]
    return sorted(to_check + extra, key=lambda t: key(t.plan))


def build_order_section(members: list[Offer], amounts: dict[int, float], mult: float, desired: float,
                        desired_max: float | None, count_unit: str | None = None, notes: dict | None = None):
    """members（単位の量が読めた候補）から注文案・確認済みの最安・逆転し得る候補を作る。
    量を指定した時（上限なし）は注文額が最小の案、範囲指定（上限あり）の時は注文の単価（注文額÷注文量）が最小の案を選ぶ
    （同じなら注文額が小さい方。WP14 B1）。(plans, cheapest_order, to_check, 範囲外の件数) を返す。"""
    by_unit = desired_max is not None
    plans: list[OrderPlan] = []
    out_of_range = 0
    for o in members:
        if o.price is None:
            continue
        plan, skipped = _order_plan(o, amounts[id(o)], mult, desired, desired_max, count_unit,
                                    notes=(notes or {}).get(id(o)))
        if plan is not None:
            plans.append(plan)
        else:
            out_of_range += 1
    plans.sort(key=_plan_order(by_unit))
    best = next((p for p in plans if p.confirmed), None)
    to_check = [ToCheck(p, _conditions(p, best, by_unit)) for p in plans if not p.confirmed and _cheaper(p, best, by_unit)]
    return plans, best, to_check, out_of_range


def _group_caveats(plans: list[OrderPlan], best: OrderPlan | None, name: str,
                   desired: float, desired_max: float | None, out_of_range: int) -> list[str]:
    """希望量を指定した時のグループ（または全体）の caveats。"""
    out: list[str] = []
    rng = f"{format_amount(desired)}{name} 以上" + (f"・{format_amount(desired_max)}{name} 以下" if desired_max is not None else "")
    if not plans:
        out.append(f"必要数量 {rng}を満たす注文の組み合わせがない")
    elif best is None:
        parts = Counter(r for p in plans for r in p.reasons)
        label = {"shipping_separate": "送料別", "shipping_unknown": "送料不明", "price_varies": "選択肢で価格が変わる",
                 "unit_price_outlier": "数量の読み違いの疑い", "quantity_from_caption": "説明欄から補完した数量",
                 "caption_conflict": "題名と説明欄の数量が食い違う", "measure_from_caption": "説明欄から補った内容量",
                 "counter_assumed": "数え語の換算を仮定", "pack_content_differs": "1袋の中身が違う"}
        detail = "・".join(f"{label[k]} {v}件" for k, v in parts.items() if k in label)
        out.append(f"確認済み（数量が商品名から読め・価格が選択肢で変わらず・外れ値でなく・送料込み）の注文の候補がない"
                   f"（足りない条件: {detail}）。to_check に条件付きの候補を安い順に出した")
    if out_of_range:
        out.append(f"希望量の上限（{format_amount(desired_max)}{name}）を超える注文になる候補は除いた: {out_of_range}件")
    return out


COUNT_GROUP_CAVEAT = ("数え方の違う候補（{others}）は比べていません。最上位の cheapest_unit_price・cheapest_order・to_check は"
                      "主グループ［{main}］（main_count_unit）のもので、他のグループの結果は groups[] の中にあります。"
                      "別の数え方で比べるには basis に数え語（本・袋・枚・ロールなど）を指定してください（MCP・CLI）")


def _main_group(groups: list[ComparisonGroup], by_unit: bool = False) -> ComparisonGroup | None:
    """複数の数え語グループがある時の主グループ（WP14 W3 の改訂）。単位価格が出た候補の数が最多、同数なら確認済みの候補が多い方、
    さらに同じなら最安の注文額（希望量が無ければ商品価格の最安）が安い方（それも同じなら数え語の順）。グループが 1 つならそれ。"""
    if not groups:
        return None

    def key(g: ComparisonGroup):
        ranked = [o for o in g.offers if o.unit_price is not None]
        prices = [o.price for o in g.offers if o.price is not None]
        cheapest = ((_unit_raw(g.cheapest_order) if by_unit else g.cheapest_order.order_total)
                    if g.cheapest_order else (min(prices) if prices else 10**12))
        return (-len(ranked), -sum(1 for o in ranked if is_confirmed(o)), cheapest, g.count_unit or "")
    return min(groups, key=key)


def _split_groups(members: list[Offer], name: str, dim: str, counter: str | None = None) -> list[ComparisonGroup]:
    """単位価格の出た候補を比較グループに分ける（WP14 W3）。basis が個（数える）の時は数え語（count_unit）ごと
    （本・袋・枚・ロール・個…を同じ単価順に並べない）。大きいグループが先。ほかの次元は次元ごとに 1 つ。
    basis に数え語を指定した時は 1 つ（count_unit がその数え語の候補と packs にその数え語がある候補を同じグループで比べる。WP15 段B）。"""
    if not members:
        return []
    if counter:
        return [ComparisonGroup(basis=name, dimension=dim, offers=members, count_unit=counter)]
    if dim != "count":
        return [ComparisonGroup(basis=name, dimension=dim, offers=members)]
    by: dict[str, list[Offer]] = {}
    for o in members:
        by.setdefault(o.quantity.count_unit, []).append(o)
    return [ComparisonGroup(basis=name, dimension=dim, offers=by[u], count_unit=u)
            for u in sorted(by, key=lambda u: (-len(by[u]), u))]


def compare(offers: list[Offer], include_terms=None, exclude_terms=None,
            desired_quantity=None, basis: str | None = None, desired_quantity_max=None) -> Comparison:
    check_desired_range(desired_quantity, desired_quantity_max)   # 検査の実装は inputs に一本化（不正なら InvalidInput＝ValueError）
    fixed3 = resolve_compare_basis(basis) if basis not in (None, "") else None   # 不正なら ValueError。数え語の指定（本・袋…）も通る
    fixed = fixed3[:2] if fixed3 else None
    counter = fixed3[2] if fixed3 else None            # basis に数え語を指定した時、その数え語の候補だけで比べる（WP14 W3）
    caveats: list[str] = []
    notes: list[str] = []

    # 語による絞り込み（商品名で判定。含む語 → 除く語の順）
    candidates, term_notes = filter_by_terms(offers, include_terms, exclude_terms)
    notes.extend(term_notes)

    for o in candidates:
        if o.quantity is None:
            o.quantity = read_offer_quantity(o)
        o.unit_price = None
        o.unit_price_label = None
        o.unit_price_dimension = None
        o.unit_price_outlier = False
        o.pack_content_differs = False

    name, dim = fixed if fixed else _auto_basis(candidates)
    mult, label = DISPLAY[dim]
    if counter:
        label = f"1{counter}あたり"

    members: list[Offer] = []
    unknown: list[Offer] = []
    other_unit: list[Offer] = []
    pack_offers: list[Offer] = []                       # basis=数え語 で packs の数を使う候補（counter_basis (b)）
    others: list[Offer] = []                            # basis=数え語 で (a)(b) に入らない候補（換算の仮定つきで to_check に残す）
    amounts: dict[int, float] = {}
    for o in candidates:
        amount = _amount(o, dim)
        if counter:
            kind = counter_basis.counted_as(o, counter)
            if kind == "pack":
                amount = float(counter_basis.pack_of(o, counter)["count"])
                pack_offers.append(o)
            elif kind is None:
                others.append(o)
                if amount is not None:
                    other_unit.append(o)               # 数え語が違う（本を指定したのに袋）。単価を出さず、比べない
                amount = None
        if amount is None:
            unknown.append(o)
            continue
        amounts[id(o)] = amount
        if o.price is not None:
            o.unit_price = o.price * mult / amount
            o.unit_price_label = label
            o.unit_price_dimension = dim
        members.append(o)
    members.sort(key=lambda o: (o.unit_price is None, o.unit_price or 0.0,
                                o.price if o.price is not None else 10**12, o.mall_item_code))
    pack_notes: dict[int, dict] = {}
    base = counter_basis.choose_base(pack_offers, counter, desired_quantity,
                                     lambda o: not unconfirmed_reasons(o)) if counter else None
    n_base = counter_basis.base_count(pack_offers, counter, base) if base else 0
    for o in pack_offers:                               # 1袋の中身が基準と食い違う候補は確認済みにしない（pack_content_differs）
        if counter_basis.content_key(counter_basis.pack_of(o, counter)) != base:
            o.pack_content_differs = True
            pack_notes[id(o)] = {"pack_content_differs": counter_basis.differs_text(o, counter, base, n_base)}
    assumptions: list[counter_basis.Assumption] = []
    assume_why: str | None = None
    if counter and desired_quantity is not None:
        assumptions, assume_why = counter_basis.assume_for_counter(others, pack_offers, counter)
    groups = _split_groups(members, name, dim, counter)
    outliers = [o for g in groups for o in mark_unit_price_outliers(g.offers)]      # 外れ値は数え語のグループの中で判定する

    priced = [o for o in candidates if o.price is not None]
    if len(priced) != len(candidates):
        caveats.append(f"価格が不明な候補 {len(candidates) - len(priced)} 件は順位付けから外した")
    if not candidates:
        caveats.append("比較できる候補がない")
    if unknown:
        caveats.append(f"単価を出せない候補: {len(unknown)}件（比べる単位 {name} の量を商品名から"
                       "確定できないため、単位価格の最安の判定から外した）")
    other_unit_slot = len(caveats)                       # 件数は to_check が決まってから入れる（換算の仮定つきで出した候補は数えない）
    caveats.append("")
    if pack_offers and base:
        caveats.append(counter_basis.base_caveat(counter, base, n_base, len(pack_offers)))
    if outliers:
        caveats.append(f"単価が他の候補の 1/{OUTLIER_RATIO} 未満で、数量の読み違いの疑いがある候補: "
                       f"{len(outliers)}件（単位価格の最安・必要数量を満たす最安から外しています）")
    varies = [o for o in members if o.price_varies]
    if varies:
        caveats.append(f"選択肢によって価格が変わる候補: {len(varies)}件（表示価格が商品名の数量の選択肢の価格とは"
                       "限らないため、単位価格・注文の最安から外した）")

    from_caption = [o for o in members if o.quantity.source == "caption"]
    if from_caption:
        caveats.append(f"数量を説明欄の見出し付きの記述から補った候補: {len(from_caption)}件（題名から数量が読めなかった候補。"
                       "確認済みではないので、単位価格・注文の最安には選ばず、安い時は to_check に条件つきで出した）")
    measured = [o for o in members if o.quantity.source == "title+caption" and o.unit_price_dimension == o.quantity.content_dimension]
    if measured:
        caveats.append(f"内容量を説明欄の見出し『長さ』から補った候補: {len(measured)}件（題名の個数は確認済みのままだが、"
                       f"{name} あたりの単価は補った内容量を使うので仮。最安には選ばず、安い時は to_check に条件つきで出した）")
    hinted = [o for o in unknown if o.quantity.caption_candidate is not None]
    if hinted:
        caveats.append(f"題名から数量が読めず、説明欄の見出し付きの記述に数量がある候補: {len(hinted)}件（印と根拠だけで、"
                       "単価・注文案には使っていない。各候補の quantity.caption_candidate・caption_evidence を商品ページで確認）")
    conflicting = [o for o in candidates if o.quantity.caption_conflict]
    if conflicting:
        caveats.append(f"題名の数量と説明欄の見出し付きの数量が食い違う候補: {len(conflicting)}件"
                       "（各候補の quantity.caption_conflict・caption_evidence。説明欄が単位あたりの記述のこともあるので商品ページで確認）")

    cheapest_price = min(priced, key=lambda o: (o.price, o.mall_item_code)) if priced else None

    unknown_ship = [o for o in priced if total_price(o) is None]
    if unknown_ship:
        cheapest_total = None
        caveats.append(f"送料が不明な候補が {len(unknown_ship)} 件あるため、"
                       "支払総額の最安は断定できない")
    else:
        cheapest_total = min(priced, key=lambda o: (total_price(o), o.mall_item_code))             if priced else None

    # グループごとの最安・注文の組み合わせ（WP14）
    desired_caveats: list[str] = []
    for g in groups:
        ranked = [o for o in g.offers if o.unit_price is not None and is_confirmed(o)]
        g.cheapest_unit_price = min(ranked, key=lambda o: (o.unit_price, o.price, o.mall_item_code))             if ranked else None
        if desired_quantity is not None:
            plans, best, to_check, out_of_range = build_order_section(
                g.offers, amounts, mult, desired_quantity, desired_quantity_max, g.count_unit, pack_notes)
            if counter:
                to_check = add_assumed_to_check(to_check, best, assumptions, mult, desired_quantity, desired_quantity_max,
                                                counter, label)
            g.order_plans, g.cheapest_order, g.to_check = plans, best, to_check
            desired_caveats += [(f"［{g.count_unit}］" if len(groups) > 1 else "") + c
                                for c in _group_caveats(plans, best, g.count_unit or name, desired_quantity,
                                                        desired_quantity_max, out_of_range)]
    if desired_quantity is not None:
        if not groups:
            desired_caveats.append(f"必要数量 {format_amount(desired_quantity)}{name} 以上を満たす注文の組み合わせがない")
        if unknown:
            desired_caveats.append("量を読み取れない候補は必要数量の判定に使っていない")
        if any({"shipping_separate", "shipping_unknown"} & set(p.reasons) for g in groups for p in g.order_plans):
            desired_caveats.append(SHIPPING_LINE_CAVEAT)
    caveats.extend(desired_caveats)

    only = _main_group(groups, desired_quantity_max is not None)
    if only is not None and groups[0] is not only:
        groups.remove(only)
        groups.insert(0, only)                 # 主グループが groups の先頭（Q19）
    if len(groups) > 1:
        caveats.append(COUNT_GROUP_CAVEAT.format(
            main=only.count_unit, others="・".join(f"{g.count_unit} {len(g.offers)}件" for g in groups if g is not only)))
        if desired_quantity is not None:
            rng = format_amount(desired_quantity) + (f"〜{format_amount(desired_quantity_max)}" if desired_quantity_max is not None else "")
            others = [g.count_unit for g in groups if g is not only and g.count_unit != "個"]      # basis の「個」は全数え語の意味なので勧めない
            hint = f"{others[0]}で数えるなら basis={others[0]} を指定してください" if others else "別の数え方なら basis に数え語を指定してください"
            caveats.append(f"希望量 {rng} は主グループの数え方［{only.count_unit}］として扱いました（他のグループにも同じ数を当てた結果は groups[] の中）。{hint}")
    cross_unit: list[counter_basis.Assumption] = []
    if dim == "count" and not counter and len(groups) > 1 and desired_quantity is not None and only is not None:
        # basis が個で数え語が複数: 主グループと違う数え語の候補は、確認済みの横断比較はせず、主グループの to_check に
        # 「1個が1枚なら」の条件つきで出す（WP15 段B・Q19）
        cross_unit = counter_basis.assume_for_main([o for g in groups if g is not only for o in g.offers], only.count_unit)
        only.to_check = add_assumed_to_check(only.to_check, only.cheapest_order, cross_unit, mult, desired_quantity,
                                             desired_quantity_max, only.count_unit, f"1{only.count_unit}あたり")
    top_to_check = only.to_check if only else []
    if only is None and assumptions:           # 比べられる候補（グループ）が無くても、換算の仮定つきの候補は最上位の to_check に出す
        top_to_check = add_assumed_to_check([], None, assumptions, mult, desired_quantity, desired_quantity_max, counter, label)
    placed = {id(t.plan.offer) for t in top_to_check} | {id(t.plan.offer) for g in groups for t in g.to_check}   # 換算の仮定つきで出した候補（WP15 段B）
    other_unit = [o for o in other_unit if id(o) not in placed]
    if other_unit:
        caveats[other_unit_slot] = (f"数え語が {counter} でない候補: {len(other_unit)}件"
                                    f"（比べる単位 {counter} の量を持たないので単価を出していない）")
    else:
        del caveats[other_unit_slot]
    dropped = [a.offer for a in assumptions if not a.keep and id(a.offer) not in placed]
    if dropped:                                  # 量が読めず、1点＝1数え語 の仮定でも確認済みの最安より安くなり得ない候補（unknown_offers に残す。WP15 段B・Q20）
        caveats.append(f"数量が商品名から読めず、仮定（この商品1点が1{counter}なら・題名の個数の読みが1{counter}なら）でも確認済みの最安より安くなり得ない候補: "
                       f"{len(dropped)}件（to_check には出さず unknown_offers に残した）")
    for items, why in ((assumptions, assume_why), (cross_unit, None)):
        text = counter_basis.caveat([a for a in items if id(a.offer) in placed], counter or (only.count_unit if only else ""), why)
        if text:
            caveats.append(text)
    meeting = only.cheapest_order.offer if only is not None and only.cheapest_order is not None else None

    caveats.append(SPEC_CAVEAT)
    caveats.append(QUANTITY_CAVEAT)
    return Comparison(basis=name, basis_label=label, groups=groups, unknown_offers=unknown,
                      cheapest_price=cheapest_price,
                      cheapest_unit_price=only.cheapest_unit_price if only else None,
                      cheapest_total=cheapest_total, cheapest_for_quantity=meeting,
                      caveats=caveats, notes=notes,
                      order_plans=only.order_plans if only else [],
                      cheapest_order=only.cheapest_order if only else None,
                      to_check=top_to_check,
                      main_count_unit=only.count_unit if only else None)
