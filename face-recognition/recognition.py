"""RecognitionEngine — pipeline 2 luồng tối ưu cho Raspberry Pi.

Thread A  │  capture_loop : resize + encode JPEG liên tục → _display_jpeg
          │                (không inference, ~15-20 FPS display)
          │
Thread B  │  infer_loop   : lấy frame → detect + recognize mỗi N frame
          │                → cập nhật _last_faces, _latest_name, _fps
          │
Flask     │  engine.latest() → trả _display_jpeg (thread A cập nhật)
          │  engine.status() → trả name/similarity/fps (thread B cập nhật)
"""

import queue
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from camera import Camera
from database import FaceDatabase


class RecognitionEngine:
    """YuNet + SFace — tách display thread và inference thread."""

    def __init__(self, camera: Camera, database: FaceDatabase) -> None:
        self.camera = camera
        self.database = database

        base = Path(__file__).resolve().parent
        det_path = base / "models" / "face_detection_yunet_2023mar.onnx"
        rec_path = base / "models" / "face_recognition_sface_2021dec.onnx"
        if not det_path.exists() or not rec_path.exists():
            raise RuntimeError(
                f"Thiếu model ONNX tại thư mục models/.\n"
                f"Hãy chạy script download_models.sh trước:\n"
                f"  cd {base}\n"
                f"  chmod +x download_models.sh && ./download_models.sh"
            )

        # Giới hạn OpenCV chỉ dùng 2 thread để không tranh CPU với Pi
        cv2.setNumThreads(2)
        self.detector = cv2.FaceDetectorYN.create(str(det_path), "", (320, 320), 0.8, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(rec_path), "")

        self.gallery = self.database.get_gallery()
        self.threshold = 0.363

        # ── Tham số có thể chỉnh ──────────────────────────────────────────
        self.process_width = 320   # resolution inference (nhỏ hơn = nhanh hơn)
        self.process_height = 240
        self.infer_every = 1       # inference mỗi N frame trong infer_loop
        self.log_interval = 5.0     # giây giữa 2 lần ghi DB cùng người
        self.jpeg_quality = 60      # chất lượng stream về browser
        # ─────────────────────────────────────────────────────────────────

        # Shared state — display
        self._display_jpeg: Optional[bytes] = None
        self._display_frame: Optional[np.ndarray] = None
        self._display_lock = threading.Lock()

        # Shared state — inference result
        self._latest_name = "Chưa nhận diện"
        self._latest_similarity = 0.0
        self._latest_fps = 0.0
        self._has_known = False
        self._has_stranger = False
        self._known_person_name = ""
        self._last_faces: list[tuple[np.ndarray, str, float]] = []
        self._infer_lock = threading.RLock()

        # Frame queue: capture_loop → infer_loop (size 1, drop-oldest)
        self._infer_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=1)

        # Control
        self._stop = threading.Event()
        self._pause_infer = threading.Event()   # set=pause, clear=run

        self._capture_thread: Optional[threading.Thread] = None
        self._infer_thread: Optional[threading.Thread] = None

        self._last_logged: dict[int, float] = {}

        # FPS counter — inference (Thread B)
        self._fps_t0 = time.monotonic()
        self._fps_frames = 0

        # FPS counter — capture/display (Thread A)
        self._latest_capture_fps = 0.0
        self._cap_fps_t0 = time.monotonic()
        self._cap_fps_frames = 0
        self._last_frame_counter = -1  # để phát hiện frame mới thật từ camera

    # ── Gallery ──────────────────────────────────────────────────────────

    def reload_gallery(self) -> None:
        with self._infer_lock:
            self.gallery = self.database.get_gallery()

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        self._stop.clear()
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="cap-loop", daemon=True
        )
        self._infer_thread = threading.Thread(
            target=self._infer_loop, name="infer-loop", daemon=True
        )
        self._capture_thread.start()
        self._infer_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._pause_infer.clear()
        for t in (self._capture_thread, self._infer_thread):
            if t:
                t.join(timeout=2)
        self._capture_thread = self._infer_thread = None

    # ── Thread A: capture + draw cached + encode JPEG ────────────────────

    def _capture_loop(self) -> None:
        """
        Chạy nhanh nhất có thể:
          1. Lấy frame mới nhất từ camera
          2. Resize về process_width × process_height
          3. Vẽ bounding box cached (từ infer thread) lên frame
          4. Encode JPEG → _display_jpeg  (Flask stream lấy từ đây)
          5. Đẩy frame vào _infer_queue để infer thread lấy
        """
        while not self._stop.is_set():
            frame, counter = self.camera.get_latest_with_counter()
            if frame is None:
                time.sleep(0.02)
                continue

            is_new_frame = (counter != self._last_frame_counter)
            self._last_frame_counter = counter

            frame = cv2.resize(
                frame,
                (self.process_width, self.process_height),
                interpolation=cv2.INTER_AREA,
            )

            # Vẽ kết quả inference gần nhất lên frame (không cần chờ inference)
            annotated = self._draw_cached(frame)

            ok, buf = cv2.imencode(
                ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            )
            with self._display_lock:
                self._display_frame = annotated.copy()
                if ok:
                    self._display_jpeg = buf.tobytes()

            # FPS capture (Thread A) — chỉ đếm khi camera thực sự có frame mới
            if is_new_frame:
                self._cap_fps_frames += 1
                elapsed = time.monotonic() - self._cap_fps_t0
                if elapsed >= 1.0:
                    cap_fps = self._cap_fps_frames / elapsed
                    self._cap_fps_frames = 0
                    self._cap_fps_t0 = time.monotonic()
                    with self._display_lock:
                        self._latest_capture_fps = cap_fps

            # Đẩy frame cho infer thread — drop nếu infer thread chưa kịp lấy
            try:
                self._infer_queue.put_nowait(frame.copy())
            except queue.Full:
                try:
                    self._infer_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._infer_queue.put_nowait(frame.copy())
                except queue.Full:
                    pass

    # ── Thread B: inference ──────────────────────────────────────────────

    def _infer_loop(self) -> None:
        """
        Chỉ làm inference, không encode JPEG.
        Chạy chậm hơn capture_loop là bình thường.
        """
        counter = 0
        while not self._stop.is_set():
            # Tạm dừng khi register_latest() đang chạy
            if self._pause_infer.is_set():
                time.sleep(0.05)
                continue

            try:
                frame = self._infer_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            counter += 1
            if counter % self.infer_every != 0:
                continue

            try:
                self._run_inference(frame)

                # FPS inference
                self._fps_frames += 1
                elapsed = time.monotonic() - self._fps_t0
                if elapsed >= 1.0:
                    fps = self._fps_frames / elapsed
                    self._fps_frames = 0
                    self._fps_t0 = time.monotonic()
                    with self._infer_lock:
                        self._latest_fps = fps

            except (cv2.error, ValueError) as exc:
                print(f"Inference error: {exc}", flush=True)

    # ── Inference logic ───────────────────────────────────────────────────

    def _detect(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)
        return np.empty((0, 15), dtype=np.float32) if faces is None else faces

    def _match(self, feature: np.ndarray) -> tuple[Optional[dict], float]:
        best_item, best_score = None, -1.0
        with self._infer_lock:
            gallery = list(self.gallery)
        for item in gallery:
            score = float(
                self.recognizer.match(
                    feature,
                    item["embedding"].reshape(1, -1),
                    cv2.FaceRecognizerSF_FR_COSINE,
                )
            )
            if score > best_score:
                best_item, best_score = item, score
        return best_item, best_score

    def _run_inference(self, frame: np.ndarray) -> None:
        faces = self._detect(frame)
        result_name, result_score = "Người lạ", 0.0
        cached: list[tuple[np.ndarray, str, float]] = []
        has_known = False
        has_stranger = False
        known_name = ""

        for face in faces:
            aligned = self.recognizer.alignCrop(frame, face)
            feature = self.recognizer.feature(aligned)
            item, score = self._match(feature)
            name = item["name"] if item and score >= self.threshold else "Người lạ"
            cached.append((face.copy(), name, score))

            if name != "Người lạ":
                has_known = True
                known_name = name
                result_name, result_score = name, score
                person_id = int(item["person_id"])
                now = time.monotonic()
                if now - self._last_logged.get(person_id, 0.0) >= self.log_interval:
                    self.database.log_recognition(person_id, name, score)
                    self._last_logged[person_id] = now
            else:
                has_stranger = True

        with self._infer_lock:
            self._last_faces = cached
            self._latest_name = result_name
            self._latest_similarity = result_score
            self._has_known = has_known
            self._has_stranger = has_stranger
            self._known_person_name = known_name

    # ── Draw helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _draw_face(frame, x, y, w, h, name, score) -> None:
        if name == "Người lạ":
            color = (0, 0, 255)  # Màu đỏ cảnh báo người lạ
            label = "NGUOI LA / UNKNOWN"
        else:
            color = (0, 220, 0)  # Màu xanh lá người đã đăng ký
            label = f"{name} ({score:.2f})"

        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        label_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        y_label = max(20, y - 8)
        cv2.rectangle(
            frame,
            (x, y_label - label_size[1] - 4),
            (x + label_size[0] + 4, y_label + baseline),
            color,
            -1,
        )
        cv2.putText(
            frame,
            label,
            (x + 2, y_label - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 0, 0) if name != "Người lạ" else (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    def _draw_cached(self, frame: np.ndarray) -> np.ndarray:
        with self._infer_lock:
            cached = list(self._last_faces)
        for face, name, score in cached:
            x, y, w, h = [int(v) for v in face[:4]]
            self._draw_face(frame, x, y, w, h, name, score)
        return frame

    # ── Register ─────────────────────────────────────────────────────────

    def register_latest(self, name: str, sample_count: int = 5) -> tuple[bool, str]:
        clean = name.strip()
        if not clean:
            return False, "Tên không được rỗng"

        # Tạm dừng infer thread để tránh race condition ONNX
        self._pause_infer.set()
        try:
            embeddings: list[np.ndarray] = []
            best_frame: Optional[np.ndarray] = None
            deadline = time.monotonic() + 8.0

            while len(embeddings) < sample_count and time.monotonic() < deadline:
                frame = self.camera.get_latest()
                if frame is not None:
                    fr = cv2.resize(
                        frame,
                        (self.process_width, self.process_height),
                        interpolation=cv2.INTER_AREA,
                    )
                    faces = self._detect(fr)
                    if len(faces) == 1:
                        aligned = self.recognizer.alignCrop(fr, faces[0])
                        feature = self.recognizer.feature(aligned).reshape(-1).astype(np.float32)
                        if not any(
                            float(np.linalg.norm(feature - old)) < 0.01 for old in embeddings
                        ):
                            embeddings.append(feature)
                            best_frame = fr.copy()
                time.sleep(0.35)

            if len(embeddings) < 2:
                return False, (
                    f"Chỉ thu được {len(embeddings)} mẫu; hãy nhìn thẳng camera và thử lại"
                )

            person_id = self.database.add_person_embeddings(clean, embeddings)

            if best_frame is not None:
                ok_enc, jpeg_buf = cv2.imencode(
                    ".jpg", best_frame, [cv2.IMWRITE_JPEG_QUALITY, 85]
                )
                if ok_enc:
                    self.database.save_registration_photo(person_id, clean, jpeg_buf.tobytes())

            self.reload_gallery()
            return True, f"Đã lưu {len(embeddings)} mẫu cho {clean}"
        finally:
            self._pause_infer.clear()

    # ── Read state ────────────────────────────────────────────────────────

    def latest(self) -> tuple[Optional[bytes], str, float, float, float]:
        with self._display_lock:
            jpeg = self._display_jpeg
            capture_fps = self._latest_capture_fps
        with self._infer_lock:
            name = self._latest_name
            sim = self._latest_similarity
            fps = self._latest_fps
        return jpeg, name, sim, fps, capture_fps

    def get_status_info(self) -> dict:
        """Lấy dữ liệu hiển thị trực tiếp cho cửa sổ OpenCV và trạng thái AI."""
        with self._display_lock:
            frame = None if self._display_frame is None else self._display_frame.copy()
            cap_fps = self._latest_capture_fps
        with self._infer_lock:
            has_known = self._has_known
            known_name = self._known_person_name
            has_stranger = self._has_stranger
            faces_count = len(self._last_faces)
            infer_fps = self._latest_fps
            latest_name = self._latest_name
            similarity = self._latest_similarity

        return {
            "frame": frame,
            "has_known": has_known,
            "known_name": known_name,
            "has_stranger": has_stranger,
            "faces_count": faces_count,
            "infer_fps": infer_fps,
            "cap_fps": cap_fps,
            "latest_name": latest_name,
            "similarity": similarity,
        }
