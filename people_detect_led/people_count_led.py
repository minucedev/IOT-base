"""Dem nguoi qua camera va hien so nguoi tren LED (toi da 5 LED).

Dua tren y tuong cua repo tham khao:
    https://github.com/WinG-282k4/IOT_preople_detect
(repo goc dung SSD-MobileNet-V2 + bam vet + dem qua vach, chay tren Pi 4B).
File nay don gian hoa yeu cau: chi CAN dem so nguoi dang xuat hien trong khung
hinh va hien thi len 5 LED gan GPIO cua Raspberry Pi. Model dung dung y model
repo goc de xuat - MobileNet-SSD (ban Caffe, 21 lop VOC, chi loc lay lop
"person") - chay qua cv2.dnn, khong can GPU, nhe du de chay tren Pi.

File model (da tai san trong thu muc models/ canh script nay, khong can tai
them gi):
    models/MobileNetSSD_deploy.prototxt    (kien truc mang, ~29 KB)
    models/MobileNetSSD_deploy.caffemodel  (trong so da huan luyen, ~23 MB)
(nguon: https://github.com/djmv/MobilNet_SSD_opencv - ban Caffe pho bien nhat
de dung voi cv2.dnn.readNetFromCaffe, MobileNet-SSD huan luyen tren VOC2007+
2012, lop "person" la lop thu 15 trong 21 lop.)

QUAN TRONG ve phien ban OpenCV: ban OpenCV 5.0 (moi nhat tren PyPI) da BO
readNetFromCaffe (va ca CascadeClassifier/HOGDescriptor) khoi Python binding,
script se bao loi "module 'cv2.dnn' has no attribute 'readNetFromCaffe'" neu
cai ban nay. Raspberry Pi OS (apt) hien van cai OpenCV 4.x nen khong bi anh
huong; con neu cai bang pip (kem ca tren may test) phai ghim phien ban < 5
nhu huong dan ben duoi. Da test truc tiep voi opencv-python==4.10.0.84.

===========================================================================
1) CAI DAT PHAN MEM
===========================================================================
Tren Raspberry Pi (Raspberry Pi OS, khuyen dung vi apt cai san OpenCV 4.x):
    sudo apt update
    sudo apt install -y python3-opencv python3-rpi.gpio

Neu dung pip/venv (tren Pi hoac may test), PHAI ghim OpenCV ban < 5 vi ly do
neu tren:
    pip install "opencv-python<5" numpy RPi.GPIO

Tren may khong phai Pi (Windows/macOS/Linux thuong) de TEST truoc camera va
thuat toan dem nguoi (khong co GPIO that):
    pip install "opencv-python<5" numpy
    python people_count_led.py
    -> Script tu dong phat hien khong co module RPi.GPIO va chuyen sang
       "Mock GPIO": in trang thai bat/tat LED ra console thay vi dieu khien
       chan that, de ban van chay va debug duoc phan camera.

===========================================================================
2) NOI DAY 5 LED VAO RASPBERRY PI (dung khi chay that tren Pi)
===========================================================================
Moi LED can 1 dien tro han dong 220-330 ohm noi tiep de bao ve GPIO.
Dau anode (chan dai) cua LED noi vao chan GPIO, dau cathode (chan ngan) noi
qua dien tro xuong GND.

    LED 1 (nguoi thu 1) -> GPIO17  (chan vat ly 11)
    LED 2 (nguoi thu 2) -> GPIO27  (chan vat ly 13)
    LED 3 (nguoi thu 3) -> GPIO22  (chan vat ly 15)
    LED 4 (nguoi thu 4) -> GPIO5   (chan vat ly 29)
    LED 5 (nguoi thu 5) -> GPIO6   (chan vat ly 31)
    GND cua breadboard  -> chan GND bat ky cua Pi (vi du chan vat ly 6, 9, 14...)

So do 1 LED:
    GPIO_pin ---> (anode) LED (cathode) ---> dien tro 220-330 ohm ---> GND

Neu chi co it hon 5 LED, cu cam theo thu tu tu LED 1 tro di; cac LED con lai
trong LED_PINS se don gian khong duoc dung toi.

Camera: co 2 cach, chinh bang bien CAMERA_SOURCE ben duoi.

  Cach A - Camera gan truc tiep vao may chay script nay (USB webcam hoac
  Pi Camera Module qua adapter USB/CSI-to-USB):
      CAMERA_SOURCE = 0   # hoac 1, 2... neu may co nhieu camera

  Cach B - Camera nam tren mot may khac (vi du laptop co webcam, con
  Raspberry Pi chi co LED/GPIO khong gan camera) - giong y het cach lay
  IP trong face_detection/laptop_cam_server.py:
      1. Tren may CO CAMERA (laptop), chay:
             python laptop_cam_server.py
         Console se in ra dong dang:
             Stream : http://<LAPTOP_IP>:5000/video_feed
         <LAPTOP_IP> chinh la dia chi IP LAN cua may do (vi du 192.168.1.10),
         no tu dong lay bang ham get_lan_ip(), khong phai tu go tay.
      2. Tren Raspberry Pi (may chay people_count_led.py, dieu khien LED),
         sua bien CAMERA_SOURCE ben duoi thanh URL vua thay, vi du:
             CAMERA_SOURCE = "http://192.168.1.10:5000/video_feed"
      3. Dam bao Pi va laptop cung mot mang LAN/Wi-Fi thi moi ket noi duoc.

===========================================================================
3) CHAY
===========================================================================
    python3 people_count_led.py

Cua so "People Count" se hien camera voi khung xanh quanh moi nguoi phat
hien duoc va so nguoi dem duoc o goc tren trai. Nhan 'q' trong cua so do de
thoat (chuong trinh se tu tat het LED va don GPIO truoc khi ket thuc).
"""

