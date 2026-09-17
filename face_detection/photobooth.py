import cv2
import time
import sys
import os
import numpy as np
import RPi.GPIO as GPIO

# --- Cấu hình ---
# Local: CAMERA_SOURCE = 0
# Laptop server: CAMERA_SOURCE = "http://<LAPTOP_IP>:5000/video_feed"
LAPTOP_CAM_URL = "http://192.168.1.10:5000/video_feed"  # <-- sửa IP laptop
CAMERA_SOURCE = LAPTOP_CAM_URL  # đổi thành 0 nếu muốn dùng cam cắm trực tiếp vào Pi
CAMERA_INDEX = 0  # giữ để tương thích cũ
CAMERA_RESOLUTION = (640, 480)
DISPLAY_WINDOW_NAME = "Photobooth OpenCV - Raspberry Pi"
SAVE_PREFIX = "./"

# --- Cấu hình Nút Bấm ---
BUTTON_PIN = 24
DEBOUNCE_TIME = 0.3

# --- Các Hiệu ứng sẽ áp dụng (mũ + kính + ria cùng lúc) ---
EFFECTS_TO_APPLY = ["hat", "glasses", "mustache"]

# --- Cấu hình đường dẫn và lớp phủ (Overlays) ---
FACE_CASCADE_PATH = './haarcascade_frontalface_default.xml'
FACE_DETECTION_PARAMS = {
    "scaleFactor": 1.1,
    "minNeighbors": 5,
    "minSize": (30, 30),
    "flags": 0
}

OVERLAYS = {
    "hat": {
        "name": "Mũ",
        "image_path": "./hat.png",
        # cascade_path = None -> neo theo đỉnh khuôn mặt, luôn hiện khi thấy mặt
        "cascade_path": None,
        "anchor": "face_top",
        "scale_factor": 1.2,
        "offset_x_ratio": 0,
        "offset_y_ratio": 0.25
    },
    "mustache": {
        "name": "Ria mép",
        "image_path": "./rau2.png", 
        "cascade_path": "./haarcascade_mcs_nose.xml",
        "anchor": "nose",
        "scale_factor": 0.6,
        "offset_x_ratio": 0,   
        "offset_y_ratio": 0.35  
    },
    "glasses": {
        "name": "Kính mắt",
        "image_path": "./sunglasses.png",
        "cascade_path": "./haarcascade_eye.xml",
        "anchor": "eyes_center",
        "scale_factor": 0.9,
        "offset_x_ratio": 0,   
        "offset_y_ratio": 0.35
    }
}

loaded_cascades = {}
loaded_overlays = {}

def initialize_resources():
    print("Đang tải các mô hình nhận diện và hình ảnh lớp phủ...")
    loaded_cascades['face'] = cv2.CascadeClassifier(FACE_CASCADE_PATH)
    if loaded_cascades['face'].empty():
        print(f"LỖI: Không thể tải face cascade tại {FACE_CASCADE_PATH}")
        sys.exit(1)

    for key, config in OVERLAYS.items():
        if not os.path.exists(config['image_path']):
            print(f"Cảnh báo: Không tìm thấy file ảnh {config['image_path']}. Bỏ qua hiệu ứng này.")
            OVERLAYS[key]['cascade_loaded'] = False
            continue

        img = cv2.imread(config['image_path'], cv2.IMREAD_UNCHANGED)
        if img is None:
            print(f"Cảnh báo: Lỗi đọc ảnh {config['image_path']}")
            OVERLAYS[key]['cascade_loaded'] = False
            continue
            
        if img.shape[2] == 4:
            loaded_overlays[key] = {'rgb': img[:, :, :3], 'mask': img[:, :, 3]}
        else:
            loaded_overlays[key] = {'rgb': img, 'mask': np.ones((img.shape[0], img.shape[1]), dtype=np.uint8) * 255}

        # Hiệu ứng neo theo mặt (vd: mũ) không cần cascade riêng
        if not config.get('cascade_path'):
            OVERLAYS[key]['cascade_loaded'] = True
            continue
            
        cascade = cv2.CascadeClassifier(config['cascade_path'])
        if not cascade.empty():
            loaded_cascades[config['cascade_path']] = cascade
            OVERLAYS[key]['cascade_loaded'] = True
        else:
            print(f"Cảnh báo: Không thể tải cascade tại {config['cascade_path']}. Bạn đã tải file .xml chưa?")
            OVERLAYS[key]['cascade_loaded'] = False

