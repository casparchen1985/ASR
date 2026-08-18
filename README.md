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
5. **動態選軌混音（主從音軌＋插話疊加）**：不是單純疊加所有軌，而是以「一段發言」為單位鎖定一軌當主軌，硬切換＋短暫交叉淡化（`align_mix.py` 的 `mix_tracks()`），輸出 32kHz、192kbps AAC 的完整會議錄音檔。取代舊版 `amix` 疊加——疊加會讓同一聲源同時被多支麥克風收到、夾帶不同聲學延遲，聽起來像梳狀濾波的空洞感。停頓短於 `SEGMENT_GAP_SEC`（0.7 秒）視為同一段發言內部的換氣停頓，不切段，整段固定選同一軌，避免逐影格比能量時同一人講話過程中因瞬間能量波動在音軌間來回切換。細節見下方「主從音軌與插話疊加」。
6. **語者分段**：對混音結果做聲學特徵的語者變化偵測（只偵測換人講話，不做身份辨識）。
7. **ASR 轉錄**：對混音後的單一錄音跑一次 `faster-whisper large-v3`（CPU、int8 量化），依語者分段點分段落。Whisper 預設輸出簡體字，會自動用 OpenCC 轉繁體（含台灣慣用詞）。轉錄時會把 `Keywords.txt` 濃縮成一段簡短提示（`initial_prompt`，控制在 200 字元內、優先保留型號／Reader／認證類別詞彙），幫助模型認得團隊自己的產品型號與專有名詞——**這個提示的長度是刻意限制過的**，見下方「已知限制」。
8. **輸出草稿**：`{date}_Meeting.m4a` ＋ `{date}_Meeting.txt`，標頭附上 AI 轉錄逐字稿的免責聲明（未經校對、僅供參考）。要換其他命名規則，改 `phase1_pipeline.py` 的 `stem` 變數即可。

## 主從音軌與插話疊加

2026-08-17 決策：**人聲重疊改為軟體處理**，推翻原本「人聲重疊靠麥克風擺位／發言秩序預防、不透過軟體解決」的結論（該結論原本記在 `CLAUDE.md` 決策記錄，2026-08-14 重新評估殘響時還維持過一次）。背景是：動態選軌混音把「一段發言」鎖定在同一軌之後，如果會議桌前排主講人講話中途，後排與會者插話或回應，插話那幾秒仍然會固定播放主軌（因為主軌整段的累積分數還是比插話那幾秒的累積分數高），插話者收音比較清楚的那一軌反而完全被捨棄。改成：偵測到這種插話/回應，改用**疊加（不是切換）**的方式把插話內容補進主軌，兩人的內容都保留。

**主／從怎麼判斷**：不是固定哪一台裝置是主、哪一台是從——同一份錄音裡，主從角色每個發言段各自動態算一次，這一段誰講得多、收得清楚，這一段就是主軌；換一個人講比較久，主從就跟著換。判斷依據是加權分數：

- **比較基準用哪個階段的訊號**：`dereverb.py` 處理完（去殘響後）、`preprocess.py` 的 `dynamic_gain()` 處理前的訊號（`_build_cluster()` 裡的 `dereverbed`），不是最終輸出用的 `cleaned`。原因：`dynamic_gain()`（`dynaudnorm`）的工作目的就是把各時段音量拉到目標響度，會把音量差異本身抹平，拿增益後的訊號比較「誰原本比較大聲/清晰」會失真；去殘響則相反，是在移除房間反射造成的能量灌水失真，幫忙讓比較更準，不用跟著繞開。混音實際輸出的音訊內容仍然用完整處理過的 `cleaned`（增益＋降噪），只有「決策」這一步看 `dereverbed`。
- **分數組成**：音量（RMS 轉 dB）與 SNR（活躍影格能量 ÷ 該軌自己的雜訊底，轉 dB）各佔 50%，兩者先各自 min-max 正規化（正規化範圍要跨軌一起算，不能每軌各自正規化，否則會把軌間差異洗掉）再加權加總。原本還提案第三個指標「加工增益值」（`dynamic_gain()` 套用了多少 dB），評估後認為跟「增益前音量」高度相關（增益的作用本來就是拉平音量差異，兩者近似鏡像關係），會重複計分，所以沒有另外實作。
- **主軌鎖定**：沿用 `SEGMENT_GAP_SEC`（0.7 秒）分段邏輯，同一發言段內把各軌的加權分數加總，整段固定選分數最高的那一軌當主軌，避免逐影格切換造成的背景雜訊忽大忽小。
- **插話/回應偵測**：同一發言段內，某個非主軌片刻的分數超過主軌、且持續達到 `MIN_OVERLAY_SEC`（0.3 秒）以上（排除短暫雜訊或麥克風洩漏音造成的誤判），判定為插話/回應。
- **疊加方式**：把該非主軌片段疊加到主軌上——疊加前先用主軌／從軌各自在插話片段前一小段的內容做局部微調對齊（`_local_realign_samples()`，搜尋範圍 `LOCAL_REALIGN_SEARCH_SEC` = ±0.05 秒），修正裝置間可能累積的時脈漂移；再依主軌片段的音量做增益平衡（上限 `MAX_OVERLAY_GAIN` = 3 倍），避免疊加片段忽大忽小。

