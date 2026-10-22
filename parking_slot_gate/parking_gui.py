#!/usr/bin/env python3
"""Giao diện (xem qua VNC) cho bãi đỗ xe: điền IP loa, chọn ảnh, xem kết quả.

Chạy trên Raspberry Pi, trong phiên desktop VNC:
    python3 parking_gui.py
Bấm "Bắt đầu" để bật cảm biến + servo. Đổi ảnh được cả khi đang chạy.
"""
import base64
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path

import cv2

import raspberry_parking_yolov8n_1280_speaker_jpg as core

OUTPUT = Path("results")
RESULT_IMAGE = OUTPUT / "parking_result.png"
PREVIEW_HEIGHT = 420


class QueueWriter:
    """Chuyển print() của core vào ô log của giao diện."""
    def __init__(self, q):
        self.q = q
        self.buffer = ""

    def write(self, text):
        self.buffer += text
        *lines, self.buffer = self.buffer.split("\n")
        for line in lines:
            self.q.put(line)

    def flush(self):
        pass


def to_photo(path, height=PREVIEW_HEIGHT):
    image = cv2.imread(str(path))
    if image is None:
        return None
    h, w = image.shape[:2]
    image = cv2.resize(image, (int(w * height / h), height))
    ok, png = cv2.imencode(".png", image)
    return tk.PhotoImage(data=base64.b64encode(png.tobytes())) if ok else None


class App:
    def __init__(self, root):
        self.root = root
        self.detector = None
        self.hw = None
        self.logs = queue.Queue()
        # Bỏ qua kết quả cũ từ lần chạy trước.
        self.result_mtime = RESULT_IMAGE.stat().st_mtime if RESULT_IMAGE.exists() else 0
        root.title("Bãi đỗ xe thông minh")

        top = tk.Frame(root, padx=10, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="IP laptop loa:").grid(row=0, column=0, sticky="w")
        self.ip = tk.Entry(top, width=22)
        self.ip.grid(row=0, column=1, sticky="w")
        tk.Label(top, text="(để trống = không loa)").grid(row=0, column=2, sticky="w")
        self.test_btn = tk.Button(top, text="Thử loa", command=self.test_speaker)
        self.test_btn.grid(row=0, column=3, padx=5)

        tk.Label(top, text="Ảnh bãi đỗ:").grid(row=1, column=0, sticky="w", pady=6)
        self.scene = tk.StringVar(value="trong")
        labels = {"goc": "Ảnh gốc (27 ô)", "trong": "Còn chỗ", "day": "Hết chỗ"}
        for i, name in enumerate(core.SCENES):
            tk.Radiobutton(top, text=labels.get(name, name), value=name,
                           variable=self.scene, command=self.change_scene
                           ).grid(row=1, column=1 + i, sticky="w")

        buttons = tk.Frame(top)
        buttons.grid(row=2, column=0, columnspan=4, sticky="w", pady=4)
        self.start_btn = tk.Button(buttons, text="Bắt đầu", width=12, bg="#2e7d32",
                                   fg="white", command=self.start)
        self.start_btn.pack(side="left")
        tk.Button(buttons, text="Quét thử 1 lần", width=14,
                  command=self.scan_once).pack(side="left", padx=5)
        tk.Button(buttons, text="Thoát", width=10, command=self.quit).pack(side="left")
        self.status = tk.Label(top, text="Chưa chạy", fg="gray", font=("Arial", 12, "bold"))
        self.status.grid(row=3, column=0, columnspan=4, sticky="w")
        self.distance = tk.Label(top, text="Khoảng cách: -- cm", font=("Arial", 20, "bold"))
        self.distance.grid(row=4, column=0, columnspan=4, sticky="w")

        self.preview = tk.Label(root)
        self.preview.pack(padx=10)
        self.log = tk.Text(root, height=12, width=90)
        self.log.pack(padx=10, pady=10, fill="both", expand=True)

        sys.stdout = QueueWriter(self.logs)
        self.show_image(core.SCENES[self.scene.get()][0])
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(200, self.poll)

    def speaker_url(self):
        ip = self.ip.get().strip()
        if not ip:
            return ""
        if ip.startswith("http"):
            return ip
        return f"http://{ip if ':' in ip else ip + ':8765'}/speak"

    def show_image(self, path):
        photo = to_photo(path)
        if photo is not None:
            self.preview.configure(image=photo)
            self.preview.image = photo

    def get_detector(self):
        image, slots = core.SCENES[self.scene.get()]
        if self.detector is None:
            self.detector = core.ParkingDetector(
                image, slots, "yolov8n_640.onnx", 0.03, 640, str(OUTPUT), iou=0.70)
        return self.detector

    def change_scene(self):
        image, slots = core.SCENES[self.scene.get()]
        if self.detector is not None:
            self.detector.set_scene(image, slots)
        self.show_image(image)

    def background(self, target):
        threading.Thread(target=target, daemon=True).start()

    def test_speaker(self):
        url = self.speaker_url()
        if not url:
            print("[LOA] Chưa điền IP.")
            return
        self.background(lambda: core.AudioNotifier(speaker_url=url).notify(
            "Xin chào. Hệ thống bãi đỗ xe đã kết nối loa.", wait=True))

    def scan_once(self):
        def run():
            try:
                core.print_report(self.get_detector().detect())
            except Exception as exc:
                print(f"[LOI] {exc}")
        self.background(run)

    def start(self):
        url = self.speaker_url()
        self.start_btn.configure(state="disabled")
        self.ip.configure(state="disabled")
        self.status.configure(text=f"Đang chạy | loa: {url or 'tắt'}", fg="#2e7d32")

        def run():
            try:
                detector = self.get_detector()
                self.hw = core.PiHardware()
                core.run_loop(detector, self.hw, core.AudioNotifier(speaker_url=url),
                              sensor_debug=True)
            except Exception as exc:
                print(f"[LOI] {exc}")
                self.root.after(0, lambda: self.status.configure(
                    text=f"Lỗi: {exc}", fg="red"))
        self.background(run)

    def poll(self):
        while not self.logs.empty():
            line = self.logs.get()
            if line.endswith(" cm") and len(line) < 12:
                # Dòng khoảng cách -> chỉ cập nhật nhãn, không ghi log.
                self.distance.configure(text=f"Khoảng cách: {line}")
            else:
                self.log.insert("end", line + "\n")
        # Giữ 300 dòng cuối, tránh ô log phình to làm giao diện đơ.
        if int(self.log.index("end-1c").split(".")[0]) > 300:
            self.log.delete("1.0", "end-300l")
        self.log.see("end")
        # Có kết quả quét mới -> hiện ảnh đã đánh dấu ô.
        if RESULT_IMAGE.exists() and RESULT_IMAGE.stat().st_mtime != self.result_mtime:
            self.result_mtime = RESULT_IMAGE.stat().st_mtime
            self.show_image(RESULT_IMAGE)
        self.root.after(200, self.poll)

    def quit(self):
        if self.hw is not None:
            self.hw.close()
        os._exit(0)


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    root = tk.Tk()
    App(root)
    root.mainloop()
