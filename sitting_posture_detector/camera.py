"""Lấy frame từ luồng video mạng (webcam laptop qua MJPEG/RTSP) bằng OpenCV."""
import logging
import time

import cv2
import numpy as np

import config
from state import GlobalState

log = logging.getLogger(__name__)


class Camera:
    """Đọc frame BGR từ CAMERA_SOURCE (URL stream hoặc chỉ số webcam), tự kết nối lại khi mất."""

    def __init__(self, source=config.CAMERA_SOURCE, resolution=config.CAMERA_RESOLUTION):
        self.source = source
        self.resolution = resolution
        self._cap = None

    def _open(self) -> None:
        if self._cap is not None:
            self._cap.release()
        self._cap = cv2.VideoCapture(self.source)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # luôn lấy frame mới nhất, giảm trễ
        if not self._cap.isOpened():
            raise RuntimeError(f"Không mở được nguồn video: {self.source}")
        log.info("Đã kết nối nguồn video: %s", self.source)

    def start(self) -> None:
        self._open()

    def read(self) -> np.ndarray:
        while True:
            ok, frame = self._cap.read()
            if ok:
                break
            log.warning("Mất frame từ %s, thử kết nối lại sau %.0fs...",
                        self.source, config.CAMERA_RECONNECT_SEC)
            time.sleep(config.CAMERA_RECONNECT_SEC)
            try:
                self._open()
            except RuntimeError as exc:
                log.warning("%s", exc)
        if (frame.shape[1], frame.shape[0]) != tuple(self.resolution):
            frame = cv2.resize(frame, self.resolution)
        if config.CAMERA_HFLIP or config.CAMERA_VFLIP:
            code = -1 if (config.CAMERA_HFLIP and config.CAMERA_VFLIP) else (1 if config.CAMERA_HFLIP else 0)
            frame = cv2.flip(frame, code)
        return frame

    def stop(self) -> None:
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
