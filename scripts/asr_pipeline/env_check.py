import os
import platform
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")  # Windows 主控台預設編碼不是 UTF-8，印中文會亂碼甚至報錯
sys.stderr.reconfigure(encoding="utf-8")


def check_ffmpeg():
    path = shutil.which("ffmpeg")
    if not path:
        return False, ""
    try:
        out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=5)
        version_line = out.stdout.splitlines()[0] if out.stdout else ""
    except Exception:
        version_line = ""
    return True, version_line


def check_package(module_name):
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


FFMPEG_INSTALL_HINT = {
    "Darwin": "brew install ffmpeg",
    "Linux": "sudo apt install ffmpeg",
    "Windows": "choco install ffmpeg，或至 ffmpeg.org 下載並將 bin 目錄加入 PATH",
}


def main():
    print(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"CPU: {platform.processor() or platform.machine()}, {os.cpu_count()} logical cores")
    print(f"Python: {platform.python_version()}")

    ffmpeg_ok, ffmpeg_version = check_ffmpeg()
    print(f"ffmpeg: {'OK - ' + ffmpeg_version if ffmpeg_ok else 'NOT FOUND'}")

    for pkg in ("faster_whisper", "noisereduce", "soundfile", "opencc"):
        print(f"{pkg}: {'OK' if check_package(pkg) else 'NOT INSTALLED'}")

    recommended_threads = max(1, (os.cpu_count() or 2) - 1)
    print(f"建議 faster-whisper cpu_threads = {recommended_threads}（保留 1 核給系統）")

    if not ffmpeg_ok:
        hint = FFMPEG_INSTALL_HINT.get(platform.system(), "請安裝 ffmpeg 並確認在 PATH 中")
        print(f"-> {hint}")


if __name__ == "__main__":
    main()
