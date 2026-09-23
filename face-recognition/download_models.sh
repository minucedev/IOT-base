#!/usr/bin/env bash
set -eu
cd "$(dirname "${BASH_SOURCE[0]}")"
mkdir -p models

echo "[*] Đang tải mô hình phát hiện khuôn mặt YuNet..."
curl -L --fail --retry 3 -o models/face_detection_yunet_2023mar.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

echo "[*] Đang tải mô hình trích xuất đặc trưng SFace..."
curl -L --fail --retry 3 -o models/face_recognition_sface_2021dec.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx

echo "✅ Đã tải thành công các model YuNet và SFace vào thư mục models/."
