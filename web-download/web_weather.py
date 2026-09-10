import time
import threading
import requests
import RPi.GPIO as GPIO

from gpiozero import Motor
from gpiozero.pins.lgpio import LGPIOFactory


# ==============================================================================
# CẤU HÌNH GPIO
# ==============================================================================

# ---------------- MOTOR DC - L298N ----------------
MOTOR_EN = 18       # ENA - PWM
MOTOR_IN1 = 23      # IN1
MOTOR_IN2 = 24      # IN2

# ---------------- ĐÈN / RELAY ----------------
LIGHT_PIN = 25


# ==============================================================================
# KHỞI TẠO GPIO ĐÈN
# ==============================================================================

try:
    GPIO.setmode(GPIO.BCM)

    GPIO.setup(
        LIGHT_PIN,
        GPIO.OUT,
        initial=GPIO.LOW
    )

    print(
        f"[OK] Đã khởi tạo đèn tại GPIO {LIGHT_PIN}"
    )

except Exception as e:
    print(
        f"[ERROR] Không thể khởi tạo GPIO đèn: {e}"
    )


# ==============================================================================
# KHỞI TẠO MOTOR
# ==============================================================================

motor = None

try:

    factory = LGPIOFactory()

    motor = Motor(
        forward=MOTOR_IN1,
        backward=MOTOR_IN2,
        enable=MOTOR_EN,
        pwm=True,
        pin_factory=factory
    )

    print(
        "[OK] Đã khởi tạo Motor DC"
    )

    print(
        f"     ENA = GPIO {MOTOR_EN}"
    )

    print(
        f"     IN1 = GPIO {MOTOR_IN1}"
    )

    print(
        f"     IN2 = GPIO {MOTOR_IN2}"
    )

except Exception as e:

    print(
        f"[ERROR] Không thể khởi tạo Motor: {e}"
    )

    motor = None


# ==============================================================================
# TRẠNG THÁI
# ==============================================================================

state = {
    "city": "",
    "temperature": None,
    "weather": "",
    "rain": False,

    "light_on": False,

    "motor_on": False,
    "motor_direction": "STOP",
    "motor_speed": 60
}

lock = threading.Lock()


# ==============================================================================
# ĐIỀU KHIỂN ĐÈN
# ==============================================================================

def control_light(raining):

    try:

        if raining:

            GPIO.output(
                LIGHT_PIN,
                GPIO.HIGH
            )

            with lock:
                state["light_on"] = True

            print(
                "💡 ĐÈN: BẬT"
            )

        else:

            GPIO.output(
                LIGHT_PIN,
                GPIO.LOW
            )

            with lock:
                state["light_on"] = False

            print(
                "💡 ĐÈN: TẮT"
            )

    except Exception as e:

        print(
            f"[ERROR ĐÈN] {e}"
        )


# ==============================================================================
# ĐIỀU KHIỂN MOTOR
# ==============================================================================

def control_motor(temperature):

    if motor is None:
        return

    try:

        # ==============================================================
        # NHIỆT ĐỘ > 30°C
        # ==============================================================
        if temperature > 30:

            speed = state["motor_speed"] / 100.0

            motor.forward(speed)

            with lock:

                state["motor_on"] = True
                state["motor_direction"] = "FORWARD"

            print(
                f"⚙️ MOTOR: QUAY THUẬN "
                f"({state['motor_speed']}%)"
            )

        # ==============================================================
        # NHIỆT ĐỘ <= 30°C
        # ==============================================================
        else:

            motor.stop()

            with lock:

                state["motor_on"] = False
                state["motor_direction"] = "STOP"

            print(
                "⚙️ MOTOR: DỪNG"
            )

    except Exception as e:

        print(
            f"[ERROR MOTOR] {e}"
        )


# ==============================================================================
# KIỂM TRA TRỜI MƯA
# ==============================================================================

def is_raining(weather_description, precip_mm):

    description = weather_description.lower()

    rain_keywords = [

        "rain",
        "drizzle",
        "shower",
        "thunderstorm",

        "mưa",
        "rainy",

        "light rain",
        "heavy rain"

    ]

    # Kiểm tra mô tả
    for keyword in rain_keywords:

        if keyword in description:

            return True

    # Kiểm tra lượng mưa
    try:

        if float(precip_mm) > 0:

            return True

    except:

        pass

    return False


