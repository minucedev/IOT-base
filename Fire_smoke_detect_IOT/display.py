# display.py
"""
Module hiển thị hình ảnh trực tiếp lên màn hình (qua OpenCV GUI).
- Vẽ bounding box, nhãn và confidence.
- Đổi màu viền toàn màn hình khi có báo động (Đỏ: Phát hiện lửa, Xanh: An toàn).
- Hiển thị FPS thời gian thực.
- Hỗ trợ phím nóng:
  + 'f': Kích hoạt lấy nét tự động (Autofocus)
  + '[' / ']': Chỉnh tiêu cự lấy nét gần/xa thủ công
  + 'q' hoặc ESC: Thoát
"""

import os
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import config


@lru_cache(maxsize=8)
def _font(size, bold=False):
    """Nạp font Unicode có hỗ trợ đầy đủ tiếng Việt trên Raspberry Pi."""
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = [
        os.path.join("/usr/share/fonts/truetype/dejavu", filename),
        os.path.join("C:/Windows/Fonts", "arialbd.ttf" if bold else "arial.ttf"),
        filename,
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()

def draw_overlay(frame, detections, fps=None, ai_fps=None):
    """
    Vẽ thông tin nhận diện và trạng thái lên frame.
    Trả về frame đã vẽ (định dạng BGR cho OpenCV imshow).
    """
    h, w = frame.shape[:2]

    # Frame từ camera đã ở dạng BGR chuẩn hiển thị cho OpenCV imshow
    render_frame = frame.copy()

    if detections:
        # 1. Viền đỏ cảnh báo toàn khung hình để nhận diện từ xa
        cv2.rectangle(render_frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 6)

        # 2. Thanh banner cảnh báo ở trên cùng
        cv2.rectangle(render_frame, (0, 0), (w, 50), (0, 0, 200), -1)
        # 3. Vẽ bounding box từng đối tượng lửa
        for d in detections:
            x1, y1, x2, y2 = d["box"]

            box_color = (0, 0, 255)  # Màu đỏ cho lửa

            # Bounding box
            cv2.rectangle(render_frame, (x1, y1), (x2, y2), box_color, 2)
    else:
        # Trạng thái an toàn bình thường
        cv2.rectangle(render_frame, (0, 0), (w, 40), (40, 40, 40), -1)

    # Thanh trạng thái dưới cùng (FPS + Hướng dẫn phím)
    cv2.rectangle(render_frame, (0, h - 30), (w, h), (20, 20, 20), -1)
    if fps is not None and ai_fps is not None and ai_fps > 0:
        fps_str = f"Cam: {fps:.1f} FPS | AI: {ai_fps:.1f} FPS"
    elif fps is not None:
        fps_str = f"FPS: {fps:.1f}"
    else:
        fps_str = "FPS: --"

    # OpenCV Hershey không hỗ trợ Unicode. Dùng Pillow + DejaVu Sans để chữ
    # tiếng Việt có dấu hiển thị đúng trên Raspberry Pi.
    pil_image = Image.fromarray(cv2.cvtColor(render_frame, cv2.COLOR_BGR2RGB))
    painter = ImageDraw.Draw(pil_image)

    if detections:
        painter.text(
            (18, 10), "!!! CẢNH BÁO: PHÁT HIỆN LỬA !!!",
            font=_font(25, bold=True), fill=(255, 255, 255)
        )
        tag_font = _font(17, bold=True)
        for d in detections:
            x1, y1, _, _ = d["box"]
            tag_text = f"LỬA {d['conf']:.2f}"
            left, top, right, bottom = painter.textbbox((0, 0), tag_text, font=tag_font)
            text_w, text_h = right - left, bottom - top
            tag_y = max(y1 - text_h - 10, 55)
            painter.rectangle(
                (x1, tag_y, x1 + text_w + 8, tag_y + text_h + 8),
                fill=(220, 0, 0)
            )
            painter.text((x1 + 4, tag_y + 2), tag_text, font=tag_font, fill=(255, 255, 255))
    else:
        painter.text(
            (15, 7), "TRẠNG THÁI: AN TOÀN",
            font=_font(20, bold=True), fill=(0, 230, 0)
        )

    painter.text(
        (15, h - 25), fps_str,
        font=_font(16, bold=True), fill=(255, 255, 0)
    )

    render_frame = cv2.cvtColor(np.asarray(pil_image), cv2.COLOR_RGB2BGR)

    return render_frame

_window_initialized = False


def show(frame):
    """
    Hiện frame lên cửa sổ.
    Trả về hành động phím:
    - 'quit': nếu nhấn 'q' hoặc ESC
    - 'color': nếu nhấn 'c' để đảo màu trực tiếp
    - 'focus': nếu nhấn 'f' để lấy nét lại
    - 'focus_near': nếu nhấn ']' hoặc '+' để tăng tiêu cự
    - 'focus_far': nếu nhấn '[' hoặc '-' để giảm tiêu cự
    - 'no_gui': môi trường không hỗ trợ mở cửa sổ OpenCV GUI
    - None: không có phím đặc biệt
    """
    global _window_initialized
    try:
        if not _window_initialized:
            # Khởi tạo cửa sổ chuẩn, không có thanh toolbar nút thừa (WINDOW_GUI_NORMAL)
            cv2.namedWindow(config.WINDOW_NAME, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL)
            h, w = frame.shape[:2]
            cv2.resizeWindow(config.WINDOW_NAME, w, h)
            _window_initialized = True

        cv2.imshow(config.WINDOW_NAME, frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            return 'quit'
        elif key == ord('c'):
            return 'color'
        elif key == ord('f'):
            return 'focus'
        elif key in (ord(']'), ord('='), ord('+')):
            return 'focus_near'
        elif key in (ord('['), ord('-')):
            return 'focus_far'
        return None
    except cv2.error:
        return 'no_gui'
    except Exception:
        return 'no_gui'


def close():
    """Đóng tất cả cửa sổ OpenCV"""
    global _window_initialized
    _window_initialized = False
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass
