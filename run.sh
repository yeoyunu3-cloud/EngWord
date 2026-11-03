#!/bin/zsh
# 영단어 암기 트레이너 실행: 처음 한 번만 환경을 만든 뒤 서버를 켭니다.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt || exit 1
fi
(sleep 2 && open http://localhost:${PORT:-8001}) &
exec .venv/bin/python server.py
