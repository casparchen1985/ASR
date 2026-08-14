import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import correlate

sys.stdout.reconfigure(encoding="utf-8")  # Windows 主控台預設編碼不是 UTF-8，印中文會亂碼甚至報錯
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))
from preprocess import dynamic_gain, reduce_ac_noise, normalize_loudness, SAMPLE_RATE
from dereverb import dereverb_cluster

QUERY_SEC = 300          # 用來搜尋位置的查詢片段長度上限（取自每一軌開頭）
SEARCH_SR = 2000         # 粗略定位搜尋用的低取樣率，只影響搜尋速度，不影響最終混音音質
REFINE_WINDOW_SEC = 1.5  # 粗略定位後，在附近用 SAMPLE_RATE 精修的搜尋窗口半徑（秒）
REFINE_QUERY_SEC = 20    # 精修用的查詢片段長度；太短（例如 2~5 秒）信心值會掉到雜訊等級，測過 20 秒才夠穩定

# 判斷兩軌是否真的有重疊內容的信心門檻（互相關峰值相對雜訊背景的 z-score）。
# 用這次專案手上的真實錄音校準：所有已知「確實重疊」的案例 z 值介於 15~565 之間，10.0 留了安全邊界。
# 沒有真實的「確實不重疊」案例可以測，這個門檻還沒有驗證過負樣本，之後遇到真實案例應該回頭校準。
CONFIDENCE_THRESHOLD = 10.0

# 動態選軌用的短時能量包絡影格參數，跟 diarize.py 現有 MFCC 特徵擷取的影格慣例一致
# （FRAME_SEC=0.025／FRAME_HOP_SEC=0.010），比「判斷粒度需在 50ms 以內」的要求更嚴。
ENERGY_FRAME_SEC = 0.020
ENERGY_HOP_SEC = 0.010
# 最短停留時間：兩軌能量接近時避免頻繁來回切換（chattering）。
MIN_DWELL_SEC = 0.2
# 切換點交叉淡化長度：硬切換結構性避免了多軌疊加造成的空洞感，
# 但切換瞬間仍需要短暫淡入淡出來避免爆音，長度刻意壓短以降低可聞的相位混濁感。
CROSSFADE_SEC = 0.03
# 以上四個閾值都是初始值，尚未用真實會議聽感校準，跟 CONFIDENCE_THRESHOLD 一樣的處境，
# 之後應依實際案例調整。


def _ffmpeg():
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg not found in PATH")
    return path


def _ffprobe():
    # 不能對整個路徑做 ffmpeg->ffprobe 字串取代：安裝路徑裡可能還有其他地方
    # 包含 "ffmpeg" 子字串（例如 winget 裝的資料夾 ffmpeg-9.0-full_build），
    # 取代到就會產生不存在的路徑。只取代檔名部分，且只取代第一個出現處。
    ffmpeg_path = Path(_ffmpeg())
    return str(ffmpeg_path.with_name(ffmpeg_path.name.replace("ffmpeg", "ffprobe", 1)))


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-2000:]}")
    return result


