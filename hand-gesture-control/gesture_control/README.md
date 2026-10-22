# Raspberry Pi + webcam USB + cử chỉ tay + LED/motor DC + Flask

Chương trình dùng model MediaPipe Gesture Recognizer có sẵn, thư viện **RPi.GPIO**, một LED và một motor DC qua driver cầu H có IN1/IN2/ENA. Không cần thu dữ liệu hoặc huấn luyện lại.

Đây là nhận diện **bốn nhóm cử chỉ để điều khiển thiết bị**. Model này không dịch câu thủ ngữ tiếng Việt.

## 1. Chức năng và quy tắc điều khiển

**Phiên bản chỉnh sửa:** hệ thống khóa lúc khởi động; phải xòe cả bàn tay để mở khóa.

| Tư thế | Nhãn model | Tác dụng |
|---|---|---|
| Xòe cả bàn tay | `Open_Palm` | Mở khóa điều khiển (không đổi đèn/quạt) |
| Ngón trỏ | `Pointing_Up` | Bật đèn (LED) |
| Ngón cái (lên hoặc xuống) | `Thumb_Up` / `Thumb_Down` | Tắt quạt (motor DC) |
| Còn lại (nắm tay, `Victory`, `ILoveYou`) | `Closed_Fist`… | Tắt hết đèn + quạt |

Khi chưa mở khóa, mọi cử chỉ khác bị bỏ qua. Lỗi camera/timeout/dừng chương trình sẽ khóa lại. `None` (không nhận ra gì) không phát lệnh.

“Thuận” là **IN1=HIGH, IN2=LOW**; “ngược” là **IN1=LOW, IN2=HIGH**. Thuận/ngược là quy ước điện trong mã, không tự bảo đảm chiều kim đồng hồ khi nhìn vào trục. Nếu muốn đổi chiều vật lý tương ứng, đổi hai dây motor ở OUT1/OUT2 khi đã tắt nguồn.

Ví dụ: xòe tay → LED ON, quay thuận → ngón trỏ → LED vẫn ON, motor tiếp tục chiều thuận → ngón cái → LED vẫn ON, quay ngược → nắm tay → cả hai tắt. Ngón trỏ/ngón cái cũng có thể bật motor từ trạng thái dừng; chúng không tự bật LED.

Mặc định:

- Khởi động: LED OFF, motor tắt, ENA duty 0%.
- Chỉ phát lệnh khi điểm model ≥ 0.65 và cùng nhóm cử chỉ liên tục ≥ 0.4 giây.
- Lặp lại cùng chiều không ngắt ENA, nên xòe tay → ngón trỏ không làm motor dừng giữa chừng.
- Đổi thuận ↔ ngược: ENA về 0%, IN1/IN2 về LOW, chờ 0.3 giây rồi chạy chiều mới.
- Khi mất tay, nhãn không thuộc nhóm cho phép hoặc điểm thấp: field nhận diện cập nhật ngay; đầu ra giữ lệnh trước trong tối đa khoảng 2 giây kể từ cử chỉ hợp lệ cuối, rồi cả hai tắt.
- Camera không trả ảnh/lỗi xử lý: tắt đầu ra. Nếu luồng đọc camera/model bị treo, watchdog độc lập tắt đầu ra sau khoảng 3 giây không có kết quả mới.
- `Ctrl+C` hoặc SIGTERM: ngừng nhận lệnh, tắt PWM/đầu ra và `GPIO.cleanup()`.

Không có cảm biến tốc độ hay cảm biến phản hồi LED: field lệnh phản ánh **lệnh đã phát**, không chứng minh motor thực tế quay hoặc LED thực tế sáng.

## 2. Các file trong bộ chương trình

