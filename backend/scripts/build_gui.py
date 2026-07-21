"""把 bitbrowser_relay_agent_gui.py 打包成单文件可执行程序。

在 BitBrowser 那台电脑（一般是 Windows）上执行::

    pip install pyinstaller pyqt5 websockets httpx
    python build_gui.py

产物在 dist/ 下（Windows 为 BitBrowserRelayAgent.exe）。也可直接手敲::

    pyinstaller --noconfirm --clean --windowed --onefile \
        --name BitBrowserRelayAgent bitbrowser_relay_agent_gui.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    entry = HERE / "bitbrowser_relay_agent_gui.py"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        "BitBrowserRelayAgent",
        str(entry),
    ]
    print("运行:", " ".join(cmd))
    raise SystemExit(subprocess.call(cmd, cwd=str(HERE)))


if __name__ == "__main__":
    main()
