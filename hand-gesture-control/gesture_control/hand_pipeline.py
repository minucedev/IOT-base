"""Nhận diện cử chỉ bàn tay bằng LiteRT, không cần gói mediapipe.

mediapipe không có wheel cho Python 3.13 trên Pi 4 (bản >= 1.0 lại đòi tập lệnh AES mà
Pi 4 không có). Module này chạy lại đúng bốn model TFLite nằm trong gesture_recognizer.task:
phát hiện lòng bàn tay -> 21 điểm mốc -> embedding -> phân loại 8 nhãn.
Kết quả có cùng hình dạng (hand_landmarks, gestures) mà gesture_logic.choose_gesture đọc.
"""

import io
import math
import zipfile
from types import SimpleNamespace

import cv2
import numpy as np
from ai_edge_litert.interpreter import Interpreter

# Thứ tự đầu ra của canned_gesture_classifier.tflite.
LABELS = ("None", "Closed_Fist", "Open_Palm", "Pointing_Up", "Thumb_Down", "Thumb_Up", "Victory", "ILoveYou")
DETECTOR_SIZE = 192
LANDMARK_SIZE = 224
ROI_SCALE = 2.6
ROI_SHIFT_Y = -0.5


def _anchors():
    """2016 anchor cố định kích thước của palm detector: stride 8 (2/ô) rồi stride 16 (6/ô)."""
    points = []
    for stride, per_cell in ((8, 2), (16, 6)):
        cells = DETECTOR_SIZE // stride
        for y in range(cells):
            for x in range(cells):
                points.extend([((x + 0.5) / cells, (y + 0.5) / cells)] * per_cell)
    return np.array(points, dtype=np.float32)


def _sigmoid(value):
    return 1.0 / (1.0 + np.exp(-np.clip(value, -100.0, 100.0)))


class _Model:
    def __init__(self, content, threads):
        self.interpreter = Interpreter(model_content=content, num_threads=threads)
        self.interpreter.allocate_tensors()
        self.inputs = [d["index"] for d in self.interpreter.get_input_details()]
        self.outputs = [d["index"] for d in self.interpreter.get_output_details()]

    def __call__(self, *tensors):
        for index, tensor in zip(self.inputs, tensors):
            self.interpreter.set_tensor(index, tensor)
        self.interpreter.invoke()
        return [self.interpreter.get_tensor(index)[0].copy() for index in self.outputs]