def get_duration_seconds(path: Path) -> float:
    ffprobe = _ffprobe()
    result = subprocess.run(
        [ffprobe, "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip() or 0.0)


def extract_serial_number(path: Path):
    """從檔名擷取可能的序號，用來在聲波比對判定「無重疊」時決定接續順序（聲音內容不重疊就沒有波形依據排序）。
    排除 8 碼的日期格式（yyyyMMdd），取第一個其餘的數字片段；完全找不到就回傳 None。"""
    numbers = re.findall(r"\d+", path.stem)
    candidates = [int(n) for n in numbers if len(n) != 8]
    return candidates[0] if candidates else None


def _decode_low_rate(path: Path, out_path: Path, max_sec: float = None, sr: int = SEARCH_SR) -> Path:
    ffmpeg = _ffmpeg()
    cmd = [ffmpeg, "-y", "-i", str(path)]
    if max_sec is not None:
        cmd += ["-t", str(max_sec)]
    cmd += ["-ar", str(sr), "-ac", "1", str(out_path)]
    _run(cmd)
    return out_path


def locate_offset_seconds(reference_path: Path, target_path: Path) -> tuple:
    """在 reference 全長範圍內搜尋 target 開頭一段內容最匹配的位置。

    回傳 (offset_seconds, confidence)：offset 是 target 相對 reference 起點的偏移秒數；
    confidence 是互相關峰值相對雜訊背景的 z-score，用來判斷這個位置是不是真的匹配，
    還是兩軌根本沒有重疊內容、矮子裡拔將軍硬選出來的爛答案（見 CONFIDENCE_THRESHOLD 說明）。

    不論 target 是完整全場錄音還是被剪過的片段，都用同一套邏輯：只取 target 開頭最多 QUERY_SEC 秒
    當查詢片段，但在整個 reference 長度範圍內搜尋，不假設 target 一定接近 reference 的開頭。
    用低取樣率做搜尋只是加速，不影響最終混音音質。
    """
    with tempfile.TemporaryDirectory() as tmp:
        ref_low = _decode_low_rate(reference_path, Path(tmp) / "ref.wav")
        tgt_low = _decode_low_rate(target_path, Path(tmp) / "tgt.wav", max_sec=QUERY_SEC)
        ref, sr = sf.read(str(ref_low))
        tgt, _ = sf.read(str(tgt_low))
        corr = correlate(ref, tgt, mode="valid", method="fft")
        best = int(np.argmax(corr))
        peak = corr[best]
        baseline = np.median(corr)
        spread = np.std(corr) + 1e-9
        confidence = float((peak - baseline) / spread)
        return best / sr, confidence


def refine_offset_seconds(reference_path: Path, target_path: Path, coarse_offset_sec: float) -> float:
    """粗略定位後的精修：只在粗略偏移點附近一小段窗口內，用 SAMPLE_RATE 重新比對，
    把時間精度從粗略搜尋（SEARCH_SR，毫秒級）提升到取樣點級（1/SAMPLE_RATE，約 20 微秒），
    避免混音疊加同一個聲音來源時，殘餘誤差造成梳狀濾波（聽起來像回音/空洞感）。

    查詢片段長度用 REFINE_QUERY_SEC（實測 2~5 秒信心值會掉到雜訊等級、鎖到錯誤峰值，20 秒才穩定）。
    精修結果信心不夠就直接放棄、沿用粗略估計，不能讓不可靠的精修結果蓋掉本來就對的答案。
    """
    with tempfile.TemporaryDirectory() as tmp:
        ffmpeg = _ffmpeg()
        window_start = max(0.0, coarse_offset_sec - REFINE_WINDOW_SEC)
        ref_clip = Path(tmp) / "ref_clip.wav"
        _run([
            ffmpeg, "-y", "-ss", str(window_start), "-i", str(reference_path),
            "-t", str(REFINE_WINDOW_SEC * 2 + REFINE_QUERY_SEC), "-ar", str(SAMPLE_RATE), "-ac", "1", str(ref_clip),
        ])
        tgt_clip = Path(tmp) / "tgt_clip.wav"
        _run([
            ffmpeg, "-y", "-i", str(target_path),
            "-t", str(REFINE_QUERY_SEC), "-ar", str(SAMPLE_RATE), "-ac", "1", str(tgt_clip),
        ])

        ref, sr = sf.read(str(ref_clip))
        tgt, _ = sf.read(str(tgt_clip))
        if len(tgt) >= len(ref):
            return coarse_offset_sec  # 精修片段比參考片段還長，跳過精修，沿用粗略結果

        corr = correlate(ref, tgt, mode="valid", method="fft")
        best = int(np.argmax(corr))
        peak = corr[best]
        baseline = np.median(corr)
        spread = np.std(corr) + 1e-9
        confidence = float((peak - baseline) / spread)
        if confidence < CONFIDENCE_THRESHOLD:
            return coarse_offset_sec  # 精修信心不夠，沿用粗略估計比較安全

        return window_start + best / sr


def place_on_timeline(track_path: Path, offset_sec: float, total_duration_sec: float, output_wav: Path) -> Path:
    """把 track 放到長度為 total_duration_sec 的共同時間軸上，起點對齊到 offset_sec，其餘補靜音。"""
    ffmpeg = _ffmpeg()
    delay_ms = max(0, round(offset_sec * 1000))
    _run([
        ffmpeg, "-y", "-i", str(track_path),
        "-af", f"adelay={delay_ms}|{delay_ms}",
        "-t", str(total_duration_sec),
        "-ar", str(SAMPLE_RATE), "-ac", "1",
        str(output_wav),
    ])
    return output_wav


def _short_time_energy(y: np.ndarray, sr: int, frame_sec: float, hop_sec: float) -> np.ndarray:
    frame_len = max(1, int(frame_sec * sr))
    hop_len = max(1, int(hop_sec * sr))
    n_frames = max(1, (len(y) - frame_len) // hop_len + 1)
    energy = np.empty(n_frames)
    for i in range(n_frames):
        start = i * hop_len
        chunk = y[start:start + frame_len]
        energy[i] = np.sqrt(np.mean(chunk.astype(np.float64) ** 2) + 1e-12)
    return energy


def _select_active_track(energies: np.ndarray, hop_sec: float, min_dwell_sec: float) -> np.ndarray:
    """energies: (n_tracks, n_frames)，回傳每個影格選中的音軌 index。
    套最短停留時間（遲滯判斷）：候選主軌換人時，要撐滿 min_dwell_sec 才真的切換，
    避免兩軌能量接近時來回快速切換。"""
    selection = np.argmax(energies, axis=0)
    min_dwell_frames = max(1, round(min_dwell_sec / hop_sec))

    current = selection[0]
    since_switch = 0
    smoothed = np.empty(len(selection), dtype=int)
    for i, candidate in enumerate(selection):
        if candidate != current and since_switch >= min_dwell_frames:
            current = candidate
            since_switch = 0
        else:
            since_switch += 1
        smoothed[i] = current
    return smoothed


def mix_tracks(cleaned_wavs: list, output_wav: Path) -> Path:
    """動態選軌混音：依各軌短時能量包絡，每個時刻挑目前最乾淨的一軌，硬切換＋交叉淡化。
    取代原本 ffmpeg amix 單純疊加所有軌——疊加會讓同一聲源同時被多支麥克風收到、
    夾帶不同聲學延遲，聽起來像梳狀濾波的空洞感；硬切換同一時刻只播放一軌，結構性避免這個問題。"""
    if len(cleaned_wavs) == 1:
        shutil.copy(cleaned_wavs[0], output_wav)
        return output_wav

    signals = []
    sr = None
    for wav in cleaned_wavs:
        data, sr = sf.read(str(wav))
        signals.append(data)
    max_len = max(len(s) for s in signals)
    tracks = np.zeros((len(signals), max_len))
    for i, s in enumerate(signals):
        tracks[i, :len(s)] = s

    energies = np.stack([
        _short_time_energy(tracks[i], sr, ENERGY_FRAME_SEC, ENERGY_HOP_SEC)
        for i in range(len(signals))
    ])
    selection = _select_active_track(energies, ENERGY_HOP_SEC, MIN_DWELL_SEC)

    hop_len = max(1, int(ENERGY_HOP_SEC * sr))
    crossfade_len = max(1, int(CROSSFADE_SEC * sr))

    switch_points = [0] + [
        i * hop_len for i in range(1, len(selection)) if selection[i] != selection[i - 1]
    ]
    switch_points.append(max_len)

    mixed = np.zeros(max_len)
    for seg_start, seg_end in zip(switch_points[:-1], switch_points[1:]):
        frame_idx = min(seg_start // hop_len, len(selection) - 1)
        track_idx = selection[frame_idx]
        mixed[seg_start:seg_end] = tracks[track_idx, seg_start:seg_end]

    for cut in switch_points[1:-1]:
        fade_start = max(0, cut - crossfade_len // 2)
        fade_end = min(max_len, cut + crossfade_len // 2)
        length = fade_end - fade_start
        if length <= 0:
            continue
        prev_idx = selection[min(fade_start // hop_len, len(selection) - 1)]
        next_idx = selection[min((fade_end - 1) // hop_len, len(selection) - 1)]
        fade = np.linspace(0.0, 1.0, length)
        mixed[fade_start:fade_end] = (
            tracks[prev_idx, fade_start:fade_end] * (1 - fade)
            + tracks[next_idx, fade_start:fade_end] * fade
        )

    sf.write(str(output_wav), mixed, sr)
    return output_wav


def _find_clusters(track_paths: list) -> list:
    """把輸入軌分群：同一群內彼此聲音內容有重疊、可以互相對齊；群跟群之間視為時間軸上互不重疊
    （例如裝置中途沒電、換另一台裝置接手錄）。

    回傳 [(anchor_path, {member_path: offset_relative_to_anchor}), ...]，遞迴拆出每一群，
    直到剩下的軌彼此都跟目前的參考軌沒有重疊為止。
    """
    if len(track_paths) == 1:
        return [(track_paths[0], {track_paths[0]: 0.0})]

    durations = {p: get_duration_seconds(p) for p in track_paths}
    anchor = max(track_paths, key=lambda p: durations[p])

    members = {anchor: 0.0}
    remaining = []
    for p in track_paths:
        if p == anchor:
            continue
        offset, confidence = locate_offset_seconds(anchor, p)
        if confidence >= CONFIDENCE_THRESHOLD:
            members[p] = refine_offset_seconds(anchor, p, offset)
        else:
            remaining.append(p)

    clusters = [(anchor, members)]
    if remaining:
        clusters += _find_clusters(remaining)
    return clusters


def _cluster_sort_key(cluster: tuple):
    anchor, _members = cluster
    serial = extract_serial_number(anchor)
    if serial is None:
        print(f"警告：{anchor.name} 檔名裡找不到序號，接續順序退回用檔名字母排序，可能不正確，建議人工確認。")
        return (1, anchor.name)
    return (0, serial)


def _build_cluster(members: dict, tmp_dir: Path, idx: int, output_wav: Path) -> Path:
    durations = {p: get_duration_seconds(p) for p in members}
    total_duration = max(offset + durations[p] for p, offset in members.items())

    aligned = []
    for i, (p, offset) in enumerate(members.items()):
        aligned_wav = tmp_dir / f"c{idx}_track{i}_aligned.wav"
        place_on_timeline(p, offset, total_duration, aligned_wav)
        aligned.append(aligned_wav)

    # 去殘響（多軌聯合）要在「原始未處理」的對齊訊號上做，因為 WPE 假設殘響訊號＝乾淨訊號
    # 經房間脈衝響應線性捲積；如果先對每軌各自做動態增益這種非線性調整，會打亂多軌之間
    # 估計共變異數/預測濾波器所依賴的線性關係。
    dereverbed = [tmp_dir / f"c{idx}_track{i}_dereverb.wav" for i in range(len(aligned))]
    dereverb_cluster(aligned, dereverbed)

    gained = []
    for i, wav in enumerate(dereverbed):
        gained_wav = tmp_dir / f"c{idx}_track{i}_gain.wav"
        dynamic_gain(wav, gained_wav)
        gained.append(gained_wav)

    cleaned = []
    for i, wav in enumerate(gained):
        cleaned_wav = tmp_dir / f"c{idx}_track{i}_clean.wav"
        reduce_ac_noise(wav, cleaned_wav)
        cleaned.append(cleaned_wav)

    return mix_tracks(cleaned, output_wav)


def _concat_wavs(wav_paths: list, output_wav: Path) -> Path:
    if len(wav_paths) == 1:
        shutil.copy(wav_paths[0], output_wav)
        return output_wav

    ffmpeg = _ffmpeg()
    concat_list = output_wav.parent / "_concat_list.txt"
    with concat_list.open("w") as f:
        for p in wav_paths:
            f.write(f"file '{p}'\n")
    _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), str(output_wav)])
    concat_list.unlink()
    return output_wav


def build_merged_recording(track_paths: list, output_m4a: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        clusters = _find_clusters(track_paths)
        order = sorted(range(len(clusters)), key=lambda i: _cluster_sort_key(clusters[i]))

        cluster_wavs = []
        for idx in order:
            _anchor, members = clusters[idx]
            cluster_wav = tmp_dir / f"cluster{idx}.wav"
            _build_cluster(members, tmp_dir, idx, cluster_wav)
            cluster_wavs.append(cluster_wav)

        if len(cluster_wavs) > 1:
            print("=== 偵測到錄音無法完全對齊，判定為多段接續（例如裝置中途沒電、換手繼續錄），"
                  "依檔名序號接續，中間不補靜音 ===")
            cumulative = 0.0
            for i, wav in enumerate(cluster_wavs):
                dur = get_duration_seconds(wav)
                if i > 0:
                    print(f"接續點：合併後音檔第 {cumulative:.1f} 秒（約 {cumulative / 60:.1f} 分鐘）處接上下一段")
                cumulative += dur

        merged_wav = tmp_dir / "merged_clusters.wav"
        _concat_wavs(cluster_wavs, merged_wav)

        final_wav = tmp_dir / "final.wav"
        normalize_loudness(merged_wav, final_wav)

        ffmpeg = _ffmpeg()
        _run([ffmpeg, "-y", "-i", str(final_wav), "-c:a", "aac", "-b:a", "192k", str(output_m4a)])
    return output_m4a


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: align_mix.py <output.m4a> <track1> [track2 ...]")
        sys.exit(1)
    output = Path(sys.argv[1])
    tracks = [Path(p) for p in sys.argv[2:]]
    result = build_merged_recording(tracks, output)
    print(f"done: {result}")
