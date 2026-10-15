#!/usr/bin/env python3
"""Raspberry Pi prototype: YOLOv8n ONNX 1280 + LCD, sensor, servo + laptop speaker.

Works WITHOUT PyTorch or Ultralytics on the Pi. Export on Colab/laptop:
    YOLO("yolov8n.pt").export(format="onnx", imgsz=1280,
                                  simplify=True, nms=False, half=False)
Rename the exported file to yolov8n_1280.onnx and copy it next to this script.

Detect ONE static image, NO GPIO:
    python raspberry_parking_yolov8n_1280.py --once

Run the Raspberry Pi GPIO demonstration:
    python raspberry_parking_yolov8n_1280_speaker.py --speaker-url http://IP_LAPTOP:8765/speak

Requires ONNX YOLOv8 DETECTION model with COCO 80 classes, raw output
[1, 84, 33600] for input [1, 3, 1280, 1280]. Do not supply a segmentation model.

LAB / DEMONSTRATION ONLY: one ultrasonic sensor cannot ensure a vehicle
is clear of the barrier. Real gates require independent safety devices.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import queue
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from scipy.optimize import linear_sum_assignment
from shapely.geometry import Point, Polygon, box

# GPIO numbers (BCM), NOT physical header pins.
TRIG_GPIO = 23        # Physical 16
ECHO_GPIO = 24        # Physical 18 - MUST reduce HC-SR04 Echo 5 V -> 3.3 V
SERVO_GPIO = 18       # Physical 12 - servo must use appropriate EXTERNAL 5 V
RED_LED_GPIO = 27     # Physical 13 - current-limiting resistor required
GREEN_LED_GPIO = 22   # Physical 15 - current-limiting resistor required
LCD_I2C_ADDR = 0x27   # Sometimes 0x3F; check sudo i2cdetect -y 1

ENTRY_DISTANCE_CM = 50.0
EXIT_DISTANCE_CM = 65.0
CLEAR_CONFIRM_SECONDS = 3.0
POLL_SECONDS = 0.25

MIN_SLOT_COVERAGE = 0.10
MIN_MATCH_SCORE = 0.33
COLOR_OCCUPIED_FRACTION = 0.08  # slot is OCCUPIED if >=8% car-coloured pixels; 0 = off
VEHICLE_CLASSES = (2, 3, 5, 7)  # COCO: car, motorcycle, bus, truck
# Set IDs of persistently obscured slots so a missed car isn't labelled EMPTY.
OCCLUDED_SLOT_IDS = set()  # e.g. {45, 87}


@dataclass
class Slot:
    id: object
    points: list
    poly: Polygon
    anchors: list
    row: int


@dataclass
class ParkingResult:
    total: int
    empty: list
    occupied: list
    unknown: list
    suggested: Slot | None
    vehicle_count: int


def valid_polygon(points):
    poly = Polygon(points)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area <= 1:
        raise ValueError(f"Polygon không hợp lệ: {points}")
    return poly


def slot_anchors(points):
    """Three points along the long axis of a perspective-tilted slot."""
    pts = np.asarray(points, dtype=np.float32)
    if pts.shape != (4, 2):
        raise ValueError("Mỗi ô trong slots.json phải có 4 điểm [x, y].")
    center = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    pts = pts[np.argsort(angles)]
    edges = [np.linalg.norm(pts[(i + 1) % 4] - pts[i]) for i in range(4)]
    if edges[0] + edges[2] >= edges[1] + edges[3]:
        end1, end2 = (pts[1] + pts[2]) / 2, (pts[3] + pts[0]) / 2
    else:
        end1, end2 = (pts[0] + pts[1]) / 2, (pts[2] + pts[3]) / 2
    return [
        (Point(*map(float, end1 * (1 - t) + end2 * t)), weight)
        for t, weight in ((0.25, 0.25), (0.50, 0.50), (0.75, 0.25))
    ]


def row_number(points):
    """Keep the original project's Y thresholds; same source resolution required."""
    y = float(np.asarray(points, dtype=float)[:, 1].mean())
    return 1 if y > 650 else 2 if y > 500 else 3 if y > 380 else 4


def parse_reference_size(text):
    """Convert WIDTHxHEIGHT to tuple. Used when slots.json belongs to another image size."""
    try:
        parts = text.lower().strip().split("x")
        if len(parts) != 2:
            raise ValueError
        width, height = map(int, parts)
        if width <= 0 or height <= 0:
            raise ValueError
        return width, height
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Kích thước phải có dạng WIDTHxHEIGHT, ví dụ 2390x1792"
        ) from exc


def scale_slots_to_image(slots, source_size, target_size):
    """Map original polygons to a resized but camera-aligned image.

    Row is kept from the original slot because guidance rows use fixed Y thresholds.
    Does not solve camera viewpoint or crop changes.
    """
    src_w, src_h = source_size
    dst_w, dst_h = target_size
    sx, sy = dst_w / src_w, dst_h / src_h
    scaled = []
    for slot in slots:
        points = [[float(x) * sx, float(y) * sy] for x, y in slot.points]
        scaled.append(Slot(slot.id, points, valid_polygon(points),
                           slot_anchors(points), slot.row))
    return scaled


