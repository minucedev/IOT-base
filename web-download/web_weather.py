import time
import threading
import requests
import RPi.GPIO as GPIO

from flask import Flask, render_template_string, jsonify, request
from gpiozero import Motor
from gpiozero.pins.lgpio import LGPIOFactory


# ==============================================================================
# CẤU HÌNH GPIO
# ==============================================================================

# ---------------- ĐỘNG CƠ DC - L298N ----------------
MOTOR_EN = 18       # ENA - PWM
MOTOR_IN1 = 23      # IN1
MOTOR_IN2 = 24      # IN2

# ---------------- ĐÈN / RELAY ----------------
# Nếu đèn của bạn nối GPIO khác thì sửa dòng này.
LIGHT_PIN = 25


# ==============================================================================
# KHỞI TẠO GPIO
# ==============================================================================

# GPIO dùng cho đèn
try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LIGHT_PIN, GPIO.OUT)
    GPIO.output(LIGHT_PIN, GPIO.LOW)

    print(f"-> [THÀNH CÔNG] Đã setup đèn tại GPIO {LIGHT_PIN}")

except Exception as e:
    print(f"-> [LỖI] Không thể setup GPIO đèn: {e}")


# ==============================================================================
# KHỞI TẠO MOTOR
# ==============================================================================

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
        f"-> [THÀNH CÔNG] Motor DC: "
        f"ENA={MOTOR_EN}, IN1={MOTOR_IN1}, IN2={MOTOR_IN2}"
    )

except Exception as e:
    print(f"-> [LỖI] Không thể khởi tạo motor: {e}")
    motor = None


# ==============================================================================
# TRẠNG THÁI HỆ THỐNG
# ==============================================================================

system_state = {
    # Thành phố mặc định
    "city": "Da Nang",

    # Thời tiết
    "temperature": None,
    "weather": "Chưa có dữ liệu",
    "is_raining": False,

    # Thiết bị
    "light_on": False,
    "motor_running": False,
    "motor_direction": "STOP",
    "motor_speed": 60,

    # Trạng thái API
    "weather_ok": False,
    "last_weather_update": "--:--:--",
    "error": ""
}

lock = threading.Lock()


# ==============================================================================
# HÀM ĐIỀU KHIỂN ĐÈN
# ==============================================================================

def set_light(state):
    """
    Bật / tắt đèn.

    state = True  -> bật
    state = False -> tắt
    """

    try:
        GPIO.output(LIGHT_PIN, GPIO.HIGH if state else GPIO.LOW)

        with lock:
            system_state["light_on"] = state

        if state:
            print("💡 [ĐÈN] BẬT - Phát hiện trời mưa")
        else:
            print("💡 [ĐÈN] TẮT - Không mưa")

    except Exception as e:
        print(f"[LỖI ĐÈN] {e}")


# ==============================================================================
# HÀM ĐIỀU KHIỂN MOTOR
# ==============================================================================

def apply_motor():
    """
    Điều khiển motor dựa trên trạng thái hiện tại.

    Nếu nhiệt độ > 30°C:
        Motor quay thuận.

    Nếu nhiệt độ <= 30°C:
        Motor dừng.
    """

    with lock:
        running = system_state["motor_running"]
        direction = system_state["motor_direction"]
        speed = system_state["motor_speed"] / 100.0

    if motor is None:
        print("[MOTOR] Không có motor phần cứng.")
        return

    try:

        if not running or speed <= 0:
            motor.stop()

            with lock:
                system_state["motor_direction"] = "STOP"

            print("⚙️ [MOTOR] DỪNG")

        elif direction == "FORWARD":

            motor.forward(speed)

            print(
                f"⚙️ [MOTOR] QUAY THUẬN - "
                f"Tốc độ {int(speed * 100)}%"
            )

        else:
            motor.stop()

            with lock:
                system_state["motor_direction"] = "STOP"

    except Exception as e:
        print(f"[LỖI MOTOR] {e}")


# ==============================================================================
# HÀM CẬP NHẬT MOTOR THEO NHIỆT ĐỘ
# ==============================================================================

