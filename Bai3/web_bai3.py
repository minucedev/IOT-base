import time
import threading

import requests

import board
import adafruit_dht

from digitalio import DigitalInOut, Direction
from adafruit_motor import stepper

from flask import Flask, render_template_string, jsonify


# ============================================================
# GPIO
# ============================================================

IN1 = board.D17
IN2 = board.D18
IN3 = board.D27
IN4 = board.D22

DHT_PIN = board.D4


# ============================================================
# STEPPER MOTOR
# 28BYJ-48 + ULN2003
# ============================================================

coil1 = DigitalInOut(IN1)
coil2 = DigitalInOut(IN2)
coil3 = DigitalInOut(IN3)
coil4 = DigitalInOut(IN4)

for coil in (coil1, coil2, coil3, coil4):
    coil.direction = Direction.OUTPUT

motor = stepper.StepperMotor(
    coil1,
    coil3,
    coil2,
    coil4,
    microsteps=None
)


# ============================================================
# STEPPER CONFIG
# ============================================================

STEPS_PER_REV = 4096

DEGREE_PER_STEP = 360.0 / STEPS_PER_REV

# MAX speed
STEP_DELAY = 0.001

# Nghỉ 1 giây sau mỗi lần quay
BURST_PAUSE = 1.0


# ============================================================
# DHT11
# ============================================================

dht = adafruit_dht.DHT11(DHT_PIN)


# ============================================================
# THỜI TIẾT ĐÀ NẴNG (Open-Meteo - như bài web_weather.py)
# ============================================================

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

DANANG = {
    "name": "Đà Nẵng",
    "latitude": 16.0544,
    "longitude": 108.2022
}

# Cập nhật thời tiết mỗi 60 giây
WEATHER_INTERVAL = 60


# ============================================================
# MOTOR STATE
# ============================================================

state = {
    "running": False,
    "direction": "FORWARD",
    "step_angle": 10,
    "angle": 0.0,
    "temperature": None,
    "humidity": None,
    # --- Thời tiết Đà Nẵng (online) ---
    "dn_temperature": None,
    "dn_humidity": None,
    "dn_rain_prob": None,
    "dn_rain": None,
    "dn_description": None,
    "dn_is_raining": False,
    "dn_last_update": None,
}

lock = threading.Lock()


# ============================================================
# CHUYỂN WEATHER CODE THÀNH MÔ TẢ
# (copy từ bài web_weather.py)
# ============================================================

def weather_description(code):

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
# (chỉ cần có mưa thôi: rain > 0)
# ============================================================

def check_rain(rain):

    if rain is not None and rain > 0:

        return True

    return False


# ============================================================
# MOTOR LOOP
# ============================================================

def motor_loop():

    while True:

        # ----------------------------------------------------
        # Kiểm tra motor có đang chạy không
        # ----------------------------------------------------

        with lock:
            running = state["running"]

        if not running:

            motor.release()

            time.sleep(0.05)

            continue


        # ----------------------------------------------------
        # Lấy góc mỗi nhịp
        # ----------------------------------------------------

        with lock:
            step_angle = state["step_angle"]


        # ----------------------------------------------------
        # Đổi góc sang số bước
        # ----------------------------------------------------

        steps = max(
            1,
            round(step_angle / DEGREE_PER_STEP)
        )


        interrupted = False


        # ----------------------------------------------------
        # Quay từng bước
        # ----------------------------------------------------

        for _ in range(steps):

            with lock:

                # Nếu người dùng bấm DỪNG
                if not state["running"]:

                    interrupted = True

                    break


                # ------------------------------------------------
                # Đảo chiều vật lý
                #
                # UI THUẬN  -> motor BACKWARD
                # UI NGƯỢC  -> motor FORWARD
                # ------------------------------------------------

                if state["direction"] == "FORWARD":

                    motor_direction = stepper.BACKWARD

                else:

                    motor_direction = stepper.FORWARD


            # ------------------------------------------------
            # Quay 1 bước
            # ------------------------------------------------

            try:

                motor.onestep(
                    direction=motor_direction,
                    style=stepper.INTERLEAVE
                )

            except Exception as e:

                print(f"[MOTOR ERROR] {e}")

                with lock:
                    state["running"] = False

                motor.release()

                interrupted = True

                break


            # ------------------------------------------------
            # Cập nhật góc hiện tại
            # ------------------------------------------------

            with lock:

                if state["direction"] == "FORWARD":

                    state["angle"] -= DEGREE_PER_STEP

                else:

                    state["angle"] += DEGREE_PER_STEP


                # Giữ góc trong khoảng 0 -> 360
                state["angle"] %= 360.0


            # ------------------------------------------------
            # Delay tốc độ MAX
            # ------------------------------------------------

            time.sleep(STEP_DELAY)


        # ----------------------------------------------------
        # Nhả motor sau mỗi nhịp
        # ----------------------------------------------------

        motor.release()


        # ----------------------------------------------------
        # Nghỉ 1 giây rồi quay tiếp
        # ----------------------------------------------------

        if not interrupted:

            with lock:
                running = state["running"]

            if running:

                time.sleep(BURST_PAUSE)


