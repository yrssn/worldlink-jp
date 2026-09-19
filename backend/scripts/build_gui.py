"""把 bitbrowser_relay_agent_gui.py 打包成单文件可执行程序（Windows / macOS）。

PyInstaller 不支持跨平台交叉编译：要 Windows 版就在 Windows 上跑，要 macOS 版就在
macOS 上跑（Apple Silicon 与 Intel 也各打各的，或用 GitHub Actions 一次全出，见
``.github/workflows/build-relay-agent.yml``）。

在目标电脑上执行::

    pip install pyinstaller pyqt5 websockets httpx
    python build_gui.py

产物在 dist/ 下：

* Windows: ``BitBrowserRelayAgent.exe``
* macOS:   ``BitBrowserRelayAgent.app``，并额外压成 ``BitBrowserRelayAgent-macos-<arch>.zip``
  方便分发。未签名的 .app 首次打开会被 Gatekeeper 拦，右键「打开」或执行
  ``xattr -cr BitBrowserRelayAgent.app`` 即可。

也可直接手敲::

    pyinstaller --noconfirm --clean --windowed --onefile \
        --name BitBrowserRelayAgent bitbrowser_relay_agent_gui.py
"""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_NAME = "BitBrowserRelayAgent"


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
        APP_NAME,
    ]
    if sys.platform == "darwin":
        cmd += ["--osx-bundle-identifier", "jp.worldlink.bitbrowser-relay-agent"]
    cmd.append(str(entry))
    print("运行:", " ".join(cmd))
    code = subprocess.call(cmd, cwd=str(HERE))
    if code != 0:
        raise SystemExit(code)

    if sys.platform == "darwin":
        dist = HERE / "dist"
        app = dist / f"{APP_NAME}.app"
        zip_path = dist / f"{APP_NAME}-macos-{platform.machine().lower()}.zip"
        # .app 是目录，用 ditto 压包才能保留可执行权限和符号链接
        subprocess.check_call(["ditto", "-c", "-k", "--keepParent", str(app), str(zip_path)])
        print("已生成:", zip_path)


if __name__ == "__main__":
    main()
