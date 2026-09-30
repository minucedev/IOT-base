# config.py
"""
Cấu hình hệ thống nhận diện khói & lửa nhận stream từ Laptop Camera Server
"""

# Đường dẫn tới model weights (ONNX tối ưu cho Raspberry Pi)
MODEL_PATH = "models/fire_smoke_yolov8n.onnx"

# Ngưỡng độ tin cậy để kích hoạt cảnh báo (0.0 - 1.0)
CONFIDENCE_THRESHOLD = 0.30
IOU_THRESHOLD = 0.45

# Độ phân giải xử lý ảnh
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# --- CẤU HÌNH CAMERA STREAM TỪ LAPTOP ---
DEFAULT_CAMERA_URL = "http://10.232.65.44:5000/video_feed"

# Đảo kênh màu R-B (False = mặc định BGR chuẩn OpenCV). Có thể bấm phím 'c' khi đang chạy.
CAMERA_SWAP_RB = False

# Thời gian duy trì đèn LED sáng (giây) sau khi ngọn lửa bị chớp tắt (tránh nhấp nháy gián đoạn)
HOLD_FIRE_TIME = 1.5

# --- CẤU HÌNH ĐÈN CẢNH BÁO LỬA (LED) TRÊN PI ---
# Chân BCM GPIO nối đèn LED cảnh báo lửa (BCM 27 = Physical Pin 13)
LED_PIN = 27

# --- CẤU HÌNH CÒI BUZZER TRÊN PI ---
# Chân BCM GPIO nối còi buzzer trên Pi (BCM 17 = Physical Pin 11)
BUZZER_PIN = 17

# Loại còi: "passive" (cần xung PWM) hoặc "active" (cấp mức HIGH tự kêu)
BUZZER_TYPE = "passive"

# Tần số phát âm cho Passive Buzzer (Hz)
BUZZER_FREQUENCY = 2000

# Thời gian còi kêu mỗi lần cảnh báo (giây)
ALERT_DURATION = 2.0

# Thời gian tối thiểu giữa 2 lần cảnh báo liên tiếp (cooldown, giây)
ALERT_COOLDOWN = 5.0

# --- LƯU ẢNH SNAPSHOT ---
SAVE_SNAPSHOT = False
SNAPSHOT_DIR = "data/snapshots"

# --- HIỂN THỊ MÀN HÌNH ---
# Hiện cửa sổ video (cv2.imshow). Đặt True để hiện màn hình camera, False nếu chạy headless (không màn hình)
SHOW_DISPLAY = True
WINDOW_NAME = "Hệ thống nhận diện lửa - IoT"
