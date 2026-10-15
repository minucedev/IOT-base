"""Test còi trên Raspberry Pi bằng 2 cách (chạy: python test_buzzer.py --pin 24).

1. digital: gpiozero.Buzzer -> on(), tắt sau 1s   (buzzer ACTIVE)
2. pwm:     gpiozero.PWMOutputDevice -> value = 0.5 trong 1s rồi value = 0.0 (buzzer PASSIVE)
"""
import argparse
import time

from gpiozero import Buzzer, PWMOutputDevice


def test_digital(pin: int, seconds: float) -> None:
    print(f"[1] Buzzer.on() trên GPIO{pin} trong {seconds}s...")
    buzzer = Buzzer(pin)
    try:
        buzzer.on()
        time.sleep(seconds)
        buzzer.off()
    finally:
        buzzer.close()


def test_pwm(pin: int, seconds: float, freq: int) -> None:
    print(f"[2] PWM value=0.5 @ {freq} Hz trên GPIO{pin} trong {seconds}s...")
    buzzer = PWMOutputDevice(pin, frequency=freq)
    try:
        buzzer.value = 0.5   # bật còi (duty 50%)
        time.sleep(seconds)
        buzzer.value = 0.0   # tắt còi
    finally:
        buzzer.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", type=int, default=24, help="Chân BCM nối chân + của còi")
    ap.add_argument("--seconds", type=float, default=1.0)
    ap.add_argument("--freq", type=int, default=2000, help="Tần số PWM (Hz)")
    ap.add_argument("--mode", choices=["digital", "pwm", "both"], default="both")
    a = ap.parse_args()

    if a.mode in ("digital", "both"):
        test_digital(a.pin, a.seconds)
    if a.mode == "both":
        time.sleep(1.0)
    if a.mode in ("pwm", "both"):
        test_pwm(a.pin, a.seconds, a.freq)
    print("Xong.")
