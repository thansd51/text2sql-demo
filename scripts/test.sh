#!/usr/bin/env bash
# 자동 테스트를 모두 돌린다 (실제 LLM은 호출하지 않는다): 백엔드 린트·서식·테스트 + 화면 테스트.
# 사용법: ./scripts/test.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 백엔드: 린트 =="
uv run ruff check .
echo "== 백엔드: 서식 =="
uv run ruff format --check .
echo "== 백엔드: 테스트 =="
uv run pytest -q
echo "== 화면: 테스트 =="
(cd frontend && npm test)
echo
echo "모든 테스트를 통과했습니다."
