import time
import threading

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


# A = IN1 + IN3
# B = IN2 + IN4
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

# 28BYJ-48 half-step
STEPS_PER_REV = 4096

# Góc lý thuyết của 1 step
DEGREE_PER_STEP = 360.0 / STEPS_PER_REV

# Nghỉ sau mỗi nhịp quay
BURST_PAUSE = 1.0


# ============================================================
# DHT11
# ============================================================

dht = adafruit_dht.DHT11(DHT_PIN)


# ============================================================
# MOTOR STATE
# ============================================================

state = {
    # Motor ON / OFF
    "running": False,

    # FORWARD / BACKWARD
    "direction": "FORWARD",

    # 1 = chậm
    # 2 = vừa
    # 3 = nhanh
    # 4 = MAX
    "speed": 2,

    # Góc quay trong mỗi nhịp
    # Chỉ nhận số nguyên từ 1 -> 180
    "step_angle": 10,

    # Góc hiện tại
    "angle": 0.0,

    # DHT11
    "temperature": None,
    "humidity": None,
}


lock = threading.Lock()


# ============================================================
# SPEED
# ============================================================

SPEED_DELAY = {
    1: 0.005,
    2: 0.003,
    3: 0.002,
    4: 0.001,
}


# ============================================================
# STEPPER LOOP
# ============================================================

def motor_loop():

    while True:

        # ----------------------------------------------------
        # Kiểm tra motor
        # ----------------------------------------------------

        with lock:
            running = state["running"]

        if not running:

            motor.release()

            time.sleep(0.05)

            continue


        # ----------------------------------------------------
        # Lấy cấu hình hiện tại
        # ----------------------------------------------------

        with lock:
            step_angle = state["step_angle"]
            speed = state["speed"]
            direction = state["direction"]


        # ----------------------------------------------------
        # Tính số step cho một nhịp
        #
        # 4096 step = 360°
        #
        # Ví dụ:
        # 10°  -> ~114 step
        # 45°  -> ~512 step
        # 90°  -> ~1024 step
        # 180° -> ~2048 step
        # ----------------------------------------------------

        steps = max(
            1,
            round(step_angle / DEGREE_PER_STEP)
        )


        # ----------------------------------------------------
        # Xác định chiều
        # ----------------------------------------------------

        if direction == "FORWARD":

            motor_direction = stepper.FORWARD

        else:

            motor_direction = stepper.BACKWARD


        # ----------------------------------------------------
        # QUAY MỘT NHỊP
        # ----------------------------------------------------

        interrupted = False

        for _ in range(steps):

            # -----------------------------------------------
            # Kiểm tra trạng thái
            # -----------------------------------------------

            with lock:

                if not state["running"]:

                    interrupted = True

                    break


                # Cho phép đổi chiều
                if state["direction"] == "FORWARD":

                    motor_direction = stepper.FORWARD

                else:

                    motor_direction = stepper.BACKWARD


                speed = state["speed"]


            # -----------------------------------------------
            # Tốc độ
            # -----------------------------------------------

            delay = SPEED_DELAY.get(
                speed,
                SPEED_DELAY[2]
            )


            # -----------------------------------------------
            # Quay 1 step
            # -----------------------------------------------

            try:

                motor.onestep(
                    direction=motor_direction,
                    style=stepper.INTERLEAVE
                )

            except Exception as e:

                print(
                    f"[MOTOR ERROR] {e}"
                )

                with lock:
                    state["running"] = False

                motor.release()

                interrupted = True

                break


            # -----------------------------------------------
            # Cập nhật góc
            # -----------------------------------------------

            with lock:

                if motor_direction == stepper.FORWARD:

                    state["angle"] += DEGREE_PER_STEP

                else:

                    state["angle"] -= DEGREE_PER_STEP


                # Giữ góc trong 0 -> 360
                state["angle"] %= 360.0


            # -----------------------------------------------
            # Delay giữa các step
            # -----------------------------------------------

            time.sleep(delay)


        # ----------------------------------------------------
        # Nhả motor sau khi quay xong
        # ----------------------------------------------------

        motor.release()


        # ----------------------------------------------------
        # Nếu đang chạy:
        # NGHỈ 1 GIÂY
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


            # ------------------------------------------------
            # Temperature
            # ------------------------------------------------

            if temperature is not None:

                with lock:

                    state["temperature"] = round(
                        temperature,
                        1
                    )


            # ------------------------------------------------
            # Humidity
            # ------------------------------------------------

            if humidity is not None:

                with lock:

                    state["humidity"] = round(
                        humidity,
                        1
                    )


        except RuntimeError:

            # DHT11 đôi khi lỗi đọc tạm thời
            pass


        except Exception as e:

            print(
                f"[DHT11 ERROR] {e}"
            )


        # DHT11 nên đọc khoảng 2 giây/lần
        time.sleep(2)


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

<title>DHT11 & Stepper</title>


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


/* ==========================================================
   DHT11
   ========================================================== */