def overlay_image_alpha(img, img_overlay, x, y, alpha_mask):
    try:
        h, w = img_overlay.shape[0], img_overlay.shape[1]
        y1, y2 = max(0, y), min(img.shape[0], y + h)
        x1, x2 = max(0, x), min(img.shape[1], x + w)

        roi = img[y1:y2, x1:x2]

        overlay_h, overlay_w = y2 - y1, x2 - x1
        if overlay_h <= 0 or overlay_w <= 0: return img
        
        img_overlay_cropped = img_overlay[0:overlay_h, 0:overlay_w]
        alpha_mask_cropped = alpha_mask[0:overlay_h, 0:overlay_w]
        
        if roi.shape[0] != overlay_h or roi.shape[1] != overlay_w: return img

        mask = cv2.merge((alpha_mask_cropped, alpha_mask_cropped, alpha_mask_cropped))
        mask_inv = cv2.bitwise_not(mask)

        img_bg = cv2.bitwise_and(roi, mask_inv)
        img_fg = cv2.bitwise_and(img_overlay_cropped, mask)

        dst = cv2.add(img_bg, img_fg)
        img[y1:y2, x1:x2] = dst
    except Exception as e:
        print(f"Lỗi khi overlay: {e}")
    return img

def apply_multiple_overlays(frame, list_of_overlay_keys):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    processed_frame = frame.copy()

    needed_cascades = {}
    for key in list_of_overlay_keys:
        if key in OVERLAYS:
            config = OVERLAYS[key]
            if config['cascade_path'] and config.get('cascade_loaded', False):
                path = config['cascade_path']
                if path not in needed_cascades:
                    needed_cascades[path] = set()
                needed_cascades[path].add(config['anchor'])

    faces = loaded_cascades['face'].detectMultiScale(
        gray,
        scaleFactor=FACE_DETECTION_PARAMS["scaleFactor"],
        minNeighbors=FACE_DETECTION_PARAMS["minNeighbors"],
        minSize=FACE_DETECTION_PARAMS["minSize"],
        flags=FACE_DETECTION_PARAMS["flags"]
    )

    if len(faces) == 0:
        return processed_frame

    faces = sorted(faces, key=lambda face: face[2] * face[3], reverse=True)

    for i, (x, y, w, h) in enumerate(faces):
        face_roi_gray = gray[y:y+h, x:x+w]
        detected_features = {'face': (x, y, w, h)}
        
        for cascade_path, anchors_needed in needed_cascades.items():
            if 'nose' in anchors_needed and cascade_path in loaded_cascades:
                noses = loaded_cascades[cascade_path].detectMultiScale(face_roi_gray, 1.1, 5, minSize=(15, 15))
                if len(noses) > 0:
                    noses = sorted(noses, key=lambda n: n[2] * n[3], reverse=True)
                    detected_features['nose'] = noses[0]

            if 'eyes_center' in anchors_needed and cascade_path in loaded_cascades:
                eyes = loaded_cascades[cascade_path].detectMultiScale(face_roi_gray, 1.05, 6, minSize=(10, 10))
                if len(eyes) >= 2:
                    eyes = sorted(eyes, key=lambda e: e[0])
                    if len(eyes) > 2:
                        eyes = sorted(eyes, key=lambda e: e[2] * e[3], reverse=True)[:2]
                        eyes = sorted(eyes, key=lambda e: e[0])
                    detected_features['eyes'] = eyes[:2]

        for overlay_key in list_of_overlay_keys:
            if (overlay_key not in OVERLAYS or overlay_key not in loaded_overlays or not OVERLAYS[overlay_key].get('cascade_loaded', False)):
                continue

            config = OVERLAYS[overlay_key]
            overlay_data = loaded_overlays[overlay_key]
            overlay_rgb = overlay_data['rgb']
            overlay_mask = overlay_data['mask']
            anchor = config['anchor']
            scale = config['scale_factor']
            offset_x_r = config['offset_x_ratio']
            offset_y_r = config['offset_y_ratio']

            target_x, target_y, target_w, target_h = 0, 0, 0, 0
            anchor_found = False

            if anchor == 'face_top':
                # Mũ: neo theo đỉnh khuôn mặt -> luôn hiện khi thấy mặt
                target_w = int(w * scale)
                target_h = int(target_w * (overlay_rgb.shape[0] / overlay_rgb.shape[1]))
                target_x = x + int(w / 2) - int(target_w / 2) + int(target_w * offset_x_r)
                target_y = y - target_h + int(h * offset_y_r)
                anchor_found = True

            elif anchor == 'nose':
                if 'nose' in detected_features:
                    nx, ny, nw, nh = detected_features['nose']
                    target_w = int(w * scale)
                    target_h = int(target_w * (overlay_rgb.shape[0] / overlay_rgb.shape[1]))
                    target_x = x + nx + int(nw / 2) - int(target_w / 2) + int(target_w * offset_x_r)
                    target_y = y + ny + int(nh / 2) - int(target_h / 2) + int(target_h * offset_y_r)
                    anchor_found = True
                else:
                    # Fallback theo tỉ lệ mặt để ria luôn hiện cùng lúc
                    target_w = int(w * scale)
                    target_h = int(target_w * (overlay_rgb.shape[0] / overlay_rgb.shape[1]))
                    target_x = x + int(w / 2) - int(target_w / 2) + int(target_w * offset_x_r)
                    target_y = y + int(h * 0.65) - int(target_h / 2) + int(target_h * offset_y_r)
                    anchor_found = True
                
            elif anchor == 'eyes_center':
                if 'eyes' in detected_features and len(detected_features['eyes']) == 2:
                    e1, e2 = detected_features['eyes']
                    ex1, ey1, ew1, eh1 = e1
                    ex2, ey2, ew2, eh2 = e2
                    center_x = x + int((ex1 + ex2 + ew2) / 2)
                    center_y = y + int((ey1 + ey2) / 2)
                    target_w = int(w * scale)
                    target_h = int(target_w * (overlay_rgb.shape[0] / overlay_rgb.shape[1]))
                    target_x = center_x - int(target_w / 2) + int(target_w * offset_x_r)
                    target_y = center_y - int(target_h / 2) + int(target_h * offset_y_r)
                    anchor_found = True
                else:
                    # Fallback theo tỉ lệ mặt để kính luôn hiện cùng lúc
                    center_x = x + int(w / 2)
                    center_y = y + int(h * 0.35)
                    target_w = int(w * scale)
                    target_h = int(target_w * (overlay_rgb.shape[0] / overlay_rgb.shape[1]))
                    target_x = center_x - int(target_w / 2) + int(target_w * offset_x_r)
                    target_y = center_y - int(target_h / 2) + int(target_h * offset_y_r)
                    anchor_found = True

            if anchor_found and target_w > 0 and target_h > 0:
                current_overlay = cv2.resize(overlay_rgb, (target_w, target_h), interpolation=cv2.INTER_AREA)
                current_mask = cv2.resize(overlay_mask, (target_w, target_h), interpolation=cv2.INTER_AREA)
                processed_frame = overlay_image_alpha(processed_frame, current_overlay, target_x, target_y, current_mask)
                
    return processed_frame

