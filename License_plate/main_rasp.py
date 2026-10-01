"""
Nhận diện biển số xe realtime trên Raspberry Pi 4 tích hợp Flask Web Dashboard
- Thay thế màn hình LCD 16x2 bằng giao diện Web Flask (hiển thị mô phỏng LCD 16x2 realtime)
- Webcam USB -> phát hiện biển số (YOLOv9 tiny) -> OCR (fast-plate-ocr)
- So khớp với SQLite (plates.db)
- ĐÚNG : Web LCD hiện biển số, servo quay 0 -> 180 độ, giữ 2 giây rồi về 0
- SAI  : Web LCD hiện "KHONG CO", đèn LED sáng 2 giây
- Dù đúng hay sai đều giữ kết quả 2 giây rồi mới quét tiếp
- Servo dùng gpiozero (AngularServo) trên GPIO12
- Đèn LED báo sai trên GPIO16

Nối dây:
    Servo tín hiệu -> GPIO12 (chân vật lý 32) | VCC servo -> nguồn 5V ngoài, GND chung với Pi
    LED (+220 ohm) -> GPIO16 (chân vật lý 36)
    Nút đăng ký -> GPIO20 (chân vật lý 38) và GND (chân 39), dùng pull-up nội
    (Không cần đấu nối LCD I2C)

Cài đặt trên Raspberry Pi:
    sudo apt update
    sudo apt install -y python3-opencv
    pip install open-image-models fast-plate-ocr onnxruntime gpiozero flask --break-system-packages

Test phần cứng (servo, LED, nút) trước khi chạy:
    python3 test_hardware.py

Chạy:
    python3 main_rasp.py                  # Chạy nhận diện + mở Web Dashboard tại http://<IP_RASP>:5000
    python3 main_rasp.py add 43A12345     # Thêm biển số vào database qua CLI

Phím tắt (khi có cửa sổ video OpenCV):
    q = thoát

Đăng ký biển mới: nhấn nút vật lý ở GPIO20 (chân 38, nối xuống GND) khi biển số đang trước camera.
"""

import difflib
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from collections import deque

# ---------------- CẤU HÌNH ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "plates.db")
DEFAULT_CAMERA_URL = "http://10.232.65.44:5000/video_feed"
SHOW_WINDOW = True           # True: mở cửa sổ OpenCV GUI nếu có màn hình; False: headless
cv2 = None                   # Được import trong hàm main() khi khởi chạy

# Flask Config
WEB_HOST = "0.0.0.0"
WEB_PORT = 8080              # Cổng Web Dashboard mô phỏng LCD

SERVO_PIN = 12               # GPIO12 = chân vật lý 32, dây tín hiệu servo
LED_PIN = 16                 # GPIO16 = chân vật lý 36
BUTTON_PIN = 20              # GPIO20 = chân vật lý 38, nút đăng ký biển số (nối xuống GND)
REGISTER_WINDOW = 3.0        # Chỉ đăng ký biển đọc được trong N giây gần nhất

DETECTOR_MODEL = "yolo-v9-t-384-license-plate-end2end"
OCR_MODEL = "cct-xs-v2-global-model"

MIN_DET_CONF = 0.5
CONFIRM_FRAMES = 3           # Đọc giống nhau N lần liên tiếp mới chấp nhận
FUZZY_THRESHOLD = 0.90       # 1.0 = khớp tuyệt đối
HOLD_SECONDS = 2             # Giữ kết quả (đúng hay sai đều 2 giây)
SERVO_RETURN_TIME = 0.6      # Thời gian chờ servo quay hết hành trình 0 <-> 180
COOLDOWN = 0                 # Quét tiếp ngay sau khi xong
# ------------------------------------------

GREEN = (0, 200, 0)
RED = (0, 0, 220)
YELLOW = (0, 220, 220)


