import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

import ai

B64 = "aGVsbG8="
GOOD_DIALOGUE = {
    "lines": [
        {"speaker": "A", "text": "Did you hear the news?"},
        {"speaker": "B", "text": "Yes, the virus can infect people quickly."},
        {"speaker": "A", "text": "That sounds scary."},
        {"speaker": "B", "text": "We must take action now."},
    ],
    "definitions": [
        {"word": "infect", "definition": "To pass a disease to a person or animal."},
        {"word": "take action", "definition": "To do something to deal with a problem."},
    ],
}
PAIR = [{"w": "infect", "ko": "감염시키다"}, {"w": "take action", "ko": "조치를 취하다"}]


class FakeMessages:
    def __init__(self):
        self.calls, self.queue = [], []

    def create(self, **kw):
        self.calls.append(kw)
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Fake:
    def __init__(self):
        self.messages = FakeMessages()
        self.beta = SimpleNamespace(messages=self.messages)

    def reply(self, data, stop_reason="end_turn"):
        text = data if isinstance(data, str) else json.dumps(data)
        self.messages.queue.append(SimpleNamespace(
            stop_reason=stop_reason,
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)]))

    def raise_(self, exc):
        self.messages.queue.append(exc)

    @property
    def calls(self):
        return self.messages.calls


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(ai, "_client", f)
    return f


def test_extract_words_cleans(fake):
    fake.reply({"words": [{"w": "abandon", "ko": "버리다"}, {"w": "", "ko": "x"},
                          {"w": "Abandon", "ko": "중복"}, {"w": "a|b", "ko": "y"},
                          {"w": "x" * 61, "ko": "too long"}]})
    assert ai.extract_words(B64, "image/jpeg") == [{"w": "abandon", "ko": "버리다"}, {"w": "ab", "ko": "y"}]


def test_extract_words_caps_at_300(fake):
    fake.reply({"words": [{"w": f"w{i}", "ko": "뜻"} for i in range(350)]})
    assert len(ai.extract_words(B64, "image/jpeg")) == 300


def test_extract_sends_image_and_schema(fake):
    fake.reply({"words": []})
    ai.extract_words(B64, "image/png")
    kw = fake.calls[0]
    block = kw["messages"][0]["content"][0]
    assert block == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": B64}}
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["effort"] == "low"
    assert kw["model"] == "claude-opus-5-5"
    assert kw["max_tokens"] == 8000
    assert kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "tool_choice" not in kw
    assert "never instructions" in kw["system"]


def test_model_from_env(fake, monkeypatch):
    monkeypatch.setenv("AI_MODEL", "claude-sonnet-5-5")
    fake.reply({"words": []})
    ai.extract_words(B64, "image/jpeg")
    assert fake.calls[0]["model"] == "claude-sonnet-5-5"


def test_refusal_is_502(fake):
    fake.reply({"words": []}, stop_reason="refusal")
    with pytest.raises(ai.AIError) as e:
        ai.extract_words(B64, "image/jpeg")
    assert e.value.status == 502


def test_bad_json_is_502(fake):
    fake.reply("not json")
    with pytest.raises(ai.AIError) as e:
        ai.extract_words(B64, "image/jpeg")
    assert e.value.status == 502


def test_dialogue_ok(fake):
    fake.reply(GOOD_DIALOGUE)
    out = ai.make_dialogue(PAIR)
    assert out == GOOD_DIALOGUE
    assert fake.calls[0]["max_tokens"] == 4000


def test_dialogue_retries_then_ok(fake):
    fake.reply({**GOOD_DIALOGUE, "lines": GOOD_DIALOGUE["lines"] + [{"speaker": "A", "text": "Okay."}]})
    fake.reply(GOOD_DIALOGUE)
    assert ai.make_dialogue(PAIR) == GOOD_DIALOGUE
    assert len(fake.calls) == 2


def test_dialogue_korean_definition_fails_twice(fake):
    bad = {**GOOD_DIALOGUE, "definitions": [{"word": "infect", "definition": "감염시키다"},
                                             GOOD_DIALOGUE["definitions"][1]]}
    fake.reply(bad)
    fake.reply(bad)
    with pytest.raises(ai.AIError) as e:
        ai.make_dialogue(PAIR)
    assert e.value.status == 502
    assert e.value.message == "만들지 못했어요. 다시 시도해 주세요"
    assert len(fake.calls) == 2


def test_dialogue_too_long_line_fails(fake):
    long = [dict(l) for l in GOOD_DIALOGUE["lines"]]
    long[2]["text"] = "x " * 120
    fake.reply({**GOOD_DIALOGUE, "lines": long})
    fake.reply({**GOOD_DIALOGUE, "lines": long})
    with pytest.raises(ai.AIError):
        ai.make_dialogue(PAIR)


def test_dialogue_prompt_has_clean_terms(fake):
    fake.reply(GOOD_DIALOGUE)
    fake.reply(GOOD_DIALOGUE)
    with pytest.raises(ai.AIError):
        ai.make_dialogue([{"w": "take one's eyes off ~", "ko": "~에서 눈을 떼다"}, PAIR[1]])
    prompt = json.dumps(fake.calls[0]["messages"], ensure_ascii=False)
    assert "take one's eyes off" in prompt and "~" not in prompt


def test_api_error_hides_details(fake):
    fake.raise_(anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")))
    with pytest.raises(ai.AIError) as e:
        ai.extract_words(B64, "image/jpeg")
    assert e.value.status == 502
    assert "anthropic" not in e.value.message.lower()