def control_motor_by_temperature(temperature):

    if temperature is None:
        return

    if temperature > 30:

        with lock:
            system_state["motor_running"] = True
            system_state["motor_direction"] = "FORWARD"

        print(
            f"🌡️ {temperature}°C > 30°C "
            f"-> Motor QUAY THUẬN"
        )

    else:

        with lock:
            system_state["motor_running"] = False
            system_state["motor_direction"] = "STOP"

        print(
            f"🌡️ {temperature}°C <= 30°C "
            f"-> Motor DỪNG"
        )

    apply_motor()


# ==============================================================================
# HÀM KIỂM TRA TRỜI MƯA
# ==============================================================================

def check_rain(weather_description, precip_mm):

    description = weather_description.lower()

    rain_keywords = [
        "rain",
        "drizzle",
        "shower",
        "thunderstorm",
        "mưa",
        "light rain",
        "heavy rain"
    ]

    # Kiểm tra mô tả thời tiết
    for keyword in rain_keywords:
        if keyword in description:
            return True

    # Hoặc lượng mưa > 0
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

    """
    Lấy dữ liệu thời tiết từ wttr.in.

    Không cần API key.
    """

    try:

        city = city.strip()

        if not city:
            raise ValueError("Tên thành phố không được để trống.")

        url = f"https://wttr.in/{city}"

        params = {
            "format": "j1"
        }

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        print(f"🌐 [WEATHER] Đang lấy thời tiết: {city}")

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        current = data["current_condition"][0]

        # Nhiệt độ Celsius
        temperature = float(current["temp_C"])

        # Mô tả thời tiết
        weather_description = current["weatherDesc"][0]["value"]

        # Lượng mưa
        precip_mm = float(current.get("precipMM", 0))

        # Kiểm tra mưa
        raining = check_rain(
            weather_description,
            precip_mm
        )

        return {
            "city": city,
            "temperature": temperature,
            "weather": weather_description,
            "precip_mm": precip_mm,
            "is_raining": raining
        }

    except requests.exceptions.RequestException as e:

        print(f"[LỖI INTERNET] {e}")

        return {
            "error": f"Không thể kết nối web thời tiết: {e}"
        }

    except Exception as e:

        print(f"[LỖI WEATHER] {e}")

        return {
            "error": str(e)
        }


# ==============================================================================
# ÁP DỤNG DỮ LIỆU THỜI TIẾT VÀO THIẾT BỊ
# ==============================================================================

def update_weather(city):

    result = get_weather(city)

    if "error" in result:

        with lock:
            system_state["weather_ok"] = False
            system_state["error"] = result["error"]

        print(
            f"❌ [WEATHER] {result['error']}"
        )

        return False

    temperature = result["temperature"]
    weather = result["weather"]
    raining = result["is_raining"]

    # --------------------------------------------------------------------------
    # Cập nhật trạng thái hệ thống
    # --------------------------------------------------------------------------

    with lock:

        system_state["city"] = result["city"]

        system_state["temperature"] = temperature

        system_state["weather"] = weather

        system_state["is_raining"] = raining

        system_state["weather_ok"] = True

        system_state["last_weather_update"] = time.strftime(
            "%H:%M:%S"
        )

        system_state["error"] = ""

    # --------------------------------------------------------------------------
    # ĐIỀU KHIỂN ĐÈN
    # --------------------------------------------------------------------------

    if raining:
        set_light(True)
    else:
        set_light(False)

    # --------------------------------------------------------------------------
    # ĐIỀU KHIỂN MOTOR
    # --------------------------------------------------------------------------

    control_motor_by_temperature(temperature)

    print("=" * 60)
    print("THỜI TIẾT")
    print(f"Thành phố : {city}")
    print(f"Nhiệt độ  : {temperature}°C")
    print(f"Thời tiết : {weather}")
    print(f"Lượng mưa : {result['precip_mm']} mm")
    print(f"Trời mưa  : {'CÓ' if raining else 'KHÔNG'}")
    print("=" * 60)

    return True


# ==============================================================================
# LUỒNG TỰ ĐỘNG CẬP NHẬT THỜI TIẾT
# ==============================================================================

