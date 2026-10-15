"""GlobalState: trạng thái dùng chung giữa các thread (thread-safe)."""
import threading
import time
from typing import Any, Dict, Optional, Tuple


class _LatestSlot:
    """Giữ giá trị mới nhất + số thứ tự; consumer chờ giá trị mới bằng Condition."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._value: Any = None
        self._seq = 0

    def put(self, value: Any) -> None:
        with self._cond:
            self._value = value
            self._seq += 1
            self._cond.notify_all()

    def wait_newer(self, last_seq: int, timeout: float) -> Optional[Tuple[Any, int]]:
        with self._cond:
            if self._seq == last_seq:
                self._cond.wait(timeout)
            if self._seq == last_seq:
                return None
            return self._value, self._seq

    def get(self) -> Any:
        with self._cond:
            return self._value


class GlobalState:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self._raw = _LatestSlot()    # frame BGR mới nhất từ camera
        self._jpeg = _LatestSlot()   # frame đã vẽ overlay, mã hóa JPEG
        self._overlay = _LatestSlot()
        self._lock = threading.Lock()
        self._status: Dict[str, Any] = {
            "status": "NO_PERSON",
            "alert": False,
            "person_detected": False,
            "neck_angle": None,
            "trunk_angle": None,
            "esh_angle": None,
            "shoulder_tilt": None,
            "side": None,
            "bad_seconds": 0.0,
            "fps": 0.0,
            "inference_ms": 0.0,
            "led": {},
            "timestamp": time.time(),
        }

    # --- frame ---
    def set_raw_frame(self, frame) -> None:
        self._raw.put(frame)

    def wait_raw_frame(self, last_seq: int, timeout: float = 1.0):
        return self._raw.wait_newer(last_seq, timeout)

    def set_jpeg(self, data: bytes) -> None:
        self._jpeg.put(data)

    def wait_jpeg(self, last_seq: int, timeout: float = 1.0):
        return self._jpeg.wait_newer(last_seq, timeout)

    def set_overlay(self, overlay: Any) -> None:
        self._overlay.put(overlay)

    def get_overlay(self) -> Any:
        return self._overlay.get()

    # --- status ---
    def update_status(self, **kwargs) -> None:
        with self._lock:
            self._status.update(kwargs)
            self._status["timestamp"] = time.time()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            snap = dict(self._status)
            snap["led"] = dict(self._status["led"])
            return snap