# ---------------- TRẠNG THÁI WEB (THAY THẾ LCD) ----------------
class WebDisplayState:
    """Quản lý trạng thái mô phỏng màn hình LCD 16x2 và ngoại vi cho Web Dashboard."""

    def __init__(self):
        self.lock = threading.Lock()
        self.line1 = "San sang quet..."
        self.line2 = ""
        self.status = "IDLE"  # IDLE | OK | FAIL
        self.plate = ""
        self.servo_angle = 0
        self.servo_status = "ĐÓNG (0°)"
        self.led_status = False
        self.updated_at = time.time()

    def update(self, line1=None, line2=None, status=None, plate=None,
               servo_angle=None, servo_status=None, led_status=None):
        with self.lock:
            if line1 is not None:
                self.line1 = line1
            if line2 is not None:
                self.line2 = line2
            if status is not None:
                self.status = status
            if plate is not None:
                self.plate = plate
            if servo_angle is not None:
                self.servo_angle = servo_angle
            if servo_status is not None:
                self.servo_status = servo_status
            if led_status is not None:
                self.led_status = led_status
            self.updated_at = time.time()

    def to_dict(self):
        with self.lock:
            return {
                "line1": self.line1,
                "line2": self.line2,
                "status": self.status,
                "plate": self.plate,
                "servo_angle": self.servo_angle,
                "servo_status": self.servo_status,
                "led_status": self.led_status,
                "updated_at": self.updated_at,
            }


web_state = WebDisplayState()


def create_flask_app():
    from flask import Flask, jsonify, render_template

    # Tắt log truy cập định kỳ của Werkzeug để tránh spam terminal khi web polling
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/status")
    def get_status():
        return jsonify(web_state.to_dict())

    return app


