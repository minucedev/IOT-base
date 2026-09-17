"""Dem nguoi qua camera va hien so nguoi tren LED (toi da 5 LED).

Dua tren y tuong cua repo tham khao:
    https://github.com/WinG-282k4/IOT_preople_detect
(repo goc dung SSD-MobileNet-V2 + bam vet + dem qua vach, chay tren Pi 4B).
File nay don gian hoa yeu cau: chi CAN dem so nguoi dang xuat hien trong khung
hinh va hien thi len 5 LED gan GPIO cua Raspberry Pi - khong dung model rieng,
khong can tai file model, chi dung HOGDescriptor co san trong OpenCV nen chay
duoc ngay sau khi "pip install opencv-python".

Neu can do chinh xac cao hon (giong repo goc), thay ham detect_people() bang
mot detector MobileNet-SSD/TFLite roi giu nguyen phan dieu khien LED ben duoi.

===========================================================================
1) CAI DAT PHAN MEM
===========================================================================
Tren Raspberry Pi (Raspberry Pi OS):
    sudo apt update
    sudo apt install -y python3-opencv python3-rpi.gpio
    # hoac neu dung pip/venv:
    pip install opencv-python numpy RPi.GPIO

Tren may khong phai Pi (Windows/macOS/Linux thuong) de TEST truoc camera va
thuat toan dem nguoi (khong co GPIO that):
    pip install opencv-python numpy
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

Camera: dung webcam USB thuong hoac Pi Camera Module qua adapter USB/CSI-to-
USB; script mo camera bang cv2.VideoCapture(CAMERA_INDEX) nen camera nao duoc
Linux nhan la /dev/video0 (index 0) deu dung duoc.

===========================================================================
3) CHAY
===========================================================================
    python3 people_count_led.py

Cua so "People Count" se hien camera voi khung xanh quanh moi nguoi phat
hien duoc va so nguoi dem duoc o goc tren trai. Nhan 'q' trong cua so do de
thoat (chuong trinh se tu tat het LED va don GPIO truoc khi ket thuc).
"""

import sys

import cv2

# --- Cau hinh ---
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
MAX_LEDS = 5
LED_PINS = [17, 27, 22, 5, 6]  # BCM numbering, dung dung MAX_LEDS phan tu
DETECT_EVERY_N_FRAMES = 3  # bo bot khung hinh de do tai CPU tren Pi
HOG_SCALE = 1.05
HOG_WIN_STRIDE = (8, 8)
NMS_SCORE_THRESHOLD = 0.0
NMS_IOU_THRESHOLD = 0.65

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
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return hog


def detect_people(hog, frame):
    """Tra ve danh sach hop (x, y, w, h) quanh nguoi phat hien duoc trong frame."""
    boxes, weights = hog.detectMultiScale(
        frame, winStride=HOG_WIN_STRIDE, padding=(8, 8), scale=HOG_SCALE
    )
    if len(boxes) == 0:
        return []

    scores = [float(w) for w in weights]
    indices = cv2.dnn.NMSBoxes(
        list(boxes), scores, NMS_SCORE_THRESHOLD, NMS_IOU_THRESHOLD
    )
    if len(indices) == 0:
        return []
    indices = indices.flatten()
    return [tuple(boxes[i]) for i in indices]


def main():
    setup_leds()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    if not cap.isOpened():
        print(f"LOI: khong mo duoc camera index {CAMERA_INDEX}")
        GPIO.cleanup()
        sys.exit(1)

    hog = build_detector()
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
                last_boxes = detect_people(hog, frame)
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
