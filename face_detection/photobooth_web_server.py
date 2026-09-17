"""Photobooth Web Server - chup hinh qua trinh duyet (ban cam REMOTE).

Kien truc:
    laptop_cam_server.py (port 5000)  -> phat cam tho
    photobooth_web_server.py (port 5001) -> doc stream remote, gan hieu ung, phat lai + nut chup

Chay:
    pip install flask opencv-python numpy
    # 1. Chay server cam truoc (may co camera):
    python laptop_cam_server.py
    # 2. Chay photobooth web:
    python photobooth_web_server.py

Mo trinh duyet:
    http://127.0.0.1:5001/   (may local)
    http://<LAN_IP>:5001/    (may khac cung mang)
"""

import os
import socket
import time
import threading
from datetime import datetime

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template_string, send_from_directory

# --- Khai bao CAMERA REMOTE (sua o day neu laptop doi IP/port) ---
CAMERA_SOURCE = "http://10.70.66.91:5000/video_feed"
# Muon ve cam local thi doi thanh: CAMERA_SOURCE = 0

FRAME_WIDTH = 640
FRAME_HEIGHT = 480
JPEG_QUALITY = 85
PORT = 5001
MIRROR = True  # lat ngang cho giong soi guong

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Anh overlay co the nam cung folder hoac folder nhandienkhuonmat ben canh
SEARCH_DIRS = [BASE_DIR, os.path.join(os.path.dirname(BASE_DIR), "nhandienkhuonmat")]


def find_file(filename):
    for d in SEARCH_DIRS:
        p = os.path.join(d, filename)
        if os.path.exists(p):
            return p
    return os.path.join(BASE_DIR, filename)  # mac dinh de bao loi ro


FACE_CASCADE_PATH = find_file("haarcascade_frontalface_default.xml")
EYE_CASCADE_PATH = find_file("haarcascade_eye.xml")
NOSE_CASCADE_PATH = find_file("haarcascade_mcs_nose.xml")

OVERLAYS_CONFIG = {
    "hat": {"name": "Mu", "image_path": find_file("mu.png"),
            "scale_w": 1.25, "offset_y_ratio": -0.72},
    "glasses": {"name": "Kinh mat", "image_path": find_file("sunglasses.png"),
                "scale_w": 0.88, "fallback_y_ratio": 0.4},
    "mustache": {"name": "Ria mep", "image_path": find_file("rau2.png"),
                 "scale_w": 0.55, "fallback_y_ratio": 0.66},
}

CAPTURE_DIR = os.path.join(BASE_DIR, "captures")
os.makedirs(CAPTURE_DIR, exist_ok=True)

app = Flask(__name__)

loaded_cascades = {}
loaded_overlays = {}


def load_rgba_image(filepath):
    if not os.path.exists(filepath):
        print(f"[Canh bao] Khong tim thay file: {filepath}")
        return None
    img = cv2.imread(filepath, cv2.IMREAD_UNCHANGED)
    if img is None:
        print(f"[Canh bao] Khong doc duoc anh: {filepath}")
        return None
    if len(img.shape) == 3 and img.shape[2] == 4:
        return {"rgb": img[:, :, :3], "mask": img[:, :, 3]}
    return {"rgb": img, "mask": np.ones((img.shape[0], img.shape[1]), dtype=np.uint8) * 255}


def initialize_resources():
    print(f"[+] Nguon camera REMOTE: {CAMERA_SOURCE}")
    face_cc = cv2.CascadeClassifier(FACE_CASCADE_PATH)
    if face_cc.empty():
        print(f"[LOI] Khong tai duoc face cascade: {FACE_CASCADE_PATH}")
    else:
        loaded_cascades["face"] = face_cc
    for name, path in [("eye", EYE_CASCADE_PATH), ("nose", NOSE_CASCADE_PATH)]:
        if os.path.exists(path):
            cc = cv2.CascadeClassifier(path)
            if not cc.empty():
                loaded_cascades[name] = cc
    for key, cfg in OVERLAYS_CONFIG.items():
        data = load_rgba_image(cfg["image_path"])
        if data is not None:
            loaded_overlays[key] = data
            print(f"    -> Da nap: {cfg['name']} ({cfg['image_path']})")
        else:
            print(f"    -> Thieu anh {cfg['name']}: {cfg['image_path']}")


