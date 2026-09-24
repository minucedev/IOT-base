"""Streaming Vietnamese microphone ASR với hynt Zipformer + sherpa-onnx.

Hỗ trợ 2 nguồn âm thanh:
1. Stream qua TCP Socket từ Laptop (mặc định - không cần cảm biến âm thanh cắm vào Pi).
2. Local microphone trên Pi qua sounddevice (khi truyền tham số --local-mic).
"""

from __future__ import annotations

import argparse
import queue
import re
import sys
import time
import unicodedata
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from audio_client import stream_audio_from_laptop, LAPTOP_IP, AUDIO_PORT

SAMPLE_RATE = 16_000
PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = PROJECT_DIR / "models" / "Zipformer-30M-RNNT-Streaming-6000h"
DEFAULT_VAD_MODEL = PROJECT_DIR / "models" / "silero_vad.onnx"


# ---------------------------------------------------------------------------
# Vietnamese command-focused post-processing
# ---------------------------------------------------------------------------
COMMAND_WORDS = (
    "bật", "mở", "tắt", "đóng",
    "động", "cơ", "đèn",
    "hết", "cả", "hai", "và", "đi",
    "nóng", "lạnh", "quá", "trời", "sáng", "tối",
)

COMMAND_FILLERS = {"đi"}

COMMAND_CONFUSIONS = {
    "bực": "bật",
    "bậc": "bật",
    "đống": "đóng",
}


def _strip_vietnamese_marks(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(
        ch
        for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    ).lower()


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (ca != cb),
                )
            )
        previous = current
    return previous[-1]


_COMMAND_ASCII = {}
for _word in COMMAND_WORDS:
    _COMMAND_ASCII.setdefault(_strip_vietnamese_marks(_word), []).append(_word)


def _normalize_command_token(token: str) -> str:
    if token == "2":
        return "hai"
    if token in COMMAND_WORDS:
        return token
    if token in COMMAND_CONFUSIONS:
        return COMMAND_CONFUSIONS[token]

    plain = _strip_vietnamese_marks(token)
    exact = _COMMAND_ASCII.get(plain, [])
    if len(exact) == 1:
        return exact[0]

    if len(plain) >= 2:
        candidates = []
        for word in COMMAND_WORDS:
            target = _strip_vietnamese_marks(word)
            if not target or not plain or target[0] != plain[0]:
                continue
            if abs(len(target) - len(plain)) > 1:
                continue
            dist = _edit_distance(plain, target)
            if dist <= 1:
                candidates.append((dist, word))
        if candidates:
            candidates.sort(key=lambda item: item[0])
            if len(candidates) == 1 or candidates[0][0] < candidates[1][0]:
                return candidates[0][1]

    return token


def postprocess_command_text(text: str) -> str:
    raw_tokens = re.findall(r"[\w]+|[^\w\s]", text.lower(), flags=re.UNICODE)
    cleaned: list[str] = []
    for token in raw_tokens:
        if not token.isalnum():
            continue
        normalized = _normalize_command_token(token)
        if normalized in COMMAND_FILLERS:
            continue
        cleaned.append(normalized)
    return " ".join(cleaned).strip()


# ---------------------------------------------------------------------------
# Models and Sherpa-ONNX runtime
# ---------------------------------------------------------------------------
class ModelFiles(NamedTuple):
    tokens: Path
    encoder: Path
    decoder: Path
    joiner: Path


def import_runtime() -> tuple[Any, Any]:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Cần thư viện numpy. Chạy: pip install numpy") from exc

    try:
        import sherpa_onnx
    except ImportError as exc:
        raise RuntimeError("Cần thư viện sherpa-onnx. Chạy: pip install sherpa-onnx") from exc

    return np, sherpa_onnx


def require_real_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(
            f"Không tìm thấy file {label}: {path}\n"
            f"Hãy chạy script download_models.sh trước."
        )


def find_model_files(model_dir: Path, chunk_size: int) -> ModelFiles:
    pattern_suffix = f"chunk-{chunk_size}-left-128.fp16.onnx"
    encoders = sorted(model_dir.glob(f"encoder-*{pattern_suffix}"))
    decoders = sorted(model_dir.glob(f"decoder-*{pattern_suffix}"))
    joiners = sorted(model_dir.glob(f"joiner-*{pattern_suffix}"))
    tokens = model_dir / "tokens.txt"
    if not tokens.is_file():
        # Repo hynt/Zipformer đóng gói bảng token trực tiếp trong file config.json
        tokens = model_dir / "config.json"

    def pick(matches: list[Path], role: str) -> Path:
        if not matches:
            raise FileNotFoundError(
                f"Không tìm thấy file model {role} phù hợp với chunk-size={chunk_size} tại {model_dir}"
            )
        return matches[0]

    files = ModelFiles(
        tokens=tokens,
        encoder=pick(encoders, "encoder"),
        decoder=pick(decoders, "decoder"),
        joiner=pick(joiners, "joiner"),
    )
    for label, path in zip(ModelFiles._fields, files):
        require_real_file(path, label)
    return files


