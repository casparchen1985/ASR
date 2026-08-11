import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows 主控台預設編碼不是 UTF-8，印中文會亂碼甚至報錯
sys.stderr.reconfigure(encoding="utf-8")

REPO_DIR = Path(__file__).parent
VENV_DIR = REPO_DIR / ".venv"
SYSTEM = platform.system()


def _print(msg):
    print(f"=== {msg} ===")


def _venv_bin(name):
    if SYSTEM == "Windows":
        return VENV_DIR / "Scripts" / f"{name}.exe"
    return VENV_DIR / "bin" / name


def ensure_ffmpeg():
    if shutil.which("ffmpeg"):
        print(f"ffmpeg 已安裝：{shutil.which('ffmpeg')}")
        return

    _print("安裝 ffmpeg")
    if SYSTEM == "Darwin":
        if not shutil.which("brew"):
            print("找不到 Homebrew，請先安裝 https://brew.sh，再重跑本腳本")
            sys.exit(1)
        subprocess.run(["brew", "install", "ffmpeg"], check=True)
    elif SYSTEM == "Linux":
        if not shutil.which("apt-get"):
            print("找不到 apt-get，這台機器不是 Debian/Ubuntu 系列，請自行安裝 ffmpeg 後重跑本腳本")
            sys.exit(1)
        subprocess.run(["sudo", "apt-get", "update"], check=True)
        subprocess.run(["sudo", "apt-get", "install", "-y", "ffmpeg"], check=True)
    elif SYSTEM == "Windows":
        if not shutil.which("winget"):
            print("找不到 winget，請先從 Microsoft Store 安裝 App Installer，或手動安裝 ffmpeg 並加入 PATH 後重跑本腳本")
            sys.exit(1)
        subprocess.run([
            "winget", "install", "-e", "--id", "Gyan.FFmpeg",
            "--accept-package-agreements", "--accept-source-agreements",
        ], check=True)
        print("ffmpeg 安裝完成。如果這個視窗還偵測不到 ffmpeg，是 Windows PATH 沒有即時更新的正常現象，"
              "請關閉視窗重開一次再執行本腳本。")
    else:
        print(f"未知作業系統 {SYSTEM}，請自行安裝 ffmpeg 並確認在 PATH 中")
        sys.exit(1)


def ensure_python_deps():
    _print("建立虛擬環境並安裝 Python 套件")
    if not VENV_DIR.exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    pip = _venv_bin("pip")
    subprocess.run([str(pip), "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(pip), "install", "-r", str(REPO_DIR / "requirements.txt")], check=True)


def run_env_check():
    _print("環境檢查")
    python = _venv_bin("python")
    subprocess.run([str(python), str(REPO_DIR / "env_check.py")], check=True)


def main():
    print(f"作業系統偵測：{SYSTEM}")
    ensure_ffmpeg()
    ensure_python_deps()
    run_env_check()

    python = _venv_bin("python")
    print()
    print("設定完成。之後執行方式：")
    print(f"  {python} phase1_pipeline.py --dir <週會資料夾> --date <yyyyMMdd>")


if __name__ == "__main__":
    main()
