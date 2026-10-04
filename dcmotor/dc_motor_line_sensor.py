from gpiozero import Motor, DigitalInputDevice, Button
from time import sleep

SENSOR_PIN = 17
BUTTON_PIN = 27

MOTOR_EN = 18
MOTOR_IN1 = 23
MOTOR_IN2 = 24

FAST_SPEED = 0.8
SLOW_SPEED = 0.3

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

forward = True

def reverse_motor():
    global forward

    motor.stop()
    sleep(0.2)
    
    forward = not forward

button.when_pressed = reverse_motor

try:
    while True:

        # sensor state
        line  = sensor.is_active

        # speed
        speed = FAST_SPEED if line else SLOW_SPEED

        # direction
        direction = "FORWARD" if forward else "BACKWARD"

        if forward:
            motor.forward(speed)
        else:
            motor.backward(speed)

        print(
            f"Direction: {direction:<8} | "
            f"Line: {'YES' if line else 'NO ':<3} | "
            f"Speed: {speed:.2f}"
        )


        sleep(0.1)

except KeyboardInterrupt:
    motor.stop()