def create_recognizer(sherpa_onnx: Any, files: ModelFiles, args: argparse.Namespace) -> Any:
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(files.tokens),
        encoder=str(files.encoder),
        decoder=str(files.decoder),
        joiner=str(files.joiner),
        num_threads=getattr(args, "num_threads", getattr(args, "threads", 2)),
        sample_rate=SAMPLE_RATE,
        feature_dim=80,
        decoding_method=getattr(args, "decoding_method", "modified_beam_search"),
        max_active_paths=args.max_active_paths,
        blank_penalty=args.blank_penalty,
        provider=getattr(args, "provider", "cpu"),
        enable_endpoint_detection=False,
    )


def create_vad(sherpa_onnx: Any, args: argparse.Namespace) -> tuple[Any, int]:
    require_real_file(args.vad_model, "VAD model")
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(args.vad_model)
    config.silero_vad.threshold = args.vad_threshold
    config.silero_vad.min_silence_duration = args.min_silence
    config.silero_vad.min_speech_duration = args.min_speech
    config.silero_vad.max_speech_duration = args.max_speech
    config.sample_rate = SAMPLE_RATE
    window_size = int(config.silero_vad.window_size)
    detector = sherpa_onnx.VoiceActivityDetector(
        config,
        buffer_size_in_seconds=max(30, int(args.max_speech) + 5),
    )
    return detector, window_size


def decode_ready(recognizer: Any, stream: Any) -> None:
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)


def finalize_stream(np: Any, recognizer: Any, stream: Any, tail_padding: float) -> str:
    if tail_padding > 0:
        tail = np.zeros(int(tail_padding * SAMPLE_RATE), dtype=np.float32)
        stream.accept_waveform(SAMPLE_RATE, tail)
        decode_ready(recognizer, stream)

    stream.input_finished()
    decode_ready(recognizer, stream)
    return get_result_text(recognizer, stream)


def get_result_text(recognizer: Any, stream: Any) -> str:
    result = recognizer.get_result(stream)
    if hasattr(result, "text"):
        return result.text.strip()
    return str(result).strip()


class SentenceDisplay:
    def __init__(self) -> None:
        self.sentence_number = 0
        self.last_partial = ""
        self.is_terminal = sys.stdout.isatty()

    def speech_started(self) -> None:
        pass

    def partial(self, text: str) -> None:
        if not text or text == self.last_partial:
            return
        self.last_partial = text
        if self.is_terminal:
            print(f"\r\033[2K[đang nói...] {text}", end="", flush=True)
        else:
            print(f"[đang nói...] {text}", flush=True)

    def final(self, text: str) -> None:
        self.sentence_number += 1
        prefix = "\r\033[2K" if self.is_terminal else ""
        shown = text or "(phát hiện giọng nói nhưng chưa rõ từ)"
        print(f"{prefix}[Khẩu lệnh {self.sentence_number}] 🎙️  {shown}", flush=True)
        self.last_partial = ""


