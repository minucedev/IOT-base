# camera.py
"""
Module thu thập hình ảnh camera:
- Nhận stream HTTP MJPEG từ Laptop Media Stream Server (laptop_cam_server).
- Luồng đọc nền (Threaded Worker) giúp khung hình luôn mới nhất, không bị tích lũy độ trễ mạng.
- Tự động kết nối lại khi mất mạng hoặc khi Laptop Server khởi động lại.
"""

import threading
import time
import cv2
import config


class FireCamera:
    def __init__(self, source=None):
        self.source = source or getattr(config, "DEFAULT_CAMERA_URL", "http://10.232.65.44:5000/video_feed")
        self.running = True
        self.frame = None
        self.lock = threading.Lock()
        self.swap_rb = getattr(config, "CAMERA_SWAP_RB", False)
        self.cap = None

        print(f"[Camera] Khoi tao nhan stream tu Laptop: {self.source}")

        # Khởi chạy luồng chạy ngầm đọc frame liên tục (Threaded Reader)
        self.thread = threading.Thread(target=self._capture_worker, daemon=True)
        self.thread.start()

        # Đợi frame đầu tiên sẵn sàng
        start_wait = time.time()
        while self.frame is None and (time.time() - start_wait < 6.0):
            time.sleep(0.1)

        if self.frame is None:
            print(f"[Camera - Canh bao] Chua nhan duoc frame sau 6s tu {self.source}.")
            print("  Vui long kiem tra laptop_cam_server da chay chua va dia chi IP.")

    def trigger_autofocus(self):
        """Autofocus duoc quan ly tren webcam Laptop."""
        print("[Camera] Che do stream: Autofocus duoc thiet lap truc tiep tren webcam Laptop.")

    def adjust_focus(self, step):
        """Tieu cu duoc quan ly tren webcam Laptop."""
        print("[Camera] Che do stream: Tieu cu duoc thiet lap truc tiep tren webcam Laptop.")

    def toggle_color_swap(self):
        """Đảo kênh màu R-B trực tiếp khi đang chạy (hỗ trợ phím nóng 'c')"""
        self.swap_rb = not self.swap_rb
        mode = "DAO KENH R-B" if self.swap_rb else "MAC DINH"
        print(f"\n[Camera] >>> DA CHUYEN CHE DO MAU: {mode} <<<")
        return self.swap_rb

    def _capture_worker(self):
        """Luồng đọc liên tục khung hình từ camera ở background"""
        while self.running:
            try:
                if self.cap is None or not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(self.source)
                    if not self.cap.isOpened():
                        time.sleep(1.0)
                        continue
                    print(f"[Camera] Da ket noi toi Laptop Stream: {self.source}")

                ok, raw = self.cap.read()
                if not ok or raw is None or raw.size == 0:
                    if self.cap:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                    self.cap = None
                    time.sleep(0.5)
                    continue

                if self.swap_rb:
                    current_frame = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
                else:
                    current_frame = raw

                with self.lock:
                    self.frame = current_frame

            except Exception as e:
                time.sleep(0.5)

    def get_frame(self):
        """Trả về 1 frame dạng numpy array mới nhất."""
        with self.lock:
            if self.frame is not None:
                return self.frame.copy()

        time.sleep(0.02)
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def close(self):
        """Giải phóng camera"""
        self.running = False
        if hasattr(self, "thread") and self.thread.is_alive():
            self.thread.join(timeout=1.0)

        if hasattr(self, "cap") and self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
        print("[Camera] Da dong ket noi stream.")
