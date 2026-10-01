"""
Test phần cứng cho hệ thống nhận diện biển số: servo, đèn LED, nút nhấn (gpiozero).
Dùng chung số chân với main_rasp.py, sửa ở đây thì sửa cả bên đó.

Chạy:
    python3 test_hardware.py            # Test lần lượt servo -> LED -> nút
    python3 test_hardware.py servo      # Chỉ test servo
    python3 test_hardware.py led        # Chỉ test LED
    python3 test_hardware.py button     # Chỉ test nút
"""

import sys
import time

from gpiozero import AngularServo, Button, LED

SERVO_PIN = 12               # GPIO12 = chân vật lý 32
LED_PIN = 16                 # GPIO16 = chân vật lý 36
BUTTON_PIN = 20              # GPIO20 = chân vật lý 38, nối xuống GND

BUTTON_PRESSES = 3           # Số lần nhấn cần đủ để đạt
BUTTON_TIMEOUT = 15.0        # Thời gian chờ nhấn nút (giây)


def test_servo():
    print(f"\n[SERVO] GPIO {SERVO_PIN}: quay 0 -> 90 -> 180 -> 0")
    servo = AngularServo(
        SERVO_PIN, initial_angle=None, min_angle=0, max_angle=180,
        min_pulse_width=0.0005, max_pulse_width=0.0025,
    )
    try:
        for angle in (0, 90, 180, 0):
            print(f"  Góc {angle}°")
            servo.angle = angle
            time.sleep(1.0)
        servo.detach()
    finally:
        servo.close()
    return ask("Servo có quay đủ 0 -> 90 -> 180 -> 0 không?")


def test_led():
    print(f"\n[LED] GPIO {LED_PIN}: nháy 3 lần rồi sáng 2 giây")
    led = LED(LED_PIN)
    try:
        for _ in range(3):
            led.on()
            time.sleep(0.3)
            led.off()
            time.sleep(0.3)
        led.on()
        time.sleep(2.0)
        led.off()
    finally:
        led.close()
    return ask("Đèn LED có nháy và sáng không?")


def test_button():
    print(f"\n[NÚT] GPIO {BUTTON_PIN}: nhấn nút {BUTTON_PRESSES} lần trong {BUTTON_TIMEOUT:.0f} giây")
    button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.05)
    try:
        if button.is_pressed:
            print("  [CẢNH BÁO] Nút đang ở trạng thái nhấn khi chưa bấm, kiểm tra lại dây.")
        deadline = time.monotonic() + BUTTON_TIMEOUT
        count = 0
        while count < BUTTON_PRESSES:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not button.wait_for_press(timeout=remaining):
                break
            count += 1
            print(f"  Nhận lần nhấn {count}/{BUTTON_PRESSES}")
            button.wait_for_release(timeout=max(0.0, deadline - time.monotonic()))
    finally:
        button.close()
    return count >= BUTTON_PRESSES


def ask(question):
    return input(f"  {question} [y/n]: ").strip().lower().startswith("y")


TESTS = {"servo": test_servo, "led": test_led, "button": test_button}


def main():
    names = sys.argv[1:] or list(TESTS)
    unknown = [n for n in names if n not in TESTS]
    if unknown:
        print(f"Không có bài test: {', '.join(unknown)}. Chọn trong: {', '.join(TESTS)}")
        return 2

    results = {}
    for name in names:
        try:
            results[name] = TESTS[name]()
        except Exception as e:
            print(f"  [LỖI] {e}")
            results[name] = False

    print("\n===== KẾT QUẢ =====")
    for name, ok in results.items():
        print(f"  {name:<7}: {'OK' if ok else 'LỖI'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nĐã dừng.")
        sys.exit(130)