# ============================================================
# DHT11 LOOP
# ============================================================

def dht_loop():

    while True:

        try:

            temperature = dht.temperature
            humidity = dht.humidity


            if temperature is not None:

                with lock:
                    state["temperature"] = round(
                        temperature,
                        1
                    )


            if humidity is not None:

                with lock:
                    state["humidity"] = round(
                        humidity,
                        1
                    )


        except RuntimeError:

            # DHT11 đôi khi đọc lỗi tạm thời
            pass


        except Exception as e:

            print(f"[DHT11 ERROR] {e}")


        # DHT11 đọc mỗi 2 giây
        time.sleep(2)


# ============================================================
# WEATHER LOOP - ĐÀ NẴNG (Open-Meteo)
# ============================================================

def weather_loop():

    while True:

        try:

            params = {

                "latitude": DANANG["latitude"],

                "longitude": DANANG["longitude"],

                "current": (
                    "temperature_2m,"
                    "relative_humidity_2m,"
                    "rain,"
                    "precipitation,"
                    "precipitation_probability,"
                    "weather_code"
                ),

                "timezone": "Asia/Ho_Chi_Minh"
            }

            response = requests.get(
                WEATHER_URL,
                params=params,
                timeout=15
            )

            response.raise_for_status()

            current = response.json().get(
                "current",
                {}
            )

            temperature = current.get(
                "temperature_2m"
            )

            humidity = current.get(
                "relative_humidity_2m"
            )

            rain = current.get(
                "rain",
                0
            )

            rain_prob = current.get(
                "precipitation_probability"
            )

            weather_code = current.get(
                "weather_code"
            )

            is_raining = check_rain(rain)

            with lock:

                if temperature is not None:
                    state["dn_temperature"] = round(
                        float(temperature),
                        1
                    )

                if humidity is not None:
                    state["dn_humidity"] = int(humidity)

                if rain_prob is not None:
                    state["dn_rain_prob"] = int(rain_prob)

                state["dn_rain"] = float(rain or 0)

                state["dn_description"] = weather_description(
                    weather_code
                )

                state["dn_is_raining"] = is_raining

                state["dn_last_update"] = time.strftime(
                    "%H:%M:%S"
                )

            print(
                f"[WEATHER] Da Nang: "
                f"{state['dn_temperature']}C, "
                f"{state['dn_humidity']}%, "
                f"mua {state['dn_rain_prob']}%, "
                f"rain {state['dn_rain']}mm"
            )

        except Exception as e:

            print(f"[WEATHER ERROR] {e}")


        time.sleep(WEATHER_INTERVAL)


# ============================================================
# START THREADS
# ============================================================

threading.Thread(
    target=motor_loop,
    daemon=True
).start()

threading.Thread(
    target=dht_loop,
    daemon=True
).start()

threading.Thread(
    target=weather_loop,
    daemon=True
).start()


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# HTML
# ============================================================

