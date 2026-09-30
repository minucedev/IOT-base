# alert.py
"""
Module điều khiển còi báo động (Buzzer) và Đèn cảnh báo (LED).
- Hỗ trợ Passive Buzzer (PWM) và Active Buzzer trên GPIO BCM 17.
- Hỗ trợ Đèn LED cảnh báo cháy trên GPIO BCM 27.
- Chạy còi trong luồng nền (non-blocking thread) để không làm đơ camera/vòng lặp AI.
"""

import time
import math
import threading
import config

class AlertSystem:
    def __init__(self):
        self.last_alert_time = 0.0
        self.last_fire_time = 0.0
        self.is_buzzing = False
        self.is_led_on = False
        self._lock = threading.Lock()
        self._should_buzz = False
        self._buzz_thread = None
        self.has_hardware = False
        self.buzzer = None
        self.led = None
        self.mode = None

        try:
            if getattr(config, "BUZZER_TYPE", "passive") == "passive":
                from gpiozero import PWMOutputDevice
                self.buzzer = PWMOutputDevice(
                    pin=config.BUZZER_PIN,
                    frequency=getattr(config, "BUZZER_FREQUENCY", 2000)
                )
                self.mode = "pwm"
            else:
                from gpiozero import Buzzer
                self.buzzer = Buzzer(config.BUZZER_PIN)
                self.mode = "active"

            from gpiozero import LED
            self.led = LED(getattr(config, "LED_PIN", 27))
            self.has_hardware = True
            self.platform = "pi"
            print(f"[Cảnh báo] Đã khởi tạo GPIO: Còi BCM {config.BUZZER_PIN} ({self.mode}), Đèn LED BCM {getattr(config, 'LED_PIN', 27)}")
        except Exception as e:
            self.platform = "simulation"
            print(f"[Cảnh báo] Chạy chế độ mô phỏng console (không có GPIO: {e}).")

    def _sound_on(self):
        """Bật còi"""
        if self.has_hardware:
            if self.mode == "pwm":
                self.buzzer.value = 0.5
            else:
                self.buzzer.on()

    def _sound_off(self):
        """Tắt còi"""
        if self.has_hardware:
            if self.mode == "pwm":
                self.buzzer.value = 0.0
            else:
                self.buzzer.off()

    def _led_on(self):
        """Bật đèn cảnh báo lửa"""
        if not self.is_led_on:
            self.is_led_on = True
            if self.has_hardware:
                self.led.on()
            print(f"[LED] >>> BẬT ĐÈN CẢNH BÁO LỬA (GPIO {getattr(config, 'LED_PIN', 27)}) <<<")

    def _led_off(self):
        """Tắt đèn cảnh báo lửa"""
        if self.is_led_on:
            self.is_led_on = False
            if self.has_hardware:
                self.led.off()
            print("[LED] >>> TẮT ĐÈN CẢNH BÁO LỬA <<<")

    def _buzz_sine_worker(self):
        """
        Còi hú mềm theo chu kỳ:
        - Quét êm 1400 -> 2400 -> 1400 Hz trong 0.8 giây.
        - Nghỉ 0.2 giây giữa hai nhịp để cảnh báo rõ nhưng không quá chói.
        - Fade âm lượng 80 ms ở đầu/cuối nhịp để tránh tiếng tạch.
        """
        update_interval = 0.02
        tone_duration = 0.8
        pause_duration = 0.2
        cycle_duration = tone_duration + pause_duration
        fade_duration = 0.08
        min_frequency = 1400
        max_frequency = 2400
        started_at = time.monotonic()

        while self._should_buzz:
            position = (time.monotonic() - started_at) % cycle_duration

            if position < tone_duration:
                phase = position / tone_duration
                frequency = min_frequency + (max_frequency - min_frequency) * (
                    0.5 - 0.5 * math.cos(2 * math.pi * phase)
                )
                fade_in = min(1.0, position / fade_duration)
                fade_out = min(1.0, (tone_duration - position) / fade_duration)
                volume = 0.5 * min(fade_in, fade_out)

                if self.has_hardware and self.mode == "pwm":
                    try:
                        self.buzzer.frequency = int(frequency)
                        self.buzzer.value = max(0.0, volume)
                    except Exception:
                        pass
                elif self.has_hardware:
                    self.buzzer.on()
            else:
                self._sound_off()

            time.sleep(update_interval)

        self._sound_off()
        with self._lock:
            self.is_buzzing = False

    def set_fire_led(self, has_fire: bool):
        """
        Điều khiển đèn LED cảnh báo lửa ở GPIO 27:
        - Đèn CHỈ SÁNG khi nhận diện được lửa trong khung hình.
        - Khi khung hình không còn nhận diện được lửa, đèn lập tức TẮT ngay.
        """
        if has_fire:
            self._led_on()
        else:
            self._led_off()

    def set_buzzer(self, has_fire: bool):
        """
        Điều khiển còi liên tục theo trạng thái nhận diện:
        - has_fire=True  : bắt đầu hú sóng sin (nếu chưa chạy)
        - has_fire=False : dừng ngay lập tức
        """
        if has_fire:
            with self._lock:
                if self.is_buzzing:
                    return  # đang chạy rồi, không spawn thêm
                self._should_buzz = True
                self.is_buzzing = True
            if not self.has_hardware:
                print("[CẢNH BÁO] >>> CÒI GIẢ LẬP: ĐANG HÚ CẢNH BÁO <<<")
            self._buzz_thread = threading.Thread(
                target=self._buzz_sine_worker, daemon=True, name="BuzzSine"
            )
            self._buzz_thread.start()
        else:
            self._should_buzz = False  # worker tự dừng sau 1 vòng

    def trigger(self):
        """
        [Legacy] Kích hoạt còi (giữ để tương thích). Dùng set_buzzer() cho chế độ mới.
        """
        now = time.time()

        # Kiểm tra cooldown còi
        if now - self.last_alert_time < config.ALERT_COOLDOWN:
            return False

        if self.is_buzzing:
            return False

        self.last_alert_time = now
        worker = threading.Thread(target=self._buzz_worker, daemon=True)
        worker.start()
        return True

    def cleanup(self):
        """Dọn dẹp tài nguyên khi tắt chương trình"""
        self._sound_off()
        self._led_off()
        if self.has_hardware:
            if hasattr(self, "buzzer") and self.buzzer:
                try:
                    self.buzzer.close()
                except Exception:
                    pass
            if hasattr(self, "led") and self.led:
                try:
                    self.led.close()
                except Exception:
                    pass
