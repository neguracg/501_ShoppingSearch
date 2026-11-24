# @owns モールAPIへの GET と JSON 応答の読み取り（外部通信の失敗を種別だけにする）
"""URL・ヘッダー・例外本文・応答本文は戻り値にも例外にも出さない（preflight.py の作法）。
リダイレクトは追わない（URL に秘密が入るため）。モール固有の知識（エンドポイント・項目名）は持たない。"""
from __future__ import annotations

import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .base import AdapterError

MAX_RESPONSE_BYTES = 5_000_000
TIMEOUT_SEC = 20


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_kind(code: int) -> str:
    return f"http_{code}"


def fetch_json(req: Request, *, opener=None, kind_for_status=http_kind,
               timeout: float = TIMEOUT_SEC, max_bytes: int = MAX_RESPONSE_BYTES) -> object:
    """失敗は except 内で raise せず kind だけ持ち出す（__context__ に元例外を残さない）。
    HTTP の状態コードは kind_for_status(code) で種別にする（モールごとの語）。"""
    opener = opener or build_opener(NoRedirect())
    kind = None
    raw = b""
    try:
        with opener.open(req, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                kind = kind_for_status(status)
            else:
                raw = response.read(max_bytes + 1)
    except HTTPError as exc:
        kind = kind_for_status(exc.code)
        exc.close()
    except (TimeoutError, socket.timeout):
        kind = "timeout"
    except URLError as exc:
        reason = getattr(exc, "reason", None)
        kind = "timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "network_error"
    except OSError:
        kind = "network_error"
    if kind is None and len(raw) > max_bytes:
        kind = "unexpected_response"
    if kind is None:
        try:
            return json.loads(raw)
        except (UnicodeError, ValueError):  # JSONDecodeError は ValueError の子
            kind = "invalid_json"
    raise AdapterError(kind)
