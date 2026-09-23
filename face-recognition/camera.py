"""Camera stream client cho Raspberry Pi face recognition.

Đọc stream HTTP MJPEG từ laptop camera server qua cv2.VideoCapture.
Có cơ chế tự động kết nối lại khi mạng ngắt quãng và log kiểm tra khung hình.
"""

import os
import queue
import threading
import time
from typing import Optional
import cv2
import numpy as np

# =====================================================================
# CẤU HÌNH CAMERA STREAM TỪ LAPTOP
# Thay địa chỉ IP bên dưới bằng IP của Laptop đang chạy laptop_cam_server
# Ví dụ: "http://192.168.1.50:5000/video_feed"
# =====================================================================
CAMERA_URL = "http://10.93.29.44:5000/video_feed"
# =====================================================================


class Camera:
    """Quản lý kết nối và luồng đọc video stream từ Laptop."""

    def __init__(self, url: Optional[str] = None) -> None:
        configured_url = url or os.environ.get("CAMERA_URL", CAMERA_URL)
        self.url = str(configured_url).strip()

        self.frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=1)
        self._latest: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._capture: Optional[cv2.VideoCapture] = None
        self.error: Optional[str] = None
        self._frame_counter: int = 0
        self.latest_brightness: float = 0.0
        self._received_first_frame = False

    def start(self) -> None:
        """Khởi động luồng đọc camera."""
        if self._thread is not None:
            raise RuntimeError("Camera thread đã được khởi động.")

        print(f"[*] Đang kết nối tới nguồn camera: {self.url} ...", flush=True)
        self._capture = cv2.VideoCapture(self.url)
        if not self._capture.isOpened():
            print(
                f"[!] Cảnh báo: Chưa thể mở stream tại {self.url}.\n"
                f"    Kiểm tra lại xem Laptop đã bật `laptop_cam_server` chưa,\n"
                f"    và đảm bảo CAMERA_URL đã đúng IP laptop.\n"
                f"    Hệ thống sẽ liên tục thử kết nối lại trong nền...",
                flush=True,
            )
            self.error = f"Không kết nối được {self.url}"

        self._thread = threading.Thread(target=self._reader, name="camera-stream-reader", daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        """Luồng đọc liên tục từ HTTP stream với tính năng tự động kết nối lại."""
        fail_count = 0
        warned_dark = False

        while not self._stop.is_set():
            # Nếu capture chưa mở hoặc bị mất kết nối, thử mở lại định kỳ
            if self._capture is None or not self._capture.isOpened():
                self.error = f"Chờ kết nối tới {self.url}"
                time.sleep(1.0)
                try:
                    if self._capture is not None:
                        self._capture.release()
                    self._capture = cv2.VideoCapture(self.url)
                    if self._capture.isOpened():
                        print(f"[+] Kết nối lại camera stream thành công: {self.url}", flush=True)
                        fail_count = 0
                        self.error = None
                except Exception as exc:
                    self.error = f"Lỗi kết nối lại: {exc}"
                continue

            ok, frame = self._capture.read()
            if not ok or frame is None:
                fail_count += 1
                self.error = f"Đọc frame thất bại ({fail_count}x)"
                
                if fail_count % 30 == 1:
                    print(f"[!] Mất tín hiệu stream ({self.error}), đang thử kết nối lại...", flush=True)

                # Giữ nhịp chờ 3 giây (30 lần x 0.1s) trước khi tạo lại VideoCapture
                if fail_count >= 30:
                    print(f"[!] Quá thời gian chờ stream, đang reset kết nối tới {self.url}...", flush=True)
                    try:
                        if self._capture is not None:
                            self._capture.release()
                    except Exception:
                        pass
                    self._capture = None
                    time.sleep(1.0)
                    continue

                time.sleep(0.1)
                continue

            fail_count = 0
            self.error = None

            # Tính độ sáng khung hình
            brightness = float(np.mean(frame))
            self.latest_brightness = brightness

            if not self._received_first_frame:
                self._received_first_frame = True
                h, w = frame.shape[:2]
                print(f"\n✅ ĐÃ NHẬN KHUNG HÌNH TỪ CAMERA STREAM!", flush=True)
                print(f"   Nguồn : {self.url}")
                print(f"   Size  : {w}x{h}")
                print(f"   Độ sáng trung bình: {brightness:.1f}\n", flush=True)

            if brightness < 8.0:
                if not warned_dark:
                    print(
                        f"[!] CẢNH BÁO: Khung hình nhận được đang bị ĐEN (độ sáng TB = {brightness:.1f})!\n"
                        f"    -> Webcam trên Laptop đang gửi khung hình đen.\n"
                        f"    -> Hãy mở nắp che webcam laptop hoặc đổi index camera: python app.py --cam 1\n",
                        flush=True,
                    )
                    warned_dark = True
            else:
                if warned_dark:
                    print(f"[+] Khung hình đã sáng bình thường (độ sáng TB = {brightness:.1f})", flush=True)
                    warned_dark = False

            with self._lock:
                self._latest = frame
                self._frame_counter += 1

            # Đẩy vào queue frames (chỉ giữ 1 frame mới nhất)
            try:
                self.frames.put_nowait(frame.copy())
            except queue.Full:
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.frames.put_nowait(frame.copy())
                except queue.Full:
                    pass

    def get_latest(self) -> Optional[np.ndarray]:
        """Lấy bản copy của frame mới nhất."""
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    def get_latest_with_counter(self) -> tuple[Optional[np.ndarray], int]:
        """Trả về (frame, counter) - counter tăng mỗi khi có frame mới thực sự."""
        with self._lock:
            frame = None if self._latest is None else self._latest.copy()
            return frame, self._frame_counter

    def stop(self) -> None:
        """Dừng luồng đọc và giải phóng camera."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    @property
    def is_running(self) -> bool:
        """Kiểm tra camera có đang hoạt động tốt không."""
        return (
            self._thread is not None
            and self._thread.is_alive()
            and not self._stop.is_set()
            and self.error is None
        )
