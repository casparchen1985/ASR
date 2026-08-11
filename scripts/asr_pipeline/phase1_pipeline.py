import argparse
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows 主控台預設編碼不是 UTF-8，印中文會亂碼甚至報錯
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))
from align_mix import build_merged_recording, _ffmpeg, _ffprobe
from diarize import diarize
from transcribe import transcribe, DEFAULT_MODEL

OWN_OUTPUT_SUFFIX = "_AppDevWeeklyMeeting.m4a"
DRAFT_HEADER = (
    "【草稿，待確認】{name} 會議逐字稿\n"
    "本檔案為語音辨識(ASR)直接輸出，尚未經過 AI 校對，可能包含辨識錯誤與專有名詞誤植。"
    "請先貼進 Claude Code，套用 Keywords.txt／RulesAndRestricts.txt 的規則校對，"
    "校對後再開放團隊訂正彙整定稿。\n\n"
)


def discover_tracks(input_dir: Path) -> list:
    tracks = sorted(
        p for p in input_dir.glob("*.m4a")
        if not p.name.endswith(OWN_OUTPUT_SUFFIX)
    )
    return tracks


def get_duration_seconds(path: Path) -> float:
    ffprobe = _ffprobe()
    result = subprocess.run(
        [ffprobe, "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip() or 0.0)


def confirm_tracks(tracks: list, assume_yes: bool) -> None:
    print(f"掃描到 {len(tracks)} 個原始音軌檔：")
    for t in tracks:
        try:
            duration = get_duration_seconds(t)
            print(f"  - {t.name}  ({duration / 60:.1f} 分鐘)")
        except Exception as e:
            print(f"  - {t.name}  (無法讀取時長: {e})")
    if not tracks:
        raise RuntimeError("資料夾內找不到任何 *.m4a 原始音軌，請確認 --dir 指定正確")
    if not assume_yes:
        answer = input("以上檔案清單正確嗎？確認請輸入 y 繼續：").strip().lower()
        if answer != "y":
            raise SystemExit("使用者取消執行")


def ensure_model_ready(model_size: str = DEFAULT_MODEL) -> None:
    """在背景執行緒把 faster-whisper 模型準備好：本地已有快取就立刻回傳，沒有就下載。
    跟主流程的對齊/混音/分段偵測平行進行，省下轉錄前乾等下載的時間。"""
    from faster_whisper import WhisperModel
    WhisperModel(model_size, device="cpu", compute_type="int8")


def decode_to_wav(m4a_path: Path, wav_path: Path) -> Path:
    ffmpeg = _ffmpeg()
    subprocess.run(
        [ffmpeg, "-y", "-i", str(m4a_path), "-ar", "16000", "-ac", "1", str(wav_path)],
        capture_output=True, text=True, check=True,
    )
    return wav_path


def group_into_paragraphs(asr_segments: list, speaker_segments: list) -> list:
    def speaker_index(t):
        for i, (start, end) in enumerate(speaker_segments):
            if start <= t < end:
                return i
        return -1

    paragraphs = []
    current_speaker = None
    current_lines = []
    for seg in asr_segments:
        midpoint = (seg["start"] + seg["end"]) / 2
        spk = speaker_index(midpoint)
        if spk != current_speaker and current_lines:
            paragraphs.append("".join(current_lines))
            current_lines = []
        current_speaker = spk
        current_lines.append(seg["text"])
    if current_lines:
        paragraphs.append("".join(current_lines))
    return paragraphs


def run(input_dir: Path, date: str, output_dir: Path = None, assume_yes: bool = False, skip_asr: bool = False) -> tuple:
    output_dir = output_dir or input_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{date}_AppDevWeeklyMeeting"

    if not skip_asr:
        model_thread = threading.Thread(target=ensure_model_ready, daemon=True)
        model_thread.start()

    tracks = discover_tracks(input_dir)
    confirm_tracks(tracks, assume_yes)

    merged_m4a = output_dir / f"{stem}.m4a"
    build_merged_recording(tracks, merged_m4a)

    if skip_asr:
        return merged_m4a, None

    with tempfile.TemporaryDirectory() as tmp:
        merged_wav = decode_to_wav(merged_m4a, Path(tmp) / "merged.wav")

        speaker_segments = diarize(merged_wav)

        model_thread.join()  # 確保模型已就緒（已快取的話這裡幾乎不用等）
        asr_segments = transcribe(merged_wav)

    paragraphs = group_into_paragraphs(asr_segments, speaker_segments)
    raw_text = "\n\n".join(paragraphs)

    # AI 校對改為人工貼進 Claude Code 執行（沒有 Anthropic Console/API 計費權限，只有 Claude Team），
    # 這裡只輸出 ASR 原始結果
    transcript_path = output_dir / f"{stem}.txt"
    transcript_path.write_text(DRAFT_HEADER.format(name=stem) + raw_text, encoding="utf-8-sig")

    return merged_m4a, transcript_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="週會資料夾路徑，內含當週原始多軌 *.m4a")
    parser.add_argument("--date", required=True, help="會議日期，格式 yyyyMMdd")
    parser.add_argument("--outdir", default=None, help="輸出資料夾，預設與 --dir 相同")
    parser.add_argument("--yes", action="store_true", help="略過檔案清單確認提示")
    parser.add_argument("--skip-asr", action="store_true", help="混音完成後就停止，不執行分段偵測與 ASR 轉錄")
    args = parser.parse_args()

    m4a_result, txt_result = run(
        Path(args.dir), args.date,
        Path(args.outdir) if args.outdir else None,
        assume_yes=args.yes,
        skip_asr=args.skip_asr,
    )
    print(f"合併錄音: {m4a_result}")
    if txt_result is not None:
        print(f"逐字稿草稿: {txt_result}")
