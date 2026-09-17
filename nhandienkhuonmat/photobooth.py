import cv2
import time
import sys
import os
import argparse
import numpy as np

# Thử import RPi.GPIO (khi chạy trực tiếp trên Raspberry Pi)
try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except (ImportError, RuntimeError):
    HAS_GPIO = False

# --- Cấu hình thư mục hiện tại ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_path(filename):
    return os.path.join(BASE_DIR, filename)

# --- Cấu hình Camera & Cửa sổ hiển thị ---
CAMERA_RESOLUTION = (640, 480)
DISPLAY_WINDOW_NAME = "Photobooth Raspberry Pi"
SAVE_PREFIX = BASE_DIR + os.sep

# --- Cấu hình Nút Bấm Vật Lý (GPIO 24) ---
BUTTON_PIN = 24
DEBOUNCE_TIME = 0.3

# --- Cấu hình Cascades ---
FACE_CASCADE_PATH = get_path('haarcascade_frontalface_default.xml')
EYE_CASCADE_PATH = get_path('haarcascade_eye.xml')
NOSE_CASCADE_PATH = get_path('haarcascade_mcs_nose.xml')

# --- Cấu hình Hiệu ứng Lớp phủ (Mũ, Kính mắt, Râu) ---
OVERLAYS_CONFIG = {
    "hat": {
        "name": "Mũ",
        "image_path": get_path("mu.png"),
        "scale_w": 1.25,        # Chiều rộng mũ = 1.25 lần chiều rộng mặt
        "offset_y_ratio": -0.72  # Đặt phía trên đỉnh trán
    },
    "glasses": {
        "name": "Kính mắt",
        "image_path": get_path("sunglasses.png"),
        "scale_w": 0.88,         # Kính rộng khoảng 88% khuôn mặt
        "fallback_y_ratio": 0.4 # Vị trí mắt chuẩn ngang tầm mắt
    },
    "mustache": {
        "name": "Ria mép",
        "image_path": get_path("rau2.png"),
        "scale_w": 0.55,         # Râu rộng khoảng 55% khuôn mặt
        "fallback_y_ratio": 0.66 # Đặt vị trí dưới mũi, trên miệng
    }
}

loaded_cascades = {}
loaded_overlays = {}

def load_rgba_image(filepath):
    """Tải ảnh và tách RGB cùng Alpha mask."""
    if not os.path.exists(filepath):
        print(f"[Cảnh báo] Không tìm thấy file: {filepath}")
        return None
    img = cv2.imread(filepath, cv2.IMREAD_UNCHANGED)
    if img is None:
        print(f"[Cảnh báo] Không thể đọc ảnh: {filepath}")
        return None
    if img.shape[2] == 4:
        return {'rgb': img[:, :, :3], 'mask': img[:, :, 3]}
    else:
        return {'rgb': img, 'mask': np.ones((img.shape[0], img.shape[1]), dtype=np.uint8) * 255}

def initialize_resources():
    print("[+] Đang nạp mô hình Haar Cascades...")
    if not os.path.exists(FACE_CASCADE_PATH):
        print(f"[LỖI] Không tìm thấy file: {FACE_CASCADE_PATH}")
        sys.exit(1)
    
    face_cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)
    if face_cascade.empty():
        print(f"[LỖI] Không thể đọc face cascade tại {FACE_CASCADE_PATH}")
        sys.exit(1)
    loaded_cascades['face'] = face_cascade

    if os.path.exists(EYE_CASCADE_PATH):
        eye_cascade = cv2.CascadeClassifier(EYE_CASCADE_PATH)
        if not eye_cascade.empty():
            loaded_cascades['eye'] = eye_cascade

    if os.path.exists(NOSE_CASCADE_PATH):
        nose_cascade = cv2.CascadeClassifier(NOSE_CASCADE_PATH)
        if not nose_cascade.empty():
            loaded_cascades['nose'] = nose_cascade

    print("[+] Đang nạp hình ảnh các lớp phủ: Mũ, Kính mắt và Râu...")
    for key, cfg in OVERLAYS_CONFIG.items():
        data = load_rgba_image(cfg['image_path'])
        if data is not None:
            loaded_overlays[key] = data
            print(f"    -> Đã nạp thành công: {cfg['name']} ({cfg['image_path']})")
        else:
            print(f"    -> [!] Thiếu file ảnh {cfg['name']}: {cfg['image_path']}")

def overlay_image_alpha(img, img_overlay, x, y, alpha_mask):
    """Ghép ảnh lớp phủ PNG có kênh Alpha vào khung hình gốc."""
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

        roi_blended = (1.0 - alpha) * roi.astype(float) + alpha * crop_overlay.astype(float)
        img[y1:y2, x1:x2] = roi_blended.astype(np.uint8)
    except Exception as e:
        print(f"[Lỗi Overlay] {e}")
    return img

