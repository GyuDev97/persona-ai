#!/usr/bin/env bash
# GyuNexus 실행(macOS/Linux): 패키지 설치·대시보드 빌드가 필요하면 하고, 서버를 띄우고 브라우저를 연다.
# 사용: ./start.sh         → http://127.0.0.1:8000
#       ./start.sh dev     → 백엔드(--reload, 8000) + 프런트(Vite, 5173)
#       ./start.sh test    → pytest + 프런트 typecheck
set -euo pipefail
cd "$(dirname "$0")"

# venv: GYUNEXUS_VENV 로 바꿀 수 있다. 없으면 만든다.
VENV="${GYUNEXUS_VENV:-$HOME/Desktop/python/.venv}"
if [ ! -f "$VENV/bin/activate" ]; then
  echo "[GyuNexus] venv 가 없어 새로 만듭니다: $VENV"
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
PY="$VENV/bin/python"

if [ ! -f .env ]; then
  echo "[INFO] .env 가 없어 .env.example 을 복사했습니다. OPENAI_API_KEY 를 채우고 다시 실행하세요."
  cp .env.example .env
  exit 1
fi

"$PY" -c "import gyunexus" 2>/dev/null || {
  echo "[GyuNexus] 백엔드 패키지 설치 중..."
  "$PY" -m pip install -e "backend[dev]"
}

MODE="${1:-run}"

if [ "$MODE" = "test" ]; then
  rc=0
  (cd backend && "$PY" -m pytest -q) || rc=1
  (cd frontend && npm run typecheck) || rc=1
  exit $rc
fi

if [ "$MODE" = "dev" ]; then
  [ -d frontend/node_modules ] || (cd frontend && npm install)
  (cd backend && "$PY" -m uvicorn gyunexus.main:create_app --factory --reload --port 8000) &
  BACK=$!
  trap 'kill $BACK 2>/dev/null || true' EXIT INT TERM
  (sleep 4; open "http://localhost:5173" 2>/dev/null || xdg-open "http://localhost:5173" 2>/dev/null || true) &
  cd frontend && npm run dev
  exit 0
fi

if [ ! -f frontend/dist/index.html ]; then
  echo "[GyuNexus] 대시보드 빌드 중..."
  (cd frontend && { [ -d node_modules ] || npm install; } && npm run build)
fi

(sleep 3; open "http://127.0.0.1:8000" 2>/dev/null || xdg-open "http://127.0.0.1:8000" 2>/dev/null || true) &
cd backend
exec "$PY" -m uvicorn gyunexus.main:create_app --factory --host 0.0.0.0 --port 8000
