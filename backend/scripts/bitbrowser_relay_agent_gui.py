"""BitBrowser 中继 agent —— PyQt5 图形界面版。

包一层 GUI，方便每位使用者在自己装有 BitBrowser 的电脑（Windows / macOS）上不用命令行
也能填后端地址 + 系统账号并一键启停中继。核心逻辑复用命令行版
``bitbrowser_relay_agent.py`` 里的 ``Agent``。

默认是「专属中继」：用自己的系统账号登录，只转发自己的 BitBrowser 请求；填了
「共享 Token」则作为全员共用的共享中继。

本地运行::

    pip install pyqt5 websockets httpx certifi
    python bitbrowser_relay_agent_gui.py

打包（Windows 出 exe、macOS 出 .app，需在对应系统上执行，详见 build_gui.py；
也可在 GitHub Actions 手动触发 "Build BitBrowser Relay Agent" 一次出齐三个平台）::

    pip install pyinstaller pyqt5 websockets httpx certifi
    pyinstaller --noconfirm --clean --windowed --onefile \
        --name BitBrowserRelayAgent bitbrowser_relay_agent_gui.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading

from PyQt5.QtCore import QObject, QSettings, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bitbrowser_relay_agent import Agent, AgentAuthError

log = logging.getLogger("bb-relay-agent")


class _QtLogHandler(logging.Handler, QObject):
    """把 logging 记录通过 Qt 信号送回主线程展示。"""

    record = pyqtSignal(str)

    def __init__(self) -> None:
        logging.Handler.__init__(self)
        QObject.__init__(self)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.record.emit(self.format(record))
        except Exception:  # noqa: BLE001
            pass


class RelayWorker(QObject):
    """在后台线程里跑 asyncio 事件循环，驱动 Agent.run_forever。"""

    stopped = pyqtSignal()

    def __init__(
        self,
        server: str,
        token: str,
        bb_url: str,
        bb_api_key: str,
        username: str = "",
        password: str = "",
    ) -> None:
        super().__init__()
        self._server = server
        self._token = token
        self._username = username
        self._password = password
        self._bb_url = bb_url
        self._bb_api_key = bb_api_key
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="bb-relay", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        agent = Agent(
            self._server,
            self._token,
            self._bb_url,
            self._bb_api_key or None,
            username=self._username,
            password=self._password,
        )
        try:
            self._task = loop.create_task(agent.run_forever())
            loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except AgentAuthError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("中继异常退出：%s", e)
        finally:
            try:
                loop.run_until_complete(agent._close_all_cdp())
            except Exception:  # noqa: BLE001
                pass
            loop.close()
            self.stopped.emit()

    def stop(self) -> None:
        loop = self._loop
        task = self._task
        if loop is not None and task is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BitBrowser 中继 Agent")
        self.resize(640, 520)
        self._settings = QSettings("worldlink-jp", "BitBrowserRelayAgent")
        self._worker: RelayWorker | None = None

        self.server_edit = QLineEdit(self._settings.value("server", "", str))
        self.server_edit.setPlaceholderText("如 https://后端域名或IP:8014（与浏览器里打开管理端的地址一致）")
        self.username_edit = QLineEdit(self._settings.value("username", "", str))
        self.username_edit.setPlaceholderText("登录管理端用的账号；中继只服务这个账号")
        self.password_edit = QLineEdit(self._settings.value("password", "", str))
        self.password_edit.setPlaceholderText("登录管理端用的密码")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.token_edit = QLineEdit(self._settings.value("token", "", str))
        self.token_edit.setPlaceholderText("仅全员共用一台 BitBrowser 电脑时填；填了就不用账号密码")
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.bb_url_edit = QLineEdit(
            self._settings.value("bb_url", "http://127.0.0.1:54345", str)
        )
        self.bb_key_edit = QLineEdit(self._settings.value("bb_api_key", "", str))
        self.bb_key_edit.setPlaceholderText("BitBrowser Local API 鉴权 Token（未开启可留空）")
        self.bb_key_edit.setEchoMode(QLineEdit.Password)

        form = QFormLayout()
        form.addRow("后端地址", self.server_edit)
        form.addRow("系统账号", self.username_edit)
        form.addRow("系统密码", self.password_edit)
        form.addRow("共享 Token（可选）", self.token_edit)
        form.addRow("BitBrowser Local API", self.bb_url_edit)
        form.addRow("Local API Token", self.bb_key_edit)

        self.start_btn = QPushButton("启动")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)

        self.status_label = QLabel("未启动")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(btn_row)
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel("运行日志"))
        layout.addWidget(self.log_view, 1)

        self._log_handler = _QtLogHandler()
        self._log_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        self._log_handler.record.connect(self._append_log, Qt.QueuedConnection)
        logging.getLogger().addHandler(self._log_handler)
        logging.getLogger().setLevel(logging.INFO)

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _on_start(self) -> None:
        server = self.server_edit.text().strip()
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        token = self.token_edit.text().strip()
        if not server:
            self.status_label.setText("请先填写后端地址")
            return
        if not token and not (username and password):
            self.status_label.setText("请填写系统账号和密码（或共享 Token）")
            return
        bb_url = self.bb_url_edit.text().strip() or "http://127.0.0.1:54345"
        bb_api_key = self.bb_key_edit.text().strip()

        self._settings.setValue("server", server)
        self._settings.setValue("username", username)
        self._settings.setValue("password", password)
        self._settings.setValue("token", token)
        self._settings.setValue("bb_url", bb_url)
        self._settings.setValue("bb_api_key", bb_api_key)

        # 填了共享 Token 就走共享中继，否则用账号密码登录为专属中继
        if token:
            username, password = "", ""
        self._worker = RelayWorker(server, token, bb_url, bb_api_key, username, password)
        self._worker.stopped.connect(self._on_worker_stopped, Qt.QueuedConnection)
        self._worker.start()

        self._set_inputs_enabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("运行中（共享中继）" if token else f"运行中（专属中继：{username}）")

    def _on_stop(self) -> None:
        if self._worker is not None:
            self.status_label.setText("正在停止 ...")
            self.stop_btn.setEnabled(False)
            self._worker.stop()

    def _on_worker_stopped(self) -> None:
        self._worker = None
        self._set_inputs_enabled(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("已停止")

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for w in (
            self.server_edit,
            self.username_edit,
            self.password_edit,
            self.token_edit,
            self.bb_url_edit,
            self.bb_key_edit,
        ):
            w.setEnabled(enabled)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None:
            self._worker.stop()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
