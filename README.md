# 多軌會議錄音逐字稿自動化

把多軌會議錄音，自動處理成一份完整會議錄音檔＋草稿逐字稿，取代純人工聽打整理的流程。AI 輔助產出草稿，非保證品質的定稿，實際品質由團隊開放修訂機制把關。

本文件（README）是給接手維護者／貢獻者看的技術說明，聚焦於通用的管線設計，不綁定特定團隊或會議類型。

## 目前狀態

- **Phase 1（已實作）**：多軌錄音自動對齊、混音、降噪、正規化，產出一份完整會議錄音檔；語音辨識（ASR）產出依語者分段的草稿逐字稿。
- **Phase 2（尚未實作，目前為特定部署情境的規劃）**：依內容切成個別檔案並具名命名，命名規則依使用情境而定（例如某次導入案例採用 `yyyyMMdd_SerialNumber_RDName.*`）。
- **AI 校對**：不是獨立腳本呼叫 API——使用者僅有 Claude Team 帳號、無 Anthropic Console／API 計費權限，這一步改為在 Claude Code 對話中直接讀取草稿逐字稿與專有名詞對照表（`Keywords.txt`／`RulesAndRestricts.txt`）校對，僅傳輸文字，不涉及音檔。

## 核心原則

- **音檔全程不上雲**：語音辨識與音訊前處理都在本機／內部 VM 執行，開源 Whisper large-v3 模型（透過 `faster-whisper`），不使用 OpenAI 或其他雲端 ASR API。
- **不追求準確率數字**：逐字稿明確定位為 AI 輔助草稿，品質把關靠團隊開放修訂，不是某個 WER/CER 數字。
- **純 CPU 執行**：三台候選機器（見下）都沒有 NVIDIA GPU，`faster-whisper` 底層的 CTranslate2 只支援 CUDA 加速，純 CPU 不只是選擇，也是這三台機器的硬體限制。

## 流程（`scripts/asr_pipeline/phase1_pipeline.py`）

1. **掃描資料夾**：讀取指定會議資料夾內所有 `*.m4a`，排除已符合輸出檔名格式的舊產出，列出清單請執行者確認一次。
2. **對齊**：用音訊互相關（純 numpy／scipy 實作，不依賴 GPU）比對各軌與參考軌（最長一軌）的重疊內容——先低取樣率粗略定位，再原始取樣率局部精修，控制在毫秒級以下，避免混音時的梳狀濾波（回音／空洞感）。
3. **信心判斷與分群**：比對信心不足代表兩軌沒有真正重疊（例如裝置中途沒電、另一裝置接手），此時不強行對齊，改依檔名序號接續，並在畫面上提示接續發生的時間點；那段真正沒錄到的內容維持空白，不會被演算法生出來或悄悄隱藏。
4. **去殘響、動態增益、降噪**：對齊後才處理（不是對齊前），確保任何跨軌調整判斷都對應到正確時刻。依序：
   - **多軌聯合去殘響**（`dereverb.py`，`nara_wpe` 的 WPE 演算法）：把同一群組已對齊的各軌一次餵給 WPE，用跨軌空間資訊估計房間脈衝響應，處理麥克風離講者較遠時聽起來空洞、殘響重的問題；長錄音採分段處理控制記憶體。刻意排在動態增益之前，避免非線性增益調整打亂 WPE 依賴的線性關係。
   - **每軌動態增益**（`preprocess.py` 的 `dynamic_gain()`，ffmpeg `dynaudnorm`）：逐時段調整音量，取代舊版對整條軌套用單一線性增益的做法，避免遠距離時段被整條軌的平均響度拖累、連噪音底一起放大。
   - **冷氣等穩定背景噪音降噪**（`preprocess.py` 的 `reduce_ac_noise()`，`noisereduce`）：目標鎖定抑制冷氣等穩定背景噪音，不追求處理所有雜訊類型。