def run_asr_pipeline(
    np: Any,
    recognizer: Any,
    vad: Any,
    window_size: int,
    args: argparse.Namespace,
    audio_source_generator: Any,
    on_final: Callable[[str], None] | None = None,
) -> None:
    """Xử lý âm thanh streaming qua Silero VAD và Zipformer."""
    display = SentenceDisplay()
    pre_roll: deque[np.ndarray] = deque(
        maxlen=max(1, int(round(args.pre_roll * SAMPLE_RATE / window_size)))
    )

    stream: Any = None
    active = False
    last_partial_time = 0.0

    print("=" * 66)
    print(" 🚀 HỆ THỐNG NHẬN DIỆN GIỌNG NÓI TIẾNG VIỆT ĐÃ SẴN SÀNG")
    print("=" * 66)
    print(" Hãy nói các khẩu lệnh: 'bật đèn', 'tắt đèn', 'mở động cơ', 'tắt động cơ'...")
    print(" Nhấn Ctrl+C để dừng.")
    print("=" * 66)

    try:
        for samples in audio_source_generator:
            samples = np.asarray(samples, dtype=np.float32)
            pre_roll.append(samples.copy())

            # VAD phát hiện có giọng nói hay không
            vad.accept_waveform(samples)
            speech_now = vad.is_speech_detected()

            if not active and speech_now:
                active = True
                stream = recognizer.create_stream()
                buffered = np.concatenate(list(pre_roll))
                stream.accept_waveform(SAMPLE_RATE, buffered)
                decode_ready(recognizer, stream)
                last_partial_time = 0.0
                display.speech_started()

            elif active and stream is not None:
                stream.accept_waveform(SAMPLE_RATE, samples)
                decode_ready(recognizer, stream)

            if active and stream is not None and args.partial_interval > 0:
                now = time.monotonic()
                if now - last_partial_time >= args.partial_interval:
                    raw_p = get_result_text(recognizer, stream)
                    display.partial(postprocess_command_text(raw_p))
                    last_partial_time = now

            completed_segment = False
            while not vad.empty():
                vad.pop()
                completed_segment = True

            if completed_segment and active and stream is not None:
                raw_text = finalize_stream(np, recognizer, stream, args.tail_padding)
                text = postprocess_command_text(raw_text)
                display.final(text)
                if text and on_final is not None:
                    on_final(text)

                active = False
                stream = None
                last_partial_time = 0.0
                pre_roll.clear()

    except KeyboardInterrupt:
        if active and stream is not None:
            raw_text = finalize_stream(np, recognizer, stream, args.tail_padding)
            text = postprocess_command_text(raw_text)
            display.final(text)
            if text and on_final is not None:
                on_final(text)
        print("\n[*] Đã dừng hệ thống nhận diện giọng nói.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vietnamese Streaming ASR via Laptop Mic or Local Mic")
    parser.add_argument("--laptop-ip", type=str, default=LAPTOP_IP, help=f"IP Laptop chạy audio server (mặc định: {LAPTOP_IP})")
    parser.add_argument("--audio-port", type=int, default=AUDIO_PORT, help=f"Cổng TCP audio (mặc định: {AUDIO_PORT})")
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR, help="Thư mục chứa model Zipformer")
    parser.add_argument("--vad-model", type=Path, default=DEFAULT_VAD_MODEL, help="Đường dẫn file silero_vad.onnx")
    parser.add_argument("--chunk-size", type=int, default=32, choices=(16, 32, 64), help="Kích thước chunk Zipformer")
    parser.add_argument("--num-threads", "--threads", dest="num_threads", type=int, default=2, help="Số luồng CPU cho sherpa-onnx")
    parser.add_argument("--provider", default="cpu", choices=("cpu", "cuda", "coreml"), help="ONNX execution provider")
    parser.add_argument("--decoding-method", default="modified_beam_search", choices=("greedy_search", "modified_beam_search"), help="Thuật toán giải mã ASR")
    parser.add_argument("--max-active-paths", type=int, default=15, help="Beam paths")
    parser.add_argument("--blank-penalty", type=float, default=0.25, help="Blank penalty")
    parser.add_argument("--vad-threshold", type=float, default=0.35, help="Ngưỡng nhạy VAD")
    parser.add_argument("--min-speech", type=float, default=0.12, help="Độ dài tối thiểu tiếng nói (s)")
    parser.add_argument("--min-silence", type=float, default=0.8, help="Độ dài khoảng lặng để ngắt câu (s)")
    parser.add_argument("--max-speech", type=float, default=20.0, help="Độ dài tối đa 1 câu nói (s)")
    parser.add_argument("--pre-roll", type=float, default=0.5, help="Bộ đệm âm thanh trước khi VAD kích hoạt (s)")
    parser.add_argument("--partial-interval", type=float, default=0.25, help="Tần suất cập nhật kết quả từng phần (s)")
    parser.add_argument("--tail-padding", type=float, default=0.30, help="Đệm số 0 sau khi dứt câu (s)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    np, sherpa_onnx = import_runtime()
    files = find_model_files(args.model_dir, args.chunk_size)
    print("[-] Đang nạp mô hình ASR Zipformer...")
    recognizer = create_recognizer(sherpa_onnx, files, args)
    vad, window_size = create_vad(sherpa_onnx, args)

    audio_gen = stream_audio_from_laptop(host=args.laptop_ip, port=args.audio_port, blocksize=window_size)
    run_asr_pipeline(np, recognizer, vad, window_size, args, audio_gen)
