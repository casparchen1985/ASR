import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from nara_wpe.utils import istft, stft
from nara_wpe.wpe import wpe

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# STFT 參數依取樣率從 nara_wpe 官方範例（16kHz, size=512/shift=128）等比例換算到 32kHz，
# 維持相同的時間解析度（32ms 窗／8ms 跳動）。
STFT_SIZE = 1024
STFT_SHIFT = 256

# WPE 論文與 nara_wpe 官方範例的預設值，尚未用真實會議聽感驗證，之後應依實測調整。
WPE_TAPS = 10
WPE_DELAY = 3
WPE_ITERATIONS = 5

# 分段處理長度：避免長會議（實測案例 74.9 分鐘）一次性把整段多聲道 STFT 塞進記憶體。
# 分段交界處保留 OVERLAP_SEC 重疊並交叉淡化，避免每個分段邊界出現接縫雜音。
CHUNK_SEC = 60.0
OVERLAP_SEC = 2.0


def _dereverb_chunk(chunk: np.ndarray) -> np.ndarray:
    """chunk: (D, T) 多聲道時域訊號，回傳同形狀的去殘響結果。"""
    Y = stft(chunk, size=STFT_SIZE, shift=STFT_SHIFT).transpose(2, 0, 1)  # (F, D, T)
    Z = wpe(
        Y, taps=WPE_TAPS, delay=WPE_DELAY, iterations=WPE_ITERATIONS,
        statistics_mode="full",
    ).transpose(1, 2, 0)  # (D, T, F)
    z = istft(Z, size=STFT_SIZE, shift=STFT_SHIFT)
    if z.shape[-1] < chunk.shape[-1]:
        z = np.pad(z, ((0, 0), (0, chunk.shape[-1] - z.shape[-1])))
    else:
        z = z[:, :chunk.shape[-1]]
    return z


def _stitch_chunks(pieces: list, total_len: int, overlap: int) -> np.ndarray:
    """pieces: [(start, end, chunk), ...]，重疊區間用線性交叉淡化後依權重歸一化接合。"""
    d = pieces[0][2].shape[0]
    out = np.zeros((d, total_len))
    weight = np.zeros(total_len)
    for start, end, chunk in pieces:
        length = end - start
        w = np.ones(length)
        if start > 0:
            fade = np.linspace(0.0, 1.0, min(overlap, length))
            w[:len(fade)] = fade
        if end < total_len:
            fade = np.linspace(1.0, 0.0, min(overlap, length))
            w[-len(fade):] = np.minimum(w[-len(fade):], fade)
        out[:, start:end] += chunk[:, :length] * w
        weight[start:end] += w
    weight[weight == 0] = 1.0
    return out / weight


def dereverb_cluster(aligned_wavs: list, output_wavs: list) -> list:
    """把同一群組（已對齊到同一時間軸）的多軌一次餵給 WPE 做多聲道聯合去殘響。

    善用多軌已對齊的事實：多聲道 WPE 用跨軌的空間資訊估計房間脈衝響應，
    效果優於逐軌各自獨立處理。單軌群組（len==1）一樣可以跑，退化為單聲道 WPE。
    """
    signals = []
    sr = None
    for wav in aligned_wavs:
        data, sr = sf.read(str(wav))
        signals.append(data)
    max_len = max(len(s) for s in signals)
    y = np.zeros((len(signals), max_len))
    for i, s in enumerate(signals):
        y[i, :len(s)] = s

    chunk_len = int(CHUNK_SEC * sr)
    overlap = int(OVERLAP_SEC * sr)
    step = chunk_len - overlap

    if max_len <= chunk_len:
        z = _dereverb_chunk(y)
    else:
        pieces = []
        start = 0
        while True:
            end = min(start + chunk_len, max_len)
            pieces.append((start, end, _dereverb_chunk(y[:, start:end])))
            if end == max_len:
                break
            start += step
        z = _stitch_chunks(pieces, max_len, overlap)

    for i, out_path in enumerate(output_wavs):
        sf.write(str(out_path), z[i], sr)
    return output_wavs


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: dereverb.py <output1.wav> [output2.wav ...] -- <input1.wav> [input2.wav ...]")
        sys.exit(1)
    sep = sys.argv.index("--")
    outputs = [Path(p) for p in sys.argv[1:sep]]
    inputs = [Path(p) for p in sys.argv[sep + 1:]]
    dereverb_cluster(inputs, outputs)
    print(f"done: {outputs}")
