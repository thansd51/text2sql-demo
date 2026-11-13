#!/usr/bin/env bash
# 서버를 실행한다. 기본은 만들어 둔 화면(frontend/dist)을 함께 제공한다.
# 사용법:
#   ./scripts/run.sh          서버 + 화면 (http://127.0.0.1:8085)
#   ./scripts/run.sh --dev    화면 개발 서버(Vite, 5173)도 같이 띄우고, 코드를 고치면 서버가 자동 재시작
# 환경변수: APP_HOST(기본 127.0.0.1), APP_PORT(기본 8085). --dev에서 화면은 8085로 연결되므로 포트를 바꾸지 마세요.
set -euo pipefail
cd "$(dirname "$0")/.."

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8085}"

if [ ! -f .env ]; then
  echo ".env가 없습니다. 먼저 ./scripts/setup.sh를 실행하세요."
  exit 1
fi

if [ "${1:-}" = "--dev" ]; then
  (cd frontend && npm run dev -- --host 127.0.0.1) &
  vite_pid=$!
  trap 'kill "$vite_pid" 2>/dev/null || true' EXIT INT TERM
  echo "화면(개발):  http://127.0.0.1:5173"
  echo "API:         http://${APP_HOST}:${APP_PORT}"
  uv run uvicorn text2sql.main:app --reload --host "$APP_HOST" --port "$APP_PORT"
else
  if [ ! -f frontend/dist/index.html ]; then
    echo "화면 빌드(frontend/dist)가 없습니다. ./scripts/setup.sh를 실행하거나 (cd frontend && npm run build)를 하세요."
    exit 1
  fi
  echo "접속: http://${APP_HOST}:${APP_PORT}   (종료: Ctrl+C)"
  exec uv run uvicorn text2sql.main:app --host "$APP_HOST" --port "$APP_PORT"
fi
