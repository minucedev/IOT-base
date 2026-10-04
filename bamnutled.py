from gpiozero import Button, LED
from signal import pause
import time

BUTTON_PIN = 17
LED_PIN = 18

button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.05)
led = LED(LED_PIN)

click_count = 0
last_click_time = 0


def button_pressed():
    global click_count, last_click_time

    current_time = time.monotonic()

    # LED đang tắt -> bấm 1 lần là bật
    if not led.is_lit:
        led.on()
        click_count = 0
        print("LED: BAT")
        return

    # LED đang bật -> bắt đầu đếm click
    if click_count == 0:
        click_count = 1
        last_click_time = current_time
        print("Click 1 - cho click thu 2...")

    elif click_count == 1:
        if current_time - last_click_time <= 0.5:
            led.off()
            click_count = 0
            print("Click 2 - LED: TAT")
        else:
            # Click đầu tiên đã quá 0.5 giây
            click_count = 1
            last_click_time = current_time


button.when_pressed = button_pressed

print("Chuong trinh dang chay...")

try:
    while True:
        # Nếu click đầu tiên quá 0.5 giây
        # mà không có click thứ 2 thì reset
        if click_count == 1:
            if time.monotonic() - last_click_time > 0.5:
                click_count = 0
                print("Het thoi gian cho click thu 2")

        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nDa dung chuong trinh.")

finally:
    led.off()
    button.close()
    led.close()

