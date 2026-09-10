import time
import requests
from gpiozero import LED, Motor
from gpiozero.pins.lgpio import LGPIOFactory


# ============================================================
# CẤU HÌNH API
# ============================================================

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


# ============================================================
# CẤU HÌNH GPIO
# ============================================================

# ---------------- MOTOR DC - L298N ----------------
MOTOR_EN = 18
MOTOR_IN1 = 23
MOTOR_IN2 = 24

# ---------------- ĐÈN ----------------
LED_PIN = 22


# ============================================================
# NGƯỠNG ĐIỀU KHIỂN
# ============================================================

# Nếu nhiệt độ > 30 độ C:
#     Motor quay thuận
#
# Nếu nhiệt độ <= 30 độ C:
#     Motor dừng

TEMPERATURE_LIMIT = 30.0


# ============================================================
# THỜI GIAN CẬP NHẬT
# ============================================================

UPDATE_INTERVAL = 60       # cập nhật mỗi 60 giây


# ============================================================
# TỌA ĐỘ CÁC THÀNH PHỐ
#
# Không cần gọi Geocoding API đối với các thành phố này.
# ============================================================

CITY_COORDS = {

    # --------------------------------------------------------
    # ĐÀ NẴNG
    # --------------------------------------------------------

    "da nang": {
        "name": "Đà Nẵng",
        "latitude": 16.0544,
        "longitude": 108.2022
    },

    "danang": {
        "name": "Đà Nẵng",
        "latitude": 16.0544,
        "longitude": 108.2022
    },

    "đà nẵng": {
        "name": "Đà Nẵng",
        "latitude": 16.0544,
        "longitude": 108.2022
    },


    # --------------------------------------------------------
    # HÀ NỘI
    # --------------------------------------------------------

    "ha noi": {
        "name": "Hà Nội",
        "latitude": 21.0285,
        "longitude": 105.8542
    },

    "hanoi": {
        "name": "Hà Nội",
        "latitude": 21.0285,
        "longitude": 105.8542
    },

    "hà nội": {
        "name": "Hà Nội",
        "latitude": 21.0285,
        "longitude": 105.8542
    },


    # --------------------------------------------------------
    # TP HỒ CHÍ MINH
    # --------------------------------------------------------

    "ho chi minh": {
        "name": "TP. Hồ Chí Minh",
        "latitude": 10.8231,
        "longitude": 106.6297
    },

    "ho chi minh city": {
        "name": "TP. Hồ Chí Minh",
        "latitude": 10.8231,
        "longitude": 106.6297
    },

    "hồ chí minh": {
        "name": "TP. Hồ Chí Minh",
        "latitude": 10.8231,
        "longitude": 106.6297
    },

    "tphcm": {
        "name": "TP. Hồ Chí Minh",
        "latitude": 10.8231,
        "longitude": 106.6297
    },

    "sai gon": {
        "name": "TP. Hồ Chí Minh",
        "latitude": 10.8231,
        "longitude": 106.6297
    },

    "sài gòn": {
        "name": "TP. Hồ Chí Minh",
        "latitude": 10.8231,
        "longitude": 106.6297
    },


    # --------------------------------------------------------
    # CẦN THƠ
    # --------------------------------------------------------

    "can tho": {
        "name": "Cần Thơ",
        "latitude": 10.0452,
        "longitude": 105.7469
    },

    "cần thơ": {
        "name": "Cần Thơ",
        "latitude": 10.0452,
        "longitude": 105.7469
    },


    # --------------------------------------------------------
    # HẢI PHÒNG
    # --------------------------------------------------------

    "hai phong": {
        "name": "Hải Phòng",
        "latitude": 20.8449,
        "longitude": 106.6881
    },

    "hải phòng": {
        "name": "Hải Phòng",
        "latitude": 20.8449,
        "longitude": 106.6881
    },


    # --------------------------------------------------------
    # HUẾ
    # --------------------------------------------------------

    "hue": {
        "name": "Huế",
        "latitude": 16.4637,
        "longitude": 107.5909
    },

    "huế": {
        "name": "Huế",
        "latitude": 16.4637,
        "longitude": 107.5909
    },


    # --------------------------------------------------------
    # NHA TRANG
    # --------------------------------------------------------

    "nha trang": {
        "name": "Nha Trang",
        "latitude": 12.2388,
        "longitude": 109.1967
    },


    # --------------------------------------------------------
    # ĐÀ LẠT
    # --------------------------------------------------------

    "da lat": {
        "name": "Đà Lạt",
        "latitude": 11.9404,
        "longitude": 108.4583
    },

    "đà lạt": {
        "name": "Đà Lạt",
        "latitude": 11.9404,
        "longitude": 108.4583
    },


    # --------------------------------------------------------
    # VŨNG TÀU
    # --------------------------------------------------------

    "vung tau": {
        "name": "Vũng Tàu",
        "latitude": 10.4114,
        "longitude": 107.1362
    },

    "vũng tàu": {
        "name": "Vũng Tàu",
        "latitude": 10.4114,
        "longitude": 107.1362
    },


    # --------------------------------------------------------
    # DUBAI
    # --------------------------------------------------------

    "dubai": {
        "name": "Dubai",
        "latitude": 25.2048,
        "longitude": 55.2708
    },

    "dubai city": {
        "name": "Dubai",
        "latitude": 25.2048,
        "longitude": 55.2708
    }

}

