"""
Nhận diện biển số xe realtime trên Raspberry Pi 4 tích hợp Flask Web Dashboard
- Thay thế màn hình LCD 16x2 bằng giao diện Web Flask (hiển thị mô phỏng LCD 16x2 realtime)
- Webcam USB -> phát hiện biển số (YOLOv9 tiny) -> OCR (fast-plate-ocr)
- So khớp với SQLite (plates.db)
- ĐÚNG : Web LCD hiện biển số, servo quay 0 -> 180 độ, giữ 2 giây rồi về 0
- SAI  : Web LCD hiện "KHONG CO", đèn LED sáng 2 giây
- Dù đúng hay sai đều giữ kết quả 2 giây rồi mới quét tiếp
- Servo dùng PWM PHẦN CỨNG (rpi-hardware-pwm) trên GPIO12
- Đèn LED báo sai trên GPIO16

Nối dây:
    Servo tín hiệu -> GPIO12 (chân vật lý 32) | VCC servo -> nguồn 5V ngoài, GND chung với Pi
    LED (+220 ohm) -> GPIO16 (chân vật lý 36)
    (Không cần đấu nối LCD I2C)

Cài đặt trên Raspberry Pi:
    sudo apt update
    sudo apt install -y python3-opencv
    pip install open-image-models fast-plate-ocr onnxruntime gpiozero rpi-hardware-pwm flask --break-system-packages

    Bật PWM phần cứng: thêm dòng sau vào cuối /boot/firmware/config.txt rồi reboot
        dtoverlay=pwm,pin=12,func=4
    Kiểm tra: ls /sys/class/pwm/ (phải thấy pwmchip0)

Chạy:
    python3 main_rasp.py                  # Chạy nhận diện + mở Web Dashboard tại http://<IP_RASP>:5000
    python3 main_rasp.py add 43A12345     # Thêm biển số vào database qua CLI

Phím tắt (khi có cửa sổ video OpenCV):
    a = thêm biển vừa đọc vào DB
    q = thoát
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
CAMERA_INDEX = 0
SHOW_WINDOW = True           # True: mở cửa sổ OpenCV GUI nếu có màn hình; False: headless
cv2 = None                   # Được import trong hàm main() khi khởi chạy webcam

# Flask Config
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000

# Servo: GPIO12 = PWM kênh 0 (dtoverlay=pwm,pin=12,func=4)
SERVO_PWM_CHANNEL = 0
SERVO_PWM_CHIP = 0           # Pi 4 = 0, Pi 5 = 2
LED_PIN = 16                 # GPIO16 = chân vật lý 36

DETECTOR_MODEL = "yolo-v9-t-384-license-plate-end2end"
OCR_MODEL = "cct-xs-v2-global-model"

MIN_DET_CONF = 0.5
CONFIRM_FRAMES = 3           # Đọc giống nhau N lần liên tiếp mới chấp nhận
FUZZY_THRESHOLD = 0.90       # 1.0 = khớp tuyệt đối
PROCESS_EVERY_N_FRAMES = 4   # Tăng lên để giảm tải CPU
HOLD_SECONDS = 2             # Giữ kết quả (đúng hay sai đều 2 giây)
SERVO_RETURN_TIME = 0.6      # Thời gian chờ servo quay về 0
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


def start_flask():
    try:
        app = create_flask_app()
        print(f"[*] Flask Web Dashboard đang chạy tại http://{WEB_HOST}:{WEB_PORT}")
        app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        print(f"[CẢNH BÁO] Không thể khởi động Flask Web Server: {e}")


# ---------------- PHẦN CỨNG ----------------
class HwServo:
    """Servo dùng PWM phần cứng, độc lập với CPU."""

    def __init__(self, channel=0, chip=0, min_us=500, max_us=2500):
        self.channel, self.chip = channel, chip
        self.min_us, self.max_us = min_us, max_us
        self.running = False
        self._angle = 0
        self.pwm = None
        try:
            from rpi_hardware_pwm import HardwarePWM
            self.pwm = HardwarePWM(pwm_channel=channel, hz=50, chip=chip)
        except Exception as e:
            print(f"[CẢNH BÁO] Không khởi tạo được HardwarePWM: {e}. Chạy chế độ giả lập.")

    @property
    def angle(self):
        return self._angle

    @angle.setter
    def angle(self, value):
        self._angle = value
        if self.pwm:
            try:
                pulse_us = self.min_us + (self.max_us - self.min_us) * value / 180
                duty = pulse_us / 20000 * 100      # chu kỳ 20 ms = 50 Hz
                if self.running:
                    self.pwm.change_duty_cycle(duty)
                else:
                    self.pwm.start(duty)
                    self.running = True
            except Exception as e:
                print(f"[Lỗi Servo PWM]: {e}")

    def detach(self):
        """Ngừng phát xung để servo đứng yên, không rung."""
        if self.pwm and self.running:
            try:
                self.pwm.stop()
            except Exception:
                pass
            self.running = False


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


servo = HwServo(channel=SERVO_PWM_CHANNEL, chip=SERVO_PWM_CHIP)
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


# ---------------- MAIN ----------------
def main():
    global SHOW_WINDOW, cv2
    try:
        import cv2
    except ImportError:
        print("[LỖI] Chưa cài đặt OpenCV (python3-opencv hoặc opencv-python).")
        print("Vui lòng chạy: sudo apt install -y python3-opencv hoặc pip install opencv-python")
        return

    conn = init_db()
    init_ai_models()

    # Khởi động Flask Server chạy ngầm
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened():
        print(f"[LỖI] Không mở được webcam tại CAMERA_INDEX={CAMERA_INDEX}")
        return

    # Đưa servo về 0 rồi ngắt xung để đứng yên không giật
    servo.angle = 0
    time.sleep(0.6)
    servo.detach()
    led.off()
    show_idle()

    history = deque(maxlen=CONFIRM_FRAMES)
    frame_count = 0
    box, live_text, box_time = None, None, 0
    last_seen = None
    status, status_plate, status_until = None, "", 0
    next_allowed = 0
    print("[*] Hệ thống sẵn sàng. Truy cập Web Dashboard hoặc nhấn 'q' trên cửa sổ video để thoát.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame_count += 1
            now = time.time()

            if frame_count % PROCESS_EVERY_N_FRAMES == 0:
                text, b = recognize(frame)
                box, live_text, box_time = b, text, now
                history.append(text)
                if text:
                    last_seen = text

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
                        hold = HOLD_SECONDS + SERVO_RETURN_TIME + 0.3
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
                    key = cv2.waitKey(1) & 0xFF
                except cv2.error:
                    print("[*] Không mở được cửa sổ OpenCV GUI, tự động chuyển sang chế độ không màn hình.")
                    SHOW_WINDOW = False
                    continue

                if key == ord("q"):
                    break
                if key == ord("a") and last_seen:
                    add_plate(conn, last_seen)
                    print("Đã thêm vào DB:", last_seen)
            else:
                time.sleep(0.005)

    except KeyboardInterrupt:
        print("\n[*] Đang tắt hệ thống...")
    finally:
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


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "add":
        c = init_db()
        add_plate(c, sys.argv[2])
        print("Đã thêm biển số vào DB:", normalize(sys.argv[2]))
    else:
        main()
