# Hệ Thống Nhận Diện Lửa & Khói Thông Minh (Camera AI + IoT)

Ứng dụng nhận diện ngọn lửa và khói realtime chạy mô hình **YOLOv8 ONNX**, nhận luồng video truyền từ **Laptop Media Stream Server** qua mạng LAN và điều khiển còi hú buzzer + đèn LED cảnh báo trên Raspberry Pi 4.

---

## 1. Sơ Đồ Đấu Nối Phần Cứng (GPIO BCM trên Raspberry Pi)

| Thiết bị | Chân tín hiệu | Chân vật lý | Nguồn cấp | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| **Còi Buzzer (Passive)** | **GPIO 17** | Pin 11 | GND Pi | Còi quét tần số sóng sin 1400-2400Hz (PWM) |
| **Đèn LED Báo Cháy (+ 220Ω)** | **GPIO 27** | Pin 13 | GND Pi | Sáng khi phát hiện lửa (giữ 1.5s) |
| **Camera** | Stream qua mạng LAN | - | Laptop Media Server | URL: `http://10.232.65.44:5000/video_feed` |

---

## 2. Các Bước Triển Khai & Khởi Chạy

### Bước 1: Khởi động Stream Server trên Laptop
Vào thư mục `laptop_cam_server` trên laptop và chạy:

```bash
python3 app.py
# Server bắt đầu stream camera tại: http://10.232.65.44:5000/video_feed
```

### Bước 2: Cài đặt thư viện trên Raspberry Pi
Mở Terminal trên Raspberry Pi:

```bash
cd Fire_smoke_detect_IOT
sudo apt update
sudo apt install -y python3-gpiozero python3-opencv fonts-dejavu-core libgl1 libglib2.0-0
pip install -r requirements.txt --break-system-packages
```

### Bước 3: Chạy chương trình nhận diện trên Raspberry Pi
Chạy với nguồn stream mặc định (`http://10.232.65.44:5000/video_feed`):

```bash
python3 main.py

# Hoặc tùy biến URL khi laptop đổi IP:
python3 main.py --source http://10.232.65.44:5000/video_feed

# Nếu chạy SSH không có màn hình hiển thị:
python3 main.py --no-window
```

---

## 3. Phím Tắt Điều Khiển (Khi có cửa sổ OpenCV)

- `q` hoặc `Esc`: Thoát ứng dụng.
- `c`: Đảo kênh màu R-B (nếu webcam laptop bị sai hệ màu).

---

## 4. Tùy Chọn Cấu Hình (`config.py`)

- `CONFIDENCE_THRESHOLD`: Ngưỡng tin cậy kích hoạt cảnh báo lửa (mặc định: `0.30`).
- `HOLD_FIRE_TIME`: Thời gian giữ đèn LED sáng ổn định (mặc định: `1.5s`).
- `BUZZER_FREQUENCY`: Tần số còi passive (mặc định: `2000Hz`).
- `SHOW_DISPLAY`: `True` nếu có màn hình hiển thị, `False` nếu chạy headless.
