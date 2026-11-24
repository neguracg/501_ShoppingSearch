# @owns モールAPIの応答項目（数・文字）を型の違いに強く読む関数
"""楽天・Yahoo のアダプタが共有する。読めない値は例外にせず None（推測で埋めない）。"""
from __future__ import annotations


def to_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        t = value.strip()
        digits = t[1:] if t.startswith("-") else t
        if digits and len(digits) <= 18 and digits.isascii() and digits.isdecimal():    # ①² などの Unicode 数字・巨大な数字列を int() に渡さない
            return int(t)
    return None


def to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value != "" else None