def weather_loop():

    while True:

        try:

            with lock:
                city = system_state["city"]

            update_weather(city)

        except Exception as e:

            print(f"[WEATHER LOOP ERROR] {e}")

        # Cập nhật mỗi 5 phút
        time.sleep(300)


# ==============================================================================
# GIAO DIỆN WEB
# ==============================================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>Hệ thống điều khiển theo thời tiết</title>

<style>

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    font-family: Arial, sans-serif;
}

body {

    min-height: 100vh;

    background:
        radial-gradient(
            circle at top left,
            #164e63,
            transparent 40%
        ),
        radial-gradient(
            circle at bottom right,
            #312e81,
            transparent 40%
        ),
        #020617;

    color: white;

    display: flex;
    justify-content: center;
    align-items: center;

    padding: 20px;
}

.container {

    width: 100%;
    max-width: 650px;
}

.card {

    background: rgba(15, 23, 42, 0.90);

    border: 1px solid rgba(255,255,255,0.1);

    border-radius: 25px;

    padding: 30px;

    box-shadow:
        0 20px 60px rgba(0,0,0,0.5);

}

h1 {

    text-align: center;

    color: #38bdf8;

    margin-bottom: 10px;

}

.subtitle {

    text-align: center;

    color: #94a3b8;

    margin-bottom: 25px;

}

.city-form {

    display: flex;

    gap: 10px;

    margin-bottom: 25px;

}

.city-form input {

    flex: 1;

    padding: 15px;

    border-radius: 12px;

    border: 1px solid #334155;

    background: #020617;

    color: white;

    font-size: 16px;

}

.city-form button {

    padding: 15px 20px;

    border: none;

    border-radius: 12px;

    background: #0ea5e9;

    color: white;

    font-weight: bold;

    cursor: pointer;

}

.weather-card {

    background: rgba(30,41,59,0.7);

    border-radius: 20px;

    padding: 25px;

    text-align: center;

    margin-bottom: 20px;

}

.city {

    font-size: 22px;

    font-weight: bold;

    color: #38bdf8;

}

.temperature {

    font-size: 65px;

    font-weight: bold;

    margin: 15px 0;

}

.weather {

    font-size: 20px;

    color: #cbd5e1;

}

.grid {

    display: grid;

    grid-template-columns:
        repeat(2, 1fr);

    gap: 12px;

}

.status {

    padding: 20px;

    border-radius: 16px;

    background: rgba(255,255,255,0.04);

    border: 1px solid rgba(255,255,255,0.08);

    text-align: center;

}

.status-title {

    color: #94a3b8;

    font-size: 13px;

    margin-bottom: 8px;

}

.status-value {

    font-size: 20px;

    font-weight: bold;

}

.rain {

    color: #38bdf8;

}

.no-rain {

    color: #10b981;

}

.motor-on {

    color: #10b981;

}

.motor-off {

    color: #ef4444;

}

.light-on {

    color: #fbbf24;

}

.light-off {

    color: #64748b;

}

.info {

    margin-top: 20px;

    padding: 15px;

    background: rgba(14,165,233,0.1);

    border-radius: 12px;

    color: #bae6fd;

    line-height: 1.6;

}

.error {

    margin-top: 15px;

    padding: 15px;

    border-radius: 12px;

    background: rgba(239,68,68,0.15);

    color: #fca5a5;

    display: none;

}

.footer {

    text-align: center;

    margin-top: 20px;

    color: #64748b;

    font-size: 12px;

}

@media(max-width: 500px) {

    .city-form {
        flex-direction: column;
    }

    .grid {
        grid-template-columns: 1fr;
    }

    .temperature {
        font-size: 50px;
    }

}

</style>

<script>

async function updateWeather() {

    const city =
        document.getElementById("city").value.trim();

    if (!city) {

        alert("Vui lòng nhập tên thành phố!");

        return;

    }

    try {

        const response =
            await fetch(
                "/api/weather/update",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        city: city
                    })
                }
            );

        const data =
            await response.json();

        updateUI(data);

    }
    catch(error) {

        console.error(error);

        alert(
            "Không thể kết nối Raspberry Pi!"
        );

    }

}


