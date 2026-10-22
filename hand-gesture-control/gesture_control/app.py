"""Raspberry Pi 4 + webcam USB + MediaPipe + RPi.GPIO + web Flask."""

import atexit
import logging
import os
import platform
import signal
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template
from gesture_logic import GESTURE_NAMES, StableGesture, choose_gesture
from gpio_outputs import GPIOOutputs, env_number

ROOT = Path(__file__).resolve().parent
# Đổi thành IP laptop đang chạy laptop_cam_server.py (hoặc đặt biến môi trường CAMERA_URL).
CAMERA_URL = "http://10.93.29.44:5000/video_feed"
LOG = logging.getLogger(__name__)
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15),
    (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)


def build_options(mp, model_path):
    """Hàm riêng để kiểm tra API mà không khởi tạo/chạy model."""
    return mp.tasks.vision.GestureRecognizerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path),
            delegate=mp.tasks.BaseOptions.Delegate.CPU,
        ),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        # Không lọc bằng allowlist: lấy nhãn cao nhất toàn bộ model, rồi
        # choose_gesture() bỏ các nhãn nằm ngoài bốn nhóm điều khiển.
        canned_gesture_classifier_options=mp.tasks.components.processors.ClassifierOptions(
            max_results=1
        ),
    )


class GestureCamera:
    def __init__(self, outputs=None):
        # Như các bài khác trong repo: laptop chạy laptop_cam_server.py, Pi đọc stream.
        # CAMERA_INDEX (nếu đặt) vẫn dùng được cho webcam cắm trực tiếp / camera local.
        self.source = os.getenv("CAMERA_INDEX") or os.getenv("CAMERA_URL", CAMERA_URL)
        self.width = int(os.getenv("FRAME_WIDTH", "640"))
        self.height = int(os.getenv("FRAME_HEIGHT", "480"))
        if not 160 <= self.width <= 1920 or not 120 <= self.height <= 1080:
            raise ValueError("FRAME_WIDTH: 160–1920; FRAME_HEIGHT: 120–1080.")
        self.target_fps = env_number("TARGET_FPS", 10, 1, 60)
        self.threshold = env_number("SCORE_THRESHOLD", 0.65, 0, 1)
        self.hold = env_number("HOLD_SECONDS", 0.4, 0, 10)
        self.mirror = os.getenv("MIRROR", "1") == "1"
        self.model_path = ROOT / "models" / "gesture_recognizer.task"
        self.outputs = outputs if outputs is not None else GPIOOutputs()
        self.stability = StableGesture(self.hold)
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.finished = threading.Event()
        self.thread = None
        self.jpeg = None
        self.frame_id = 0
        self.last_publish = None
        self.state = {
            "camera_ok": False,
            "result": "Đang khởi động…",
            "gesture": "",
            "model_label": "",
            "score": 0.0,
            "hand_detected": False,
            "fps": 0.0,
            "error": "",
        }

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._process_camera, name="gesture-camera", daemon=True)
            self.thread.start()

    def stop(self):
        self.outputs.begin_shutdown()  # Khóa lệnh mới trước khi dọn GPIO.
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        try:
            if self.thread is not None and self.thread is not threading.current_thread():
                self.thread.join(timeout=3)
        finally:
            self.outputs.close()

    def snapshot(self):
        with self.condition:
            data = self.state.copy()
            last_publish = self.last_publish
        if data["camera_ok"] and last_publish is not None and time.monotonic() - last_publish > self.outputs.frame_timeout:
            data.update(camera_ok=False, result="Camera chưa có ảnh mới", gesture="", score=0.0, fps=0.0, hand_detected=False)
        data["outputs"] = self.outputs.snapshot()
        return data

    def _camera_error(self, message):
        self.stability.update(None, time.monotonic())
        self.outputs.all_off("camera_error")
        with self.condition:
            self.state.update(
                camera_ok=False, result="Camera hoặc nhận diện gặp lỗi", gesture="",
                model_label="", score=0.0, fps=0.0, hand_detected=False, error=message,
            )
            self.condition.notify_all()

    def stream(self):
        """Mọi trình duyệt dùng chung ảnh từ một luồng camera/model duy nhất."""
        previous = 0
        while not self.stop_event.is_set():
            with self.condition:
                self.condition.wait_for(
                    lambda: self.frame_id != previous or self.finished.is_set() or self.stop_event.is_set(),
                    timeout=2,
                )
                if self.stop_event.is_set():
                    break
                if self.jpeg is None or self.frame_id == previous:
                    if self.finished.is_set():
                        break
                    continue
                jpeg, previous = self.jpeg, self.frame_id
            yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                   + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")

    def _process_camera(self):
        camera = None
        recognizer = None
        try:
            # Import và mở phần cứng tại đây; import app.py không mở webcam/GPIO.
            import cv2
            import mediapipe as mp

            if not self.model_path.is_file():
                raise FileNotFoundError("Thiếu model. Chạy: python download_model.py")
            cv2.setNumThreads(2)
            source = int(self.source) if self.source.isdecimal() else self.source
            if isinstance(source, str) and source.startswith(("http://", "https://", "rtsp://")):
                backend = cv2.CAP_ANY  # Stream MJPEG từ laptop
            else:
                backend = {"Linux": cv2.CAP_V4L2, "Windows": cv2.CAP_DSHOW}.get(platform.system(), cv2.CAP_ANY)
            camera = cv2.VideoCapture(source, backend)
            if not camera.isOpened():
                raise RuntimeError(f"Không mở được camera {self.source}. Đã chạy laptop_cam_server.py trên laptop và đúng IP chưa?")
            camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            camera.set(cv2.CAP_PROP_FPS, self.target_fps)
            camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            recognizer = mp.tasks.vision.GestureRecognizer.create_from_options(build_options(mp, self.model_path))
            epoch = time.monotonic()
            previous_timestamp = -1
            previous_publish = None
            fps = 0.0
            failures = 0
            while not self.stop_event.is_set():
                started = time.monotonic()
                ok, frame = camera.read()
                if self.stop_event.is_set():
                    break
                if not ok or frame is None:
                    failures += 1
                    self._camera_error("Webcam không trả ảnh. Kiểm tra cáp USB/nguồn và đóng ứng dụng camera khác.")
                    if failures >= 20:
                        raise RuntimeError("Webcam đã ngừng trả ảnh; cắm lại camera rồi chạy lại app.")
                    self.stop_event.wait(0.1)
                    continue
                failures = 0
                frame = cv2.resize(frame, (self.width, self.height))
                if self.mirror:
                    frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                # VIDEO mode yêu cầu timestamp tăng nghiêm ngặt, đơn vị ms.
                timestamp = max(previous_timestamp + 1, int((time.monotonic() - epoch) * 1000))
                previous_timestamp = timestamp
                recognition = recognizer.recognize_for_video(image, timestamp)
                if self.stop_event.is_set():
                    break
                now = time.monotonic()
                self.outputs.heartbeat()
                has_hand, raw_label, score, accepted = choose_gesture(recognition, self.threshold)
                stable = self.stability.update(accepted, now)
                if stable is not None:
                    self.outputs.apply(stable)
                if not has_hand:
                    result = "Chưa thấy bàn tay"
                elif accepted is None:
                    result = "Chưa xác định được cử chỉ"
                elif stable is None:
                    result = "Đang xác nhận cử chỉ…"
                else:
                    result = GESTURE_NAMES[stable]
                for hand in recognition.hand_landmarks:
                    points = [(int(p.x * self.width), int(p.y * self.height)) for p in hand]
                    for a, b in HAND_CONNECTIONS:
                        cv2.line(frame, points[a], points[b], (65, 225, 100), 2)
                    for point in points:
                        cv2.circle(frame, point, 3, (25, 170, 255), -1)
                # Tiếng Việt hiển thị trên web; font OpenCV dùng nhãn ASCII.
                cv2.putText(frame, raw_label or "NO HAND", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                encoded_ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if not encoded_ok:
                    raise RuntimeError("Không mã hóa được ảnh JPEG.")
                publish_time = time.monotonic()
                if previous_publish is not None:
                    measured = 1.0 / max(publish_time - previous_publish, 0.001)
                    fps = measured if fps == 0 else 0.85 * fps + 0.15 * measured
                previous_publish = publish_time
                with self.condition:
                    self.jpeg = encoded.tobytes()
                    self.frame_id += 1
                    self.last_publish = publish_time
                    self.state.update(
                        camera_ok=True, result=result, gesture=stable or "", model_label=raw_label,
                        score=round(score, 4), fps=round(fps, 1), hand_detected=has_hand, error="",
                    )
                    self.condition.notify_all()
                self.stop_event.wait(max(0, 1.0 / self.target_fps - (time.monotonic() - started)))
        except Exception as exc:
            LOG.exception("Camera/MediaPipe đã ngừng xử lý")
            self._camera_error(str(exc))
        finally:
            try:
                self.outputs.all_off("camera_stopped")
            finally:
                for resource in (camera, recognizer):
                    if resource is not None:
                        try:
                            resource.release() if resource is camera else resource.close()
                        except Exception:
                            LOG.exception("Không dọn được tài nguyên camera/model")
                self.finished.set()
                with self.condition:
                    self.condition.notify_all()


def create_app(engine):
    app = Flask(__name__, template_folder=str(ROOT / "templates"))
    app.json.ensure_ascii = False

    @app.after_request
    def no_cache(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/video_feed")
    def video_feed():
        return Response(engine.stream(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/state")
    def state():
        return jsonify(engine.snapshot())

    return app


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Ctrl+C và SIGTERM đều đi qua finally để tắt PWM và cleanup GPIO.
    def terminate(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    port = int(os.getenv("PORT", "5000"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT phải nằm trong 1–65535.")
    engine = GestureCamera()
    atexit.register(engine.stop)
    try:
        engine.start()
        create_app(engine).run(host=os.getenv("HOST", "0.0.0.0"), port=port,
                               threaded=True, debug=False, use_reloader=False)
    finally:
        engine.stop()


if __name__ == "__main__":
    main()
