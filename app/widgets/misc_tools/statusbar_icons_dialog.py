from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QCheckBox

from qfluentwidgets import CardWidget, TitleLabel, CaptionLabel, BodyLabel, PushButton, PrimaryPushButton, MessageDialog

from app.services import adb_service as svc


class _StatusBarIconsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("隐藏状态栏图标")
        self.resize(980, 620)

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
        h.addWidget(TitleLabel("隐藏状态栏图标", header))
        h.addWidget(CaptionLabel("通过 secure 的 icon_blacklist 控制（Android 9+ 常见；不同ROM项名可能不同）", header))
        lay.addWidget(header)

        card = CardWidget(self)
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 12, 16, 12)
        c.setSpacing(10)

        c.addWidget(BodyLabel("选择要隐藏的图标：", card))

        grid = QGridLayout();
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        self._items = [
            ("clock", "时间"),
            ("bluetooth", "蓝牙"),
            ("location", "定位"),
            ("headset", "耳机"),
            ("battery", "电池"),
            ("wifi", "WiFi"),
            ("alarm_clock", "闹钟"),
            ("nfc", "NFC"),
            ("volume", "声音"),
            ("mobile", "信号"),
            ("airplane", "飞行模式"),
            ("rotate", "旋转"),
            ("seconds", "时间显示秒"),
        ]
        self._checks: dict[str, QCheckBox] = {}

        col = 0
        row = 0
        for key, label in self._items:
            cb = QCheckBox(label, card)
            self._checks[key] = cb
            grid.addWidget(cb, row, col)
            col += 1
            if col >= 4:
                col = 0
                row += 1

        c.addLayout(grid)

        row_btn = QHBoxLayout(); row_btn.setSpacing(8)
        row_btn.addStretch(1)
        btn_refresh = PushButton("刷新当前", card)
        btn_refresh.clicked.connect(self._refresh)
        row_btn.addWidget(btn_refresh)
        btn_apply = PrimaryPushButton("应用", card)
        btn_apply.clicked.connect(self._apply)
        row_btn.addWidget(btn_apply)
        btn_clear = PushButton("清空(全部显示)", card)
        btn_clear.clicked.connect(self._clear)
        row_btn.addWidget(btn_clear)
        c.addLayout(row_btn)

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
        out = (self._shell("settings get secure icon_blacklist", timeout=6) or "").strip()
        cur = set([x.strip() for x in out.split(',') if x.strip()]) if out and out.lower() != 'null' else set()
        for key, cb in self._checks.items():
            try:
                cb.setChecked(key in cur)
            except Exception:
                pass

    def _apply(self):
        keys = []
        for key, cb in self._checks.items():
            try:
                if cb.isChecked():
                    keys.append(key)
            except Exception:
                pass
        val = ",".join(keys)
        out = self._shell(f"settings put secure icon_blacklist '{val}'", timeout=8)
        if out and "Permission" in out:
            self._toast("失败", "权限不足：部分系统需要 Root 或 Shizuku")
            return
        self._toast("完成", "已应用")

    def _clear(self):
        out = self._shell("settings delete secure icon_blacklist", timeout=8)
        _ = out
        self._refresh()
        self._toast("完成", "已清空")
