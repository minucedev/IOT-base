"""Ứng dụng Nhận diện khuôn mặt trên Raspberry Pi 4 (Cửa sổ OpenCV Desktop - Không Web).

Tính năng:
  - Nhận luồng video thời gian thực từ laptop_cam_server.py trên Laptop.
  - Nhận diện khuôn mặt bằng YuNet + SFace (ONNX).
  - Hiển thị kết quả lên một cửa sổ Desktop OpenCV duy nhất.
  - Người đã đăng ký: Điều khiển Servo quay 180 độ trong 5s rồi tự đóng về 0 độ.
    (Không cần cooldown, nếu người quen vẫn đứng trước cam sau 5s thì tiếp tục mở lại ngay).
  - Người lạ (Unknown): Hú còi Active Buzzer liên tục cho đến khi người lạ rời đi.
  - Phím [r]: Đăng ký khuôn mặt mới (thu thập 5 mẫu ảnh tối ưu).
  - Phím [q]: Thoát ứng dụng an toàn và giải phóng chân GPIO.
"""

import atexit
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from camera import Camera, CAMERA_URL
from database import FaceDatabase
from hardware import HardwareController
from recognition import RecognitionEngine

BASE_DIR = Path(__file__).resolve().parent
WINDOW_TITLE = "Face Recognition System - Raspberry Pi 4"


