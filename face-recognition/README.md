# Face Recognition trên Raspberry Pi (HTTP Stream)

Ứng dụng nhận diện khuôn mặt thời gian thực chạy trên Raspberry Pi, sử dụng OpenCV YuNet (Face Detection) + SFace (Face Recognition) và Flask Web UI, lấy nguồn video từ webcam Laptop qua HTTP MJPEG stream.

---

## 1. Cấu hình IP Laptop Stream

Mở file [`camera.py`](camera.py) và sửa hằng số `CAMERA_URL` ở ngay đầu file:

```python
# camera.py
CAMERA_URL = "http://<LAPTOP_IP>:5000/video_feed"
```

*(Thay `<LAPTOP_IP>` bằng địa chỉ IP của Laptop hiển thị khi bạn bật `laptop_cam_server` trên máy tính).*

---

## 2. Tải Mô hình ONNX (Chỉ cần chạy lần đầu)

Trên Raspberry Pi:

```bash
cd IOT-base/face-recognition
./download_models.sh
```

---

## 3. Cài đặt thư viện & Khởi chạy trên Pi

Cài đặt thư viện:
```bash
pip install -r requirements.txt
```

Khởi chạy ứng dụng:
```bash
python3 main.py
# Hoặc: ./run.sh
```

---

## 4. Truy cập giao diện Web

Mở trình duyệt trên máy tính/điện thoại trong cùng mạng:
```
http://<RASPBERRY_PI_IP>:5000
```

Các tính năng trên giao diện:
- **Xem luồng camera trực tiếp** kèm khung nhận diện khuôn mặt và tên người đã lưu.
- **Đăng ký người mới**: Nhập tên và bấm *Đăng ký khuôn mặt* (thu thập vector đặc trưng và lưu ảnh chân dung vào SQLite database).
- **Quản lý danh sách**: Xem và xóa người đã đăng ký.
- **Lịch sử nhận diện**: Nhật ký các lần nhận diện theo thời gian thực (UTC+7).
