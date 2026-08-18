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
# 判斷「這一刻真的有人講話」的門檻：能量要比該軌自己的雜訊底（低百分位數）高出這個倍數，
# 沒有任何一軌達標就視為沒人講話、不切換，避免停頓時純粹雜訊底高低差異觸發切換
# （2026-08-14 實測發現：不做這層判斷會導致一直聽到背景雜訊忽大忽小）。
SILENCE_MARGIN_RATIO = 2.0
# 判斷「這段發言結束了」的停頓長度：短於此門檻的靜音視為同一段發言內部的換氣停頓／字詞間隙，
# 不算邊界；只有停頓夠長才視為換人講話或換發言的邊界，同一段發言內固定選同一軌
# （2026-08-17 需求：逐影格切換太細，同一人講話過程中換氣瞬間能量波動就可能切到別軌雜訊底，
# 造成背景雜訊忽大忽小；改成整段發言鎖定同一軌）。
SEGMENT_GAP_SEC = 0.7
# 切換點交叉淡化長度：硬切換結構性避免了多軌疊加造成的空洞感，
# 但切換瞬間仍需要短暫淡入淡出來避免爆音，長度刻意壓短以降低可聞的相位混濁感。
CROSSFADE_SEC = 0.03

# 主／從音軌判斷用的加權分數組成：音量與 SNR 各半（2026-08-17 決策）。
# 兩者都刻意用「去殘響後、增益前」（dereverbed）的訊號計算，不能用增益後的訊號——
# dynamic_gain() 的工作目的就是把各時段拉到目標響度，會把音量差異本身抹平，
# 拿增益後的訊號比較「誰原本比較大聲/清晰」會失真。原本另外提案的「加工增益值」
# 指標因此也不需要了：增益前音量已經是同一件事的直接量測，不用再算一次增益量。
VOLUME_WEIGHT = 0.5
SNR_WEIGHT = 0.5
# 判斷「這是真的插話/回應、不是雜訊或洩漏波動」的最短持續時間：同一個發言段內，
# 某個非主軌的分數短暫超過主軌，如果持續不到這個長度，視為雜訊波動或洩漏音，不疊加。
MIN_OVERLAY_SEC = 0.3
# 疊加插話片段前的局部微調對齊：用插話片段前一小段「只有主軌在講話」的內容
# （這段內容多少會被從軌麥克風洩漏收到）重新比對局部延遲殘差，修正裝置間
# 可能累積的時脈漂移；LOCAL_REALIGN_SEARCH_SEC 是搜尋範圍，找到的偏移量本身
# 精度是取樣點級（遠優於 2ms 的目標），但只有殘餘漂移落在搜尋範圍內才找得到。
LOCAL_REALIGN_SEARCH_SEC = 0.05
LOCAL_REALIGN_CONTEXT_SEC = 1.0
# 從軌疊加時的音量平衡上限（線性倍率），避免疊加片段前後過於安靜導致增益計算暴衝。
MAX_OVERLAY_GAIN = 3.0
# 以上七個閾值都是初始值，尚未用真實會議聽感校準，跟 CONFIDENCE_THRESHOLD 一樣的處境，
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


def _to_db(x: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(x, 1e-12))


