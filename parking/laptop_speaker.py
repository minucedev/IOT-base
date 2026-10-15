#!/usr/bin/env python3
"""Tiny authenticated LAN TTS receiver for Ubuntu laptop (stdlib only).

Run on the Ubuntu laptop, *not* on Raspberry Pi:
    export PARKING_SPEAKER_TOKEN='same-long-secret-as-raspberry-pi'
    sudo apt install espeak-ng
    python3 laptop_speaker.py
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import queue
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main():
    parser = argparse.ArgumentParser(description="Laptop Ubuntu speaker for Raspberry Pi parking demo")
    parser.add_argument("--host", default="0.0.0.0", help="LAN interface (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--voice", default="vi", help="eSpeak voice (vi)")
    parser.add_argument("--speed", type=int, default=125)
    args = parser.parse_args()
    secret = os.environ.get("PARKING_SPEAKER_TOKEN", "")
    if not secret:
        parser.error("Hãy đặt biến môi trường PARKING_SPEAKER_TOKEN trước khi chạy.")
    if not shutil.which("espeak-ng"):
        parser.error("Chưa có espeak-ng. Ubuntu: sudo apt install espeak-ng")

    messages = queue.Queue(maxsize=8)

    def speaker_worker():
        while True:
            message = messages.get()
            try:
                print(f"[SPEAK] {message}", flush=True)
                p = subprocess.run(
                    ["espeak-ng", "-v", args.voice, "-s", str(args.speed), message],
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
                if p.returncode:
                    print(f"[AUDIO ERROR] eSpeak returned {p.returncode}: "
                          f"{p.stderr.decode(errors='replace')[:300]}", flush=True)
            except Exception as exc:
                print(f"[AUDIO ERROR] {exc}", flush=True)
            finally:
                messages.task_done()

    threading.Thread(target=speaker_worker, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, message):
            body = json.dumps({"message": message}, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, "speaker-ready")
            else:
                self.reply(404, "not-found")

        def do_POST(self):
            if self.path != "/speak":
                self.reply(404, "not-found")
                return
            if not hmac.compare_digest(self.headers.get("X-Parking-Token", ""), secret):
                self.reply(403, "forbidden")
                return
            length_str = self.headers.get("Content-Length", "")
            if not length_str.isdigit() or not 0 < int(length_str) <= 4096:
                self.reply(400, "invalid-content-length")
                return
            try:
                data = json.loads(self.rfile.read(int(length_str)).decode("utf-8"))
                text = data.get("message", "")
                if not isinstance(text, str) or not text.strip() or len(text) > 500:
                    raise ValueError("message must be a short string")
            except (ValueError, UnicodeError, AttributeError):
                self.reply(400, "invalid-json-or-message")
                return
            try:
                messages.put_nowait(text.strip())
            except queue.Full:
                self.reply(503, "speaker-queue-full")
                return
            # 202 means "queued"; audio may start a fraction of a second later.
            self.reply(202, "queued")

        def log_message(self, fmt, *args):
            print(f"[HTTP] {self.address_string()} - {fmt % args}", flush=True)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[READY] Laptop speaker listening on {args.host}:{args.port}", flush=True)
    print("[READY] Health check: http://localhost:8765/health", flush=True)
    print("[SECURITY] Dùng trong mạng LAN tin cậy; không mở port 8765 ra Internet.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[STOP]", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