**已知的技術代價（老實講）**：疊加終究是把兩個不同麥克風收到的同一批聲源加在一起，跟舊版 `amix` 疊加被淘汰的原因是同一類問題——主軌的麥克風多少也會洩漏收到插話者的聲音（比較小聲），從軌的麥克風也會洩漏收到主講人的聲音，疊加會讓這些洩漏聲部分重複、帶有不同延遲，理論上還是有機會產生輕微的梳狀濾波（空洞感），只是規模縮小到插話那幾秒、且洩漏音量通常遠小於直接收音，嚴重程度目前沒有拿真實錄音聽感驗證過。

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

- **`SEGMENT_GAP_SEC`（判斷「這段發言結束了」的停頓長度，目前 0.7 秒，見 `align_mix.py`）尚未用真實會議聽感校準**：太短會退回逐影格切換的問題（同一人講話中途因換氣被切到別軌雜訊）；太長則可能把兩個人快速接話的段落誤判成同一段發言、整段鎖到其中一人的軌，需要實際聽過真實會議錄音後調整。
- **主從音軌與插話疊加的四組閾值（`VOLUME_WEIGHT`/`SNR_WEIGHT` = 0.5/0.5、`MIN_OVERLAY_SEC` = 0.3 秒、`LOCAL_REALIGN_SEARCH_SEC` = ±0.05 秒、`MAX_OVERLAY_GAIN` = 3 倍，皆見 `align_mix.py`）全部是初始值，尚未用真實會議聽感校準**：權重 50/50 沒有實測依據，只是「沒有明顯理由偏向哪一個」的起始猜測；`MIN_OVERLAY_SEC` 太短會把雜訊/洩漏誤判成插話疊加、太長會漏掉真正短促的插話（例如「對」「嗯」這類簡短回應）；`LOCAL_REALIGN_SEARCH_SEC` 只設 ±0.05 秒，如果裝置間實際時脈漂移超過這個範圍（長時間錄音、廉價裝置時脈較不準時可能發生），局部微調會找不到信心足夠的峰值、直接放棄修正、沿用全域對齊結果，殘餘誤差可能超過原本設計要壓低到的 2ms 目標。另外，疊加終究是把兩支麥克風收到的同一批聲源加在一起，理論上還是有機會產生輕微梳狀濾波（空洞感），只是規模縮小到插話那幾秒，嚴重程度沒有拿真實錄音聽感驗證過，細節見上方「主從音軌與插話疊加」。
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
    align_mix.py               # 多軌對齊、信心判斷、分群接續、動態選軌混音（主從音軌判斷＋插話疊加）
    diarize.py                 # 語者變化偵測（純 numpy/scipy，不依賴 torch/numba）
    transcribe.py               # faster-whisper 轉錄 + OpenCC 簡轉繁 + Keywords.txt initial_prompt
    phase1_pipeline.py          # 主流程整合（支援 --skip-align／--skip-asr）
    requirements.txt
```
