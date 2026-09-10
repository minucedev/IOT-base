import time
import threading
import requests
import RPi.GPIO as GPIO

from gpiozero import Motor
from gpiozero.pins.lgpio import LGPIOFactory


# ============================================================
# API OPEN-METEO
# ============================================================

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


# ============================================================
# CẤU HÌNH GPIO
# ============================================================

# L298N
MOTOR_EN = 18
MOTOR_IN1 = 23
MOTOR_IN2 = 24

# Relay điều khiển đèn
LIGHT_PIN = 25

# Tốc độ motor
MOTOR_SPEED = 60

# Thời gian cập nhật tự động
UPDATE_INTERVAL = 300


# ============================================================
# KHỞI TẠO GPIO
# ============================================================

GPIO.setmode(GPIO.BCM)

GPIO.setup(
    LIGHT_PIN,
    GPIO.OUT,
    initial=GPIO.LOW
)


# ============================================================
# KHỞI TẠO MOTOR
# ============================================================

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

    print("-> [OK] Khởi tạo Motor DC thành công.")

except Exception as e:

    print(
        f"-> [LOI] Không thể khởi tạo Motor: {e}"
    )


# ============================================================
# TRẠNG THÁI
# ============================================================

state = {

    "city": "",

    "latitude": None,
    "longitude": None,

    "temperature": None,

    "weather_code": None,
    "weather_description": "",

    "rain_mm": 0.0,
    "precipitation_mm": 0.0,

    "is_raining": False,

    "pm10": None,
    "pm2_5": None,

    "us_aqi": None,

    "light": False,
    "motor": False
}

lock = threading.Lock()


# ============================================================
# WEATHER CODE → MÔ TẢ
# ============================================================

def weather_description(code):

    descriptions = {

        0: "Trời quang",

        1: "Chủ yếu quang",
        2: "Mây rải rác",
        3: "Nhiều mây",

        45: "Sương mù",
        48: "Sương mù đóng băng",

        51: "Mưa phùn nhẹ",
        53: "Mưa phùn vừa",
        55: "Mưa phùn mạnh",

        56: "Mưa phùn lạnh nhẹ",
        57: "Mưa phùn lạnh mạnh",

        61: "Mưa nhẹ",
        63: "Mưa vừa",
        65: "Mưa to",

        66: "Mưa lạnh nhẹ",
        67: "Mưa lạnh mạnh",

        71: "Tuyết nhẹ",
        73: "Tuyết vừa",
        75: "Tuyết to",

        77: "Hạt tuyết",

        80: "Mưa rào nhẹ",
        81: "Mưa rào vừa",
        82: "Mưa rào mạnh",

        85: "Mưa tuyết nhẹ",
        86: "Mưa tuyết mạnh",

        95: "Dông",

        96: "Dông có mưa đá",
        99: "Dông có mưa đá mạnh"
    }

    return descriptions.get(
        int(code),
        "Không xác định"
    )


# ============================================================
# KIỂM TRA WEATHER CODE CÓ PHẢI MƯA
# ============================================================

def check_rain(weather_code, rain_mm):

    code = int(weather_code)

    # Các mã WMO liên quan đến mưa/dông
    rain_codes = (

        list(range(51, 68))

        + list(range(80, 83))

        + list(range(95, 100))
    )

    if code in rain_codes:
        return True

    if rain_mm > 0:
        return True

    return False


# ============================================================
# TÌM THÀNH PHỐ
# ============================================================

