"""클래스카드 세트 가져오기 — 세트 링크에서 단어(카드 앞면)와 뜻(카드 뒷면)을 읽어 온다.

받는 링크 예:  https://battle.classcard.net/set/31507889
               https://www.classcard.net/set/31507889
               31507889   (세트 번호만)
어떤 링크든 세트 번호만 뽑아서 www.classcard.net 공개 세트 페이지를 읽는다.
"""
import html
import re
import urllib.error
import urllib.request

SET_RE = re.compile(r"classcard\.net/(?:[\w-]+/)*set/(\d+)")
CARD_RE = re.compile(
    r'flip-card-front">\s*<div class="card-content">(.*?)</div>\s*</div>\s*</div>'
    r'.*?flip-card-back">\s*<div class="card-content">(.*?)</div>\s*</div>\s*</div>',
    re.S)
TITLE_RE = re.compile(r"<title>\s*(?:클래스카드\s*\|\s*)?(.*?)\s*</title>", re.S)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


class CardSetError(Exception):
    pass


def set_id_of(link: str) -> str:
    link = link.strip()
    if link.isdigit():
        return link
    m = SET_RE.search(link)
    if not m:
        raise CardSetError("클래스카드 세트 링크가 아니에요. 예: https://www.classcard.net/set/31507889")
    return m.group(1)


def _text(fragment: str) -> str:
    # 카드 한 면에 여러 줄이 있으면 쉼표로 이어 붙인다 (뜻 채점이 쉼표 단위라서)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = html.unescape(re.sub(r"<[^>]+>", "", fragment))
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in fragment.splitlines()]
    # 단어책 파일은 | 로 칸을 나누므로 본문에서는 쓰지 않는다
    return ", ".join(ln for ln in lines if ln).replace("|", "/")


def parse(page: str) -> tuple[str, list[tuple[str, str]]]:
    m = TITLE_RE.search(page)
    title = html.unescape(m.group(1)) if m else ""
    cards = []
    for front, back in CARD_RE.findall(page):
        en, ko = _text(front), _text(back)
        if en and ko:
            cards.append((en, ko))
    return title, cards


def fetch_set(link: str) -> tuple[str, str, list[tuple[str, str]]]:
    """(세트 번호, 세트 제목, [(단어, 뜻), ...])"""
    set_id = set_id_of(link)
    req = urllib.request.Request(f"https://www.classcard.net/set/{set_id}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            page = r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as e:
        raise CardSetError(f"클래스카드에 접속하지 못했어요. ({e})") from e
    title, cards = parse(page)
    if not cards:
        raise CardSetError("단어를 찾지 못했어요. 비공개 세트이거나 링크가 잘못됐을 수 있어요.")
    return set_id, title or f"클래스카드 {set_id}", cards
