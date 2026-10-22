"""Laptop camera server cho Raspberry Pi photobooth.

Chạy trên LAPTOP (máy có camera):
    pip install flask opencv-python
    python laptop_cam_server.py

Raspberry Pi sẽ đọc stream thay cho cv2.VideoCapture(0):
    CAMERA_SOURCE = "http://<LAPTOP_IP>:5000/video_feed"

Endpoints:
    /              - trang test xem stream trên trình duyệt
    /video_feed    - MJPEG stream cho Pi (cv2.VideoCapture đọc được)
    /snapshot.jpg  - 1 frame JPEG (để test nhanh)
"""
import socket
import cv2
from flask import Flask, Response, render_template_string

# --- Cấu hình ---
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
JPEG_QUALITY = 80
PORT = 5000

app = Flask(__name__)

cap = cv2.VideoCapture(CAMERA_INDEX)
# Trên Windows dùng CAP_DSHOW cho nhanh, các OS khác bỏ qua
try:
    cap_test = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if cap_test.isOpened():
        cap.release()
        cap = cap_test
    else:
        cap_test.release()
except Exception:
    pass

cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

INDEX_HTML = """
<html><head><title>Laptop Cam Server</title></head>
<body style="background:#111;color:#fff;font-family:Arial;text-align:center">
<h2>Laptop Cam Server OK</h2>
<p>Pi dùng: <b>http://&lt;LAPTOP_IP&gt;:5000/video_feed</b></p>
<img src="/video_feed" width="640" />
</body></html>
"""


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def gen_mjpeg():
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        ok, buf = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        )
        if not ok:
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + buf.tobytes()
            + b"\r\n"
        )


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/video_feed")
def video_feed():
    return Response(
        gen_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/snapshot.jpg")
def snapshot():
    ok, frame = cap.read()
    if not ok:
        return "Camera error", 500
    ok, buf = cv2.imencode(
        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
    )
    if not ok:
        return "Encode error", 500
    return Response(buf.tobytes(), mimetype="image/jpeg")


if __name__ == "__main__":
    if not cap.isOpened():
        print(f"LOI: khong mo duoc camera index {CAMERA_INDEX}")
    else:
        print("=" * 50)
        print("LAPTOP CAM SERVER")
        print("=" * 50)
        print(f"LAN IP : {get_lan_ip()}")
        print(f"Stream : http://{get_lan_ip()}:{PORT}/video_feed")
        print(f"Test   : http://127.0.0.1:{PORT}/  (tren laptop)")
        print("Tren Pi sua: CAMERA_SOURCE = "
              f"\"http://{get_lan_ip()}:{PORT}/video_feed\"")
        print("=" * 50)
    app.run(host="0.0.0.0", port=PORT, threaded=True)
