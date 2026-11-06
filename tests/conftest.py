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
    # server는 import할 때 로컬 .env를 읽는다. 여기서 한 번 먼저 import해 두면
    # 테스트마다 도는 no_ai_env가 그 값을 지운 상태에서 테스트가 시작된다
    import server  # noqa: F401


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
