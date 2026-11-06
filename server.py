"""영단어 암기 트레이너 — 로컬 백엔드

- GET  /                          : index.html 제공
- GET  /api/books                 : 단어책 목록과 Day 구성
- GET  /api/books/{book}/words    : 책 전체 단어 (단어, 품사, 뜻, 예문)
- GET  /api/books/{book}/days/{n} : Day n의 단어
- GET  /api/progress/{book}       : 학습 기록 (외운 단어, 틀린 횟수)
- PUT  /api/progress/{book}       : 학습 기록 저장
- POST /api/import                : 클래스카드 세트 링크로 단어책 추가 {"url": "..."}
- DELETE /api/books/{book}        : 가져온 단어책(cc-*) 삭제

단어책은 data/<책 id>/*.txt 파일을 이름 순서대로 읽어 만든다.
한 줄 형식: 단어|품사|뜻|예문   (#으로 시작하는 줄은 주석)
책 제목은 data/<책 id>/title.txt 가 있으면 그 내용, 없으면 BOOK_TITLES 또는 폴더 이름.
클래스카드에서 가져온 책은 data/cc-<세트 번호>/ 에 저장되고, 세트 전체가 Day 하나다.

Vercel(서버리스)에서는 코드 폴더가 읽기 전용이라 가져온 세트와 progress.db를 /tmp/engword 에 쓴다.
/tmp는 서버 인스턴스가 바뀌면 비워지므로, 거기 쓴 내용은 언제든 사라질 수 있다.

실행:  .venv/bin/python server.py   →  http://localhost:8001
"""
import base64
import binascii
import hmac
import os
import shutil
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints

import ai
from classcard import CardSetError, fetch_set

ROOT = Path(__file__).parent


def load_dotenv(path: Path) -> None:
    """로컬 .env(KEY=VALUE, # 주석)를 환경 변수로 읽는다. 이미 있는 값은 덮어쓰지 않는다."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


load_dotenv(ROOT / ".env")

# 모든 응답에 붙이는 보안 헤더. 화면은 인라인 script/style을 쓰고 폰트만 Google Fonts에서 받는다
SECURITY_HEADERS = {
    "Content-Security-Policy": "; ".join([
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
    ]),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
DATA = ROOT / "data"
STATE = Path(os.environ.get("ENGWORD_STATE_DIR") or ("/tmp/engword" if os.environ.get("VERCEL") else ROOT))
IMPORTED = DATA if STATE == ROOT else STATE / "data"
IMPORTED.mkdir(parents=True, exist_ok=True)
DB_PATH = STATE / "progress.db"
DAY_SIZE = 25
BOOK_TITLES = {"basic": "고교 필수 영단어"}

app = FastAPI(title="EngWord")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


def load_books() -> dict:
    books = {}
    # 같은 이름이면 IMPORTED 쪽(새로 가져온 내용)이 이긴다
    folders = {p.name: p for d in (DATA, IMPORTED) for p in d.iterdir() if p.is_dir()}
    for folder in (folders[k] for k in sorted(folders)):
        words, seen = [], set()
        for f in sorted(folder.glob("*.txt")):
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) != 4 or parts[0].lower() in seen:
                    continue
                seen.add(parts[0].lower())
                words.append({"w": parts[0], "pos": parts[1], "ko": parts[2], "ex": parts[3]})
        if words:
            title_file = folder / "title.txt"
            title = title_file.read_text(encoding="utf-8").strip() if title_file.exists() else ""
            # 가져온 세트는 시험 범위 하나라서 Day로 나누지 않는다
            day_size = len(words) if folder.name.startswith("cc-") else DAY_SIZE
            books[folder.name] = {"title": title or BOOK_TITLES.get(folder.name, folder.name),
                                  "words": words, "daySize": day_size}
    return books


BOOKS = load_books()

db_lock = threading.Lock()
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS progress (
    book TEXT NOT NULL, word TEXT NOT NULL,
    mastered INTEGER NOT NULL DEFAULT 0, wrong INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (book, word))""")
db.commit()


