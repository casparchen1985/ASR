const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, AlignmentType, LevelFormat, TableOfContents,
  PageBreak, convertInchesToTwip
} = require("docx");

const NAVY = "1F3864";
const ACCENT = "2E74B5";
const LIGHT = "DCE6F1";
const GREY = "595959";

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 160 },
    children: [new TextRun({ text, bold: true, color: NAVY, size: 30 })],
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 260, after: 120 },
    children: [new TextRun({ text, bold: true, color: ACCENT, size: 24 })],
  });
}
function body(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 160, line: 300 },
    children: [new TextRun({ text, size: 22, color: "262626", ...opts })],
  });
}
function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullet-list", level },
    spacing: { after: 80, line: 280 },
    children: [new TextRun({ text, size: 22, color: "262626" })],
  });
}
function numbered(text, ref, level = 0) {
  return new Paragraph({
    numbering: { reference: ref, level },
    spacing: { after: 80, line: 280 },
    children: [new TextRun({ text, size: 22, color: "262626" })],
  });
}
function cell(text, opts = {}) {
  const { header = false, width, shade } = opts;
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: shade ? { type: ShadingType.CLEAR, fill: shade } : undefined,
    margins: { top: 100, bottom: 100, left: 120, right: 120 },
    children: [
      new Paragraph({
        children: [
          new TextRun({
            text,
            bold: header,
            size: 21,
            color: header ? "FFFFFF" : "262626",
          }),
        ],
      }),
    ],
  });
}
function hr() {
  return new Paragraph({
    spacing: { after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "BFBFBF" } },
    children: [],
  });
}

// ---- Table builders ----
function makeTable(headerRow, rows, widths) {
  return new Table({
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({
        tableHeader: true,
        children: headerRow.map((t, i) => cell(t, { header: true, width: widths[i], shade: NAVY })),
      }),
      ...rows.map(
        (r, idx) =>
          new TableRow({
            children: r.map((t, i) => cell(t, { width: widths[i], shade: idx % 2 === 1 ? LIGHT : undefined })),
          })
      ),
    ],
  });
}