5. **動態選軌混音**：不是單純疊加所有軌，而是依各軌短時能量包絡，每個時刻挑目前最乾淨的一軌，硬切換＋短暫交叉淡化（`align_mix.py` 的 `mix_tracks()`），輸出 32kHz、192kbps AAC 的完整會議錄音檔。取代舊版 `amix` 疊加——疊加會讓同一聲源同時被多支麥克風收到、夾帶不同聲學延遲，聽起來像梳狀濾波的空洞感。
6. **語者分段**：對混音結果做聲學特徵的語者變化偵測（只偵測換人講話，不做身份辨識）。
7. **ASR 轉錄**：對混音後的單一錄音跑一次 `faster-whisper large-v3`（CPU、int8 量化），依語者分段點分段落。Whisper 預設輸出簡體字，會自動用 OpenCC 轉繁體（含台灣慣用詞）。轉錄時會把 `Keywords.txt` 濃縮成一段簡短提示（`initial_prompt`，控制在 200 字元內、優先保留型號／Reader／認證類別詞彙），幫助模型認得團隊自己的產品型號與專有名詞——**這個提示的長度是刻意限制過的**，見下方「已知限制」。
8. **輸出草稿**：`{date}_Meeting.m4a` ＋ `{date}_Meeting.txt`，標頭附上 AI 轉錄逐字稿的免責聲明（未經校對、僅供參考）。要換其他命名規則，改 `phase1_pipeline.py` 的 `stem` 變數即可。

## 安裝與執行

跨平台自動偵測作業系統（macOS／Ubuntu／Windows 10）。驗證程度依平台不同：

- **macOS**（2020 MacBook Pro，i5＋16GB）：完整跑過對齊混音＋語者分段＋ASR 轉錄全流程，**目前正式週會主要在這台機器上執行**。
- **Windows 10**（Dell Latitude 3490，i5-8250U＋32GB）：完整跑過對齊混音＋語者分段＋ASR 轉錄全流程，正式週會少量執行過。
- **Ubuntu Server**（i7、Python 3.8）：只驗證過對齊混音（`setup.py` 安裝環境＋產出 `*.m4a`），**還沒跑過 ASR 轉錄那段**，目前是備用機器，還沒實際拿來跑過正式週會。

```bash
cd scripts/asr_pipeline
python3 setup.py       # macOS / Linux
# 或雙擊 run_setup.bat（Windows）／ run_setup.sh（macOS/Linux 也可用）
```

`setup.py` 會依偵測到的作業系統自動安裝 `ffmpeg`（macOS 用 Homebrew、Ubuntu 用 `apt-get`、Windows 用 `winget`），建立 `.venv`，安裝 `requirements.txt`，最後跑 `env_check.py` 驗證環境。在 Ubuntu（Python 3.8）上實測時修過幾個環境相容性問題：`python3-venv` 系統套件缺失、venv 建立到一半失敗留下殘缺環境、`tokenizers` 新版沒有 Python 3.8 wheel 需要編譯。在 Windows 10 上實測時也修過兩個問題：`pip.exe` 執行中不能覆寫自己導致升級失敗（改用 `python -m pip`）、`get_duration_seconds()` 原本對整條 ffmpeg 路徑做字串取代找 ffprobe，遇到安裝路徑本身含 `ffmpeg` 子字串（例如 winget 裝的 `ffmpeg-9.0-full_build` 資料夾）會取代到路徑本身、找到不存在的檔案（改成只取代檔名的 `_ffprobe()`）。這些都已經修進 `setup.py`／`align_mix.py`／`requirements.txt`，見 git log。

**注意：一定要用 `.venv` 裡的 Python 執行，不要用裸的 `python3`／`python`。** 套件都裝在 `.venv` 裡，不是系統全域，用系統原生 `python3` 跑任何腳本（`env_check.py`、`align_mix.py`、`diarize.py`、`transcribe.py`、`preprocess.py`、`setup.py`、`phase1_pipeline.py` ……全部都算）都會出現「NOT INSTALLED」／`ModuleNotFoundError`，這不是安裝失敗，是沒有指到 venv。兩種正確用法：

```bash
# 方式一：直接指定 venv 的 python（每次都要打完整路徑，較保險）
.venv/bin/python3 env_check.py
.venv/bin/python3 phase1_pipeline.py --dir <會議資料夾> --date <yyyyMMdd>

# 方式二：先 activate，這個 shell session 裡的 python3 就會指向 venv
source .venv/bin/activate
python3 env_check.py
python3 phase1_pipeline.py --dir <會議資料夾> --date <yyyyMMdd>
```