def days_of(book: dict) -> list[dict]:
    n, size = len(book["words"]), book["daySize"]
    return [{"day": d + 1, "count": min(size, n - d * size)} for d in range((n + size - 1) // size)]


def summary(book_id: str) -> dict:
    b = BOOKS[book_id]
    return {"id": book_id, "title": b["title"], "count": len(b["words"]), "daySize": b["daySize"],
            "days": days_of(b), "imported": book_id.startswith("cc-")}


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/books")
def books():
    return [summary(k) for k in BOOKS]


@app.get("/api/books/{book}/words")
def book_words(book: str):
    b = BOOKS.get(book)
    if not b:
        raise HTTPException(404, "없는 단어책이에요.")
    return {"book": book, "words": b["words"]}


@app.get("/api/books/{book}/days/{day}")
def day_words(book: str, day: int):
    b = BOOKS.get(book)
    if not b:
        raise HTTPException(404, "없는 단어책이에요.")
    start = (day - 1) * b["daySize"]
    if day < 1 or start >= len(b["words"]):
        raise HTTPException(404, "없는 Day예요.")
    return {"book": book, "day": day, "words": b["words"][start:start + b["daySize"]]}


class ImportReq(BaseModel):
    url: str


@app.post("/api/import")
def import_set(req: ImportReq):
    global BOOKS
    try:
        set_id, title, cards = fetch_set(req.url)
    except CardSetError as e:
        raise HTTPException(400, str(e))
    book_id = f"cc-{set_id}"
    folder = IMPORTED / book_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "title.txt").write_text(title + "\n", encoding="utf-8")
    # 클래스카드 카드는 품사·예문이 없어서 그 칸은 비워 둔다. 같은 링크를 다시 넣으면 새 내용으로 덮어쓴다
    (folder / "words.txt").write_text("".join(f"{en}||{ko}|\n" for en, ko in cards), encoding="utf-8")
    BOOKS = load_books()
    # 서버리스에서는 다음 요청이 다른 인스턴스로 갈 수 있어서 단어까지 한 번에 돌려준다
    return {**summary(book_id), "words": BOOKS[book_id]["words"]}


@app.delete("/api/books/{book}")
def delete_book(book: str):
    global BOOKS
    if not book.startswith("cc-") or book not in BOOKS:
        raise HTTPException(404, "가져온 단어책만 지울 수 있어요.")
    if not (IMPORTED / book).is_dir():
        raise HTTPException(403, "저장소에 들어 있는 세트는 화면에서 지울 수 없어요.")
    shutil.rmtree(IMPORTED / book)
    BOOKS = load_books()
    reset_progress(book)
    return {"ok": True}


@app.get("/api/progress/{book}")
def get_progress(book: str):
    with db_lock:
        rows = db.execute("SELECT word, mastered, wrong FROM progress WHERE book = ?", (book,)).fetchall()
    return {w: {"m": m, "x": x} for w, m, x in rows}


class Entry(BaseModel):
    m: int = 0
    x: int = 0


@app.put("/api/progress/{book}")
def put_progress(book: str, items: dict[str, Entry]):
    with db_lock:
        db.executemany(
            """INSERT INTO progress (book, word, mastered, wrong) VALUES (?, ?, ?, ?)
               ON CONFLICT(book, word) DO UPDATE SET mastered = excluded.mastered, wrong = excluded.wrong""",
            [(book, w, e.m, e.x) for w, e in items.items()])
        db.commit()
    return {"saved": len(items)}


@app.delete("/api/progress/{book}")
def reset_progress(book: str):
    with db_lock:
        db.execute("DELETE FROM progress WHERE book = ?", (book,))
        db.commit()
    return {"ok": True}


# ---------- AI 기능 (사진으로 단어 읽기, 대화 만들기) ----------
# 키(ANTHROPIC_API_KEY)와 접근 코드(AI_PASSCODE)가 둘 다 있어야 켜진다. 키만 있으면 잠겨 있다.
# 호출 제한은 서버 인스턴스마다 따로 센다(서버리스라 완벽하지 않음). 최종 상한은 Anthropic Console 월 한도.
LIMIT_WINDOW = 600  # 10분
MAX_CODE_FAILS = 10
MAX_AI_CALLS = 30
_limit_lock = threading.Lock()
_code_fails: dict[str, deque] = {}
_ai_calls: dict[str, deque] = {}


def reset_limits() -> None:
    with _limit_lock:
        _code_fails.clear()
        _ai_calls.clear()


def _recent(store: dict, ip: str, now: float) -> deque:
    q = store.setdefault(ip, deque())
    while q and now - q[0] > LIMIT_WINDOW:
        q.popleft()
    return q


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def ai_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("AI_PASSCODE"))


def ai_guard(request: Request) -> None:
    if not ai_enabled():
        raise HTTPException(503, "AI 기능이 아직 설정되지 않았어요")
    ip, now = _client_ip(request), time.monotonic()
    given = request.headers.get("x-ai-passcode", "")
    with _limit_lock:
        fails = _recent(_code_fails, ip, now)
        if len(fails) >= MAX_CODE_FAILS:
            raise HTTPException(429, "잠시 후 다시 시도해 주세요")
        if not hmac.compare_digest(given.encode(), os.environ["AI_PASSCODE"].encode()):
            fails.append(now)
            raise HTTPException(401, "접근 코드가 맞지 않아요")
        calls = _recent(_ai_calls, ip, now)
        if len(calls) >= MAX_AI_CALLS:
            raise HTTPException(429, "잠시 후 다시 시도해 주세요")
        calls.append(now)


def sniff_image(data: bytes) -> str | None:
    """파일 앞부분 바이트로 실제 형식을 알아낸다. 요청에 적힌 형식은 믿지 않는다."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _ai_call(fn, *args):
    try:
        return fn(*args)
    except ai.AIError as e:
        raise HTTPException(e.status, e.message) from None


class PhotoReq(BaseModel):
    image: str = Field(max_length=4_000_000)
    mediaType: str = Field(default="", max_length=50)


Word = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Meaning = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


class WordItem(BaseModel):
    w: Word
    ko: Meaning = ""


class DialogueReq(BaseModel):
    words: list[WordItem] = Field(min_length=2, max_length=2)


@app.get("/api/ai-status")
def ai_status():
    return {"enabled": ai_enabled()}


@app.post("/api/photo-words")
def photo_words(req: PhotoReq, request: Request):
    ai_guard(request)
    try:
        data = base64.b64decode(req.image, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "사진 파일만 올릴 수 있어요 (JPEG, PNG, WebP)") from None
    kind = sniff_image(data)
    if not kind:
        raise HTTPException(400, "사진 파일만 올릴 수 있어요 (JPEG, PNG, WebP)")
    # 사진은 메모리에서만 쓰고 저장하지 않는다
    return {"words": _ai_call(ai.extract_words, req.image, kind)}


@app.post("/api/dialogue")
def dialogue(req: DialogueReq, request: Request):
    ai_guard(request)
    if not all(ai.term_ok(w.w) for w in req.words):
        raise HTTPException(400, "영어 단어가 없는 항목은 대화에 쓸 수 없어요")
    return _ai_call(ai.make_dialogue, [w.model_dump() for w in req.words])


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8001)))
