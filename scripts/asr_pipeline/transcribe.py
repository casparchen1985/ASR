import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows 主控台預設編碼不是 UTF-8，印中文會亂碼甚至報錯
sys.stderr.reconfigure(encoding="utf-8")

from faster_whisper import WhisperModel
from opencc import OpenCC

DEFAULT_MODEL = "large-v3"
KEYWORDS_PATH = Path(__file__).parent.parent.parent / "Keywords.txt"
_s2twp = OpenCC("s2twp")


_HEADER_LINE = re.compile(r"^[\w()（）\s]+[-:：]$")


def load_keyword_hint(keywords_path: Path = KEYWORDS_PATH) -> str:
    """從 Keywords.txt 讀取分類詞彙表（逗號分隔、依分類標頭區隔），組成 Whisper initial_prompt
    用的詞彙提示。每次執行都重新讀取，不快取，確保吃到團隊最新更新的版本。

    分類標頭行（例如 "Software name -"、"Division -"、"PM Head:"）本身不是詞彙，會被跳過；
    其餘每行依逗號拆開，去除頭尾空白後當作詞彙。
    """
    if not keywords_path.exists():
        return ""
    text = keywords_path.read_text(encoding="utf-8")

    terms = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or _HEADER_LINE.match(line):
            continue
        for piece in line.split(","):
            term = piece.strip()
            if term and term not in seen:
                seen.add(term)
                terms.append(term)
    return "、".join(terms)


def transcribe(audio_path: Path, model_size: str = DEFAULT_MODEL, cpu_threads: int = None) -> list:
    threads = cpu_threads or max(1, (os.cpu_count() or 2) - 1)
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=threads)

    initial_prompt = load_keyword_hint() or None

    # Whisper 的 "zh" 解碼預設輸出簡體字，即使音檔是台灣國語也一樣，
    # 因此每個 segment 都要過一次 OpenCC 轉繁體（含台灣慣用詞）
    segments, _info = model.transcribe(
        str(audio_path), language="zh", vad_filter=True, initial_prompt=initial_prompt,
    )

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