import os
import sys

import cv2

# --- Cau hinh ---
# So nguyen (0, 1, 2...) = camera gan truc tiep vao may nay.
# Chuoi URL = doc stream MJPEG tu may khac, vi du camera tren laptop:
#   CAMERA_SOURCE = "http://192.168.1.10:5000/video_feed"
# (chay laptop_cam_server.py tren laptop truoc, lay IP no in ra - xem phan
# 2 "NOI DAY..." o tren, muc Camera - Cach B)
CAMERA_SOURCE = "http://10.70.66.91:5000/video_feed"
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
MAX_LEDS = 5
LED_PINS = [17, 27, 22, 5, 6]  # BCM numbering, dung dung MAX_LEDS phan tu
DETECT_EVERY_N_FRAMES = 3  # bo bot khung hinh de do tai CPU tren Pi

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models")
PROTOTXT_PATH = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.prototxt")
CAFFEMODEL_PATH = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.caffemodel")
DNN_INPUT_SIZE = (300, 300)  # kich thuoc dau vao co dinh cua MobileNet-SSD
DNN_SCALE_FACTOR = 0.007843  # = 1/127.5, chuan hoa pixel ve khoang [-1, 1]
DNN_MEAN = 127.5
PERSON_CLASS_ID = 15  # lop "person" trong 21 lop VOC ma model nay dung
CONFIDENCE_THRESHOLD = 0.5  # bo qua ket qua co do tin cay thap hon

assert len(LED_PINS) == MAX_LEDS, "LED_PINS phai co dung MAX_LEDS chan GPIO"


class MockGPIO:
    """Gia lap RPi.GPIO de test tren may khong co chan GPIO that (vi du laptop)."""

    BCM = "BCM"
    OUT = "OUT"
    HIGH = 1
    LOW = 0

    def setmode(self, mode):
        print(f"[MOCK GPIO] setmode({mode})")

    def setwarnings(self, flag):
        pass

    def setup(self, pin, mode):
        print(f"[MOCK GPIO] setup chan {pin} lam OUTPUT")

    def output(self, pin, value):
        print(f"[MOCK GPIO] chan {pin} -> {'BAT' if value else 'TAT'}")

    def cleanup(self):
        print("[MOCK GPIO] cleanup")


try:
    import RPi.GPIO as GPIO

    USING_REAL_GPIO = True
