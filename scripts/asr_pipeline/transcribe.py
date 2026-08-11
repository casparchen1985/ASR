import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows 主控台預設編碼不是 UTF-8，印中文會亂碼甚至報錯
sys.stderr.reconfigure(encoding="utf-8")

from faster_whisper import WhisperModel
from opencc import OpenCC

DEFAULT_MODEL = "large-v3"
_s2twp = OpenCC("s2twp")


def transcribe(audio_path: Path, model_size: str = DEFAULT_MODEL, cpu_threads: int = None) -> list:
    threads = cpu_threads or max(1, (os.cpu_count() or 2) - 1)
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=threads)

    # Whisper 的 "zh" 解碼預設輸出簡體字，即使音檔是台灣國語也一樣，
    # 因此每個 segment 都要過一次 OpenCC 轉繁體（含台灣慣用詞）
    segments, _info = model.transcribe(str(audio_path), language="zh", vad_filter=True)

    results = []
    for seg in segments:
        text = _s2twp.convert(seg.text.strip())
        results.append({"start": seg.start, "end": seg.end, "text": text})
        print(f"[{seg.start:7.1f}s -> {seg.end:7.1f}s] {text}")
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: transcribe.py <audio_path> [model_size]")
        sys.exit(1)
    size = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL
    transcribe(Path(sys.argv[1]), size)
