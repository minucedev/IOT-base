"""TCP Audio Stream Client cho Raspberry Pi.

Nhận luồng âm thanh PCM thô (16kHz, mono, float32) từ Laptop qua TCP Socket.
Thay thế cho sounddevice.InputStream đọc từ I2S INMP441 trên Raspberry Pi.
"""

import os
import socket
import time
from typing import Generator, Optional
import numpy as np

# =====================================================================
# CẤU HÌNH KẾT NỐI STREAM MICROPHONE TỪ LAPTOP
# Thay LAPTOP_IP bằng IP của Laptop đang chạy laptop_cam_server
# =====================================================================
LAPTOP_IP = "192.168.1.100"   # <-- Thay IP của Laptop tại đây
AUDIO_PORT = 5001             # Cổng TCP stream Mic
# =====================================================================

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 4  # float32 = 4 bytes


def stream_audio_from_laptop(
    host: Optional[str] = None,
    port: Optional[int] = None,
    blocksize: int = 512,
    retry_delay: float = 2.0,
) -> Generator[np.ndarray, None, None]:
    """Generator liên tục kết nối tới Laptop TCP Audio Server và yield các chunk float32."""
    target_host = host or os.environ.get("LAPTOP_IP", LAPTOP_IP)
    target_port = int(port or os.environ.get("AUDIO_PORT", AUDIO_PORT))
    bytes_needed = blocksize * BYTES_PER_SAMPLE

    print("=" * 66)
    print(" 🎙️ TCP AUDIO CLIENT (RASPBERRY PI)")
    print("=" * 66)
    print(f" Kết nối tới Laptop Mic: {target_host}:{target_port}")
    print(f" Cấu hình âm thanh      : {SAMPLE_RATE} Hz, mono, {blocksize} samples/chunk")
    print("-" * 66)
    print(f" >> Để đổi IP Laptop, sửa `LAPTOP_IP` trong `audio_client.py`")
    print("=" * 66)

    sock: Optional[socket.socket] = None
    connected = False

    while True:
        # Nếu chưa kết nối, thử kết nối lại
        if sock is None:
            try:
                print(f"[*] Đang kết nối tới Laptop Mic tại {target_host}:{target_port} ...", flush=True)
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.settimeout(5.0)
                s.connect((target_host, target_port))
                s.settimeout(None)  # Blocking read sau khi kết nối thành công
                sock = s
                connected = True
                print(f"✅ ĐÃ KẾT NỐI THÀNH CÔNG tới microphone của Laptop ({target_host}:{target_port})!\n", flush=True)
            except Exception as exc:
                print(f"[!] Chưa kết nối được ({exc}). Thử lại sau {retry_delay:.0f}s...", flush=True)
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass
                    sock = None
                time.sleep(retry_delay)
                continue

        # Đọc đủ bytes_needed (ví dụ 512 samples * 4 bytes = 2048 bytes)
        raw_buffer = bytearray()
        read_error = False

        while len(raw_buffer) < bytes_needed:
            try:
                chunk = sock.recv(bytes_needed - len(raw_buffer))
                if not chunk:
                    # Server ngắt kết nối
                    print("[!] Mất kết nối từ Laptop Audio Server.", flush=True)
                    read_error = True
                    break
                raw_buffer.extend(chunk)
            except Exception as exc:
                print(f"[!] Lỗi nhận dữ liệu audio: {exc}", flush=True)
                read_error = True
                break

        if read_error or len(raw_buffer) < bytes_needed:
            try:
                sock.close()
            except Exception:
                pass
            sock = None
            connected = False
            time.sleep(1.0)
            continue

        # Chuyển raw bytes thành mảng float32
        samples = np.frombuffer(raw_buffer, dtype=np.float32).copy()
        yield samples
