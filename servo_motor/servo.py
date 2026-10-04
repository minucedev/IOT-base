from gpiozero import DistanceSensor, AngularServo
from gpiozero.pins.lgpio import LGPIOFactory
from time import sleep

# =========================
# GPIO SETUP
# =========================

factory = LGPIOFactory()

sensor = DistanceSensor(
    echo=23,
    trigger=24,
    max_distance=4,
    pin_factory=factory
)

servo = AngularServo(
    18,
    min_angle=0,
    max_angle=180,
    min_pulse_width=0.5/1000,
    max_pulse_width=2.5/1000,
    frame_width=20/1000,
    pin_factory=factory
)


# =========================
# MAIN
# =========================

try:
    while True:

        # Đọc khoảng cách
        distance = sensor.distance * 100

        print(f"Khoảng cách: {distance:.1f} cm")

        # Vật cản dưới 30 cm
        if distance < 30:

            print("Vật cản < 30 cm → Servo 180°")

            servo.angle = 180
            sleep(0.5)

            print("Servo → 0°")

            servo.angle = 0
            sleep(0.5)

        # Vật cản từ 30 cm trở lên
        else:

            print("Vật cản >= 30 cm → Servo 90°")

            servo.angle = 90
            sleep(0.5)

            print("Servo → 0°")

            servo.angle = 0
            sleep(0.5)

        sleep(0.2)


except KeyboardInterrupt:
    print("\nDừng chương trình")


finally:
    servo.close()
    sensor.close()

