"""Test LED/motor trên Pi, không dùng camera, MediaPipe hay Flask."""

import argparse
import logging
import math
import os
import time

from gpio_outputs import GPIOOutputs


def show(outputs):
    state = outputs.snapshot()
    print(f"  {state['command']} | ENA duty={state['ena_duty']:g}%", flush=True)
    print(f"  GPIO readback (BCM): {outputs.read_levels()}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Dừng app.py trước khi chạy test này.")
    parser.add_argument("--case", choices=("led", "motor", "all", "gestures"), default="all")
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument("--duty", type=float, default=100, help="Tốc độ PWM ENA: 1–100%%")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0.5 <= args.seconds <= 30:
        parser.error("--seconds phải nằm trong 0.5–30.")
    if not math.isfinite(args.duty) or not 1 <= args.duty <= 100:
        parser.error("--duty phải nằm trong 1–100.")
    os.environ["MOTOR_DUTY"] = str(args.duty)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    outputs = GPIOOutputs(start_watchdog=False)
    try:
        print("BCM: LED27 (pin13), IN1=23 (pin16), IN2=24 (pin18), ENA12 (pin32)", flush=True)
        print("Log chỉ xác nhận lệnh/mức GPIO, cần quan sát LED và motor.", flush=True)
        if args.case in ("led", "all"):
            print(f"[LED] Bật {args.seconds:g}s", flush=True)
            outputs.set_led(True)
            show(outputs)
            time.sleep(args.seconds)
            outputs.set_led(False)
            print("[LED] Tắt", flush=True)
            time.sleep(1)
        if args.case in ("motor", "all"):
            print(f"[DC] Quay thuận {args.seconds:g}s: IN1=1 IN2=0, ENA được bật", flush=True)
            outputs.set_motor("forward")
            show(outputs)
            time.sleep(args.seconds)
            outputs.set_motor("stop")
            print("[DC] Dừng 2s", flush=True)
            time.sleep(2)
            print(f"[DC] Quay ngược {args.seconds:g}s: IN1=0 IN2=1", flush=True)
            outputs.set_motor("reverse")
            show(outputs)
            time.sleep(args.seconds)
            outputs.set_motor("stop")
        if args.case == "gestures":
            for gesture, description in (
                ("Open_Palm", "Xòe: LED ON, quay thuận"),
                ("Pointing_Up", "Trỏ: LED vẫn ON, tiếp tục quay thuận"),
                ("Thumb", "Cái: LED vẫn ON, quay ngược"),
                ("Closed_Fist", "Nắm: LED OFF, DC tắt"),
            ):
                print(f"[Lệnh giả lập, không nhận diện] {description}", flush=True)
                outputs.apply(gesture)
                show(outputs)
                time.sleep(args.seconds)
    finally:
        outputs.close()
        print("Đã tắt LED, motor, PWM và giải phóng GPIO.", flush=True)


if __name__ == "__main__":
    main()
