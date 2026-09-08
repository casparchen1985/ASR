from datetime import datetime


def log(msg: str) -> None:
    """加時間戳記印出訊息，方便從 log 抓兩個階段之間間隔多久（排程情境會跨午夜，
    只印時分秒無法分辨是同一天還是隔天，格式固定含月/日）。

    背景執行時 stdout 沒有接到終端機，Python 預設走區塊緩衝，不會即時寫進輸出檔，
    要等緩衝區塞滿或程式結束才看得到——這樣就失去監看進度的意義，因此每次都強制 flush。
    """
    print(f"[{datetime.now():%m/%d %H:%M:%S}] {msg}", flush=True)
