# @owns 認証情報の読み込み（.env/環境変数）
"""認証情報の読み込み。.env または環境変数から。値は repr/str に出さない。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_ID_VAR = "RAKUTEN_APPLICATION_ID"
ACCESS_KEY_VAR = "RAKUTEN_ACCESS_KEY"
DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


@dataclass(frozen=True)
class RakutenCredentials:
    app_id: str
    access_key: str

    def __repr__(self) -> str:
        return (f"RakutenCredentials(app_id={'***' if self.app_id else ''!r}, "
                f"access_key={'***' if self.access_key else ''!r})")

    __str__ = __repr__

    @property
    def present(self) -> bool:
        return bool(self.app_id and self.access_key)


def parse_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE 形式の最小パーサー。コメント行・空行・引用符を扱う。無ければ空 dict。"""
    values: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_credentials(env_path: Path | str | None = None) -> RakutenCredentials:
    """優先順位: 環境変数 > .env ファイル。どちらも無ければ空の認証情報（present=False）。"""
    file_values = parse_env_file(Path(env_path) if env_path else DEFAULT_ENV_PATH)
    app_id = os.environ.get(APP_ID_VAR) or file_values.get(APP_ID_VAR, "")
    access_key = os.environ.get(ACCESS_KEY_VAR) or file_values.get(ACCESS_KEY_VAR, "")
    return RakutenCredentials(app_id=app_id.strip(), access_key=access_key.strip())


# ---- Yahoo!ショッピング（WP17 Y8） ----
YAHOO_VAR = "YAHOO_CLIENT_ID"
YAHOO_LOCAL_ENV_PATH = DEFAULT_ENV_PATH.parent / ".env.yahoo.local"     # ローカルの PoC 用（git 管理外。ASCII 1 行 YAHOO_CLIENT_ID=<値>）


@dataclass(frozen=True)
class YahooCredentials:
    client_id: str

    def __repr__(self) -> str:
        return f"YahooCredentials(client_id={'***' if self.client_id else ''!r})"

    __str__ = __repr__

    @property
    def present(self) -> bool:
        return bool(self.client_id)


def load_yahoo_credentials(env_path: Path | str | None = None,
                           local_path: Path | str | None = None) -> YahooCredentials:
    """優先順位: 環境変数 YAHOO_CLIENT_ID > .env > .env.yahoo.local。どれも無ければ空（present=False。Yahoo は無効になる）。"""
    value = os.environ.get(YAHOO_VAR, "").strip()
    for path, default in ((env_path, DEFAULT_ENV_PATH), (local_path, YAHOO_LOCAL_ENV_PATH)):
        if value:
            break
        value = parse_env_file(Path(path) if path else default).get(YAHOO_VAR, "").strip()
    return YahooCredentials(client_id=value)
