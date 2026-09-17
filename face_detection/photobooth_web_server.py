# """Photobooth Web Server - chup hinh qua trinh duyet.

# Chay tren may co camera (laptop/webcam):
#     pip install flask opencv-python
#     python photobooth_web_server.py

# Mo trinh duyet:
#     http://127.0.0.1:5001/          (may local)
#     http://<LAN_IP>:5001/           (may khac trong cung mang)

# Trang web hoat dong nhu mot photobooth:
#     - Xem stream truc tiep tu camera
#     - Bam nut "Chup hinh" (co dem nguoc 3-2-1) de chup
#     - Anh vua chup duoc luu vao thu muc ./captures/ va hien ngay tren trang
#     - Danh sach anh da chup hien ben duoi de xem/tai lai

# Day la file rieng, doc lap voi laptop_cam_server.py (server stream cho Pi).
# """
# import os
# import socket
# import time
# from datetime import datetime

# import cv2
# from flask import Flask, Response, jsonify, render_template_string, send_from_directory

# # --- Cau hinh ---
# CAMERA_INDEX = 0
# FRAME_WIDTH = 640
# FRAME_HEIGHT = 480
# JPEG_QUALITY = 85
# PORT = 5001
# MIRROR = True  # lat ngang anh cho giong soi guong

# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# CAPTURE_DIR = os.path.join(BASE_DIR, "captures")
# os.makedirs(CAPTURE_DIR, exist_ok=True)

# app = Flask(__name__)

# cap = cv2.VideoCapture(CAMERA_INDEX)
# try:
#     cap_test = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
#     if cap_test.isOpened():
#         cap.release()
#         cap = cap_test
#     else:
#         cap_test.release()
# except Exception:
#     pass

# cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
# cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

# INDEX_HTML = """
# <!doctype html>
# <html lang="vi">
# <head>
# <meta charset="utf-8">
# <meta name="viewport" content="width=device-width, initial-scale=1">
# <title>Photobooth</title>
# <style>
#   body { background:#111; color:#fff; font-family:Arial, sans-serif; text-align:center; margin:0; padding:20px; }
#   h1 { margin-bottom:4px; }
#   .stage { position:relative; display:inline-block; }
#   .stage img#stream { width:640px; max-width:95vw; border:4px solid #333; border-radius:8px; }
#   .countdown {
#     position:absolute; top:0; left:0; width:100%; height:100%;
#     display:none; align-items:center; justify-content:center;
#     font-size:8rem; font-weight:bold; color:#fff; text-shadow:0 0 20px #000;
#     background:rgba(0,0,0,0.25);
#   }
#   .flash {
#     position:absolute; top:0; left:0; width:100%; height:100%;
#     background:#fff; opacity:0; pointer-events:none;
#   }
#   .flash.on { animation: flash-anim 0.4s ease-out; }
#   @keyframes flash-anim { 0% { opacity:0.9; } 100% { opacity:0; } }
#   button#shutter {
#     margin-top:16px; padding:14px 32px; font-size:1.2rem; font-weight:bold;
#     border:none; border-radius:30px; background:#e63946; color:#fff; cursor:pointer;
#   }
#   button#shutter:disabled { background:#666; cursor:not-allowed; }
#   #last-shot img { width:200px; border-radius:8px; border:2px solid #444; margin-top:8px; }
#   #gallery { display:flex; flex-wrap:wrap; gap:8px; justify-content:center; margin-top:16px; max-width:900px; margin-left:auto; margin-right:auto; }
#   #gallery img { width:110px; height:82px; object-fit:cover; border-radius:6px; border:1px solid #333; }
#   a { color:#8ecae6; }
# </style>
# </head>
# <body>
#   <h1>Photobooth</h1>
#   <p>Bam nut de chup hinh (co dem nguoc 3 giay)</p>

#   <div class="stage">
#     <img id="stream" src="/video_feed" alt="camera stream">
#     <div class="countdown" id="countdown"></div>
#     <div class="flash" id="flash"></div>
#   </div>
#   <br>
#   <button id="shutter" onclick="startCountdown()">📸 Chup hinh</button>

#   <div id="last-shot"></div>

#   <h3>Anh da chup</h3>
#   <div id="gallery"></div>

# <script>
# const countdownEl = document.getElementById('countdown');
# const flashEl = document.getElementById('flash');
# const shutterBtn = document.getElementById('shutter');
# const lastShotEl = document.getElementById('last-shot');
# const galleryEl = document.getElementById('gallery');

