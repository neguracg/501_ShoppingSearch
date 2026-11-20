# @owns Offer/QuantityInfo/SearchStats等のデータ形
"""データモデル。不明は None（推測で埋めない）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QuantityInfo:
    """商品名から読み取った数量。個数 × 1個あたり内容量。商品の意味（種類・仕様）は持たない。"""
    count_total: int | None = None         # 総個数。confidence != "high" なら None
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
    # 選択肢（サイズ・枚数）で価格が変わる商品の価格幅（WP14 W1。楽天の itemPriceMin/Max。出典 SPEC §5）。
    # price（itemPrice）は最小の選択肢の価格で、商品名の数量の選択肢の価格とは限らない
    price_min: int | None = None
    price_max: int | None = None
    # あす楽（楽天の asurakuFlag / asurakuClosingTime）。発送目安・送料額の項目は API に無い
    asuraku_flag: bool | None = None
    asuraku_closing_time: str | None = None

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
    truncated: bool = False     # next_page があること（範囲・時間の上限で、取れるはずの続きを残して止めた）


@dataclass
class SearchStats:
    per_keyword: list[KeywordStat] = field(default_factory=list)
    total_received: int = 0
    duplicates_removed: int = 0
    unique_offers: int = 0
    fetched_at: str | None = None
    stopped_reason: str | None = None
    elapsed_sec: float | None = None    # 取得にかかった秒（小数 1 桁）
    # stopped_reason: rate_limited（楽天 429）/ time_limit（1 回の取得の時間の上限で途中まで）
