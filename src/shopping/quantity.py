# @owns 商品名からの数量（個数 × 1個あたり内容量）の読み取り・単位換算表・信頼度判定
"""数量の読み取り。商品の意味（種類・仕様の違い）は持たない。

読むのは「個数」と「1個あたりの内容量（数値＋計量単位）」だけ。単位は表（UNITS / DISPLAY / COUNTERS）で
持ち、表に1行足すだけで増える（単位ごとの if 分岐は書かない）。読めない・矛盾する時は推測で埋めず
total=None にする。
"""
from __future__ import annotations

import functools
import re
import unicodedata
from dataclasses import dataclass, field

from .models import QuantityInfo

# 単位の換算表: 別名 → (次元, 基準単位への係数)。大文字小文字・全角半角は区別せずに引く（NFKC＋casefold。
# 照合キーが同じになる別名は書かない: mL は ml、ℓ は L と同じ。import 時に検査する）。
UNITS: dict[str, tuple[str, float]] = {
    "ml": ("volume", 1), "cc": ("volume", 1),
    "L": ("volume", 1000), "リットル": ("volume", 1000),
    "ミリリットル": ("volume", 1),
    "g": ("mass", 1), "kg": ("mass", 1000), "mg": ("mass", 0.001),
    "グラム": ("mass", 1), "キログラム": ("mass", 1000),
    "m": ("length", 1), "メートル": ("length", 1), "cm": ("length", 0.01), "mm": ("length", 0.001),
    "km": ("length", 1000), "センチメートル": ("length", 0.01), "ミリメートル": ("length", 0.001),
    "W": ("power", 1), "ワット": ("power", 1), "kW": ("power", 1000), "キロワット": ("power", 1000),
    "mAh": ("charge", 1), "Ah": ("charge", 1000),
    "Wh": ("energy", 1), "kWh": ("energy", 1000),
}

# 表示用: 次元 → (単価を出す時の倍率, ラベル)。ラベルの先頭の数字を除いた部分（"ml" 等）が基準単位名。
DISPLAY: dict[str, tuple[float, str]] = {
    "volume": (100, "100mlあたり"),
    "mass": (100, "100gあたり"),
    "length": (1, "1mあたり"),
    "power": (1, "1Wあたり"),
    "charge": (1, "1mAhあたり"),
    "energy": (1, "1Whあたり"),
    "count": (1, "1個あたり"),
}

# 数え語: 別名 → 正規の数え語。（"R" は「ロール」の略）
COUNTERS: dict[str, str] = {
    "個": "個", "本": "本", "枚": "枚", "袋": "袋", "箱": "箱", "パック": "パック", "缶": "缶",
    "ロール": "ロール", "R": "ロール", "roll": "ロール", "rolls": "ロール",
    "セット": "セット", "組": "組", "足": "足", "着": "着", "台": "台", "錠": "錠", "包": "包",
    "粒": "粒", "ケース": "ケース", "玉": "玉", "束": "束", "巻": "巻", "食": "食", "回分": "回分",
    "点": "点", "冊": "冊", "ペア": "ペア", "ヶ": "個", "ダース": "個",
    "P": "パック", "pc": "個", "pcs": "個",
    "コ": "個", "ケ": "個", "膳": "膳",
}

# 数え語の倍率（別名 → 倍）。ダースは 12 個。ただし内側の個数がある時（12本入り 2ダース）は袋数と同じ扱いで倍率を掛けない
COUNT_MULTIPLIERS: dict[str, int] = {"ダース": 12}

# 使用回数・換算の説明であって個数ではない数え語（S1）。計量値や他の個数が名前にある時は数えない
SERVING_WORDS = frozenset({"回分"})

# 「12ロール 4パック」のように空白だけで続けても掛け算にする、入れ物を表す数え語
CONTAINERS = frozenset({"パック", "袋", "セット", "ケース", "梱"})

# P4: 同じ数が続く時に「外側の入れ物」として掛け算にする容器語（3個入り 3セット → 9）
OUTER_WORDS = frozenset({"セット", "ケース", "パック", "箱", "袋"})

# 数え語としての条件が文脈で変わる語（X1）。表の別名（正規化後）で持つ
SOLO_LOW_COUNTERS = frozenset({"P"})           # ×・入数に続かない単独の NP は high にしない（60P 対応）
MAX_PACK_P = 99                                # 単独の P は 1〜99 だけ個数の候補（1080P は画質）。連結位置の P には掛けない（P6）

MAX_PLAUSIBLE_COUNT = 100_000
MAX_DIGITS = 9                      # 数値は千区切りを除いて 9 桁まで（S6）

