"""Điều phối: camera thread, inference thread, web thread, xử lý Ctrl+C."""
import logging
import signal
import threading
import time

import cv2

import config
from alert import AlertManager
from camera import Camera, capture_loop
from detector import PoseDetector
from display import draw_overlay
from state import GlobalState
from web import WebServer

log = logging.getLogger("main")


def inference_loop(state: GlobalState, detector: PoseDetector, alert: AlertManager) -> None:
    min_interval = 1.0 / config.INFERENCE_MAX_FPS
    seq, fps, last_done = 0, 0.0, time.monotonic()
    try:
        while not state.stop_event.is_set():
            item = state.wait_raw_frame(seq, timeout=1.0)
            if item is None:
                continue
            frame, seq = item
            t0 = time.monotonic()

            persons = detector.detect(frame)
            posture = (detector.analyze(persons[0].keypoints) if persons
                       else detector.analyze(None))
            alert_state = alert.update(posture.status)

            infer_ms = (time.monotonic() - t0) * 1000
            now = time.monotonic()
            inst_fps = 1.0 / max(now - last_done, 1e-6)
            fps = inst_fps if fps == 0 else 0.9 * fps + 0.1 * inst_fps
            last_done = now

            state.set_overlay((persons, posture, alert_state, fps))

            state.update_status(
                status=posture.status, alert=alert_state.is_alert,
                person_detected=bool(persons), side=posture.side,
                neck_angle=posture.neck_angle, trunk_angle=posture.trunk_angle,
                esh_angle=posture.esh_angle, shoulder_tilt=posture.shoulder_tilt,
                bad_seconds=alert_state.bad_seconds, fps=fps, inference_ms=infer_ms,
                led=alert_state.leds,
            )

            spare = min_interval - (time.monotonic() - t0)
            if spare > 0:
                state.stop_event.wait(spare)
    except Exception:  # noqa: BLE001
        log.exception("Inference thread lỗi -> dừng ứng dụng")
        state.stop_event.set()


def stream_loop(state: GlobalState) -> None:
    """Mã hóa từng frame camera mới bằng kết quả nhận diện mới nhất."""
    enc_params = [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_QUALITY]
    seq = 0
    try:
        while not state.stop_event.is_set():
            item = state.wait_raw_frame(seq, timeout=1.0)
            if item is None:
                continue
            frame, seq = item

            overlay = state.get_overlay()
            if overlay is not None:
                persons, posture, alert_state, fps = overlay
                frame = draw_overlay(frame.copy(), persons, posture, alert_state, fps)

            ok, buf = cv2.imencode(".jpg", frame, enc_params)
            if ok:
                state.set_jpeg(buf.tobytes())
    except Exception:  # noqa: BLE001
        log.exception("Video stream thread lỗi -> dừng ứng dụng")
        state.stop_event.set()


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    state = GlobalState()
    detector = PoseDetector()
    alert = AlertManager()
    camera = Camera()
    web = WebServer(state)

    def _handle_stop(signum, _frame):
        log.info("Nhận tín hiệu %s, đang dừng...", signal.Signals(signum).name)
        state.stop_event.set()

    signal.signal(signal.SIGTERM, _handle_stop)

    threads = []
    try:
        camera.start()
        threads = [
            threading.Thread(target=capture_loop, args=(camera, state), name="camera", daemon=True),
            threading.Thread(target=inference_loop, args=(state, detector, alert),
                             name="inference", daemon=True),
            threading.Thread(target=stream_loop, args=(state,), name="stream", daemon=True),
        ]
        for t in threads:
            t.start()
        web.start()
        while not state.stop_event.wait(0.5):
            pass
    except KeyboardInterrupt:
        log.info("Nhận Ctrl+C, đang dừng chương trình...")
    finally:
        state.stop_event.set()
        for t in threads:
            t.join(timeout=3)
        web.stop()
        camera.stop()
        alert.close()
        log.info("Đã dừng.")


if __name__ == "__main__":
    main()