class GestureRecognizer:
    def __init__(self, task_path, threads=2, min_detection=0.5, min_presence=0.5):
        with zipfile.ZipFile(task_path) as bundle:
            landmarker = zipfile.ZipFile(io.BytesIO(bundle.read("hand_landmarker.task")))
            gesture = zipfile.ZipFile(io.BytesIO(bundle.read("hand_gesture_recognizer.task")))
        self.detector = _Model(landmarker.read("hand_detector.tflite"), threads)
        self.landmarker = _Model(landmarker.read("hand_landmarks_detector.tflite"), threads)
        self.embedder = _Model(gesture.read("gesture_embedder.tflite"), threads)
        self.classifier = _Model(gesture.read("canned_gesture_classifier.tflite"), threads)
        self.anchors = _anchors()
        self.min_detection = min_detection
        self.min_presence = min_presence

    def recognize(self, rgb):
        """rgb: ảnh uint8 (H, W, 3). Trả về đối tượng có hand_landmarks và gestures."""
        empty = SimpleNamespace(hand_landmarks=[], gestures=[])
        roi = self._detect_palm(rgb)
        if roi is None:
            return empty
        landmarks, presence, handedness, world = self.landmarker(self._crop(rgb, roi))
        if float(presence[0]) < self.min_presence:
            return empty
        points, world_points = self._to_image_space(landmarks.reshape(21, 3), world.reshape(21, 3), roi, rgb.shape)
        scores = self._classify(points, world_points, float(handedness[0]))
        category = [SimpleNamespace(category_name=name, score=float(score)) for name, score in zip(LABELS, scores)]
        return SimpleNamespace(
            hand_landmarks=[[SimpleNamespace(x=float(x), y=float(y), z=float(z)) for x, y, z in points]],
            gestures=[category],
        )

    def _detect_palm(self, rgb):
        height, width = rgb.shape[:2]
        scale = DETECTOR_SIZE / max(height, width)
        new_w, new_h = round(width * scale), round(height * scale)
        pad_x, pad_y = (DETECTOR_SIZE - new_w) // 2, (DETECTOR_SIZE - new_h) // 2
        canvas = np.zeros((DETECTOR_SIZE, DETECTOR_SIZE, 3), dtype=np.uint8)
        canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
        raw, logits = self.detector((canvas.astype(np.float32) / 255.0)[None])
        scores = _sigmoid(logits[:, 0])
        best = int(scores.argmax())
        if scores[best] < self.min_detection:
            return None
        row, (anchor_x, anchor_y) = raw[best], self.anchors[best]

        def to_image(x, y):  # tọa độ chuẩn hoá trong ảnh letterbox -> ảnh gốc (0..1)
            return ((x * DETECTOR_SIZE - pad_x) / new_w, (y * DETECTOR_SIZE - pad_y) / new_h)

        cx, cy = to_image(row[0] / DETECTOR_SIZE + anchor_x, row[1] / DETECTOR_SIZE + anchor_y)
        box_w, box_h = row[2] / new_w, row[3] / new_h
        wrist = to_image(row[4] / DETECTOR_SIZE + anchor_x, row[5] / DETECTOR_SIZE + anchor_y)
        middle = to_image(row[8] / DETECTOR_SIZE + anchor_x, row[9] / DETECTOR_SIZE + anchor_y)
        # Xoay sao cho cổ tay -> gốc ngón giữa hướng thẳng lên.
        rotation = math.pi / 2 - math.atan2(-(middle[1] - wrist[1]) * height, (middle[0] - wrist[0]) * width)
        rotation -= 2 * math.pi * math.floor((rotation + math.pi) / (2 * math.pi))
        # Dịch ROI lên phía đầu ngón tay (trong hệ toạ độ đã xoay), rồi làm vuông và phóng to.
        shift = ROI_SHIFT_Y * box_h * height
        cx += -shift * math.sin(rotation) / width
        cy += shift * math.cos(rotation) / height
        side = max(box_w * width, box_h * height) * ROI_SCALE
        return SimpleNamespace(cx=cx * width, cy=cy * height, side=side, rotation=rotation)

    def _crop(self, rgb, roi):
        cos, sin = math.cos(roi.rotation), math.sin(roi.rotation)
        dst = np.array([[0, 0], [LANDMARK_SIZE, 0], [0, LANDMARK_SIZE]], dtype=np.float32)
        src = np.array([
            [roi.cx + dx * cos - dy * sin, roi.cy + dx * sin + dy * cos]
            for dx, dy in (((u / LANDMARK_SIZE - 0.5) * roi.side, (v / LANDMARK_SIZE - 0.5) * roi.side) for u, v in dst)
        ], dtype=np.float32)
        matrix = cv2.getAffineTransform(src, dst)
        crop = cv2.warpAffine(rgb, matrix, (LANDMARK_SIZE, LANDMARK_SIZE), flags=cv2.INTER_LINEAR)
        return (crop.astype(np.float32) / 255.0)[None]

    @staticmethod
    def _to_image_space(landmarks, world, roi, shape):
        height, width = shape[:2]
        cos, sin = math.cos(roi.rotation), math.sin(roi.rotation)
        dx = (landmarks[:, 0] / LANDMARK_SIZE - 0.5) * roi.side
        dy = (landmarks[:, 1] / LANDMARK_SIZE - 0.5) * roi.side
        x = (roi.cx + dx * cos - dy * sin) / width
        y = (roi.cy + dx * sin + dy * cos) / height
        z = landmarks[:, 2] / LANDMARK_SIZE * roi.side / width
        # Điểm mốc thế giới (mét) cũng phải xoay ngược lại theo ROI.
        world_points = np.stack([
            world[:, 0] * cos - world[:, 1] * sin,
            world[:, 0] * sin + world[:, 1] * cos,
            world[:, 2],
        ], axis=1)
        return np.stack([x, y, z], axis=1), world_points

    def _classify(self, points, world_points, handedness):
        # Embedder nhận điểm mốc đã tịnh tiến về cổ tay và chia cho giá trị tuyệt đối lớn nhất.
        relative = points - points[0]
        relative /= max(float(np.abs(relative).max()), 1e-6)
        embedding = self.embedder(
            relative[None].astype(np.float32),
            np.array([[handedness]], dtype=np.float32),
            world_points[None].astype(np.float32),
        )[0]
        return self.classifier(embedding[None])[0]

    def close(self):
        self.detector = self.landmarker = self.embedder = self.classifier = None
