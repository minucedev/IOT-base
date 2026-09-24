# ĐẶC TẢ YÊU CẦU ĐỀ TÀI: HỆ THỐNG NHẬN DIỆN KHUÔN MẶT ĐIỀU KHIỂN SERVO VÀ BÁO ĐỘNG TRÊN RASPBERRY PI 4

---

## 1. TỔNG QUAN HỆ THỐNG
Xây dựng một hệ thống nhúng thông minh trên **Raspberry Pi 4**, nhận luồng video thời gian thực từ webcam laptop qua mạng LAN, thực hiện bài toán **Nhận diện khuôn mặt (Face Recognition)** trực tiếp trên Pi 4, hiển thị kết quả trực tiếp lên màn hình máy qua **cửa sổ Desktop OpenCV duy nhất (KHÔNG dùng giao diện Web)** và điều khiển các cơ cấu chấp hành:
1. **Người đã đăng ký (Authorized)**: Động cơ Servo quay **180 độ**, giữ nguyên trong đúng **5 giây**, sau đó quay trở về vị trí cũ (**0 độ**). Nếu người đó vẫn tiếp tục đứng trước camera sau 5 giây thì tiếp tục quay mở lại.
2. **Người lạ (Unknown / Stranger)**: Còi báo động (**Active Buzzer**) hú liên tục không dừng chừng nào người lạ vẫn còn xuất hiện trước camera. Khi người lạ rời khỏi khung hình thì còi tự động ngắt.
3. **Đăng ký khuôn mặt mới (Registration)**: Bấm phím `'r'` ngay tại cửa sổ hiển thị, nhập tên qua Terminal/Dialog, hệ thống tự động thu thập 5 khung hình liên tiếp để trích xuất vector đặc trưng trung bình tối ưu nhất và lưu vào cơ sở dữ liệu SQLite.

---

## 2. ĐẶC TẢ CHI TIẾT CÁC THÀNH PHẦN

