#!/usr/bin/env bash
# 로컬 모델 서버(llama.cpp, Docker)를 띄운다. 이 PC에서만 접근할 수 있게 127.0.0.1에만 연다.
# 사용법: ./scripts/llm-start.sh
# 환경변수(선택): MODEL_DIR(기본 ./models) MODEL_FILE LLM_PORT(기본 8083) LLM_THREADS(기본 4) LLM_CTX(기본 16384)
#                 DRY_RUN=1 이면 실행하지 않고 docker 명령만 보여 준다.
# 앱 쪽 설정(.env.example 기본값과 같다): TEXT2SQL_LLM_PROVIDER=openai, TEXT2SQL_LLM_BASE_URL=http://localhost:8083/v1,
# TEXT2SQL_LLM_CONTEXT_TOKENS=16384. LLM_PORT나 LLM_CTX를 바꿨다면 .env도 같은 값으로 맞추세요.
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL_DIR="${MODEL_DIR:-models}"
MODEL_FILE="${MODEL_FILE:-Qwen3-4B-Instruct-2507-Q4_K_M.gguf}"
LLM_PORT="${LLM_PORT:-8083}"
LLM_THREADS="${LLM_THREADS:-4}"
LLM_CTX="${LLM_CTX:-16384}"
NAME="text2sql-llm"
IMAGE="ghcr.io/ggml-org/llama.cpp:server"

if ! command -v docker >/dev/null 2>&1; then
  echo "[없음] docker — https://docs.docker.com/engine/install/ubuntu/ 를 참고해 설치하고, sudo usermod -aG docker \$USER 후 다시 로그인하세요."
  exit 1
fi
if [ ! -f "${MODEL_DIR}/${MODEL_FILE}" ]; then
  echo "모델 파일이 없습니다: ${MODEL_DIR}/${MODEL_FILE}"
  echo "먼저 ./scripts/download-model.sh를 실행하세요."
  exit 1
fi

abs_dir="$(cd "$MODEL_DIR" && pwd)"
cmd=(docker run -d --name "$NAME" -p "127.0.0.1:${LLM_PORT}:8080" -v "${abs_dir}:/models:ro" "$IMAGE"
  -m "/models/${MODEL_FILE}" --host 0.0.0.0 --port 8080
  -t "$LLM_THREADS" -tb "$LLM_THREADS" -c "$LLM_CTX" -b 512 -ub 512 -fa on --parallel 1 --no-ui)

if [ "${DRY_RUN:-0}" = "1" ]; then
  printf '%q ' "${cmd[@]}"
  echo
  exit 0
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true
"${cmd[@]}" >/dev/null
echo "모델 서버를 시작했습니다 (이름: $NAME, 주소: http://127.0.0.1:${LLM_PORT}). 모델을 읽는 중…"

for _ in $(seq 1 120); do
  if curl -fs "http://127.0.0.1:${LLM_PORT}/health" >/dev/null 2>&1; then
    echo "준비됐습니다. 종료는 ./scripts/llm-stop.sh"
    exit 0
  fi
  sleep 1
done
echo "[경고] 2분 안에 준비되지 않았습니다. 'docker logs $NAME'으로 확인하세요 (메모리 부족일 수 있습니다)."
exit 1