_FILL = r"(?:入り?|入数|セット|組|パック|袋|箱|ケース|梱|各|の)"
_GAP_X = re.compile(rf"\s*(?:{_FILL}\s*)*[×x*]\s*")
_GAP_LABEL = re.compile(rf"\s*(?:{_FILL}\s*)*[×x*]\s*[^\d×x*\s]{{0,4}}\s*")
_GAP_PLAIN = re.compile(r"\s*(?:(?:入り?|入数|約|各)\s*)*")
# 個数と内容量のあいだ（2枚組 34cm）。数え語の間（_GAP_PLAIN）より読み飛ばす語を広げる
_GAP_COUNT_MEASURE = re.compile(rf"\s*(?:(?:入り?|入数|約|各|セット|組|パック|袋|箱|ケース|梱|の)\s*)*")
# 数値の形。桁数の検査は _tokens 側で行う（9 桁を超える数は数量にせず low。出店者の書いた巨大な数字列で
# float が inf になり int() が落ちる事故も防ぐ）
_NUM = r"(?<![\d.,])\d[\d,]*(?:\.\d+)?"
_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+")
_AFTER_SKIP = re.compile(r"\s*(?:分(?![a-z])|相当|換算|あたり|当たり|当り|につき|ごと|限定|まで|以上|以下|以内|未満|から|ずつ)")
# 「最大700g」。ASCII の MAX1kg は語境界を要し、空白を挟む独立語（Pepsi MAX 500ml）や語の一部（Climax・vitamin）は上限にしない
_BEFORE_SKIP = re.compile(r"(?:最大|最小)\s*$|(?<![a-z])(?:max|min)$")
# 択一の標識（接続語の集合・網羅ではない（漏れは SPEC §7 R5））。数え語ごとの語リストではない: 計量値の付く先頭の 1<数え語> の後ろに別の個数が続く時、
# 間にこれがあれば択一（1個 または 3個）、無ければ単位あたりの説明・販促語（1個 送料無料 3個セット）
_ALTERNATIVE = re.compile(r"(?:または|又は|もしくは|或いは|あるいは|(?<![a-z])or(?![a-z])|[〜~～/])")
# 販促・価格表記（数量ではない）
_PROMO = [
    re.compile(r"\d+(?:\.\d+)?\s*倍"),                                   # ポイント10倍・2倍
    re.compile(r"\d+(?:\.\d+)?\s*%"),                                    # 最大50%OFF
    re.compile(r"\d[\d,]*(?:\.\d+)?\s*円"),                              # 1000円ポッキリ・1,980円
]


def _norm(s: str) -> str:
    """照合用の正規化: NFKC＋casefold（全角半角・大文字小文字を区別しない。ℓ→l、L→l）。"""
    return unicodedata.normalize("NFKC", s or "").casefold()


def _normalize(text: str) -> str:
    s = _norm(text)
    for ch in "✕✖⨯":
        s = s.replace(ch, "×")
    s = re.sub(r"[()\[\]{}【】「」『』〈〉《》<>]", " ", s)
    for pat in _PROMO:
        s = pat.sub(" ", s)
    return s


# ---- 表の引き方（表を直接書き換えても効くよう、使う時に引く） ----

def _unit_table() -> dict[str, tuple[str, float]]:
    return {_norm(k): v for k, v in UNITS.items()}


def _counter_table() -> dict[str, str]:
    return {_norm(k): v for k, v in COUNTERS.items()}


def _multiplier_table() -> dict[str, int]:
    return {_norm(k): v for k, v in COUNT_MULTIPLIERS.items()}


def _check_tables() -> None:
    """表の整合を import 時に検査する（S11）。直し忘れは起動できない形で知らせる。"""
    missing = sorted({dim for dim, _ in UNITS.values() if dim not in DISPLAY})
    if missing:
        raise RuntimeError(f"UNITS の次元に DISPLAY の行が無い: {missing}")
    for name, table in (("UNITS", UNITS), ("COUNTERS", COUNTERS)):
        seen: dict[str, str] = {}
        for key in table:
            norm = _norm(key)
            if norm in seen:
                raise RuntimeError(f"{name} の別名が NFKC＋casefold で重複: {seen[norm]!r} と {key!r}")
            seen[norm] = key


_check_tables()


def resolve_unit(alias: str) -> tuple[str, float] | None:
    """単位の別名 → (次元, 係数)。無ければ None。"""
    return _unit_table().get(_norm(alias).strip())


def base_unit(dimension: str) -> str:
    """次元の基準単位名（"ml" 等）。表示ラベルの先頭の数字と「あたり」を除いたもの。"""
    label = DISPLAY[dimension][1]
    m = re.fullmatch(r"[\d.]+(.+?)あたり", label)
    return m.group(1) if m else label


def resolve_basis(basis: str) -> tuple[str, str]:
    """比べる単位の指定 → (基準単位名, 次元)。"個" は ("個", "count")。別名（L・kg 等）は基準単位に直す。
    表に無ければ ValueError。"""
    if isinstance(basis, str):
        b = basis.strip()
        if b in ("個", "count"):
            return "個", "count"
        hit = resolve_unit(b)
        if hit is not None and hit[0] in DISPLAY:
            return base_unit(hit[0]), hit[0]
        for dim in DISPLAY:
            if dim != "count" and _norm(base_unit(dim)) == _norm(b):
                return base_unit(dim), dim
    raise ValueError("invalid basis")


def basis_choices() -> list[str]:
    """比べる単位として選べる基準単位名（"個" と、表にある次元の基準単位）。"""
    return ["個"] + [base_unit(d) for d in DISPLAY if d != "count"]


def dimension_of_basis(name: str) -> str:
    return resolve_basis(name)[1]


# ---- 表示用の数の整形（指数表記を使わない。S10）----

def format_amount(x: float | None) -> str:
    """量の表示。整数は千区切り（1,000,000）、小数は末尾の 0 を落として 9 桁まで。指数表記にしない。"""
    if x is None:
        return ""
    if x == int(x):
        return f"{int(x):,}"
    return f"{x:,.9f}".rstrip("0").rstrip(".")


# ---- 読み取り ----

@dataclass
class _Tok:
    kind: str                 # "count" / "measure" / "bare"
    start: int
    end: int
    n: float = 0.0            # count/bare: 個数、measure: 基準単位に直した量
    word: str = ""            # count: 正規の数え語
    dim: str = ""             # measure: 次元
    mult: int = 1             # count: 数え語の倍率（ダース=12）
    solo_low: bool = False    # count: 単独だと high にしない数え語（P。X1）