const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullet-list",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 240 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 840, hanging: 240 } } } },
        ],
      },
      {
        reference: "num-list-main",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 240 } } } },
        ],
      },
      {
        reference: "num-list-multitrack",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 240 } } } },
        ],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 11906, height: 16838 }, // A4
          margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 },
        },
      },
      headers: {},
      children: [
        // ---------- COVER ----------
        new Paragraph({ spacing: { before: 2000 }, children: [] }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "App Dev Team", bold: true, size: 26, color: GREY })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 200 },
          children: [new TextRun({ text: "週會繁體中文逐字稿自動化計劃書", bold: true, size: 52, color: NAVY })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { before: 100, after: 1600 },
          children: [new TextRun({ text: "AI 輔助草稿 ・ 本機處理不上雲 ・ 開放修訂機制", size: 24, color: ACCENT })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 },
          children: [new TextRun({ text: "版本 v1.0", size: 22, color: GREY })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 },
          children: [new TextRun({ text: "日期：2026 年 8 月 9 日", size: 22, color: GREY })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "提出單位：App Dev Team", size: 22, color: GREY })],
        }),
        new Paragraph({ children: [new PageBreak()] }),

        // ---------- 目錄 ----------
        h1("目錄"),
        new TableOfContents("目錄", { hyperlink: true, headingStyleRange: "1-2" }),
        new Paragraph({ children: [new PageBreak()] }),

        // ---------- 一、專案背景與目的 ----------
        h1("一、專案背景與目的"),
        h2("1.1 背景"),
        body(
          "App Dev Team 每週五固定召開 weekly meeting，目前會議紀錄仰賴人工紀錄或事後回憶整理，容易遺漏決議細節、技術名詞與行動項目歸屬，也難以讓臨時缺席的同事快速掌握完整討論脈絡。"
        ),
        h2("1.2 目的"),
        bullet("為每週會議建立一套穩定可重複的流程，用 AI 輔助產出逐字稿草稿，取代目前從頭聽打的人工方式，降低整理會議紀錄的負擔。"),
        bullet("逐字稿定位為「方便閱讀、方便查找的草稿」，廣發後開放全員訂正，作為輔助工具而非取代人工確認的最終依據。"),
        bullet("將逐字稿延伸整理成會議摘要與行動項目清單，降低會後整理的人力成本。"),
        bullet("建立標準化存檔與分享機制，讓缺席同事與新進成員都能快速回溯歷史討論。"),
        bullet("流程需可持續每週重複使用，並隨著使用逐步減少人工介入的比重。"),

        // ---------- 二、現況與挑戰 ----------
        h1("二、現況與挑戰"),
        body("目前會議為實體會議，僅能取得音檔（無錄影），且團隊討論內容中英夾雜技術詞彙頻繁，對逐字稿的可讀性與可用性帶來以下挑戰："),
        makeTable(
          ["挑戰", "說明", "影響"],
          [
            ["收音品質不穩定", "實體會議受場地迴音、多人交談、距離收音影響", "語音辨識容易出現誤判，草稿需要較多人工修正"],
            ["中英夾雜詞彙多", "API、sprint、bug、產品代號等技術詞彙頻繁出現", "語音辨識引擎容易誤判或音譯錯誤"],
            ["缺乏標準流程", "目前無固定錄音、轉檔、校對步驟", "品質與效率因人而異，難以規模化"],
            ["人工校對耗時", "純人工逐字聽打校對曠日費時", "難以在會議後短時間內產出可用逐字稿"],
            ["人聲重疊與會議室回音", "多人搶話、發言重疊，或空間迴響造成聲音模糊", "降噪演算法對此類雜訊效果有限，屬於收音當下即難以事後修正的限制"],
          ],
          [2600, 4200, 2600]
        ),

        // ---------- 三、目標與成功指標 ----------
        h1("三、目標與成功指標"),
        body(
          "本計劃不設定準確率作為成功指標。逐字稿定位為 AI 輔助產出的草稿，實際品質由團隊開放修訂機制把關，而非追求機器單方面達到某個數字。以下指標聚焦在流程本身是否可行、可重複、對團隊是實際的負擔減輕。"
        ),
        makeTable(
          ["指標", "目標值", "衡量方式"],
          [
            ["草稿產出時效", "由於會議固定在週五，目標為下週一上班前產出草稿並廣發，避免與夜間批次處理、週末非工作日的排程衝突", "記錄每週流程實際完成時間，對照目標時效檢視落差"],
            ["定稿完成時效", "無強制時限，依團隊開放修訂進度為準", "記錄每週定稿實際完成時間，供後續調整參考"],
            ["流程穩定性", "連續 4 週流程可順利執行，不需人工從頭重新聽打", "每週執行紀錄追蹤表"],
            ["人工投入時間", "初期（第 1–4 週）每次 3–5 小時，隨對照表與流程成熟逐步下降", "記錄流程執行、校對、抽查之實際總耗時"],
          ],
          [2800, 3400, 3200]
        ),
        body(
          "人工投入時間刻意不設過度樂觀的初期目標：流程建立階段（含執行腳本、檢視結果、校對、更新對照表）預期需要 3–5 小時，待對照表成熟、流程穩定後才會逐步縮短，計劃書不以「15 分鐘」這類不切實際的數字自我設限。",
          { italics: true, color: GREY, size: 20 }
        ),

        // ---------- 四、整體流程設計 ----------
        h1("四、整體流程設計"),
        body("整體流程分為九個步驟，前五步為前置、前處理與轉錄，中段為校對與初步產出，最後兩步為開放修訂與定稿，形成「機器初稿 → AI 校對 → 人工把關 → 團隊訂正」的分層把關方式，逐步降低人工需要從頭處理的份量。逐字稿在步驟 8 產出的是草稿，並非最終不可更動的紀錄，實際品質仰賴步驟 9 的團隊開放修訂。"),
        h2("4.1 流程步驟"),
        numbered("錄音品質把關：會議桌中央放置手機或使用外接全向麥克風／會議錄音筆，錄音開始先測試 30 秒確認收音清楚。", "num-list-main"),
        numbered("音檔轉存整理：統一轉成 m4a 格式，以固定規則命名（例如 2026-08-14_AppDevWeekly.m4a），並存入指定內部資料夾。", "num-list-main"),
        numbered("音訊前處理：自動套用音量正規化（loudness normalization）統一各音檔響度，並執行輕度降噪，重點抑制冷氣等穩定背景噪音，改善後續辨識效果。", "num-list-main"),
        numbered("ASR 初稿轉錄：使用開源 Whisper large-v3 模型（透過 faster-whisper 於本機或公司內部主機／VM 執行），產生繁體中文逐字稿初稿，音檔全程不上傳雲端。", "num-list-main"),
        numbered("專有名詞比對：套用團隊維護的專有名詞對照表，修正技術詞彙、產品名稱、人名的辨識錯誤；多機錄音時於此步驟同步進行多軌交叉比對。", "num-list-main"),
        numbered("AI 二次校對：交由 Claude 依對照表校正錯字、修正標點斷句、統一講者標示，讓草稿更接近可直接閱讀的狀態。", "num-list-main"),
        numbered("人工快速抽查：針對數字、決議事項等關鍵段落，以及多軌比對中標記的分歧段落人工複核，作為草稿發出前的基本把關。", "num-list-main"),
        numbered("草稿產出與分發：將草稿逐字稿與初版會議摘要、行動項目清單，於下週一上班前存入指定資料夾／知識庫並廣發給團隊，同時開放全員針對草稿提出修改或訂正。", "num-list-main"),
        numbered("彙整修訂形成定稿：收集團隊回饋的修正意見，統一彙整後更新為定稿，並將新出現的專有名詞回饋更新至對照表，供下週使用。", "num-list-main"),

        h2("4.2 流程示意"),
        body("錄音 → 轉檔整理 → 音訊前處理 → ASR 初稿 → 專有名詞／多軌比對 → AI 校對 → 人工抽查 → 草稿產出分發 → 開放修訂彙整定稿", { italics: true, color: GREY }),

        h2("4.3 音訊前處理說明"),
        body(
          "音量正規化納入流程並非未經驗證的假設：團隊已手動調整音量增益進行約 3 週的實測，觀察到對辨識效果有明顯幫助，此步驟即是把這個已驗證有效的手動調整自動化、標準化，避免每週依賴人工憑經驗調整。降噪則鎖定明確且單一的目標——會議室冷氣的穩定背景噪音，不追求處理所有類型雜訊。"
        ),
        makeTable(
          ["處理項目", "說明", "建議工具"],
          [
            ["音量正規化", "依 EBU R128 標準將各音檔自動校正到統一響度目標（如 -16 LUFS），將先前人工驗證有效的音量調整自動化", "ffmpeg（loudnorm 濾鏡）"],
            ["降噪（鎖定冷氣噪音）", "目標為抑制會議室冷氣等穩定低頻背景噪音，強度以「明顯降低冷氣聲、不影響人聲清晰度」為準，不追求消除所有雜訊", "noisereduce（頻譜門控）／RNNoise"],
          ],
          [2600, 4200, 2600]
        ),
        body(
          "降噪並非處理越強越好，過度降噪反而會讓 ASR 誤判增加；此步驟以「抑制冷氣噪音＋音量正規化」為明確範圍，其餘噪音仍優先靠錄音當下的麥克風位置與環境選擇解決。",
          { italics: true, color: GREY, size: 20 }
        ),

        // ---------- 五、多機音軌自動整合方案 ----------
        h1("五、多機音軌自動整合方案（進階選配）"),
        body(
          "實體會議收音品質不易掌握，建議視現場座位與人數，同時以 2–4 台裝置（例如手機、MBP、外接錄音筆等組合）各自獨立錄音，形成多音軌。各軌可互為備援，也可用於交叉比對，輔助人工更快找出可能有問題的段落，且整個整合過程不需要人工手動對時或剪接，裝置數量增加時流程邏輯不需改變，僅是比對的音軌數量從 2 軌擴充為 N 軌。"
        ),
        h2("5.1 為什麼用多機錄音"),
        bullet("備援：任一裝置沒電、存滿或忘記錄音時，仍有其他裝置的錄音可用。"),
        bullet("互補：各裝置與講者的距離不同，同一時刻通常有一至兩軌收音較清楚，可截長補短。"),
        bullet("輔助抓錯：搭配專有名詞交叉比對，當多軌辨識結果不一致時自動標記出來，縮小人工需要逐字核對的範圍，而不是要求人工從頭聽過整份逐字稿。"),
        h2("5.2 自動化整合流程（2026-08 實作後更新）"),
        body(
          "本節原設計為「各軌分別轉錄、逐字比對多數決」，實際動手實作後改為「先對齊混音成一份完整錄音、再轉錄一次」，原因是實測拿到的真實裝置錄音，多數是同一場會議的完整重複錄音（例如兩支手機皆從頭錄到尾），而非設計上假設的逐字獨立比對素材；先合併再轉錄一次，可避免運算成本隨裝置數等比疊加。以下流程為實際實作版本，取代原本 5.2 的描述。",
          { italics: true, color: GREY, size: 20 }
        ),
        numbered("自動歸組：程式讀取指定資料夾內所有原始音軌，排除已符合輸出檔名格式的檔案，執行前列出清單請執行者確認一次，避免誤把舊檔或不相關檔案當成本次原始軌。", "num-list-multitrack"),
        numbered("自動時間對齊與信心判斷：以音訊互相關（純 numpy／scipy 實作，不依賴 GPU）比對各軌與參考軌（挑最長一軌）的重疊內容，先用低取樣率粗略定位，再於命中位置附近用原始取樣率局部精修，將對齊精度控制在毫秒級以下。同時檢查比對信心值：信心不足代表兩軌並未真正重疊（例如某裝置錄到一半沒電、由另一裝置接手），此時改採依檔名序號接續，不強行對齊，並在執行畫面上明確提示發生接續的時間點。", "num-list-multitrack"),
        numbered("對齊後才進行降噪與音量正規化：確保任何跨軌比較或增益調整，都建立在「已知道哪個時刻該對應哪幾軌」的基礎上，而非對還沒對齊的音檔各自處理。", "num-list-multitrack"),
        numbered("混音合併：把已對齊、已處理的各軌疊加混成一份完整錄音，再做整體音量正規化，輸出為 32kHz、192kbps AAC，作為會議完整錄音成品，取代原本 4.2 節單軌流程直接使用的原始錄音檔。", "num-list-multitrack"),
        numbered("依聲學特徵切分語者段落：對混音後的錄音偵測語者變化時間點（僅偵測換人講話，不做身份辨識），作為逐字稿分段依據。", "num-list-multitrack"),
        numbered("單軌轉錄：對混音後的單一錄音跑一次 Whisper large-v3，依語者分段點分段落，不需要每一軌各自轉錄一次。", "num-list-multitrack"),
        h2("5.3 與主流程的銜接"),
        body(
          "此方案銜接在主流程「步驟 3 音訊前處理」到「步驟 4 ASR 初稿轉錄」之間，多軌時以上述對齊混音流程取代單軌直接前處理，其餘步驟（專有名詞比對、AI 二次校對、人工抽查、草稿產出、開放修訂）維持不變。人工抽查範圍聚焦在語者切換的分段點，而非原設計的「各軌分歧段落」（該概念隨逐字比對多數決一併取消）。"
        ),
        h2("5.4 使用限制與注意事項"),
        bullet("多軌對齊只能判斷「兩軌是否有重疊內容」，不代表對齊後的混音結果完全正確，最終品質仍需人工抽查確認。"),
        bullet("若多台裝置擺放位置相近（例如都在會議室同一側），收音特性接近，可能對同一段內容產生相關的辨識錯誤，建議裝置分散擺放於不同側，降低這種情況發生的機會。"),
        bullet("若某段時間沒有任何裝置錄到（例如裝置中途沒電、由另一台裝置晚一段時間才接手），這段真正遺失的內容無法透過演算法還原，混音結果該時段會是空白；系統會偵測到這種「接續」情況並主動在執行畫面提示發生的時間點，不會悄悄略過不提。目前只用真實重疊案例校準過信心門檻，還沒有真正的「裝置中途斷錄」案例可驗證，門檻數值日後應視實際案例回頭校準。"),
        bullet("多軌混音疊加同一個聲音來源時，若對齊精度不足會產生「梳狀濾波」效應，聽感類似回音／空洞感；目前用兩階段比對（粗略定位＋局部精修）將誤差壓到毫秒級以下緩解此問題，但混音仍是單純疊加，並非依語者動態切換音軌，未來如需更細緻的效果可考慮改用動態混音方式。"),
        h2("5.5 技術可行性"),
        makeTable(
          ["處理階段", "可用技術／工具"],
          [
            ["音軌自動歸組", "檔名規則比對＋執行前人工確認清單（Python 腳本）"],
            ["時間軸自動對齊", "音訊互相關演算法（純 numpy／scipy 實作，不依賴 librosa／GPU），粗略定位＋局部精修兩階段"],
            ["語音辨識", "各軌先對齊混音成一份完整錄音，Whisper large-v3（faster-whisper 本機執行）只對混音結果轉錄一次，運算成本不隨裝置數增加而疊加"],
            ["逐字稿分段", "依聲學特徵偵測語者變化時間點，取代原本的逐字比對多數決"],
          ],
          [4400, 5000]
        ),
        body(
          "此方案為選配加值項目，不影響主流程可獨立運作；已於 2026 年 8 月用一場真實會議錄音（含兩支手機全程錄音、一台裝置人工剪接的歷史片段）完整實測過對齊混音與轉錄流程，細節見 6.1 節。",
          { italics: true, color: GREY, size: 20 }
        ),

        // ---------- 六、工具與資源需求 ----------
        h1("六、工具與資源需求"),
        makeTable(
          ["項目", "建議工具／資源", "備註"],
          [
            ["錄音設備", "手機錄音 或 會議專用麥克風／錄音筆", "多人會議建議使用全向麥克風提升收音品質"],
            ["執行環境", "候選環境三選一：Ubuntu Server i7-7700＋32GB RAM／2020 MacBook Pro i5＋16GB RAM／Windows 10 筆電 i5-8250U＋32GB RAM", "皆不使用 GPU，純 CPU 執行；三者硬體世代與作業系統不同，正式排程前需分別實測轉錄耗時再擇優使用"],
            ["語音辨識", "Whisper large-v3（開源模型，透過 faster-whisper 於上述環境執行）", "音檔全程不上傳雲端或第三方 API，資料留在公司環境內"],
            ["音訊前處理", "ffmpeg（loudnorm）／noisereduce", "同樣於本機執行，與語音辨識共用執行環境"],
            ["AI 校對", "Claude Code（直接於對話中讀取逐字稿與對照表校對，非另外寫程式呼叫開發者 API）", "使用者僅有 Claude Team 帳號、無 Anthropic Console／API 計費權限，校對步驟改為在 Claude Code 對話中直接執行；僅傳輸逐字稿文字，不涉及音檔"],
            ["專有名詞對照表", "共用試算表（Google Sheet／Excel）", "由團隊共同維護，每週依需要新增詞彙"],
            ["檔案存放", "內部資料夾／Notion 或既有知識庫", "統一資料夾結構，方便歷史回溯"],
          ],
          [2400, 4400, 2600]
        ),
        body(
          "語音辨識與音訊前處理刻意選用可本機執行的開源方案，避免會議錄音（可能涉及未公開的產品規劃或技術細節）上傳至第三方雲端服務，僅 AI 校對步驟會將逐字稿文字（非原始音檔）提供給 Claude 處理。",
          { italics: true, color: GREY, size: 20 }
        ),
        h2("6.1 運算時間與硬體限制"),
        body(
          "目前候選執行環境為三台硬體世代與作業系統均不同的機器：Ubuntu Server（Intel i7-7700＋32GB RAM）、2020 MacBook Pro（i5＋16GB RAM）、Windows 10 筆電（i5-8250U＋32GB RAM），三者皆無 NVIDIA GPU。faster-whisper 所用的 CTranslate2 引擎本身只支援 NVIDIA CUDA 加速，在這三台機器上即使想用 GPU 也沒有對應的加速路徑可用，因此「純 CPU 執行」不只是團隊主動選擇，也是這三台候選機器的硬體限制。Whisper large-v3 在純 CPU 環境下的轉錄速度通常明顯慢於即時（實際比值依硬體與音檔長度而異，需實測確認），三台機器的 CPU 定位也不同——i5-8250U 為筆電用低功耗晶片，持續高負載運算的表現通常不如桌上型或伺服器等級處理器，實際運算時間需在正式排程前分別實測比較，選出效能較佳或較穩定可用的一台作為正式執行環境。多軌情境下運算時間隨軌數等比增加（例如 3 軌約為單軌的 3 倍運算時間）。由於會議固定在週五，因應方式為「用時間換取」：將轉錄工作排程於週五深夜至週末以批次方式執行，於下週一上班前取得草稿，而非強求會議結束後 24 小時內產出——這也是目標時效改以「下週一上班前」表述、而非「24 小時內」的原因。若日後導入多軌方案，運算時間會進一步拉長，屆時需重新確認批次排程是否仍能在週一上班前完成，必要時檢討是否需要更高規格的執行環境。"
        ),
        body(
          "已於 2026 年 8 月在候選機器之一（2020 MacBook Pro，i5＋16GB RAM）完成第一次真實會議錄音的完整實測（74.9 分鐘、三軌，含手動剪接過的歷史片段）：三軌對齊混音耗時約 18～21 分鐘，Whisper large-v3 純 CPU 轉錄實測即時倍數約 2.25～2.57 倍，全流程總耗時約 3 小時。這是目前唯一一台已實測的機器，Ubuntu Server（i7-7700）與 Windows 10 筆電（i5-8250U）尚待用同一套腳本實測比較，數字僅供這台機器參考，不代表其他兩台的實際表現。",
          { italics: true, color: GREY, size: 20 }
        ),

        // ---------- 七、角色與分工 ----------
        h1("七、角色與分工"),
        makeTable(
          ["角色", "負責事項"],
          [
            ["會議主持人／紀錄窗口", "負責啟動錄音、確認收音品質、會後將音檔存入指定資料夾"],
            ["流程執行人", "執行前處理、ASR 轉錄、AI 校對，產出草稿逐字稿與摘要"],
            ["內容把關人", "人工抽查關鍵段落與多軌分歧段落，確認決議事項與數字無誤"],
            ["對照表維護人", "定期更新專有名詞對照表，補充新技術詞彙"],
            ["全體團隊成員", "草稿廣發後，針對自己發言或熟悉的內容協助訂正，回饋給流程執行人彙整定稿"],
          ],
          [3200, 6200]
        ),

        // ---------- 八、時程規劃 ----------
        h1("八、時程規劃"),
        makeTable(
          ["階段", "工作內容", "預計時間"],
          [
            ["第 1 週", "建立專有名詞對照表初版、確認錄音設備與執行環境（本機／VM）", "1 週"],
            ["第 2–3 週", "試行完整流程，記錄實際運算時間與人工投入時數，視需要調整為夜間批次排程", "2 週"],
            ["第 4 週", "流程定案，確認整套流程可穩定重複執行（含執行環境、對照表、開放修訂機制）", "1 週"],
            ["第 5–6 週", "導入多機音軌自動整合方案，先以 2 台裝置試行比對邏輯；因運算時間隨軌數增加，需重新確認批次排程能否於週一上班前完成", "2 週"],
            ["第 7 週起", "正式導入每週例行執行，持續優化對照表與裝置擺位", "持續進行"],
          ],
          [2000, 5200, 2400]
        ),

        // ---------- 九、風險與因應對策 ----------
        h1("九、風險與因應對策"),
        makeTable(
          ["風險", "因應對策"],
          [
            ["收音品質不佳導致辨識率偏低", "固定收音位置與設備，會議前 30 秒測試錄音"],
            ["新技術詞彙未收錄於對照表", "每週校對時同步更新對照表，滾動累積詞庫"],
            ["人工抽查流於形式，遺漏錯誤", "明訂抽查段落原則（決議、數字、行動項目優先），並涵蓋多軌分歧段落"],
            ["流程執行人力不足或請假", "建立操作手冊，確保多人可代理執行"],
            ["多軌時間對齊失敗或誤差過大", "保留單軌流程為備援，對齊失敗時自動退回單軌處理"],
            ["會議內容涉及敏感資訊外洩", "語音辨識與音訊前處理全程本機執行，音檔不上傳雲端；僅逐字稿文字用於 AI 校對"],
            ["CPU 環境運算時間過長，無法在下週一上班前產出草稿", "排程於週五深夜至週末以批次方式，於候選三台機器中效能較佳者執行；若導入多軌後運算時間倍增仍無法如期完成，優先評估精簡軌數或改用較小的量化模型，三台候選機器皆無 NVIDIA GPU，追加 GPU 資源需另外申請具 NVIDIA GPU 的環境，非既有設備可直接支援"],
            ["人工投入時間被低估，執行人力難以負荷", "目標值誠實抓 3–5 小時／次，並每週實際記錄耗時，超出預期時檢討分工或簡化步驟"],
            ["多軌裝置擺位相近，錯誤彼此相關，交叉比對失去意義", "要求裝置分散擺放於會議室不同側，降低各軌錯誤的相關性"],
            ["對照表維護人單點故障（請假／離職）", "指定至少一名備援維護人，並將對照表存放於團隊共用位置，任何人都可臨時代為更新"],
            ["人聲重疊、會議室回音等雜訊，降噪演算法難以消除", "此類雜訊不寄望軟體修正，優先靠麥克風擺位與會議發言秩序（避免搶話重疊）預防"],
            ["草稿被團隊當成定稿直接引用，沒人做開放修訂", "廣發時明確標示「草稿，待確認」字樣，並定期提醒團隊參與訂正，而非預設沉默等於正確"],
          ],
          [4200, 5200]
        ),

        // ---------- 十、預期成效 ----------
        h1("十、預期成效"),
        bullet("每週固定於下週一上班前可取得 AI 輔助產出的草稿逐字稿，省去從頭聽打的時間。"),
        bullet("大幅降低會後人工整理紀錄的時間成本，將原本分散、不規則的人工聽打工作，收斂為每週 3–5 小時可預期、可分工的固定投入。"),
        bullet("建立可回溯的會議歷史紀錄，提升缺席同事與新進成員的資訊對稱性。"),
        bullet("累積之專有名詞對照表可延伸應用至其他會議或文件轉錄場景。"),
        bullet("導入多機音軌自動整合後，可望進一步縮小人工需要逐字核對的範圍，讓人力集中在真正有疑慮的段落。"),

        // ---------- 十一、附錄 ----------
        h1("十一、附錄：專有名詞對照表範本"),
        body("以下為對照表起始範例，實際使用時建議以共用試算表維護，方便每週更新："),
        makeTable(
          ["辨識常見錯誤", "正確用詞", "類型"],
          [
            ["得撲樓依", "deploy", "技術詞彙"],
            ["史普林", "sprint", "技術詞彙"],
            ["巴哥", "bug", "技術詞彙"],
            ["（依實際會議內容持續新增）", "", ""],
          ],
          [3600, 3600, 2200]
        ),
        new Paragraph({ spacing: { before: 300 }, children: [] }),
        hr(),
        body("本計劃書為初版，將依前四週試行結果滾動調整流程細節與時程。", { italics: true, color: GREY, size: 20 }),
      ],
    },
  ],
});

const path = require("path");
const OUTPUT_PATH = path.join(__dirname, "..", "App_Dev_Team_逐字稿自動化計劃書.docx");

Packer.toBuffer(doc).then((buf) => {
  require("fs").writeFileSync(OUTPUT_PATH, buf);
  console.log("done:", OUTPUT_PATH);
});
