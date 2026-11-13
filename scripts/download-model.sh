#!/usr/bin/env bash
# 로컬 모델(Qwen3-4B-Instruct-2507, Q4_K_M, 약 2.3GB)을 models/ 폴더에 내려받고 체크섬을 확인한다.
# 이미 받은 파일이 맞으면 아무것도 하지 않는다. 중간에 끊겨도 다시 실행하면 이어서 받는다.
# 사용법: ./scripts/download-model.sh
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL_DIR="${MODEL_DIR:-models}"
MODEL_FILE="Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
URL="https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/${MODEL_FILE}"
# Hugging Face가 알려 주는 파일 크기와 sha256 (2026-11-13 확인)
SIZE=2497281120
SHA256=3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597

for tool in curl sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || { echo "[없음] $tool"; exit 1; }
done

mkdir -p "$MODEL_DIR"
dest="${MODEL_DIR}/${MODEL_FILE}"

verify() {
  [ "$(stat -c %s "$1")" = "$SIZE" ] && [ "$(sha256sum "$1" | cut -d' ' -f1)" = "$SHA256" ]
}

if [ -f "$dest" ] && verify "$dest"; then
  echo "이미 받았고 체크섬이 맞습니다: $dest"
  exit 0
fi

echo "내려받는 중 (약 2.3GB): $URL"
curl -L --fail --retry 3 -C - -o "${dest}.part" "$URL"

echo "체크섬 확인 중…"
if verify "${dest}.part"; then
  mv "${dest}.part" "$dest"
  echo "완료: $dest"
else
  echo "[오류] 받은 파일의 크기나 체크섬이 맞지 않습니다. ${dest}.part를 지우고 다시 실행하세요."
  exit 1
fi
