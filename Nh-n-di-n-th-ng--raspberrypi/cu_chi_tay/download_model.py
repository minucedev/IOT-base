"""Kiểm tra/tải model Google có sẵn, không huấn luyện hoặc chạy nhận diện."""

import argparse
import hashlib
import os
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
EXPECTED_SHA256 = "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482"


def check(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Model không khớp SHA256 bản đi kèm; chạy lại với --force.")
    with zipfile.ZipFile(path) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("Bundle model bị hỏng.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Tải lại model chính thức")
    args = parser.parse_args()
    directory = ROOT / "models"
    directory.mkdir(exist_ok=True)
    destination = directory / "gesture_recognizer.task"
    if destination.exists() and not args.force:
        check(destination)
        print(f"Model OK: {destination}")
        return
    temporary = destination.with_suffix(".download")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        check(temporary)
        os.replace(temporary, destination)
        print(f"Đã tải và kiểm tra model: {destination}")
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
