"""Module điều khiển phần cứng: Động cơ Servo và Còi Báo Động Buzzer.

Tương thích Raspberry Pi 4 (qua RPi.GPIO).
Tự động kích hoạt chế độ Giả lập (Mock Mode) nếu chạy trên máy tính (Windows/macOS)
để phục vụ kiểm thử không bị crash.
"""

import sys
import threading
import time
from typing import Optional

# Cấu hình chân GPIO mặc định theo chuẩn BCM
SERVO_PIN = 18    # GPIO 18 (Chân vật lý 12) - Hardware PWM0
BUZZER_PIN = 23   # GPIO 23 (Chân vật lý 16) - Digital Output

# Cấu hình xung cho Servo SG90 (50Hz = chu kỳ 20ms)
SERVO_FREQ = 50
DUTY_0_DEGREE = 2.5    # ~0.5ms (Góc 0 độ - Cửa đóng)
DUTY_180_DEGREE = 12.0  # ~2.4ms (Góc 180 độ - Cửa mở)

IS_RASPBERRY_PI = False
try:
    import RPi.GPIO as GPIO
    IS_RASPBERRY_PI = True
except (ImportError, RuntimeError):
    IS_RASPBERRY_PI = False


class HardwareController:
    """Quản lý điều khiển Servo và Buzzer an toàn và bất đồng bộ."""

    def __init__(self, servo_pin: int = SERVO_PIN, buzzer_pin: int = BUZZER_PIN) -> None:
        self.servo_pin = servo_pin
        self.buzzer_pin = buzzer_pin
        self.is_pi = IS_RASPBERRY_PI

        self._servo_pwm = None
        self._servo_lock = threading.Lock()
        self._is_door_open = False
        self._door_thread: Optional[threading.Thread] = None

        self._is_buzzer_active = False

        self._init_gpio()

    def _init_gpio(self) -> None:
        """Khởi tạo chân GPIO trên Raspberry Pi hoặc chạy chế độ Mock."""
        if self.is_pi:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)

                # Khởi tạo chân Servo
                GPIO.setup(self.servo_pin, GPIO.OUT)
                self._servo_pwm = GPIO.PWM(self.servo_pin, SERVO_FREQ)
                self._servo_pwm.start(0)

                # Khởi tạo chân Buzzer
                GPIO.setup(self.buzzer_pin, GPIO.OUT)
                GPIO.output(self.buzzer_pin, GPIO.LOW)

                print(f"[Hardware] ✅ Khởi tạo phần cứng thành công: Servo=GPIO{self.servo_pin}, Buzzer=GPIO{self.buzzer_pin}")
                # Đưa servo về vị trí 0 độ ban đầu
                self._apply_servo_angle(0)
            except Exception as e:
                print(f"[Hardware] ❌ Lỗi khởi tạo GPIO: {e}. Chuyển sang chế độ giả lập.")
                self.is_pi = False
        else:
            print("[Hardware] ⚠️ Không tìm thấy RPi.GPIO (Chạy trên PC/Laptop). Đang dùng chế độ GIẢ LẬP (Mock GPIO).")

    # ── ĐIỀU KHIỂN SERVO ────────────────────────────────────────────────

    def _angle_to_duty(self, angle: float) -> float:
        """Chuyển đổi góc từ 0 đến 180 sang duty cycle tương ứng."""
        angle = max(0.0, min(180.0, float(angle)))
        return DUTY_0_DEGREE + (angle / 180.0) * (DUTY_180_DEGREE - DUTY_0_DEGREE)

    def _apply_servo_angle(self, angle: float) -> None:
        """Xuất xung PWM để đưa servo tới góc chỉ định, sau đó ngắt xung chống rung."""
        if self.is_pi and self._servo_pwm is not None:
            duty = self._angle_to_duty(angle)
            self._servo_pwm.ChangeDutyCycle(duty)
            time.sleep(0.4)  # Đợi servo quay đến vị trí
            self._servo_pwm.ChangeDutyCycle(0)  # Ngắt xung giữ để servo không rung/kêu è è
        else:
            print(f"[MOCK GPIO] -> Servo chuyển động tới góc: {angle}°")

    def trigger_open_door(self, hold_seconds: float = 5.0) -> bool:
        """Kích hoạt mở cửa 180 độ trong hold_seconds rồi tự động đóng về 0 độ.
        
        Trả về True nếu kích hoạt mở thành công. Trả về False nếu cửa đang mở sẵn.
        """
        with self._servo_lock:
            if self._is_door_open:
                return False  # Cửa đang trong chu kỳ mở, không kích hoạt đè
            self._is_door_open = True

        def _run_door_cycle():
            print(f"\n[Hardware] 🟢 XÁC THỰC NGƯỜI QUEN: Quay Servo 180° (Giữ {hold_seconds}s)...", flush=True)
            self._apply_servo_angle(180)
            time.sleep(hold_seconds)
            print("[Hardware] 🔄 Hết thời gian mở: Quay Servo về 0° (Đóng cửa)...", flush=True)
            self._apply_servo_angle(0)
            with self._servo_lock:
                self._is_door_open = False
            print("[Hardware] 🚪 Cửa đã đóng hoàn toàn.", flush=True)

        self._door_thread = threading.Thread(target=_run_door_cycle, name="servo-door-thread", daemon=True)
        self._door_thread.start()
        return True

    @property
    def is_door_open(self) -> bool:
        """Trạng thái hiện tại của cửa (True = đang mở 180°, False = đóng 0°)."""
        with self._servo_lock:
            return self._is_door_open

    # ── ĐIỀU KHIỂN CÒI BUZZER ──────────────────────────────────────────

    def set_buzzer(self, state: bool) -> None:
        """Bật hoặc tắt còi báo động Active Buzzer."""
        if self._is_buzzer_active == state:
            return  # Không thay đổi trạng thái, bỏ qua

        self._is_buzzer_active = state
        if self.is_pi:
            GPIO.output(self.buzzer_pin, GPIO.HIGH if state else GPIO.LOW)
        else:
            print(f"[MOCK GPIO] -> Còi Buzzer: {'🔔 HÚ CÒI (BẬT)' if state else '🔕 TẮT CÒI'}")

    @property
    def is_buzzer_on(self) -> bool:
        """Kiểm tra còi có đang hú không."""
        return self._is_buzzer_active

    # ── DỌN DẸP TÀI NGUYÊN ──────────────────────────────────────────────

    def cleanup(self) -> None:
        """Tắt còi, hạ servo và giải phóng chân GPIO khi thoát chương trình."""
        print("[Hardware] Đang giải phóng phần cứng...", flush=True)
        self.set_buzzer(False)
        self._apply_servo_angle(0)
        if self.is_pi:
            try:
                if self._servo_pwm is not None:
                    self._servo_pwm.stop()
                GPIO.cleanup()
            except Exception:
                pass
        print("[Hardware] Giải phóng phần cứng xong.", flush=True)