HTML = """
<!DOCTYPE html>

<html lang="vi">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>DHT11 & Stepper + Thoi tiet Da Nang</title>


<style>

* {
    box-sizing: border-box;
}


body {

    margin: 0;

    min-height: 100vh;

    display: flex;

    align-items: center;

    justify-content: center;

    background: #111827;

    color: #ffffff;

    font-family: Arial, sans-serif;
}


.container {

    width: 100%;

    max-width: 420px;

    padding: 16px;
}


.card {

    background: #1f2937;

    border-radius: 16px;

    padding: 20px;
}


h1 {

    text-align: center;

    font-size: 21px;

    margin: 0 0 18px;
}


h2 {

    text-align: center;

    font-size: 15px;

    color: #93c5fd;

    margin: 18px 0 10px;
}


/* =========================================================
   SENSOR
   ========================================================= */

.sensor {

    display: grid;

    grid-template-columns: 1fr 1fr;

    gap: 10px;

    margin-bottom: 14px;
}


.sensor-3 {

    display: grid;

    grid-template-columns: 1fr 1fr 1fr;

    gap: 10px;

    margin-bottom: 10px;
}


.sensor-box {

    background: #111827;

    border-radius: 12px;

    padding: 14px;

    text-align: center;
}


.label {

    font-size: 12px;

    color: #9ca3af;

    margin-bottom: 6px;
}


.value {

    font-size: 27px;

    font-weight: bold;
}


.unit {

    font-size: 13px;

    color: #9ca3af;
}


/* =========================================================
   WEATHER
   ========================================================= */

.weather-card {

    background: #0c4a6e;

    border-radius: 12px;

    padding: 14px;

    margin-bottom: 12px;

    text-align: center;
}


.weather-desc {

    font-size: 16px;

    font-weight: bold;

    margin-bottom: 4px;
}


.weather-sub {

    font-size: 12px;

    color: #bae6fd;
}


/* =========================================================
   MOTOR STATUS
   ========================================================= */

.status {

    background: #111827;

    border-radius: 12px;

    padding: 14px;

    text-align: center;

    margin-bottom: 12px;
}


.status-main {

    font-size: 20px;

    font-weight: bold;

    margin-bottom: 5px;
}


.status-direction {

    color: #9ca3af;

    font-size: 14px;
}


/* =========================================================
   BUTTONS
   ========================================================= */

.row {

    display: grid;

    grid-template-columns: 1fr 1fr;

    gap: 8px;

    margin-bottom: 8px;
}


button {

    border: none;

    border-radius: 10px;

    padding: 13px 8px;

    font-size: 14px;

    font-weight: bold;

    cursor: pointer;

    color: white;
}


.on {

    background: #16a34a;
}


.off {

    background: #dc2626;
}


.forward {

    background: #2563eb;
}


.backward {

    background: #7c3aed;
}


/* =========================================================
   ANGLE
   ========================================================= */

.angle-box {

    background: #111827;

    border-radius: 12px;

    padding: 14px;

    margin-top: 10px;
}


.angle-header {

    display: flex;

    justify-content: space-between;

    font-size: 14px;

    margin-bottom: 10px;
}


input[type="range"] {

    width: 100%;
}


.current-angle {

    text-align: center;

    color: #9ca3af;

    font-size: 13px;

    margin-top: 12px;
}

</style>

</head>


<body>


<div class="container">

<div class="card">


<h1>DHT11 & STEPPER MOTOR</h1>


<!-- =====================================================
     DHT11
     ===================================================== -->

<div class="sensor">


    <div class="sensor-box">

        <div class="label">
            NHIỆT ĐỘ
        </div>

        <div class="value">

            <span id="temperature">
                --
            </span>

            <span class="unit">
                °C
            </span>

        </div>

    </div>


    <div class="sensor-box">

        <div class="label">
            ĐỘ ẨM
        </div>

        <div class="value">

            <span id="humidity">
                --
            </span>

            <span class="unit">
                %
            </span>

        </div>

    </div>


</div>


<!-- =====================================================
     THOI TIET DA NANG (ONLINE)
     ===================================================== -->

<h2>🌤️ THỜI TIẾT ĐÀ NẴNG (ONLINE)</h2>

<div class="sensor-3">


    <div class="sensor-box">

        <div class="label">
            NHIỆT ĐỘ
        </div>

        <div class="value">

            <span id="dn_temperature">
                --
            </span>

            <span class="unit">
                °C
            </span>

        </div>

    </div>


    <div class="sensor-box">

        <div class="label">
            ĐỘ ẨM
        </div>

        <div class="value">

            <span id="dn_humidity">
                --
            </span>

            <span class="unit">
                %
            </span>

        </div>

    </div>


    <div class="sensor-box">

        <div class="label">
            KHẢ NĂNG MƯA
        </div>

        <div class="value">

            <span id="dn_rain_prob">
                --
            </span>

            <span class="unit">
                %
            </span>

        </div>

    </div>


</div>


<div class="weather-card">

    <div
        id="dn_description"
        class="weather-desc"
    >
        Đang tải...
    </div>

    <div class="weather-sub">

        Mưa: <span id="dn_rain">--</span> mm

        • <span id="dn_is_raining">--</span>

        • Cập nhật: <span id="dn_last_update">--</span>

    </div>

</div>


<!-- =====================================================
     MOTOR STATUS
     ===================================================== -->

<div class="status">


    <div
        id="motorStatus"
        class="status-main"
    >
        ĐANG DỪNG
    </div>


    <div
        id="direction"
        class="status-direction"
    >
        ↻ THUẬN
    </div>


</div>


<!-- =====================================================
     ON / OFF
     ===================================================== -->

<div class="row">


    <button
        class="on"
        onclick="send('/api/motor/on')"
    >
        ▶ BẬT
    </button>


    <button
        class="off"
        onclick="send('/api/motor/off')"
    >
        ■ DỪNG
    </button>


</div>


<!-- =====================================================
     DIRECTION
     ===================================================== -->

<div class="row">


    <button
        class="forward"
        onclick="send('/api/motor/direction/forward')"
    >
        ↻ THUẬN
    </button>


    <button
        class="backward"
        onclick="send('/api/motor/direction/backward')"
    >
        ↺ NGƯỢC
    </button>


</div>


<!-- =====================================================
     ANGLE
     ===================================================== -->

<div class="angle-box">


    <div class="angle-header">


        <span>
            Góc mỗi nhịp
        </span>


        <strong>

            <span id="stepAngle">
                10
            </span>

            °

        </strong>


    </div>


    <input
        id="angleSlider"
        type="range"
        min="1"
        max="360"
        step="1"
        value="10"
        oninput="setAngle(this.value)"
    >


</div>


<!-- =====================================================
     CURRENT ANGLE
     ===================================================== -->

<div class="current-angle">


    Góc hiện tại:


    <strong>

        <span id="currentAngle">
            0
        </span>

        °

    </strong>


</div>


</div>

</div>


<script>


// =========================================================
// SEND API
// =========================================================

async function send(url) {

    try {

        const response =
            await fetch(url);

        const data =
            await response.json();

        updateUI(data);

    }

    catch (error) {

        console.error(error);

    }

}


// =========================================================
// SET ANGLE
// =========================================================

async function setAngle(angle) {

    angle = Math.round(
        Number(angle)
    );


    document.getElementById(
        'stepAngle'
    ).innerText = angle;


    await send(
        '/api/motor/angle/' + angle
    );

}


// =========================================================
// UPDATE UI
// =========================================================

function updateUI(data) {


    // Temperature

    document.getElementById(
        'temperature'
    ).innerText =
        data.temperature ?? '--';


    // Humidity

    document.getElementById(
        'humidity'
    ).innerText =
        data.humidity ?? '--';


    // Da Nang weather

    document.getElementById(
        'dn_temperature'
    ).innerText =
        data.dn_temperature ?? '--';

    document.getElementById(
        'dn_humidity'
    ).innerText =
        data.dn_humidity ?? '--';

    document.getElementById(
        'dn_rain_prob'
    ).innerText =
        data.dn_rain_prob ?? '--';

    document.getElementById(
        'dn_rain'
    ).innerText =
        data.dn_rain ?? '--';

    document.getElementById(
        'dn_description'
    ).innerText =
        data.dn_description ?? 'Đang tải...';

    document.getElementById(
        'dn_is_raining'
    ).innerText =
        data.dn_is_raining ? 'ĐANG MƯA' : 'KHÔNG MƯA';

    document.getElementById(
        'dn_last_update'
    ).innerText =
        data.dn_last_update ?? '--';


    // Motor status

    document.getElementById(
        'motorStatus'
    ).innerText =

        data.running
            ? 'ĐANG CHẠY'
            : 'ĐANG DỪNG';


    // Direction

    document.getElementById(
        'direction'
    ).innerText =

        data.direction === 'FORWARD'

            ? '↻ THUẬN'

            : '↺ NGƯỢC';


    // Current angle

    document.getElementById(
        'currentAngle'
    ).innerText =

        Math.round(
            Number(data.angle)
        );


    // Step angle

    document.getElementById(
        'stepAngle'
    ).innerText =

        Math.round(
            Number(data.step_angle)
        );


    // Slider

    document.getElementById(
        'angleSlider'
    ).value =

        Math.round(
            Number(data.step_angle)
        );

}


// =========================================================
// AUTO UPDATE
// =========================================================

setInterval(
    async () => {

        try {

            const response =
                await fetch(
                    '/api/status'
                );

            const data =
                await response.json();

            updateUI(data);

        }

        catch (error) {

            // Không làm gì nếu mất kết nối
        }

    },

    500
);


// =========================================================
// INITIAL STATUS
// =========================================================

send('/api/status');

</script>


</body>

</html>
"""