async function getStatus() {

    try {

        const response =
            await fetch("/api/status");

        const data =
            await response.json();

        updateUI(data);

    }
    catch(error) {

        console.log(error);

    }

}


function updateUI(data) {

    // Thành phố
    document.getElementById(
        "cityDisplay"
    ).innerText =
        data.city;


    // Nhiệt độ
    if (data.temperature !== null) {

        document.getElementById(
            "temperature"
        ).innerText =
            data.temperature + "°C";

    }
    else {

        document.getElementById(
            "temperature"
        ).innerText =
            "--°C";

    }


    // Thời tiết
    document.getElementById(
        "weather"
    ).innerText =
        data.weather;


    // Trời mưa
    const rain =
        document.getElementById(
            "rainStatus"
        );

    if (data.is_raining) {

        rain.innerText =
            "🌧️ CÓ MƯA";

        rain.className =
            "status-value rain";

    }
    else {

        rain.innerText =
            "☀️ KHÔNG MƯA";

        rain.className =
            "status-value no-rain";

    }


    // Đèn
    const light =
        document.getElementById(
            "lightStatus"
        );

    if (data.light_on) {

        light.innerText =
            "💡 ĐANG BẬT";

        light.className =
            "status-value light-on";

    }
    else {

        light.innerText =
            "⚫ ĐANG TẮT";

        light.className =
            "status-value light-off";

    }


    // Motor
    const motor =
        document.getElementById(
            "motorStatus"
        );

    if (data.motor_running) {

        motor.innerText =
            "▶️ QUAY THUẬN";

        motor.className =
            "status-value motor-on";

    }
    else {

        motor.innerText =
            "⏹️ ĐANG DỪNG";

        motor.className =
            "status-value motor-off";

    }


    // Thời gian cập nhật
    document.getElementById(
        "lastUpdate"
    ).innerText =
        data.last_weather_update;


    // Thông báo lỗi
    const error =
        document.getElementById(
            "error"
        );

    if (data.error) {

        error.style.display =
            "block";

        error.innerText =
            "❌ " + data.error;

    }
    else {

        error.style.display =
            "none";

    }

}


// Cập nhật trạng thái mỗi 5 giây
setInterval(
    getStatus,
    5000
);


window.onload =
    getStatus;

</script>

</head>


<body>

<div class="container">

<div class="card">

<h1>
🌦️ HỆ THỐNG ĐIỀU KHIỂN THEO THỜI TIẾT
</h1>

<div class="subtitle">
Raspberry Pi + Web Weather + Motor DC + Đèn
</div>


<!-- NHẬP THÀNH PHỐ -->

<div class="city-form">

<input
    id="city"
    type="text"
    value="Da Nang"
    placeholder="Nhập tên thành phố..."
>

<button onclick="updateWeather()">
🔍 XEM THỜI TIẾT
</button>

</div>


<!-- THÔNG TIN THỜI TIẾT -->

<div class="weather-card">

<div class="city">
📍 <span id="cityDisplay">
Da Nang
</span>
</div>

<div
    id="temperature"
    class="temperature"
>
--°C
</div>

<div
    id="weather"
    class="weather"
>
Chưa có dữ liệu
</div>

</div>


<!-- TRẠNG THÁI -->

<div class="grid">


<div class="status">

<div class="status-title">
🌧️ TRỜI MƯA
</div>

<div
    id="rainStatus"
    class="status-value"
>
--
</div>

</div>


<div class="status">

<div class="status-title">
💡 ĐÈN
</div>

<div
    id="lightStatus"
    class="status-value"
>
--
</div>

</div>


<div class="status">

<div class="status-title">
⚙️ ĐỘNG CƠ DC
</div>

<div
    id="motorStatus"
    class="status-value"
>
--
</div>

</div>


<div class="status">

<div class="status-title">
🔄 CẬP NHẬT
</div>

<div
    id="lastUpdate"
    class="status-value"
>
--
</div>

</div>


</div>


<!-- GIẢI THÍCH -->