# ============================================================
# KHỞI TẠO GPIO
# ============================================================

print("==============================================")
print("        KHỞI TẠO PHẦN CỨNG")
print("==============================================")


try:

    factory = LGPIOFactory()

    print("✅ LGPIOFactory: OK")

except Exception as e:

    print("❌ Không thể khởi tạo LGPIOFactory")

    print(e)

    factory = None


# ============================================================
# KHỞI TẠO MOTOR
# ============================================================

motor = None

try:

    motor = Motor(
        forward=MOTOR_IN1,
        backward=MOTOR_IN2,
        enable=MOTOR_EN,
        pwm=True,
        pin_factory=factory
    )

    print(
        f"✅ Motor DC: OK "
        f"(ENA={MOTOR_EN}, "
        f"IN1={MOTOR_IN1}, "
        f"IN2={MOTOR_IN2})"
    )

except Exception as e:

    print("❌ Lỗi khởi tạo Motor:")

    print(e)


# ============================================================
# KHỞI TẠO LED
# ============================================================

led = None

try:

    led = LED(
        LED_PIN,
        pin_factory=factory
    )

    led.off()

    print(
        f"✅ LED: OK (GPIO {LED_PIN})"
    )

except Exception as e:

    print("❌ Lỗi khởi tạo LED:")

    print(e)


# ============================================================
# TRẠNG THÁI HỆ THỐNG
# ============================================================

system_state = {

    "city": "",

    "latitude": 0.0,

    "longitude": 0.0,

    "temperature": 0.0,

    "rain": 0.0,

    "weather_code": -1,

    "weather_description": "",

    "is_raining": False,

    "pm25": None,

    "pm10": None,

    "us_aqi": None,

    "led_on": False,

    "motor_on": False,

    "motor_direction": "STOP",

    "last_update": ""
}


# ============================================================
# CHUYỂN WEATHER CODE THÀNH MÔ TẢ
# ============================================================

def weather_description(code):

    """
    Open-Meteo sử dụng WMO Weather Code.

    Một số mã quan trọng:

    0       = Trời quang
    1-3     = Có mây
    45-48   = Sương mù
    51-57   = Mưa phùn
    61-67   = Mưa
    71-77   = Tuyết
    80-82   = Mưa rào
    85-86   = Tuyết rào
    95      = Dông
    96-99   = Dông có mưa đá
    """

    descriptions = {

        0: "Trời quang",

        1: "Chủ yếu quang",

        2: "Có mây",

        3: "Nhiều mây",

        45: "Sương mù",

        48: "Sương mù đóng băng",

        51: "Mưa phùn nhẹ",

        53: "Mưa phùn vừa",

        55: "Mưa phùn mạnh",

        56: "Mưa phùn đóng băng nhẹ",

        57: "Mưa phùn đóng băng mạnh",

        61: "Mưa nhẹ",

        63: "Mưa vừa",

        65: "Mưa lớn",

        66: "Mưa đóng băng nhẹ",

        67: "Mưa đóng băng mạnh",

        71: "Tuyết nhẹ",

        73: "Tuyết vừa",

        75: "Tuyết lớn",

        77: "Hạt tuyết",

        80: "Mưa rào nhẹ",

        81: "Mưa rào vừa",

        82: "Mưa rào mạnh",

        85: "Tuyết rào nhẹ",

        86: "Tuyết rào mạnh",

        95: "Dông",

        96: "Dông có mưa đá nhẹ",

        99: "Dông có mưa đá mạnh"
    }

    return descriptions.get(
        code,
        "Không xác định"
    )


