from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout

from qfluentwidgets import CardWidget, TitleLabel, CaptionLabel, BodyLabel, LineEdit, PushButton, PrimaryPushButton, MessageDialog

from app.services import adb_service as svc


class _DisplayTweaksDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("显示属性修改")
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
        header_lay.addWidget(TitleLabel("显示属性修改", header))
        header_lay.addWidget(CaptionLabel("读取并修改分辨率 / 密度DPI / 最小宽度DP（部分ROM可能不支持最小宽度项）", header))
        lay.addWidget(header)

        self.card = CardWidget(self)
        c_lay = QVBoxLayout(self.card)
        c_lay.setContentsMargins(16, 12, 16, 12)
        c_lay.setSpacing(10)

        # resolution
        row_res = QHBoxLayout(); row_res.setSpacing(8)
        row_res.addWidget(BodyLabel("分辨率 (例如 1080x2400)", self.card))
        row_res.addStretch(1)
        self.edt_res = LineEdit(self.card)
        self.edt_res.setPlaceholderText("留空表示不修改")
        self.edt_res.setMinimumWidth(220)
        row_res.addWidget(self.edt_res)
        btn_res = PrimaryPushButton("应用", self.card)
        btn_res.clicked.connect(self._apply_resolution)
        row_res.addWidget(btn_res)
        c_lay.addLayout(row_res)

        # density
        row_den = QHBoxLayout(); row_den.setSpacing(8)
        row_den.addWidget(BodyLabel("密度DPI (例如 420)", self.card))
        row_den.addStretch(1)
        self.edt_density = LineEdit(self.card)
        self.edt_density.setPlaceholderText("留空表示不修改")
        self.edt_density.setMinimumWidth(220)
        row_den.addWidget(self.edt_density)
        btn_den = PrimaryPushButton("应用", self.card)
        btn_den.clicked.connect(self._apply_density)
        row_den.addWidget(btn_den)
        c_lay.addLayout(row_den)

        # smallest width dp
        row_sw = QHBoxLayout(); row_sw.setSpacing(8)
        row_sw.addWidget(BodyLabel("最小宽度DP (例如 411)", self.card))
        row_sw.addStretch(1)
        self.edt_sw = LineEdit(self.card)
        self.edt_sw.setPlaceholderText("留空表示不修改")
        self.edt_sw.setMinimumWidth(220)
        row_sw.addWidget(self.edt_sw)
        btn_sw = PrimaryPushButton("应用", self.card)
        btn_sw.clicked.connect(self._apply_smallest_width)
        row_sw.addWidget(btn_sw)
        c_lay.addLayout(row_sw)

        # actions
        row_actions = QHBoxLayout(); row_actions.setSpacing(8)
        row_actions.addStretch(1)
        btn_refresh = PushButton("刷新当前值", self.card)
        btn_refresh.clicked.connect(self._refresh)
        row_actions.addWidget(btn_refresh)
        btn_reset = PushButton("重置(WM)", self.card)
        btn_reset.clicked.connect(self._reset_wm)
        row_actions.addWidget(btn_reset)
        c_lay.addLayout(row_actions)

        lay.addWidget(self.card)

        self._refresh()

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

    def _toast(self, title: str, content: str):
        MessageDialog(title, content, self).exec()

    def _refresh(self):
        serial = self._get_serial()
        if not serial:
            self._toast("提示", "未检测到设备")
            return

        out_size = self._shell("wm size", timeout=6)
        out_den = self._shell("wm density", timeout=6)
        sw = self._shell("settings get secure smallest_width", timeout=6).strip()

        # parse wm size
        res = ""
        for line in (out_size or "").splitlines():
            t = (line or "").strip()
            if "Physical size:" in t:
                res = t.split("Physical size:", 1)[1].strip()
                break
            if t.lower().startswith("physical size:"):
                res = t.split(":", 1)[1].strip()
                break
        if not res:
            for line in (out_size or "").splitlines():
                t = (line or "").strip()
                if "Override size:" in t:
                    res = t.split("Override size:", 1)[1].strip()
                    break

        # parse wm density
        dpi = ""
        for line in (out_den or "").splitlines():
            t = (line or "").strip()
            if "Physical density:" in t:
                dpi = t.split("Physical density:", 1)[1].strip()
                break
        if not dpi:
            for line in (out_den or "").splitlines():
                t = (line or "").strip()
                if "Override density:" in t:
                    dpi = t.split("Override density:", 1)[1].strip()
                    break

        try:
            self.edt_res.setText(res)
        except Exception:
            pass
        try:
            self.edt_density.setText(dpi)
        except Exception:
            pass
        try:
            self.edt_sw.setText(sw if sw and sw.lower() != "null" else "")
        except Exception:
            pass

    def _apply_resolution(self):
        val = (self.edt_res.text() or "").strip()
        if not val:
            self._toast("提示", "分辨率为空")
            return
        if "x" not in val:
            self._toast("提示", "分辨率格式应类似 1080x2400")
            return
        out = self._shell(f"wm size {val}", timeout=10)
        self._toast("完成", (out or "已应用分辨率").strip() or "已应用分辨率")

    def _apply_density(self):
        val = (self.edt_density.text() or "").strip()
        if not val:
            self._toast("提示", "密度为空")
            return
        if not val.isdigit():
            self._toast("提示", "密度应为数字")
            return
        out = self._shell(f"wm density {val}", timeout=10)
        self._toast("完成", (out or "已应用密度").strip() or "已应用密度")

    def _apply_smallest_width(self):
        val = (self.edt_sw.text() or "").strip()
        if not val:
            self._toast("提示", "最小宽度为空")
            return
        if not val.isdigit():
            self._toast("提示", "最小宽度应为数字")
            return
        out = self._shell(f"settings put secure smallest_width {val}", timeout=10)
        if out and "Permission" in out:
            self._toast("失败", "权限不足：部分系统需要 Root 或 Shizuku")
            return
        self._toast("完成", (out or "已应用最小宽度").strip() or "已应用最小宽度")

    def _reset_wm(self):
        out1 = self._shell("wm size reset", timeout=10)
        out2 = self._shell("wm density reset", timeout=10)
        self._refresh()
        msg = "已重置\n"
        if out1:
            msg += out1.strip() + "\n"
        if out2:
            msg += out2.strip() + "\n"
        self._toast("完成", msg.strip())
