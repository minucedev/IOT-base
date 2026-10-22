"""Test riêng webcam USB: lưu ảnh, tùy chọn mở preview trên VNC."""

import argparse
import os
import platform
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", default=os.getenv("CAMERA_INDEX") or os.getenv("CAMERA_URL", "http://10.93.29.44:5000/video_feed"))
    parser.add_argument("--output", default="camera_test.jpg")
    parser.add_argument("--preview", action="store_true", help="Mở cửa sổ trên desktop/VNC, nhấn q để thoát")
    args = parser.parse_args()
    import cv2

    source = int(args.camera) if args.camera.isdecimal() else args.camera
    if args.camera.startswith(("http://", "https://", "rtsp://")):
        backend = cv2.CAP_ANY
    else:
        backend = {"Linux": cv2.CAP_V4L2, "Windows": cv2.CAP_DSHOW}.get(platform.system(), cv2.CAP_ANY)
    camera = cv2.VideoCapture(source, backend)
    try:
        if not camera.isOpened():
            raise RuntimeError(f"Không mở được {args.camera}. Kiểm tra node Video Capture và đóng app camera khác.")
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        frame = None
        for _ in range(20):
            ok, current = camera.read()
            if ok and current is not None:
                frame = current
        if frame is None:
            raise RuntimeError("Webcam không trả ảnh. Kiểm tra nguồn/cáp và định dạng thiết bị.")
        if not cv2.imwrite(args.output, frame):
            raise RuntimeError(f"Không lưu được ảnh {args.output}.")
        print(f"Đã lưu {Path(args.output).resolve()} | kích thước {frame.shape[1]}x{frame.shape[0]}", flush=True)
        if args.preview:
            print("Nhấn q trong cửa sổ camera để thoát.", flush=True)
            while True:
                ok, frame = camera.read()
                if not ok or frame is None:
                    raise RuntimeError("Camera ngừng trả ảnh trong lúc preview.")
                cv2.imshow("Test USB camera - q to quit", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        camera.release()
        if args.preview:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