# ============================================================
# API
# ============================================================

@app.route("/")
def index():

    return render_template_string(HTML)


# ============================================================
# STATUS
# ============================================================

@app.route("/api/status")
def api_status():

    with lock:

        return jsonify({

            "running":
                state["running"],

            "direction":
                state["direction"],

            "step_angle":
                state["step_angle"],

            "angle":
                state["angle"],

            "temperature":
                state["temperature"],

            "humidity":
                state["humidity"],

            "dn_temperature":
                state["dn_temperature"],

            "dn_humidity":
                state["dn_humidity"],

            "dn_rain_prob":
                state["dn_rain_prob"],

            "dn_rain":
                state["dn_rain"],

            "dn_description":
                state["dn_description"],

            "dn_is_raining":
                state["dn_is_raining"],

            "dn_last_update":
                state["dn_last_update"],

        })


# ============================================================
# MOTOR ON
# ============================================================

@app.route("/api/motor/on")
def motor_on():

    with lock:

        state["running"] = True

        return jsonify(state)


# ============================================================
# MOTOR OFF
# ============================================================

@app.route("/api/motor/off")
def motor_off():

    with lock:

        state["running"] = False


    motor.release()


    return jsonify(state)


# ============================================================
# MOTOR DIRECTION
# ============================================================

