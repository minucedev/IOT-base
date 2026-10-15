"""Chạy trên LAPTOP: phát webcam thành luồng MJPEG để Raspberry Pi đọc.

    pip install opencv-python
    python laptop_stream.py --port 8080 --cam 0

Pi đặt CAMERA_SOURCE = "http://<ip-laptop>:8080/video" trong config.py.
"""
import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

_lock = threading.Condition()
_jpeg = None


def capture(cam: int, width: int, height: int, quality: int, fps: float) -> None:
    global _jpeg
    cap = cv2.VideoCapture(cam)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    interval, next_t = 1.0 / fps, time.monotonic()
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.1)
            continue
        frame = cv2.flip(frame, 1)  # lật ngang để giống gương
        now = time.monotonic()
        if now < next_t:  # bỏ frame thừa để giữ đúng FPS
            continue
        next_t = max(next_t + interval, now)
        ok, buf = cv2.imencode(".jpg", frame, params)
        if ok:
            with _lock:
                _jpeg = buf.tobytes()
                _lock.notify_all()


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
        except (ConnectionError, OSError):  # client (Pi) ngắt kết nối
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
    ap.add_argument("--fps", type=float, default=15)
    a = ap.parse_args()
    threading.Thread(target=capture, args=(a.cam, a.width, a.height, a.quality, a.fps), daemon=True).start()
    print(f"Đang phát {a.fps:g} FPS: http://<ip-laptop>:{a.port}/video  (Ctrl+C để dừng)")
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()
