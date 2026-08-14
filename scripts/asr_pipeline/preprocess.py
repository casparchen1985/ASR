import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import noisereduce as nr
import soundfile as sf

TARGET_LUFS = -16.0
SAMPLE_RATE = 32000  # 保留給人聽的混音成品品質；人聲內容 16kHz 頻寬已足夠，比 48kHz 省下約 1/3 降噪運算量；ASR 那步 faster-whisper 會自己內部轉成它要的取樣率
NOISE_PROP_DECREASE = 0.75  # 過強會讓 ASR 誤判增加，見計劃書 4.3 節


def _ffmpeg():
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg not found in PATH — 請先安裝 ffmpeg（見 env_check.py 的安裝提示）")
    return path


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-2000:]}")
    return result


def normalize_loudness(input_path: Path, output_wav: Path, target_lufs: float = TARGET_LUFS) -> None:
    ffmpeg = _ffmpeg()

    measure = subprocess.run(
        [
            ffmpeg, "-i", str(input_path),
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    match = re.search(r"\{.*\}", measure.stderr, re.S)
    measured = json.loads(match.group(0)) if match else None

    if measured:
        af = (
            f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:"
            f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
            "linear=true:print_format=summary"
        )
    else:
        af = f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"

    _run([
        ffmpeg, "-y", "-i", str(input_path),
        "-af", af,
        "-ar", str(SAMPLE_RATE), "-ac", "1",
        str(output_wav),
    ])


def reduce_ac_noise(input_wav: Path, output_wav: Path) -> None:
    audio, sr = sf.read(str(input_wav))
    cleaned = nr.reduce_noise(y=audio, sr=sr, stationary=True, prop_decrease=NOISE_PROP_DECREASE)
    sf.write(str(output_wav), cleaned, sr)


def dynamic_gain(input_path: Path, output_wav: Path) -> None:
    """逐時段動態調整響度（ffmpeg dynaudnorm），取代 normalize_loudness 對整條軌套用單一線性增益的作法。
    單軌內不同講者/距離造成的音量差異依各自所在時段分別調整，避免離麥克風遠的時段因為
    整條軌平均響度偏低而被過度放大，連噪音底一起拉大（見 README 已知限制）。"""
    ffmpeg = _ffmpeg()
    _run([
        ffmpeg, "-y", "-i", str(input_path),
        "-af", "dynaudnorm",
        "-ar", str(SAMPLE_RATE), "-ac", "1",
        str(output_wav),
    ])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: preprocess.py <input_audio> <output_wav>")
        sys.exit(1)
    with tempfile.TemporaryDirectory() as tmp:
        gained = Path(tmp) / "gained.wav"
        dynamic_gain(Path(sys.argv[1]), gained)
        reduce_ac_noise(gained, Path(sys.argv[2]))
    print(f"done: {sys.argv[2]}")