def _minmax_normalize(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """把 values 正規化到 0~1，範圍由 mask 為 True 的值決定（讓沒人講話的極端值不拉大範圍）。
    正規化要跨軌一起做（同一個 min/max），不能每軌各自正規化——每軌各自正規化會把
    軌間本來就想比較的音量/SNR 差異洗掉，只留下每軌自己時間上的相對高低，失去比較主從的意義。"""
    if not mask.any():
        return np.zeros_like(values)
    pool = values[mask]
    lo, hi = pool.min(), pool.max()
    if hi - lo < 1e-9:
        return np.full_like(values, 0.5)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def _compute_scores(decision_tracks: np.ndarray, sr: int) -> tuple:
    """decision_tracks: (n_tracks, n_samples)，用「去殘響後、增益前」的訊號算主從判斷分數。

    回傳 (is_active, score)，皆為 (n_tracks, n_frames)。score 是音量與 SNR 正規化後
    依 VOLUME_WEIGHT/SNR_WEIGHT 加權加總的結果，用來決定同一時刻哪一軌收音比較好。"""
    energies = np.stack([
        _short_time_energy(decision_tracks[i], sr, ENERGY_FRAME_SEC, ENERGY_HOP_SEC)
        for i in range(len(decision_tracks))
    ])
    noise_floor = np.percentile(energies, 20, axis=1, keepdims=True)
    is_active = energies > noise_floor * SILENCE_MARGIN_RATIO

    volume_db = _to_db(energies)
    snr_db = _to_db(energies / (noise_floor + 1e-12))

    volume_norm = _minmax_normalize(volume_db, is_active)
    snr_norm = _minmax_normalize(snr_db, is_active)

    score = VOLUME_WEIGHT * volume_norm + SNR_WEIGHT * snr_norm
    return is_active, score


def _find_islands(any_active: np.ndarray, hop_sec: float, gap_sec: float) -> list:
    """把 any_active（任一軌活躍的影格）依 SEGMENT_GAP_SEC 分段邏輯切成發言段清單
    [(start_frame, end_frame), ...]，停頓短於 gap_sec 併入同一段，見 SEGMENT_GAP_SEC 說明。"""
    gap_frames = max(1, round(gap_sec / hop_sec))
    n = len(any_active)
    islands = []
    i = 0
    while i < n:
        if not any_active[i]:
            i += 1
            continue
        start = i
        last_active = i
        j = i + 1
        while j < n and (any_active[j] or j - last_active <= gap_frames):
            if any_active[j]:
                last_active = j
            j += 1
        islands.append((start, last_active + 1))
        i = j
    return islands


def _plan_track_selection(is_active: np.ndarray, score: np.ndarray, hop_sec: float,
                           segment_gap_sec: float, min_overlay_sec: float) -> tuple:
    """回傳 (master_selection, overlay_spans)。

    master_selection：每個影格的主軌 index（長度 n_frames），決定混音的「底」放哪一軌——
    以發言段（island）為單位鎖定，段內用整段加權分數加總決定主軌，避免逐影格切換造成的
    背景雜訊忽大忽小（沿用 SEGMENT_GAP_SEC 的分段邏輯）。

    overlay_spans：[(start_frame, end_frame, track_idx), ...]，發言段內某個非主軌片刻的
    分數超過主軌、且持續夠久（>= min_overlay_sec，排除短暫雜訊或洩漏波動）的區段，
    代表插話／回應，之後疊加（不取代）到主軌上。"""
    n_tracks, n_frames = score.shape
    any_active = is_active.any(axis=0)
    islands = _find_islands(any_active, hop_sec, segment_gap_sec)

    master_selection = np.empty(n_frames, dtype=int)
    overlay_spans = []
    min_overlay_frames = max(1, round(min_overlay_sec / hop_sec))

    current = int(np.argmax(score[:, 0])) if n_frames else 0
    prev_end = 0
    for start, end in islands:
        master_selection[prev_end:start] = current  # 發言段之間的靜音維持原本選的軌，不切換
        island_active = is_active[:, start:end]
        island_score = np.where(island_active, score[:, start:end], 0.0).sum(axis=1)
        master = int(np.argmax(island_score))
        master_selection[start:end] = master
        current = master

        # 每個影格在「活躍的軌」裡分數最高的是誰；master 本身活躍且分數最高時就是 master 自己，
        # 差一步就代表這一刻的插話/回應比主軌當下的收音更好。
        masked_score = np.where(island_active, score[:, start:end], -np.inf)
        frame_winner = np.argmax(masked_score, axis=0)
        frame_winner = np.where(island_active.any(axis=0), frame_winner, master)

        run_track, run_start = master, 0
        island_len = end - start
        for f in range(island_len + 1):
            track_here = frame_winner[f] if f < island_len else master
            if track_here == run_track:
                continue
            if run_track != master and f - run_start >= min_overlay_frames:
                overlay_spans.append((start + run_start, start + f, int(run_track)))
            run_track, run_start = track_here, f

        prev_end = end

    master_selection[prev_end:] = current
    return master_selection, overlay_spans


def _local_realign_samples(master: np.ndarray, secondary: np.ndarray, sr: int,
                            span_start: int) -> int:
    """疊加插話片段前的局部微調對齊：用插話片段前一小段「只有主軌在講話」的內容
    （這段內容多少會被從軌麥克風洩漏收到，只是比較小聲）重新比對局部延遲殘差，
    修正裝置間可能累積的時脈漂移。信心不足（洩漏太弱、比對不出明顯尖峰）就不修正，
    回傳 0，沿用既有的全域對齊結果。"""
    search = int(LOCAL_REALIGN_SEARCH_SEC * sr)
    context = int(LOCAL_REALIGN_CONTEXT_SEC * sr)
    ctx_start = max(0, span_start - context)
    ref = master[ctx_start:span_start]
    tgt = secondary[ctx_start:span_start]
    if len(ref) < search * 2 or len(tgt) < search * 2:
        return 0

    corr = correlate(ref, tgt, mode="full")
    mid = len(corr) // 2
    lo, hi = max(0, mid - search), min(len(corr), mid + search + 1)
    window = corr[lo:hi]
    if len(window) == 0:
        return 0

    local_best = int(np.argmax(window))
    peak = window[local_best]
    baseline = np.median(corr)
    spread = np.std(corr) + 1e-9
    confidence = float((peak - baseline) / spread)
    if confidence < CONFIDENCE_THRESHOLD:
        return 0
    return (lo + local_best) - mid


def mix_tracks(decision_wavs: list, output_wavs: list, output_wav: Path, track_names: list = None) -> Path:
    """動態選軌混音：以「一段發言」為單位鎖定主軌（硬切換＋交叉淡化，取代 ffmpeg amix 疊加
    造成的梳狀濾波空洞感），發言段內偵測其他軌插話／回應並疊加（不取代）進主軌
    （2026-08-17 決策：人聲重疊改為軟體處理，見 README「主從音軌與插話疊加」）。

    decision_wavs：去殘響後、增益前的訊號，只用來算音量／SNR 分數判斷主從，不直接輸出——
    dynamic_gain() 的目的就是抹平音量差異，拿增益後的訊號比較「誰原本比較清晰」會失真。
    output_wavs：完整處理過（增益＋降噪）的訊號，實際混音輸出用這份內容。
    兩者一一對應、時間軸完全相同（增益/降噪都不改變取樣點位置，只改振幅）。
    track_names：只用於印出診斷訊息時標示原始檔名，不影響混音結果，省略時用軌 index 代替。"""
    if len(decision_wavs) == 1:
        shutil.copy(output_wavs[0], output_wav)
        return output_wav

    names = track_names or [str(i) for i in range(len(decision_wavs))]

    decision_signals, output_signals = [], []
    sr = None
    for dw, ow in zip(decision_wavs, output_wavs):
        d, sr = sf.read(str(dw))
        o, _ = sf.read(str(ow))
        decision_signals.append(d)
        output_signals.append(o)

    max_len = max(len(s) for s in decision_signals)
    decision_tracks = np.zeros((len(decision_signals), max_len))
    output_tracks = np.zeros((len(output_signals), max_len))
    for i, (d, o) in enumerate(zip(decision_signals, output_signals)):
        decision_tracks[i, :len(d)] = d
        output_tracks[i, :len(o)] = o

    is_active, score = _compute_scores(decision_tracks, sr)
    master_selection, overlay_spans = _plan_track_selection(
        is_active, score, ENERGY_HOP_SEC, SEGMENT_GAP_SEC, MIN_OVERLAY_SEC,
    )

    if overlay_spans:
        print(f"=== 偵測到 {len(overlay_spans)} 段插話/回應，已疊加進主軌（不是取代）===")
        for s, e, tr in overlay_spans:
            start_sec = s * ENERGY_HOP_SEC
            dur_sec = (e - s) * ENERGY_HOP_SEC
            master_idx = master_selection[s]
            print(f"  {start_sec/60:6.1f} 分鐘處，持續 {dur_sec:4.1f} 秒："
                  f"主軌 {names[master_idx]} 疊加 {names[tr]} 的插話")
    else:
        print("=== 這場錄音沒有偵測到符合 MIN_OVERLAY_SEC 門檻的插話/回應 ===")

    hop_len = max(1, int(ENERGY_HOP_SEC * sr))
    crossfade_len = max(1, int(CROSSFADE_SEC * sr))

    switch_points = [0] + [
        i * hop_len for i in range(1, len(master_selection)) if master_selection[i] != master_selection[i - 1]
    ]
    switch_points.append(max_len)

    mixed = np.zeros(max_len)
    for seg_start, seg_end in zip(switch_points[:-1], switch_points[1:]):
        frame_idx = min(seg_start // hop_len, len(master_selection) - 1)
        track_idx = master_selection[frame_idx]
        mixed[seg_start:seg_end] = output_tracks[track_idx, seg_start:seg_end]

    for cut in switch_points[1:-1]:
        fade_start = max(0, cut - crossfade_len // 2)
        fade_end = min(max_len, cut + crossfade_len // 2)
        length = fade_end - fade_start
        if length <= 0:
            continue
        prev_idx = master_selection[min(fade_start // hop_len, len(master_selection) - 1)]
        next_idx = master_selection[min((fade_end - 1) // hop_len, len(master_selection) - 1)]
        fade = np.linspace(0.0, 1.0, length)
        mixed[fade_start:fade_end] = (
            output_tracks[prev_idx, fade_start:fade_end] * (1 - fade)
            + output_tracks[next_idx, fade_start:fade_end] * fade
        )

    for span_start_frame, span_end_frame, track_idx in overlay_spans:
        sample_start = span_start_frame * hop_len
        sample_end = min(span_end_frame * hop_len, max_len)
        if sample_end <= sample_start:
            continue
        master_idx = master_selection[span_start_frame]
        shift = _local_realign_samples(output_tracks[master_idx], output_tracks[track_idx], sr, sample_start)

        secondary_start = max(0, sample_start + shift)
        length = min(sample_end - sample_start, max_len - secondary_start)
        if length <= 0:
            continue
        secondary_clip = output_tracks[track_idx, secondary_start:secondary_start + length]
        master_clip = mixed[sample_start:sample_start + length]

        target_rms = np.sqrt(np.mean(master_clip.astype(np.float64) ** 2) + 1e-12)
        clip_rms = np.sqrt(np.mean(secondary_clip.astype(np.float64) ** 2) + 1e-12)
        balance_gain = min(target_rms / clip_rms, MAX_OVERLAY_GAIN) if clip_rms > 1e-9 else 0.0
        mixed[sample_start:sample_start + length] += secondary_clip * balance_gain

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

    return mix_tracks(dereverbed, cleaned, output_wav, track_names=[p.name for p in members])


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