| File | Chức năng |
|---|---|
| `app.py` | Một luồng đọc webcam, chạy model, phát lệnh GPIO và chia sẻ hình ảnh qua Flask |
| `gpio_outputs.py` | RPi.GPIO: LED27, IN1=23, IN2=24, ENA12; PWM, đảo chiều, watchdog, cleanup |
| `gesture_logic.py` | Gộp hai nhãn ngón cái, bỏ nhãn ngoài phạm vi, xác nhận cử chỉ ổn định |
| `templates/index.html` | Web có đúng ba component chính: camera, kết quả cử chỉ, lệnh LED/DC |
| `test_camera.py` | Test webcam độc lập: chụp ảnh, tùy chọn preview trên VNC |
| `test_gpio.py` | Test LED/motor độc lập hoặc phát chuỗi bốn lệnh giả lập, không chạy model |
| `requirements.txt` | Các thư viện Python cần cài |
| `download_model.py` | Kiểm tra model có sẵn hoặc tải lại model chính thức |
| `models/gesture_recognizer.task` | Model có sẵn, đã kèm trong ZIP |
| `models/model_info.json` | Nguồn model và mã SHA256 |
| `models/LICENSE_MODEL.txt` | Giấy phép đi kèm model |
| `VALIDATION.md` | Phạm vi kiểm tra phần mềm của bộ chương trình |

## 3. Phần cứng và đấu dây

Thực hiện đấu dây khi đã tắt nguồn Pi và nguồn motor. Webcam USB **cắm trực tiếp vào Pi**; webcam cắm vào laptop không được VNC tự chia sẻ sang Pi.

Code dùng `GPIO.setmode(GPIO.BCM)`. Bảng dưới có cả số BCM và số thứ tự chân trên header 40 chân:

| Chức năng | Số BCM dùng trong code | Chân vật lý Pi | Nối tới |
|---|---:|---:|---|
| LED | 27 | **13** | Điện trở 330 Ω → chân dương LED |
| Motor IN1 | 23 | **16** | IN1 của driver |
| Motor IN2 | 24 | **18** | IN2 của driver |
| Motor ENA | 12 | **32** | ENA của driver |
| GND | — | **6** | Chân âm LED và GND driver |

**GPIO27 là chân vật lý 13. GPIO12 là chân vật lý 32, không phải chân vật lý 12.** Dùng sơ đồ header của Raspberry Pi để xác định vị trí; không dựa vào hướng ảnh hoặc tự đếm khi chưa biết chân 1.

LED thường: nối chân vật lý 13 tới điện trở 330 Ω; đầu còn lại của điện trở tới chân dương LED (thường là chân dài). Chân âm LED nối GND chân 6. Nếu LED đã cắt chân, mép phẳng vỏ thường đánh dấu phía âm.

### Nếu dùng module L298N, kênh A

| Đầu nối trên L298N | Nối với |
|---|---|
| IN1 | Pi chân vật lý 16, BCM23 |
| IN2 | Pi chân vật lý 18, BCM24 |
| ENA | Pi chân vật lý 32, BCM12; **tháo jumper ENA** |
| OUT1 và OUT2 | Hai đầu motor DC |
| GND | Âm nguồn motor và GND Pi, cùng một mass |
| Vs / đầu nguồn motor thường ghi `+12V` | Dương nguồn motor phù hợp motor và module |
| Nguồn logic 5V | Cấp đúng theo hướng dẫn module/jumper ổn áp của module |

**Tháo jumper ENA trước khi nối ENA vào Pi.** Jumper ENA có thể nối enable tới 5V; không nối GPIO Pi vào điểm đang được kéo lên 5V. `ENA` và `5V-EN` là hai jumper có chức năng khác nhau. Với `5V-EN`, cần làm đúng hướng dẫn module theo điện áp nguồn motor; không tự nối cọc 5V module vào Pi khi chưa xác định đó là đầu vào hay đầu ra.

Motor dùng nguồn qua driver, không nối trực tiếp motor vào GPIO hoặc lấy dòng motor từ GPIO. Pi và driver phải có GND chung. Motor ở OUT1/OUT2 thì dùng IN1/IN2/ENA; nếu motor ở OUT3/OUT4, bộ IN1/IN2/ENA này không điều khiển kênh đó.

Với driver khác, phải kiểm tra chân enable, nguồn logic và mọi chân standby bổ sung của driver; bộ dây trên nhắm tới L298N hoặc driver tương đương.

## 4. Kiểm tra hệ điều hành/Python trên Pi

Trong Terminal của Raspberry Pi (VNC hoặc SSH):

```bash
uname -m
getconf LONG_BIT
python3 --version
```

