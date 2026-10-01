# Hệ Thống Nhận Diện Biển Số Xe Tích Hợp Web Dashboard (Raspberry Pi 4)

Dự án nhận diện biển số xe tự động điều khiển cổng Barrier trên Raspberry Pi 4. Màn hình LCD 16x2 vật lý trước đây đã được thay thế hoàn toàn bằng **Flask Web Dashboard** hiển thị giao diện mô phỏng LCD 16x2 và trạng thái servo / LED theo thời gian thực (realtime).

---

## 1. Sơ Đồ Đấu Nối Phần Cứng (GPIO BCM)

> **Lưu ý:** Dự án này **không cần** kết nối màn hình LCD 16x2 I2C nữa.

| Thiết bị | Chân tín hiệu | Chân vật lý | Nguồn cấp | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| **Servo Barrier (SG90/MG996R)** | **GPIO 12** | Pin 32 | Nguồn 5V ngoài + GND chung Pi | Điều khiển bằng gpiozero `AngularServo` |
| **Đèn LED Báo Lỗi (+ Trở 220Ω)** | **GPIO 16** | Pin 36 | GND Pi | Sáng 2 giây khi biển số không hợp lệ |
| **Nút nhấn đăng ký biển số** | **GPIO 20** | Pin 38 | GND (Pin 39) | Pull-up nội, nhấn = nối GND. Nhấn khi biển đang trước camera để đăng ký vào DB |
| **Camera** | Stream qua mạng LAN | - | Laptop Media Stream Server | URL: `http://10.232.65.44:5000/video_feed` |

---

## 2. Chuẩn Bị & Cấu Hình Raspberry Pi

### Test phần cứng
Servo, LED và nút nhấn đều dùng thư viện `gpiozero`, không cần cấu hình PWM phần cứng. Nếu trước đây đã thêm dòng `dtoverlay=pwm,pin=12,func=4` vào `/boot/firmware/config.txt` thì xóa dòng đó rồi reboot.

Sau khi cài thư viện (mục 3), kiểm tra đấu nối:

```bash
python3 test_hardware.py          # test lần lượt servo, LED, nút
python3 test_hardware.py servo    # hoặc chỉ test một phần: servo | led | button
```

---

## 3. Cài Đặt Thư Viện

Cài đặt các gói hệ thống và thư viện Python cần thiết:

```bash
sudo apt update
sudo apt install -y python3-opencv

cd License_plate
pip install -r requirements.txt --break-system-packages
```

---

## 4. Hướng Dẫn Sử Dụng

### Bước 1: Khởi động Camera Stream Server trên Laptop
Vào thư mục `laptop_cam_server` trên laptop và chạy:
```bash
python3 app.py
# Server phát luồng tại: http://10.232.65.44:5000/video_feed
```

### Bước 2: Thêm biển số được phép vào Database (trên Pi)
Trước khi chạy, bạn có thể thêm các biển số xe hợp lệ vào SQLite (`plates.db`):

```bash
python3 main_rasp.py add 43A12345
python3 main_rasp.py add 29B99999
```

### Bước 3: Chạy Hệ Thống Nhận Diện + Web Server (trên Pi)
Chạy chương trình chính (mặc định lấy stream từ `http://10.232.65.44:5000/video_feed`):

```bash
python3 main_rasp.py

# Hoặc tùy biến URL laptop / cổng web:
python3 main_rasp.py --source http://10.232.65.44:5000/video_feed --web-port 8080

# Nếu chạy SSH không màn hình:
python3 main_rasp.py --no-window
```

- **Nút vật lý:** Đặt biển số trước camera rồi nhấn nút (GPIO20) để đăng ký biển vừa đọc vào DB. Web LCD hiện `DA DANG KY`. Nếu không có biển nào được đọc trong 3 giây gần nhất, LCD hiện `CHUA THAY BIEN`.
- **OpenCV Window:** Nhấn `q` để thoát.
- **Web Dashboard:** Mở trình duyệt từ điện thoại, máy tính cùng mạng Wi-Fi/LAN:
  ```
  http://<IP_RASPBERRY_PI>:8080
  ```

### Giao Diện Web Dashboard Hiển Thị:
- Màn hình LCD 16x2 retro mô phỏng:
  - Dòng 1: `BIEN SO HOP LE` hoặc `KHONG CO` hoặc `San sang quet...`
  - Dòng 2: Biển số xe được nhận diện
- Trạng thái Barrier: `ĐÓNG (0°)` hoặc `MỞ (180°)`
- Trạng thái đèn cảnh báo LED: `TẮT` hoặc `SÁNG ĐỎ`

---

## 5. Hướng Dẫn Commit & Push Lên Git

Từ thư mục gốc của repository `IOT-base`:

```bash
git status
git add License_plate/
git commit -m "feat: add License_plate module with Flask Web Dashboard replacing LCD"
git push origin main
```