@dataclass
class _Group:
    toks: list[_Tok] = field(default_factory=list)

    @property
    def factors(self) -> list[_Tok]:
        return [t for t in self.toks if t.kind in ("count", "bare")]

    @property
    def measures(self) -> list[_Tok]:
        return [t for t in self.toks if t.kind == "measure"]


def _alt(keys) -> str:
    out = []
    for k in sorted(set(keys), key=lambda x: (-len(x), x)):
        piece = re.escape(k)
        if k[-1:].isascii() and k[-1:].isalpha():
            piece += r"(?![a-wyz]|x(?!\s*\d))"
        out.append(piece)
    return "|".join(out)


@functools.lru_cache(maxsize=8)
def _token_re(unit_keys: tuple[str, ...], counter_keys: tuple[str, ...]):
    return re.compile(
        rf"(?P<num>{_NUM})\s*(?:(?P<unit>{_alt(unit_keys)})(?!サイズ)|(?P<counter>{_alt(counter_keys)}))")


_IRI_AFTER = re.compile(r"\s*入")
# P5: 数え語の直後に文字（かな・漢字・英字・長音）が続く時、個数にしてよいのは次の語の時だけ。それ以外
# （お・ご・同・目・付・プ・指・刃・口・所・骨・タ・長音…）は個数にしない。語ごとの除外リストは持たない
_COUNTER_BOUNDARY_WORDS = re.compile(r"(?:x|入|セット|パック|組|ケース|箱|袋|梱|set|pack)")
# P5 で捨てた数が総数と食い違うと low にする規則（P5 の末尾）の対象外。SPEC §7 P5 補足が例示する3型の「数え語＋続く語」の
# 組だけを持つ（期間・販促・還元で、個数の候補ではないと分かっているもの）。数え語（正規化後の別名）ごとに引く。
# 組に無いもの（「6個で1000円」「30本ポイント10倍」）は捨てた数として検査する。捨てる判定そのものには使わない
_KNOWN_NOT_COUNT: dict[str, re.Pattern[str]] = {
    "ヶ": re.compile("月"), "ケ": re.compile("月"),                                    # 12ヶ月保証
    "点": re.compile("(?:購入|以上|まで|で)"),                                          # 2点購入・3点以上・2点で
    "p": re.compile("(?:還元|倍|up|アップ|ポイント|増量)"),                              # 10P還元・5Pアップ
}
# _AFTER_SKIP のうち、数え語の直後にあると購入条件・上限になる語（捨てた数の検査の対象にする）
_LIMIT_WORDS = re.compile(r"(?:以上|まで|以下|以内|未満|から)")
_BARE_RE = re.compile(r"(?:[×*]|(?<![a-z])x)\s*(\d+)(?![\d.]|[a-z])")
# 数字の直後に続く語（表にあるかどうかは別途判定する）
_WORD_AFTER_NUM = re.compile(r"(?<![\d.,])(\d{1,9})([^\W\d_]+)")
_UNK_BEFORE = re.compile(r"(?:[×*]|(?<![a-z])x|入数)\s*$")
_UNK_AFTER = re.compile(r"\s*(?:入り?|入数)?\s*(?:[×*]|x)\s*\d")
# P7 の対象: 量・個数に空白で続く「数字＋カタカナの語」（ブロック・カップ・ボトル・パウチ）。漢字の語（2層・1年・3色）と
# 英字の語（4K・60fps）は仕様・期間の記号が大半なので対象にしない
_KATAKANA_WORD = re.compile(r"[ァ-ヶ]")
# P0（WP9）E2: 構成品を並べる連結記号（NFKC 後の + と &。＋・＆ を含む）。この記号でつながれた列の中の個数
# （本体+バッテリ2個+充電器）は構成品の1つの個数であって、商品全体の個数ではない
_BUNDLE_JOINERS = "+&"


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def _digits_ok(raw: str) -> bool | None:
    """数値の文字列の桁検査。True=読める、False=桁が多すぎる（low）、None=千区切りの形でない（数量にしない）。"""
    integer = raw.split(".")[0]
    if "," in integer and not _THOUSANDS.fullmatch(integer):
        return None
    return len(integer.replace(",", "")) <= MAX_DIGITS


def _counter_boundary_ok(s: str, end: int) -> bool:
    """P5: 数え語の直後の文字が境界か。数え語ごとの例外分岐はここに足さない。"""
    if end >= len(s) or not s[end].isalpha():
        return True                  # 末尾・空白・数字・記号（×・=・読点・中点・括弧など）
    return _COUNTER_BOUNDARY_WORDS.match(s, end) is not None


def _is_known_not_count(counter: str, s: str, end: int) -> bool:
    """P5 の捨てた数の検査から外す「数え語＋続く語」の組か（_KNOWN_NOT_COUNT）。counter は正規化後の別名。"""
    known = _KNOWN_NOT_COUNT.get(counter)
    return bool(known and known.match(s, end))


def _is_link_position(s: str, start: int, end: int) -> bool:
    """P6: 個数の連結位置か（×・入数の直後、または直後に×が続く）。"""
    return bool(_UNK_BEFORE.search(s[:start]) or _UNK_AFTER.match(s, end))


