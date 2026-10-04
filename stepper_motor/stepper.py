import time
import board
import adafruit_dht
from digitalio import DigitalInOut, Direction
from adafruit_motor import stepper

# GPIO
IN1 = board.D17
IN2 = board.D18
IN3 = board.D27
IN4 = board.D22
DHT_PIN = board.D4

# Motor setup
coil1 = DigitalInOut(IN1)
coil2 = DigitalInOut(IN2)
coil3 = DigitalInOut(IN3)
coil4 = DigitalInOut(IN4)

for coil in (coil1, coil2, coil3, coil4):
    coil.direction = Direction.OUTPUT

# 28BYJ-48: cuộn A = IN1+IN3, cuộn B = IN2+IN4 -> truyền (coil1, coil3, coil2, coil4)
motor = stepper.StepperMotor(coil1, coil3, coil2, coil4, microsteps=None)

# DHT11
dht = adafruit_dht.DHT11(DHT_PIN)

# 28BYJ-48: half-step = 4096 bước/vòng
STEPS_PER_REV = 4096
STEPS_180 = STEPS_PER_REV // 2
STEPS_90 = STEPS_PER_REV // 4
STEP_DELAY = 0.002  # 0.001 làm motor trượt bước, không quay


def rotate(steps, direction):
    for _ in range(steps):
        motor.onestep(direction=direction, style=stepper.INTERLEAVE)
        time.sleep(STEP_DELAY)
    motor.release()


try:
    while True:
        try:
            temperature = dht.temperature
        except RuntimeError:
            print("Lỗi đọc DHT11")
            time.sleep(2)
            continue

        if temperature is None:
            time.sleep(2)
            continue

        print(f"Nhiệt độ: {temperature:.1f}°C")

        if temperature > 30:
            print("→ Quay thuận 180°")
            rotate(STEPS_180, stepper.BACKWARD)
        else:
            print("→ Quay ngược 90°")
            rotate(STEPS_90, stepper.FORWARD)

        time.sleep(2)

except KeyboardInterrupt:
    print("\nĐang dừng hệ thống...")

finally:
    motor.release()
    coil1.deinit()
    coil2.deinit()
    coil3.deinit()
    coil4.deinit()
    dht.exit()

