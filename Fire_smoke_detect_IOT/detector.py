# detector.py
"""
Module nhận diện ngọn lửa sử dụng ONNX Runtime.
Tối ưu hóa:
- Zero-copy color pipeline: Nhận diện trực tiếp mảng RGB từ Picamera2 (không đảo ngược màu).
- Model 480x640 chuẩn tỷ lệ: Giữ nguyên vẹn hình thái ngọn lửa, độ chính xác cao nhất.
- Vectorized post-processing siêu nhanh.
"""

import ast
import os
import threading
import time
import cv2
import numpy as np
import onnxruntime as ort
import config

class FireSmokeDetector:
    def __init__(self, model_path=None):
        self.model_path = model_path or config.MODEL_PATH
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Không tìm thấy file model ONNX tại: {self.model_path}\n"
                f"Hãy đảm bảo file .onnx đã có trong thư mục models/."
            )

        print(f"[Detector] Dang nap model ONNX: {self.model_path} ...")
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 3  # Dùng 3 cores cho AI, để 1 core cho Camera, GUI và OS
        self.session = ort.InferenceSession(
            self.model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"]
        )

        self.input_info = self.session.get_inputs()[0]
        self.input_name = self.input_info.name
        self.output_name = self.session.get_outputs()[0].name

        self.input_shape = self.input_info.shape
        self.input_h = self.input_shape[2] if len(self.input_shape) >= 4 else 480
        self.input_w = self.input_shape[3] if len(self.input_shape) >= 4 else 640

        self.names = self._load_class_names()
        self.conf_threshold = getattr(config, "CONFIDENCE_THRESHOLD", 0.35)
        self.iou_threshold = getattr(config, "IOU_THRESHOLD", 0.45)

        print(f"[Detector] Nap thanh cong ONNX model. Kich thuoc input: ({self.input_w}x{self.input_h})")
        print(f"[Detector] Nhan ho tro: {self.names} | Nguong confidence: {self.conf_threshold}")

    def _load_class_names(self):
        """Đọc danh sách nhãn lớp từ metadata của file ONNX nếu có"""
        default_names = {0: "fire", 1: "smoke"}
        try:
            meta = self.session.get_modelmeta().custom_metadata_map
            if "names" in meta:
                parsed = ast.literal_eval(meta["names"])
                return {int(k): v for k, v in parsed.items()}
        except Exception:
            pass
        return default_names

    def detect(self, frame):
        """
        Chạy nhận diện trên 1 frame ảnh.
        Trả về list các dict:
        [
            {"label": "fire", "conf": float, "box": (x1, y1, x2, y2)},
            ...
        ]
        """
        orig_h, orig_w = frame.shape[:2]

        # 1. Resize về kích thước input của model nếu cần
        if orig_h != self.input_h or orig_w != self.input_w:
            resized = cv2.resize(frame, (self.input_w, self.input_h))
        else:
            resized = frame

        # 2. Chuẩn hóa kênh màu: Chuyển BGR sang RGB cho mạng nơ-ron YOLOv8
        rgb_tensor = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

        tensor = rgb_tensor.transpose((2, 0, 1)).astype(np.float32) / 255.0
        blob = np.expand_dims(tensor, axis=0)

        # 3. Chạy Inference qua ONNX Runtime
        outputs = self.session.run([self.output_name], {self.input_name: blob})
        preds = outputs[0][0]  # shape: (6, num_anchors)
        preds = np.transpose(preds)  # shape: (num_anchors, 6)

        # 4. Trích xuất xác suất các lớp
        scores_matrix = preds[:, 4:]  # (num_anchors, num_classes)
        class_ids = np.argmax(scores_matrix, axis=1)
        confidences = np.max(scores_matrix, axis=1)

        # Lọc theo ngưỡng tin cậy
        mask = confidences >= self.conf_threshold
        if not np.any(mask):
            return []

        filtered_preds = preds[mask]
        filtered_conf = confidences[mask]
        filtered_cls = class_ids[mask]

        cx = filtered_preds[:, 0]
        cy = filtered_preds[:, 1]
        w = filtered_preds[:, 2]
        h = filtered_preds[:, 3]

        scale_x = orig_w / float(self.input_w)
        scale_y = orig_h / float(self.input_h)

        x1 = ((cx - w / 2.0) * scale_x)
        y1 = ((cy - h / 2.0) * scale_y)
        w_scaled = (w * scale_x)
        h_scaled = (h * scale_y)

        boxes_for_nms = np.column_stack([x1, y1, w_scaled, h_scaled]).astype(int).tolist()
        conf_list = filtered_conf.astype(float).tolist()
        cls_list = filtered_cls.astype(int).tolist()

        indices = cv2.dnn.NMSBoxes(
            boxes_for_nms,
            conf_list,
            self.conf_threshold,
            self.iou_threshold
        )

        detections = []
        if len(indices) > 0:
            for idx in np.array(indices).flatten():
                cls_id = cls_list[idx]
                label = self.names.get(cls_id, f"class_{cls_id}")
                conf = conf_list[idx]

                # CHỈ LẤY LỬA ('fire'), bỏ qua khói
                if "fire" in label.lower():
                    bx, by, bw, bh = boxes_for_nms[idx]
                    xmin = max(0, min(orig_w - 1, bx))
                    ymin = max(0, min(orig_h - 1, by))
                    xmax = max(0, min(orig_w - 1, bx + bw))
                    ymax = max(0, min(orig_h - 1, by + bh))

                    detections.append({
                        "label": "fire",
                        "conf": float(conf),
                        "box": (int(xmin), int(ymin), int(xmax), int(ymax))
                    })

        return detections


