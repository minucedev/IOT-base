# Vietnamese Speech Smart Home Control trên Raspberry Pi

Hệ thống điều khiển thiết bị nhà thông minh bằng giọng nói tiếng Việt thời gian thực (Streaming ASR) trên Raspberry Pi:
- **Nguồn âm thanh:** Stream âm thanh từ microphone Laptop qua TCP Socket (16kHz PCM float32) mà không cần nối thêm cảm biến I2S INMP441 trên Pi.
- **Xử lý AI:** Sử dụng **Silero VAD** (phát hiện giọng nói) + **hynt/Zipformer-30M-RNNT-Streaming-6000h** qua `sherpa-onnx`.
- **Phần cứng điều khiển:** Đèn (GPIO17) và Quạt L298N (GPIO23, 24, 13 PWM), tự động hỗ trợ **Mock Hardware** khi test nếu chưa cắm phần cứng thật.

---

## 1. Cấu hình IP Laptop Audio Stream

Mở file [`audio_client.py`](audio_client.py) và sửa `LAPTOP_IP` thành địa chỉ IP của Laptop:

```python
# audio_client.py
LAPTOP_IP = "192.168.1.100"  # <-- Thay bằng IP Laptop chạy laptop_cam_server
AUDIO_PORT = 5001
```

*(Hoặc có thể truyền qua cờ khi chạy: `python3 speech_control.py --laptop-ip 192.168.1.50`)*.

---

## 2. Tải Mô hình ONNX (Chỉ cần chạy lần đầu)

Trên Raspberry Pi:

```bash
cd IOT-base/speech-control
chmod +x download_models.sh run.sh
./download_models.sh
```

---

## 3. Cài đặt thư viện & Khởi chạy trên Pi

Cài đặt thư viện Python:
```bash
pip install -r requirements.txt
```

Khởi chạy ứng dụng:
```bash
python3 speech_control.py
# Hoặc: ./run.sh
```

---

## 4. Các khẩu lệnh được hỗ trợ

Nói vào microphone của Laptop:
- 💡 **Điều khiển đèn:**
  - *"bật đèn"* / *"mở đèn"* $\rightarrow$ Bật LED / Relay GPIO17.
  - *"tắt đèn"* / *"đóng đèn"* $\rightarrow$ Tắt LED / Relay GPIO17.
- 🌀 **Điều khiển quạt:**
  - *"bật quạt"* / *"mở quạt"* $\rightarrow$ Quay động cơ quạt (L298N GPIO23/24/13).
  - *"tắt quạt"* / *"đóng quạt"* $\rightarrow$ Dừng động cơ quạt.
- ⚡ **Điều khiển đồng thời:**
  - *"bật cả hai"* / *"bật hết"* / *"bật đèn và quạt"* $\rightarrow$ Bật cả đèn và quạt.
  - *"tắt cả hai"* / *"tắt hết"* / *"tắt đèn và quạt"* $\rightarrow$ Tắt cả đèn và quạt.

---

## 5. Sơ đồ nối dây phần cứng trên Raspberry Pi 4

| Thiết bị | Chân thiết bị | Chân GPIO Raspberry Pi | Số Pin vật lý |
|---|---|---:|---:|
| **Đèn / LED** | Cực dương (+) | GPIO17 | Pin 11 |
| **Đèn / LED** | Cực âm (-) | GND | Pin 9 |
| **Quạt L298N** | IN1 | GPIO23 | Pin 16 |
| **Quạt L298N** | IN2 | GPIO24 | Pin 18 |
| **Quạt L298N** | ENA (PWM) | GPIO13 | Pin 33 |
| **Quạt L298N** | GND | GND | Pin 6 |
