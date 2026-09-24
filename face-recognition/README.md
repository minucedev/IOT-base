# HỆ THỐNG NHẬN DIỆN KHUÔN MẶT - SERVO & BUZZER TRÊN RASPBERRY PI 4

Ứng dụng nhận diện khuôn mặt thời gian thực cục bộ chạy trên **Raspberry Pi 4**, hiển thị trực tiếp lên một cửa sổ Desktop OpenCV duy nhất (**không dùng giao diện Web**), nhận luồng camera từ Laptop Windows truyền qua mạng LAN và điều khiển các cơ cấu chấp hành phần cứng:
- **Người đã đăng ký (Authorized)**: Động cơ Servo quay **180 độ trong 5 giây** rồi quay về 0 độ (mở cửa). Nếu người đó vẫn đứng trước cam sau 5 giây thì tiếp tục mở lại ngay.
- **Người lạ (Unknown)**: Còi báo động (Active Buzzer) **hú liên tục** chừng nào người lạ còn đứng trước camera.
- **Đăng ký khuôn mặt**: Bấm phím `[r]` trên cửa sổ OpenCV, nhập tên trong Terminal, hệ thống chụp 5 mẫu ảnh để lấy vector đặc trưng tối ưu nhất.

---

## 📚 TÀI LIỆU DỰ ÁN CHI TIẾT
- 📋 [**DE_BAI.md**](DE_BAI.md): Đặc tả chi tiết toàn bộ yêu cầu đề tài, bài toán và quy trình nghiệp vụ.
- 🔌 [**WIRING.md**](WIRING.md): Sơ đồ nối dây chi tiết Raspberry Pi 4 với Servo SG90 và Còi Buzzer (bảng chân GPIO, lưu ý nguồn cấp).
- 🧠 [**LY_THUYET.md**](LY_THUYET.md): Tài liệu lý thuyết nền tảng (Thị giác máy tính YuNet + SFace, Cosine Similarity, xung PWM Servo 50Hz, Buzzer).

---

## ⚡ HƯỚNG DẪN KHỞI CHẠY HỆ THỐNG

### BƯỚC 1: Khởi động Camera Server trên Laptop Windows
Trên máy tính xách tay (có webcam):
```bash
pip install flask opencv-python
python laptop_cam_server.py
```
> Ghi lại địa chỉ IP hiển thị trên màn hình Laptop, ví dụ: `http://192.168.1.50:5000/video_feed`.

---

### BƯỚC 2: Cấu hình địa chỉ Camera trên Raspberry Pi
Mở file [camera.py](camera.py) và điền địa chỉ IP của laptop:
```python
# camera.py
CAMERA_URL = "http://<IP_CUA_LAPTOP>:5000/video_feed"
```

---

### BƯỚC 3: Tải Mô hình AI ONNX (Chỉ chạy 1 lần đầu trên Pi)
```bash
chmod +x download_models.sh
./download_models.sh
```

---

### BƯỚC 4: Chạy ứng dụng chính trên Raspberry Pi 4
Cài đặt thư viện:
```bash
pip install -r requirements.txt
# Lưu ý: Trên Raspberry Pi OS Desktop, khuyên dùng:
# sudo apt update && sudo apt install -y python3-opencv python3-rpi.gpio
```

Khởi chạy hệ thống:
```bash
python3 main.py
```

---

## 🎮 HƯỚNG DẪN THAO TÁC TRÊN CỬA SỔ DESKTOP
- **Quan sát trạng thái**:
  - `DOOR: [OPEN 180 deg]` (Xanh lá) khi servo đang mở, `[CLOSED 0 deg]` khi đang đóng.
  - `ALARM: [ON - DANGER!]` (Đỏ) khi còi đang hú, `[OFF]` khi bình thường.
- **Phím `[r]` hoặc `[R]`**: Kích hoạt chế độ đăng ký khuôn mặt mới.
  1. Bấm `[r]`.
  2. Nhập họ và tên trên cửa sổ Terminal.
  3. Nhìn thẳng vào webcam để máy chụp 5 mẫu ảnh liên tiếp.
  4. Hệ thống cập nhật cơ sở dữ liệu ngay tức thì.
- **Phím `[q]` hoặc `ESC`**: Thoát chương trình an toàn, ngắt còi, đưa servo về 0° và dọn dẹp GPIO.
