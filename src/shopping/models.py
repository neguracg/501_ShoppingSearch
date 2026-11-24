# @owns Offer/QuantityInfo/SearchStats等のデータ形
"""データモデル。不明は None（推測で埋めない）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QuantityInfo:
    """商品名から読み取った数量。個数 × 1個あたり内容量。商品の意味（種類・仕様）は持たない。"""
    count_total: int | None = None         # 総個数。confidence が high のほか、題名 low で読みを仮の数量にした時（low_adopted。WP16 U2a・U2b）に入る
    count_unit: str = "個"                 # 数え語（無ければ "個"）
    content_amount: float | None = None    # 1個あたり内容量（基準単位）。無い/読めない時は None
    content_dimension: str | None = None   # volume / mass / length / power / charge / energy / None
    content_unit: str | None = None        # 基準単位名（"ml" "g" "m" "W" "mAh" "Wh"）
    measure_total: float | None = None     # count_total × content_amount（内容量が無ければ None）
    confidence: str = "none"               # "high" / "low" / "none"
    evidence: str = ""                     # 根拠にした文字列（無ければ ""）
    # 名前に書かれた次元ごとの 1個あたり内容量（基準単位。S5: 比べる単位を明示した時に使う）。
    # content_dimension / content_amount は、この中で最初に書かれた次元（自動判定用）
    content_amounts: dict = field(default_factory=dict)
    # 数量の出どころ（WP14 W4）。"title"=商品名（quantity.py の読み取り）、"caption"=題名から読めず説明欄の見出し付きの記述から補完
    source: str = "title"
    caption_evidence: str | None = None      # source=="caption"、または題名と説明欄が食い違う時（caption_conflict）の、説明欄の見出しから値までの原文
    caption_conflict: bool = False           # 題名が high で、説明欄の見出し付きの数量と食い違う（confidence は変えない）
    # 題名が none で、説明欄に見出し付きの数量がある時の候補（WP14 W4 の出荷形＝印と根拠だけ。単位価格・最安・注文案には使わない）。
    # {"count_total","count_unit","content_amount","content_dimension"}。caption_quantity.CAPTION_FILL_UNIT_PRICE を True にすると
    # この候補を数量として補完する（source="caption"）形になる
    caption_candidate: dict | None = None
    # 包装の数（WP15 段B。題名の F1〜F3 の形。pack_forms.py）。[{"unit":"袋","count":2,"per_pack":18,"per_pack_unit":"本"}]。
    # 題名の総数が high でその総数が N×M と一致する時だけ。読めなければ []。総数・confidence には影響しない
    packs: list = field(default_factory=list)
    # 題名 low の出力（WP16 U2a・readings）。low_reason＝low の理由のコード（quantity.py `_low` の表。low 以外は None）。
    # readings＝low の題名から読めた個数・内容量の読みの一覧（印。単価には使わない）。low 以外は None
    low_reason: str | None = None
    readings: dict | None = None
    # 説明欄の各文から抽出したが採らなかった値の一覧（WP16 U1。印。確定値ではない）。
    # [{"count_total","count_unit","content_amount","content_dimension","evidence"}]（読めなかった項目は None）。キーは常に出す
    caption_candidates: list = field(default_factory=list)
    # U1 の採用待ち（次元 → caption_candidates の中の候補 dict〔同一の物〕）。(ii)(i) を通った値で、(iii) 桁の照合は
    # 比較グループの統計が要るので caption_adopt.adopt_u1 が採用する（抽出と採用の分離）。採用された次元は u1_adopted
    u1_pending: dict = field(default_factory=dict)
    u1_adopted: list = field(default_factory=list)

    @property
    def low_adopted(self) -> bool:
        """題名 low の読みを仮の数量として使っている（U2a の総数・U2b で選んだ読み。confidence は low のまま。未確定理由 quantity_low）。
        low で count_total が入るのは、この2つだけ。"""
        return self.confidence == "low" and self.count_total is not None

    def __post_init__(self) -> None:
        if (self.measure_total is None and self.count_total is not None
                and self.content_amount is not None):
            self.measure_total = round(self.count_total * self.content_amount, 9)


@dataclass
class Offer:
    mall: str
    mall_item_code: str
    item_name: str
    price: int | None
    item_url: str
    item_url_status: str         # "ok" / "needs_review"
    shop_name: str | None = None
    shop_code: str | None = None
    shipping_status: str = "unknown"      # "included" / "separate" / "unknown"
    shipping_fee: int | None = None
    availability: bool | None = None
    points_rate: int | None = None
    review_average: float | None = None
    review_count: int | None = None
    jan: str | None = None
    model_number: str | None = None
    caption: str | None = None
    fetched_at: str | None = None         # ISO8601 JST
    matched_keywords: list[str] = field(default_factory=list)
    quantity: QuantityInfo | None = None
    # 比較（pricing.compare）が書き込む。表示単位あたりの円（丸める前）と表示用ラベル（"100mlあたり" 等）
    unit_price: float | None = None
    unit_price_label: str | None = None
    # 単位価格に使った量の次元（count / volume / mass …）。basis を明示した時、名前に複数の次元があっても
    # どれで比べたかが分かる（S5）。単価を出せない候補は None
    unit_price_dimension: str | None = None
    # 単位価格が同じ比較グループの中央値の 1/10 未満（数量の読み違いの疑い。WP10）。比較が書き込む。
    # True の候補は単位価格の最安・必要数量を満たす最安に選ばれない（候補一覧には残す）
    unit_price_outlier: bool = False
    # basis に数え語（袋）を指定した比較で、1袋の中身が基準と食い違う（WP15 段B。比較が書き込む。counter_basis.py）。
    # True の候補の単価は仮（pack_content_differs）で、注文の最安に選ばれない
    pack_content_differs: bool = False
    # 選択肢（サイズ・枚数）で価格が変わる商品の価格幅（WP14 W1。楽天の itemPriceMin/Max。出典 SPEC §5）。
    # price（itemPrice）は最小の選択肢の価格で、商品名の数量の選択肢の価格とは限らない
    price_min: int | None = None
    price_max: int | None = None
    # あす楽（楽天の asurakuFlag / asurakuClosingTime）。発送目安・送料額の項目は API に無い
    asuraku_flag: bool | None = None
    asuraku_closing_time: str | None = None
    # モールのアダプタが付ける「確認済みにできない理由」の語（WP17 P1。pricing.unconfirmed_reasons がそのまま足す）。
    # price_options_unchecked / price_tax_unknown / condition_not_new。楽天は常に []
    mall_unconfirmed: list[str] = field(default_factory=list)
    points_amount: int | None = None      # 円相当の参考値（Yahoo のストアポイント・期間限定。総額・単価・最安には使わない）
    shipping_condition: str | None = None  # "conditional_free"（条件付き送料無料）など。shipping_status とは別の参考
    condition: str | None = None          # 商品の状態（Yahoo の new / used 等）。楽天は None
    sale: dict | None = None              # セール中の参考（{"discounted_price", "period_end"}）。price は値下げ後の価格のまま

    @property
    def price_varies(self) -> bool:
        """選択肢によって価格が変わる（min と max が両方あり min≠max）。この時 price は商品名の数量の価格とは限らない。"""
        return (self.price_min is not None and self.price_max is not None
                and self.price_min != self.price_max)


@dataclass
class Product:
    product_key: str
    name: str
    jan: str | None = None
    maker: str | None = None
    model_number: str | None = None
    spec: dict = field(default_factory=dict)
    spec_status: str = "unknown"          # confirmed / extracted / unknown


@dataclass
class KeywordStat:
    keyword: str
    api_count: int | None = None
    received: int = 0
    error: str | None = None
    pages_fetched: int = 0      # 実際に取得できたページ数
    start_page: int = 1         # 取り始めたページ（呼び出しの start_page）
    last_page: int | None = None    # 取得できた最後のページ（1 ページも取れなければ None）
    next_page: int | None = None    # 続きがあれば次のページ番号。無い・楽天の 100 ページ天井に達した・エラーの時は None
    remaining: int | None = None    # api_count のうち、100 ページ天井以内でまだ取っていない件数（目安）。件数が分からなければ None
    truncated: bool = False     # next_page があること（範囲・時間の上限で、取れるはずの続きを残して止めた）。モールの件数の上限（Yahoo の 1000 件目）で止めた時は next_page=None のまま True
    mall: str = ""              # 検索したモール（WP17 C4）


@dataclass
class MallStat:
    """モール別の要約（WP17 C4）。api_count は語ごとの api_count の和（読めた語だけ。1 つも無ければ None）。"""
    mall: str
    fetched: int = 0                  # 取得件数
    api_count: int | None = None
    error: str | None = None          # 全部の語が失敗した時の最初の種別（一部の語だけの失敗は per_keyword の error）
    truncated: bool = False           # どれかの語に続きがある、またはモールの上限で打ち切った
    stopped_reason: str | None = None  # rate_limited / server_error / time_limit
    skipped: int = 0                  # 応答のうち、読めずに捨てた hit の件数


@dataclass
class SearchStats:
    per_keyword: list[KeywordStat] = field(default_factory=list)
    total_received: int = 0
    duplicates_removed: int = 0
    unique_offers: int = 0
    fetched_at: str | None = None
    stopped_reason: str | None = None
    elapsed_sec: float | None = None    # 取得にかかった秒（小数 1 桁）
    per_mall: list[MallStat] = field(default_factory=list)      # モール別の要約（WP17 C4）
    # stopped_reason: rate_limited（楽天 429）/ time_limit（1 回の取得の時間の上限で途中まで）
