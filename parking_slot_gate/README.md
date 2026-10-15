# Bãi đỗ xe thông minh: nhận diện ô trống + cảm biến siêu âm + servo

Xe tới gần → HC-SR04 phát hiện → quét ảnh `parking.jpg` tìm ô trống (YOLOv8n ONNX + kiểm tra màu từng ô)
→ **chỉ khi có ô trống** servo mới mở, LED xanh sáng, LCD/loa hướng dẫn ô cần đến.
Hết chỗ: servo đóng, LED đỏ, LCD "BAI DA DAY".

## File
| File | Việc |
|---|---|
| `raspberry_parking_yolov8n_1280_speaker_jpg.py` | Chương trình chính chạy trên Raspberry Pi |
| `slots.json` | 27 ô đỗ (polygon theo ảnh 1000x750) |
| `parking.jpg` | Ảnh bãi đỗ dùng làm đề tài |
| `parking_left_empty.jpg` + `slots_left.json` | Demo còn chỗ (18 ô A, B) |
| `parking_right_full.jpg` + `slots_right.json` | Demo hết chỗ (9 ô C) |
| `yolov8n_640.onnx` | Model YOLOv8n COCO (input 640, float16) |
| `laptop_speaker.py` | (tuỳ chọn) Loa đọc thông báo trên laptop Ubuntu |

## Linh kiện
Raspberry Pi (có I2C bật), HC-SR04, servo SG90/MG90S, 2 LED (đỏ, xanh), 2 điện trở 220 Ω,
1 điện trở 1 kΩ + 1 điện trở 2 kΩ (chia áp cho Echo), LCD 16x2 I2C (PCF8574), nguồn 5 V ngoài cho servo, breadboard + dây.

## Sơ đồ nối dây (số GPIO là BCM)

| Linh kiện | Chân linh kiện | Nối tới Pi | Chân vật lý |
|---|---|---|---|
| HC-SR04 | VCC | 5V | 2 |
| HC-SR04 | TRIG | GPIO 23 | 16 |
| HC-SR04 | ECHO | GPIO 24 **qua chia áp** | 18 |
| HC-SR04 | GND | GND | 6 |
| Servo | Đỏ (VCC) | **5V nguồn ngoài** | - |
| Servo | Nâu/đen (GND) | GND nguồn ngoài **và** GND Pi | 14 |
| Servo | Cam/vàng (tín hiệu) | GPIO 18 | 12 |
| LED đỏ | Anode (+) qua 220 Ω | GPIO 27 | 13 |
| LED xanh | Anode (+) qua 220 Ω | GPIO 22 | 15 |
| LED đỏ/xanh | Cathode (−) | GND | 9 / 20 |
| LCD I2C | VCC | 5V | 4 |
| LCD I2C | GND | GND | 39 |
| LCD I2C | SDA | GPIO 2 (SDA1) | 3 |
| LCD I2C | SCL | GPIO 3 (SCL1) | 5 |

### Chia áp cho chân ECHO (bắt buộc)
ECHO của HC-SR04 ra 5 V, chân GPIO Pi chỉ chịu 3.3 V:
```
HC-SR04 ECHO ──[ 1 kΩ ]──┬── GPIO 24
                          │
                       [ 2 kΩ ]
                          │
                         GND
```

### Servo
- Cấp 5 V từ **nguồn ngoài** (không lấy từ chân 5V của Pi để tránh sụt áp / reset Pi).
- **Nối chung GND** giữa nguồn ngoài và Pi.

## Cài đặt trên Pi
```bash
sudo raspi-config nonint do_i2c 0          # bật I2C
sudo i2cdetect -y 1                        # xem địa chỉ LCD (0x27 hoặc 0x3F)
pip install onnxruntime opencv-python numpy scipy shapely gpiozero RPLCD
```

## Chạy
```bash
# Thử nhận diện ô trống, không GPIO
python raspberry_parking_yolov8n_1280_speaker_jpg.py --once

# Chạy thật với cảm biến + servo + LCD
python raspberry_parking_yolov8n_1280_speaker_jpg.py --sensor-debug

# Thêm loa laptop (trên laptop chạy trước: python3 laptop_speaker.py)
python raspberry_parking_yolov8n_1280_speaker_jpg.py --speaker-url http://IP_LAPTOP:8765/speak
```
### Demo 2 trạng thái (ảnh cắt đôi 500x750)
Không truyền `--scene`/`--image` thì chương trình hỏi chọn ảnh khi chạy. Hoặc chọn sẵn:
```bash
python raspberry_parking_yolov8n_1280_speaker_jpg.py --once --scene trong   # còn chỗ: ô A1–A9, B1–B9
python raspberry_parking_yolov8n_1280_speaker_jpg.py --once --scene day     # hết chỗ: ô C1–C9
python raspberry_parking_yolov8n_1280_speaker_jpg.py --once --scene goc     # ảnh gốc 27 ô
```
`slots_check_left.jpg` / `slots_check_right.jpg`: ảnh vẽ khung ô để kiểm tra polygon.
Bỏ `--once` để chạy thật với servo: ảnh trái → mở cổng, ảnh phải → "BAI DA DAY".

LCD địa chỉ 0x3F: thêm `--lcd-address 0x3F`.

## Tham số nên chỉnh khi đổi ảnh / camera
- `--confidence` (mặc định 0.03): YOLO COCO yếu với ảnh chụp thẳng từ trên xuống nên đặt thấp.
- `--color-threshold` (mặc định 0.08): ô có ≥ 8 % pixel màu xe thì coi là có xe (0 = tắt).
- `--entry-distance 50` / `--exit-distance 65` (cm): ngưỡng xe tới gần / đã rời.

## Lưu ý
- Kết quả trên ảnh mẫu: 11 ô trống, 16 ô có xe. Ngưỡng chỉ được kiểm chứng trên 1 ảnh này.
- Code đọc ảnh tĩnh `parking.jpg`, chưa đọc camera trực tiếp.
- Mô hình thử nghiệm: một cảm biến siêu âm không đủ để đảm bảo an toàn cho rào thật.
