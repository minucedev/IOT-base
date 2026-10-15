"""Cấu hình trung tâm cho Posture Monitor. Chỉnh ngưỡng/chân GPIO tại đây."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ----------------------------- Model ---------------------------------
MODEL_PATH = BASE_DIR / "models" / "yolov8n-pose.onnx"
MODEL_INPUT_SIZE = 640        # Chỉ dùng khi model có input shape động
CONF_THRESHOLD = 0.50         # Ngưỡng tin cậy người
NMS_IOU_THRESHOLD = 0.45
KPT_CONF_THRESHOLD = 0.40     # Ngưỡng tin cậy từng keypoint
ORT_NUM_THREADS = 4           # Pi 4/5 có 4 nhân
ORT_PROVIDERS = ["CPUExecutionProvider"]

# ----------------------------- Camera --------------------------------
# Nguồn video: URL stream từ laptop (chạy laptop_stream.py trên laptop),
# hoặc số 0 để dùng webcam USB cắm trực tiếp.
CAMERA_SOURCE = "http://172.31.114.91:8080/video"   # đổi thành IP laptop
CAMERA_RESOLUTION = (640, 480)   # frame được resize về kích thước này
CAMERA_RECONNECT_SEC = 2.0       # chờ trước khi kết nối lại khi mất stream
CAMERA_HFLIP = False
CAMERA_VFLIP = False

# ----------------------------- Inference -----------------------------
INFERENCE_MAX_FPS = 15           # Giới hạn để tránh nghẽn CPU
ANGLE_EMA_ALPHA = 0.4            # Làm mượt góc (0..1, càng nhỏ càng mượt)

# ----------------------------- Trạng thái tư thế ---------------------
STATUS_GOOD = "GOOD"
STATUS_SLOUCH = "SLOUCH"         # Ngồi gù
STATUS_LEAN = "LEAN"             # Nghiêng
STATUS_HEAD_DOWN = "HEAD_DOWN"   # Cúi đầu
STATUS_NO_PERSON = "NO_PERSON"
STATUS_UNKNOWN = "UNKNOWN"       # Thấy người nhưng thiếu keypoint tai/vai/hông
BAD_STATUSES = {STATUS_SLOUCH, STATUS_LEAN, STATUS_HEAD_DOWN}

# Ngưỡng góc (độ) - điểm khởi đầu, hãy hiệu chỉnh theo vị trí đặt camera.
# Camera nên đặt nhìn NGANG (góc ~90°) để đo tai-vai-hông chính xác.
SLOUCH_ESH_MIN_DEG = 145.0       # Góc Tai-Vai-Hông < ngưỡng  -> gù
NECK_FORWARD_MAX_DEG = 30.0      # Góc (vai->tai) lệch phương thẳng đứng > ngưỡng -> cúi đầu
TRUNK_LEAN_MAX_DEG = 15.0        # Góc (hông->vai) lệch phương thẳng đứng > ngưỡng -> nghiêng
SHOULDER_TILT_MAX_DEG = 10.0     # Chỉ dùng khi nhìn chính diện: vai lệch ngang > ngưỡng -> nghiêng

# ----------------------------- Cảnh báo ------------------------------
BAD_POSTURE_HOLD_SEC = 1.0       # Sai tư thế liên tục bao lâu thì còi kêu

# ----------------------------- GPIO (BCM) ----------------------------
# Mỗi trạng thái một LED
LED_PINS = {
    STATUS_GOOD: 17,             # Xanh lá - chân vật lý 11
    STATUS_SLOUCH: 27,           # Gù      - chân vật lý 13
    STATUS_LEAN: 22,             # Nghiêng - chân vật lý 15
    STATUS_HEAD_DOWN: 23,        # Cúi đầu - chân vật lý 16
}
BUZZER_PIN = 24                  # Chân vật lý 18 (còi passive, điều khiển PWM)
BUZZER_ENABLED = True
BUZZER_FREQ = 2000               # Tần số PWM (Hz) = cao độ tiếng còi
BUZZER_DUTY = 0.5                # value khi bật (0.5 = to nhất với còi passive)
BUZZER_ON_SEC = 0.2              # Kêu 0.2s
BUZZER_OFF_SEC = 0.3             # nghỉ 0.3s, lặp lại khi còn sai tư thế

# ----------------------------- Web -----------------------------------
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000
JPEG_QUALITY = 70