def apply_all_overlays(frame):
    """Tự động phát hiện khuôn mặt và gắn Mũ + Kính mắt + Râu vào khung hình."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    faces = loaded_cascades['face'].detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(60, 60)
    )

    if len(faces) == 0:
        return frame

    for (x, y, w, h) in faces:
        face_roi_gray = gray[y:y+h, x:x+w]

        # 1. GẮN MŨ (HAT) LÊN ĐỈNH ĐẦU
        if "hat" in loaded_overlays:
            hat_rgb = loaded_overlays["hat"]['rgb']
            hat_mask = loaded_overlays["hat"]['mask']
            cfg_h = OVERLAYS_CONFIG["hat"]

            target_w = int(w * cfg_h['scale_w'])
            target_h = int(target_w * (hat_rgb.shape[0] / hat_rgb.shape[1]))
            target_x = x + (w // 2) - (target_w // 2)
            target_y = y + int(target_h * cfg_h['offset_y_ratio'])

            if target_w > 0 and target_h > 0:
                resized_hat = cv2.resize(hat_rgb, (target_w, target_h), interpolation=cv2.INTER_AREA)
                resized_mask = cv2.resize(hat_mask, (target_w, target_h), interpolation=cv2.INTER_AREA)
                frame = overlay_image_alpha(frame, resized_hat, target_x, target_y, resized_mask)

        # 2. GẮN KÍNH MẮT (GLASSES) - ĐƯA LÊN ĐÚNG VỊ TRÍ MẮT
        if "glasses" in loaded_overlays:
            g_rgb = loaded_overlays["glasses"]['rgb']
            g_mask = loaded_overlays["glasses"]['mask']
            cfg_g = OVERLAYS_CONFIG["glasses"]

            target_w = int(w * cfg_g['scale_w'])
            target_h = int(target_w * (g_rgb.shape[0] / g_rgb.shape[1]))
            target_x = x + (w // 2) - (target_w // 2)

            eye_y = y + int(h * cfg_g['fallback_y_ratio'])
            eyes_found = False

            if 'eye' in loaded_cascades:
                roi_top = max(0, int(h * 0.08))
                roi_bottom = int(h * 0.42)
                eye_roi = face_roi_gray[roi_top:roi_bottom, :]
                eyes = loaded_cascades['eye'].detectMultiScale(
                    eye_roi,
                    scaleFactor=1.1,
                    minNeighbors=6,
                    minSize=(15, 15)
                )
                if len(eyes) >= 2:
                    eyes = sorted(eyes, key=lambda e: e[0])
                    for i in range(len(eyes) - 1):
                        for j in range(i + 1, len(eyes)):
                            e1, e2 = eyes[i], eyes[j]
                            dx = abs((e2[0] + e2[2] // 2) - (e1[0] + e1[2] // 2))
                            dy = abs((e1[1] + e1[3] // 2) - (e2[1] + e2[3] // 2))
                            if dx >= int(w * 0.20) and dy <= int(h * 0.08):
                                center_eye_x = x + int((e1[0] + e2[0] + e2[2]) / 2)
                                center_eye_y = y + roi_top + int((e1[1] + e2[1] + (e1[3] + e2[3]) // 2) / 2)
                                target_x = center_eye_x - (target_w // 2)
                                eye_y = center_eye_y
                                eyes_found = True
                                break
                        if eyes_found:
                            break

            target_y = eye_y - int(target_h * 0.52)

            if target_w > 0 and target_h > 0:
                resized_g = cv2.resize(g_rgb, (target_w, target_h), interpolation=cv2.INTER_AREA)
                resized_mask = cv2.resize(g_mask, (target_w, target_h), interpolation=cv2.INTER_AREA)
                frame = overlay_image_alpha(frame, resized_g, target_x, target_y, resized_mask)

        # 3. GẮN RIA MÉP (MUSTACHE)
        if "mustache" in loaded_overlays:
            m_rgb = loaded_overlays["mustache"]['rgb']
            m_mask = loaded_overlays["mustache"]['mask']
            cfg_m = OVERLAYS_CONFIG["mustache"]

            target_w = int(w * cfg_m['scale_w'])
            target_h = int(target_w * (m_rgb.shape[0] / m_rgb.shape[1]))
            target_x = x + (w // 2) - (target_w // 2)

            nose_found = False
            if 'nose' in loaded_cascades:
                noses = loaded_cascades['nose'].detectMultiScale(face_roi_gray, 1.1, 5, minSize=(20, 20))
                if len(noses) > 0:
                    noses = sorted(noses, key=lambda n: n[2] * n[3], reverse=True)
                    nx, ny, nw, nh = noses[0]
                    target_y = y + ny + int(nh * 0.72) - (target_h // 2)
                    nose_found = True

            if not nose_found:
                target_y = y + int(h * cfg_m['fallback_y_ratio']) - (target_h // 2)

            if target_w > 0 and target_h > 0:
                resized_m = cv2.resize(m_rgb, (target_w, target_h), interpolation=cv2.INTER_AREA)
                resized_mask = cv2.resize(m_mask, (target_w, target_h), interpolation=cv2.INTER_AREA)
                frame = overlay_image_alpha(frame, resized_m, target_x, target_y, resized_mask)

    return frame

def main():
    parser = argparse.ArgumentParser(description="Photobooth Raspberry Pi: Gan Mu, Kinh & Rau")
    parser.add_argument("source_pos", nargs="?", default=None, help="Nguon camera (0, 1 hoac URL stream)")
    parser.add_argument("--source", "-s", default="http://10.70.66.91:5000/video_feed", help="Nguon camera (Mac dinh: http://10.70.66.91:5000/video_feed)")
    args = parser.parse_args()

    raw_source = args.source_pos if args.source_pos is not None else args.source
    if raw_source.isdigit():
        camera_source = int(raw_source)
    else:
        camera_source = raw_source

    initialize_resources()

    # Khởi tạo nút bấm GPIO 24 trên Raspberry Pi
    if HAS_GPIO:
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            print(f"[+] Đã cấu hình nút bấm vật lý tại chân GPIO {BUTTON_PIN} trên Raspberry Pi.")
        except Exception as e:
            print(f"[!] Lỗi khởi tạo GPIO: {e}")
    else:
        print("[i] Chế độ máy tính: Nhấn phím 'c' hoặc 'Space' trên bàn phím để chụp ảnh.")

    print(f"[+] Đang kết nối nguồn camera: {camera_source} ...")
    cap = cv2.VideoCapture(camera_source)
    if not cap.isOpened():
        print(f"\n[LỖI] Không thể mở nguồn camera: {camera_source}")
        sys.exit(1)

    # Đặt độ phân giải và tạo cửa sổ hiển thị trực tiếp
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_RESOLUTION[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_RESOLUTION[1])
    cv2.namedWindow(DISPLAY_WINDOW_NAME, cv2.WINDOW_NORMAL)

    print("\n" + "="*60)
    print("  PHOTOBOOTH RASPBERRY PI ĐANG CHẠY TRỰC TIẾP TRÊN MÀN HÌNH!")
    print("="*60)
    print(f"  * Nguồn hình ảnh : {camera_source}")
    print("  * Tự động gắn    : Mũ, Kính mắt & Ria mép realtime")
    print(f"  * Chụp ảnh       : Bấm nút vật lý (Chân GPIO {BUTTON_PIN}) hoặc phím 'c' / 'Space'")
    print("  * Thoát          : Nhấn phím 'q'")
    print("="*60 + "\n")

    last_button_state = False
    button_press_time = 0.0
    saved_notice_until = 0.0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.02)
                continue

            # Lật gương khung hình để nhìn tự nhiên
            frame = cv2.flip(frame, 1)

            # TỰ ĐỘNG GẮN CẢ MŨ, KÍNH MẮT VÀ RÂU
            processed_frame = apply_all_overlays(frame)

            # Kiểm tra nút bấm vật lý trên Pi (Chân GPIO 24)
            capture_triggered = False
            if HAS_GPIO:
                current_state = GPIO.input(BUTTON_PIN) == GPIO.HIGH
                if current_state and not last_button_state and (time.time() - button_press_time > DEBOUNCE_TIME):
                    capture_triggered = True
                    button_press_time = time.time()
                last_button_state = current_state

            # Kiểm tra phím bấm trên bàn phím (Phím 'c', 'Space' hoặc 'q')
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('c') or key == 32:  # 'c' hoặc Space
                capture_triggered = True

            # Xử lý khi có sự kiện chụp ảnh
            if capture_triggered:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"{SAVE_PREFIX}photobooth_{timestamp}.jpg"
                cv2.imwrite(filename, processed_frame)
                print(f"[✔] ĐÃ CHỤP VÀ LƯU ẢNH: {filename}")
                saved_notice_until = time.time() + 2.0

            # Hiển thị thông báo "ĐÃ CHỤP & LƯU ẢNH!" trên màn hình trong 2 giây
            if time.time() < saved_notice_until:
                cv2.putText(
                    processed_frame, 
                    "DA CHUP & LUU ANH!", 
                    (30, 60), 
                    cv2.FONT_HERSHEY_SIMPLEX, 
                    1.0, 
                    (0, 255, 0), 
                    2, 
                    cv2.LINE_AA
                )

            # Hiển thị trực tiếp lên cửa sổ màn hình
            cv2.imshow(DISPLAY_WINDOW_NAME, processed_frame)

    except KeyboardInterrupt:
        print("\nĐang dừng Photobooth...")
    finally:
        print("Đang dọn dẹp GPIO và tắt camera...")
        cap.release()
        cv2.destroyAllWindows()
        if HAS_GPIO:
            GPIO.cleanup()

if __name__ == '__main__':
    main()