def load_slots(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        raw = raw.get("slots", raw.get("parking_slots"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("slots.json cần một danh sách các object {id, polygon}.")
    slots = []
    for item in raw:
        points = item["polygon"]
        slots.append(Slot(item["id"], points, valid_polygon(points),
                          slot_anchors(points), row_number(points)))
    return slots


def match_metrics(slot, vehicle_poly, bbox):
    if not slot.poly.intersects(vehicle_poly):
        return None
    intersection = slot.poly.intersection(vehicle_poly).area
    if intersection <= 0:
        return None
    slot_cov = intersection / slot.poly.area
    vehicle_cov = intersection / vehicle_poly.area
    anchor_score = sum(weight for pt, weight in slot.anchors if vehicle_poly.covers(pt))
    x1, y1, x2, y2 = bbox
    inside = slot.poly.covers(Point((x1 + x2) / 2, (y1 + y2) / 2))
    reliable = (anchor_score >= 0.25 or slot_cov >= 0.28 or
                (vehicle_cov >= 0.45 and slot_cov >= 0.17))
    score = (0.45 * min(slot_cov / 0.55, 1) + 0.35 * anchor_score +
             0.15 * min(vehicle_cov / 0.60, 1) + 0.05 * float(inside))
    passed = slot_cov >= MIN_SLOT_COVERAGE and reliable and score >= MIN_MATCH_SCORE
    return score, passed, slot_cov, anchor_score


def slot_color_fractions(image, slots):
    """Fraction of each slot covered by bright/saturated pixels (car body vs asphalt).

    Backup for COCO YOLO, which misses many cars in top-down aerial views.
    Thin white lines are removed by a morphological opening; polygons are eroded.
    Dark cars/shadows are NOT caught here - YOLO has to cover those.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    bright = (gray > 165).astype(np.uint8)
    saturated = ((hsv[..., 1] > 90) & (hsv[..., 2] > 60)).astype(np.uint8)
    car_like = (cv2.morphologyEx(bright, cv2.MORPH_OPEN, kernel) |
                cv2.morphologyEx(saturated, cv2.MORPH_OPEN, kernel)).astype(bool)
    fractions = []
    for slot in slots:
        mask = np.zeros(gray.shape, np.uint8)
        cv2.fillPoly(mask, [np.asarray(slot.points, np.int32)], 1)
        mask = cv2.erode(mask, np.ones((9, 9), np.uint8)).astype(bool)
        area = int(mask.sum())
        fractions.append(float((car_like & mask).sum() / area) if area else 0.0)
    return fractions


class YoloOnnx:
    """YOLOv8n COCO detection on ONNX Runtime; Torch is not imported.

    Compare against yolov8n.pt with predict(imgsz=1280, rect=False,
    conf=0.12, iou=0.7) when checking inference parity on Colab.
    """

    def __init__(self, model_path, confidence=0.12, imgsz=1280, iou=0.70, threads=2):
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(f"Không tìm thấy model: {path}")
        if not 0 < confidence < 1 or not 0 < iou < 1:
            raise ValueError("confidence và iou phải trong khoảng (0,1).")
        if imgsz <= 0 or imgsz % 32 != 0:
            raise ValueError("--imgsz phải là bội số của 32, ví dụ 960 hoặc 1280.")

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, int(threads))
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        inputs = self.session.get_inputs()
        if len(inputs) != 1 or len(inputs[0].shape) != 4:
            raise ValueError("ONNX phải có 1 input [batch,3,height,width].")
        inp = inputs[0]
        dims = inp.shape
        if isinstance(dims[1], int) and dims[1] != 3:
            raise ValueError(f"ONNX không phải ảnh RGB 3 kênh: {dims}")
        if inp.type not in ("tensor(float)", "tensor(float16)"):
            raise ValueError(f"ONNX có kiểu {inp.type}; cần float32 hoặc float16.")
        self.input_dtype = np.float16 if inp.type == "tensor(float16)" else np.float32

        self.input_name = inp.name
        self.dynamic = not isinstance(dims[2], int) or not isinstance(dims[3], int)
        self.height = int(dims[2]) if isinstance(dims[2], int) else imgsz
        self.width = int(dims[3]) if isinstance(dims[3], int) else imgsz
        self.confidence = float(confidence)
        self.iou = float(iou)
        self.max_det = 300  # Ultralytics predict default
        self.stride = 32

        outputs = [(x.name, x.shape) for x in self.session.get_outputs()]
        print(f"[ONNX] model={path.name} | input={dims} | output={outputs}")
        print(f"[ONNX] conf={confidence} | iou={iou} | class-aware NMS | "
              f"input-size={self.width}x{self.height} | dynamic={self.dynamic}")
        if not self.dynamic and (self.width != imgsz or self.height != imgsz):
            raise ValueError(
                f"ONNX đang có input cố định {self.width}x{self.height}, "
                f"nhưng bạn yêu cầu --imgsz={imgsz}. "
                f"Hãy export lại yolov8n.pt với imgsz={imgsz} trên Colab. "
                "Đổi tham số CLI KHÔNG tự nâng độ phân giải mô hình ONNX."
            )
        if not self.dynamic:
            print(f"[INFO] ONNX fixed {self.width}x{self.height} dùng padding vuông. "
                  f"Để so sánh trên Colab: yolov8n.pt, imgsz={imgsz}, rect=False.")

    def _preprocess(self, image):
        """Ultralytics-style centered letterbox, BGR->RGB, [0,1], NCHW.

        PT predict(rect=True) applies minimum-rectangle padding for one image.
        Dynamic ONNX supports the same layout; fixed ONNX needs full padding.
        """
        old_h, old_w = image.shape[:2]
        r = min(self.height / old_h, self.width / old_w)
        unpad_w = int(round(old_w * r))
        unpad_h = int(round(old_h * r))
        dw = self.width - unpad_w
        dh = self.height - unpad_h
        if self.dynamic:
            dw %= self.stride
            dh %= self.stride
        dw /= 2
        dh /= 2
        left = int(round(dw - 0.1))
        right = int(round(dw + 0.1))
        top = int(round(dh - 0.1))
        bottom = int(round(dh + 0.1))
        if (old_w, old_h) != (unpad_w, unpad_h):
            image = cv2.resize(image, (unpad_w, unpad_h),
                               interpolation=cv2.INTER_LINEAR)
        padded = cv2.copyMakeBorder(image, top, bottom, left, right,
                                    cv2.BORDER_CONSTANT, value=(114, 114, 114))
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        tensor = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None],
                                      dtype=np.float32) / 255.0
        return tensor, r, left, top

    def _decode(self, raw):
        """Decode YOLOv8 [1,84,N] or [1,N,84] into detections.

        The 84 channels are 4 xywh + 80 class probabilities (NO objectness).
        Also supports models exported with NMS output [1,N,6].
        """
        arr = np.asarray(raw, dtype=np.float32)
        if arr.ndim == 3:
            if arr.shape[0] != 1:
                raise ValueError(f"ONNX batch chưa được hỗ trợ: {arr.shape}")
            arr = arr[0]
        if arr.ndim != 2:
            raise ValueError(f"ONNX output shape chưa được hỗ trợ: {arr.shape}")
        if arr.shape[0] in (84, 6) and arr.shape[1] not in (84, 6):
            arr = arr.T
        if arr.shape[1] == 6:
            # A model exported with nms=True can already output xyxy, conf, cls.
            xyxy = np.asarray(arr[:, :4], dtype=np.float32)
            scores = np.asarray(arr[:, 4], dtype=np.float32)
            classes = np.asarray(arr[:, 5], dtype=np.int32)
            valid = np.isfinite(scores) & (scores >= self.confidence) & \
                    np.isin(classes, VEHICLE_CLASSES)
            return xyxy[valid], scores[valid], classes[valid], "xyxy"
        if arr.shape[1] != 84:
            raise ValueError(
                f"Output ONNX {arr.shape} không phải YOLOv8/YOLO11 detect COCO "
                "(84=4+80). Kiểm tra model export task=detect, nms=False."
            )
        class_prob = arr[:, 4:]
        classes = class_prob.argmax(axis=1).astype(np.int32)
        scores = class_prob[np.arange(len(classes)), classes].astype(np.float32)
        valid = np.isfinite(scores) & (scores >= self.confidence) & \
                np.isin(classes, VEHICLE_CLASSES)
        return arr[valid, :4].astype(np.float32), scores[valid], classes[valid], "cxcywh"

    def detect(self, image):
        """Return detections as (x1,y1,x2,y2,conf,class) in original pixels."""
        input_tensor, scale, pad_x, pad_y = self._preprocess(image)
        input_tensor = input_tensor.astype(self.input_dtype, copy=False)
        before = time.perf_counter()
        outputs = self.session.run(None, {self.input_name: input_tensor})
        seconds = time.perf_counter() - before
        if not outputs:
            raise RuntimeError("Model ONNX không trả output")
        raw_boxes, confs, classes, fmt = self._decode(outputs[0])
        image_h, image_w = image.shape[:2]
        records = []
        for raw_box, confidence, cls in zip(raw_boxes, confs, classes):
            if not np.isfinite(raw_box).all():
                continue
            if fmt == "cxcywh":
                cx, cy, bw, bh = map(float, raw_box)
                x1, y1, x2, y2 = (cx-bw/2, cy-bh/2, cx+bw/2, cy+bh/2)
            else:
                x1, y1, x2, y2 = map(float, raw_box)
            x1 = float(np.clip((x1 - pad_x) / scale, 0, image_w))
            x2 = float(np.clip((x2 - pad_x) / scale, 0, image_w))
            y1 = float(np.clip((y1 - pad_y) / scale, 0, image_h))
            y2 = float(np.clip((y2 - pad_y) / scale, 0, image_h))
            if x2 <= x1 or y2 <= y1:
                continue
            records.append((x1, y1, x2, y2, float(confidence), int(cls)))

        # A detection model exported with nms=True already ran its own NMS.
        if fmt == "xyxy":
            result = sorted(records, key=lambda rec: rec[4], reverse=True)[:self.max_det]
            print(f"[ONNX] {seconds:.2f}s | input={input_tensor.shape} | "
                  f"model-NMS={len(result)} xe")
            return result

        # Match Ultralytics: NMS is PER CLASS (agnostic_nms=False), IoU=0.70.
        # Do not accidentally suppress a car because a different class overlaps.
        selected = []
        for cls in VEHICLE_CLASSES:
            candidates = [r for r in records if r[5] == cls]
            if not candidates:
                continue
            boxes_xywh = [[r[0], r[1], r[2] - r[0], r[3] - r[1]]
                          for r in candidates]
            scores = [r[4] for r in candidates]
            keep = cv2.dnn.NMSBoxes(boxes_xywh, scores,
                                   self.confidence, self.iou)
            for idx in np.asarray(keep, dtype=int).reshape(-1):
                selected.append(candidates[int(idx)])
        result = sorted(selected, key=lambda r: r[4], reverse=True)[:self.max_det]
        print(f"[ONNX] {seconds:.2f}s | input={input_tensor.shape} | "
              f"trước NMS={len(records)} | sau NMS={len(result)} xe")
        return result


class ParkingDetector:
    def __init__(self, image_path, slots_path, model_path, confidence, imgsz,
                 output_dir, iou=0.45, threads=2, allow_zero_vehicles=False,
                 slots_reference_size=None, color_threshold=COLOR_OCCUPIED_FRACTION):
        self.color_threshold = color_threshold
        self.image_path = Path(image_path)
        self.slots = load_slots(slots_path)
        self.slots_reference_size = slots_reference_size
        self.model = YoloOnnx(model_path, confidence, imgsz, iou, threads)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.allow_zero_vehicles = allow_zero_vehicles

    def detect(self):
        # OpenCV supports .jpg/.jpeg/.png. The FULL filename must be passed with --image.
        if not self.image_path.is_file():
            raise FileNotFoundError(
                f"Không tìm thấy file ảnh: {self.image_path.resolve()} "
                "(kiểm tra --image parking_full_01.jpg)"
            )
        image = cv2.imread(str(self.image_path))
        if image is None:
            raise ValueError(f"Ảnh không đọc được hoặc bị lỗi: {self.image_path}")
        h, w = image.shape[:2]
        print(f"[INPUT] Ảnh: {self.image_path.name} | kích thước: {w}x{h}", flush=True)
        if self.slots_reference_size:
            ref_w, ref_h = self.slots_reference_size
            slots = scale_slots_to_image(self.slots, (ref_w, ref_h), (w, h))
            print(f"[SLOTS] Quy đổi polygon {ref_w}x{ref_h} -> {w}x{h}; "
                  "chỉ hợp lệ khi ảnh mới cùng góc chụp và vùng cắt.", flush=True)
            aspect_change = abs((w / h) / (ref_w / ref_h) - 1)
            if aspect_change > 0.025:
                print("[CANH BAO] Tỷ lệ ảnh khác >2.5%; cần kiểm tra lại căn chỉnh!", flush=True)
        else:
            slots = self.slots
        if any(x < 0 or x >= w or y < 0 or y >= h
               for slot in slots for x, y in slot.points):
            max_x = max(x for slot in slots for x, _ in slot.points)
            max_y = max(y for slot in slots for _, y in slot.points)
            raise ValueError(
                f"Polygon slots.json vượt ảnh {w}x{h}; tọa độ lớn nhất "
                f"({max_x:.0f},{max_y:.0f}). Nếu tạo slots trên PNG "
                "2390x1792, thêm --slots-reference-size 2390x1792. "
                "Chỉ dùng khi ảnh cùng góc chụp/crop."
            )

        predictions = self.model.detect(image)
        debug_yolo = image.copy()
        vehicles = []
        detection_rows = []
        for x1, y1, x2, y2, confidence, category in predictions:
            detection_rows.append({
                "class_id": category, "confidence": round(confidence, 6),
                "x1": round(x1, 2), "y1": round(y1, 2),
                "x2": round(x2, 2), "y2": round(y2, 2),
            })
            bw, bh = x2 - x1, y2 - y1
            shape = box(x1 + 0.04 * bw, y1 + 0.04 * bh,
                        x2 - 0.04 * bw, y2 - 0.04 * bh)
            vehicles.append((shape, (x1, y1, x2, y2)))
            cv2.rectangle(debug_yolo, (int(x1), int(y1)), (int(x2), int(y2)),
                          (255, 0, 255), 2)
            cv2.putText(debug_yolo, f"{category}:{confidence:.2f}",
                        (int(x1), max(12, int(y1) - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 0, 255), 1)
        cv2.imwrite(str(self.output_dir / "yolo_debug.png"), debug_yolo)
        with open(self.output_dir / "yolo_detections.csv", "w",
                  encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "class_id", "confidence", "x1", "y1", "x2", "y2"
            ])
            writer.writeheader()
            writer.writerows(detection_rows)
        # Model failure / wrong output shouldn't claim all spaces are EMPTY.
        if not vehicles and not self.allow_zero_vehicles:
            raise RuntimeError(
                "YOLO không phát hiện xe nào. Để tránh báo trống sai, "
                "hệ thống KHÔNG mở rào. Kiểm tra yolo_debug.png, "
                "model COCO, --confidence, --imgsz. "
                "Chỉ dùng --allow-zero-vehicles nếu chắc ảnh thật sự không có xe."
            )

        count_slots, count_vehicles = len(slots), len(vehicles)
        scores = np.zeros((count_slots, count_vehicles), dtype=float)
        candidates = {}
        for si, slot in enumerate(slots):
            for vi, (shape, bbox) in enumerate(vehicles):
                metrics = match_metrics(slot, shape, bbox)
                if metrics is None:
                    continue
                candidates[(si, vi)] = metrics
                if metrics[1]:
                    scores[si, vi] = metrics[0]

        matched = {}
        if count_vehicles:
            rows, cols = linear_sum_assignment(-scores)
            for si, vi in zip(rows, cols):
                if scores[si, vi] >= MIN_MATCH_SCORE:
                    matched[si] = vi

        # Second opinion: car-coloured pixels inside the slot. OR with YOLO so a
        # missed car is never reported as EMPTY (wrongly opening the gate).
        color_fractions = slot_color_fractions(image, slots)
        color_occupied = {si for si, frac in enumerate(color_fractions)
                          if self.color_threshold > 0 and frac >= self.color_threshold}

        empty, occupied, unknown = [], [], []
        annotated = image.copy()
        csv_rows = []
        obscured = {str(value) for value in OCCLUDED_SLOT_IDS}
        for si, slot in enumerate(slots):
            if si in matched or si in color_occupied:
                status, color = "OCCUPIED", (0, 0, 255)
                occupied.append(slot)
            elif str(slot.id) in obscured:
                status, color = "UNKNOWN", (0, 165, 255)
                unknown.append(slot)
            else:
                status, color = "EMPTY", (0, 255, 0)
                empty.append(slot)
            pts = np.asarray(slot.points, np.int32).reshape(-1, 1, 2)
            cv2.polylines(annotated, [pts], True, color, 2)
            for anchor_point, _ in slot.anchors:
                cv2.circle(annotated, (int(anchor_point.x), int(anchor_point.y)),
                           3, color, -1)
            x, y = slot.points[0]
            cv2.putText(annotated, f"#{slot.id}", (int(x), max(12, int(y) - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
            candidate = [(vi, met) for (slot_i, vi), met in candidates.items()
                         if slot_i == si]
            best = max(candidate, key=lambda item: item[1][2], default=None)
            csv_rows.append({
                "slot_id": slot.id,
                "status": status,
                "matched_vehicle": matched.get(si, ""),
                "color_fraction": round(color_fractions[si], 3),
                "best_overlap_vehicle": best[0] if best else "",
                "best_score": round(best[1][0], 3) if best else "",
                "slot_coverage": round(best[1][2], 3) if best else "",
                "anchor_score": round(best[1][3], 2) if best else "",
                "passed_filters": best[1][1] if best else False,
            })

        suggested = empty[0] if empty else None  # preserve order in slots.json
        if suggested is not None:
            polygon = np.asarray(suggested.points, np.int32).reshape(-1, 1, 2)
            cv2.polylines(annotated, [polygon], True, (0, 255, 255), 4)
        cv2.imwrite(str(self.output_dir / "parking_result.png"), annotated)
        with open(self.output_dir / "parking_debug.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(csv_rows[0]))
            writer.writeheader()
            writer.writerows(csv_rows)
        return ParkingResult(count_slots, empty, occupied, unknown,
                             suggested, count_vehicles)


def lcd_lines(result):
    if result.suggested is None:
        if result.unknown:
            return "KHONG XAC DINH", "XIN CHO KIEM TRA"
        return "BAI DA DAY!", "XIN QUAY LAI"
    slot = result.suggested
    direction = "TRAI" if slot.row <= 2 else "THANG"
    return (f"TRONG {len(result.empty)}/{result.total}"[:16],
            f"O#{slot.id} {direction} D{slot.row}"[:16])


def print_report(result):
    line1, line2 = lcd_lines(result)
    print(f"\nONNX: {result.vehicle_count} xe | Tong: {result.total} o | "
          f"Trong: {len(result.empty)} | Co xe: {len(result.occupied)} | "
          f"Khong ro: {len(result.unknown)}")
    if result.suggested is not None:
        slot = result.suggested
        direction = "rẽ trái" if slot.row <= 2 else "đi thẳng"
        print(f"Goi y: o #{slot.id}, {direction}, day {slot.row}")
    print(f"+----------------+\n|{line1:<16}|\n|{line2:<16}|\n+----------------+")


class PiHardware:
    def __init__(self, lcd_address):
        # Lazy GPIO import lets --once run without any Raspberry Pi hardware.
        from gpiozero import AngularServo, DistanceSensor, LED
        self.sensor = None
        self.servo = None
        self.red = None
        self.green = None
        self.lcd = None
        try:
            self.red = LED(RED_LED_GPIO)
            self.green = LED(GREEN_LED_GPIO)
            # Power servo with external, adequate 5 V supply + COMMON GND.
            self.servo = AngularServo(SERVO_GPIO, min_angle=0, max_angle=90,
                                      min_pulse_width=0.001,
                                      max_pulse_width=0.002,
                                      initial_angle=0)
            self.sensor = DistanceSensor(trigger=TRIG_GPIO, echo=ECHO_GPIO,
                                         max_distance=2.0, queue_len=5)
            self.set_gate(False)
            try:
                from RPLCD.i2c import CharLCD
                self.lcd = CharLCD("PCF8574", address=lcd_address, port=1,
                                   cols=16, rows=2, auto_linebreaks=False)
                self.display("CHO XE VAO", "HE THONG SAN SANG")
            except Exception as exc:
                print(f"[CANH BAO] LCD không kết nối: {exc}")
        except Exception:
            self.close()
            raise

    def distance_cm(self):
        try:
            cm = 100.0 * self.sensor.distance
            return cm if math.isfinite(cm) else None
        except Exception as exc:
            print(f"[LOI] HC-SR04: {exc}")
            return None

    def set_gate(self, open_gate):
        self.servo.angle = 90 if open_gate else 0
        if open_gate:
            self.red.off()
            self.green.on()
        else:
            self.green.off()
            self.red.on()

    def display(self, line1, line2):
        print(f"LCD: [{line1[:16]}] [{line2[:16]}]")
        if self.lcd is None:
            return
        try:
            self.lcd.cursor_pos = (0, 0)
            self.lcd.write_string(f"{line1:<16}"[:16])
            self.lcd.cursor_pos = (1, 0)
            self.lcd.write_string(f"{line2:<16}"[:16])
        except Exception as exc:
            print(f"[CANH BAO] LCD write: {exc}")

    def close(self):
        # Emergency interrupt: release PWM; don't order barrier to close blindly.
        if self.servo is not None:
            self.servo.detach()
        if self.lcd is not None:
            try:
                self.lcd.clear()
                self.lcd.close(clear=False)
            except Exception:
                pass
        for obj in (self.sensor, self.servo, self.red, self.green):
            if obj is not None:
                obj.close()


def guidance_message(result):
    """Vietnamese announcements spoken only after the decision has been made."""
    if result.suggested is None:
        if result.unknown:
            return ("Hiện không có ô trống nào được xác nhận. "
                    "Xin vui lòng chờ nhân viên kiểm tra.")
        return "Thông báo. Bãi đỗ xe đã hết chỗ. Xin vui lòng quay lại sau."
    slot = result.suggested
    direction = "rẽ trái" if slot.row <= 2 else "đi thẳng"
    return (
        f"Chào mừng bạn đến với bãi đỗ xe. "
        f"Hiện tại còn {len(result.empty)} ô trống. "
        f"Mời bạn {direction}, đến ô số {slot.id}, dãy số {slot.row}."
    )


class AudioNotifier:
    """Send text to Ubuntu laptop over HTTP; fallback is optional local eSpeak.

    Network/TTS is isolated from the GPIO state machine by a small queue.
    No audio failure may change the gate decision.
    """
    def __init__(self, speaker_url=None, token=None, local_voice=False):
        self.speaker_url = (speaker_url or "").strip()
        self.token = token or ""
        self.local_voice = bool(local_voice and not self.speaker_url)
        self.enabled = bool(self.speaker_url or self.local_voice)
        if self.speaker_url:
            parsed = urlsplit(self.speaker_url)
            if parsed.scheme != "http" or not parsed.netloc or parsed.path != "/speak":
                raise ValueError("--speaker-url cần dạng http://IP_LAPTOP:8765/speak")
            if not self.token:
                raise ValueError("Hãy đặt PARKING_SPEAKER_TOKEN trên Raspberry Pi và laptop.")
        if self.local_voice and shutil.which("espeak-ng") is None:
            raise RuntimeError("Không thấy espeak-ng trên Raspberry Pi; hoặc hãy dùng --speaker-url.")
        self.messages = queue.Queue(maxsize=8)
        if self.enabled:
            self.worker = threading.Thread(target=self._worker, daemon=True)
            self.worker.start()

    def _deliver(self, message):
        try:
            if self.speaker_url:
                body = json.dumps({"message": message}, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request(
                    self.speaker_url,
                    data=body,
                    headers={"Content-Type": "application/json; charset=utf-8",
                             "X-Parking-Token": self.token},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=3) as response:
                    if response.status not in (200, 202):
                        raise RuntimeError(f"Speaker HTTP {response.status}")
                print(f"[LOA LAPTOP] Đã gửi: {message}", flush=True)
                return True
            if self.local_voice:
                subprocess.Popen(
                    ["espeak-ng", "-v", "vi", "-s", "125", message],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                print(f"[LOA PI] Đã gửi: {message}", flush=True)
                return True
            print("[LOA] Chưa bật: thêm --speaker-url hoặc --voice", flush=True)
            return False
        except Exception as exc:
            print(f"[CANH BAO] Không gửi được âm thanh: {exc}", flush=True)
            return False

    def _worker(self):
        while True:
            message = self.messages.get()
            try:
                self._deliver(message)
            finally:
                self.messages.task_done()

    def notify(self, message, wait=False):
        if not self.enabled or not message:
            return False
        if wait:
            return self._deliver(message)  # for --test-speaker
        try:
            self.messages.put_nowait(message)
            return True
        except queue.Full:
            print("[CANH BAO] Hàng đợi loa đầy; bỏ thông báo này.", flush=True)
            return False


def run_loop(detector, hw, notifier, sensor_debug=True,
             entry_distance=ENTRY_DISTANCE_CM,
             exit_distance=EXIT_DISTANCE_CM,
             clear_seconds=CLEAR_CONFIRM_SECONDS):
    """Tabletop model only: measure near -> recognize -> OPEN/FULL -> clear -> IDLE.

    An OPEN gate is closed only after a *valid* distance >= exit_distance
    for clear_seconds continuously. Missing data must NOT trigger closure.
    Use --sensor-debug to learn why a gate stays open.
    """
    state = "IDLE"
    near_samples = 0
    clear_since = None
    last_sensor_log = float("-inf")
    last_reason = None
    print(f"[CONFIG] Phát hiện xe <{entry_distance:g} cm; xác nhận rời >= "
          f"{exit_distance:g} cm liên tục {clear_seconds:g} giây.", flush=True)
    print("Đang chờ xe... Ctrl+C để dừng.", flush=True)

    try:
        while True:
            d = hw.distance_cm()
            now = time.monotonic()

            # Explain OPEN/FULL behavior even when the gate never resets.
            if d is None:
                reason = "CAM_BIEN_KHONG_CO_GIA_TRI"
            elif d < exit_distance:
                reason = "VAT_VAN_TRONG_VUNG_CAM_BIEN"
            else:
                reason = "DA_RA_KHOI_VUNG_CAM_BIEN"

            if state in ("OPEN", "FULL"):
                if d is not None and d >= exit_distance:
                    if clear_since is None:
                        clear_since = now
                        print(f"[CAM BIEN] Xe đã xa >= {exit_distance:g} cm. "
                              f"Bắt đầu đếm {clear_seconds:g} giây...", flush=True)
                    elapsed = now - clear_since
                    if elapsed >= clear_seconds:
                        # Always restore initial servo/LED state together.
                        # This runs for OPEN or FULL, even if LEDs drifted.
                        print("[RESET] Hết thời gian xác nhận. "
                              "Đóng servo 0°, tắt LED xanh, bật LED đỏ.", flush=True)
                        hw.set_gate(False)
                        hw.display("CHO XE VAO", "HE THONG SAN SANG")
                        state = "IDLE"
                        near_samples = 0
                        clear_since = None
                        last_reason = None
                        print("[STATE] -> IDLE", flush=True)
                else:
                    if clear_since is not None:
                        print("[CAM BIEN] Khoảng cách không còn >= ngưỡng; "
                              "hủy đếm, phải đủ liên tục mới được đóng.", flush=True)
                    clear_since = None

            if sensor_debug and (now - last_sensor_log >= 1.0 or
                                 (state in ("OPEN", "FULL") and reason != last_reason)):
                distance_text = "KHONG DOC DUOC" if d is None else f"{d:.1f} cm"
                current_clear = (f"{now - clear_since:.1f}/{clear_seconds:g}s"
                                 if clear_since is not None else "0s")
                print(f"[SENSOR] state={state} | distance={distance_text} | "
                      f"{reason} | clear={current_clear} | "
                      f"near_samples={near_samples}", flush=True)
                last_sensor_log = now
                last_reason = reason

            if state == "IDLE":
                if d is not None and d < entry_distance:
                    near_samples += 1
                else:
                    near_samples = 0
                if near_samples >= 2:
                    near_samples = 0
                    hw.display("DANG QUET BAI XE", "VUI LONG DOI...")
                    print(f"[STATE] Phát hiện vật cách {d:.1f} cm. "
                          "Phân tích ảnh tĩnh...", flush=True)
                    try:
                        result = detector.detect()
                    except Exception as exc:
                        print(f"[LOI] Nhận diện: {exc}", flush=True)
                        hw.set_gate(False)
                        hw.display("LOI NHAN DIEN", "RAO DANG DONG")
                        notifier.notify("Hệ thống đang gặp lỗi nhận diện. Xin vui lòng chờ.")
                        state = "FULL"
                        clear_since = None
                        continue

                    print_report(result)
                    # If the object moved away while inference was running, don't open.
                    d_after = hw.distance_cm()
                    after_text = "KHONG DOC DUOC" if d_after is None else f"{d_after:.1f} cm"
                    print(f"[STATE] Nhận diện xong. HC-SR04 sau YOLO: {after_text}", flush=True)
                    if (result.suggested is not None and
                            d_after is not None and d_after < exit_distance):
                        hw.set_gate(True)
                        hw.display(*lcd_lines(result))
                        notifier.notify(guidance_message(result))
                        state = "OPEN"
                        print("[STATE] -> OPEN: servo 90°, LED xanh. "
                              f"Chờ khoảng cách >= {exit_distance:g} cm để đóng.", flush=True)
                    elif result.suggested is None:
                        hw.set_gate(False)
                        hw.display(*lcd_lines(result))
                        notifier.notify(guidance_message(result))
                        state = "FULL"
                        print("[STATE] -> FULL: servo 0°, LED đỏ.", flush=True)
                    else:
                        hw.set_gate(False)
                        hw.display("XE DA ROI", "CHO LUOT TIEP")
                        state = "FULL"
                        print("[STATE] -> FULL: vật không còn trước cảm biến; "
                              "không mở servo.", flush=True)
                    clear_since = None
                    last_reason = None

            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nĐã dừng theo yêu cầu.", flush=True)
    finally:
        # Do not force a real barrier shut during an unexpected shutdown.
        hw.close()


def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi: 143 ô đỗ + YOLOv8n ONNX 1280")
    parser.add_argument("--image", default="parking.jpg", help="Ảnh JPG hoặc PNG, ví dụ parking_full_01.jpg")
    parser.add_argument("--slots-reference-size", type=parse_reference_size, default=None,
                        help="Kích thước ảnh gốc khi tạo slots.json, ví dụ 2390x1792; "
                             "tự co giãn polygon nếu ảnh mới có kích thước khác")
    parser.add_argument("--slots", default="slots.json", help="File polygons {id, polygon}")
    parser.add_argument("--model", default="yolov8n_640.onnx", help="YOLOv8n ONNX detect COCO (file kèm theo là 640)")
    parser.add_argument("--confidence", type=float, default=0.03, help="YOLO confidence")
    parser.add_argument("--iou", type=float, default=0.70, help="NMS IoU threshold")
    parser.add_argument("--imgsz", type=int, default=640, help="Kích thước export ONNX (mặc định 640)")
    parser.add_argument("--threads", type=int, default=2, help="Số CPU threads của ONNX")
    parser.add_argument("--output", default="results", help="Thư mục xuất hình và CSV")
    parser.add_argument("--lcd-address", type=lambda s: int(s, 0), default=LCD_I2C_ADDR)
    parser.add_argument("--voice", action="store_true", help="Dùng espeak-ng ngay trên Pi (không dùng laptop)")
    parser.add_argument("--speaker-url", default="",
                        help="Địa chỉ loa Ubuntu: http://IP_LAPTOP:8765/speak")
    parser.add_argument("--speaker-token", default=os.environ.get("PARKING_SPEAKER_TOKEN", ""),
                        help="Token xác thực; nên đặt bằng biến môi trường PARKING_SPEAKER_TOKEN")
    parser.add_argument("--test-speaker", action="store_true",
                        help="Thử loa laptop ngay, KHÔNG load YOLO, KHÔNG bật GPIO")
    parser.add_argument("--announce-once", action="store_true",
                        help="Với --once: đọc kết quả qua loa đã cấu hình")
    parser.add_argument("--sensor-debug", action="store_true",
                        help="In khoảng cách HC-SR04 và lý do chưa đóng rào mỗi giây")
    parser.add_argument("--entry-distance", type=float, default=ENTRY_DISTANCE_CM,
                        help="Phát hiện vật tới gần khi < ngưỡng này (cm), mặc định 50")
    parser.add_argument("--exit-distance", type=float, default=EXIT_DISTANCE_CM,
                        help="Xác nhận vật đã xa khi >= ngưỡng này (cm), mặc định 65")
    parser.add_argument("--clear-seconds", type=float, default=CLEAR_CONFIRM_SECONDS,
                        help="Thời gian liên tục >= exit-distance để reset (mặc định 3s)")
    parser.add_argument("--color-threshold", type=float, default=COLOR_OCCUPIED_FRACTION,
                        help="Ô có >= tỉ lệ pixel màu xe này thì coi là có xe (0 = tắt)")
    parser.add_argument("--once", action="store_true", help="Chạy nhận diện MỘT LẦN, không GPIO")
    parser.add_argument("--allow-zero-vehicles", action="store_true",
                        help="Chỉ dành cho ảnh bãi trống thực sự; bỏ chặn 0 detection")
    args = parser.parse_args()
    notifier = AudioNotifier(speaker_url=args.speaker_url,
                             token=args.speaker_token, local_voice=args.voice)
    if args.test_speaker:
        if not notifier.enabled:
            parser.error("--test-speaker cần --speaker-url hoặc --voice")
        ok = notifier.notify("Xin chào. Hệ thống bãi đỗ xe đã kết nối loa thành công.", wait=True)
        if not ok:
            raise SystemExit(1)
        return

    detector = ParkingDetector(args.image, args.slots, args.model,
                               args.confidence, args.imgsz, args.output,
                               iou=args.iou, threads=args.threads,
                               allow_zero_vehicles=args.allow_zero_vehicles,
                               slots_reference_size=args.slots_reference_size,
                               color_threshold=args.color_threshold)
    if args.once:
        report = detector.detect()
        print_report(report)
        print(f"Đã lưu: {Path(args.output).resolve()}")
        if args.announce_once:
            notifier.notify(guidance_message(report), wait=True)
        return
    if not 5 <= args.entry_distance < args.exit_distance < 200:
        parser.error("Cần 5 <= entry-distance < exit-distance < 200 cm.")
    if args.clear_seconds < 3.0:
        parser.error("--clear-seconds cần >= 3 giây cho mô hình thử nghiệm.")
    hw = PiHardware(args.lcd_address)
    run_loop(detector, hw, notifier,
             sensor_debug=args.sensor_debug,
             entry_distance=args.entry_distance,
             exit_distance=args.exit_distance,
             clear_seconds=args.clear_seconds)


if __name__ == "__main__":
    main()
