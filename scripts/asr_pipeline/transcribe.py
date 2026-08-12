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

# 實測過（見 git log／README「已知限制」）：把 Keywords.txt 全部詞彙串成一長串（1000+ 字元、
# 沒有語句結構）直接餵給 Whisper 的 initial_prompt，會讓轉錄開頭一段變成完全無關的幻覺文字。
# 對照測試證實只要縮短並包成自然語句就不會重現這個問題，所以這裡限制長度，並優先保留
# 型號／專有名詞這類 ASR 最常聽錯、且不像人名一樣容易被模型過度腦補的類別。
_PROMPT_LEAD_IN = "以下是這場會議可能提到的產品型號與專有名詞："
_MAX_PROMPT_CHARS = 200
_PRIORITY_HEADER_KEYWORDS = ("product model", "reader", "certificate")


def load_keyword_hint(keywords_path: Path = KEYWORDS_PATH, max_chars: int = _MAX_PROMPT_CHARS) -> str:
    """從 Keywords.txt 讀取分類詞彙表，組成給 Whisper initial_prompt 用的簡短提示。
    每次執行都重新讀取，不快取，確保吃到團隊最新更新的版本。

    分類標頭行（例如 "Software name -"、"Division -"、"PM Head:"）本身不是詞彙，用來分組；
    型號／Reader／認證類別優先排前面，其餘依檔案原順序，再取到字數上限為止。
    """
    if not keywords_path.exists():
        return ""
    text = keywords_path.read_text(encoding="utf-8")

    sections = []
    header, terms = "", []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _HEADER_LINE.match(line):
            if terms:
                sections.append((header, terms))
            header, terms = line, []
            continue
        terms.extend(piece.strip() for piece in line.split(",") if piece.strip())
    if terms:
        sections.append((header, terms))

    def section_priority(h: str) -> int:
        h = h.lower()
        return 0 if any(k in h for k in _PRIORITY_HEADER_KEYWORDS) else 1

    sections.sort(key=lambda s: section_priority(s[0]))

    seen = set()
    ordered_terms = []
    for _h, ts in sections:
        for t in ts:
            if t not in seen:
                seen.add(t)
                ordered_terms.append(t)

    budget = max_chars - len(_PROMPT_LEAD_IN)
    picked, used = [], 0
    for t in ordered_terms:
        added = len(t) + (1 if picked else 0)  # "、" 分隔符也算進預算
        if used + added > budget:
            break
        picked.append(t)
        used += added

    return _PROMPT_LEAD_IN + "、".join(picked) if picked else ""


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
