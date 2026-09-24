#!/usr/bin/env python3
"""Điều khiển thiết bị nhà thông minh bằng giọng nói tiếng Việt trên Raspberry Pi.

Nhận âm thanh stream từ Laptop Microphone qua TCP Socket,
nhận diện khẩu lệnh (bật/tắt đèn, bật/tắt động cơ DC) và điều khiển trực tiếp qua chân GPIO.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gpiozero import LED, OutputDevice, PWMOutputDevice

import realtime_asr_streaming as asr
from audio_client import stream_audio_from_laptop, LAPTOP_IP, AUDIO_PORT

# ============================================================
# CẤU HÌNH CHÂN GPIO (RASPBERRY PI)
# ============================================================
LIGHT_PIN = 17       # Chân điều khiển Đèn / LED

MOTOR_IN1_PIN = 23   # Chân L298N IN1
MOTOR_IN2_PIN = 24   # Chân L298N IN2
MOTOR_ENA_PIN = 13   # Chân L298N ENA (PWM tốc độ động cơ)
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
# HARDWARE CONTROLLER (GPIO)
# ============================================================
class HardwareController:
    """Điều khiển trực tiếp phần cứng qua thư viện gpiozero."""

    def __init__(self) -> None:
        self.light = LED(LIGHT_PIN, active_high=True, initial_value=False)
        self.motor_in1 = OutputDevice(MOTOR_IN1_PIN, active_high=True, initial_value=False)
        self.motor_in2 = OutputDevice(MOTOR_IN2_PIN, active_high=True, initial_value=False)
        self.motor_ena = PWMOutputDevice(MOTOR_ENA_PIN, active_high=True, initial_value=0, frequency=1000)
        self._closed = False
        print(color("[+] Khởi tạo GPIO thành công (Đèn: GPIO17, Động cơ: GPIO13,23,24).", C.GREEN))

    def turn_light_on(self) -> None:
        self.light.on()

    def turn_light_off(self) -> None:
        self.light.off()

    def turn_motor_on(self, speed: float = 1.0) -> None:
        speed = max(0.0, min(1.0, float(speed)))
        self.motor_in1.on()
        self.motor_in2.off()
        self.motor_ena.value = speed

    def turn_motor_off(self) -> None:
        self.motor_ena.value = 0
        self.motor_in1.off()
        self.motor_in2.off()

    def get_light_state(self) -> bool:
        return self.light.is_lit

    def get_motor_state(self) -> bool:
        return self.motor_ena.value > 0

    def cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.turn_light_off()
        self.turn_motor_off()
        self.light.close()
        self.motor_in1.close()
        self.motor_in2.close()
        self.motor_ena.close()


# ============================================================
# COMMAND PARSER
# ============================================================
ACTION_ALIASES = {
    "on": ("bật", "mở"),
    "off": ("tắt", "đóng"),
}

DEVICE_ALIASES = {
    "light": ("đèn",),
    "motor": ("động_cơ",),  # normalize() đã gộp "động cơ" -> "động_cơ" thành 1 token
}

ACTION_LABELS = {"on": "BẬT", "off": "TẮT"}
DEVICE_LABELS = {"light": "ĐÈN", "motor": "ĐỘNG CƠ"}
DEVICE_ICONS = {"light": "💡", "motor": "🌀"}


@dataclass(frozen=True)
class Command:
    device: str
    action: str


# Khẩu lệnh cảm ngữ cảnh: không cần nói "bật/tắt", chỉ cần mô tả điều kiện.
# Mỗi trigger khớp khi TẤT CẢ các từ khóa xuất hiện trong câu nói (không phân biệt thứ tự).
SENSOR_TRIGGERS: tuple[tuple[frozenset[str], tuple[Command, ...]], ...] = (
    (frozenset({"nóng", "quá"}), (Command("motor", "on"),)),
    (frozenset({"lạnh", "quá"}), (Command("motor", "off"),)),
    (frozenset({"trời", "tối"}), (Command("light", "on"),)),
    (frozenset({"trời", "sáng"}), (Command("light", "off"),)),
)


def normalize(text: str) -> str:
    text = asr.postprocess_command_text(text)
    # "động cơ" là khẩu lệnh 2 từ -> gộp thành 1 token để so khớp thiết bị.
    return text.replace("động cơ", "động_cơ")


def parse_commands(text: str) -> list[Command]:
    """Phân tích chuỗi văn bản thành danh sách lệnh điều khiển."""
    text = normalize(text)
    if not text:
        return []

    tokens = text.split()
    token_set = set(tokens)

    # Khẩu lệnh cảm ngữ cảnh: "nóng quá", "lạnh quá", "trời sáng", "trời tối"...
    for keywords, cmds in SENSOR_TRIGGERS:
        if keywords <= token_set:
            return list(cmds)

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
        return [Command("light", act), Command("motor", act)]

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


def execute_command(cmd: Command, hw: HardwareController) -> None:
    """Thực thi lệnh lên phần cứng GPIO."""
    icon = DEVICE_ICONS.get(cmd.device, "⚙️")
    dev_name = DEVICE_LABELS.get(cmd.device, cmd.device.upper())
    act_name = ACTION_LABELS.get(cmd.action, cmd.action.upper())

    print(color(f"  >> {icon} {act_name} {dev_name}", C.BRIGHT_GREEN if cmd.action == "on" else C.YELLOW, C.BOLD))

    if cmd.device == "light":
        if cmd.action == "on":
            hw.turn_light_on()
        else:
            hw.turn_light_off()
    elif cmd.device == "motor":
        if cmd.action == "on":
            hw.turn_motor_on(1.0)
        else:
            hw.turn_motor_off()


def print_banner(host: str, port: int) -> None:
    print("=" * 60)
    print(color("  🎙️  VIETNAMESE SPEECH SMART HOME CONTROL", C.CYAN, C.BOLD))
    print("=" * 60)
    print(f" Nguồn Mic Laptop : {host}:{port} (TCP PCM 16kHz)")
    print(f" Phần cứng GPIO   : Đèn (GPIO 17), Động cơ DC (GPIO 13, 23, 24)")
    print(hr(60))
    print(" Các khẩu lệnh được hỗ trợ:")
    print("   💡 'bật đèn'   / 'tắt đèn'   (hoặc 'mở đèn' / 'đóng đèn')")
    print("   🌀 'bật động cơ'  / 'tắt động cơ'  (hoặc 'mở động cơ' / 'đóng động cơ')")
    print("   ⚡ 'bật cả hai' / 'tắt hết'  / 'bật đèn và động cơ'")
    print("   🌡️  'nóng quá' -> bật động cơ  |  'lạnh quá' -> tắt động cơ")
    print("   🌤️  'trời tối' -> bật đèn      |  'trời sáng' -> tắt đèn")
    print("=" * 60)


def main() -> None:
    args = asr.parse_args()
    hw = HardwareController()

    print_banner(args.laptop_ip, args.audio_port)

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
