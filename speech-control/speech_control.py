#!/usr/bin/env python3
"""Điều khiển thiết bị nhà thông minh bằng giọng nói tiếng Việt.

Nhận âm thanh stream từ Laptop Microphone qua TCP Socket,
nhận diện khẩu lệnh (bật/tắt đèn, bật/tắt quạt) và điều khiển qua chân GPIO.
Hỗ trợ tự động chuyển sang Mock Hardware nếu không có phần cứng thật.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import realtime_asr_streaming as asr
from audio_client import stream_audio_from_laptop, LAPTOP_IP, AUDIO_PORT

# ============================================================
# CẤU HÌNH CHÂN GPIO (RASPBERRY PI)
# ============================================================
LIGHT_PIN = 17       # Chân điều khiển Đèn / LED

MOTOR_IN1_PIN = 23   # Chân L298N IN1
MOTOR_IN2_PIN = 24   # Chân L298N IN2
MOTOR_ENA_PIN = 13   # Chân L298N ENA (PWM tốc độ quạt)
# ============================================================


# ============================================================
# CONSOLE UI
# ============================================================
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"


def color(text: str, *codes: str) -> str:
    return "".join(codes) + text + C.RESET


def hr(width: int = 56) -> str:
    return color("─" * width, C.BRIGHT_BLACK)


# ============================================================
# HARDWARE CONTROLLERS (REAL & MOCK)
# ============================================================
class HardwareController:
    """Điều khiển phần cứng thật qua thư viện gpiozero."""

    def __init__(self) -> None:
        from gpiozero import LED, OutputDevice, PWMOutputDevice

        self.light = LED(LIGHT_PIN, active_high=True, initial_value=False)
        self.motor_in1 = OutputDevice(MOTOR_IN1_PIN, active_high=True, initial_value=False)
        self.motor_in2 = OutputDevice(MOTOR_IN2_PIN, active_high=True, initial_value=False)
        self.motor_ena = PWMOutputDevice(MOTOR_ENA_PIN, active_high=True, initial_value=0, frequency=1000)
        self._closed = False

    def turn_light_on(self) -> None:
        self.light.on()

    def turn_light_off(self) -> None:
        self.light.off()

    def turn_fan_on(self, speed: float = 1.0) -> None:
        speed = max(0.0, min(1.0, float(speed)))
        self.motor_in1.on()
        self.motor_in2.off()
        self.motor_ena.value = speed

    def turn_fan_off(self) -> None:
        self.motor_ena.value = 0
        self.motor_in1.off()
        self.motor_in2.off()

    def get_light_state(self) -> bool:
        return self.light.is_lit

    def get_fan_state(self) -> bool:
        return self.motor_ena.value > 0

    def cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.turn_light_off()
        self.turn_fan_off()
        self.light.close()
        self.motor_in1.close()
        self.motor_in2.close()
        self.motor_ena.close()


class MockHardwareController:
    """Giả lập phần cứng khi chạy thử trên máy tính hoặc chưa cắm dây GPIO."""

    def __init__(self) -> None:
        self.light_state = False
        self.fan_state = False
        self.fan_speed = 0.0

    def turn_light_on(self) -> None:
        self.light_state = True
        print(color("  [MOCK HW] 💡 ĐÈN: ĐÃ BẬT", C.BRIGHT_GREEN, C.BOLD))

    def turn_light_off(self) -> None:
        self.light_state = False
        print(color("  [MOCK HW] 💡 ĐÈN: ĐÃ TẮT", C.RED, C.BOLD))

    def turn_fan_on(self, speed: float = 1.0) -> None:
        self.fan_state = True
        self.fan_speed = speed
        print(color(f"  [MOCK HW] 🌀 QUẠT: ĐÃ BẬT ({int(speed * 100)}%)", C.BRIGHT_GREEN, C.BOLD))

    def turn_fan_off(self) -> None:
        self.fan_state = False
        self.fan_speed = 0.0
        print(color("  [MOCK HW] 🌀 QUẠT: ĐÃ TẮT", C.RED, C.BOLD))

    def get_light_state(self) -> bool:
        return self.light_state

    def get_fan_state(self) -> bool:
        return self.fan_state

    def cleanup(self) -> None:
        pass


def create_controller(force_mock: bool = False) -> tuple[Any, bool]:
    """Tự động phát hiện và tạo controller phù hợp."""
    if force_mock:
        print(color("[*] Đang sử dụng Mock Hardware Controller (--mock).", C.YELLOW))
        return MockHardwareController(), True

    try:
        controller = HardwareController()
        print(color("[+] Khởi tạo GPIO Controller thành công (chân GPIO thật).", C.GREEN))
        return controller, False
    except Exception as exc:
        print(color(f"[!] Không thể mở GPIO ({exc}). Tự động chuyển sang Mock Hardware.", C.YELLOW))
        return MockHardwareController(), True


# ============================================================
# COMMAND PARSER
# ============================================================
ACTION_ALIASES = {
    "on": ("bật", "mở"),
    "off": ("tắt", "đóng"),
}

DEVICE_ALIASES = {
    "light": ("đèn",),
    "fan": ("quạt",),
}

ACTION_LABELS = {"on": "BẬT", "off": "TẮT"}
DEVICE_LABELS = {"light": "ĐÈN", "fan": "QUẠT"}
DEVICE_ICONS = {"light": "💡", "fan": "🌀"}


@dataclass(frozen=True)
class Command:
    device: str
    action: str


def normalize(text: str) -> str:
    return asr.postprocess_command_text(text)


def parse_commands(text: str) -> list[Command]:
    """Phân tích chuỗi văn bản thành danh sách lệnh điều khiển."""
    text = normalize(text)
    if not text:
        return []

    tokens = text.split()
    actions = [w for w in tokens if any(w in aliases for aliases in ACTION_ALIASES.values())]
    devices = [w for w in tokens if any(w in aliases for aliases in DEVICE_ALIASES.values())]

    def to_action(w: str) -> str:
        for act, aliases in ACTION_ALIASES.items():
            if w in aliases:
                return act
        return ""

    def to_device(w: str) -> str:
        for dev, aliases in DEVICE_ALIASES.items():
            if w in aliases:
                return dev
        return ""

    # Khẩu lệnh kép: "bật cả hai", "tắt hết"
    has_all = any(w in tokens for w in ("hết", "cả", "hai"))
    if actions and has_all:
        act = to_action(actions[0])
        return [Command("light", act), Command("fan", act)]

    # Ghép action + device
    results: list[Command] = []
    if len(actions) == 1 and len(devices) >= 1:
        act = to_action(actions[0])
        for d in devices:
            dev = to_device(d)
            if dev:
                results.append(Command(dev, act))
    elif len(actions) == len(devices):
        for a, d in zip(actions, devices):
            act = to_action(a)
            dev = to_device(d)
            if act and dev:
                results.append(Command(dev, act))

    return results


def execute_command(cmd: Command, hw: Any) -> None:
    """Thực thi lệnh lên phần cứng."""
    icon = DEVICE_ICONS.get(cmd.device, "⚙️")
    dev_name = DEVICE_LABELS.get(cmd.device, cmd.device.upper())
    act_name = ACTION_LABELS.get(cmd.action, cmd.action.upper())

    print(color(f"  >> {icon} {act_name} {dev_name}", C.BRIGHT_GREEN if cmd.action == "on" else C.YELLOW, C.BOLD))

    if cmd.device == "light":
        if cmd.action == "on":
            hw.turn_light_on()
        else:
            hw.turn_light_off()
    elif cmd.device == "fan":
        if cmd.action == "on":
            hw.turn_fan_on(1.0)
        else:
            hw.turn_fan_off()


def print_banner(host: str, port: int, is_mock: bool) -> None:
    print("=" * 60)
    print(color("  🎙️  VIETNAMESE SPEECH SMART HOME CONTROL", C.CYAN, C.BOLD))
    print("=" * 60)
    print(f" Nguồn Mic Laptop : {host}:{port} (TCP PCM 16kHz)")
    print(f" Chế độ Hardware  : {'MÔ PHỎNG (MOCK)' if is_mock else 'GPIO THẬT (Light: 17, Fan: 13,23,24)'}")
    print(hr(60))
    print(" Các khẩu lệnh được hỗ trợ:")
    print("   💡 'bật đèn'   / 'tắt đèn'   (hoặc 'mở đèn' / 'đóng đèn')")
    print("   🌀 'bật quạt'  / 'tắt quạt'  (hoặc 'mở quạt' / 'đóng quạt')")
    print("   ⚡ 'bật cả hai' / 'tắt hết'  / 'bật đèn và quạt'")
    print("=" * 60)


def main() -> None:
    args = asr.parse_args()
    hw, is_mock = create_controller(force_mock=args.mock)

    print_banner(args.laptop_ip, args.audio_port, is_mock)

    np, sherpa_onnx = asr.import_runtime()
    files = asr.find_model_files(args.model_dir, args.chunk_size)
    print("[*] Đang tải mô hình nhận diện giọng nói Zipformer...")
    recognizer = asr.create_recognizer(sherpa_onnx, files, args)
    vad, window_size = asr.create_vad(sherpa_onnx, args)

    def on_speech_final(text: str) -> None:
        cmds = parse_commands(text)
        if cmds:
            print(color(f"\n[PHÁT HIỆN LỆNH]: {text}", C.BRIGHT_YELLOW, C.BOLD))
            for cmd in cmds:
                execute_command(cmd, hw)
            print()
        else:
            if text:
                print(color(f"  (Chưa khớp khẩu lệnh điều khiển: '{text}')", C.DIM))

    audio_gen = stream_audio_from_laptop(
        host=args.laptop_ip,
        port=args.audio_port,
        blocksize=window_size,
    )

    try:
        asr.run_asr_pipeline(
            np=np,
            recognizer=recognizer,
            vad=vad,
            window_size=window_size,
            args=args,
            audio_source_generator=audio_gen,
            on_final=on_speech_final,
        )
    finally:
        hw.cleanup()
        print("\n[*] Hoàn tất dọn dẹp hệ thống.")


if __name__ == "__main__":
    main()
