import base64

import pytest

import ai

JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 100).decode()
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()
WEBP = base64.b64encode(b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 100).decode()
PAIR = [{"w": "infect", "ko": "감염시키다"}, {"w": "take action", "ko": "조치를 취하다"}]
CODE = "test-passcode-123"
H = {"X-AI-Passcode": CODE}


@pytest.fixture(autouse=True)
def reset_limits(server_mod):
    server_mod.reset_limits()


@pytest.fixture
def ai_on(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AI_PASSCODE", CODE)


@pytest.fixture
def fake_ai(monkeypatch):
    calls = {"photo": [], "dialogue": []}

    def extract(image_b64, media_type):
        calls["photo"].append(media_type)
        return [{"w": "abandon", "ko": "버리다"}]

    def dialogue(words):
        calls["dialogue"].append(words)
        return {"lines": [], "definitions": []}

    monkeypatch.setattr(ai, "extract_words", extract)
    monkeypatch.setattr(ai, "make_dialogue", dialogue)
    return calls


@pytest.mark.parametrize("key,code,expected", [
    (None, None, False), ("sk", None, False), (None, "c", False), ("sk", "c", True)])
def test_status(client, monkeypatch, key, code, expected):
    if key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    if code:
        monkeypatch.setenv("AI_PASSCODE", code)
    assert client.get("/api/ai-status").json() == {"enabled": expected}


def test_key_only_is_503(client, monkeypatch, fake_ai):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    r = client.post("/api/dialogue", json={"words": PAIR}, headers=H)
    assert r.status_code == 503
    assert r.json()["detail"] == "AI 기능이 아직 설정되지 않았어요"
    assert fake_ai["dialogue"] == []


def test_wrong_passcode_401(client, ai_on, fake_ai):
    r = client.post("/api/dialogue", json={"words": PAIR}, headers={"X-AI-Passcode": "nope"})
    assert r.status_code == 401
    assert fake_ai["dialogue"] == []


def test_missing_header_401(client, ai_on, fake_ai):
    assert client.post("/api/dialogue", json={"words": PAIR}).status_code == 401


def test_passcode_bruteforce_429(client, ai_on, fake_ai):
    for _ in range(10):
        assert client.post("/api/dialogue", json={"words": PAIR}, headers={"X-AI-Passcode": "x"}).status_code == 401
    r = client.post("/api/dialogue", json={"words": PAIR}, headers=H)
    assert r.status_code == 429
    assert r.json()["detail"] == "잠시 후 다시 시도해 주세요"


def test_call_limit_429(client, ai_on, fake_ai):
    for _ in range(30):
        assert client.post("/api/dialogue", json={"words": PAIR}, headers=H).status_code == 200
    assert client.post("/api/dialogue", json={"words": PAIR}, headers=H).status_code == 429
    assert len(fake_ai["dialogue"]) == 30


def test_limits_are_per_ip(client, ai_on, fake_ai):
    for _ in range(10):
        client.post("/api/dialogue", json={"words": PAIR}, headers={"X-AI-Passcode": "x", "X-Forwarded-For": "1.1.1.1"})
    r = client.post("/api/dialogue", json={"words": PAIR}, headers={**H, "X-Forwarded-For": "2.2.2.2"})
    assert r.status_code == 200


def test_fake_png_is_400(client, ai_on, fake_ai):
    svg = base64.b64encode(b"<svg onload=alert(1)>").decode()
    r = client.post("/api/photo-words", json={"image": svg, "mediaType": "image/png"}, headers=H)
    assert r.status_code == 400
    assert fake_ai["photo"] == []


def test_not_base64_is_400(client, ai_on, fake_ai):
    r = client.post("/api/photo-words", json={"image": "!!!not base64!!!", "mediaType": "image/jpeg"}, headers=H)
    assert r.status_code == 400


def test_too_large_422(client, ai_on, fake_ai):
    r = client.post("/api/photo-words", json={"image": "A" * 4_000_001, "mediaType": "image/jpeg"}, headers=H)
    assert r.status_code == 422


@pytest.mark.parametrize("data,kind", [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")])
def test_photo_ok_uses_sniffed_type(client, ai_on, fake_ai, data, kind):
    r = client.post("/api/photo-words", json={"image": data, "mediaType": "image/gif"}, headers=H)
    assert r.status_code == 200
    assert r.json() == {"words": [{"w": "abandon", "ko": "버리다"}]}
    assert fake_ai["photo"] == [kind]


@pytest.mark.parametrize("words", [PAIR[:1], PAIR + PAIR[:1], [{"w": "x" * 61, "ko": ""}, PAIR[1]],
                                   [{"w": "", "ko": ""}, PAIR[1]], [{"w": "a", "ko": "k" * 101}, PAIR[1]]])
def test_dialogue_input_validation_422(client, ai_on, fake_ai, words):
    assert client.post("/api/dialogue", json={"words": words}, headers=H).status_code == 422


def test_ai_error_maps_status(client, ai_on, monkeypatch):
    def boom(words):
        raise ai.AIError(502, "만들지 못했어요. 다시 시도해 주세요")
    monkeypatch.setattr(ai, "make_dialogue", boom)
    r = client.post("/api/dialogue", json={"words": PAIR}, headers=H)
    assert r.status_code == 502
    assert r.json() == {"detail": "만들지 못했어요. 다시 시도해 주세요"}


def test_dialogue_ok(client, ai_on, fake_ai):
    r = client.post("/api/dialogue", json={"words": PAIR}, headers=H)
    assert r.status_code == 200
    assert fake_ai["dialogue"] == [PAIR]
