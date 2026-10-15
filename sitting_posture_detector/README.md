# Posture Monitor (Raspberry Pi + YOLOv8n-pose ONNX)

Giám sát tư thế ngồi theo thời gian thực: webcam laptop (stream MJPEG qua mạng) → YOLOv8n-pose (ONNX Runtime) →
tính góc Tai-Vai-Hông → overlay + 4 LED trạng thái + còi PWM + web stream MJPEG.

## 1. Phần cứng

| Linh kiện | Nối với |
|---|---|
| LED Tốt - GOOD (anode, qua điện trở 220–330 Ω) | GPIO17 (chân vật lý 11) |
| LED Gù - SLOUCH (anode, qua điện trở) | GPIO27 (chân vật lý 13) |
| LED Nghiêng - LEAN (anode, qua điện trở) | GPIO22 (chân vật lý 15) |
| LED Cúi đầu - HEAD_DOWN (anode, qua điện trở) | GPIO23 (chân vật lý 16) |
| Còi passive (chân +) | GPIO24 (chân vật lý 18), điều khiển PWM |
| Catode các LED, chân − còi | GND (chân vật lý 9, 14 hoặc 20) |

Đổi chân trong `config.py` (`LED_PINS`, `BUZZER_PIN`, đánh số BCM).

**Đặt camera:** nhìn ngang từ bên cạnh (~90°) ở độ cao vai/đầu, thấy rõ một bên tai–vai–hông.
Nhìn chính diện chỉ đo được độ nghiêng vai, không đo được gù/cúi.

## 2. Cài đặt môi trường (Raspberry Pi OS Bookworm 64-bit)

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip

cd posture-monitor
python3 -m venv --system-site-packages .venv   # để dùng gpiozero/lgpio cài sẵn từ apt
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Chuẩn bị model ONNX

Export trên PC (không nên trên Pi):

```bash
pip install ultralytics
yolo export model=yolov8n-pose.pt format=onnx imgsz=640 simplify=True opset=12
cp yolov8n-pose.onnx posture-monitor/models/
```

Cần tốc độ cao hơn: export `imgsz=320` (hoặc `imgsz=416`). `detector.py` tự đọc kích thước đầu vào từ model.

## 4. Chạy

**Trên laptop** (cùng mạng LAN với Pi) — phát webcam:

```bash
pip install opencv-python
python laptop_stream.py --port 8080 --cam 0
```

Kiểm tra bằng trình duyệt: `http://<ip-laptop>:8080/video`. Trên Windows nhớ cho phép Python qua Firewall.

**Trên Pi** — đặt `CAMERA_SOURCE = "http://<ip-laptop>:8080/video"` trong `config.py`, rồi:

```bash
python app.py
```

Mất stream thì Pi tự kết nối lại sau `CAMERA_RECONNECT_SEC`.

Mở `http://<ip-của-pi>:5000`. Dừng bằng `Ctrl+C`.

| Endpoint | Mô tả |
|---|---|
| `/` | Giao diện web |
| `/video_feed` | Luồng MJPEG |
| `/api/status` | JSON: trạng thái, các góc, FPS, LED (`led.GOOD/SLOUCH/LEAN/HEAD_DOWN`) |
| `/healthz` | Kiểm tra sống |

Luồng MJPEG được lấy từ frame camera mới nhất và chạy độc lập với nhận diện tư thế; vì vậy
độ mượt của hình không còn bị giới hạn bởi tốc độ ONNX. Overlay được cập nhật theo lần nhận
diện mới nhất. Chất lượng JPEG mặc định là 70 trong `config.py` để giảm dung lượng truyền.

## 5. Logic phân loại

| Trạng thái | Điều kiện (mặc định, `config.py`) |
|---|---|
| Gù (SLOUCH) | Góc Tai-Vai-Hông < 145° |
| Cúi đầu (HEAD_DOWN) | Góc vai→tai lệch phương thẳng đứng > 30° |
| Nghiêng (LEAN) | Góc hông→vai lệch phương thẳng > 15°, hoặc vai lệch ngang > 10° (nhìn chính diện) |

Mỗi LED sáng theo trạng thái hiện tại. Cả 3 tư thế sai đều làm còi kêu (PWM `BUZZER_FREQ` Hz, duty `BUZZER_DUTY`) khi sai liên tục
≥ `BAD_POSTURE_HOLD_SEC` (1 s); ngồi đúng lại thì tắt ngay. Không thấy người: tắt hết.
**Các ngưỡng là điểm khởi đầu** — hãy ngồi tư thế chuẩn, xem số góc trên web rồi chỉnh theo bạn.

## 6. Chạy tự động khi khởi động (systemd)

`/etc/systemd/system/posture.service`:

```ini
[Unit]
Description=Posture Monitor
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/posture-monitor
ExecStart=/home/pi/posture-monitor/.venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now posture.service
```

## 7. Xử lý sự cố

- **FPS thấp**: export model `imgsz=320`, giảm `CAMERA_RESOLUTION`, hạ `INFERENCE_MAX_FPS`.
- **`Không mở được nguồn video`**: kiểm tra IP laptop, `laptop_stream.py` đang chạy, Firewall Windows, Pi và laptop cùng mạng.
- **LED không sáng**: kiểm tra chiều LED, điện trở, chân BCM; log sẽ báo "chế độ giả lập" nếu GPIO lỗi.
- **Ảnh ngược**: đặt `CAMERA_HFLIP` / `CAMERA_VFLIP` trong `config.py`.
- **Pi 5**: nếu gpiozero lỗi, `sudo apt install python3-lgpio`.
