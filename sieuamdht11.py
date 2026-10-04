import time
import board
import adafruit_dht

from gpiozero import LED, DistanceSensor

# =========================
# CẤU HÌNH GPIO
# =========================

DHT_PIN = board.D4

TRIG_PIN = 24
ECHO_PIN = 23

LED_PIN = 18

# =========================
# KHỞI TẠO
# =========================

dht = adafruit_dht.DHT11(DHT_PIN)

led = LED(LED_PIN)

sensor = DistanceSensor(
    echo=ECHO_PIN,
    trigger=TRIG_PIN,
    max_distance=4
)

# =========================
# CHƯƠNG TRÌNH
# =========================

try:
    while True:

        # Đọc nhiệt độ
        try:
            temperature = dht.temperature
            humidity = dht.humidity

        except RuntimeError as e:
            print("Lỗi đọc DHT11:", e)
            time.sleep(2)
            continue

        # Đọc khoảng cách
        distance_cm = sensor.distance * 100

        print(
            f"Nhiệt độ: {temperature:.1f} °C | "
            f"Độ ẩm: {humidity:.1f} % | "
            f"Khoảng cách: {distance_cm:.1f} cm"
        )

        # =========================
        # ĐIỀU KIỆN BẬT ĐÈN
        # =========================

        if distance_cm < 30 and temperature >= 30:
            led.on()
            print(">>> ĐÈN BẬT")

        else:
            led.off()
            print(">>> ĐÈN TẮT")

        time.sleep(1)

except KeyboardInterrupt:
    print("\nĐã dừng chương trình")

finally:
    led.off()
    dht.exit()

