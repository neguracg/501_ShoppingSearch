import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture(autouse=True)
def _no_real_yahoo_key(monkeypatch):
    """試験は実の Yahoo の鍵（環境変数・.env・.env.yahoo.local）を見ない。見えると、本体のフォルダで走らせた時に
    『Yahoo の鍵が無い＝楽天だけ』を前提にした試験が実 API を呼んでしまう。鍵が要る試験は自分で monkeypatch する。"""
    from shopping import config, malls
    monkeypatch.delenv(config.YAHOO_VAR, raising=False)
    monkeypatch.setattr(malls, "load_yahoo_credentials", lambda *a, **k: config.YahooCredentials(""))