def make_waiting_canvas(width: int = 640, height: int = 480, message: str = "Đang kết nối camera laptop...") -> np.ndarray:
    """Tạo khung hình thông báo chờ kết nối."""
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    canvas[:] = (30, 25, 20)
    cv2.putText(
        canvas, message, (30, height // 2 - 20),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 215, 255), 2, cv2.LINE_AA,
    )
    cv2.putText(
        canvas, f"URL: {CAMERA_URL}", (30, height // 2 + 20),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1, cv2.LINE_AA,
    )
    cv2.putText(
        canvas, "Kiem tra xem laptop_cam_server.py da bat chua", (30, height // 2 + 55),
        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (140, 140, 140), 1, cv2.LINE_AA,
    )
    return canvas


def draw_hud(
    canvas: np.ndarray,
    status_info: dict,
    is_door_open: bool,
    is_buzzer_on: bool,
    notice_text: Optional[str] = None,
) -> np.ndarray:
    """Vẽ thanh thông tin trạng thái hệ thống (HUD) lên khung hình."""
    h, w = canvas.shape[:2]

    # Thanh header trên cùng (trong suốt nhẹ)
    header_overlay = canvas.copy()
    cv2.rectangle(header_overlay, (0, 0), (w, 55), (15, 15, 15), -1)
    cv2.addWeighted(header_overlay, 0.75, canvas, 0.25, 0, canvas)

    # Hiển thị FPS
    cap_fps = status_info.get("cap_fps", 0.0)
    infer_fps = status_info.get("infer_fps", 0.0)
    cv2.putText(
        canvas, f"FPS Cam: {cap_fps:.1f} | AI: {infer_fps:.1f}", (10, 22),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
    )

    # Hiển thị trạng thái Cửa (Servo)
    if is_door_open:
        servo_text = "DOOR: [OPEN 180 deg]"
        servo_color = (0, 255, 0)  # Xanh lá
    else:
        servo_text = "DOOR: [CLOSED 0 deg]"
        servo_color = (180, 180, 180)  # Xám
    cv2.putText(
        canvas, servo_text, (10, 45),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, servo_color, 2, cv2.LINE_AA,
    )

    # Hiển thị trạng thái Còi Báo Động (Buzzer)
    if is_buzzer_on:
        buzzer_text = "ALARM: [ON - DANGER!]"
        buzzer_color = (0, 0, 255)  # Đỏ rực
    else:
        buzzer_text = "ALARM: [OFF]"
        buzzer_color = (180, 180, 180)
    cv2.putText(
        canvas, buzzer_text, (280, 45),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, buzzer_color, 2, cv2.LINE_AA,
    )

    # Thanh footer dưới cùng (hướng dẫn phím tắt)
    footer_overlay = canvas.copy()
    cv2.rectangle(footer_overlay, (0, h - 35), (w, h), (15, 15, 15), -1)
    cv2.addWeighted(footer_overlay, 0.75, canvas, 0.25, 0, canvas)

    help_msg = "[r]: Dang ky khuon mat  |  [q]: Thoat"
    cv2.putText(
        canvas, help_msg, (10, h - 12),
        cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 215, 255), 1, cv2.LINE_AA,
    )

    # Thông báo tạm thời nếu có (ví dụ: đang đăng ký, kết quả)
    if notice_text:
        notice_bg = canvas.copy()
        cv2.rectangle(notice_bg, (w // 2 - 250, h // 2 - 30), (w // 2 + 250, h // 2 + 30), (0, 0, 0), -1)
        cv2.addWeighted(notice_bg, 0.85, canvas, 0.15, 0, canvas)
        cv2.rectangle(canvas, (w // 2 - 250, h // 2 - 30), (w // 2 + 250, h // 2 + 30), (0, 215, 255), 2)
        cv2.putText(
            canvas, notice_text, (w // 2 - 230, h // 2 + 8),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA,
        )

    return canvas


def main() -> None:
    print("=" * 60)
    print(" HỆ THỐNG NHẬN DIỆN KHUÔN MẶT - SERVO & BUZZER (DESKTOP GUI)")
    print("=" * 60)
    print(f"Nguồn Camera: {CAMERA_URL}")
    print("Điều khiển phần cứng:")
    print("  - Servo (GPIO 18): Quay 180° trong 5s khi nhận diện người quen")
    print("  - Còi (GPIO 23): Hú liên tục chừng nào còn người lạ trước camera")
    print("Phím tắt:")
    print("  - [r]: Đăng ký khuôn mặt mới (thu thập 5 mẫu ảnh)")
    print("  - [q]: Thoát chương trình")
    print("=" * 60, flush=True)

    # 1. Khởi tạo phần cứng
    hardware = HardwareController()

    # 2. Khởi tạo cơ sở dữ liệu và AI engine
    database = FaceDatabase(str(BASE_DIR / "data"))
    camera = Camera(os.environ.get("CAMERA_URL", CAMERA_URL))
    camera.start()

    engine = RecognitionEngine(camera, database)
    engine.start()

    # Dọn dẹp an toàn khi tắt
    def cleanup_all():
        print("\nĐang tắt hệ thống...", flush=True)
        engine.stop()
        camera.stop()
        hardware.cleanup()
        cv2.destroyAllWindows()
        print("Đã giải phóng tài nguyên. Tạm biệt!", flush=True)

    atexit.register(cleanup_all)

    # Cửa sổ OpenCV
    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_TITLE, 640, 480)

    notice_message: Optional[str] = None
    notice_expire_time: float = 0.0

    try:
        while True:
            # Lấy thông tin trạng thái từ engine
            status = engine.get_status_info()
            frame = status.get("frame")

            if frame is None:
                # Chưa nhận được luồng hình ảnh
                display_img = make_waiting_canvas(640, 480, "Đang kết nối camera laptop...")
            else:
                # Phóng to frame hiển thị cho rõ nét trên màn hình Desktop
                display_img = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_LINEAR)

                # ==========================================================
                # LOGIC ĐIỀU KHIỂN PHẦN CỨNG
                # ==========================================================
                has_known = status.get("has_known", False)
                known_name = status.get("known_name", "")
                has_stranger = status.get("has_stranger", False)

                # 1. Người đã đăng ký: Quay servo 180° giữ 5s
                if has_known:
                    if not hardware.is_door_open:
                        hardware.trigger_open_door(hold_seconds=5.0)

                # 2. Người lạ: Hú còi liên tục khi còn xuất hiện
                if has_stranger:
                    hardware.set_buzzer(True)
                else:
                    hardware.set_buzzer(False)

            # Xử lý thông báo tạm thời trên màn hình
            current_time = time.monotonic()
            active_notice = None
            if notice_message and current_time < notice_expire_time:
                active_notice = notice_message
            else:
                notice_message = None

            # Vẽ HUD lên khung hình
            final_canvas = draw_hud(
                display_img,
                status,
                is_door_open=hardware.is_door_open,
                is_buzzer_on=hardware.is_buzzer_on,
                notice_text=active_notice,
            )

            cv2.imshow(WINDOW_TITLE, final_canvas)

            # Bắt sự kiện phím bấm
            key = cv2.waitKey(20) & 0xFF

            # Phím [q] -> Thoát
            if key in (ord('q'), ord('Q'), 27):
                print("[!] Người dùng yêu cầu dừng chương trình.", flush=True)
                break

            # Phím [r] -> Đăng ký khuôn mặt mới
            elif key in (ord('r'), ord('R')):
                # Tạm thời tắt còi trong khi đăng ký
                hardware.set_buzzer(False)

                notice_message = "Vui long nhap ten vao Terminal..."
                notice_expire_time = time.monotonic() + 10.0

                # Render thông báo ngay lập tức lên cửa sổ
                hud_temp = draw_hud(
                    display_img, status, hardware.is_door_open, False,
                    notice_text="NHAP TEN TRONG TERMINAL CONSOLE..."
                )
                cv2.imshow(WINDOW_TITLE, hud_temp)
                cv2.waitKey(1)

                print("\n" + "=" * 50)
                print(">> [CHẾ ĐỘ ĐĂNG KÝ KHUÔN MẶT]")
                name_input = input(">> Nhập họ và tên người cần đăng ký: ").strip()

                if not name_input:
                    print(">> Hủy đăng ký (tên trống).")
                    notice_message = "Da huy dang ky (Ten trong)!"
                    notice_expire_time = time.monotonic() + 3.0
                else:
                    print(f">> Hãy nhìn thẳng vào camera để thu thập 5 mẫu ảnh cho '{name_input}'...")
                    
                    hud_collecting = draw_hud(
                        display_img, status, hardware.is_door_open, False,
                        notice_text=f"DANG CHUP 5 MAU ANH CHO: {name_input}..."
                    )
                    cv2.imshow(WINDOW_TITLE, hud_collecting)
                    cv2.waitKey(1)

                    success, msg = engine.register_latest(name_input, sample_count=5)
                    print(f">> Kết quả: {msg}")
                    notice_message = f"DANG KY: {msg}"
                    notice_expire_time = time.monotonic() + 4.0
                print("=" * 50 + "\n", flush=True)

    except KeyboardInterrupt:
        print("\n[!] Bắt được tín hiệu ngắt bàn phím (Ctrl+C).", flush=True)
    finally:
        cleanup_all()
        # Bỏ đăng ký atexit để không chạy 2 lần
        atexit.unregister(cleanup_all)
        sys.exit(0)


if __name__ == "__main__":
    main()