except (ImportError, RuntimeError):
    GPIO = MockGPIO()
    USING_REAL_GPIO = False
    print("Khong tim thay RPi.GPIO (khong chay tren Raspberry Pi?) -> dung Mock GPIO,"
          " trang thai LED se duoc in ra console.")


def setup_leds():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in LED_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)


def update_leds(people_count):
    """Sang dan tung LED theo so nguoi dem duoc, toi da MAX_LEDS LED."""
    leds_on = min(people_count, MAX_LEDS)
    for i, pin in enumerate(LED_PINS):
        GPIO.output(pin, GPIO.HIGH if i < leds_on else GPIO.LOW)


def build_detector():
    if not hasattr(cv2.dnn, "readNetFromCaffe"):
        print(
            "LOI: cv2.dnn.readNetFromCaffe khong ton tai - ban dang cai OpenCV"
            " 5.x, ban nay da bo trinh doc model Caffe. Chay:"
            " pip install \"opencv-python<5\""
            " (xem phan 1 CAI DAT PHAN MEM o dau file)."
        )
        sys.exit(1)
    if not os.path.isfile(PROTOTXT_PATH) or not os.path.isfile(CAFFEMODEL_PATH):
        print(f"LOI: khong tim thay model trong {MODEL_DIR}")
        sys.exit(1)
    return cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, CAFFEMODEL_PATH)


def detect_people(net, frame):
    """Tra ve danh sach hop (x, y, w, h) quanh nguoi phat hien duoc trong frame."""
    h, w = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.resize(frame, DNN_INPUT_SIZE),
        DNN_SCALE_FACTOR,
        DNN_INPUT_SIZE,
        DNN_MEAN,
    )
    net.setInput(blob)
    detections = net.forward()

    boxes = []
    for i in range(detections.shape[2]):
        confidence = float(detections[0, 0, i, 2])
        class_id = int(detections[0, 0, i, 1])
        if confidence < CONFIDENCE_THRESHOLD or class_id != PERSON_CLASS_ID:
            continue

        box = detections[0, 0, i, 3:7] * [w, h, w, h]
        x1, y1, x2, y2 = box.astype(int)
        x1, y1 = max(x1, 0), max(y1, 0)
        x2, y2 = min(x2, w - 1), min(y2, h - 1)
        boxes.append((x1, y1, x2 - x1, y2 - y1))
    return boxes


def main():
    setup_leds()

    cap = cv2.VideoCapture(CAMERA_SOURCE)
    if isinstance(CAMERA_SOURCE, int):
        # Tren Windows, CAP_DSHOW mo camera local nhanh va on dinh hon;
        # khong ap dung khi CAMERA_SOURCE la URL stream tu may khac.
        try:
            cap_dshow = cv2.VideoCapture(CAMERA_SOURCE, cv2.CAP_DSHOW)
            if cap_dshow.isOpened():
                cap.release()
                cap = cap_dshow
            else:
                cap_dshow.release()
        except Exception:
            pass
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    if not cap.isOpened():
        print(f"LOI: khong mo duoc camera (CAMERA_SOURCE = {CAMERA_SOURCE!r})")
        GPIO.cleanup()
        sys.exit(1)

    net = build_detector()
    frame_idx = 0
    last_boxes = []

    print("Dang chay... nhan 'q' trong cua so camera de thoat.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Khong doc duoc frame tu camera.")
                break

            if frame_idx % DETECT_EVERY_N_FRAMES == 0:
                last_boxes = detect_people(net, frame)
            frame_idx += 1

            people_count = len(last_boxes)
            update_leds(people_count)

            for (x, y, w, h) in last_boxes:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            leds_on = min(people_count, MAX_LEDS)
            cv2.putText(
                frame,
                f"So nguoi: {people_count}  (LED sang: {leds_on}/{MAX_LEDS})",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
                2,
            )

            cv2.imshow("People Count", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        for pin in LED_PINS:
            GPIO.output(pin, GPIO.LOW)
        GPIO.cleanup()


if __name__ == "__main__":
    main()
