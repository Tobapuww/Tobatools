from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout

from qfluentwidgets import CardWidget, TitleLabel, CaptionLabel, BodyLabel, LineEdit, ComboBox, PushButton, PrimaryPushButton, MessageDialog

from app.services import adb_service as svc


class _BatterySimDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("电池状态模拟")
        self.resize(860, 520)

        lay = QVBoxLayout(self)
        try:
            lay.setContentsMargins(24, 20, 24, 20)
            lay.setSpacing(12)
        except Exception:
            pass

        header = CardWidget(self)
        header_lay = QVBoxLayout(header)
        header_lay.setContentsMargins(16, 14, 16, 14)
        header_lay.setSpacing(4)
        header_lay.addWidget(TitleLabel("电池状态模拟", header))
        header_lay.addWidget(CaptionLabel("通过 dumpsys/cmd battery 模拟电量、温度与充电状态（部分系统需要允许 shell 修改）", header))
        lay.addWidget(header)

        card = CardWidget(self)
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(16, 12, 16, 12)
        c_lay.setSpacing(10)

        row_level = QHBoxLayout(); row_level.setSpacing(8)
        row_level.addWidget(BodyLabel("电量(0-100)", card))
        row_level.addStretch(1)
        self.edt_level = LineEdit(card)
        self.edt_level.setMinimumWidth(220)
        row_level.addWidget(self.edt_level)
        btn_level = PrimaryPushButton("应用", card)
        btn_level.clicked.connect(self._apply_level)
        row_level.addWidget(btn_level)
        c_lay.addLayout(row_level)

        row_temp = QHBoxLayout(); row_temp.setSpacing(8)
        row_temp.addWidget(BodyLabel("温度(℃)", card))
        row_temp.addStretch(1)
        self.edt_temp = LineEdit(card)
        self.edt_temp.setMinimumWidth(220)
        row_temp.addWidget(self.edt_temp)
        btn_temp = PrimaryPushButton("应用", card)
        btn_temp.clicked.connect(self._apply_temp)
        row_temp.addWidget(btn_temp)
        c_lay.addLayout(row_temp)

        row_status = QHBoxLayout(); row_status.setSpacing(8)
        row_status.addWidget(BodyLabel("充电状态", card))
        row_status.addStretch(1)
        self.combo_plug = ComboBox(card)
        self.combo_plug.addItems(["非充电", "无线充电", "USB充电", "直流充电"])
        self.combo_plug.setMinimumWidth(220)
        row_status.addWidget(self.combo_plug)
        btn_plug = PrimaryPushButton("应用", card)
        btn_plug.clicked.connect(self._apply_plug)
        row_status.addWidget(btn_plug)
        c_lay.addLayout(row_status)

        row_actions = QHBoxLayout(); row_actions.setSpacing(8)
        row_actions.addStretch(1)
        btn_refresh = PushButton("刷新当前值", card)
        btn_refresh.clicked.connect(self._refresh)
        row_actions.addWidget(btn_refresh)
        btn_reset = PushButton("重置模拟", card)
        btn_reset.clicked.connect(self._reset)
        row_actions.addWidget(btn_reset)
        c_lay.addLayout(row_actions)

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

    def _ensure_override(self) -> bool:
        out = self._shell("cmd battery set usb 0", timeout=6)
        _ = out
        out2 = self._shell("cmd battery set ac 0", timeout=6)
        _ = out2
        out3 = self._shell("cmd battery set wireless 0", timeout=6)
        _ = out3
        self._shell("cmd battery set status 1", timeout=6)
        self._shell("cmd battery set present true", timeout=6)
        # enable override
        o = self._shell("cmd battery set", timeout=6)
        _ = o
        en = self._shell("dumpsys battery set", timeout=6)
        _ = en
        self._shell("cmd battery set", timeout=6)
        # some devices use: dumpsys battery set ac/usb/wireless
        return True

    def _refresh(self):
        serial = self._get_serial()
        if not serial:
            self._toast("提示", "未检测到设备")
            return

        dump = self._shell("dumpsys battery", timeout=8)
        level = ""
        temp_c = ""
        plugged = ""
        for line in (dump or "").splitlines():
            t = (line or "").strip()
            if t.startswith("level:"):
                level = t.split(":", 1)[1].strip()
            elif t.startswith("temperature:"):
                v = t.split(":", 1)[1].strip()
                try:
                    temp_c = str(float(v) / 10.0)
                except Exception:
                    temp_c = v
            elif t.startswith("plugged:"):
                plugged = t.split(":", 1)[1].strip()

        try:
            self.edt_level.setText(level)
        except Exception:
            pass
        try:
            self.edt_temp.setText(temp_c)
        except Exception:
            pass

        idx = 0
        if plugged == "4":
            idx = 1
        elif plugged == "2":
            idx = 2
        elif plugged == "1":
            idx = 3
        try:
            self.combo_plug.setCurrentIndex(idx)
        except Exception:
            pass

    def _apply_level(self):
        v = (self.edt_level.text() or "").strip()
        if not v or not v.isdigit():
            self._toast("提示", "请输入 0-100 的电量")
            return
        n = int(v)
        if n < 0 or n > 100:
            self._toast("提示", "电量范围 0-100")
            return
        self._shell("dumpsys battery set level " + str(n), timeout=8)
        self._toast("完成", "已设置电量")

    def _apply_temp(self):
        v = (self.edt_temp.text() or "").strip()
        if not v:
            self._toast("提示", "请输入温度")
            return
        try:
            c = float(v)
        except Exception:
            self._toast("提示", "温度应为数字")
            return
        t = int(round(c * 10.0))
        self._shell("dumpsys battery set temperature " + str(t), timeout=8)
        self._toast("完成", "已设置温度")

    def _apply_plug(self):
        idx = 0
        try:
            idx = int(self.combo_plug.currentIndex())
        except Exception:
            idx = 0

        # dumpsys battery set plugged: 0 none, 1 ac, 2 usb, 4 wireless
        plugged = "0"
        if idx == 1:
            plugged = "4"
        elif idx == 2:
            plugged = "2"
        elif idx == 3:
            plugged = "1"
        self._shell("dumpsys battery set ac 0", timeout=6)
        self._shell("dumpsys battery set usb 0", timeout=6)
        self._shell("dumpsys battery set wireless 0", timeout=6)
        if plugged == "1":
            self._shell("dumpsys battery set ac 1", timeout=6)
        elif plugged == "2":
            self._shell("dumpsys battery set usb 1", timeout=6)
        elif plugged == "4":
            self._shell("dumpsys battery set wireless 1", timeout=6)
        self._shell("dumpsys battery set plugged " + plugged, timeout=6)
        self._toast("完成", "已设置充电状态")

    def _reset(self):
        out = self._shell("dumpsys battery reset", timeout=10)
        self._refresh()
        self._toast("完成", (out or "已重置").strip() or "已重置")
