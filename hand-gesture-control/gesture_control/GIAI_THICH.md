# Giải thích: điều khiển đèn + quạt bằng cử chỉ tay

## 1. Hệ thống làm gì

Dùng camera laptop nhìn bàn tay, Raspberry Pi nhận diện cử chỉ bằng model MediaPipe (chạy qua LiteRT) và điều khiển đèn LED + quạt (motor DC).

| Cử chỉ | Tác dụng |
|---|---|
| Xòe cả bàn tay | **Mở khóa** điều khiển (không đổi đèn/quạt) |
| Ngón trỏ | Bật đèn |
| Ngón cái (lên hoặc xuống) | Tắt quạt |
| Còn lại (nắm tay, Victory, ILoveYou) | Tắt hết đèn + quạt |

Hệ thống **khóa** lúc khởi động: chưa xòe tay thì mọi cử chỉ khác bị bỏ qua. Lỗi camera, timeout hoặc dừng chương trình sẽ khóa lại. Nắm tay tắt hết nhưng vẫn giữ trạng thái đã mở khóa.

## 2. Luồng hoạt động

```
Laptop                         Raspberry Pi
camera --> laptop_cam_server   app.py
           (MJPEG :5000) ----> cv2.VideoCapture(URL)
                                  |
                                  v
                          hand_pipeline.py (model MediaPipe qua LiteRT)
                                  |
                          gesture_logic.py  (chọn nhãn + giữ ổn định 0.4s)
                                  |
                          gpio_outputs.py   (khóa/mở, đèn, quạt)
                                  |
                          GPIO: LED, L298N --> quạt
                                  |
                          Flask web (:5000 trên Pi): xem hình + trạng thái
```

## 3. Các file chính

- `laptop_cam_server.py` — chạy trên laptop, phát hình camera qua HTTP (MJPEG).
- `app.py` — chạy trên Pi: đọc stream, nhận diện, ra lệnh, mở web xem trạng thái.
- `gesture_logic.py` — gom nhãn của model thành 4 nhóm lệnh; `StableGesture` yêu cầu giữ cử chỉ ổn định `HOLD_SECONDS` (0.4s) mới ra lệnh, tránh nhiễu.
- `gpio_outputs.py` — logic khóa/mở và điều khiển chân GPIO. Có watchdog tự tắt đầu ra nếu camera ngừng trả hình. Khi không có `RPi.GPIO` (chạy trên laptop) tự chuyển sang giả lập.
- `test_gpio.py`, `test_camera.py` — thử riêng GPIO và camera.
- `README.md` — tài liệu gốc từ repo clone về (chi tiết cài đặt trên Pi).

## 4. Sơ đồ cắm dây (BCM)

| Thiết bị | Chân Pi | Ghi chú |
|---|---|---|
| LED | GPIO27 (pin 13) | Qua điện trở 220–330Ω, GND pin 14 |
| L298N IN1 | GPIO23 (pin 16) | |
| L298N IN2 | GPIO24 (pin 18) | |
| L298N ENA | GPIO12 (pin 32) | Tháo jumper ENA |
| GND | pin 6 | Nối chung GND với nguồn ngoài của quạt |

Quạt cấp nguồn ngoài qua L298N, không lấy từ chân 5V của Pi.

## 5. Cách chạy

```bash
# Laptop
pip install flask opencv-python
python laptop_cam_server.py          # in ra http://<IP laptop>:5000/video_feed

# Raspberry Pi
pip install -r requirements.txt
python download_model.py             # nếu thiếu model
CAMERA_URL=http://<IP laptop>:5000/video_feed python app.py
```

Có thể sửa hằng số `CAMERA_URL` trong `app.py`. Đặt `CAMERA_INDEX` nếu dùng webcam cắm trực tiếp.

## 6. Biến môi trường hay dùng

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CAMERA_URL` | trong `app.py` | Địa chỉ stream từ laptop |
| `CAMERA_INDEX` | — | Webcam cục bộ, ưu tiên hơn URL |
| `SCORE_THRESHOLD` | 0.65 | Ngưỡng điểm tin cậy tối thiểu |
| `HOLD_SECONDS` | 0.4 | Thời gian giữ cử chỉ trước khi ra lệnh |
| `FRAME_TIMEOUT` | 3 | Quá số giây này không có hình thì tắt đầu ra |
| `PORT` | 5000 | Cổng web của app |

## 7. Lưu ý

- Theo yêu cầu hiện tại, **không cử chỉ nào bật quạt** (chỉ có lệnh tắt). Muốn bật quạt cần thêm vào hàm `apply()` trong `gpio_outputs.py`.
- Trạng thái trên web là lệnh đã gửi, không phải xác nhận quạt thực sự quay.
