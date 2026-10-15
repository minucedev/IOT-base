"""Lấy frame từ Raspberry Pi Camera (OV5647/CSI) bằng Picamera2 (libcamera)."""
import logging
import time

import numpy as np

import config
from state import GlobalState

log = logging.getLogger(__name__)


class Camera:
    """Trả về frame numpy BGR (uint8, HxWx3), dùng trực tiếp với OpenCV.

    Lưu ý: định dạng "RGB888" của Picamera2 có thứ tự byte trong bộ nhớ là
    B-G-R, nên mảng trả về đã tương thích OpenCV (không cần cvtColor).
    """

    def __init__(self, resolution=config.CAMERA_RESOLUTION, fps=config.CAMERA_FPS):
        self.resolution = resolution
        self.fps = fps
        self._picam2 = None
        self._cap = None

    def start(self) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError:
            if not config.ALLOW_WEBCAM_FALLBACK:
                raise RuntimeError(
                    "Không import được picamera2. Cài bằng: sudo apt install -y python3-picamera2"
                )
            import cv2
            log.warning("Picamera2 không khả dụng -> dùng webcam OpenCV (chế độ dev).")
            self._cap = cv2.VideoCapture(0)
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
            return

        kwargs = {}
        if config.CAMERA_HFLIP or config.CAMERA_VFLIP:
            from libcamera import Transform
            kwargs["transform"] = Transform(hflip=config.CAMERA_HFLIP, vflip=config.CAMERA_VFLIP)

        self._picam2 = Picamera2()
        cam_config = self._picam2.create_preview_configuration(
            main={"size": self.resolution, "format": "RGB888"},
            controls={"FrameRate": self.fps},
            buffer_count=4,
            **kwargs,
        )
        self._picam2.configure(cam_config)
        self._picam2.start()
        time.sleep(0.5)  # chờ AE/AWB ổn định
        log.info("Picamera2 started: %s @ %s fps", self.resolution, self.fps)

    def read(self) -> np.ndarray:
        if self._picam2 is not None:
            return self._picam2.capture_array("main")
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError("Không đọc được frame từ webcam.")
        return frame

    def stop(self) -> None:
        if self._picam2 is not None:
            try:
                self._picam2.stop()
                self._picam2.close()
            except Exception:  # noqa: BLE001
                log.exception("Lỗi khi đóng Picamera2")
            self._picam2 = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def capture_loop(camera: Camera, state: GlobalState) -> None:
    """Thread: liên tục lấy frame mới nhất đẩy vào GlobalState."""
    try:
        while not state.stop_event.is_set():
            state.set_raw_frame(camera.read())
    except Exception:  # noqa: BLE001
        log.exception("Camera thread lỗi -> dừng ứng dụng")
        state.stop_event.set()
