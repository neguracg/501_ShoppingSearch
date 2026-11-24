# @owns モールAdapterの共通契約とAdapterError
"""モール Adapter の共通インターフェースとエラー型。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Offer


class AdapterError(Exception):
    """kind だけを持つ。URL・キー・応答本文は絶対に含めない。"""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind

    def __str__(self) -> str:
        return self.kind

    def __repr__(self) -> str:
        return f"AdapterError({self.kind!r})"


def adapter_attr(adapter, name: str):
    """モール別の属性を引く。属性を持たないアダプタ（試験の偽物・包んだ物）は、楽天相当の既定（MarketplaceAdapter の値）。"""
    return getattr(adapter, name, getattr(MarketplaceAdapter, name))


class MarketplaceAdapter(ABC):
    """モールごとの値（上限・流量・URL の形・表示名）はサブクラスの属性に持つ。外（orchestrator・guard・web・service）は属性を引くだけ。"""
    mall: str = ""
    label: str = ""                       # 利用者に見せるモール名
    short_label: str = ""                 # 文中で「〇〇のデータでは」と言う時の短い名前
    source: str = ""                      # 出典の表記（notes・結果の source）
    max_hits: int = 30                    # 1 ページの最大件数
    page_size: int | None = None          # 1 ページの件数が固定のモールはその値（None は呼び出し側の hits）
    max_page: int = 100                   # 返せる最後のページ番号
    min_interval_sec: float = 1.0         # 1 リクエストごとに空ける秒
    stop_kinds: tuple = ("http_429",)     # この種別のエラーは、そのモールの残りの検索を打ち切る
    empty_means_end: bool = True          # 空のページ＝終わり（アダプタ内で候補を捨てるモールは False）
    ceiling_note: str = ""                # max_page に達した時の注記

    @staticmethod
    def is_item_url(url: object) -> bool:
        return False

    def request_notes(self, *, sort: str = "standard", ng_keyword: str | None = None) -> list[str]:
        """この検索条件をこのモールでどう扱うか（読み替え・代替）の注記。無ければ []。"""
        return []

    @abstractmethod
    def search(self, keyword: str, *, page: int = 1, hits: int = 30,
               ng_keyword: str | None = None, min_price: int | None = None,
               max_price: int | None = None, sort: str = "standard",
               availability: int = 1) -> tuple[list[Offer], int]:
        """(offers, api_count) を返す。失敗は AdapterError(kind)。"""
