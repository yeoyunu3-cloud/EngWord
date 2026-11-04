"""영단어 암기 트레이너 — 로컬 백엔드

- GET  /                          : index.html 제공
- GET  /api/books                 : 단어책 목록과 Day 구성
- GET  /api/books/{book}/words    : 책 전체 단어 (단어, 품사, 뜻, 예문)
- GET  /api/books/{book}/days/{n} : Day n의 단어
- GET  /api/progress/{book}       : 학습 기록 (외운 단어, 틀린 횟수)
- PUT  /api/progress/{book}       : 학습 기록 저장
- POST /api/import                : 클래스카드 세트 링크로 단어책 추가 {"url": "..."}
- DELETE /api/books/{book}        : 가져온 단어책(cc-*) 삭제
- GET  /api/config                : 로그인용 Supabase 주소와 공개 키 (환경변수 SUPABASE_URL, SUPABASE_ANON_KEY)

단어책은 data/<책 id>/*.txt 파일을 이름 순서대로 읽어 만든다.
한 줄 형식: 단어|품사|뜻|예문   (#으로 시작하는 줄은 주석)
책 제목은 data/<책 id>/title.txt 가 있으면 그 내용, 없으면 BOOK_TITLES 또는 폴더 이름.
클래스카드에서 가져온 책은 data/cc-<세트 번호>/ 에 저장되고, 세트 전체가 Day 하나다.

Vercel(서버리스)에서는 코드 폴더가 읽기 전용이라 가져온 세트와 progress.db를 /tmp/engword 에 쓴다.
/tmp는 서버 인스턴스가 바뀌면 비워지므로, 거기 쓴 내용은 언제든 사라질 수 있다.

실행:  .venv/bin/python server.py   →  http://localhost:8001
"""
import os
import shutil
import sqlite3
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from classcard import CardSetError, fetch_set

ROOT = Path(__file__).parent
DATA = ROOT / "data"
STATE = Path(os.environ.get("ENGWORD_STATE_DIR") or ("/tmp/engword" if os.environ.get("VERCEL") else ROOT))
IMPORTED = DATA if STATE == ROOT else STATE / "data"
IMPORTED.mkdir(parents=True, exist_ok=True)
DB_PATH = STATE / "progress.db"
DAY_SIZE = 25
BOOK_TITLES = {"basic": "고교 필수 영단어"}

app = FastAPI(title="EngWord")


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
    return FileResponse(ROOT / "index.html")


@app.get("/api/config")
def config():
    # anon 키는 브라우저에 보여도 되는 공개 키다. 다른 사람 기록은 Supabase의 RLS 정책이 막는다
    return {"supabaseUrl": os.environ.get("SUPABASE_URL", ""),
            "supabaseKey": os.environ.get("SUPABASE_ANON_KEY", "")}


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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8001)))