# ============================================================
# KIỂM TRA CÓ MƯA HAY KHÔNG
# ============================================================

def check_rain(weather_code, rain):

    """
    Xác định trời mưa dựa trên:

    1. Lượng mưa > 0

    HOẶC

    2. Weather Code thuộc nhóm mưa.
    """

    # Nếu lượng mưa lớn hơn 0 mm
    if rain is not None and rain > 0:

        return True


    # Các mã thời tiết có mưa
    rain_codes = {

        51,
        53,
        55,
        56,
        57,

        61,
        63,
        65,
        66,
        67,

        80,
        81,
        82,

        95,
        96,
        99
    }


    if weather_code in rain_codes:

        return True


    return False


# ============================================================
# TÌM THÀNH PHỐ
# ============================================================

def find_city(city):

    city_key = city.strip().lower()

    if city_key == "":

        return None


    # --------------------------------------------------------
    # Tìm trong danh sách thành phố
    # --------------------------------------------------------

    if city_key in CITY_COORDS:

        location = CITY_COORDS[city_key]

        print()

        print("✅ Đã tìm thấy thành phố.")

        print(
            f"   Thành phố : "
            f"{location['name']}"
        )

        print(
            f"   Latitude  : "
            f"{location['latitude']}"
        )

        print(
            f"   Longitude : "
            f"{location['longitude']}"
        )

        return location


    # --------------------------------------------------------
    # Không tìm thấy
    # --------------------------------------------------------

    print()

    print(
        f"❌ Chưa có tọa độ cho "
        f"'{city}'."
    )

    print()

    print(
        "Các thành phố đang hỗ trợ:"
    )

    supported = set()

    for value in CITY_COORDS.values():

        supported.add(
            value["name"]
        )

    for name in sorted(supported):

        print(
            f"   - {name}"
        )

    return None


# ============================================================
# LẤY THỜI TIẾT
# ============================================================

def get_weather(location):

    latitude = location["latitude"]

    longitude = location["longitude"]


    # --------------------------------------------------------
    # Tham số gửi cho Open-Meteo
    # --------------------------------------------------------

    params = {

        "latitude": latitude,

        "longitude": longitude,

        "current": (
            "temperature_2m,"
            "rain,"
            "precipitation,"
            "weather_code"
        ),

        "timezone": "Asia/Ho_Chi_Minh"
    }


    print()

    print("🌐 Đang lấy dữ liệu thời tiết...")

    print(
        f"   URL: {WEATHER_URL}"
    )


    try:

        response = requests.get(

            WEATHER_URL,

            params=params,

            timeout=15
        )


        response.raise_for_status()


        data = response.json()


        # ----------------------------------------------------
        # Lấy phần current
        # ----------------------------------------------------

        current = data.get(
            "current",
            {}
        )


        temperature = current.get(
            "temperature_2m"
        )


        rain = current.get(
            "rain",
            0
        )


        precipitation = current.get(
            "precipitation",
            0
        )


        weather_code = current.get(
            "weather_code"
        )


        if temperature is None:

            print(
                "❌ API không trả về nhiệt độ."
            )

            return None


        # ----------------------------------------------------
        # Kiểm tra mưa
        # ----------------------------------------------------

        is_raining = check_rain(

            weather_code,

            rain
        )


        result = {

            "temperature":
                float(temperature),

            "rain":
                float(rain or 0),

            "precipitation":
                float(precipitation or 0),

            "weather_code":
                weather_code,

            "description":
                weather_description(
                    weather_code
                ),

            "is_raining":
                is_raining
        }


        print(
            "✅ Lấy thời tiết thành công."
        )


        return result


    except requests.exceptions.Timeout:

        print()

        print(
            "❌ API thời tiết bị TIMEOUT."
        )

        print(
            "   Kiểm tra kết nối Internet "
            "của Raspberry Pi."
        )

        return None


    except requests.exceptions.ConnectionError:

        print()

        print(
            "❌ Không thể kết nối tới "
            "Open-Meteo."
        )

        return None


    except requests.exceptions.HTTPError as e:

        print()

        print(
            f"❌ HTTP Error: {e}"
        )

        return None


    except Exception as e:

        print()

        print(
            f"❌ Lỗi lấy thời tiết: {e}"
        )

        return None