Bộ requirements nhắm tới **Pi 4, OS 64-bit (`aarch64`, `64`) và Python 3.10, 3.11 hoặc 3.12**. Python 3.11 là lựa chọn khởi đầu phù hợp. Python 3.13 trở lên và OS 32-bit không có bộ wheel MediaPipe 0.10.18 tương ứng trong hướng dẫn này.

Nếu bạn đang ở một môi trường ảo, có thể kiểm tra thêm `python --version` để biết phiên bản của môi trường đang kích hoạt. Một môi trường tạo bằng Python 3.13 vẫn dùng Python 3.13, dù sau đó bạn cài thêm Python 3.11.

**Nếu hiện tại là Python 3.13.5 hoặc bất kỳ phiên bản nào ngoài nhóm 3.10/3.11/3.12, làm theo mục 5.2B:** dùng `uv` cài Python 3.11 riêng và tạo `.venv311`. Không cần gỡ Python hiện tại hoặc đổi Python hệ thống. Nếu OS là `armv7l`/32-bit, cài thêm Python không giải quyết được việc thiếu wheel ARM64; cần môi trường OS 64-bit phù hợp trước khi dùng bộ này.

## 5. Chép và cài chương trình

Giải nén `RaspberryPi_Gesture_LED_DC_Full.zip`. Chép cả thư mục `rasp_gesture_led_dc` sang Pi, ví dụ:

```text
/home/pi/IoT/rasp_gesture_led_dc
```

Các lệnh bên dưới dùng đường dẫn đó. Nếu bạn chép vào thư mục khác, thay đường dẫn trong lệnh `cd` bằng vị trí thật. Dùng đầy đủ bộ file mới để `app.py`, `gesture_logic.py`, `gpio_outputs.py` và `templates/index.html` khớp nhau.

### 5.1. Cài gói hệ thống

```bash
sudo apt update
sudo apt install -y curl python3-venv python3-pip python3-dev build-essential v4l-utils libgl1 libglib2.0-0 libportaudio2
```

`build-essential` và `python3-dev` giúp build RPi.GPIO nếu pip dùng bản source. Nếu dùng Python 3.12 tự cài trong khi Python hệ thống là phiên bản khác, cần headers/dev của **đúng Python 3.12** từ cách cài Python đó.

### 5.2. Chọn một cách tạo môi trường Python

Chỉ chọn **A hoặc B**, rồi cùng tiếp tục mục **5.3**. Nếu Terminal đang kích hoạt môi trường cũ (có tiền tố như `(.venv)`), chạy `deactivate` trước khi chọn cách mới.

#### 5.2A. Python hiện tại là 3.10, 3.11 hoặc 3.12

Kiểm tra `python3 --version`. Nếu phiên bản phù hợp, tạo môi trường bằng Python đó:

```bash
cd ~/IoT/rasp_gesture_led_dc
python3 -m venv .venv
source .venv/bin/activate
python --version
```

Kết quả phải thuộc Python 3.10.x/3.11.x/3.12.x. Nếu `.venv` cũ đã tạo bằng phiên bản không phù hợp, không tái sử dụng môi trường đó; chọn cách **5.2B** để có một môi trường mới.

#### 5.2B. Python hiện tại không phù hợp, ví dụ Python 3.13.5

Cách này cài thêm **Python 3.11 riêng cho dự án** bằng công cụ `uv`. Các bước cần có kết nối Internet. Chạy trên Terminal của Pi, không cần dùng `sudo` cho lệnh cài `uv` hoặc tạo venv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
"$HOME/.local/bin/uv" python install 3.11
```

Tạo một môi trường mới tên `.venv311` trong thư mục chương trình:

```bash
cd ~/IoT/rasp_gesture_led_dc
"$HOME/.local/bin/uv" venv --python 3.11 --seed .venv311
source .venv311/bin/activate
python --version
```

**Kết quả phải hiện `Python 3.11.x`.** Tùy chọn `--seed` cài pip vào venv để dùng các lệnh `python -m pip` tiếp theo. Môi trường `.venv` cũ không bị xóa; dự án dùng `.venv311` mới. Không sao chép thư viện từ môi trường cũ sang môi trường mới.

Nếu `python --version` vẫn hiện 3.13.5, kiểm tra bạn đã chạy đúng lệnh `source .venv311/bin/activate` trong thư mục dự án. Có thể kiểm tra interpreter trực tiếp bằng:

```bash
which python
./.venv311/bin/python --version
```

Interpreter trực tiếp phải là Python 3.11.x; `which python` sau khi kích hoạt phải trỏ tới `.venv311/bin/python` của dự án.

### 5.3. Cài requirements và kiểm tra

Sau khi kích hoạt môi trường đã chọn ở A hoặc B:

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install --prefer-binary -r requirements.txt
```

