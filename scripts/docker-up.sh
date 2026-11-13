#!/usr/bin/env bash
# 앱과 로컬 모델을 Docker(compose)로 한 번에 띄운다. 파이썬·Node 설치가 필요 없다.
# 사용법: ./scripts/docker-up.sh      (먼저 ./scripts/download-model.sh로 모델을 받아 두세요)
# 환경변수(선택): APP_PORT(기본 8085) MODEL_DIR(기본 ./models) LLM_THREADS(기본 4) LLM_CTX(기본 16384)
#                 TEXT2SQL_ACCESS_KEY (없으면 무작위로 만들어 화면에 한 번 보여 줍니다)
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "[없음] docker 또는 docker compose — https://docs.docker.com/engine/install/ubuntu/ 를 참고해 설치하세요."
  exit 1
fi

MODEL_DIR="${MODEL_DIR:-models}"
MODEL_FILE="${MODEL_FILE:-Qwen3-4B-Instruct-2507-Q4_K_M.gguf}"
if [ ! -f "${MODEL_DIR}/${MODEL_FILE}" ]; then
  echo "모델 파일이 없습니다: ${MODEL_DIR}/${MODEL_FILE}"
  echo "먼저 ./scripts/download-model.sh를 실행하세요."
  exit 1
fi

# 접속 키: 환경변수 → .env → 새로 만들기 순서로 찾는다
generated=0
if [ -z "${TEXT2SQL_ACCESS_KEY:-}" ] && ! { [ -f .env ] && grep -qE '^TEXT2SQL_ACCESS_KEY=.+' .env; }; then
  TEXT2SQL_ACCESS_KEY="$(head -c 24 /dev/urandom | base64 | tr '/+' '-_' | tr -d '=\n')"
  export TEXT2SQL_ACCESS_KEY
  generated=1
fi

export MODEL_DIR MODEL_FILE
APP_PORT="${APP_PORT:-8085}"
export APP_PORT

docker compose up -d --build

echo "앱이 준비되길 기다리는 중…"
for _ in $(seq 1 120); do
  if curl -fs "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1; then
    echo
    echo "접속: http://127.0.0.1:${APP_PORT}"
    if [ "$generated" = 1 ]; then
      echo "접속 키: ${TEXT2SQL_ACCESS_KEY}   (이번에 새로 만든 키입니다. 화면에서 입력하세요.)"
      echo "         같은 키를 계속 쓰려면 .env에 TEXT2SQL_ACCESS_KEY=<키>를 적어 두세요."
    else
      echo "접속 키: .env 또는 환경변수의 TEXT2SQL_ACCESS_KEY 값을 화면에서 입력하세요."
    fi
    echo "모델은 처음 질문할 때 시간이 걸립니다 (수십 초). 종료는 ./scripts/docker-down.sh"
    exit 0
  fi
  sleep 1
done
echo "[경고] 2분 안에 준비되지 않았습니다. 'docker compose logs app llm'으로 확인하세요."
exit 1