# function startCountdown() {
#   shutterBtn.disabled = true;
#   let n = 3;
#   countdownEl.style.display = 'flex';
#   countdownEl.textContent = n;
#   const timer = setInterval(() => {
#     n -= 1;
#     if (n > 0) {
#       countdownEl.textContent = n;
#     } else {
#       clearInterval(timer);
#       countdownEl.style.display = 'none';
#       doCapture();
#     }
#   }, 1000);
# }

# async function doCapture() {
#   flashEl.classList.remove('on');
#   void flashEl.offsetWidth; // reset animation
#   flashEl.classList.add('on');
#   try {
#     const res = await fetch('/capture', { method: 'POST' });
#     const data = await res.json();
#     if (data.ok) {
#       showLastShot(data.url);
#       loadGallery();
#     } else {
#       alert('Chup that bai: ' + (data.error || 'unknown'));
#     }
#   } catch (e) {
#     alert('Loi ket noi server: ' + e);
#   } finally {
#     shutterBtn.disabled = false;
#   }
# }

# function showLastShot(url) {
#   lastShotEl.innerHTML = '<p>Anh vua chup:</p><img src="' + url + '?t=' + Date.now() + '">';
# }

# async function loadGallery() {
#   try {
#     const res = await fetch('/captures_list');
#     const data = await res.json();
#     galleryEl.innerHTML = '';
#     data.files.forEach(f => {
#       const a = document.createElement('a');
#       a.href = '/captures/' + f;
#       a.target = '_blank';
#       const img = document.createElement('img');
#       img.src = '/captures/' + f;
#       a.appendChild(img);
#       galleryEl.appendChild(a);
#     });
#   } catch (e) {
#     console.error(e);
#   }
# }

# loadGallery();
# </script>
# </body>
# </html>
# """


# def get_lan_ip():
#     try:
#         s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#         s.connect(("8.8.8.8", 80))
#         ip = s.getsockname()[0]
#         s.close()
#         return ip
#     except Exception:
#         return "127.0.0.1"


# def read_frame():
#     ok, frame = cap.read()
#     if not ok:
#         return None
#     if MIRROR:
#         frame = cv2.flip(frame, 1)
#     return frame


# def gen_mjpeg():
#     while True:
#         frame = read_frame()
#         if frame is None:
#             continue
#         ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
#         if not ok:
#             continue
#         yield (
#             b"--frame\r\n"
#             b"Content-Type: image/jpeg\r\n\r\n"
#             + buf.tobytes()
#             + b"\r\n"
#         )


# @app.route("/")
# def index():
#     return render_template_string(INDEX_HTML)


# @app.route("/video_feed")
# def video_feed():
#     return Response(
#         gen_mjpeg(),
#         mimetype="multipart/x-mixed-replace; boundary=frame",
#     )


# @app.route("/capture", methods=["POST"])
# def capture():
#     frame = read_frame()
#     if frame is None:
#         return jsonify(ok=False, error="Khong doc duoc camera"), 500

#     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
#     filename = f"photo_{timestamp}.jpg"
#     filepath = os.path.join(CAPTURE_DIR, filename)

#     ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
#     if not ok:
#         return jsonify(ok=False, error="Loi encode anh"), 500

#     with open(filepath, "wb") as f:
#         f.write(buf.tobytes())

#     return jsonify(ok=True, filename=filename, url=f"/captures/{filename}")


# @app.route("/captures/<path:filename>")
# def get_capture(filename):
#     return send_from_directory(CAPTURE_DIR, filename)


# @app.route("/captures_list")
# def captures_list():
#     files = [f for f in os.listdir(CAPTURE_DIR) if f.lower().endswith(".jpg")]
#     files.sort(reverse=True)
#     return jsonify(files=files)


# if __name__ == "__main__":
#     if not cap.isOpened():
#         print(f"LOI: khong mo duoc camera index {CAMERA_INDEX}")
#     else:
#         print("=" * 50)
#         print("PHOTOBOOTH WEB SERVER")
#         print("=" * 50)
#         print(f"LAN IP     : {get_lan_ip()}")
#         print(f"Mo trinh duyet : http://127.0.0.1:{PORT}/")
#         print(f"May khac       : http://{get_lan_ip()}:{PORT}/")
#         print(f"Anh luu tai    : {CAPTURE_DIR}")
#         print("=" * 50)
#     app.run(host="0.0.0.0", port=PORT, threaded=True)
