#!/usr/bin/env python3
"""Loa laptop: nhận câu từ Raspberry Pi qua HTTP rồi đọc bằng Google TTS (gTTS).

Chạy trên laptop (cùng mạng LAN với Pi, cần Internet):
    pip install gTTS
    sudo apt install mpg123
    python3 laptop_speaker.py
Pi gửi tới: http://IP_LAPTOP:8765/speak
"""
import json
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from gtts import gTTS

PORT = 8765


def speak(message):
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3") as f:
            gTTS(message, lang="vi").write_to_fp(f)
            f.flush()
            subprocess.run(["mpg123", "-q", f.name])
    except Exception as exc:
        print(f"[LỖI LOA] {exc}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        message = json.loads(self.rfile.read(length) or b"{}").get("message", "")
        print(f"[SPEAK] {message}", flush=True)
        if message:
            threading.Thread(target=speak, args=(message,), daemon=True).start()
        self.send_response(200)
        self.end_headers()


if __name__ == "__main__":
    speak("Khởi động")  # thử loa trước khi nhận câu từ Pi
    print(f"Loa laptop đang chờ ở cổng {PORT}...", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
