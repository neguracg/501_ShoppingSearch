# @owns 定番品マスタ（data/regulars.json）の読み込みと検証
"""定番品マスタ。価格・在庫は保存しない（検索のたびに取り直す）。個人の購入リストなので git 管理外。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .inputs import InvalidInput, check_desired_quantity, resolve_compare_basis

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "regulars.json"
PATH_ENV = "SHOPPING_REGULARS_PATH"


class RegularsError(Exception):
    """kind: file_not_found / invalid_json / invalid_format / not_found"""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(kind)
        self.kind = kind
        self.detail = detail


@dataclass
class Regular:
    id: str
    name: str
    keywords: list[str]
    maker: str | None = None
    model_number: str | None = None
    jan: str | None = None
    include_terms: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    basis: str | None = None             # "個" または 基準単位（省略で自動）
    desired_quantity: float | None = None
    known_urls: list[str] = field(default_factory=list)
    notes: str | None = None


def _opt_str(d: dict, key: str) -> str | None:
    v = d.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise RegularsError("invalid_format", f"{key} must be a string")
    return v


def _parse_one(d: object, index: int) -> Regular:
    if not isinstance(d, dict):
        raise RegularsError("invalid_format", f"entry {index} must be an object")
    rid = d.get("id")
    name = d.get("name")
    if not isinstance(rid, str) or not rid.strip():
        raise RegularsError("invalid_format", f"entry {index}: id is required")
    if not isinstance(name, str) or not name.strip():
        raise RegularsError("invalid_format", f"entry {index}: name is required")
    kws = d.get("keywords")
    if not isinstance(kws, list) or not kws or not all(isinstance(k, str) and k.strip() for k in kws):
        raise RegularsError("invalid_format", f"{rid}: keywords must be a non-empty list of strings")
    terms: dict[str, list[str]] = {}
    for key in ("include_terms", "exclude_terms"):
        v = d.get(key)
        if v is None:
            v = []
        if not isinstance(v, list) or not all(isinstance(t, str) and t.strip() for t in v):
            raise RegularsError("invalid_format", f"{rid}: {key} must be a list of strings")
        terms[key] = [t.strip() for t in v]
    basis = d.get("basis")
    if basis is not None:
        try:
            resolve_compare_basis(basis)
        except ValueError:
            raise RegularsError("invalid_format", f"{rid}: basis is not a known unit") from None
    dq = d.get("desired_quantity")
    try:                                         # 検査の実装は inputs に一本化（公開面・pricing と同じ）
        check_desired_quantity(dq)
    except InvalidInput:
        raise RegularsError("invalid_format", f"{rid}: desired_quantity must be a positive number") from None
    urls = d.get("known_urls", [])
    if urls is None:
        urls = []
    if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
        raise RegularsError("invalid_format", f"{rid}: known_urls must be a list of strings")
    return Regular(id=rid, name=name, keywords=list(kws), maker=_opt_str(d, "maker"),
                   model_number=_opt_str(d, "model_number"), jan=_opt_str(d, "jan"),
                   include_terms=terms["include_terms"],
                   exclude_terms=terms["exclude_terms"], basis=basis, desired_quantity=dq,
                   known_urls=list(urls), notes=_opt_str(d, "notes"))


def resolve_path(path: Path | str | None = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get(PATH_ENV)
    return Path(env) if env else DEFAULT_PATH


def load_regulars(path: Path | str | None = None) -> list[Regular]:
    p = resolve_path(path)
    try:
        raw = p.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise RegularsError("file_not_found") from None
    except OSError:
        raise RegularsError("file_not_found") from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise RegularsError("invalid_json") from None
    entries = data.get("regulars") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise RegularsError("invalid_format", "top level must be a list or {\"regulars\": [...]}")
    result = [_parse_one(e, i) for i, e in enumerate(entries)]
    ids = [r.id for r in result]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise RegularsError("invalid_format", f"duplicate id: {', '.join(sorted(dup))}")
    return result


def get_regular(regular_id: str, path: Path | str | None = None) -> Regular:
    for r in load_regulars(path):
        if r.id == regular_id:
            return r
    raise RegularsError("not_found")