# ============================================================
# LẤY CHẤT LƯỢNG KHÔNG KHÍ
# ============================================================

def get_air_quality(location):

    latitude = location["latitude"]

    longitude = location["longitude"]


    params = {

        "latitude": latitude,

        "longitude": longitude,

        "current": (
            "pm10,"
            "pm2_5,"
            "us_aqi"
        ),

        "timezone": "Asia/Ho_Chi_Minh"
    }


    print()

    print(
        "🌐 Đang lấy dữ liệu chất lượng không khí..."
    )


    try:

        response = requests.get(

            AIR_URL,

            params=params,

            timeout=15
        )


        response.raise_for_status()


        data = response.json()


        current = data.get(
            "current",
            {}
        )


        pm25 = current.get(
            "pm2_5"
        )


        pm10 = current.get(
            "pm10"
        )


        us_aqi = current.get(
            "us_aqi"
        )


        print(
            "✅ Lấy dữ liệu không khí thành công."
        )


        return {

            "pm25": pm25,

            "pm10": pm10,

            "us_aqi": us_aqi
        }


    except requests.exceptions.Timeout:

        print(
            "⚠️ API không khí bị timeout."
        )

        return {

            "pm25": None,

            "pm10": None,

            "us_aqi": None
        }


    except Exception as e:

        print(
            f"⚠️ Không lấy được dữ liệu "
            f"không khí: {e}"
        )

        return {

            "pm25": None,

            "pm10": None,

            "us_aqi": None
        }


# ============================================================
# ĐIỀU KHIỂN LED
# ============================================================

def control_led(is_raining):

    if led is None:

        return


    try:

        if is_raining:

            led.on()

            system_state["led_on"] = True

            print(
                "💡 ĐÈN: BẬT "
                "(TRỜI ĐANG MƯA)"
            )

        else:

            led.off()

            system_state["led_on"] = False

            print(
                "💡 ĐÈN: TẮT "
                "(KHÔNG MƯA)"
            )


    except Exception as e:

        print(
            f"❌ Lỗi điều khiển LED: {e}"
        )


# ============================================================
# ĐIỀU KHIỂN MOTOR
# ============================================================

def control_motor(temperature):

    if motor is None:

        return


    try:

        # ----------------------------------------------------
        # NHIỆT ĐỘ > 30°C
        # ----------------------------------------------------

        if temperature > TEMPERATURE_LIMIT:

            # Motor quay thuận
            motor.forward(
                0.6
            )

            system_state["motor_on"] = True

            system_state[
                "motor_direction"
            ] = "FORWARD"


            print(
                "⚙️ MOTOR: QUAY THUẬN "
                "(NHIỆT ĐỘ > 30°C)"
            )


        # ----------------------------------------------------
        # NHIỆT ĐỘ <= 30°C
        # ----------------------------------------------------

        else:

            motor.stop()

            system_state["motor_on"] = False

            system_state[
                "motor_direction"
            ] = "STOP"


            print(
                "⚙️ MOTOR: DỪNG "
                "(NHIỆT ĐỘ <= 30°C)"
            )


    except Exception as e:

        print(
            f"❌ Lỗi điều khiển Motor: {e}"
        )


# ============================================================
# CẬP NHẬT HỆ THỐNG
# ============================================================