# ==============================================================================
# LẤY THỜI TIẾT TỪ WEB
# ==============================================================================

def get_weather(city):

    try:

        url = f"https://wttr.in/{city}"

        params = {
            "format": "j1"
        }

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        print()
        print(
            f"🌐 Đang lấy thời tiết của: {city}"
        )

        response = requests.get(

            url,

            params=params,

            headers=headers,

            timeout=10

        )

        response.raise_for_status()

        data = response.json()

        current = data["current_condition"][0]

        # Nhiệt độ
        temperature = float(
            current["temp_C"]
        )

        # Mô tả thời tiết
        weather = current[
            "weatherDesc"
        ][0]["value"]

        # Lượng mưa
        precip_mm = float(
            current.get(
                "precipMM",
                0
            )
        )

        # Kiểm tra mưa
        rain = is_raining(
            weather,
            precip_mm
        )

        return {

            "temperature":
                temperature,

            "weather":
                weather,

            "precip_mm":
                precip_mm,

            "rain":
                rain

        }

    except requests.exceptions.RequestException as e:

        print()
        print(
            f"❌ Không thể kết nối Internet: {e}"
        )

        return None

    except Exception as e:

        print()
        print(
            f"❌ Lỗi lấy dữ liệu thời tiết: {e}"
        )

        return None


# ==============================================================================
# XỬ LÝ THỜI TIẾT
# ==============================================================================

def process_weather(city):

    weather_data = get_weather(city)

    if weather_data is None:

        return False

    temperature = weather_data[
        "temperature"
    ]

    weather = weather_data[
        "weather"
    ]

    precip_mm = weather_data[
        "precip_mm"
    ]

    rain = weather_data[
        "rain"
    ]


    # ==========================================================================
    # LƯU TRẠNG THÁI
    # ==========================================================================

    with lock:

        state["city"] = city

        state["temperature"] = temperature

        state["weather"] = weather

        state["rain"] = rain


    # ==========================================================================
    # HIỂN THỊ THÔNG TIN
    # ==========================================================================

    print()
    print("=" * 60)

    print(
        "              THÔNG TIN THỜI TIẾT"
    )

    print("=" * 60)

    print(
        f"📍 Thành phố : {city}"
    )

    print(
        f"🌡️ Nhiệt độ  : {temperature} °C"
    )

    print(
        f"🌤️ Thời tiết : {weather}"
    )

    print(
        f"💧 Lượng mưa : {precip_mm} mm"
    )

    if rain:

        print(
            "🌧️ Trời mưa  : CÓ"
        )

    else:

        print(
            "☀️ Trời mưa  : KHÔNG"
        )

    print("=" * 60)


    # ==========================================================================
    # ĐIỀU KHIỂN ĐÈN
    # ==========================================================================

    control_light(rain)


    # ==========================================================================
    # ĐIỀU KHIỂN MOTOR
    # ==========================================================================

    control_motor(temperature)


    print("=" * 60)

    return True


# ==============================================================================
# HIỂN THỊ TRẠNG THÁI
# ==============================================================================

def show_status():

    with lock:

        print()
        print("=" * 60)

        print(
            "                  TRẠNG THÁI"
        )

        print("=" * 60)

        print(
            f"📍 Thành phố : {state['city']}"
        )

        print(
            f"🌡️ Nhiệt độ  : "
            f"{state['temperature']} °C"
        )

        print(
            f"🌤️ Thời tiết : "
            f"{state['weather']}"
        )

        print(
            f"🌧️ Trời mưa  : "
            f"{'CÓ' if state['rain'] else 'KHÔNG'}"
        )

        print(
            f"💡 Đèn       : "
            f"{'BẬT' if state['light_on'] else 'TẮT'}"
        )

        print(
            f"⚙️ Motor     : "
            f"{'QUAY THUẬN' if state['motor_on'] else 'DỪNG'}"
        )

        print("=" * 60)


# ==============================================================================
# THREAD TỰ ĐỘNG CẬP NHẬT THỜI TIẾT
# ==============================================================================

