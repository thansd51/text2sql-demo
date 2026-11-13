#!/usr/bin/env bash
# 처음 한 번 실행한다: 필요한 프로그램 확인 → .env 만들기 → 파이썬 패키지 설치 → 화면 빌드.
# 사용법: ./scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

missing=0
need() { # 프로그램 이름, 설치 안내
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[없음] $1 — $2"
    missing=1
  fi
}

need uv "설치: curl -LsSf https://astral.sh/uv/install.sh | sh  (설치 후 새 터미널을 여세요. 파이썬 3.12는 uv가 알아서 받습니다)"
need node "Node.js 22 이상이 필요합니다. 설치: https://nodejs.org 또는 nvm (apt의 nodejs는 오래된 경우가 많습니다)"
need npm "Node.js와 함께 설치됩니다"
if [ "$missing" -ne 0 ]; then
  echo
  echo "위 프로그램을 설치한 뒤 다시 실행하세요."
  exit 1
fi

node_major="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$node_major" -lt 20 ]; then
  echo "[경고] Node.js $(node -v)는 오래됐습니다. 22 이상을 권장합니다. 화면 빌드가 실패하면 Node.js를 올리세요."
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[만듦] .env (.env.example을 복사했습니다). 로컬 시험용이라 접속 키 검사가 꺼져 있습니다."
else
  echo "[유지] .env가 이미 있어서 건드리지 않았습니다."
fi

echo "[설치] 파이썬 패키지 (uv sync)…"
uv sync

echo "[설치] 화면 패키지와 빌드 (npm ci, npm run build)…"
(cd frontend && npm ci && npm run build)

cat <<'EOF'

준비가 끝났습니다. 다음 순서로 진행하세요.
  1) 로컬 모델이 필요하면:  ./scripts/download-model.sh  →  ./scripts/llm-start.sh   (Docker 필요)
     외부 LLM(OpenAI, Claude)을 쓰면 .env를 고치세요 (README의 "LLM 연결" 참고)
  2) 서버 실행:             ./scripts/run.sh
  3) 브라우저:              http://127.0.0.1:8085
EOF