def _in_bundle_list(s: str, start: int, end: int) -> bool:
    """P0（WP9）E2: [start, end) の個数が、+・& でつながれた構成品の列の中にあるか。空白を含まない一続きの語に
    連結記号がある（本体+バッテリ2個+充電器）か、その語が空白で区切られた単独の連結記号に隣り合う（本体 + バッテリ2個）時。
    語のリストではなく「連結記号でつながれた列の中」という位置で判定する。"""
    b = start
    while b > 0 and not s[b - 1].isspace():
        b -= 1
    f = end
    while f < len(s) and not s[f].isspace():
        f += 1
    if any(c in _BUNDLE_JOINERS for c in s[b:f]):
        return True
    # 空白で区切られた単独の記号（本体 + バッテリ2個）。語に付いた記号（BIGCAPA basic+ 単3形20本）は商品名の一部
    left, right = s[:b].rstrip(), s[f:].lstrip()
    return bool((left[-1:] in tuple(_BUNDLE_JOINERS) and (len(left) == 1 or left[-2].isspace()))
                or (right[:1] in tuple(_BUNDLE_JOINERS) and (len(right) == 1 or right[1].isspace())))


def _identity(m: re.Match, counters: dict[str, str], units: dict[str, tuple[str, float]]):
    """トークンの正規の同一性（P0 WP9 E1）。計量値は (次元, 基準単位に直した量)、個数は (正規の数え語, 数)。
    読めない（桁超過・千区切りの形でない・小数の個数・0）なら None。"""
    raw = m.group("num")
    if not _digits_ok(raw):
        return None
    value = _num(raw)
    if m.group("unit"):
        dim, factor = units[m.group("unit")]
        amount = round(value * factor, 9)
        return ("measure", dim, amount) if amount > 0 else None
    if value != int(value):
        return None
    return ("count", counters[m.group("counter")], int(value))


def _note_dropped(m: re.Match, s: str, counters: dict[str, str], units: dict[str, tuple[str, float]],
                  dropped: list[float], dropped_measures: list[tuple[str, float]],
                  *, serving: bool = False) -> None:
    """読まずに捨てた「数字＋数え語／計量単位」を P0 の候補として残す。数え語ごと・単位ごとの分岐は書かない。
    serving=False の時、使用回数・換算の説明（回分。S1）は個数の候補にしない（最大33回分・/30回分）。"""
    raw = m.group("num")
    if not _digits_ok(raw):
        return                                          # 桁超過・千区切りの形でない数は候補にしない
    value = _num(raw)
    if m.group("unit"):
        dim, factor = units[m.group("unit")]
        amount = round(value * factor, 9)
        if amount > 0:
            dropped_measures.append((dim, amount))
    elif (value == int(value) and (serving or counters[m.group("counter")] not in SERVING_WORDS)
            and not _is_known_not_count(m.group("counter"), s, m.end())):
        dropped.append(value)


