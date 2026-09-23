#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

MODEL_NAME="Zipformer-30M-RNNT-Streaming-6000h"
MODEL_DIR="models/${MODEL_NAME}"
CHUNK_SIZE="${CHUNK_SIZE:-32}"
mkdir -p "${MODEL_DIR}"

HF_BASE="https://huggingface.co/hynt/${MODEL_NAME}/resolve/main"
SUFFIX="epoch-31-avg-11-chunk-${CHUNK_SIZE}-left-128.fp16.onnx"

download() {
  local url="$1"
  local output="$2"

  if [[ -s "${output}" ]]; then
    echo "  [OK] Đã có sẵn: $(basename "${output}")"
    return
  fi

  echo "  [*] Đang tải: $(basename "${output}") ..."
  curl -fL --retry 3 --retry-delay 2 -o "${output}.part" "${url}"
  mv "${output}.part" "${output}"
}

echo "============================================================"
echo " Tải mô hình ASR Tiếng Việt (Zipformer + Silero VAD)"
echo "============================================================"

# 1. Silero VAD
download \
  "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx" \
  "models/silero_vad.onnx"

# 2. Config (chứa bảng tokens cho Zipformer)
download "${HF_BASE}/config.json?download=true" "${MODEL_DIR}/config.json"

# 3. Zipformer ONNX (Encoder, Decoder, Joiner)
download "${HF_BASE}/encoder-${SUFFIX}?download=true" "${MODEL_DIR}/encoder-${SUFFIX}"
download "${HF_BASE}/decoder-${SUFFIX}?download=true" "${MODEL_DIR}/decoder-${SUFFIX}"
download "${HF_BASE}/joiner-${SUFFIX}?download=true" "${MODEL_DIR}/joiner-${SUFFIX}"

echo ""
echo "✅ Tải toàn bộ mô hình thành công!"
