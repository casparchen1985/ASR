import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.fft import dct

WINDOW_SEC = 2.0
HOP_SEC = 1.0
FRAME_SEC = 0.025
FRAME_HOP_SEC = 0.010
N_MELS = 26
N_MFCC = 13
CHANGE_THRESHOLD = 2.2  # z-score 空間裡相鄰視窗的歐氏距離門檻，超過視為換人講話
MIN_SEGMENT_SEC = 3.0


def _hz_to_mel(hz):
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel):
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _mel_filterbank(sr, n_fft, n_mels=N_MELS, fmin=80.0, fmax=None):
    fmax = fmax or sr / 2
    mel_points = np.linspace(_hz_to_mel(fmin), _hz_to_mel(fmax), n_mels + 2)
    bins = np.floor((n_fft + 1) * _mel_to_hz(mel_points) / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        left, center, right = bins[m - 1], bins[m], bins[m + 1]
        for k in range(left, center):
            fb[m - 1, k] = (k - left) / max(center - left, 1)
        for k in range(center, right):
            fb[m - 1, k] = (right - k) / max(right - center, 1)
    return fb


def _frame_mfcc(frame, mel_fb, n_fft):
    windowed = frame * np.hanning(len(frame))
    spectrum = np.abs(np.fft.rfft(windowed, n=n_fft)) ** 2
    log_mel = np.log(mel_fb.dot(spectrum) + 1e-10)
    return dct(log_mel, type=2, norm="ortho")[:N_MFCC]


def _extract_features(y: np.ndarray, sr: int) -> np.ndarray:
    frame_len = int(FRAME_SEC * sr)
    frame_hop = int(FRAME_HOP_SEC * sr)
    n_fft = 1 << (frame_len - 1).bit_length()
    mel_fb = _mel_filterbank(sr, n_fft)

    window_len = int(WINDOW_SEC * sr)
    window_hop = int(HOP_SEC * sr)

    features = []
    for start in range(0, max(1, len(y) - window_len + 1), window_hop):
        chunk = y[start:start + window_len]
        frame_mfccs = [
            _frame_mfcc(chunk[f:f + frame_len], mel_fb, n_fft)
            for f in range(0, len(chunk) - frame_len + 1, frame_hop)
        ]
        if not frame_mfccs:
            continue
        frame_mfccs = np.array(frame_mfccs)
        features.append(np.concatenate([frame_mfccs.mean(axis=0), frame_mfccs.std(axis=0)]))
    return np.array(features)


def diarize(audio_path: Path, change_threshold: float = CHANGE_THRESHOLD, min_segment_sec: float = MIN_SEGMENT_SEC) -> list:
    """回傳 [(start_sec, end_sec), ...]；偵測到聲學特徵明顯改變就切一段，代表可能換人講話，不做身份辨識。

    純 numpy/scipy 實作的古典 MFCC 分段法（刻意不用 resemblyzer/pyannote，因為它們依賴 torch，
    而 PyTorch 已不再提供 Intel macOS 的 wheel，這台機器裝不上）。準確度未拿真實會議錄音驗證過，
    尤其多人共用同一支麥克風時可能偵測不出換人，需要實測後依情況調整 CHANGE_THRESHOLD。
    """
    y, sr = sf.read(str(audio_path))
    if y.ndim > 1:
        y = y.mean(axis=1)

    features = _extract_features(y.astype(np.float64), sr)
    duration = len(y) / sr
    if len(features) == 0:
        return [(0.0, duration)]

    mean = features.mean(axis=0)
    std = features.std(axis=0) + 1e-9
    normalized = (features - mean) / std

    boundaries = [0]
    for i in range(1, len(normalized)):
        if float(np.linalg.norm(normalized[i] - normalized[i - 1])) > change_threshold:
            boundaries.append(i)
    boundaries.append(len(normalized))

    segments = []
    for start_idx, end_idx in zip(boundaries[:-1], boundaries[1:]):
        start_sec = start_idx * HOP_SEC
        end_sec = min((end_idx - 1) * HOP_SEC + WINDOW_SEC, duration)
        segments.append([start_sec, end_sec])

    merged = []
    for seg in segments:
        if merged and (seg[1] - seg[0]) < min_segment_sec:
            merged[-1][1] = seg[1]
        else:
            merged.append(seg)
    return [tuple(s) for s in merged]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: diarize.py <audio_path>")
        sys.exit(1)
    for start, end in diarize(Path(sys.argv[1])):
        print(f"[{start:7.1f}s -> {end:7.1f}s]")