Không thêm `--only-binary=:all:` cho toàn bộ requirements, vì RPi.GPIO có thể cần build từ source. Không cài thêm `opencv-python` hoặc `opencv-python-headless` vào venv này: `opencv-contrib-python` đã cung cấp `cv2`.

Kiểm tra import; các lệnh này không mở webcam hay chạy nhận diện:

```bash
python -c "import cv2, mediapipe, flask, RPi.GPIO as GPIO; print('Import OK'); print('MediaPipe:', mediapipe.__version__); print('RPi.GPIO:', GPIO.VERSION)"
python -m pip check
python download_model.py
```

Model đã kèm sẵn nên `download_model.py` chỉ kiểm tra SHA256, không cần mạng khi file đúng. Nếu file thiếu/hỏng:

```bash
python download_model.py --force
```

### 5.4. Mỗi lần mở Terminal mới

Nếu chọn **5.2A**, kích hoạt `.venv`:

```bash
cd ~/IoT/rasp_gesture_led_dc
source .venv/bin/activate
```

Nếu chọn **5.2B**, kích hoạt `.venv311`:

```bash
cd ~/IoT/rasp_gesture_led_dc
source .venv311/bin/activate
python --version
```

**Với trường hợp Python hệ thống 3.13.5 của bạn, dùng `.venv311` cho mọi lần test và chạy app.** Các lệnh `python ...` ở phần tiếp theo sẽ dùng Python của môi trường đang được kích hoạt.

## 6. Chọn đúng thiết bị webcam

```bash
lsusb
v4l2-ctl --list-devices
```

Tìm nhóm webcam như `USB Camera`, `UVC Camera`, hoặc **`USB Composite Device` / Jieli Technology**. Nhóm `bcm2835-codec`, `bcm2835-isp`, `rpi-hevc-dec` không phải webcam USB của bạn.

Ví dụ nhóm webcam có `/dev/video0` và `/dev/video1`, kiểm tra từng node:

```bash
v4l2-ctl -d /dev/video0 --all
v4l2-ctl -d /dev/video1 --all
```

Trong **Device Caps**, chọn node có **Video Capture**. Node chỉ có **Metadata Capture** không trả hình ảnh cho chương trình. Sau đó kiểm tra định dạng, ví dụ:

```bash
v4l2-ctl -d /dev/video0 --list-formats-ext
```

Chọn node có định dạng video như MJPG/YUYV và độ phân giải camera hỗ trợ. Số `/dev/videoN` có thể đổi sau khi cắm lại. Nếu không biết nhóm nào là webcam, rút camera → liệt kê → cắm lại → liệt kê, rồi kiểm tra nhóm mới xuất hiện.

## 7. Test từng phần trước khi chạy Flask

**Dừng `app.py` và các chương trình khác đang dùng cùng camera/GPIO trước mỗi test.** Chạy các test lần lượt, không mở nhiều bản cùng lúc.

### 7.1. Test camera

Thay `/dev/video0` bằng node Video Capture thật của bạn:

```bash
python test_camera.py --camera /dev/video0
```

Mong đợi tạo `camera_test.jpg` trong thư mục hiện tại. Mở ảnh bằng trình xem ảnh trong VNC. Muốn xem liên tục bằng cửa sổ trên desktop Pi:

```bash
python test_camera.py --camera /dev/video0 --preview
```

Nhấn `q` trong cửa sổ preview để thoát. Khi SSH không có desktop/display, dùng lệnh lưu ảnh, không dùng `--preview`.

### 7.2. Test LED riêng

```bash
python test_gpio.py --case led --seconds 5
```

Mong đợi LED ở BCM27 (chân vật lý 13) sáng 5 giây rồi tắt. Motor không quay. Log in mức GPIO và lệnh, nhưng phải quan sát LED thật.

### 7.3. Test motor riêng

```bash
python test_gpio.py --case motor --seconds 5 --duty 100
```