class AsyncFireDetector:
    """
    Bộ chạy nhận diện bất đồng bộ (Asynchronous Worker):
    - Đưa việc suy luận ONNX vào 1 luồng ngầm chuyên biệt.
    - Giúp luồng chính của Camera/Display luôn đạt 25 - 30 FPS mượt mà.
    - Không bao giờ làm đứng hình hoặc giật camera khi AI đang tính toán.
    """
    def __init__(self, detector):
        self.detector = detector
        self.latest_frame = None
        self.latest_detections = []
        self.lock = threading.Lock()
        self.running = True
        self.has_new_frame = threading.Event()
        self.ai_fps = 0.0

        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        self.last_update_time = time.time()
        print("[AsyncDetector] Da khoi chay luong AI suy luan ngam (Async Thread).")

    def update_frame(self, frame):
        """Cung cấp khung hình mới nhất từ camera cho AI suy luận (không chờ)"""
        with self.lock:
            self.latest_frame = frame
        self.has_new_frame.set()

    def _worker(self):
        count = 0
        t0 = time.time()
        while self.running:
            # Chờ có frame mới cần xử lý (timeout 0.05s)
            if not self.has_new_frame.wait(timeout=0.05):
                continue
            self.has_new_frame.clear()

            with self.lock:
                frame_to_process = self.latest_frame

            if frame_to_process is None:
                continue

            try:
                # Chạy suy luận ONNX
                dets = self.detector.detect(frame_to_process)
                with self.lock:
                    self.latest_detections = dets
                    self.last_update_time = time.time()
            except Exception as e:
                print(f"[AsyncDetector] Loi suy luan AI: {e}")

            count += 1
            now = time.time()
            if now - t0 >= 1.0:
                self.ai_fps = count / (now - t0)
                count = 0
                t0 = now

    def get_detections(self):
        """Lấy kết quả nhận diện mới nhất (không chặn, O(1)) kèm AI FPS"""
        with self.lock:
            return list(self.latest_detections), self.ai_fps

    def stop(self):
        """Dừng luồng AI an toàn"""
        self.running = False
        self.has_new_frame.set()
        if hasattr(self, "thread") and self.thread.is_alive():
            self.thread.join(timeout=1.0)

