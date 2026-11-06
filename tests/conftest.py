import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

AI_ENV = ("ANTHROPIC_API_KEY", "AI_PASSCODE", "AI_MODEL")


@pytest.fixture(scope="session", autouse=True)
def _state_dir(tmp_path_factory):
    # 서버가 progress.db와 가져온 세트를 테스트용 임시 폴더에 쓰게 한다
    os.environ["ENGWORD_STATE_DIR"] = str(tmp_path_factory.mktemp("state"))


@pytest.fixture(autouse=True)
def no_ai_env(monkeypatch):
    for k in AI_ENV:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def server_mod():
    import server
    return server


@pytest.fixture
def client(server_mod):
    from fastapi.testclient import TestClient
    return TestClient(server_mod.app)
