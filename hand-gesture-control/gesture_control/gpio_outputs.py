"""Điều khiển LED và motor DC qua RPi.GPIO, đánh số BCM."""

import logging
import math
import os
import threading
import time

LOG = logging.getLogger(__name__)
LED_PIN = 27                 # Chân vật lý 13
IN1_PIN = 23                 # Chân vật lý 16
IN2_PIN = 24                 # Chân vật lý 18
ENA_PIN = 12                 # Chân vật lý 32, tháo jumper ENA trên driver
PINS = (LED_PIN, IN1_PIN, IN2_PIN, ENA_PIN)


def env_number(name, default, low, high):
    value = float(os.getenv(name, str(default)))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} phải nằm trong {low}–{high}.")
    return value


class GPIOOutputs:
    """Lưu lệnh đang phát, không suy ra motor thực tế có quay hay không.

    gpio_module chỉ dành cho kiểm thử phần mềm. Khi chạy thật luôn import RPi.GPIO.
    Một watchdog độc lập dừng đầu ra nếu camera/model ngừng trả kết quả.
    """

    def __init__(self, gpio_module=None, start_watchdog=True):
        self.duty = env_number("MOTOR_DUTY", 100, 1, 100)
        self.reverse_pause = env_number("REVERSE_PAUSE", 0.3, 0.05, 3)
        self.gesture_timeout = 0
        self.frame_timeout = env_number("FRAME_TIMEOUT", 3, 1, 60)
        if gpio_module is None:
            try:
                import RPi.GPIO as gpio_module
            except ImportError as exc:
                raise RuntimeError(
                    "Chưa có RPi.GPIO. Kích hoạt .venv rồi chạy: "
                    "python -m pip install -r requirements.txt"
                ) from exc
        self.gpio = gpio_module
        self.lock = threading.RLock()
        self.closed = False
        self.stopping = False
        self.led_on = False
        self.armed = False
        self.motor_direction = "stop"
        self.last_gesture_time = None
        self.last_frame_time = time.monotonic()
        self.reason = "startup"
        self.pwm = None
        self.watchdog_stop = threading.Event()
        self.watchdog_thread = None
        configured = []
        try:
            self.gpio.setwarnings(True)
            self.gpio.setmode(self.gpio.BCM)
            for pin in PINS:
                self.gpio.setup(pin, self.gpio.OUT, initial=self.gpio.LOW)
                configured.append(pin)
            # Đây là PWM phần mềm của RPi.GPIO, kể cả khi chọn BCM12.
            self.pwm = self.gpio.PWM(ENA_PIN, 1000)
            self.pwm.start(0)
        except BaseException:
            try:
                if self.pwm is not None:
                    self.pwm.stop()
            finally:
                if configured:
                    self.gpio.cleanup(configured)
            self.closed = True
            raise
        LOG.info("RPi.GPIO BCM: LED=27 IN1=23 IN2=24 ENA=12; duty=%g%%", self.duty)
        if start_watchdog:
            self.watchdog_thread = threading.Thread(
                target=self._watchdog, name="gpio-watchdog", daemon=True
            )
            self.watchdog_thread.start()

    def _led_locked(self, on):
        on = bool(on)
        if on != self.led_on:
            self.gpio.output(LED_PIN, self.gpio.HIGH if on else self.gpio.LOW)
            self.led_on = on

    def _motor_locked(self, direction):
        if direction not in ("forward", "reverse", "stop"):
            raise ValueError("Chiều motor: forward, reverse hoặc stop.")
        if direction == self.motor_direction:
            return  # Xòe tay -> ngón trỏ: không ngắt ENA, motor tiếp tục quay.
        previous = self.motor_direction
        self.pwm.ChangeDutyCycle(0)
        self.gpio.output(IN1_PIN, self.gpio.LOW)
        self.gpio.output(IN2_PIN, self.gpio.LOW)
        if previous != "stop" and direction != "stop":
            # Chờ trước khi đảo chiều; có thể tăng REVERSE_PAUSE cho motor nặng.
            time.sleep(self.reverse_pause)
        if direction == "forward":
            self.gpio.output(IN1_PIN, self.gpio.HIGH)
        elif direction == "reverse":
            self.gpio.output(IN2_PIN, self.gpio.HIGH)
        self.pwm.ChangeDutyCycle(self.duty if direction != "stop" else 0)
        self.motor_direction = direction

    def _off_locked(self, reason):
        self.pwm.ChangeDutyCycle(0)
        self.gpio.output(IN1_PIN, self.gpio.LOW)
        self.gpio.output(IN2_PIN, self.gpio.LOW)
        self.gpio.output(LED_PIN, self.gpio.LOW)
        self.led_on = False
        self.motor_direction = "stop"
        self.last_gesture_time = None
        if reason != "Closed_Fist":
            self.armed = False  # Lỗi camera/timeout/shutdown: phải xòe tay mở khóa lại
        self.reason = reason

    def apply(self, gesture):
        with self.lock:
            if self.closed or self.stopping:
                return
            if gesture not in ("Open_Palm", "Closed_Fist", "Pointing_Up", "Thumb"):
                return
            before = (self.led_on, self.motor_direction, self.armed)
            if gesture == "Open_Palm":
                self.armed = True               # Chỉ mở khóa, không đổi đèn/quạt
            elif not self.armed:
                return                          # Chưa xòe tay: bỏ qua mọi lệnh khác
            elif gesture == "Pointing_Up":
                self._led_locked(True)          # Ngón trỏ: bật đèn
            elif gesture == "Thumb":
                self._motor_locked("stop")      # Ngón cái: tắt quạt
            else:
                self._off_locked(gesture)       # Còn lại: tắt hết (vẫn giữ mở khóa)
            self.last_gesture_time = time.monotonic()
            self.reason = gesture
            if before != (self.led_on, self.motor_direction, self.armed):
                LOG.info("%s -> %s", gesture, self.snapshot()["command"])

    def heartbeat(self):
        with self.lock:
            if not self.closed and not self.stopping:
                self.last_frame_time = time.monotonic()

    def set_led(self, on):
        """Dùng trong test GPIO độc lập."""
        with self.lock:
            if not self.closed and not self.stopping:
                self._led_locked(on)
                self.reason = "manual_test"

    def set_motor(self, direction):
        with self.lock:
            if not self.closed and not self.stopping:
                self._motor_locked(direction)
                self.reason = "manual_test"

    def all_off(self, reason="stop"):
        with self.lock:
            if not self.closed:
                self._off_locked(reason)

    def check_timeouts(self, now=None):
        with self.lock:
            if self.closed or self.stopping or not (self.led_on or self.motor_direction != "stop"):
                return
            current = time.monotonic() if now is None else now
            if current - self.last_frame_time > self.frame_timeout:
                self._off_locked("camera_timeout")
                LOG.warning("Camera/model quá lâu không có kết quả mới: tắt đầu ra.")
            elif (self.gesture_timeout > 0 and self.last_gesture_time is not None
                  and current - self.last_gesture_time > self.gesture_timeout):
                self._off_locked("gesture_timeout")
                LOG.info("Quá lâu không có cử chỉ hợp lệ: tắt đầu ra.")

    def _watchdog(self):
        while not self.watchdog_stop.wait(0.1):
            try:
                self.check_timeouts()
            except Exception:
                LOG.exception("Lỗi kiểm tra GPIO; ngừng nhận lệnh.")
                self.begin_shutdown()
                return

    def snapshot(self):
        with self.lock:
            motor_text = {"forward": "quay thuận", "reverse": "quay ngược", "stop": "tắt"}[self.motor_direction]
            return {
                "armed": self.armed,
                "led_on": self.led_on,
                "motor_direction": self.motor_direction,
                "ena_duty": self.duty if self.motor_direction != "stop" else 0,
                "command": f"{'ĐÃ MỞ' if self.armed else 'KHÓA'} | Đèn {'ON' if self.led_on else 'OFF'} | Quạt {motor_text}",
                "reason": self.reason,
                "closed": self.closed,
            }

    def read_levels(self):
        """Đọc mức GPIO để hỗ trợ đo kiểm. ENA PWM có thể đang ở mức 0 hoặc 1."""
        with self.lock:
            if self.closed:
                return {}
            return {str(pin): int(self.gpio.input(pin)) for pin in PINS}

    def begin_shutdown(self):
        with self.lock:
            self.stopping = True
            self.watchdog_stop.set()
            if not self.closed:
                self._off_locked("shutdown")

    def close(self):
        self.begin_shutdown()
        if self.watchdog_thread is not None and self.watchdog_thread is not threading.current_thread():
            self.watchdog_thread.join(timeout=1)
        with self.lock:
            if self.closed:
                return
            try:
                self.pwm.stop()
            finally:
                try:
                    self.gpio.output(ENA_PIN, self.gpio.LOW)
                finally:
                    self.closed = True
                    self.gpio.cleanup(list(PINS))