### 2.1. Nguồn Video (Camera Streaming)
- **Nguồn phát**: Chạy script [laptop_cam_server.py](file:///D:/Study_space/Ki9/IOT/IOT-base/face-recognition/laptop_cam_server.py) trên Laptop Windows kết nối cùng mạng Wi-Fi/LAN với Pi.
- **Nguồn nhận**: Raspberry Pi 4 kết nối tới stream MJPEG qua `http://<LAPTOP_IP>:5000/video_feed`.
- **Cơ chế**: Luồng nền đọc socket riêng biệt (Reader Thread) với hàng đợi `queue(maxsize=1)` để triệt tiêu hoàn toàn hiện tượng trễ hình (Zero-latency real-time stream). Tự động kết nối lại khi mạng ngắt quãng.

### 2.2. Giao diện Cửa sổ Hiển thị (Desktop OpenCV Window)
- **Loại giao diện**: Cửa sổ đồ họa cục bộ trên màn hình Pi 4 (sử dụng OpenCV `cv2.imshow`), không chạy Web server.
- **Hiển thị trên khung hình**:
  - Khung hình camera thời gian thực với FPS hiển thị ở góc trên.
  - Hộp bao (Bounding Box) khuôn mặt:
    - **Màu xanh lá** + Tên người + Điểm tin cậy (Cosine Similarity) nếu là người quen đã đăng ký.
    - **Màu đỏ** + Nhãn `"UNKNOWN / NGUOI LA"` nếu là người lạ.
  - Thanh trạng thái hệ thống:
    - Trạng thái cửa/servo: `SERVO: [OPEN 180°]` hoặc `SERVO: [CLOSED 0°]`.
    - Trạng thái còi: `ALARM: [ON - DANGER]` hoặc `ALARM: [OFF]`.
    - Hướng dẫn phím tắt: `[r] Đăng ký khuôn mặt | [q] Thoát chương trình`.

### 2.3. Quy trình Đăng ký Khuôn mặt (Face Registration)
1. Khi người dùng bấm phím `'r'` trên bàn phím:
   - Cửa sổ hiển thị trạng thái chờ `REGISTRATION MODE: Enter name in Terminal`.
   - Người dùng nhập tên cần đăng ký vào Terminal console.
   - Hệ thống tự động căn chỉnh và chụp **5 khung hình liên tiếp** của khuôn mặt.
   - Trích xuất 5 vector đặc trưng (128D) từ mô hình SFace, tính toán vector chuẩn đại diện.
   - Lưu vào cơ sở dữ liệu SQLite `data/faces.sqlite3` và cập nhật ngay lập tức vào bộ nhớ cache RAM (Gallery).
   - Hệ thống phát thông báo đăng ký thành công trên màn hình và tiếp tục nhận diện.

### 2.4. Cơ chế Điều khiển Phần cứng (Hardware Actuators)

#### A. Động cơ Servo (SG90) - Chân GPIO 18 (PWM0)
- **Vị trí đóng (Mặc định)**: Góc 0 độ (Duty Cycle ~ 2.5% - 5.0% tại tần số 50Hz).
- **Vị trí mở**: Góc 180 độ (Duty Cycle ~ 10.0% - 12.5% tại tần số 50Hz).
- **Quy trình hoạt động**:
  - Khi phát hiện người quen: Servo lập tức quay sang **180 độ**.
  - Giữ nguyên trạng thái mở trong **5 giây**.
  - Hết 5 giây: Servo quay ngược lại **0 độ**.
  - **Quy tắc lặp**: Không cần thời gian nghỉ (cooldown). Nếu sau 5 giây người quen đó vẫn đứng trước camera, hệ thống sẽ lập tức quay mở lại 180 độ.
  - Sử dụng luồng riêng biệt (`threading.Thread`) để điều khiển thời gian 5s, hoàn toàn không làm đứng hình hay giảm FPS của luồng hiển thị camera.

#### B. Còi Báo Động (Active Buzzer) - Chân GPIO 23
- Sử dụng **Active Buzzer 5V / 3.3V** điều khiển trực tiếp qua mức logic Digital (HIGH = Kêu, LOW = Tắt).
- **Quy trình hoạt động**:
  - Khi khung hình hiện tại có khuôn mặt và phân loại là **Người lạ (Unknown)**: Bật còi báo động (`GPIO.output(23, GPIO.HIGH)`).
  - Còi **hú liên tục không dừng** chừng nào người lạ vẫn còn xuất hiện trước camera.
  - Ngay khi người lạ rời đi (không còn phát hiện khuôn mặt lạ trong khung hình), còi lập tức tắt (`GPIO.output(23, GPIO.LOW)`).

---

## 3. BẢNG PHÂN CÔNG CHÂN PHẦN CỨNG (PIN MAPPING)
| Thiết bị | Chân thiết bị | Chân Raspberry Pi 4 | Chuẩn giao tiếp | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| **Servo SG90** | Tín hiệu (Cam/Vàng) | **GPIO 18** (Pin 12) | Hardware PWM0 (50Hz) | Điều khiển góc quay 0° - 180° |
| **Servo SG90** | Nguồn dương (Đỏ) | **5V Pin** (Pin 2/4) hoặc Nguồn rời 5V | Nguồn 5V DC | Khuyên dùng nguồn 5V riêng nếu sụt áp |
| **Servo SG90** | Đất (Nâu/Đen) | **GND** (Pin 6/14) | Ground chung | Nối chung mass với Pi |
| **Active Buzzer**| Tín hiệu kích | **GPIO 23** (Pin 16) | Digital Output | HIGH = Hú, LOW = Tắt |
| **Active Buzzer**| Nguồn VCC (nếu là module)| **3.3V / 5V** (Pin 1/2)| Nguồn DC | Mức logic 3.3V an toàn |
| **Active Buzzer**| Đất GND | **GND** (Pin 6/9/14) | Ground | Nối mass |

---

## 4. CẤU TRÚC THƯ MỤC DỰ ÁN
```text
face-recognition/
├── DE_BAI.md                   # File này - Toàn bộ đề bài và đặc tả hệ thống
├── WIRING.md                   # Sơ đồ và bảng hướng dẫn nối dây chân GPIO
├── LY_THUYET.md                # Tài liệu lý thuyết chuyên sâu (AI, PWM, Buzzer)
├── laptop_cam_server.py        # Server chạy trên laptop Windows phát camera
├── main.py                     # Chương trình chính (OpenCV Window + Nhận diện + Điều khiển)
├── hardware.py                 # Module điều khiển Servo (GPIO 18) & Buzzer (GPIO 23)
├── recognition.py              # Engine AI: YuNet (Detect) + SFace (Recognize)
├── database.py                 # Cơ sở dữ liệu SQLite lưu trữ vector đặc trưng khuôn mặt
├── camera.py                   # Luồng đọc camera stream không trễ từ laptop
├── download_models.sh          # Script tải model ONNX (YuNet & SFace)
├── models/                     # Chứa 2 file model .onnx
├── requirements.txt            # Thư viện Python cần thiết
├── old_main.py                 # File code Flask web cũ (đã đổi tên)
└── old_templates/              # Thư mục web UI cũ (đã đổi tên)
```
