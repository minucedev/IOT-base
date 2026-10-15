"""Chạy trên LAPTOP: phát webcam thành luồng MJPEG để Raspberry Pi đọc,
đồng thời hỏi trạng thái từ Pi và kêu bíp qua loa laptop khi sai tư thế.

    pip install opencv-python
    python laptop_stream.py --port 8080 --cam 0 --pi 192.168.1.50

Pi đặt CAMERA_SOURCE = "http://<ip-laptop>:8080/video" trong config.py.
"""
import argparse
import json
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

_lock = threading.Condition()
_jpeg = None


def capture(cam: int, width: int, height: int, quality: int) -> None:
    global _jpeg
    cap = cv2.VideoCapture(cam)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.1)
            continue
        frame = cv2.flip(frame, 1)  # lật ngang để giống gương
        ok, buf = cv2.imencode(".jpg", frame, params)
        if ok:
            with _lock:
                _jpeg = buf.tobytes()
                _lock.notify_all()


def _beep(freq: int, ms: int) -> None:
    if sys.platform == "win32":
        import winsound
        winsound.Beep(freq, ms)
    else:
        sys.stdout.write("")
        sys.stdout.flush()
        time.sleep(ms / 1000)


def alarm(pi_host: str, freq: int, beep_ms: int, pause_ms: int) -> None:
    """Hỏi /api/status của Pi; khi alert=true thì kêu bíp ngắt quãng qua loa laptop."""
    url = f"http://{pi_host}/api/status"
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                alert = json.load(r).get("alert", False)
        except Exception as exc:  # noqa: BLE001
            print(f"Không lấy được trạng thái từ {url}: {exc}")
            time.sleep(2)
            continue
        if alert:
            _beep(freq, beep_ms)
            time.sleep(pause_ms / 1000)
        else:
            time.sleep(0.2)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/video":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                with _lock:
                    _lock.wait(timeout=1.0)
                    data = _jpeg
                if data is None:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                 b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n"
                                 + data + b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--quality", type=int, default=80)
    ap.add_argument("--pi", help="IP[:port] của Pi để bật còi, vd 192.168.1.50 (bỏ trống = không kêu)")
    ap.add_argument("--freq", type=int, default=1000, help="Tần số bíp (Hz)")
    ap.add_argument("--beep-ms", type=int, default=200)
    ap.add_argument("--pause-ms", type=int, default=300)
    a = ap.parse_args()
    if a.pi:
        host = a.pi if ":" in a.pi else f"{a.pi}:5000"
        threading.Thread(target=alarm, args=(host, a.freq, a.beep_ms, a.pause_ms), daemon=True).start()
    threading.Thread(target=capture, args=(a.cam, a.width, a.height, a.quality), daemon=True).start()
    print(f"Đang phát: http://<ip-laptop>:{a.port}/video  (Ctrl+C để dừng)")
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()
