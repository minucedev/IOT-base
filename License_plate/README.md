# Hệ Thống Nhận Diện Biển Số Xe Tích Hợp Web Dashboard (Raspberry Pi 4)

Dự án nhận diện biển số xe tự động điều khiển cổng Barrier trên Raspberry Pi 4. Màn hình LCD 16x2 vật lý trước đây đã được thay thế hoàn toàn bằng **Flask Web Dashboard** hiển thị giao diện mô phỏng LCD 16x2 và trạng thái servo / LED theo thời gian thực (realtime).

---

## 1. Sơ Đồ Đấu Nối Phần Cứng (GPIO BCM)

> **Lưu ý:** Dự án này **không cần** kết nối màn hình LCD 16x2 I2C nữa.

| Thiết bị | Chân tín hiệu | Chân vật lý | Nguồn cấp | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| **Servo Barrier (SG90/MG996R)** | **GPIO 12** | Pin 32 | Nguồn 5V ngoài + GND chung Pi | Dùng Hardware PWM (kênh 0) |
| **Đèn LED Báo Lỗi (+ Trở 220Ω)** | **GPIO 16** | Pin 36 | GND Pi | Sáng 2 giây khi biển số không hợp lệ |
| **Webcam USB** | Cổng USB | Cổng USB 2.0 / 3.0 | Nguồn từ Pi | Đặt góc quay trực diện biển số |

---

## 2. Chuẩn Bị & Cấu Hình Raspberry Pi

### Bật PWM Phần Cứng cho Servo
Thêm cấu hình sau vào file cấu hình boot của Raspberry Pi:

```bash
sudo nano /boot/firmware/config.txt
# (Đối với Raspberry Pi OS cũ là /boot/config.txt)
```

Thêm dòng sau vào cuối file:
```ini
dtoverlay=pwm,pin=12,func=4
```

Lưu file và khởi động lại Raspberry Pi:
```bash
sudo reboot
```

Sau khi reboot, kiểm tra kênh PWM đã xuất hiện:
```bash
ls /sys/class/pwm/
# Kết quả phải thấy: pwmchip0
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

### Thêm biển số được phép vào Database
Trước khi chạy, bạn có thể thêm các biển số xe hợp lệ vào cơ sở dữ liệu SQLite (`plates.db`):

```bash
python3 main_rasp.py add 43A12345
python3 main_rasp.py add 29B99999
```

### Chạy Hệ Thống Nhận Diện + Web Server
Chạy chương trình chính:

```bash
python3 main_rasp.py
```

- **OpenCV Window:** Nhấn phím `a` trên cửa sổ video để thêm ngay biển số vừa đọc vào DB; nhấn `q` để thoát.
- **Web Dashboard:** Mở trình duyệt từ điện thoại, máy tính cùng mạng Wi-Fi/LAN:
  ```
  http://<IP_RASPBERRY_PI>:5000
  ```
  *(Ví dụ: `http://192.168.1.50:5000`)*

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
