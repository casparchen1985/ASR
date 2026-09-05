from datetime import datetime


def log(msg: str) -> None:
    """加時間戳記印出訊息，方便從 log 抓兩個階段之間間隔多久（排程情境會跨午夜，
    只印時分秒無法分辨是同一天還是隔天，格式固定含月/日）。"""
    print(f"[{datetime.now():%m/%d %H:%M:%S}] {msg}")
