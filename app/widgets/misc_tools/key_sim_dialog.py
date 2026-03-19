from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QGridLayout

from qfluentwidgets import CardWidget, TitleLabel, CaptionLabel, BodyLabel, PushButton, PrimaryPushButton, InfoBar, InfoBarPosition

from app.services import adb_service as svc


class _KeySimDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("模拟按键")
        self.resize(960, 620)

        lay = QVBoxLayout(self)
        try:
            lay.setContentsMargins(24, 20, 24, 20)
            lay.setSpacing(12)
        except Exception:
            pass

        header = CardWidget(self)
        h = QVBoxLayout(header)
        h.setContentsMargins(16, 14, 16, 14)
        h.setSpacing(4)
        h.addWidget(TitleLabel("模拟按键", header))
        h.addWidget(CaptionLabel("通过 adb shell input keyevent / svc data 实现音量、锁屏/电源、静音、数据流量等操作（部分ROM可能限制）", header))
        lay.addWidget(header)

        card = CardWidget(self)
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 12, 16, 12)
        c.setSpacing(10)

        c.addWidget(BodyLabel("点击按钮即可发送按键事件：", card))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        buttons = [
            ("音量 +", lambda: self._keyevent(24)),
            ("音量 -", lambda: self._keyevent(25)),
            ("静音/取消静音", lambda: self._keyevent(164)),
            ("锁屏/电源键", lambda: self._keyevent(26)),
            ("返回", lambda: self._keyevent(4)),
            ("主页", lambda: self._keyevent(3)),
            ("最近任务", lambda: self._keyevent(187)),
            ("通知栏", lambda: self._keyevent(83)),
        ]

        r = 0
        col = 0
        for text, fn in buttons:
            b = PrimaryPushButton(text, card)
            b.clicked.connect(fn)
            grid.addWidget(b, r, col)
            col += 1
            if col >= 3:
                col = 0
                r += 1

        c.addLayout(grid)

        row = QHBoxLayout(); row.setSpacing(8)
        row.addStretch(1)
        btn_data_on = PushButton("数据流量：开启", card)
        btn_data_on.clicked.connect(lambda: self._svc_data(True))
        row.addWidget(btn_data_on)
        btn_data_off = PushButton("数据流量：关闭", card)
        btn_data_off.clicked.connect(lambda: self._svc_data(False))
        row.addWidget(btn_data_off)
        c.addLayout(row)

        lay.addWidget(card)

    def _toast(self, kind: str, title: str, content: str, ms: int = 2200):
        try:
            if kind == 'ok':
                InfoBar.success(title, content, parent=self, position=InfoBarPosition.TOP, duration=ms, isClosable=True)
            elif kind == 'err':
                InfoBar.error(title, content, parent=self, position=InfoBarPosition.TOP, duration=ms, isClosable=True)
            elif kind == 'warn':
                InfoBar.warning(title, content, parent=self, position=InfoBarPosition.TOP, duration=ms, isClosable=True)
            else:
                InfoBar.info(title, content, parent=self, position=InfoBarPosition.TOP, duration=ms, isClosable=True)
        except Exception:
            pass

    def _get_serial(self) -> str:
        try:
            serials = svc.list_devices()
            return serials[0] if serials else ""
        except Exception:
            return ""

    def _shell(self, cmd: str, timeout: int = 8) -> str:
        serial = self._get_serial()
        if not serial:
            return ""
        return svc.adb_shell_serial(serial, cmd, timeout=timeout) or ""

    def _keyevent(self, code: int):
        if not self._get_serial():
            self._toast('warn', '提示', '未检测到设备')
            return
        out = self._shell(f"input keyevent {int(code)}", timeout=6)
        _ = out
        self._toast('ok', '已发送', f"keyevent {code}")

    def _svc_data(self, on: bool):
        if not self._get_serial():
            self._toast('warn', '提示', '未检测到设备')
            return
        cmd = "svc data enable" if on else "svc data disable"
        out = self._shell(cmd, timeout=8)
        if out and ("Permission" in out or "denied" in out.lower()):
            self._toast('err', '失败', '权限不足：部分系统不允许 shell 控制数据流量')
            return
        self._toast('ok', '完成', '已尝试切换数据流量')
