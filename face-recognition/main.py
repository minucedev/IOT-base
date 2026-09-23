import atexit
import io
import os
import signal
import socket
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

from camera import Camera, CAMERA_URL
from database import FaceDatabase
from recognition import RecognitionEngine

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))

# Khởi tạo camera với cấu hình URL (ưu tiên biến môi trường CAMERA_URL nếu có)
stream_url = os.environ.get("CAMERA_URL", CAMERA_URL)
camera = Camera(stream_url)
database = FaceDatabase(str(BASE_DIR / "data"))
engine = None
_shutdown_lock = threading.Lock()
_stopped = False


def get_lan_ip() -> str:
    """Lấy IP mạng LAN của Raspberry Pi."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def start_services() -> None:
    global engine
    camera.start()
    engine = RecognitionEngine(camera, database)
    engine.start()


def stop_services() -> None:
    global _stopped
    with _shutdown_lock:
        if _stopped:
            return
        _stopped = True
        if engine is not None:
            engine.stop()
        camera.stop()


def handle_signal(signum, frame) -> None:
    stop_services()
    raise SystemExit(0)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/video")
def video():
    # Tránh gửi cùng frame nhiều lần — chỉ yield khi có frame mới
    def frames():
        last_frame: bytes | None = None
        while not _stopped:
            if engine is None:
                time.sleep(0.1)
                continue
            image, _, _, _, _ = engine.latest()
            if image is None or image is last_frame:
                time.sleep(0.033)
                continue
            last_frame = image
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + image + b"\r\n"
            time.sleep(0.033)

    return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/status")
def status():
    if engine is None:
        return jsonify({
            "camera": "lỗi",
            "name": "Chưa sẵn sàng",
            "similarity": 0.0,
            "fps_infer": 0.0,
            "fps_capture": 0.0,
        })
    _, name, similarity, fps_infer, fps_capture = engine.latest()
    return jsonify({
        "camera": "đang chạy" if camera.is_running else "lỗi",
        "name": name,
        "similarity": similarity,
        "fps_infer": fps_infer,
        "fps_capture": fps_capture,
        "stream_url": camera.url,
    })


@app.post("/register")
def register():
    if engine is None:
        return jsonify({"ok": False, "message": "Engine chưa sẵn sàng"}), 503
    data = request.get_json(silent=True) or request.form
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "message": "Vui lòng nhập tên"}), 400
    ok, message = engine.register_latest(name)
    if ok:
        engine.reload_gallery()
    return jsonify({"ok": ok, "message": message}), 200 if ok else 400


@app.get("/api/persons")
def persons():
    return jsonify(database.list_persons())


@app.delete("/api/persons/<int:person_id>")
def delete_person(person_id: int):
    ok, message = database.delete_person(person_id)
    if engine is not None:
        engine.reload_gallery()
    return jsonify({"ok": ok, "message": message}), 200 if ok else 404


@app.get("/api/recognition-logs")
def recognition_logs():
    return jsonify(database.recognition_logs(request.args.get("limit", 100, type=int)))


@app.delete("/api/recognition-logs")
def clear_logs():
    database.clear_logs()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ #
# Registration photo log                                               #
# ------------------------------------------------------------------ #

@app.get("/api/registration-photos")
def registration_photos():
    """Danh sách ảnh đăng ký (metadata, không kèm blob)."""
    return jsonify(database.list_registration_photos())


@app.get("/api/registration-photos/<int:photo_id>")
def get_registration_photo(photo_id: int):
    """Trả về ảnh JPEG của lần đăng ký theo id."""
    jpeg = database.get_registration_photo(photo_id)
    if jpeg is None:
        return jsonify({"ok": False, "message": "Không tìm thấy ảnh"}), 404
    return send_file(io.BytesIO(jpeg), mimetype="image/jpeg")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    atexit.register(stop_services)

    port = int(os.environ.get("PORT", "5000"))
    pi_ip = get_lan_ip()

    print("=" * 66)
    print(" 🚀 FACE RECOGNITION SERVER (RASPBERRY PI)")
    print("=" * 66)
    print(f" Camera Stream Source : {camera.url}")
    print(f" Web UI Raspberry Pi  : http://{pi_ip}:{port}")
    print("-" * 66)
    print(" >> Để đổi IP Laptop stream:")
    print("    Cách 1: Sửa hằng số CAMERA_URL trong `camera.py`")
    print("    Cách 2: Chạy với biến môi trường: CAMERA_URL=http://<IP>:5000/video_feed ./run.sh")
    print("=" * 66)

    try:
        start_services()
    except Exception as exc:
        print(f"[!] Không thể khởi động dịch vụ: {exc}", flush=True)
        stop_services()
        raise SystemExit(1)

    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
