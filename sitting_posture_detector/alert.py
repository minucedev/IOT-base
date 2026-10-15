"""Logic cảnh báo: màu overlay + 4 LED trạng thái + còi PWM qua GPIO (gpiozero)."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import config

log = logging.getLogger(__name__)

# Màu BGR cho OpenCV
COLOR_GOOD = (0, 200, 0)
COLOR_BAD = (0, 0, 255)
COLOR_NEUTRAL = (160, 160, 160)


class _Led:
    """Bọc gpiozero.LED; tự động no-op nếu không chạy trên Raspberry Pi."""

    def __init__(self, pin: int, name: str) -> None:
        self.name, self._led = name, None
        try:
            from gpiozero import LED
            self._led = LED(pin)
        except Exception as exc:  # noqa: BLE001
            log.warning("LED %s (GPIO%d) không khả dụng, chạy chế độ giả lập: %s", name, pin, exc)

    def set(self, on: bool) -> None:
        if self._led is not None:
            self._led.on() if on else self._led.off()

    def close(self) -> None:
        if self._led is not None:
            self._led.off()
            self._led.close()


class _Buzzer:
    """Còi passive điều khiển bằng PWM (value=duty): kêu bíp ngắt quãng trong thread riêng.
    No-op nếu không chạy trên Raspberry Pi."""

    def __init__(self, pin: int) -> None:
        self._bz = None
        self._on = threading.Event()
        self._stop = threading.Event()
        try:
            from gpiozero import PWMOutputDevice
            self._bz = PWMOutputDevice(pin, frequency=config.BUZZER_FREQ)
        except Exception as exc:  # noqa: BLE001
            log.warning("Còi (GPIO%d) không khả dụng, chạy chế độ giả lập: %s", pin, exc)
            return
        threading.Thread(target=self._loop, name="buzzer", daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self._on.wait(timeout=0.2):
                continue
            self._bz.value = config.BUZZER_DUTY   # bật còi
            self._stop.wait(config.BUZZER_ON_SEC)
            self._bz.value = 0.0                  # tắt còi
            self._stop.wait(config.BUZZER_OFF_SEC)

    def set(self, on: bool) -> None:
        if on:
            self._on.set()
        else:
            self._on.clear()

    def close(self) -> None:
        self._stop.set()
        if self._bz is not None:
            self._bz.value = 0.0
            self._bz.close()


@dataclass
class AlertState:
    status: str
    is_alert: bool
    color: tuple
    leds: Dict[str, bool]
    bad_seconds: float


class AlertManager:
    """Mỗi trạng thái (GOOD/SLOUCH/LEAN/HEAD_DOWN) một LED, sáng theo trạng thái hiện tại.
    Còi kêu khi sai tư thế (bất kỳ loại nào) liên tục >= BAD_POSTURE_HOLD_SEC."""

    def __init__(self) -> None:
        self.leds = {status: _Led(pin, status) for status, pin in config.LED_PINS.items()}
        self.buzzer = _Buzzer(config.BUZZER_PIN)
        self._bad_since: Optional[float] = None

    def update(self, status: str, now: Optional[float] = None) -> AlertState:
        now = time.monotonic() if now is None else now
        bad_seconds = 0.0

        if status in config.BAD_STATUSES:
            if self._bad_since is None:
                self._bad_since = now
            bad_seconds = now - self._bad_since
        else:  # GOOD / NO_PERSON / UNKNOWN
            self._bad_since = None
        alerting = bad_seconds >= config.BAD_POSTURE_HOLD_SEC

        led_states = {name: name == status for name in self.leds}
        for name, led in self.leds.items():
            led.set(led_states[name])
        self.buzzer.set(alerting and config.BUZZER_ENABLED)

        if status in config.BAD_STATUSES:
            color = COLOR_BAD
        elif status == config.STATUS_GOOD:
            color = COLOR_GOOD
        else:
            color = COLOR_NEUTRAL
        return AlertState(status, alerting, color, led_states, bad_seconds)

    def close(self) -> None:
        for led in self.leds.values():
            led.close()
        self.buzzer.close()
