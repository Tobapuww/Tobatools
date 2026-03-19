from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout

from qfluentwidgets import CardWidget, TitleLabel, CaptionLabel, BodyLabel, LineEdit, PushButton, PrimaryPushButton, MessageDialog

from app.services import adb_service as svc


class _ScreenTimeoutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("锁屏时间修改")
        self.resize(820, 420)

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
        h.addWidget(TitleLabel("锁屏时间修改", header))
        h.addWidget(CaptionLabel("读取/修改 screen_off_timeout（单位毫秒）", header))
        lay.addWidget(header)

        card = CardWidget(self)
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 12, 16, 12)
        c.setSpacing(10)

        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(BodyLabel("锁屏时间(秒)", card))
        row.addStretch(1)
        self.edt_seconds = LineEdit(card)
        self.edt_seconds.setMinimumWidth(220)
        row.addWidget(self.edt_seconds)
        btn_apply = PrimaryPushButton("应用", card)
        btn_apply.clicked.connect(self._apply)
        row.addWidget(btn_apply)
        c.addLayout(row)

        row2 = QHBoxLayout(); row2.setSpacing(8)
        row2.addStretch(1)
        btn_refresh = PushButton("刷新当前值", card)
        btn_refresh.clicked.connect(self._refresh)
        row2.addWidget(btn_refresh)
        c.addLayout(row2)

        lay.addWidget(card)

        self._refresh()

    def _toast(self, title: str, content: str):
        MessageDialog(title, content, self).exec()

    def _get_serial(self) -> str:
        try:
            serials = svc.list_devices()
            return serials[0] if serials else ""
        except Exception:
            return ""

    def _shell(self, cmd: str, timeout: int = 10) -> str:
        serial = self._get_serial()
        if not serial:
            return ""
        return svc.adb_shell_serial(serial, cmd, timeout=timeout) or ""

    def _refresh(self):
        if not self._get_serial():
            self._toast("提示", "未检测到设备")
            return
        out = (self._shell("settings get system screen_off_timeout", timeout=6) or "").strip()
        sec = ""
        try:
            ms = int(out)
            sec = str(int(ms / 1000))
        except Exception:
            sec = ""
        try:
            self.edt_seconds.setText(sec)
        except Exception:
            pass

    def _apply(self):
        v = (self.edt_seconds.text() or "").strip()
        if not v or not v.isdigit():
            self._toast("提示", "请输入秒数")
            return
        sec = int(v)
        if sec < 5:
            self._toast("提示", "秒数太小")
            return
        ms = sec * 1000
        out = self._shell(f"settings put system screen_off_timeout {ms}", timeout=8)
        if out and "Permission" in out:
            self._toast("失败", "权限不足：部分系统需要 Root 或 Shizuku")
            return
        self._toast("完成", "已设置锁屏时间")