Windows 對應：`.venv\Scripts\python.exe env_check.py`、`.venv\Scripts\python.exe phase1_pipeline.py ...`。

**方式三（推薦）：專案根目錄（ASR/）的 `run.sh`／`run.bat`**，內定直接執行 `phase1_pipeline.py`，不用先 `cd` 進 `scripts/asr_pipeline`、不用記 `.venv` 路徑、也不用打 `phase1_pipeline.py` 的路徑，參數直接照 `phase1_pipeline.py` 原本的用法打：

```bash
# macOS/Linux，從 ASR 根目錄執行
./run.sh --dir <會議資料夾> --date <yyyyMMdd>
```

```bat
:: Windows cmd，從 ASR 根目錄執行
run.bat --dir <會議資料夾> --date <yyyyMMdd>
```

如果要跑 `phase1_pipeline.py` 以外的腳本（例如 `env_check.py`），用方式一／方式二，`run.sh`／`run.bat` 只固定對應 `phase1_pipeline.py`。

產出未校對的原始逐字稿後，把內容貼進 Claude Code，附上 `Keywords.txt`／`RulesAndRestricts.txt`，請它依規則校對（逐字不漏、不彙整、不美化，只修正錯字與專有名詞）。

若只是要重跑分段偵測／ASR 轉錄（例如 `Keywords.txt` 更新、`transcribe.py` 改了轉錄邏輯），不需要每次都重新對齊混音——**全流程真正最花時間的其實是 ASR 轉錄＋語者分段（見下方「實測效能數據」，合計 3～4 小時，遠比對齊混音的數十分鐘久）**，但對齊混音（尤其新增去殘響後）本身仍要數十分鐘以上，重跑沒有意義的話能省則省，可以加 `--skip-align` 沿用已存在的 `{date}_Meeting.m4a`：

```bash
.venv/bin/python3 phase1_pipeline.py --dir <會議資料夾> --date <yyyyMMdd> --skip-align
```

## 已知限制

- **`CONFIDENCE_THRESHOLD`（判斷兩軌是否重疊，目前 10.0，見 `align_mix.py`）只用「兩軌確實重疊」的案例校準過**：截至目前，正式週會使用中尚未發生過「裝置中途斷錄、與其他軌完全無重疊」的情況，這個分支還沒有實際案例驗證過，遇到時應回頭檢視門檻是否需要調整。
- **語者分段準確度**：舊版（單純疊加混音）搭配現有 MFCC 分段演算法，正式週會（主要在 MacBook Pro）使用幾週下來準確度約九成。新版動態選軌混音上線後，餵給分段演算法的音訊特性改變（不再是多軌疊加），這個準確度數字還沒有用新版重新驗證。
- **標點符號半形/全形混用**：Whisper 輸出本身的習慣，未做額外正規化。
- **多軌聯合 WPE 去殘響讓對齊混音階段耗時明顯增加**：2026-08-14 App Dev Team weekly（三軌、最長 89.6 分鐘）在 2020 MacBook Pro 上實測，對齊＋去殘響＋動態增益＋降噪＋動態選軌混音全部合計約 80 分鐘，是舊版單純疊加混音（同一台機器約 18～21 分鐘）的 4 倍左右，詳見下方「實測效能數據」。目前還沒有做人工聽感比對（第二排講者的空洞感/雜訊是否真的改善、切換點有無明顯切換聲），也還沒有 Ubuntu／Windows 的新版耗時數據。
- **新增依賴 `nara-wpe` 在 Ubuntu（Python 3.8）尚未驗證安裝**：其依賴的 `bottleneck` 套件在 macOS 上是從原始碼編譯（需要 C 編譯器），Ubuntu／Windows 是否有現成 wheel 或需要額外安裝編譯工具鏈還沒實測，可能重演過去 `tokenizers` 的 wheel 相容性問題。
- **AI 校對步驟依賴人工把草稿貼進 Claude Code**，沒有寫成自動化腳本（見上述帳號權限限制）。
- **`initial_prompt` 的長度會直接影響轉錄品質，不是「詞彙越多越好」**：實測驗證過（2026-08，Windows 10，A/B 對照同一段音檔）——把 `Keywords.txt` 全部詞彙（140+ 個、1021 字元）串成一長串、沒有語句結構的字串直接餵給 Whisper 的 `initial_prompt`，會讓轉錄**開頭一段**變成跟音檔內容完全無關的幻覺文字（例如亂碼符號、捏造出來的假型號代碼），拿掉提示後開頭立刻恢復正常。目前 `load_keyword_hint()`（`transcribe.py`）把提示包成自然語句、優先保留型號／Reader／認證類別詞彙、控制在 200 字元內，同一段測試音檔不再重現這個問題，但**這個 200 字元的門檻本身只驗證過「不會幻覺」，沒有驗證過「多長最有幫助」**，如果之後 `Keywords.txt` 持續變長，這個上限可能需要重新校準——A/B 測試成本較高（需要同一段音檔跑多種提示長度比對），目前沒有排這項重測。