Mong đợi: quay thuận 5 giây → dừng 2 giây → quay ngược 5 giây → dừng. LED không sáng. ENA12 được chương trình bật bằng PWM, không cần đặt thêm biến `MOTOR_ENABLE_GPIO`.

### 7.4. Test cả LED/motor

```bash
python test_gpio.py --case all --seconds 3
```

Test LED rồi test hai chiều motor. Sau khi từng phần đã hoạt động, có thể kiểm tra đúng chuỗi lệnh của ứng dụng mà chưa mở camera/model:

```bash
python test_gpio.py --case gestures --seconds 3
```

Đây là **phát lệnh giả lập** xòe → trỏ → cái → nắm, không phải model nhận diện. LED phải ON ở ba giai đoạn đầu; motor phải tiếp tục quay thuận khi chuyển xòe → trỏ, rồi đảo chiều ở “cái”, cuối cùng cả hai tắt.

## 8. Chạy chương trình Flask

Sau khi test camera và GPIO thành công, với cách **5.2B** (Python 3.11 riêng):

```bash
cd ~/IoT/rasp_gesture_led_dc
source .venv311/bin/activate
CAMERA_INDEX=/dev/video0 python app.py
```

Nếu bạn chọn cách **5.2A**, thay dòng kích hoạt bằng `source .venv/bin/activate`. Luôn kiểm tra `python --version` thuộc 3.10/3.11/3.12 trước khi chạy.

Giữ Terminal mở. Trên trình duyệt Pi vào:

[http://127.0.0.1:5000](http://127.0.0.1:5000)

Muốn xem từ laptop/điện thoại cùng mạng, lấy IP Pi:

```bash
hostname -I
```

Ví dụ IP là `192.168.1.50`, mở [http://192.168.1.50:5000](http://192.168.1.50:5000). Thay IP ví dụ bằng IP thật của Pi. Laptop chỉ mở web; mọi xử lý camera và GPIO chạy trên Pi.

Web có ba component chính:

| Component | Element chính | Dữ liệu |
|---|---|---|
| Camera trực tiếp | `<img id="camera">` | Luồng MJPEG `/video_feed` |
| Kết quả nhận diện | `<input id="recognition-result" readonly>` | `data.result` từ `/api/state` |
| Lệnh LED/DC | `<input id="control-command" readonly>` | `data.outputs.command` từ `/api/state` |

JavaScript lấy trạng thái khoảng 350 ms sau mỗi lượt trả lời, cập nhật field bằng `.value`. `/api/state` có kết quả cử chỉ và lệnh đầu ra trong cùng một phản hồi JSON. Nhiều tab dùng chung một luồng camera/model, không mở thêm camera cho từng tab. Debug/reloader bị tắt để tránh nhân đôi tiến trình GPIO.

Nhấn **Ctrl+C** để dừng. Không chạy `flask run --debug` cho ứng dụng này.

## 9. Thử bốn cử chỉ trên web

Đảm bảo đủ sáng, thấy rõ toàn bộ một bàn tay và các ngón, giữ từng cử chỉ khoảng 1–2 giây.

| Thứ tự | Cách thực hiện | Field cử chỉ mong đợi | Field lệnh mong đợi |
|---:|---|---|---|
| 1 | Xòe cả năm ngón, lòng bàn tay hướng camera | Xòe bàn tay | `LED ON \| DC quay thuận` |
| 2 | Chỉ duỗi ngón trỏ hướng lên, các ngón khác gập | Ngón trỏ | `LED ON \| DC quay thuận` |
| 3 | Nắm bốn ngón, ngón cái hướng lên | Ngón cái | `LED ON \| DC quay ngược` |
| 4 | Ngón cái hướng xuống | Ngón cái | `LED ON \| DC quay ngược` |
| 5 | Nắm tay | Nắm tay | `LED OFF \| DC tắt` |
| 6 | Khi LED OFF, đưa ngón trỏ lên | Ngón trỏ | `LED OFF \| DC quay thuận` |
| 7 | Khi LED OFF, đưa ngón cái lên/xuống | Ngón cái | `LED OFF \| DC quay ngược` |

Chuyển cử chỉ trong khoảng dưới thời gian timeout nếu muốn giữ trạng thái LED liên tục. Rút tay hoàn toàn: field hiện “Chưa thấy bàn tay”; sau khoảng 2 giây đầu ra tắt. Khi chỉ có tư thế ngoài nhóm như chữ V, model có thể báo “Chưa xác định được cử chỉ”; nếu model nhận nhầm thành nhóm hợp lệ, vẫn có thể phát lệnh, cần kiểm tra thực tế.

## 10. Tùy chỉnh

Các chân GPIO cố định ở đầu `gpio_outputs.py`: LED27, IN1=23, IN2=24, ENA12. Bảng dưới là các biến môi trường tùy chọn; không cần dùng cho lần chạy đầu.

| Biến | Mặc định | Ý nghĩa |
|---|---:|---|
| `CAMERA_INDEX` | `/dev/video0` | Node camera hoặc chỉ số camera |
| `FRAME_WIDTH`, `FRAME_HEIGHT` | 640, 480 | Kích thước ảnh xử lý |
| `TARGET_FPS` | 10 | Giới hạn mong muốn; tốc độ thực tế có thể thấp hơn |
| `SCORE_THRESHOLD` | 0.65 | Điểm model tối thiểu, 0–1 |
| `HOLD_SECONDS` | 0.4 | Thời gian cử chỉ phải ổn định |
| `MOTOR_DUTY` | 100 | Duty ENA, 1–100%; không có feedback tốc độ |
| `REVERSE_PAUSE` | 0.3 | Thời gian ngắt trước đảo chiều, 0.05–3 giây |
| `NO_GESTURE_TIMEOUT` | 2 | Thời gian không có cử chỉ hợp lệ thì tắt; 0 giữ lệnh đến cử chỉ mới |
| `FRAME_TIMEOUT` | 3 | Watchdog khi camera/model không có kết quả mới |
| `MIRROR` | 1 | Lật ngang ảnh; 0 để tắt |
| `HOST`, `PORT` | 0.0.0.0, 5000 | Địa chỉ và cổng Flask |

Ví dụ giảm độ phân giải và FPS mong muốn:

```bash
CAMERA_INDEX=/dev/video0 FRAME_WIDTH=480 FRAME_HEIGHT=360 TARGET_FPS=8 python app.py
```

Đổi chiều có tải nặng, tăng khoảng ngắt:

```bash
CAMERA_INDEX=/dev/video0 REVERSE_PAUSE=1 python app.py
```

Muốn rút tay mà giữ lệnh cho đến cử chỉ tiếp theo:

```bash
CAMERA_INDEX=/dev/video0 NO_GESTURE_TIMEOUT=0 python app.py
```

Ngay cả khi `NO_GESTURE_TIMEOUT=0`, lỗi camera, timeout luồng xử lý, `Ctrl+C`/SIGTERM vẫn tắt đầu ra. Motor có thể còn quay trớn sau khi ngắt ENA; thời gian chờ đảo chiều phải phù hợp motor/tải thật.

## 11. Khi nhận diện được nhưng LED/motor chưa hoạt động

### LED không sáng

1. Dừng Flask, chạy test LED riêng.
2. Kiểm tra **BCM27 = chân vật lý 13**, điện trở, cực LED và GND.
3. Nếu có đồng hồ, đo chân 13 so với chân 6 trong lúc test: ON gần 3.3V, OFF gần 0V.
4. Điện áp đổi đúng nhưng LED tối: kiểm tra LED và dây. Điện áp không đổi: kiểm tra đúng header/chân, chương trình khác chiếm chân hoặc lỗi RPi.GPIO.

### Motor không quay

1. Dừng Flask, chạy test motor riêng với `--duty 100`.
2. Kiểm tra nguồn motor, nguồn logic driver và **GND chung** với Pi.
3. Kiểm tra motor nối OUT1/OUT2, GPIO23/24 vào IN1/IN2, **ENA12 ở chân vật lý 32**.
4. Với L298N, tháo jumper ENA khi ENA đã nối Pi; ENA phải được bật mới chạy motor.
5. Trong test, IN1/IN2 phải lần lượt là 1/0 và 0/1; ENA duty 100%. Nếu có đồng hồ: IN1/IN2/ENA khi HIGH gần 3.3V so với GND. Với PWM dưới 100%, số đo ENA có thể là giá trị trung bình.
6. Nếu các đầu vào đổi đúng mà OUT1/OUT2 không cấp điện, kiểm tra enable, nguồn logic/motor và driver. Nếu đầu ra có điện áp thích hợp mà motor đứng, kiểm tra motor/dây/tải. L298N có sụt áp trên cầu H, nên phải bảo đảm điện áp tới motor đủ.

### Lỗi quyền GPIO/video

```bash
groups
ls -l /dev/gpiomem
ls -l /dev/video0
```

Nếu tài khoản chưa có nhóm cần thiết:

```bash
sudo usermod -aG gpio,video "$USER"
```

Đăng xuất/đăng nhập lại hoặc reboot để cập nhật nhóm. Không dùng `sudo python app.py` với Python khác venv rồi kết luận thiếu thư viện.

### Pi báo sụt áp hoặc webcam mất kết nối

```bash
sudo dmesg | tail -n 60
vcgencmd get_throttled
```

Nếu thấy `Undervoltage detected!`, kiểm tra nguồn/cáp Pi 4 (nguồn Pi 4 chính thức 5.1V/3A hoặc nguồn đáp ứng tương đương) và nguồn riêng cho motor. Sụt áp có thể làm camera/USB hoặc xử lý hoạt động thiếu ổn định. Dòng “LED ON”/“MOTOR FORWARD” chỉ là lệnh, không xác nhận phần cứng hoạt động.

### Lỗi MediaPipe/API

Tham số đúng trong `app.py` là **`canned_gesture_classifier_options`**, không thêm chữ `s` vào `gesture`. Bộ mới đã dùng tên đúng. Kiểm tra đang chạy đúng thư mục mới và đúng venv:

```bash
pwd
which python
python -c "import mediapipe as mp; print(mp.__version__)"
```

### Lỗi cài đặt

- `No matching distribution found for mediapipe==0.10.18`: kiểm tra lại OS 64-bit và `python --version` trong môi trường đang dùng. Nếu là Python 3.13+ hoặc ngoài nhóm 3.10/3.11/3.12, làm mục **5.2B**, kích hoạt `.venv311` rồi cài lại requirements trong môi trường mới.
- Lỗi build RPi.GPIO: kiểm tra compiler và headers đúng phiên bản Python của venv; không chuyển sang gpiozero trong bộ này.
- `Cannot determine SOC peripheral base address`: gửi đầy đủ traceback cùng model Pi, OS, Python và phiên bản RPi.GPIO; bộ này nhắm tới Pi 4.
- Thiếu `cv2`/`flask` khi chạy: kích hoạt đúng `.venv` (5.2A) hoặc `.venv311` (5.2B), cài lại requirements trong chính môi trường đó.
- Cổng 5000 đang dùng: dừng bản app cũ hoặc chạy `PORT=5001 CAMERA_INDEX=/dev/video0 python app.py` rồi mở cổng mới.

## 12. Nguồn chính thức

- [MediaPipe Gesture Recognizer Python](https://ai.google.dev/edge/mediapipe/solutions/vision/gesture_recognizer/python)
- [GestureRecognizerOptions và các nhãn có sẵn](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/GestureRecognizerOptions)
- [MediaPipe 0.10.18 trên PyPI](https://pypi.org/project/mediapipe/0.10.18/)
- [uv: cài đặt công cụ](https://docs.astral.sh/uv/getting-started/installation/)
- [uv: cài thêm phiên bản Python](https://docs.astral.sh/uv/guides/install-python/)
- [uv: môi trường ảo](https://docs.astral.sh/uv/pip/environments/)
- [RPi.GPIO: BCM, setup, output, cleanup](https://sourceforge.net/p/raspberry-gpio-python/wiki/BasicUsage/)
- [RPi.GPIO: PWM](https://sourceforge.net/p/raspberry-gpio-python/wiki/PWM/)
- [Raspberry Pi hardware và GPIO](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html)
- [Datasheet L298: nguồn và enable cầu H](https://www.st.com/resource/en/datasheet/l298.pdf)

Khả năng nhận diện và FPS cần thử trên Pi/webcam của bạn. Xem `VALIDATION.md` để biết phần nào đã được kiểm tra bằng phần mềm và phần nào cần xác nhận trên phần cứng.