def update_system(location):

    print()

    print(
        "============================================================"
    )

    print(
        "                 CẬP NHẬT DỮ LIỆU"
    )

    print(
        "============================================================"
    )


    # --------------------------------------------------------
    # Lấy thời tiết
    # --------------------------------------------------------

    weather = get_weather(
        location
    )


    if weather is None:

        print()

        print(
            "❌ Không thể cập nhật hệ thống."
        )

        return False


    # --------------------------------------------------------
    # Lấy chất lượng không khí
    # --------------------------------------------------------

    air = get_air_quality(
        location
    )


    # --------------------------------------------------------
    # Lưu trạng thái
    # --------------------------------------------------------

    system_state["city"] = location[
        "name"
    ]

    system_state["latitude"] = location[
        "latitude"
    ]

    system_state["longitude"] = location[
        "longitude"
    ]

    system_state["temperature"] = weather[
        "temperature"
    ]

    system_state["rain"] = weather[
        "rain"
    ]

    system_state["weather_code"] = weather[
        "weather_code"
    ]

    system_state["weather_description"] = weather[
        "description"
    ]

    system_state["is_raining"] = weather[
        "is_raining"
    ]

    system_state["pm25"] = air[
        "pm25"
    ]

    system_state["pm10"] = air[
        "pm10"
    ]

    system_state["us_aqi"] = air[
        "us_aqi"
    ]

    system_state["last_update"] = time.strftime(
        "%H:%M:%S"
    )


    # --------------------------------------------------------
    # ĐIỀU KHIỂN THIẾT BỊ
    # --------------------------------------------------------

    print()

    print(
        "🔧 ĐANG ĐIỀU KHIỂN THIẾT BỊ..."
    )

    control_led(
        weather["is_raining"]
    )

    control_motor(
        weather["temperature"]
    )


    # --------------------------------------------------------
    # Hiển thị trạng thái
    # --------------------------------------------------------

    print_status()


    return True


# ============================================================
# HIỂN THỊ TRẠNG THÁI
# ============================================================

def print_status():

    print()

    print(
        "============================================================"
    )

    print(
        "                    THÔNG TIN THỜI TIẾT"
    )

    print(
        "============================================================"
    )


    print(
        f"📍 Thành phố     : "
        f"{system_state['city']}"
    )


    print(
        f"🌡️ Nhiệt độ      : "
        f"{system_state['temperature']:.1f} °C"
    )


    print(
        f"🌤️ Thời tiết     : "
        f"{system_state['weather_description']}"
    )


    print(
        f"🔢 Weather Code  : "
        f"{system_state['weather_code']}"
    )


    print(
        f"💧 Lượng mưa     : "
        f"{system_state['rain']:.1f} mm"
    )


    print(
        f"🌧️ Trời mưa      : "
        f"{'CÓ' if system_state['is_raining'] else 'KHÔNG'}"
    )


    print()

    print(
        "---------------- CHẤT LƯỢNG KHÔNG KHÍ ----------------"
    )


    if system_state["pm25"] is not None:

        print(
            f"PM2.5           : "
            f"{system_state['pm25']:.1f} µg/m³"
        )

    else:

        print(
            "PM2.5           : Không có dữ liệu"
        )


    if system_state["pm10"] is not None:

        print(
            f"PM10            : "
            f"{system_state['pm10']:.1f} µg/m³"
        )

    else:

        print(
            "PM10            : Không có dữ liệu"
        )


    if system_state["us_aqi"] is not None:

        print(
            f"US AQI          : "
            f"{system_state['us_aqi']}"
        )

    else:

        print(
            "US AQI          : Không có dữ liệu"
        )


    print()

    print(
        "---------------- ĐIỀU KHIỂN THIẾT BỊ ----------------"
    )


    print(
        f"💡 ĐÈN           : "
        f"{'BẬT' if system_state['led_on'] else 'TẮT'}"
    )


    print(
        f"⚙️ MOTOR         : "
        f"{'ĐANG CHẠY' if system_state['motor_on'] else 'DỪNG'}"
    )


    print(
        f"↪️ Chiều Motor    : "
        f"{system_state['motor_direction']}"
    )


    print()

    print(
        f"🕐 Cập nhật lúc   : "
        f"{system_state['last_update']}"
    )


    print(
        "============================================================"
    )


# ============================================================
# TẮT THIẾT BỊ AN TOÀN
# ============================================================

def shutdown():

    print()

    print(
        "🛑 ĐANG TẮT HỆ THỐNG..."
    )


    try:

        if motor is not None:

            motor.stop()

            motor.close()

            print(
                "✅ Motor đã dừng."
            )

    except Exception as e:

        print(
            f"⚠️ Lỗi tắt motor: {e}"
        )


    try:

        if led is not None:

            led.off()

            led.close()

            print(
                "✅ LED đã tắt."
            )

    except Exception as e:

        print(
            f"⚠️ Lỗi tắt LED: {e}"
        )


    print(
        "✅ Đã giải phóng GPIO."
    )


