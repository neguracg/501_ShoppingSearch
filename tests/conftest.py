import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture(autouse=True)
def _no_real_yahoo_key(monkeypatch, tmp_path_factory):
    """試験は実の Yahoo の鍵ファイル（.env・.env.yahoo.local）を見ない。見えると、本体のフォルダで走らせた時に
    『Yahoo の鍵が無い＝楽天だけ』を前提にした試験が実 API を呼んでしまう。環境変数 YAHOO_CLIENT_ID は消してから始めるが、
    試験が自分で setenv すれば効く（鍵の読み込み自体は本物の loader を、存在しないパス 2 つで呼ぶ）。"""
    from shopping import config, malls
    nowhere = tmp_path_factory.getbasetemp() / "no-such-env-file"
    real = config.load_yahoo_credentials
    monkeypatch.delenv(config.YAHOO_VAR, raising=False)
    monkeypatch.setattr(malls, "load_yahoo_credentials",
                        lambda *a, **k: real(env_path=nowhere / ".env", local_path=nowhere / ".env.yahoo.local"))