<div class="info">

<b>⚙️ Nguyên lý hoạt động:</b>

<br>

🌧️ Nếu trời mưa
→ <b>bật đèn</b>

<br>

🌡️ Nếu nhiệt độ &gt; 30°C
→ <b>motor quay thuận</b>

<br>

🌡️ Nếu nhiệt độ ≤ 30°C
→ <b>motor dừng</b>

<br>

☀️ Nếu không mưa
→ <b>tắt đèn</b>

</div>


<div
    id="error"
    class="error"
>
</div>


<div class="footer">

Tự động cập nhật thời tiết mỗi 5 phút

</div>

</div>

</div>

</body>

</html>
"""


# ==============================================================================
# FLASK
# ==============================================================================

app = Flask(__name__)


@app.route("/")
def index():

    return render_template_string(
        HTML_TEMPLATE
    )


# ==============================================================================
# API STATUS
# ==============================================================================

@app.route("/api/status")
def api_status():

    with lock:

        return jsonify(
            system_state
        )


# ==============================================================================
# API CẬP NHẬT THỜI TIẾT
# ==============================================================================

@app.route(
    "/api/weather/update",
    methods=["POST"]
)
def api_weather_update():

    try:

        data = request.get_json()

        city = data.get(
            "city",
            ""
        ).strip()

        if not city:

            return jsonify({
                "error":
                "Tên thành phố không được để trống."
            }), 400

        # Lấy thời tiết
        update_weather(city)

        with lock:

            return jsonify(
                system_state
            )

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ==============================================================================
# API THAY ĐỔI TỐC ĐỘ MOTOR
# ==============================================================================

@app.route(
    "/api/motor/speed/<int:speed>"
)
def api_motor_speed(speed):

    speed = max(
        0,
        min(100, speed)
    )

    with lock:
        system_state[
            "motor_speed"
        ] = speed

    # Chỉ áp dụng tốc độ nếu motor đang chạy
    apply_motor()

    with lock:
        return jsonify(
            system_state
        )


# ==============================================================================
# CHẠY CHƯƠNG TRÌNH
# ==============================================================================

if __name__ == "__main__":

    print("=" * 70)

    print(
        "   HỆ THỐNG THEO DÕI THỜI TIẾT "
        "& ĐIỀU KHIỂN THIẾT BỊ"
    )

    print("=" * 70)

    print(
        f"- Motor ENA : GPIO {MOTOR_EN}"
    )

    print(
        f"- Motor IN1 : GPIO {MOTOR_IN1}"
    )

    print(
        f"- Motor IN2 : GPIO {MOTOR_IN2}"
    )

    print(
        f"- Đèn       : GPIO {LIGHT_PIN}"
    )

    print(
        "- Thời tiết : wttr.in"
    )

    print(
        "- Motor: >30°C -> QUAY THUẬN"
    )

    print(
        "- Đèn: Mưa -> BẬT"
    )

    print(
        "- Web: http://localhost:5000"
    )

    print("=" * 70)


    # --------------------------------------------------------------------------
    # Lấy dữ liệu thời tiết ngay khi khởi động
    # --------------------------------------------------------------------------

    update_weather(
        system_state["city"]
    )


    # --------------------------------------------------------------------------
    # Thread cập nhật thời tiết tự động
    # --------------------------------------------------------------------------

    weather_thread = threading.Thread(
        target=weather_loop,
        daemon=True
    )

    weather_thread.start()


    # --------------------------------------------------------------------------
    # Flask
    # --------------------------------------------------------------------------

    try:

        app.run(
            host="0.0.0.0",
            port=5000,
            debug=False,
            threaded=True
        )

    except KeyboardInterrupt:

        print(
            "\nĐang dừng hệ thống..."
        )

    finally:

        # Dừng motor
        if motor:

            try:
                motor.stop()
                motor.close()

            except Exception:
                pass


        # Tắt đèn
        try:

            GPIO.output(
                LIGHT_PIN,
                GPIO.LOW
            )

            GPIO.cleanup()

        except Exception:
            pass


        print(
            "Đã giải phóng tài nguyên."
        )