def overlay_image_alpha(img, img_overlay, x, y, alpha_mask):
    try:
        h, w = img_overlay.shape[0], img_overlay.shape[1]
        img_h, img_w = img.shape[0], img.shape[1]
        y1, y2 = max(0, y), min(img_h, y + h)
        x1, x2 = max(0, x), min(img_w, x + w)
        if x1 >= x2 or y1 >= y2:
            return img
        ov_y1 = max(0, -y)
        ov_y2 = ov_y1 + (y2 - y1)
        ov_x1 = max(0, -x)
        ov_x2 = ov_x1 + (x2 - x1)
        roi = img[y1:y2, x1:x2]
        crop_overlay = img_overlay[ov_y1:ov_y2, ov_x1:ov_x2]
        crop_alpha = alpha_mask[ov_y1:ov_y2, ov_x1:ov_x2]
        alpha = crop_alpha.astype(float) / 255.0
        alpha = np.dstack([alpha, alpha, alpha])
        img[y1:y2, x1:x2] = ((1.0 - alpha) * roi.astype(float) + alpha * crop_overlay.astype(float)).astype(np.uint8)
    except Exception as e:
        print(f"[Loi Overlay] {e}")
    return img


def apply_all_overlays(frame):
    if "face" not in loaded_cascades:
        return frame
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = loaded_cascades["face"].detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    if len(faces) == 0:
        return frame
    for (x, y, w, h) in faces:
        face_roi_gray = gray[y:y + h, x:x + w]
        # 1. Mu
        if "hat" in loaded_overlays:
            hat_rgb = loaded_overlays["hat"]["rgb"]
            hat_mask = loaded_overlays["hat"]["mask"]
            cfg_h = OVERLAYS_CONFIG["hat"]
            target_w = int(w * cfg_h["scale_w"])
            target_h = int(target_w * (hat_rgb.shape[0] / hat_rgb.shape[1]))
            target_x = x + (w // 2) - (target_w // 2)
            target_y = y + int(target_h * cfg_h["offset_y_ratio"])
            if target_w > 0 and target_h > 0:
                frame = overlay_image_alpha(frame,
                    cv2.resize(hat_rgb, (target_w, target_h), interpolation=cv2.INTER_AREA),
                    target_x, target_y,
                    cv2.resize(hat_mask, (target_w, target_h), interpolation=cv2.INTER_AREA))
        # 2. Kinh
        if "glasses" in loaded_overlays:
            g_rgb = loaded_overlays["glasses"]["rgb"]
            g_mask = loaded_overlays["glasses"]["mask"]
            cfg_g = OVERLAYS_CONFIG["glasses"]
            target_w = int(w * cfg_g["scale_w"])
            target_h = int(target_w * (g_rgb.shape[0] / g_rgb.shape[1]))
            target_x = x + (w // 2) - (target_w // 2)
            eye_y = y + int(h * cfg_g["fallback_y_ratio"])
            if "eye" in loaded_cascades:
                roi_top, roi_bottom = max(0, int(h * 0.08)), int(h * 0.42)
                eye_roi = face_roi_gray[roi_top:roi_bottom, :]
                eyes = loaded_cascades["eye"].detectMultiScale(eye_roi, scaleFactor=1.1, minNeighbors=6, minSize=(15, 15))
                if len(eyes) >= 2:
                    eyes = sorted(eyes, key=lambda e: e[0])
                    for i in range(len(eyes) - 1):
                        for j in range(i + 1, len(eyes)):
                            e1, e2 = eyes[i], eyes[j]
                            dx = abs((e2[0] + e2[2] // 2) - (e1[0] + e1[2] // 2))
                            dy = abs((e1[1] + e1[3] // 2) - (e2[1] + e2[3] // 2))
                            if dx >= int(w * 0.20) and dy <= int(h * 0.08):
                                cx = x + int((e1[0] + e2[0] + e2[2]) / 2)
                                cy = y + roi_top + int((e1[1] + e2[1] + (e1[3] + e2[3]) // 2) / 2)
                                target_x = cx - (target_w // 2)
                                eye_y = cy
                                break
            target_y = eye_y - int(target_h * 0.52)
            if target_w > 0 and target_h > 0:
                frame = overlay_image_alpha(frame,
                    cv2.resize(g_rgb, (target_w, target_h), interpolation=cv2.INTER_AREA),
                    target_x, target_y,
                    cv2.resize(g_mask, (target_w, target_h), interpolation=cv2.INTER_AREA))
        # 3. Ria
        if "mustache" in loaded_overlays:
            m_rgb = loaded_overlays["mustache"]["rgb"]
            m_mask = loaded_overlays["mustache"]["mask"]
            cfg_m = OVERLAYS_CONFIG["mustache"]
            target_w = int(w * cfg_m["scale_w"])
            target_h = int(target_w * (m_rgb.shape[0] / m_rgb.shape[1]))
            target_x = x + (w // 2) - (target_w // 2)
            nose_found = False
            if "nose" in loaded_cascades:
                noses = loaded_cascades["nose"].detectMultiScale(face_roi_gray, 1.1, 5, minSize=(20, 20))
                if len(noses) > 0:
                    noses = sorted(noses, key=lambda n: n[2] * n[3], reverse=True)
                    nx, ny, nw, nh = noses[0]
                    target_y = y + ny + int(nh * 0.72) - (target_h // 2)
                    nose_found = True
            if not nose_found:
                target_y = y + int(h * cfg_m["fallback_y_ratio"]) - (target_h // 2)
            if target_w > 0 and target_h > 0:
                frame = overlay_image_alpha(frame,
                    cv2.resize(m_rgb, (target_w, target_h), interpolation=cv2.INTER_AREA),
                    target_x, target_y,
                    cv2.resize(m_mask, (target_w, target_h), interpolation=cv2.INTER_AREA))
    return frame


# --- Doc camera REMOTE 1 luong duy nhat, share cho moi client ---
cap_lock = threading.Lock()
latest_processed = None
latest_raw = None
cap = None


def open_camera(source):
    print(f"Dang ket noi camera: {source}")
    c = cv2.VideoCapture(source)
    if isinstance(source, int):
        c.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        c.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    return c


def camera_loop():
    global cap, latest_raw, latest_processed
    fail_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            fail_count += 1
            if fail_count >= 30:
                print("Mat stream remote, thu ket noi lai...")
                try:
                    cap.release()
                except Exception:
                    pass
                time.sleep(1.0)
                cap = open_camera(CAMERA_SOURCE)
                fail_count = 0
            else:
                time.sleep(0.1)
            continue
        fail_count = 0
        if MIRROR:
            frame = cv2.flip(frame, 1)
        processed = apply_all_overlays(frame)
        with cap_lock:
            latest_raw = frame
            latest_processed = processed


INDEX_HTML = """
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Photobooth (cam remote)</title>
<style>
  body { background:#111; color:#fff; font-family:Arial, sans-serif; text-align:center; margin:0; padding:20px; }
  h1 { margin-bottom:4px; }
  .sub { color:#aaa; font-size:14px; margin-bottom:12px; }
  .stage { position:relative; display:inline-block; }
  .stage img#stream { width:640px; max-width:95vw; border:4px solid #333; border-radius:8px; }
  .countdown {
    position:absolute; top:0; left:0; width:100%; height:100%;
    display:none; align-items:center; justify-content:center;
    font-size:8rem; font-weight:bold; color:#fff; text-shadow:0 0 20px #000;
    background:rgba(0,0,0,0.25);
  }
  .flash {
    position:absolute; top:0; left:0; width:100%; height:100%;
    background:#fff; opacity:0; pointer-events:none;
  }
  .flash.on { animation: flash-anim 0.4s ease-out; }
  @keyframes flash-anim { 0% { opacity:0.9; } 100% { opacity:0; } }
  button#shutter {
    margin-top:16px; padding:14px 32px; font-size:1.2rem; font-weight:bold;
    border:none; border-radius:30px; background:#e63946; color:#fff; cursor:pointer;
  }
  button#shutter:disabled { background:#666; cursor:not-allowed; }
  #last-shot img { width:200px; border-radius:8px; border:2px solid #444; margin-top:8px; }
  #gallery { display:flex; flex-wrap:wrap; gap:8px; justify-content:center; margin-top:16px; max-width:900px; margin-left:auto; margin-right:auto; }
  #gallery img { width:110px; height:82px; object-fit:cover; border-radius:6px; border:1px solid #333; }
  a { color:#8ecae6; }
</style>
</head>
<body>
  <h1>Photobooth (cam remote)</h1>
  <div class="sub">Nguon: __CAMERA_SOURCE__ | Stream da gan mu + kinh + ria</div>

  <div class="stage">
    <img id="stream" src="/video_feed" alt="camera stream">
    <div class="countdown" id="countdown"></div>
    <div class="flash" id="flash"></div>
  </div>
  <br>
  <button id="shutter" onclick="startCountdown()">Chup hinh</button>

  <div id="last-shot"></div>

  <h3>Anh da chup</h3>
  <div id="gallery"></div>

<script>
const countdownEl = document.getElementById('countdown');
const flashEl = document.getElementById('flash');
const shutterBtn = document.getElementById('shutter');
const lastShotEl = document.getElementById('last-shot');
const galleryEl = document.getElementById('gallery');

function startCountdown() {
  shutterBtn.disabled = true;
  let n = 3;
  countdownEl.style.display = 'flex';
  countdownEl.textContent = n;
  const timer = setInterval(() => {
    n -= 1;
    if (n > 0) {
      countdownEl.textContent = n;
    } else {
      clearInterval(timer);
      countdownEl.style.display = 'none';
      doCapture();
    }
  }, 1000);
}

async function doCapture() {
  flashEl.classList.remove('on');
  void flashEl.offsetWidth;
  flashEl.classList.add('on');
  try {
    const res = await fetch('/capture', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      showLastShot(data.url);
      loadGallery();
    } else {
      alert('Chup that bai: ' + (data.error || 'unknown'));
    }
  } catch (e) {
    alert('Loi ket noi server: ' + e);
  } finally {
    shutterBtn.disabled = false;
  }
}

function showLastShot(url) {
  lastShotEl.innerHTML = '<p>Anh vua chup:</p><img src="' + url + '?t=' + Date.now() + '">';
}

async function loadGallery() {
  try {
    const res = await fetch('/captures_list');
    const data = await res.json();
    galleryEl.innerHTML = '';
    data.files.forEach(f => {
      const a = document.createElement('a');
      a.href = '/captures/' + f;
      a.target = '_blank';
      const img = document.createElement('img');
      img.src = '/captures/' + f;
      a.appendChild(img);
      galleryEl.appendChild(a);
    });
  } catch (e) {
    console.error(e);
  }
}

loadGallery();
</script>
</body>
</html>
""".replace("__CAMERA_SOURCE__", str(CAMERA_SOURCE))


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def gen_mjpeg():
    while True:
        with cap_lock:
            frame = None if latest_processed is None else latest_processed.copy()
        if frame is None:
            time.sleep(0.05)
            continue
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/video_feed")
def video_feed():
    return Response(gen_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/capture", methods=["POST"])
def capture():
    with cap_lock:
        frame = None if latest_processed is None else latest_processed.copy()
    if frame is None:
        return jsonify(ok=False, error="Chua co frame tu cam remote"), 500
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    filename = f"photo_{timestamp}.jpg"
    filepath = os.path.join(CAPTURE_DIR, filename)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        return jsonify(ok=False, error="Loi encode anh"), 500
    with open(filepath, "wb") as f:
        f.write(buf.tobytes())
    return jsonify(ok=True, filename=filename, url=f"/captures/{filename}")


@app.route("/captures/<path:filename>")
def get_capture(filename):
    return send_from_directory(CAPTURE_DIR, filename)


@app.route("/captures_list")
def captures_list():
    files = [f for f in os.listdir(CAPTURE_DIR) if f.lower().endswith(".jpg")]
    files.sort(reverse=True)
    return jsonify(files=files)


if __name__ == "__main__":
    initialize_resources()
    cap = open_camera(CAMERA_SOURCE)
    if not cap.isOpened():
        print(f"[LOI] Khong mo duoc cam remote: {CAMERA_SOURCE}")
        print(" -> Kiem tra laptop_cam_server.py da chay chua (port 5000).")
    else:
        print("=" * 50)
        print("PHOTOBOOTH WEB SERVER (CAM REMOTE)")
        print("=" * 50)
        print(f"Nguon remote : {CAMERA_SOURCE}")
        print(f"LAN IP       : {get_lan_ip()}")
        print(f"Mo trinh duyet: http://127.0.0.1:{PORT}/")
        print(f"May khac      : http://{get_lan_ip()}:{PORT}/")
        print(f"Anh luu tai   : {CAPTURE_DIR}")
        print("=" * 50)
    threading.Thread(target=camera_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