# ============================================================
# NHẬP THÀNH PHỐ
# ============================================================

def input_city():

    while True:

        print()

        city = input(
            "📍 Nhập thành phố: "
        ).strip()


        if city == "":

            print(
                "❌ Không được để trống."
            )

            continue


        location = find_city(
            city
        )


        if location is not None:

            return location


        print()

        print(
            "⚠️ Hãy nhập lại thành phố."
        )


# ============================================================
# MENU
# ============================================================

def show_menu():

    print()

    print(
        "============================================================"
    )

    print(
        "                         MENU"
    )

    print(
        "============================================================"
    )

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
        "4. Tự động cập nhật"
    )

    print(
        "q. Thoát chương trình"
    )

    print(
        "============================================================"
    )


# ============================================================
# CHẾ ĐỘ TỰ ĐỘNG
# ============================================================

def auto_update(location):

    print()

    print(
        "============================================================"
    )

    print(
        "                 CHẾ ĐỘ TỰ ĐỘNG"
    )

    print(
        f" Thành phố: {location['name']}"
    )

    print(
        f" Cập nhật mỗi {UPDATE_INTERVAL} giây"
    )

    print(
        " Nhấn Ctrl+C để quay lại menu."
    )

    print(
        "============================================================"
    )


    try:

        while True:

            update_system(
                location
            )


            print()

            print(
                f"⏳ Chờ {UPDATE_INTERVAL} giây "
                f"để cập nhật..."
            )


            time.sleep(
                UPDATE_INTERVAL
            )


    except KeyboardInterrupt:

        print()

        print(
            "↩️ Đã thoát chế độ tự động."
        )


# ============================================================
# CHƯƠNG TRÌNH CHÍNH
# ============================================================

def main():

    print()

    print(
        "============================================================"
    )

    print(
        "       HỆ THỐNG ĐIỀU KHIỂN THIẾT BỊ THEO THỜI TIẾT"
    )

    print(
        "============================================================"
    )

    print(
        "WEATHER API:"
    )

    print(
        WEATHER_URL
    )

    print()

    print(
        "AIR QUALITY API:"
    )

    print(
        AIR_URL
    )

    print()

    print(
        "Điều kiện:"
    )

    print(
        "🌧️ Trời mưa      -> BẬT ĐÈN"
    )

    print(
        "🌡️ Nhiệt độ > 30 -> MOTOR QUAY THUẬN"
    )

    print(
        "🌡️ Nhiệt độ <=30 -> MOTOR DỪNG"
    )

    print(
        "============================================================"
    )


    # --------------------------------------------------------
    # Nhập thành phố ban đầu
    # --------------------------------------------------------

    location = input_city()


    # --------------------------------------------------------
    # Lấy dữ liệu lần đầu
    # --------------------------------------------------------

    update_system(
        location
    )


    # --------------------------------------------------------
    # MENU CHÍNH
    # --------------------------------------------------------

    while True:

        show_menu()


        choice = input(
            "👉 Nhập lựa chọn: "
        ).strip().lower()


        # ====================================================
        # 1. Đổi thành phố
        # ====================================================

        if choice == "1":

            location = input_city()

            update_system(
                location
            )


        # ====================================================
        # 2. Cập nhật ngay
        # ====================================================

        elif choice == "2":

            update_system(
                location
            )


        # ====================================================
        # 3. Xem trạng thái
        # ====================================================

        elif choice == "3":

            print_status()


        # ====================================================
        # 4. Tự động cập nhật
        # ====================================================

        elif choice == "4":

            auto_update(
                location
            )


        # ====================================================
        # q. Thoát
        # ====================================================

        elif choice == "q":

            break


        else:

            print()

            print(
                "❌ Lựa chọn không hợp lệ."
            )


# ============================================================
# CHẠY CHƯƠNG TRÌNH
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()

        print(
            "🛑 Người dùng yêu cầu dừng chương trình."
        )

    except Exception as e:

        print()

        print(
            f"❌ Lỗi chương trình: {e}"
        )

    finally:

        shutdown()

        print()

        print(
            "👋 Chương trình kết thúc."
        )