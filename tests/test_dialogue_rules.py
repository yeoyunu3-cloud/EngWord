from ai import check_dialogue, clean_term, term_regex

OK = [
    {"speaker": "A", "text": "Did you hear the news?"},
    {"speaker": "B", "text": "Yes, the virus can infect people quickly."},
    {"speaker": "A", "text": "That sounds scary."},
    {"speaker": "B", "text": "We must take action now."},
]
WORDS = ["infect", "take action"]


def test_valid_dialogue_passes():
    assert check_dialogue(OK, WORDS) == []


def test_three_lines_fails():
    assert check_dialogue(OK[:3], WORDS)


def test_five_lines_fails():
    assert check_dialogue(OK + [{"speaker": "A", "text": "Okay."}], WORDS)


def test_speaker_order_fails():
    assert check_dialogue([{**OK[0], "speaker": "B"}] + OK[1:], WORDS)


def test_both_words_same_line_fails():
    lines = OK[:3] + [{"speaker": "B", "text": "It can infect us, so take action."}]
    lines[1] = {"speaker": "B", "text": "Yes, it spreads quickly."}
    assert check_dialogue(lines, WORDS)


def test_word_in_extra_line_fails():
    lines = OK[:2] + [{"speaker": "A", "text": "Can it infect pets too?"}] + OK[3:]
    assert check_dialogue(lines, WORDS)


def test_missing_word_fails():
    lines = OK[:3] + [{"speaker": "B", "text": "We must be careful."}]
    assert check_dialogue(lines, WORDS)


def test_empty_text_fails():
    lines = OK[:2] + [{"speaker": "A", "text": "  "}] + OK[3:]
    assert check_dialogue(lines, WORDS)


def test_clean_term_strips_placeholders():
    assert clean_term("take one's eyes off ~") == "take one's eyes off"
    assert clean_term("tend to 동사원형") == "tend to"
    assert clean_term("B as well as A") == "as well as"


def test_regex_korean_placeholder_tail():
    assert term_regex("tend to 동사원형").search("People tend to believe it.")


def test_regex_be_conjugated():
    assert term_regex("be on the rise").search("Prices are on the rise.")


def test_regex_be_omitted():
    assert term_regex("be on the rise").search("Sea levels on the rise worry me.")


def test_regex_possessive():
    assert term_regex("take one's eyes off ~").search("I couldn't take my eyes off it.")


def test_regex_middle_placeholder_gap():
    assert term_regex("so 형용사 that 주어 동사").search("It was so cold that we left.")


def test_regex_edge_letters():
    assert term_regex("B as well as A").search("She sings as well as dances.")


def test_regex_inflection():
    assert term_regex("infect").search("It infected him.")


def test_regex_word_boundary():
    assert not term_regex("art").search("She is smart.")


def test_regex_case_insensitive():
    assert term_regex("nevertheless").search("Nevertheless, she won.")


def test_regex_finds_every_seo_answer():
    # index.html의 서술형 문장 156개: 빈칸을 정답으로 채우면 term_regex가 찾아야 한다
    import json
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
    body = re.search(r"const SEO=\{(.*?)\n\};", src, re.S).group(1)
    entries = re.findall(r'^("[^"]+"):(\[.*\]),?$', body, re.M)
    assert len(entries) == 156
    missed = []
    for k, v in entries:
        word, (ans, sent, *_) = json.loads(k), json.loads(v)
        parts = ans.split(" ") if sent.count("___") > 1 else [ans]
        filled = sent
        for p in parts:
            filled = filled.replace("___", p, 1)
        if not term_regex(word).search(filled):
            missed.append((word, filled))
    assert missed == []
