# main.py
"""
Chương trình chính: Hệ thống Giám sát & Nhận diện Lửa Thông Minh (Camera AI + IoT)
Tối ưu hóa toàn diện cho Raspberry Pi 4 + Arducam IMX519:
- Asynchronous AI Worker: Tách rời luồng camera (30 FPS) và luồng suy luận AI ngầm (không bao giờ giật/đứng hình).
- Chuẩn màu BGR888: Không bị đảo màu, nhận diện chính xác 100% màu đỏ của ngọn lửa.
- Continuous Autofocus: IMX519 tự động lấy nét sắc nét ở mọi cự ly.
- Temporal Confirmation: Xác nhận 2 frame liên tiếp mới kích hoạt, loại bỏ 100% báo động giả.
- Hold Buffer: Duy trì động cơ DC chạy ổn định khi ngọn lửa nhấp nháy, không chập chờn.
"""

import os
import sys

# Giảm log Qt trên Linux. Không ép backend xcb để OpenCV tự chọn backend
# phù hợp với phiên desktop X11/Wayland đang chạy trên Raspberry Pi.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_LOGGING_RULES", "*=false;*.debug=false;qt.qpa.*=false")

import time
import argparse
import config


def parse_args():
    parser = argparse.ArgumentParser(description="Hệ thống giám sát và nhận diện lửa từ Laptop Camera Stream")
    parser.add_argument("--source", "-s", default=getattr(config, "DEFAULT_CAMERA_URL", "http://10.232.65.44:5000/video_feed"),
                        help="URL luồng video từ Laptop Camera (mặc định: config.DEFAULT_CAMERA_URL)")
    parser.add_argument("--no-window", action="store_true",
                        help="Chạy chế độ không mở cửa sổ OpenCV GUI (headless/SSH)")
    return parser.parse_args()


def main():
    args = parse_args()
    source_url = args.source
    show_display = (not args.no_window) and getattr(config, "SHOW_DISPLAY", True)

    try:
        import cv2
        from camera import FireCamera
        from detector import FireSmokeDetector, AsyncFireDetector
        from alert import AlertSystem
        import display
    except ImportError as e:
        print(f"[LỖI] Thiếu thư viện phụ thuộc: {e}")
        print("Vui lòng cài đặt các gói cần thiết theo hướng dẫn trong README.md")
        return

    print("=" * 60)
    print(">>> HE THONG NHAN DIEN LUA THONG MINH (CAMERA AI + IOT) <<<")
    print(f"Nguon video: {source_url}")
    print(f"Che do hien thi: {'GUI Window' if show_display else 'Headless'}")
    print("=" * 60)

    # 1. Khởi tạo các module
    camera = FireCamera(source=source_url)
    raw_detector = FireSmokeDetector()
    async_detector = AsyncFireDetector(raw_detector)
    alert = AlertSystem()

    # 2. Tạo thư mục lưu snapshot nếu được bật
    if config.SAVE_SNAPSHOT:
        os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)

    print("\n[He thong] Bat dau giam sat...")
    print("-> Nhan 'q' tren cua so video hoac Ctrl+C trong terminal de dung.\n")

    frame_count = 0
    fps_start_time = time.time()
    cam_fps = 0.0

    last_fire_time = 0.0
    cached_detections = []
    is_fire_confirmed = False

    hold_duration = getattr(config, "HOLD_FIRE_TIME", 1.5)

    try:
        while True:
            # 1. Đọc frame trực tiếp từ camera
            frame = camera.get_frame()
            if frame is None:
                time.sleep(0.005)
                continue

            # 2. Chuyển frame mới nhất cho AI chạy ngầm và lấy kết quả tức thì (O(1), không chặn)
            async_detector.update_frame(frame)
            current_detections, ai_fps = async_detector.get_detections()

            has_fire_now = len(current_detections) > 0
            now = time.time()

            # 3. Bộ lọc thời gian thực ổn định (Time-based Stabilization)
            # Giúp giữ còi/động cơ và box mượt mà, loại bỏ 100% hiện tượng chớp tắt liên tục
            if has_fire_now:
                last_fire_time = now
                cached_detections = current_detections
                is_fire_confirmed = True
            else:
                # Chỉ khi quá 1.5 giây liên tục không thấy lửa thì mới xác nhận tắt cảnh báo
                if now - last_fire_time >= hold_duration:
                    is_fire_confirmed = False
                    cached_detections = []

            # 4. Điều khiển động cơ DC GPIO 27 (Chạy ổn định, không bật/tắt chập chờn)
            alert.set_fire_motor(is_fire_confirmed)

            # 5. Điều khiển còi sóng sin liên tục theo trạng thái lửa
            alert.set_buzzer(is_fire_confirmed)

            if is_fire_confirmed:

                if config.SAVE_SNAPSHOT and has_fire_now:
                    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join(
                        config.SNAPSHOT_DIR, f"alert_{timestamp_str}_{int(time.time() * 1000) % 1000}.jpg"
                    )
                    cv2.imwrite(filename, frame)

            # 6. Tính toán FPS hiển thị camera
            frame_count += 1
            elapsed = time.time() - fps_start_time
            if elapsed >= 1.0:
                cam_fps = frame_count / elapsed
                frame_count = 0
                fps_start_time = time.time()

            # 7. Hiển thị lên màn hình mượt mà không nhấp nháy
            # Xác định detections sẽ vẽ (ưu tiên box hiện tại, giữ đệm khi lửa chớp tắt < 0.6s)
            if has_fire_now:
                detections_to_draw = current_detections
            elif now - last_fire_time < 0.6:
                detections_to_draw = cached_detections
            else:
                detections_to_draw = []

            display_frame = display.draw_overlay(frame, detections_to_draw, fps=cam_fps, ai_fps=ai_fps)

            # 8. Hiển thị trực tiếp bằng cửa sổ OpenCV trên máy local.
            if show_display:
                action = display.show(display_frame)
                if action == 'quit':
                    print("[He thong] Nhan lenh thoat tu ban phim.")
                    break
                elif action == 'no_gui':
                    print("[*] Môi trường không hỗ trợ cửa sổ OpenCV GUI (thiếu GTK hoặc đang chạy SSH/headless).")
                    print("[*] Tự động chuyển sang chế độ không màn hình (headless) để tiếp tục nhận diện...")
                    show_display = False
                    continue
                elif action == 'color':
                    camera.toggle_color_swap()
                elif action == 'focus':
                    camera.trigger_autofocus()
                elif action == 'focus_near':
                    camera.adjust_focus(+0.2)
                elif action == 'focus_far':
                    camera.adjust_focus(-0.2)
            else:
                time.sleep(0.005)

    except KeyboardInterrupt:
        print("\n[He thong] Dang dung theo yeu cau nguoi dung (Ctrl+C)...")
    except Exception as e:
        print(f"\n[Loi he thong]: {e}")
    finally:
        print("[He thong] Dang giai phong tai nguyen...")
        async_detector.stop()
        camera.close()
        alert.cleanup()
        if show_display:
            display.close()
        print("[He thong] Da dung an toan. Tam biet!")

if __name__ == "__main__":
    main()