def _tokens(s: str, flags: list[str], dropped: list[float],
            dropped_measures: list[tuple[str, float]] | None = None,
            embedded: list[tuple] | None = None) -> list[_Tok]:
    """flags に "oversize"（桁が多すぎる数）・"dropped_link"（連結位置の数え語を個数に採れなかった。P6）・
    "bundle_list"（+・& でつながれた構成品の列の中の個数。WP9 E2）を積む。embedded には、英数字の語（型番）の内側にあって
    読み飛ばした「数字＋単位・数え語」の同一性（_identity）を積む（採用した量が同じ表記で型番の一部にも現れるかを parse_quantity が見る。WP9 E1）。
    dropped には P5 の境界で個数に採らなかった「数字＋数え語」の数を、dropped_measures には採らなかった
    「数字＋計量単位」の（次元, 基準単位に直した量）を積む（採用した総数・内容量との食い違いを parse_quantity が見る。P0）。"""
    if dropped_measures is None:
        dropped_measures = []
    if embedded is None:
        embedded = []
    units, counters, mults = _unit_table(), _counter_table(), _multiplier_table()
    rx = _token_re(tuple(units), tuple(counters))
    solo_low = {_norm(w) for w in SOLO_LOW_COUNTERS}
    toks: list[_Tok] = []
    for m in rx.finditer(s):
        a = m.start("num")
        prev = s[a - 1] if a > 0 else ""
        # 英字・ハイフン等の直後の数字は型番の一部（SH-12M）。ただし直前の数量に続く「x」は乗算記号
        times = prev == "x" and ((a > 1 and not s[a - 2].isascii()) or (toks and toks[-1].end == a - 1))
        skipped = _AFTER_SKIP.match(s, m.end())
        before_limit = _BEFORE_SKIP.search(s, max(0, a - 4), a)
        if before_limit:
            # 「最大700g」「MAX1kg」「最大6個」の数は上限の記述で採らないが、採用した総数・内容量と食い違えば low（P0）
            _note_dropped(m, s, counters, units, dropped, dropped_measures)
            continue
        # 型番（SH-12M）として読まない数字のうち、直前の量・個数に続くもの（30m12R・500ml24本・100g-200g）と、
        # 区切り（_ /）の後ろのもの（シングル_55m・1本/3本セット）は、別の記述・択一の候補なので、採用した総数・内容量と
        # 食い違えば low にするため捨てた数として残す（P0）。採用はしない（high に倒す読みは足さない）。
        # ただし「/」の後ろの 1<数え語>（480ml/1個・24本入/1ケース）は単位あたりの説明なので候補にしない。
        # 直前が同じ数え語の個数（2個/1個）の時だけ択一として残す
        after_prev = bool(toks and toks[-1].end == a - (prev == "-"))             # 直前の量・個数の直後（ハイフン1字は挟む）
        if prev and not times and ((prev.isascii() and prev.isalpha()) or prev in "-_./"):
            per_unit = (prev == "/" and m.group("counter") and _num(m.group("num")) == 1
                        and not (toks and toks[-1].kind == "count" and toks[-1].word == counters[m.group("counter")]))
            if (prev in "_/" or after_prev) and not per_unit:
                _note_dropped(m, s, counters, units, dropped, dropped_measures)
            # WP9 E1: 英数字の語の内側（ICBK80L・S-500ml）。直前の量・個数に続く形（500ml24本）は上の捨てた数の検査が
            # 見るのでここでは残さない。x は乗算記号のことが多いので型番の一部とは見ない
            word_inside = ((prev.isascii() and prev.isalpha() and prev != "x")
                           or (prev == "-" and a > 1 and s[a - 2].isascii() and s[a - 2].isalnum()))
            if word_inside and not after_prev:
                ident = _identity(m, counters, units)
                if ident is not None:
                    embedded.append(ident)
            continue
        if skipped:
            # 「6個以上」「6個まで」「3個から」の数は購入条件・上限・下限で個数ではない。ただし捨てた数としては
            # 検査する（P5 と同じ。A4）。内容量（1kgから選べる）も同じ。「あたり」「相当」などの換算の説明は残さない
            limit = skipped.group().strip()
            # 個数 1 の「から」（1個から購入可）は最小購入数であって個数の候補ではない（/1個 と同じ扱い）
            minimum_one = (limit == "から" and m.group("counter") and _num(m.group("num")) == 1)
            if _LIMIT_WORDS.match(limit) and not minimum_one:
                _note_dropped(m, s, counters, units, dropped, dropped_measures, serving=True)
            continue
        ok = _digits_ok(m.group("num"))
        if ok is None:
            continue
        if not ok:
            flags.append("oversize")
            continue
        value = _num(m.group("num"))
        if m.group("unit"):
            dim, factor = units[m.group("unit")]
            amount = round(value * factor, 9)
            if amount <= 0:
                continue
            toks.append(_Tok("measure", a, m.end(), n=amount, dim=dim))
        else:
            link = _is_link_position(s, a, m.end())
            key = m.group("counter")
            word = counters[key]
            # 個数として採らない理由（P5 境界・小数・単独 P の上限）。連結位置なら黙って捨てず low（P6）
            if not _counter_boundary_ok(s, m.end()) or value != int(value):
                if value == int(value) and not _is_known_not_count(key, s, m.end()):
                    dropped.append(value)
                if link:
                    flags.append("dropped_link")
                continue
            if key in solo_low:
                # 単独の P だけ 1〜99 の時に個数の候補（1080P は画質）。×・入数に連結する P と、
                # 直前の量に空白だけで続く P（205ml 100P）は桁の上限を掛けず数える（P6。単独扱いは X1 が low にする）
                attached = link or bool(toks and toks[-1].kind == "measure" and not s[toks[-1].end:a].strip())
                if not (attached or 1 <= value <= MAX_PACK_P):
                    if link:
                        flags.append("dropped_link")
                    continue
            if _in_bundle_list(s, a, m.end()):
                flags.append("bundle_list")             # WP9 E2: 構成品の個数は商品全体の個数ではない（P0: low）
                continue
            toks.append(_Tok("count", a, m.end(), n=int(value), word=word,
                             mult=mults.get(key, 1), solo_low=key in solo_low))
    taken = {t.start for t in toks}
    for m in _BARE_RE.finditer(s):
        if m.start(1) in taken:
            continue
        if _AFTER_SKIP.match(s, m.end()):
            continue
        if len(m.group(1)) > MAX_DIGITS:
            flags.append("oversize")
            continue
        toks.append(_Tok("bare", m.start(1), m.end(1), n=int(m.group(1))))
    toks.sort(key=lambda t: t.start)
    return toks


def _unknown_counter(s: str, toks: list[_Tok]) -> bool:
    """数字の直後に表に無い語があり、そこが個数の連結位置（×の前後・入数の直後。S4）、または計量値・個数に
    空白だけで続く位置（900g 6ブロック。P7）なら True。"""
    units, counters = _unit_table(), _counter_table()
    rx = _token_re(tuple(units), tuple(counters))
    ends = {t.end for t in toks if t.kind in ("measure", "count")}
    for m in _WORD_AFTER_NUM.finditer(s):
        if rx.match(s, m.start(1)):
            continue                              # 表にある単位・数え語（読み取り側で処理する）
        word = re.sub(r"(?:入り?|入数)$", "", m.group(2))
        if not word:
            continue
        if _UNK_BEFORE.search(s[:m.start(1)]) or _UNK_AFTER.match(s, m.start(2) + len(word)):
            return True
        head = s[:m.start(1)]
        stripped = head.rstrip()
        if (len(stripped) < len(head) and len(stripped) in ends
                and _KATAKANA_WORD.match(word)):
            return True                           # P7: 量・個数の直後に空白で続く「数字＋表に無い語」
    return False


