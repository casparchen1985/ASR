# App Dev Team 週會逐字稿自動化

把每週五 App Dev Team weekly meeting 的多軌錄音，自動處理成一份完整會議錄音檔＋草稿逐字稿，取代原本純人工聽打整理的流程。AI 輔助產出草稿，非保證品質的定稿，實際品質由團隊開放修訂機制把關。

完整背景、決策脈絡與尚未實作的部分，見 [`App_Dev_Team_逐字稿自動化計劃書.docx`](./App_Dev_Team_逐字稿自動化計劃書.docx)。本文件是給接手維護者／貢獻者看的技術說明。

## 目前狀態

- **Phase 1（已實作）**：多軌錄音自動對齊、混音、降噪、正規化，產出一份完整會議錄音檔；語音辨識（ASR）產出依語者分段的草稿逐字稿。
- **Phase 2（尚未實作）**：依 RD 報告內容切成個別檔案並具名命名（`yyyyMMdd_SerialNumber_RDName.*`）。
- **AI 校對**：不是獨立腳本呼叫 API——使用者僅有 Claude Team 帳號、無 Anthropic Console／API 計費權限，這一步改為在 Claude Code 對話中直接讀取草稿逐字稿與專有名詞對照表（`Keywords.txt`／`RulesAndRestricts.txt`）校對，僅傳輸文字，不涉及音檔。

## 核心原則

- **音檔全程不上雲**：語音辨識與音訊前處理都在本機／內部 VM 執行，開源 Whisper large-v3 模型（透過 `faster-whisper`），不使用 OpenAI 或其他雲端 ASR API。
- **不追求準確率數字**：逐字稿明確定位為 AI 輔助草稿，品質把關靠團隊開放修訂，不是某個 WER/CER 數字。
- **純 CPU 執行**：三台候選機器（見下）都沒有 NVIDIA GPU，`faster-whisper` 底層的 CTranslate2 只支援 CUDA 加速，純 CPU 不只是選擇，也是這三台機器的硬體限制。

## 流程（`scripts/asr_pipeline/phase1_pipeline.py`）

1. **掃描資料夾**：讀取指定週會資料夾內所有 `*.m4a`，排除已符合輸出檔名格式的舊產出，列出清單請執行者確認一次。
2. **對齊**：用音訊互相關（純 numpy／scipy 實作，不依賴 GPU）比對各軌與參考軌（最長一軌）的重疊內容——先低取樣率粗略定位，再原始取樣率局部精修，控制在毫秒級以下，避免混音時的梳狀濾波（回音／空洞感）。
3. **信心判斷與分群**：比對信心不足代表兩軌沒有真正重疊（例如裝置中途沒電、另一裝置接手），此時不強行對齊，改依檔名序號接續，並在畫面上提示接續發生的時間點；那段真正沒錄到的內容維持空白，不會被演算法生出來或悄悄隱藏。
4. **降噪與正規化**：對齊後才處理（不是對齊前），確保任何跨軌調整判斷都對應到正確時刻。目標鎖定抑制冷氣等穩定背景噪音，不追求處理所有雜訊類型。
5. **混音**：疊加已對齊、已處理的各軌，輸出 32kHz、192kbps AAC 的完整會議錄音檔。
6. **語者分段**：對混音結果做聲學特徵的語者變化偵測（只偵測換人講話，不做身份辨識）。
7. **ASR 轉錄**：對混音後的單一錄音跑一次 `faster-whisper large-v3`（CPU、int8 量化），依語者分段點分段落。Whisper 預設輸出簡體字，會自動用 OpenCC 轉繁體（含台灣慣用詞）。
8. **輸出草稿**：`{date}_AppDevWeeklyMeeting.m4a` ＋ `{date}_AppDevWeeklyMeeting.txt`，標頭明確標示「草稿，待確認」。

## 安裝與執行

跨平台自動偵測作業系統（macOS／Ubuntu／Windows 10），已在 macOS 上實際跑過驗證：

```bash
cd scripts/asr_pipeline
python3 setup.py       # macOS / Linux
# 或雙擊 run_setup.bat（Windows）／ run_setup.sh（macOS/Linux 也可用）
```

`setup.py` 會依偵測到的作業系統自動安裝 `ffmpeg`（macOS 用 Homebrew、Ubuntu 用 `apt-get`、Windows 用 `winget`），建立 `.venv`，安裝 `requirements.txt`，最後跑 `env_check.py` 驗證環境。**Ubuntu／Windows 上的路徑尚未實際測過**，邏輯上應該可行，遇到問題以實測結果為準。

跑主流程：

```bash
.venv/bin/python phase1_pipeline.py --dir <週會資料夾> --date <yyyyMMdd>
# Windows: .venv\Scripts\python.exe phase1_pipeline.py --dir <週會資料夾> --date <yyyyMMdd>
```

產出未校對的原始逐字稿後，把內容貼進 Claude Code，附上 `Keywords.txt`／`RulesAndRestricts.txt`，請它依規則校對（逐字不漏、不彙整、不美化，只修正錯字與專有名詞）。

## 已知限制

- **語者分段準確度未經真實會議錄音大量驗證**：只用一場真實會議測過，會議開頭閒聊/搶話的段落切得比較碎，屬於預期中的已知風險。
- **信心門檻（判斷兩軌是否重疊）只用真實的「確實重疊」案例校準過**，目前門檻 `CONFIDENCE_THRESHOLD = 10.0`（見 `align_mix.py`），還沒有真正的「裝置中途斷錄、完全不重疊」案例可驗證，遇到真實案例應回頭校準。
- **混音是單純疊加，不是動態選擇最佳音軌**：多軌同時收到同一人聲音時，即使對齊精準，效果仍不如依語者動態切換音軌的混音方式，只是目前已知的簡化版本。
- **標點符號半形/全形混用**：Whisper 輸出本身的習慣，未做額外正規化。
- **AI 校對步驟依賴人工把草稿貼進 Claude Code**，沒有寫成自動化腳本（見上述帳號權限限制）。

## 實測效能數據

2026 年 8 月在 2020 MacBook Pro（i5、16GB RAM，純 CPU）上，用一場真實會議錄音（74.9 分鐘、三軌，含歷史人工剪接片段）完整跑過一次：

| 階段 | 耗時 |
|---|---|
| 三軌對齊混音（32kHz） | 約 18～21 分鐘 |
| ASR 轉錄（large-v3, CPU int8） | 即時倍數約 2.25～2.57 倍 |
| 全流程總耗時 | 約 3 小時 |

這是目前唯一實測過的機器。候選環境還有 Ubuntu Server（i7-7700＋32GB）、Windows 10 筆電（i5-8250U＋32GB），尚待用同一套腳本實測比較，數字僅供這台機器參考。

## 檔案結構

```
scripts/
  build_plan_docx.js          # 產生計劃書 docx 的腳本
  asr_pipeline/
    setup.py                  # 跨平台環境設定（ffmpeg + venv + 套件 + 驗證）
    run_setup.bat / .sh        # setup.py 的雙擊啟動器
    env_check.py               # 環境檢查
    preprocess.py              # 音量正規化 + 降噪
    align_mix.py               # 多軌對齊、信心判斷、分群接續、混音
    diarize.py                 # 語者變化偵測（純 numpy/scipy，不依賴 torch/numba）
    transcribe.py               # faster-whisper 轉錄 + OpenCC 簡轉繁
    phase1_pipeline.py          # 主流程整合
    requirements.txt
```