.sensor {

    display: grid;

    grid-template-columns: 1fr 1fr;

    gap: 10px;

    margin-bottom: 14px;
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


/* ==========================================================
   MOTOR STATUS
   ========================================================== */

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


/* ==========================================================
   BUTTONS
   ========================================================== */

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


.speed {

    background: #374151;
}


.speed.active {

    background: #2563eb;
}


/* ==========================================================
   ANGLE
   ========================================================== */

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


/* ==========================================================
   CURRENT ANGLE
   ========================================================== */

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
     SPEED
     ===================================================== -->

<div class="row">


    <button
        class="speed"
        data-speed="1"
        onclick="setSpeed(1)"
    >
        CHẬM
    </button>


    <button
        class="speed"
        data-speed="2"
        onclick="setSpeed(2)"
    >
        VỪA
    </button>


    <button
        class="speed"
        data-speed="3"
        onclick="setSpeed(3)"
    >
        NHANH
    </button>


    <button
        class="speed"
        data-speed="4"
        onclick="setSpeed(4)"
    >
        MAX
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
            </span>°

        </strong>


    </div>


    <input
        id="angleSlider"
        type="range"
        min="1"
        max="180"
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
        </span>°

    </strong>


</div>


</div>

</div>


<script>


// ==========================================================
// SEND API
// ==========================================================

async function send(url) {

    try {

        const response =
            await fetch(url);


        const data =
            await response.json();


        updateUI(data);


    } catch (error) {

        console.error(error);

    }

}


// ==========================================================
// SPEED
// ==========================================================

async function setSpeed(speed) {

    await send(
        '/api/motor/speed/' + speed
    );

}


// ==========================================================
// ANGLE
// ==========================================================

async function setAngle(angle) {

    // Chỉ lấy số nguyên
    angle = Math.round(Number(angle));


    document.getElementById(
        'stepAngle'
    ).innerText = angle;


    await send(
        '/api/motor/angle/' + angle
    );

}


// ==========================================================
// UPDATE UI
// ==========================================================

function updateUI(data) {


    // ------------------------------------------------------
    // DHT11
    // ------------------------------------------------------

    document.getElementById(
        'temperature'
    ).innerText =
        data.temperature ?? '--';


    document.getElementById(
        'humidity'
    ).innerText =
        data.humidity ?? '--';


    // ------------------------------------------------------
    // MOTOR STATUS
    // ------------------------------------------------------

    document.getElementById(
        'motorStatus'
    ).innerText =
        data.running
            ? 'ĐANG CHẠY'
            : 'ĐANG DỪNG';


    // ------------------------------------------------------
    // DIRECTION
    // ------------------------------------------------------

    document.getElementById(
        'direction'
    ).innerText =
        data.direction === 'FORWARD'
            ? '↻ THUẬN'
            : '↺ NGƯỢC';


    // ------------------------------------------------------
    // CURRENT ANGLE
    // ------------------------------------------------------

    document.getElementById(
        'currentAngle'
    ).innerText =
        Math.round(Number(data.angle));


    // ------------------------------------------------------
    // STEP ANGLE
    // ------------------------------------------------------

    document.getElementById(
        'stepAngle'
    ).innerText =
        Math.round(Number(data.step_angle));


    // ------------------------------------------------------
    // SLIDER
    // ------------------------------------------------------

    document.getElementById(
        'angleSlider'
    ).value =
        Math.round(Number(data.step_angle));


    // ------------------------------------------------------
    // SPEED
    // ------------------------------------------------------

    document
        .querySelectorAll('.speed')
        .forEach(button => {

            button.classList.toggle(

                'active',

                Number(button.dataset.speed)
                === data.speed

            );

        });

}


// ==========================================================
// AUTO UPDATE
// ==========================================================

setInterval(async () => {

    try {

        const response =
            await fetch('/api/status');


        const data =
            await response.json();


        updateUI(data);


    } catch (error) {

        // Không làm gì nếu Raspberry Pi
        // tạm thời không phản hồi

    }

}, 500);


// ==========================================================
// LOAD INITIAL STATE
// ==========================================================

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

            "speed":
                state["speed"],

            "step_angle":
                state["step_angle"],

            "angle":
                state["angle"],

            "temperature":
                state["temperature"],

            "humidity":
                state["humidity"],

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
# DIRECTION
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
# SPEED
# ============================================================

@app.route("/api/motor/speed/<int:speed>")
def motor_speed(speed):

    if speed not in SPEED_DELAY:

        return jsonify({
            "error": "Invalid speed"
        }), 400


    with lock:

        state["speed"] = speed

        return jsonify(state)


# ============================================================
# ANGLE
# ============================================================

@app.route("/api/motor/angle/<int:angle>")
def motor_angle(angle):

    # Chỉ cho phép 1 -> 180 độ

    if angle < 1 or angle > 180:

        return jsonify({
            "error": "Angle must be between 1 and 180"
        }), 400


    with lock:

        state["step_angle"] = angle


        return jsonify(state)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("=" * 50)

    print("DHT11 + 28BYJ-48 WEB CONTROL")

    print("=" * 50)

    print("DHT11    : GPIO 4")

    print(
        "STEPPER  : GPIO 17, 18, 27, 22"
    )

    print(
        "ANGLE    : 1 - 180 degrees"
    )

    print(
        "PAUSE    : 1 second"
    )

    print(
        "WEB      : http://<RASPBERRY_PI_IP>:5000"
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

        print("\nĐang dừng hệ thống...")


    finally:

        # ----------------------------------------------------
        # Nhả motor
        # ----------------------------------------------------

        motor.release()


        # ----------------------------------------------------
        # Giải phóng GPIO
        # ----------------------------------------------------

        coil1.deinit()
        coil2.deinit()
        coil3.deinit()
        coil4.deinit()


        # ----------------------------------------------------
        # DHT11
        # ----------------------------------------------------

        dht.exit()


        print("Đã giải phóng GPIO.")