def start_flask(port=WEB_PORT):
    try:
        app = create_flask_app()
        print(f"[*] Flask Web Dashboard đang chạy tại http://{WEB_HOST}:{port}")
        app.run(host=WEB_HOST, port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        print(f"[CẢNH BÁO] Không thể khởi động Flask Web Server: {e}")


# ---------------- PHẦN CỨNG ----------------
class SafeServo:
    """Servo điều khiển bằng gpiozero, bắt lỗi khi chạy ngoài Raspberry Pi."""

    def __init__(self, pin, min_us=500, max_us=2500):
        self._angle = 0
        self.servo = None
        try:
            from gpiozero import AngularServo
            self.servo = AngularServo(
                pin, initial_angle=None, min_angle=0, max_angle=180,
                min_pulse_width=min_us / 1_000_000, max_pulse_width=max_us / 1_000_000,
            )
        except Exception as e:
            print(f"[CẢNH BÁO] Không khởi tạo được servo GPIO {pin}: {e}. Chạy chế độ giả lập.")

    @property
    def angle(self):
        return self._angle

    @angle.setter
    def angle(self, value):
        self._angle = value
        if self.servo:
            try:
                self.servo.angle = value
            except Exception as e:
                print(f"[Lỗi Servo]: {e}")

    def detach(self):
        """Ngừng phát xung để servo đứng yên, không rung."""
        if self.servo:
            try:
                self.servo.detach()
            except Exception:
                pass


class SafeLED:
    """Bọc điều khiển LED với cơ chế bắt lỗi khi chạy ngoài Raspberry Pi."""

    def __init__(self, pin):
        self.led = None
        try:
            from gpiozero import LED
            self.led = LED(pin)
        except Exception as e:
            print(f"[CẢNH BÁO] Không khởi tạo được GPIO LED pin {pin}: {e}. Chạy chế độ giả lập.")

    def on(self):
        if self.led:
            self.led.on()

    def off(self):
        if self.led:
            self.led.off()


class SafeButton:
    """Nút nhấn vật lý (pull-up nội, nhấn = nối GND), bắt lỗi khi chạy ngoài Raspberry Pi."""

    def __init__(self, pin, on_press):
        self.button = None
        try:
            from gpiozero import Button
            self.button = Button(pin, pull_up=True, bounce_time=0.05)
            self.button.when_pressed = on_press
        except Exception as e:
            print(f"[CẢNH BÁO] Không khởi tạo được nút GPIO {pin}: {e}. Không thể đăng ký bằng nút.")

    def close(self):
        if self.button:
            try:
                self.button.close()
            except Exception:
                pass


servo = SafeServo(SERVO_PIN)
led = SafeLED(LED_PIN)
hw_lock = threading.Lock()   # Tránh các luồng điều khiển phần cứng chồng chéo nhau


def show_idle():
    web_state.update(
        line1="San sang quet...",
        line2="",
        status="IDLE",
        servo_angle=0,
        servo_status="ĐÓNG (0°)",
        led_status=False,
    )


def grant_access(plate):
    """Biển đúng: Web LCD hiện biển số, servo 0 -> 180, giữ 2s, rồi về 0."""
    with hw_lock:
        web_state.update(
            line1="BIEN SO HOP LE",
            line2=plate,
            status="OK",
            plate=plate,
            servo_angle=180,
            servo_status="MỞ (180°)",
            led_status=False,
        )
        servo.angle = 0
        time.sleep(0.3)
        servo.angle = 180
        time.sleep(SERVO_RETURN_TIME)
        servo.detach()           # Ngắt xung trong lúc giữ mở để servo không giật tại chỗ
        time.sleep(HOLD_SECONDS)
        servo.angle = 0
        time.sleep(SERVO_RETURN_TIME)
        servo.detach()           # Ngừng phát xung để servo không giật
        show_idle()


def deny_access(plate):
    """Biển sai: Web LCD hiện KHONG CO, LED sáng 2s (servo không quay)."""
    with hw_lock:
        web_state.update(
            line1="KHONG CO",
            line2=plate,
            status="FAIL",
            plate=plate,
            servo_angle=0,
            servo_status="ĐÓNG (0°)",
            led_status=True,
        )
        led.on()
        time.sleep(HOLD_SECONDS)
        led.off()
        show_idle()


last_seen = {"plate": None, "time": 0.0}   # Biển đọc gần nhất, dùng cho nút đăng ký


def register_plate():
    """Gọi khi nhấn nút vật lý: đăng ký biển vừa đọc được vào DB."""
    plate = last_seen["plate"]
    if not plate or time.time() - last_seen["time"] > REGISTER_WINDOW:
        print("[!] Nhấn nút nhưng chưa đọc được biển số nào, bỏ qua.")
        with hw_lock:
            web_state.update(line1="CHUA THAY BIEN", line2="", status="FAIL")
            time.sleep(1.5)
            show_idle()
        return

    conn = init_db()             # Kết nối riêng vì callback chạy ở luồng khác luồng chính
    try:
        add_plate(conn, plate)
    finally:
        conn.close()
    print("Đã đăng ký biển số mới:", plate)
    with hw_lock:
        web_state.update(line1="DA DANG KY", line2=plate, status="OK", plate=plate)
        time.sleep(HOLD_SECONDS)
        show_idle()


def run_async(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


# ---------------- DATABASE ----------------
def normalize(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS plates (plate TEXT PRIMARY KEY)")
    conn.commit()
    return conn


def add_plate(conn, plate):
    conn.execute("INSERT OR IGNORE INTO plates VALUES (?)", (normalize(plate),))
    conn.commit()


def find_in_db(conn, plate):
    rows = [r[0] for r in conn.execute("SELECT plate FROM plates")]
    if plate in rows:
        return plate
    best = difflib.get_close_matches(plate, rows, n=1, cutoff=FUZZY_THRESHOLD)
    return best[0] if best else None


# ---------------- NHẬN DIỆN ----------------
# Khởi tạo mô hình AI
detector = None
ocr = None


def init_ai_models():
    global detector, ocr
    try:
        from open_image_models import LicensePlateDetector
        from fast_plate_ocr import LicensePlateRecognizer
        print("[*] Đang tải mô hình phát hiện và nhận diện biển số...")
        detector = LicensePlateDetector(detection_model=DETECTOR_MODEL)
        ocr = LicensePlateRecognizer(OCR_MODEL)
        print("[*] Tải mô hình thành công.")
    except Exception as e:
        print(f"[CẢNH BÁO] Không thể khởi tạo mô hình AI: {e}")


def recognize(frame):
    """Trả về (text, box) hoặc (None, None). box = (x1, y1, x2, y2)."""
    if detector is None or ocr is None:
        return None, None

    detections = [d for d in detector.predict(frame) if d.confidence >= MIN_DET_CONF]
    if not detections:
        return None, None

    best = max(detections, key=lambda d: d.confidence)
    b = best.bounding_box
    h, w = frame.shape[:2]
    x1, y1 = max(int(b.x1), 0), max(int(b.y1), 0)
    x2, y2 = min(int(b.x2), w), min(int(b.y2), h)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None, None

    result = ocr.run(crop)[0]
    text = result if isinstance(result, str) else result.plate
    text = normalize(text)
    box = (x1, y1, x2, y2)
    return (text if 5 <= len(text) <= 10 else None), box


# ---------------- HIỂN THỊ CỬA SỔ OPENCV ----------------
def put(frame, text, org, color, scale=0.7, thick=2):
    cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 2)
    cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick)


def draw_ui(frame, box, live_text, status, status_plate, status_until):
    now = time.time()
    if box and live_text:
        x1, y1, x2, y2 = box
        cv2.rectangle(frame, (x1, y1), (x2, y2), YELLOW, 2)
        put(frame, live_text, (x1, max(y1 - 8, 20)), YELLOW)

    h = frame.shape[0]
    if status and now < status_until:
        if status == "OK":
            put(frame, "BIEN SO HOP LE: " + status_plate, (10, h - 50), GREEN, 0.8)
            put(frame, "SERVO: 0 -> 180 do", (10, h - 20), GREEN)
        else:
            put(frame, "KHONG CO: " + status_plate, (10, h - 50), RED, 0.8)
            put(frame, "LED: ON", (10, h - 20), RED)
    else:
        put(frame, "San sang quet...", (10, h - 20), (255, 255, 255))

    put(frame, "a: them bien vao DB | q: thoat", (10, 25), (255, 255, 255), 0.55, 1)


# ---------------- BỘ ĐỌC LUỒNG VIDEO LAPTOP ----------------
class StreamCapture:
    """Đọc luồng video MJPEG từ Laptop Server qua background thread để luôn giữ khung hình mới nhất, không tích lũy trễ."""

    def __init__(self, url):
        self.url = url
        self.cap = None
        self.frame = None
        self.frame_id = 0            # Tăng mỗi khi có khung hình mới
        self.running = True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                print(f"[*] Đang kết nối tới Laptop Camera: {self.url} ...")
                self.cap = cv2.VideoCapture(self.url)
                if not self.cap.isOpened():
                    time.sleep(1.0)
                    continue
                print(f"[✓] Đã kết nối thành công tới Laptop Camera: {self.url}")

            ok, f = self.cap.read()
            if ok and f is not None and f.size > 0:
                with self.lock:
                    self.frame = f
                    self.frame_id += 1
            else:
                if self.cap:
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                self.cap = None
                time.sleep(0.5)

    def read(self):
        with self.lock:
            if self.frame is not None:
                return True, self.frame.copy()
            return False, None

    def read_new(self, last_id):
        """Trả về (frame_id, frame) nếu có khung hình mới hơn last_id, ngược lại (last_id, None)."""
        with self.lock:
            if self.frame is not None and self.frame_id != last_id:
                return self.frame_id, self.frame.copy()
            return last_id, None

    def release(self):
        self.running = False
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass


class AsyncRecognizer:
    """Chạy nhận diện biển số ở luồng nền trên khung hình mới nhất, không chặn luồng hiển thị video."""

    def __init__(self, cap):
        self.cap = cap
        self.running = True
        self.lock = threading.Lock()
        self.result = (0, None, None, 0.0)   # (seq, text, box, thời điểm)
        self.thread = threading.Thread(target=self._worker, daemon=True, name="PlateAI")
        self.thread.start()

    def _worker(self):
        last_id, seq = 0, 0
        while self.running:
            last_id, frame = self.cap.read_new(last_id)
            if frame is None:
                time.sleep(0.005)
                continue
            try:
                text, box = recognize(frame)
            except Exception as e:
                print(f"[Lỗi nhận diện]: {e}")
                time.sleep(0.2)
                continue
            seq += 1
            with self.lock:
                self.result = (seq, text, box, time.time())

    def get(self):
        with self.lock:
            return self.result

    def stop(self):
        self.running = False


# ---------------- MAIN ----------------
def main(camera_url=DEFAULT_CAMERA_URL, web_port=WEB_PORT, show_gui=SHOW_WINDOW):
    global SHOW_WINDOW, cv2
    SHOW_WINDOW = show_gui
    try:
        import cv2
    except ImportError:
        print("[LỖI] Chưa cài đặt OpenCV (python3-opencv hoặc opencv-python).")
        print("Vui lòng chạy: sudo apt install -y python3-opencv hoặc pip install opencv-python")
        return

    conn = init_db()
    init_ai_models()

    # Khởi động Flask Server chạy ngầm
    flask_thread = threading.Thread(target=start_flask, args=(web_port,), daemon=True)
    flask_thread.start()

    # Kết nối tới Laptop Camera Stream
    cap = StreamCapture(camera_url)

    # Đưa servo về 0 rồi ngắt xung để đứng yên không giật
    servo.angle = 0
    time.sleep(0.6)
    servo.detach()
    led.off()
    show_idle()

    button = SafeButton(BUTTON_PIN, lambda: run_async(register_plate))

    recognizer = AsyncRecognizer(cap)
    history = deque(maxlen=CONFIRM_FRAMES)
    last_seq = 0
    box, live_text, box_time = None, None, 0
    status, status_plate, status_until = None, "", 0
    next_allowed = 0
    print(f"[*] Hệ thống sẵn sàng nhận diện từ nguồn: {camera_url}")
    print("[*] Nhấn 'q' trên cửa sổ video (hoặc Ctrl+C) để dừng.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            now = time.time()

            seq, text, b, result_time = recognizer.get()
            if seq != last_seq:
                last_seq = seq
                box, live_text, box_time = b, text, result_time
                history.append(text)
                if text:
                    last_seen["plate"], last_seen["time"] = text, now

                if (
                    now >= next_allowed
                    and text
                    and len(history) == CONFIRM_FRAMES
                    and len(set(history)) == 1
                ):
                    print("Đọc được:", text)
                    matched = find_in_db(conn, text)
                    if matched:
                        status, status_plate = "OK", matched
                        print(f"  -> HỢP LỆ ({matched}) | Servo 0 -> 180 -> 0 | Web LCD cập nhật")
                        run_async(grant_access, matched)
                        hold = HOLD_SECONDS + 2 * SERVO_RETURN_TIME + 0.3
                    else:
                        status, status_plate = "FAIL", text
                        print(f"  -> KHÔNG CÓ TRONG DB ({text}) | LED bật | Web LCD cập nhật")
                        run_async(deny_access, text)
                        hold = HOLD_SECONDS
                    status_until = now + HOLD_SECONDS
                    next_allowed = now + hold + COOLDOWN
                    history.clear()

            if SHOW_WINDOW:
                show_box = box if now - box_time < 0.6 else None
                draw_ui(frame, show_box, live_text, status, status_plate, status_until)
                try:
                    cv2.imshow("Nhan dien bien so - Web Dashboard Active", frame)
                    key = cv2.waitKey(15) & 0xFF
                except cv2.error:
                    print("[*] Không mở được cửa sổ OpenCV GUI, tự động chuyển sang chế độ không màn hình.")
                    SHOW_WINDOW = False
                    continue

                if key == ord("q"):
                    break
            else:
                time.sleep(0.02)

    except KeyboardInterrupt:
        print("\n[*] Đang tắt hệ thống...")
    finally:
        recognizer.stop()
        button.close()
        cap.release()
        if SHOW_WINDOW:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        with hw_lock:
            servo.detach()
            led.off()
            web_state.update(line1="DA DUNG HE THONG", line2="", status="IDLE")
        print("[*] Đã dọn dẹp và dừng tiến trình an toàn.")


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Nhận diện biển số xe nhận stream từ Laptop Camera Server")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "add"],
                        help="Lệnh thực thi: 'run' (mặc định) hoặc 'add' để thêm biển số vào DB")
    parser.add_argument("plate", nargs="?", default=None,
                        help="Biển số xe cần thêm vào DB (khi dùng lệnh 'add')")
    parser.add_argument("--source", "-s", default=DEFAULT_CAMERA_URL,
                        help=f"URL luồng video từ Laptop Camera (mặc định: {DEFAULT_CAMERA_URL})")
    parser.add_argument("--web-port", type=int, default=WEB_PORT,
                        help=f"Cổng Flask Web Dashboard trên Pi (mặc định: {WEB_PORT})")
    parser.add_argument("--no-window", action="store_true",
                        help="Chạy chế độ không mở cửa sổ OpenCV GUI (headless/SSH)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.command == "add" and args.plate:
        c = init_db()
        add_plate(c, args.plate)
        print("Đã thêm biển số vào DB:", normalize(args.plate))
    else:
        main(camera_url=args.source, web_port=args.web_port, show_gui=not args.no_window)