def auto_weather_loop():

    while True:

        # Đợi 5 phút
        time.sleep(300)

        with lock:
            city = state["city"]

        if city:

            print()
            print(
                "🔄 Tự động cập nhật thời tiết..."
            )

            process_weather(city)


# ==============================================================================
# NHẬP THÀNH PHỐ
# ==============================================================================

def input_city():

    print()
    print("=" * 60)

    print(
        "       HỆ THỐNG ĐIỀU KHIỂN THEO THỜI TIẾT"
    )

    print("=" * 60)

    print()
    print(
        "Nhập tên thành phố để kiểm tra thời tiết."
    )

    print(
        "Ví dụ: Da Nang, Hanoi, Ho Chi Minh City"
    )

    print()

    while True:

        city = input(
            "📍 Nhập thành phố: "
        ).strip()

        if city:

            return city

        print(
            "⚠️ Vui lòng nhập tên thành phố!")


# ==============================================================================
# CHƯƠNG TRÌNH CHÍNH
# ==============================================================================

def main():

    try:

        # ----------------------------------------------------------------------
        # Nhập thành phố
        # ----------------------------------------------------------------------

        city = input_city()

        with lock:
            state["city"] = city


        # ----------------------------------------------------------------------
        # Lấy thời tiết lần đầu
        # ----------------------------------------------------------------------

        success = process_weather(
            city
        )

        if not success:

            print(
                "⚠️ Không lấy được thời tiết."
            )


        # ----------------------------------------------------------------------
        # Thread cập nhật tự động
        # ----------------------------------------------------------------------

        weather_thread = threading.Thread(

            target=auto_weather_loop,

            daemon=True

        )

        weather_thread.start()


        # ----------------------------------------------------------------------
        # Menu Terminal
        # ----------------------------------------------------------------------

        print()
        print("=" * 60)

        print(
            "                  MENU"
        )

        print("=" * 60)

        print(
            "1. Nhập thành phố mới"
        )

        print(
            "2. Cập nhật thời tiết ngay"
        )

        print(
            "3. Xem trạng thái"
        )

        print(
            "q. Thoát chương trình"
        )

        print("=" * 60)


        while True:

            command = input(
                "\n👉 Nhập lựa chọn: "
            ).strip().lower()


            # ==================================================================
            # NHẬP THÀNH PHỐ MỚI
            # ==================================================================

            if command == "1":

                new_city = input(
                    "📍 Nhập thành phố mới: "
                ).strip()

                if new_city:

                    with lock:
                        state["city"] = new_city

                    process_weather(
                        new_city
                    )

                else:

                    print(
                        "⚠️ Tên thành phố không được để trống."
                    )


            # ==================================================================
            # CẬP NHẬT NGAY
            # ==================================================================

            elif command == "2":

                with lock:
                    city = state["city"]

                process_weather(city)


            # ==================================================================
            # XEM TRẠNG THÁI
            # ==================================================================

            elif command == "3":

                show_status()


            # ==================================================================
            # THOÁT
            # ==================================================================

            elif command == "q":

                print()
                print(
                    "Đang dừng hệ thống..."
                )

                break


            else:

                print(
                    "⚠️ Lựa chọn không hợp lệ."
                )


    except KeyboardInterrupt:

        print()
        print(
            "\nĐã nhận Ctrl+C."
        )

    finally:

        print(
            "Đang tắt motor và đèn..."
        )

        # ----------------------------------------------------------------------
        # Dừng motor
        # ----------------------------------------------------------------------

        if motor:

            try:
                motor.stop()
                motor.close()

            except:
                pass


        # ----------------------------------------------------------------------
        # Tắt đèn
        # ----------------------------------------------------------------------

        try:

            GPIO.output(
                LIGHT_PIN,
                GPIO.LOW
            )

        except:
            pass


        # ----------------------------------------------------------------------
        # Cleanup GPIO
        # ----------------------------------------------------------------------

        try:

            GPIO.cleanup()

        except:
            pass


        print(
            "✅ Đã giải phóng GPIO."
        )

        print(
            "Chương trình kết thúc."
        )


# ==============================================================================
# START
# ==============================================================================

if __name__ == "__main__":

    main()