def _joins(s: str, p: _Tok, t: _Tok, g: _Group, flags: list[str],
           t_chain: tuple[int, int]) -> bool:
    """t を直前のトークン p と同じ鎖（グループ）に入れるか。g は p までの鎖。
    t_chain は t が新しい鎖の先頭だった時のその鎖の（個数の積, 因子数）（4ロール×6パック → (24, 2)）。
    flags に "ambiguous"（同数・別の数え語で積か言い直しか決められない）を積む。"""
    gap = s[p.end:t.start]
    if t.kind == "bare":
        return bool(_GAP_X.fullmatch(gap))
    if t.solo_low and not (_GAP_X.fullmatch(gap) or ("入" in gap and _GAP_PLAIN.fullmatch(gap))):
        return False                 # NP は ×の直後・入数の直後でだけ連結する（X1・X5）
    if t.kind == "measure" and g.measures:
        # 内容量は 1 グループに 1 つ（寸法は同じ次元を × でつなぐ時だけ）
        return p.kind == "measure" and p.dim == t.dim and bool(_GAP_LABEL.fullmatch(gap))
    if p.kind == "measure" and t.kind == "measure":
        return p.dim == t.dim and bool(_GAP_LABEL.fullmatch(gap))
    if p.kind == "bare" and t.kind != "bare":
        return bool(_GAP_X.fullmatch(gap))
    if p.kind == "count" and t.kind == "count":
        if _GAP_X.fullmatch(gap):
            return True
        if not _GAP_COUNT_MEASURE.fullmatch(gap):
            return False
        facs = g.factors
        t_total, t_facs = t_chain
        if facs and t_total == _total(g):
            # P1: 鎖の積と等しい後続は総数の言い直し（12ロール×4パック 48ロール）。因子にしない。
            # ただし鎖が 1 因子で数が偶然同じ時（3個入り 3セット）は、外側が容器語なら掛け算（P4）、
            # そうでなければ積か言い直しか決められない（X4）ので単価不明に倒す。同じ数え語なら言い直し
            if (len(facs) == 1 and t_facs == 1 and facs[0].mult == 1 and t_total != 1
                    and t.word != facs[0].word):
                if t.word in OUTER_WORDS:
                    return True
                flags.append("ambiguous")
            return False
        if "入" in gap or (t.word in CONTAINERS and all(f.word != t.word for f in facs)):
            return True
        # 外側「5箱」のあとに内側「60個入」が来る順は、W1（内側→外側）とは逆で、積か説明か決められない
        if (len(facs) == 1 and p.n != 1 and _IRI_AFTER.match(s, t.end)
                and not _IRI_AFTER.match(s, p.end)):
            flags.append("ambiguous")
            return False
        # ×の無い2段の数え語「500枚 5冊」「12本入り 2ダース」（W1）。先頭が 1 の「1箱 24本」は
        # 1 個あたりの説明なので連結しない。同じ数え語の言い直し（12本 12本入り）も連結しない。
        # すでに 2 因子以上ある鎖には足さない（P2）
        if len(facs) > 1:
            return False
        return p.n != 1 and (p.word != t.word or t.mult > 1)
    plain = _GAP_COUNT_MEASURE if {p.kind, t.kind} == {"count", "measure"} else _GAP_PLAIN
    return bool(_GAP_X.fullmatch(gap) or plain.fullmatch(gap))


_LOOKAHEAD = 8          # 先読みする鎖の最大トークン数（商品名の鎖はこれより短い）


def _group(s: str, toks: list[_Tok], flags: list[str]) -> list[_Group]:
    # 各トークンが「新しい鎖の先頭」だったら、その鎖の（個数の積, 因子数）はいくつか。後ろから求める。
    # t の側が積（4ロール×6パック×2ケース）の時、前の記述（48個）がその言い直しかを積で判定するため
    ahead: list[tuple[int, int]] = [(1, 0)] * len(toks)
    for i in range(len(toks) - 1, -1, -1):
        g = _Group([toks[i]])
        for j in range(i + 1, min(len(toks), i + _LOOKAHEAD)):
            if not _joins(s, g.toks[-1], toks[j], g, [], ahead[j]):
                break
            g.toks.append(toks[j])
        ahead[i] = (_total(g), len(g.factors))
    groups: list[_Group] = []
    for i, t in enumerate(toks):
        if groups and _joins(s, groups[-1].toks[-1], t, groups[-1], flags, ahead[i]):
            groups[-1].toks.append(t)
        elif t.kind != "bare":      # 直前に何も無い「×6」は個数にしない
            groups.append(_Group([t]))
        else:
            flags.append("orphan_times")      # 読み飛ばした記述の後ろの「×2」など。倍数が落ちている恐れ
    return groups


def _drop_restated(g: _Group, flags: list[str]) -> _Group:
    """内容量の後ろで、内容量より前に書かれた個数と同じ数が出てきたら言い直し（二重に掛けない。S2）。
    例: 24本 (500ml×24) / 6袋 900g×6 / 2袋 (5kg×2袋)。ただし先の数え語と違う容器語で同数なら掛け算（P4。
    3個入り 400ml×3セット → 9）。"""
    before: dict[float, str] = {}
    seen_measure = False
    kept: list[_Tok] = []
    for t in g.toks:
        if t.kind == "measure":
            seen_measure = True
        elif seen_measure and t.n in before:
            # P4: 同じ数でも、先に書かれた数え語と違う容器語（袋・セット・ケース・パック）なら外側の掛け算。
            # 容器語でない別の数え語（3個入り 400ml×3冊）は積か言い直しか決められない（X4）
            if t.kind == "count" and t.n != 1 and t.word != before[t.n] and t.mult == 1:
                if t.word not in OUTER_WORDS:
                    flags.append("ambiguous")
                    continue
            else:
                continue
        elif not seen_measure:
            before.setdefault(t.n, t.word)
        kept.append(t)
    return _Group(kept)


