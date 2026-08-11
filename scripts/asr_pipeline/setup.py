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


def ensure_linux_venv_support():
    """Debian/Ubuntu 把 venv 模組的 ensurepip 拆成獨立套件（python3-venv），
    沒裝的話 `python3 -m venv` 會直接失敗，這是系統打包問題不是程式問題。
    這裡跟 ffmpeg 是否已安裝無關，一定要獨立檢查，否則 ffmpeg 已存在時會漏掉這一步。
    用 apt 直接裝，已經裝過的話 apt 會很快回報「已是最新版本」，不需要事先判斷。"""
    if SYSTEM != "Linux":
        return
    if not shutil.which("apt-get"):
        print("找不到 apt-get，這台機器不是 Debian/Ubuntu 系列，若稍後建立虛擬環境失敗，"
              "請自行安裝對應的 python3-venv 套件後重跑本腳本")
        return
    _print("確認 python3-venv（Debian/Ubuntu 的 venv 系統相依套件）")
    subprocess.run(["sudo", "apt-get", "install", "-y", "python3-venv"], check=True)


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


def _venv_has_pip(python: Path) -> bool:
    if not python.exists():
        return False
    result = subprocess.run([str(python), "-m", "pip", "--version"], capture_output=True)
    return result.returncode == 0


def ensure_python_deps():
    _print("建立虛擬環境並安裝 Python 套件")
    python = _venv_bin("python")

    # 之前若在 venv 建立到一半就失敗（例如 Debian/Ubuntu 缺 python3-venv 導致 ensurepip 失敗），
    # 資料夾會殘留但沒有 pip；只檢查資料夾存在會誤判成「已建好」而沿用殘缺環境，這裡要連 pip 一起驗證。
    if VENV_DIR.exists() and not _venv_has_pip(python):
        print("偵測到不完整的虛擬環境（可能是先前失敗的殘留），重新建立")
        shutil.rmtree(VENV_DIR)

    if not VENV_DIR.exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    if not _venv_has_pip(python):
        print("虛擬環境裡沒有 pip，嘗試用 ensurepip 補裝")
        subprocess.run([str(python), "-m", "ensurepip", "--upgrade"], check=True)

    # Windows 上直接呼叫 pip.exe 升級自己會失敗（執行中的檔案不能覆寫），改用 python -m pip
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(REPO_DIR / "requirements.txt")], check=True)


def run_env_check():
    _print("環境檢查")
    python = _venv_bin("python")
    subprocess.run([str(python), str(REPO_DIR / "env_check.py")], check=True)


def main():
    print(f"作業系統偵測：{SYSTEM}")
    ensure_ffmpeg()
    ensure_linux_venv_support()
    ensure_python_deps()
    run_env_check()

    python = _venv_bin("python")
    print()
    print("設定完成。之後執行方式：")
    print(f"  {python} phase1_pipeline.py --dir <週會資料夾> --date <yyyyMMdd>")


if __name__ == "__main__":
    main()