@app.route("/api/motor/direction/<direction>")
def motor_direction(direction):

    if direction not in [
        "forward",
        "backward"
    ]:

        return jsonify({
            "error": "Invalid direction"
        }), 400


    with lock:

        if direction == "forward":

            state["direction"] = "FORWARD"

        else:

            state["direction"] = "BACKWARD"


        return jsonify(state)


# ============================================================
# MOTOR ANGLE
# ============================================================

@app.route("/api/motor/angle/<int:angle>")
def motor_angle(angle):

    # Góc từ 1 -> 360 độ

    if angle < 1 or angle > 360:

        return jsonify({

            "error":
                "Angle must be between 1 and 360"

        }), 400


    with lock:

        state["step_angle"] = angle

        return jsonify(state)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":


    print("=" * 50)

    print("DHT11 + 28BYJ-48 + THOI TIET DA NANG")

    print("=" * 50)


    print("DHT11    : GPIO 4")

    print("STEPPER  : GPIO 17, 18, 27, 22")

    print("ANGLE    : 1 - 360 degrees")

    print("SPEED    : MAX")

    print("PAUSE    : 1 second")

    print(
        f"WEATHER  : {DANANG['name']} "
        f"({DANANG['latitude']}, {DANANG['longitude']})"
    )

    print(f"API      : {WEATHER_URL}")

    print(
        "WEB      : "
        "http://<RASPBERRY_PI_IP>:5000"
    )


    print("=" * 50)


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


        # Nhả motor

        motor.release()


        # Giải phóng GPIO

        coil1.deinit()

        coil2.deinit()

        coil3.deinit()

        coil4.deinit()


        # Thoát DHT11

        dht.exit()


        print(
            "Đã giải phóng GPIO."
        )