def _explicit_chain(s: str, g: _Group) -> bool:
    """個数の鎖が ×・入 で明示的につながっているか（12ロール×4袋・12本入 3パック）。空白だけの連結
    （48本 2ケース）は、前に別に書かれた同じ数（【48本】）が内側の言い直しか総数かを決められない。"""
    f = g.factors
    return all(re.search(r"[×x*入]", s[a.end:b.start]) for a, b in zip(f, f[1:]))


def _total(g: _Group) -> int:
    out = 1
    alone = len(g.factors) == 1
    for t in g.factors:
        out *= int(t.n) * (t.mult if alone else 1)
    return out


def _none(evidence: str = "") -> QuantityInfo:
    return QuantityInfo(confidence="none", evidence=evidence)


def _low(evidence: str) -> QuantityInfo:
    return QuantityInfo(confidence="low", evidence=evidence)


def _resolve_amount(values: dict[float, bool], count: int) -> float | None:
    """同じ次元の内容量の値（値 → その値と同じ鎖に個数があるか）から 1 個あたりの量を決める。食い違っても、
    大きい方が小さい方×個数で、個数が小さい方に付いているなら総量の併記（5kg×2袋 計10kg）とみなして
    小さい方を 1 個あたりにする（S3）。個数が大きい方に付く「5kg 10kg 2袋」は決められない。決められなければ None。"""
    if len(values) == 1:
        return next(iter(values))
    lo = min(values)
    if count > 1 and all(v == lo or (v == round(lo * count, 9) and not values[v]) for v in values):
        return lo
    return None


# WP11-4: 型番の語（英字の後ろに数字が続く、ASCII だけの語。IC6CL80・ICBK80L・LR6XJ/20SW）。
# 量の語（500ml・2l・1kg）は先頭が数字なので型番の語に入らない
_MODEL_WORD = re.compile(r"[a-z0-9\-_./]*[a-z][a-z\-_./]*[0-9][a-z0-9\-_./]*")
_DIGIT_RUN = re.compile(r"[0-9]+")
MODEL_DIGITS_MIN = 2   # 1 桁の数字は No.1・Type2・LR6 のように型番以外にも普通に現れるので同一性の根拠にしない


def _standalone_measure_digits_in_model(s: str, groups: list[_Group]) -> bool:
    """WP11-4（WP9 E1 の拡張）: 単独で立つ内容量（×・入・空白の連結で個数などとつながらない）の数字が、同じ題名の
    型番の語の内側に数字として現れるか。IC6CL80 の『80』と『80L』のように、型番に単位が付かず E1（同じ量の同一性）で
    見えない形。独立した量か型番の一部か決められないので low（P0）。鎖の一部の量は型番の言い直しとして普通に書かれるので
    掛けない（E1 と同じ）。"""
    singles = []
    for g in groups:
        if len(g.toks) == 1 and g.toks[0].kind == "measure":
            m = re.match(r"[0-9][0-9,]*(?:\.[0-9]+)?", s[g.toks[0].start:g.toks[0].end])
            if m:
                singles.append((g.toks[0], m.group().replace(",", "")))
    if not singles:
        return False
    for w in re.finditer(r"\S+", s):
        if not _MODEL_WORD.fullmatch(w.group()):
            continue
        for run in _DIGIT_RUN.finditer(w.group()):
            if len(run.group()) < MODEL_DIGITS_MIN:
                continue
            for tok, raw in singles:
                if w.start() <= tok.start < w.end():
                    continue                              # 量そのものの語
                try:
                    same = float(raw) == float(run.group())
                except ValueError:
                    continue
                if same:
                    return True
    return False