def find_city(city):

    params = {

        "name": city,

        "count": 10,

        "language": "vi",

        "format": "json",

        # Chỉ tìm Việt Nam
        "countryCode": "VN"
    }

    try:

        print()
        print(
            f"🔎 Đang tìm thành phố: {city}"
        )

        response = requests.get(

            GEOCODING_URL,

            params=params,

            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        results = data.get(
            "results",
            []
        )

        if not results:

            print(
                "❌ Không tìm thấy thành phố."
            )

            return None


        # ====================================================
        # NẾU CÓ NHIỀU KẾT QUẢ
        # ====================================================

        if len(results) > 1:

            print()
            print(
                "Các địa điểm tìm được:"
            )

            for i, item in enumerate(
                results[:10],
                start=1
            ):

                name = item.get(
                    "name",
                    ""
                )

                admin1 = item.get(
                    "admin1",
                    ""
                )

                country = item.get(
                    "country",
                    ""
                )

                print(
                    f"{i}. {name}, "
                    f"{admin1}, "
                    f"{country}"
                )


            while True:

                try:

                    choice = int(
                        input(
                            "👉 Chọn địa điểm: "
                        )
                    )

                    if 1 <= choice <= min(
                        10,
                        len(results)
                    ):

                        location = results[
                            choice - 1
                        ]

                        break

                except ValueError:
                    pass

                print(
                    "⚠️ Lựa chọn không hợp lệ."
                )

        else:

            location = results[0]


        latitude = location[
            "latitude"
        ]

        longitude = location[
            "longitude"
        ]

        name = location.get(
            "name",
            city
        )

        country = location.get(
            "country",
            ""
        )

        admin1 = location.get(
            "admin1",
            ""
        )


        print()
        print(
            "✅ Đã xác định thành phố:"
        )

        print(
            f"   Thành phố : {name}"
        )

        print(
            f"   Tỉnh      : {admin1}"
        )

        print(
            f"   Quốc gia  : {country}"
        )

        print(
            f"   Latitude  : {latitude}"
        )

        print(
            f"   Longitude : {longitude}"
        )


        return {

            "name": name,

            "country": country,

            "admin1": admin1,

            "latitude": latitude,

            "longitude": longitude
        }


    except Exception as e:

        print(
            f"❌ Lỗi tìm thành phố: {e}"
        )

        return None


# ============================================================
# LẤY THỜI TIẾT
# SỬ DỤNG WEATHER_URL
# ============================================================

def get_weather(latitude, longitude):

    params = {

        "latitude": latitude,

        "longitude": longitude,

        "current": (
            "temperature_2m,"
            "weather_code,"
            "rain,"
            "precipitation"
        ),

        "timezone": "auto"
    }


    try:

        response = requests.get(

            WEATHER_URL,

            params=params,

            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        current = data.get(
            "current"
        )

        if not current:

            print(
                "❌ Không có dữ liệu thời tiết."
            )

            return None


        temperature = float(
            current[
                "temperature_2m"
            ]
        )

        weather_code = int(
            current[
                "weather_code"
            ]
        )

        rain_mm = float(
            current.get(
                "rain",
                0
            )
        )

        precipitation_mm = float(
            current.get(
                "precipitation",
                0
            )
        )


        raining = check_rain(

            weather_code,

            rain_mm
        )


        return {

            "temperature": temperature,

            "weather_code": weather_code,

            "description":
                weather_description(
                    weather_code
                ),

            "rain_mm": rain_mm,

            "precipitation_mm":
                precipitation_mm,

            "is_raining": raining
        }


    except Exception as e:

        print(
            f"❌ Lỗi WEATHER API: {e}"
        )

        return None


# ============================================================
# LẤY CHẤT LƯỢNG KHÔNG KHÍ
# SỬ DỤNG AIR_URL
# ============================================================

def get_air_quality(latitude, longitude):

    params = {

        "latitude": latitude,

        "longitude": longitude,

        "current": (
            "pm10,"
            "pm2_5,"
            "us_aqi"
        ),

        "timezone": "auto"
    }


    try:

        response = requests.get(

            AIR_URL,

            params=params,

            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        current = data.get(
            "current"
        )

        if not current:

            print(
                "❌ Không có dữ liệu chất lượng không khí."
            )

            return None


        pm10 = current.get(
            "pm10"
        )

        pm2_5 = current.get(
            "pm2_5"
        )

        us_aqi = current.get(
            "us_aqi"
        )


        return {

            "pm10": pm10,

            "pm2_5": pm2_5,

            "us_aqi": us_aqi
        }


    except Exception as e:

        print(
            f"❌ Lỗi AIR QUALITY API: {e}"
        )

        return None


# ============================================================
# ĐIỀU KHIỂN ĐÈN
# ============================================================

def control_light(is_raining):

    try:

        if is_raining:

            GPIO.output(
                LIGHT_PIN,
                GPIO.HIGH
            )

            with lock:
                state["light"] = True

            print(
                "💡 ĐÈN: BẬT"
            )

        else:

            GPIO.output(
                LIGHT_PIN,
                GPIO.LOW
            )

            with lock:
                state["light"] = False

            print(
                "💡 ĐÈN: TẮT"
            )


    except Exception as e:

        print(
            f"❌ Lỗi điều khiển đèn: {e}"
        )


# ============================================================
# ĐIỀU KHIỂN MOTOR
# ============================================================

def control_motor(temperature):

    if motor is None:

        return


    try:

        # ====================================================
        # NHIỆT ĐỘ > 30°C
        # ====================================================

        if temperature > 30:

            speed = (
                MOTOR_SPEED / 100
            )

            motor.forward(
                speed
            )

            with lock:
                state["motor"] = True

            print(
                f"⚙️ MOTOR: "
                f"QUAY THUẬN "
                f"({MOTOR_SPEED}%)"
            )


        # ====================================================
        # NHIỆT ĐỘ <= 30°C
        # ====================================================

        else:

            motor.stop()

            with lock:
                state["motor"] = False

            print(
                "⚙️ MOTOR: DỪNG"
            )


    except Exception as e:

        print(
            f"❌ Lỗi motor: {e}"
        )


# ============================================================
# HIỂN THỊ THÔNG TIN
# ============================================================

def display_information(
    location,
    weather,
    air
):

    print()
    print("=" * 65)

    print(
        "                 THÔNG TIN THỜI TIẾT"
    )

    print("=" * 65)


    print(
        f"📍 Thành phố   : "
        f"{location['name']}"
    )

    print(
        f"📌 Tọa độ      : "
        f"{location['latitude']}, "
        f"{location['longitude']}"
    )


    print(
        f"🌡️ Nhiệt độ    : "
        f"{weather['temperature']:.1f} °C"
    )

    print(
        f"🌤️ Thời tiết   : "
        f"{weather['description']}"
    )

    print(
        f"🔢 WeatherCode : "
        f"{weather['weather_code']}"
    )

    print(
        f"💧 Lượng mưa   : "
        f"{weather['rain_mm']:.2f} mm"
    )

    print(
        f"☔ Lượng mưa TP: "
        f"{weather['precipitation_mm']:.2f} mm"
    )


    if weather["is_raining"]:

        print(
            "🌧️ Trời mưa    : CÓ"
        )

    else:

        print(
            "☀️ Trời mưa    : KHÔNG"
        )


    # ========================================================
    # AIR QUALITY
    # ========================================================

    print()
    print(
        "              CHẤT LƯỢNG KHÔNG KHÍ"
    )

    print("-" * 65)


    if air:

        print(
            f"🌫️ PM2.5       : "
            f"{air['pm2_5']} µg/m³"
        )

        print(
            f"🌫️ PM10        : "
            f"{air['pm10']} µg/m³"
        )

        print(
            f"📊 US AQI      : "
            f"{air['us_aqi']}"
        )

    else:

        print(
            "❌ Không lấy được dữ liệu không khí."
        )


    # ========================================================
    # THIẾT BỊ
    # ========================================================

    print()
    print(
        "                 ĐIỀU KHIỂN THIẾT BỊ"
    )

    print("-" * 65)


    print(
        f"💡 ĐÈN         : "
        f"{'BẬT' if state['light'] else 'TẮT'}"
    )

    print(
        f"⚙️ MOTOR       : "
        f"{'QUAY THUẬN' if state['motor'] else 'DỪNG'}"
    )


    print("=" * 65)


# ============================================================
# CẬP NHẬT THỜI TIẾT
# ============================================================

def update_weather(location):

    print()
    print(
        "🌐 Đang cập nhật dữ liệu..."
    )


    # ========================================================
    # WEATHER
    # ========================================================

    weather = get_weather(

        location["latitude"],

        location["longitude"]
    )

    if weather is None:

        return False


    # ========================================================
    # AIR QUALITY
    # ========================================================

    air = get_air_quality(

        location["latitude"],

        location["longitude"]
    )


    # ========================================================
    # LƯU STATE
    # ========================================================

    with lock:

        state["city"] = \
            location["name"]

        state["latitude"] = \
            location["latitude"]

        state["longitude"] = \
            location["longitude"]

        state["temperature"] = \
            weather["temperature"]

        state["weather_code"] = \
            weather["weather_code"]

        state["weather_description"] = \
            weather["description"]

        state["rain_mm"] = \
            weather["rain_mm"]

        state["precipitation_mm"] = \
            weather["precipitation_mm"]

        state["is_raining"] = \
            weather["is_raining"]


        if air:

            state["pm10"] = \
                air["pm10"]

            state["pm2_5"] = \
                air["pm2_5"]

            state["us_aqi"] = \
                air["us_aqi"]


    # ========================================================
    # HIỂN THỊ
    # ========================================================

    display_information(

        location,

        weather,

        air
    )


    # ========================================================
    # ĐIỀU KHIỂN ĐÈN
    # ========================================================

    control_light(
        weather["is_raining"]
    )


    # ========================================================
    # ĐIỀU KHIỂN MOTOR
    # ========================================================

    control_motor(
        weather["temperature"]
    )


    return True


# ============================================================
# CHẾ ĐỘ TEST
# ============================================================

def test_mode():

    print()
    print("=" * 65)

    print(
        "                       CHẾ ĐỘ TEST"
    )

    print("=" * 65)

    print(
        "Dùng để kiểm tra phần cứng."
    )

    print()


    # --------------------------------------------------------
    # NHIỆT ĐỘ
    # --------------------------------------------------------

    while True:

        try:

            temperature = float(
                input(
                    "🌡️ Nhập nhiệt độ (°C): "
                )
            )

            break

        except ValueError:

            print(
                "⚠️ Vui lòng nhập số."
            )


    # --------------------------------------------------------
    # MƯA
    # --------------------------------------------------------

    while True:

        rain = input(
            "🌧️ Có mưa không? (y/n): "
        ).lower().strip()


        if rain == "y":

            is_raining = True
            break


        if rain == "n":

            is_raining = False
            break


        print(
            "⚠️ Chỉ nhập y hoặc n."
        )


    print()
    print("=" * 65)

    print(
        f"🌡️ Nhiệt độ : "
        f"{temperature} °C"
    )

    print(
        f"🌧️ Mưa      : "
        f"{'CÓ' if is_raining else 'KHÔNG'}"
    )

    print("=" * 65)


    # Điều khiển theo điều kiện đề bài

    control_light(
        is_raining
    )

    control_motor(
        temperature
    )


# ============================================================
# HIỂN THỊ STATUS
# ============================================================

def show_status():

    with lock:

        print()
        print("=" * 65)

        print(
            "                    TRẠNG THÁI"
        )

        print("=" * 65)

        print(
            f"📍 Thành phố : "
            f"{state['city']}"
        )

        print(
            f"🌡️ Nhiệt độ  : "
            f"{state['temperature']} °C"
        )

        print(
            f"🌤️ Thời tiết : "
            f"{state['weather_description']}"
        )

        print(
            f"🌧️ Trời mưa  : "
            f"{'CÓ' if state['is_raining'] else 'KHÔNG'}"
        )

        print(
            f"💡 Đèn       : "
            f"{'BẬT' if state['light'] else 'TẮT'}"
        )

        print(
            f"⚙️ Motor     : "
            f"{'QUAY THUẬN' if state['motor'] else 'DỪNG'}"
        )

        print()

        print(
            f"🌫️ PM2.5     : "
            f"{state['pm2_5']}"
        )

        print(
            f"🌫️ PM10      : "
            f"{state['pm10']}"
        )

        print(
            f"📊 US AQI    : "
            f"{state['us_aqi']}"
        )

        print("=" * 65)


# ============================================================
# TỰ ĐỘNG CẬP NHẬT
# ============================================================

def auto_update():

    while True:

        time.sleep(
            UPDATE_INTERVAL
        )

        with lock:

            city = state["city"]

            latitude = state[
                "latitude"
            ]

            longitude = state[
                "longitude"
            ]


        if city:

            print()
            print(
                "🔄 TỰ ĐỘNG CẬP NHẬT..."
            )


            location = {

                "name": city,

                "latitude":
                    latitude,

                "longitude":
                    longitude
            }


            update_weather(
                location
            )


# ============================================================
# NHẬP THÀNH PHỐ
# ============================================================

def input_city():

    while True:

        city = input(
            "\n📍 Nhập thành phố: "
        ).strip()


        if not city:

            print(
                "⚠️ Không được bỏ trống."
            )

            continue


        location = find_city(
            city
        )


        if location:

            return location


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 65)

    print(
        "       HỆ THỐNG ĐIỀU KHIỂN THEO THỜI TIẾT"
    )

    print("=" * 65)

    print(
        "Weather API : Open-Meteo"
    )

    print(
        "Air API     : Open-Meteo Air Quality"
    )

    print()

    print(
        "Điều kiện:"
    )

    print(
        "  🌧️ Có mưa       → ĐÈN BẬT"
    )

    print(
        "  ☀️ Không mưa    → ĐÈN TẮT"
    )

    print(
        "  🌡️ > 30°C       → MOTOR QUAY THUẬN"
    )

    print(
        "  🌡️ <= 30°C      → MOTOR DỪNG"
    )

    print("=" * 65)


    # ========================================================
    # NHẬP THÀNH PHỐ
    # ========================================================

    location = input_city()


    # ========================================================
    # LẤY DỮ LIỆU LẦN ĐẦU
    # ========================================================

    update_weather(
        location
    )


    # ========================================================
    # THREAD TỰ ĐỘNG
    # ========================================================

    threading.Thread(

        target=auto_update,

        daemon=True

    ).start()


    # ========================================================
    # MENU
    # ========================================================

    while True:

        print()
        print("=" * 65)

        print(
            "                         MENU"
        )

        print("=" * 65)

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
            "4. Chế độ TEST phần cứng"
        )

        print(
            "q. Thoát"
        )

        print("=" * 65)


        try:

            choice = input(
                "👉 Nhập lựa chọn: "
            ).strip().lower()

        except KeyboardInterrupt:

            break


        # ----------------------------------------------------
        # THÀNH PHỐ MỚI
        # ----------------------------------------------------

        if choice == "1":

            location = input_city()

            update_weather(
                location
            )


        # ----------------------------------------------------
        # CẬP NHẬT
        # ----------------------------------------------------

        elif choice == "2":

            update_weather(
                location
            )


        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        elif choice == "3":

            show_status()


        # ----------------------------------------------------
        # TEST
        # ----------------------------------------------------

        elif choice == "4":

            test_mode()


        # ----------------------------------------------------
        # THOÁT
        # ----------------------------------------------------

        elif choice == "q":

            break


        else:

            print(
                "⚠️ Lựa chọn không hợp lệ."
            )


# ============================================================
# CLEANUP
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\n🛑 Đang dừng chương trình..."
        )

    finally:

        print(
            "⚙️ Đang dừng motor..."
        )

        if motor:

            try:

                motor.stop()
                motor.close()

            except:
                pass


        print(
            "💡 Đang tắt đèn..."
        )

        try:

            GPIO.output(
                LIGHT_PIN,
                GPIO.LOW
            )

        except:
            pass


        GPIO.cleanup()

        print(
            "✅ Đã giải phóng GPIO."
        )

        print(
            "👋 Kết thúc chương trình."
        )