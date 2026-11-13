#!/usr/bin/env bash
# 로컬 모델 서버(Docker)를 끈다. 사용법: ./scripts/llm-stop.sh
set -euo pipefail
if docker rm -f text2sql-llm >/dev/null 2>&1; then
  echo "모델 서버를 껐습니다."
else
  echo "실행 중인 모델 서버(text2sql-llm)가 없습니다."
fi