def parse_quantity(text: str, basis: str | None = None) -> QuantityInfo:
    """商品名 → 数量。basis（比べる単位）が内容量の次元で、名前にその次元の内容量があればそれを
    content_* に使う（S5）。省略時は最初に書かれた次元。"""
    s = _normalize(text)
    flags: list[str] = []
    dropped: list[float] = []
    dropped_measures: list[tuple[str, float]] = []
    embedded: list[tuple] = []
    toks = _tokens(s, flags, dropped, dropped_measures, embedded)
    if flags or _unknown_counter(s, toks):
        return _low(s.strip()[:80])
    if not toks:
        return _none()
    # 「30回分」は使用回数・換算の説明。計量値や他の個数があれば数えない（S1）
    if any(t.kind == "count" and t.word in SERVING_WORDS for t in toks) and any(
            t.kind == "measure" or (t.kind == "count" and t.word not in SERVING_WORDS) for t in toks):
        toks = [t for t in toks if not (t.kind == "count" and t.word in SERVING_WORDS)]
    groups = _group(s, toks, flags)
    # WP9 E1（B8 で限定）: 採用した内容量が、×・入・空白の連結で個数などとつながらず「単独」で立ち、同じ量が英数字の語
    # （ICBK80L）の内側にも現れる時は、独立した量か型番の一部か決められないので low（P0）。鎖の一部（PET500ml 500ml×24本・
    # 500ml 24本）は型番の言い直しとして普通に書かれるので掛けない。個数は対象外（SN12R … 12ロール は言い直し）。
    # 型番だけの題名（独立した 80L が無い）は従来どおり量にしない
    if embedded and any(len(g.toks) == 1 and g.toks[0].kind == "measure"
                        and ("measure", g.toks[0].dim, round(g.toks[0].n, 9)) in embedded for g in groups):
        return _low(s.strip()[:80])
    if _standalone_measure_digits_in_model(s, groups):      # WP11-4: 型番に単位が付かない形（IC6CL80 … 80L）
        return _low(s.strip()[:80])
    evidence = " / ".join(dict.fromkeys(s[g.toks[0].start:g.toks[-1].end].strip() for g in groups))
    if flags and groups:                 # 食い違い・倍数の落ち（P0: 失敗の向きは単価不明）
        return _low(evidence)
    # 単独の NP は個数の候補として持つが、他の読み方と一致しない限り high にしない（X1）
    solo = [g for g in groups if g.toks[0].solo_low]
    agreed = {_total(g) for g in groups if g.factors and not g.toks[0].solo_low}
    if any(_total(g) not in agreed for g in solo):
        return _low(evidence)
    groups = [_drop_restated(g, flags) for g in groups]
    if flags and groups:
        return _low(evidence)

    # --- 個数 ---
    cgroups = [g for g in groups if g.factors]
    # 「1ロール30m」「1箱24本入り」の先頭の 1<数え語> は、1個あたりの説明であって個数ではない
    keep: list[_Group] = []
    for g in cgroups:
        single_one = len(g.factors) == 1 and g.factors[0].kind == "count" and g.factors[0].n == 1
        others = [h for h in cgroups if h is not g and _total(h) != 1]
        if single_one and others:
            nxt = next((h for h in groups if h.toks[0].start >= g.toks[-1].end), None)
            adjacent = nxt is not None and not s[g.toks[-1].end:nxt.toks[0].start].strip()
            if g.measures or adjacent:
                if (nxt is not None and not adjacent and nxt.factors
                        and _ALTERNATIVE.search(s[g.toks[-1].end:nxt.toks[0].start])):
                    # 1個 または 3個・1個 or 2個・1個〜3個: 間に択一の標識を挟んで別の個数が続くのは、
                    # 単位あたりの説明ではなく択一。黙って捨てず、採用した総数と食い違えば low（P0）
                    dropped.append(1.0)
                continue
        keep.append(g)
    # 複合表記（12ロール×4袋）の 1 袋あたりと同じ単独の記述（12ロール入り）は矛盾とみなさない
    # 空白だけでつないだ鎖（48本 2ケース）の内側と同じ単独の記述は、入が付く（1ケース24本入り＝単位あたりの説明）
    # 時だけ言い直し。入の無い単独（【48本】）は内側の言い直しか総数か決められない
    compound = [h for h in keep if len(h.factors) > 1]
    inner = {(h.factors[0].word, h.factors[0].n): _explicit_chain(s, h) for h in compound}
    keep = [g for g in keep if not (len(g.factors) == 1 and (g.factors[0].word, g.factors[0].n) in inner
                                     and (inner[(g.factors[0].word, g.factors[0].n)]
                                          or _IRI_AFTER.match(s, g.factors[0].end)))]
    totals = {_total(g) for g in keep}
    if len(totals) > 1 or any(t <= 0 or t > MAX_PLAUSIBLE_COUNT for t in totals):
        return _low(evidence)
    total = next(iter(totals)) if keep else 1
    # P5 で個数に採らなかった「数字＋数え語」が採用した総数と食い違う時は、捨てた数が本当の個数かもしれない
    # （洗剤 500ml 12個送料無料）ので low。同じ数なら言い直しなので high のまま
    if any(d != total for d in dropped):
        return _low(evidence)

    # --- 内容量（同じ次元の × でつながる寸法は大きい方。別々に書かれた値が食い違えば矛盾）---
    per_group: list[tuple[str, float, int, bool]] = []
    for g in groups:
        by_dim: dict[str, float] = {}
        for m in g.measures:
            by_dim[m.dim] = max(by_dim.get(m.dim, 0.0), m.n)
        first = {d: next(m.start for m in g.measures if m.dim == d) for d in by_dim}
        per_group += [(d, a, first[d], bool(g.factors)) for d, a in by_dim.items()]
    amounts: dict[str, float] = {}
    dim = amount = None
    if per_group:
        order: list[str] = []
        for d, _, _, _ in sorted(per_group, key=lambda x: x[2]):
            if d not in order:
                order.append(d)
        for d in order:
            vals: dict[float, bool] = {}
            for dd, a, _, has in per_group:
                if dd == d:
                    vals[round(a, 9)] = vals.get(round(a, 9), False) or has
            resolved = _resolve_amount(vals, total)
            if resolved is not None:
                amounts[d] = resolved
        want = None
        if basis not in (None, ""):
            try:
                want = resolve_basis(basis)[1]
            except ValueError:
                want = None
        if want in amounts:
            dim = want
        elif order[0] in amounts:
            dim = order[0]
        else:
            return _low(evidence)
        amount = amounts[dim]
        # 採らなかった「数字＋計量単位」（最大700g・シングル_55m）が、採用した同じ次元の内容量（またはその総量）と
        # 食い違う時は、捨てた量が本当の内容量かもしれないので low（P0。個数の「捨てた数の検査」の内容量版）
        for d, v in dropped_measures:
            if d in amounts and v not in (amounts[d], round(amounts[d] * total, 9)):
                return _low(evidence)

    if keep:
        main = max(keep, key=lambda g: len(g.factors))
        word = next((t.word for t in main.factors if t.kind == "count"), "個")
    elif amount is not None:
        word = "個"
    else:
        return _none()
    return QuantityInfo(
        count_total=total, count_unit=word, content_amount=amount,
        content_dimension=dim, content_unit=base_unit(dim) if dim else None,
        measure_total=None if amount is None else round(total * amount, 9),
        confidence="high", evidence=evidence, content_amounts=amounts)