# --- Setup ---
initialize_resources()

# Thiết lập GPIO cho Raspberry Pi
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

def open_camera(source):
    print(f"Dang ket noi camera: {source}")
    c = cv2.VideoCapture(source)
    # Chỉ set resolution cho cam local, stream mạng thì server quyết định
    if isinstance(source, int):
        c.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_RESOLUTION[0])
        c.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_RESOLUTION[1])
    return c

cap = open_camera(CAMERA_SOURCE)
cv2.namedWindow(DISPLAY_WINDOW_NAME)

# Các biến trạng thái nút bấm và hiển thị
last_button_state = False
button_press_time = 0.0
saved_msg = ""
saved_msg_end_time = 0.0

print("Hệ thống đã sẵn sàng trên Raspberry Pi!")
print(f" - Stream LUÔN gắn hiệu ứng {EFFECTS_TO_APPLY}.")
print(f" - Nhấn nút vật lý (Chân GPIO {BUTTON_PIN}) hoặc phím 'c' để chụp.")
print(" - Nhấn 'q' để thoát.")

try:
    fail_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            fail_count += 1
            print(f"Lỗi: Không thể đọc khung hình từ camera ({CAMERA_SOURCE}). Lan {fail_count}")
            # Stream mạng rớt -> thử kết nối lại sau vài lần lỗi
            if fail_count >= 30:
                print("Thu ket noi lai camera...")
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
        
        # 1. LUÔN gắn hiệu ứng khi stream
        processed_frame = apply_multiple_overlays(frame, EFFECTS_TO_APPLY)
        display_frame = cv2.flip(processed_frame, 1)

        capture_triggered = False
        
        # 2. Đọc tín hiệu từ nút bấm vật lý (GPIO)
        current_state = GPIO.input(BUTTON_PIN) == GPIO.HIGH
        if current_state and not last_button_state and (time.time() - button_press_time > DEBOUNCE_TIME):
            capture_triggered = True
            button_press_time = time.time()
        last_button_state = current_state

        # 3. Đọc tín hiệu từ bàn phím (Phím 'c' hoặc 'q')
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'): 
            break
        elif key == ord('c'): 
            capture_triggered = True

        # Xử lý khi có lệnh chụp: chỉ lưu frame đang stream (đã có hiệu ứng)
        if capture_triggered:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            effect_combo_name = "-".join(EFFECTS_TO_APPLY)
            filename = f"{SAVE_PREFIX}pi_{effect_combo_name}_{timestamp}.jpg"
            cv2.imwrite(filename, display_frame)
            print(f"\nĐã chụp và lưu ảnh: {filename}")

            saved_msg = f"Da luu: {filename}"
            saved_msg_end_time = time.time() + 2.0  # Hiển thị thông báo 2 giây

        # Hiển thị thông báo "đã lưu" đè lên stream (không freeze stream)
        if saved_msg and time.time() < saved_msg_end_time:
            cv2.putText(display_frame, "Captured! " + saved_msg, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
        else:
            saved_msg = ""

        cv2.imshow(DISPLAY_WINDOW_NAME, display_frame)

finally:
    print("\nĐang dọn dẹp GPIO và thoát...")
    cap.release()
    cv2.destroyAllWindows()
    GPIO.cleanup()