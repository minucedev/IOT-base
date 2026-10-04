from gpiozero import Motor, DigitalInputDevice, Button
from time import sleep


# =========================
# GPIO CONFIG
# =========================

SENSOR_PIN = 17
BUTTON_PIN = 27

MOTOR_EN = 18
MOTOR_IN1 = 23
MOTOR_IN2 = 24


# =========================
# SPEED
# =========================

FAST_SPEED = 0.8
SLOW_SPEED = 0.5


# =========================
# DEVICES
# =========================

sensor = DigitalInputDevice(SENSOR_PIN)

button = Button(
    BUTTON_PIN,
    pull_up=False
)

motor = Motor(
    forward=MOTOR_IN1,
    backward=MOTOR_IN2,
    enable=MOTOR_EN,
    pwm=True
)


# =========================
# STATE
# =========================

running = False

# Hướng hiện tại của motor
current_direction = None


# =========================
# BUTTON: ON / OFF
# =========================

def toggle_motor():
    global running

    running = not running

    if not running:
        motor.stop()
        print("Motor: OFF")
    else:
        print("Motor: ON")


button.when_pressed = toggle_motor


# =========================
# MAIN LOOP
# =========================

try:
    while True:

        if not running:
            motor.stop()
            current_direction = None
            sleep(0.1)
            continue

        # True  = line đen
        # False = line trắng
        line_black = sensor.is_active

        if line_black:
            new_direction = "FORWARD"
            speed = FAST_SPEED
            line = "BLACK"
        else:
            new_direction = "BACKWARD"
            speed = SLOW_SPEED
            line = "WHITE"

        # =========================
        # ĐẢO CHIỀU
        # =========================

        if (
            current_direction is not None
            and new_direction != current_direction
        ):
            # Dừng trước khi đảo chiều
            motor.stop()

            print("Direction changing... STOP 0.2s")
            sleep(0.2)

        # =========================
        # CHẠY MOTOR
        # =========================

        if new_direction == "FORWARD":
            motor.forward(speed)
        else:
            motor.backward(speed)

        current_direction = new_direction

        print(
            f"Direction: {new_direction:8} | "
            f"Line: {line:5} | "
            f"Speed: {speed:.2f}"
        )

        sleep(0.1)


except KeyboardInterrupt:
    motor.stop()
    print("\nMotor stopped.")


finally:
    motor.stop()

