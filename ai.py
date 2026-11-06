"""AI 기능 — 사진에서 단어 읽기, 단어 2개로 대화 만들기.

이 파일에는 Claude 호출과, AI 출력을 믿지 않고 다시 검사하는 코드가 있다.
단어 목록의 자리 표시(~, 주어, 동사원형 같은 한글, B as well as A의 A/B)는 문장 검사에서 처리한다.
"""
import re

HANGUL = re.compile(r"[ㄱ-ㅎㅏ-ㅣ가-힣]")
GAP = None  # 단어 가운데에 있던 자리 표시(예: so 형용사 that)
BE_FORMS = r"(?:be|am|is|are|was|were|been|being)"
POSSESSIVE = r"(?:my|your|his|her|its|our|their|one's|\w+'s)"


def _tokens(w: str) -> list:
    """단어를 토큰으로 나눈다. 한글 자리 표시와 ~ 는 GAP, 양끝의 GAP과 단독 대문자 A/B는 버린다."""
    toks = [GAP if (HANGUL.search(t) or t == "~") else t for t in w.replace("~", " ~ ").split()]
    while toks and (toks[0] is GAP or toks[0] in ("A", "B")):
        toks.pop(0)
    while toks and (toks[-1] is GAP or toks[-1] in ("A", "B")):
        toks.pop()
    out = []
    for t in toks:  # 연속된 GAP은 하나로
        if t is GAP and out and out[-1] is GAP:
            continue
        out.append(t)
    return out


def clean_term(w: str) -> str:
    """AI에게 보여 줄 단어. 가운데 자리 표시는 ... 로 남긴다 (so ... that)."""
    return " ".join("..." if t is GAP else t for t in _tokens(w))


def _word_pattern(tok: str) -> str:
    low = tok.lower()
    if low == "one's":
        return POSSESSIVE
    forms = [re.escape(tok) + r"(?:s|es|d|ed|ing)?"]
    if low.endswith("e") and len(low) > 2:
        forms.append(re.escape(tok[:-1]) + "ing")
    if low.endswith("y") and len(low) > 2:
        forms.append(re.escape(tok[:-1]) + r"(?:ies|ied)")
    return "(?:" + "|".join(forms) + ")"


def term_regex(w: str) -> re.Pattern:
    """문장에서 단어(숙어)를 찾는 정규식. 동사 변화, be 동사 변화·생략, one's, 가운데 자리 표시를 허용한다."""
    toks = _tokens(w)
    lead_be = bool(toks) and toks[0].lower() == "be" and len(toks) > 1
    if lead_be:
        toks = toks[1:]
    parts, sep = [], r"\s+"
    for t in toks:
        if t is GAP:
            sep = r"\s+(?:\S+\s+){1,4}?"
            continue
        if parts:
            parts.append(sep)
        parts.append(_word_pattern(t))
        sep = r"\s+"
    body = "".join(parts)
    if lead_be:
        body = rf"(?:{BE_FORMS}\s+)?" + body
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def check_dialogue(lines: list, words: list) -> list:
    """대화 규칙 위반 사유 목록을 돌려준다. 비어 있으면 통과.

    규칙: 4줄, A·B·A·B 순서, 단어1이 든 줄 정확히 1개, 단어2가 든 줄 정확히 1개, 서로 다른 줄.
    나머지 2줄에는 두 단어가 모두 없어야 한다.
    """
    problems = []
    if not isinstance(lines, list) or len(lines) != 4:
        return ["대화가 4줄이 아님"]
    texts = []
    for k, ln in enumerate(lines):
        speaker = ln.get("speaker") if isinstance(ln, dict) else None
        text = ln.get("text") if isinstance(ln, dict) else None
        if speaker != "AB"[k % 2]:
            problems.append(f"{k + 1}번째 줄 화자 순서가 틀림")
        if not isinstance(text, str) or not text.strip():
            problems.append(f"{k + 1}번째 줄이 비어 있음")
            text = ""
        texts.append(text)
    hits = []
    for w in words:
        rx = term_regex(w)
        rows = [k for k, t in enumerate(texts) if rx.search(t)]
        if len(rows) != 1:
            problems.append(f"'{w}'이(가) 든 줄이 {len(rows)}개")
        hits.append(rows)
    if len(hits) == 2 and len(hits[0]) == 1 and hits[0] == hits[1]:
        problems.append("두 단어가 같은 줄에 있음")
    return problems
