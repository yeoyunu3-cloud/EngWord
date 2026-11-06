#!/bin/zsh
# 영단어 암기 트레이너 실행: 처음 한 번 환경을 만들고, 매번 빠진 패키지만 설치한 뒤 서버를 켭니다.
# AI 기능(사진 읽기, AI 대화)을 쓰려면 .env.example을 .env로 복사하고 값을 채우세요.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12 .venv || exit 1
fi
uv pip install -q --python .venv/bin/python -r requirements.txt || exit 1
(sleep 2 && open http://localhost:${PORT:-8001}) &
exec .venv/bin/python server.py
