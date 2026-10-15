#!/usr/bin/env python3
"""Loa laptop: nhận câu từ Raspberry Pi qua HTTP rồi đọc bằng espeak-ng.

Chạy trên laptop (cùng mạng LAN với Pi):
    sudo apt install espeak-ng
    python3 laptop_speaker.py
Pi gửi tới: http://IP_LAPTOP:8765/speak
"""
import json
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8765


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        message = json.loads(self.rfile.read(length) or b"{}").get("message", "")
        print(f"[SPEAK] {message}", flush=True)
        if message:
            subprocess.Popen(["espeak-ng", "-v", "vi", "-s", "125", message])
        self.send_response(200)
        self.end_headers()


if __name__ == "__main__":
    print(f"Loa laptop đang chờ ở cổng {PORT}...", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
