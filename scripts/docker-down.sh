#!/usr/bin/env bash
# docker-up.sh로 띄운 앱과 모델을 끈다. 사용법: ./scripts/docker-down.sh
set -euo pipefail
cd "$(dirname "$0")/.."
# 접속 키 값은 끌 때는 필요 없으므로 형식만 맞춘다
TEXT2SQL_ACCESS_KEY="${TEXT2SQL_ACCESS_KEY:-unused}" docker compose down
