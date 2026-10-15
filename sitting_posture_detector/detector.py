"""PoseDetector: YOLOv8n-pose (ONNX) + tính toán góc tư thế Tai - Vai - Hông."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import onnxruntime as ort

import config

log = logging.getLogger(__name__)

# Chỉ số keypoint COCO-17
NOSE, L_EAR, R_EAR = 0, 3, 4
L_SHOULDER, R_SHOULDER = 5, 6
L_HIP, R_HIP = 11, 12

SKELETON: List[Tuple[int, int]] = [
    (0, 1), (0, 2), (1, 3), (2, 4), (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
]


@dataclass
class Person:
    box: Tuple[float, float, float, float]  # x1, y1, x2, y2 (toạ độ ảnh gốc)
    score: float
    keypoints: np.ndarray                   # (17, 3): x, y, conf


@dataclass
class PostureResult:
    status: str = config.STATUS_NO_PERSON
    side: Optional[str] = None              # "left" | "right"
    neck_angle: Optional[float] = None      # vai->tai lệch phương thẳng đứng
    trunk_angle: Optional[float] = None     # hông->vai lệch phương thẳng đứng
    esh_angle: Optional[float] = None       # góc Tai-Vai-Hông tại vai
    shoulder_tilt: Optional[float] = None   # độ lệch đường vai so với ngang (nhìn chính diện)
    landmarks: Optional[Dict[str, Tuple[float, float]]] = None  # ear/shoulder/hip để vẽ


# ------------------------------ Hình học ------------------------------
def angle_from_vertical(p_low: np.ndarray, p_high: np.ndarray) -> float:
    """Góc (0..180°) giữa vector p_low->p_high và phương thẳng đứng hướng lên (ảnh: y xuống)."""
    vx, vy = p_high[0] - p_low[0], p_high[1] - p_low[1]
    return math.degrees(math.atan2(abs(vx), -vy))


def angle_at(vertex: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    """Góc tại `vertex` giữa hai tia vertex->a và vertex->b (độ)."""
    va, vb = a - vertex, b - vertex
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom < 1e-6:
        return 180.0
    cos = float(np.clip(np.dot(va, vb) / denom, -1.0, 1.0))
    return math.degrees(math.acos(cos))


class PoseDetector:
    def __init__(self, model_path: Path = config.MODEL_PATH) -> None:
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Không tìm thấy model: {model_path}. Xem README để export yolov8n-pose.onnx."
            )
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = config.ORT_NUM_THREADS
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=config.ORT_PROVIDERS
        )
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        h, w = inp.shape[2], inp.shape[3]
        self.input_h = h if isinstance(h, int) else config.MODEL_INPUT_SIZE
        self.input_w = w if isinstance(w, int) else config.MODEL_INPUT_SIZE
        self._ema: Dict[str, float] = {}
        log.info("Loaded %s, input %dx%d", model_path.name, self.input_w, self.input_h)

    # ------------------------- Tiền xử lý -------------------------------
    def preprocess(self, frame_bgr: np.ndarray):
        """Letterbox giữ tỉ lệ -> blob NCHW RGB float32 [0,1]."""
        h, w = frame_bgr.shape[:2]
        r = min(self.input_h / h, self.input_w / w)
        new_w, new_h = int(round(w * r)), int(round(h * r))
        resized = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        dw, dh = (self.input_w - new_w) / 2, (self.input_h - new_h) / 2
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        padded = cv2.copyMakeBorder(
            resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
        )
        blob = cv2.dnn.blobFromImage(
            padded, 1 / 255.0, (self.input_w, self.input_h), swapRB=True, crop=False
        )
        return blob, r, (left, top)

    # ------------------------- Hậu xử lý --------------------------------
    def postprocess(self, output: np.ndarray, ratio: float, pad: Tuple[int, int],
                    orig_shape: Tuple[int, int]) -> List[Person]:
        pred = output[0]
        if pred.shape[0] < pred.shape[1]:   # (56, N) -> (N, 56)
            pred = pred.T
        pred = pred[pred[:, 4] >= config.CONF_THRESHOLD]
        if pred.size == 0:
            return []

        cx, cy, bw, bh = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
        boxes_xywh = np.stack([cx - bw / 2, cy - bh / 2, bw, bh], axis=1)
        keep = cv2.dnn.NMSBoxes(
            boxes_xywh.tolist(), pred[:, 4].tolist(),
            config.CONF_THRESHOLD, config.NMS_IOU_THRESHOLD,
        )
        if len(keep) == 0:
            return []
        keep = np.array(keep).flatten()

        oh, ow = orig_shape
        left, top = pad
        people: List[Person] = []
        for i in keep:
            x1 = np.clip((boxes_xywh[i, 0] - left) / ratio, 0, ow - 1)
            y1 = np.clip((boxes_xywh[i, 1] - top) / ratio, 0, oh - 1)
            x2 = np.clip((boxes_xywh[i, 0] + boxes_xywh[i, 2] - left) / ratio, 0, ow - 1)
            y2 = np.clip((boxes_xywh[i, 1] + boxes_xywh[i, 3] - top) / ratio, 0, oh - 1)
            kpts = pred[i, 5:5 + 51].reshape(17, 3).copy()
            kpts[:, 0] = np.clip((kpts[:, 0] - left) / ratio, 0, ow - 1)
            kpts[:, 1] = np.clip((kpts[:, 1] - top) / ratio, 0, oh - 1)
            people.append(Person((x1, y1, x2, y2), float(pred[i, 4]), kpts))
        # Người có box lớn nhất (gần camera nhất) đứng đầu
        people.sort(key=lambda p: (p.box[2] - p.box[0]) * (p.box[3] - p.box[1]), reverse=True)
        return people

    def detect(self, frame_bgr: np.ndarray) -> List[Person]:
        blob, ratio, pad = self.preprocess(frame_bgr)
        output = self.session.run(None, {self.input_name: blob})[0]
        return self.postprocess(output, ratio, pad, frame_bgr.shape[:2])

    # ------------------------- Tư thế -----------------------------------
    def _smooth(self, key: str, value: float) -> float:
        prev = self._ema.get(key)
        a = config.ANGLE_EMA_ALPHA
        self._ema[key] = value if prev is None else a * value + (1 - a) * prev
        return self._ema[key]

    def analyze(self, kpts: Optional[np.ndarray]) -> PostureResult:
        """Tính góc và phân loại tư thế từ 17 keypoints của một người."""
        if kpts is None:
            self._ema.clear()
            return PostureResult(status=config.STATUS_NO_PERSON)

        thr = config.KPT_CONF_THRESHOLD
        sides = {"left": (L_EAR, L_SHOULDER, L_HIP), "right": (R_EAR, R_SHOULDER, R_HIP)}
        best_side, best_conf = None, 0.0
        for name, idx in sides.items():
            conf = float(min(kpts[i, 2] for i in idx))
            if conf > best_conf:
                best_side, best_conf = name, conf
        if best_side is None or best_conf < thr:
            self._ema.clear()
            return PostureResult(status=config.STATUS_UNKNOWN)

        ear_i, sho_i, hip_i = sides[best_side]
        ear, sho, hip = (kpts[i, :2].astype(float) for i in (ear_i, sho_i, hip_i))

        neck = self._smooth("neck", angle_from_vertical(sho, ear))
        trunk = self._smooth("trunk", angle_from_vertical(hip, sho))
        esh = self._smooth("esh", angle_at(sho, ear, hip))

        # Độ nghiêng vai: chỉ tin cậy khi nhìn tương đối chính diện
        tilt = None
        if kpts[L_SHOULDER, 2] >= thr and kpts[R_SHOULDER, 2] >= thr:
            d = kpts[R_SHOULDER, :2] - kpts[L_SHOULDER, :2]
            torso = float(np.linalg.norm(sho - hip))
            if torso > 1 and abs(d[0]) > 0.5 * torso:
                t = abs(math.degrees(math.atan2(d[1], d[0])))
                tilt = self._smooth("tilt", t if t <= 90 else 180 - t)

        if esh < config.SLOUCH_ESH_MIN_DEG:
            status = config.STATUS_SLOUCH
        elif neck > config.NECK_FORWARD_MAX_DEG:
            status = config.STATUS_HEAD_DOWN
        elif trunk > config.TRUNK_LEAN_MAX_DEG or (
                tilt is not None and tilt > config.SHOULDER_TILT_MAX_DEG):
            status = config.STATUS_LEAN
        else:
            status = config.STATUS_GOOD

        return PostureResult(
            status=status, side=best_side, neck_angle=neck, trunk_angle=trunk,
            esh_angle=esh, shoulder_tilt=tilt,
            landmarks={"ear": tuple(ear), "shoulder": tuple(sho), "hip": tuple(hip)},
        )