## 實測效能數據

**注意：ASR 轉錄的數據是舊版流程量到的**，新版對齊混音（含去殘響、動態選軌）目前只有 macOS 上的新數據，Ubuntu／Windows 還沒有補測。

同一場真實會議錄音（2026-08-07 App Dev Team weekly，74.9 分鐘、三軌／9 個原始檔案，含裝置分段錄製）分別在兩台機器上完整跑過全流程：

**2020 MacBook Pro（i5、16GB RAM，純 CPU）：**

| 階段 | 耗時 |
|---|---|
| 三軌對齊混音（32kHz，舊版，單純疊加、無去殘響） | 約 18～21 分鐘 |
| 三軌對齊混音（32kHz，新版，含去殘響＋動態增益＋降噪＋動態選軌混音，另一場會議 89.6 分鐘實測） | 約 80 分鐘 |
| ASR 轉錄（large-v3, CPU int8，舊版流程量測） | 即時倍數約 2.25～2.57 倍 |
| 全流程總耗時（舊版） | 約 3 小時 |

**Windows 10 筆電（Dell Latitude 3490，i5-8250U，4 核 8 緒＋32GB RAM）：**

| 階段 | 耗時 |
|---|---|
| 對齊混音（9 個原始檔案，全部成功對齊，未落入接續 fallback） | 約 38～40 分鐘 |
| 語者分段＋ASR 轉錄（large-v3, CPU int8） | 約 3 小時 10～20 分（即時倍數約 2.6～2.7 倍） |
| 全流程總耗時 | 約 4 小時 |

i5-8250U 是 15W 低壓行動處理器，即時倍數比 MacBook Pro 版本略慢一些符合預期。Ubuntu Server（i7-7700＋32GB）目前只驗證過對齊混音，還沒有 ASR 轉錄的實測時間可以放進這個表。

## 檔案結構

```
Keywords.txt                  # 團隊維護的專有名詞／型號／人名對照表，AI 校對與 ASR initial_prompt 都會讀
RulesAndRestricts.txt         # AI 校對的規則與限制（逐字不漏、不彙整、不美化；語音片段僅供聲紋判斷不可引用談話內容）
run.sh / run.bat              # 專案根目錄快速入口，轉呼叫 scripts/asr_pipeline/.venv 的 python，不用先 cd 進子資料夾
scripts/
  build_plan_docx.js          # 產生計劃書 docx 的腳本
  asr_pipeline/
    setup.py                  # 跨平台環境設定（ffmpeg + venv + 套件 + 驗證）
    run_setup.bat / .sh        # setup.py 的雙擊啟動器
    env_check.py               # 環境檢查
    preprocess.py              # 每軌動態增益 + 冷氣噪音降噪
    dereverb.py                 # 多軌聯合去殘響（nara_wpe / WPE）
    align_mix.py               # 多軌對齊、信心判斷、分群接續、動態選軌混音
    diarize.py                 # 語者變化偵測（純 numpy/scipy，不依賴 torch/numba）
    transcribe.py               # faster-whisper 轉錄 + OpenCC 簡轉繁 + Keywords.txt initial_prompt
    phase1_pipeline.py          # 主流程整合（支援 --skip-align／--skip-asr）
    requirements.txt
```
