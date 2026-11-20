# @owns 語による絞り込み・基準単位あたりの単価・支払総額・最安判定（比較グループ分け・断定できない理由の明示）
"""価格比較。商品の意味（仕様の違い）は判定しない。読み取った数量（個数×内容量）から、
指定または自動で決めた基準（basis）あたりの単価を出し、送料不明のときは総額最安を断定しない。"""
from __future__ import annotations

from collections import Counter
from statistics import median
from dataclasses import dataclass, field

from .inputs import check_desired_quantity
from .models import Offer
from .quantity import DISPLAY, _norm, base_unit, format_amount, parse_quantity, resolve_basis

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
    確認済み＝数量が商品名から high ∧ 選択肢で価格が変わらない ∧ 外れ値でない（∧ shipping=True の時は送料が確定）。
    理由の語: quantity_unknown / price_varies / unit_price_outlier / quantity_from_caption / shipping_separate / shipping_unknown。"""
    reasons: list[str] = []
    q = o.quantity
    if q is None or q.confidence != "high":
        reasons.append("quantity_unknown")
    elif getattr(q, "source", "title") != "title":
        reasons.append("quantity_from_caption")
    if o.price_varies:
        reasons.append("price_varies")
    if o.unit_price_outlier:
        reasons.append("unit_price_outlier")
    if shipping and total_price(o) is None:
        reasons.append("shipping_separate" if o.shipping_status == "separate" else "shipping_unknown")
    return reasons


def is_confirmed(o: Offer, *, shipping: bool = False) -> bool:
    return not unconfirmed_reasons(o, shipping=shipping)


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
class ComparisonGroup:
    basis: str                        # "ml" "g" "m" "W" "mAh" "Wh" "個"
    dimension: str                    # volume / mass / length / power / charge / energy / count
    offers: list[Offer]               # 単位価格の安い順（算出不能は末尾）


@dataclass
class Comparison:
    basis: str
    basis_label: str
    groups: list[ComparisonGroup]
    unknown_offers: list[Offer]       # basis の量が読めない候補（単位価格なし）
    cheapest_price: Offer | None
    cheapest_unit_price: Offer | None
    cheapest_total: Offer | None
    cheapest_for_quantity: Offer | None
    caveats: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


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
    dims = Counter(o.quantity.content_dimension for o in high
                   if o.quantity.content_dimension in DISPLAY)
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


def compare(offers: list[Offer], include_terms=None, exclude_terms=None,
            desired_quantity=None, basis: str | None = None) -> Comparison:
    check_desired_quantity(desired_quantity)       # 検査の実装は inputs に一本化（不正なら InvalidInput＝ValueError）
    fixed = resolve_basis(basis) if basis not in (None, "") else None   # 不正なら ValueError
    caveats: list[str] = []
    notes: list[str] = []

    # 語による絞り込み（商品名で判定。含む語 → 除く語の順）
    candidates, term_notes = filter_by_terms(offers, include_terms, exclude_terms)
    notes.extend(term_notes)

    for o in candidates:
        if o.quantity is None:
            o.quantity = parse_quantity(o.item_name)
        o.unit_price = None
        o.unit_price_label = None
        o.unit_price_dimension = None
        o.unit_price_outlier = False

    name, dim = fixed if fixed else _auto_basis(candidates)
    mult, label = DISPLAY[dim]

    members: list[Offer] = []
    unknown: list[Offer] = []
    amounts: dict[int, float] = {}
    for o in candidates:
        amount = _amount(o, dim)
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
    outliers = mark_unit_price_outliers(members)
    groups = [ComparisonGroup(basis=name, dimension=dim, offers=members)] if members else []

    priced = [o for o in candidates if o.price is not None]
    if len(priced) != len(candidates):
        caveats.append(f"価格が不明な候補 {len(candidates) - len(priced)} 件は順位付けから外した")
    if not candidates:
        caveats.append("比較できる候補がない")
    if unknown:
        caveats.append(f"単価を出せない候補: {len(unknown)}件（比べる単位 {name} の量を商品名から"
                       "確定できないため、単位価格の最安の判定から外した）")
    if outliers:
        caveats.append(f"単価が他の候補の 1/{OUTLIER_RATIO} 未満で、数量の読み違いの疑いがある候補: "
                       f"{len(outliers)}件（単位価格の最安・必要数量を満たす最安から外しています）")

    varies = [o for o in members if o.price_varies]
    if varies:
        caveats.append(f"選択肢によって価格が変わる候補: {len(varies)}件（表示価格が商品名の数量の選択肢の価格とは"
                       "限らないため、単位価格・注文の最安から外した）")

    cheapest_price = min(priced, key=lambda o: (o.price, o.mall_item_code)) if priced else None
    ranked = [o for o in members if o.unit_price is not None and is_confirmed(o)]
    cheapest_unit = min(ranked, key=lambda o: (o.unit_price, o.price, o.mall_item_code)) \
        if ranked else None

    unknown_ship = [o for o in priced if total_price(o) is None]
    if unknown_ship:
        cheapest_total = None
        caveats.append(f"送料が不明な候補が {len(unknown_ship)} 件あるため、"
                       "支払総額の最安は断定できない")
    else:
        cheapest_total = min(priced, key=lambda o: (total_price(o), o.mall_item_code)) \
            if priced else None

    meeting = None
    if desired_quantity is not None:
        ok = [o for o in members if o.price is not None and is_confirmed(o)
              and amounts[id(o)] >= desired_quantity]
        if ok:
            meeting = min(ok, key=lambda o: (o.price, o.unit_price, o.mall_item_code))
            if total_price(meeting) is None:
                caveats.append("必要数量を満たす最安は商品価格ベースで、送料は含まない（送料不明）")
        else:
            excluded = any(o.unit_price_outlier and amounts[id(o)] >= desired_quantity for o in members)
            caveats.append(f"必要数量 {format_amount(desired_quantity)}{name} 以上を満たす候補がない"
                           + ("（数量の読み違いの疑いで外した候補を除く）" if excluded else ""))
        if unknown:
            caveats.append("量を読み取れない候補は必要数量の判定に使っていない")

    caveats.append(SPEC_CAVEAT)
    caveats.append(QUANTITY_CAVEAT)
    return Comparison(basis=name, basis_label=label, groups=groups, unknown_offers=unknown,
                      cheapest_price=cheapest_price, cheapest_unit_price=cheapest_unit,
                      cheapest_total=cheapest_total, cheapest_for_quantity=meeting,
                      caveats=caveats, notes=notes)
