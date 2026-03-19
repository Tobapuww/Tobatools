from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QSlider, QLabel

from qfluentwidgets import CardWidget, TitleLabel, CaptionLabel, BodyLabel, PushButton, PrimaryPushButton, InfoBar, InfoBarPosition

from app.services import adb_service as svc


class _FontScaleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("字体调节")
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
        h.addWidget(TitleLabel("字体调节", header))
        h.addWidget(CaptionLabel("读取/修改 font_scale（建议 0.85 - 2.0，最大允许 5.0）", header))
        lay.addWidget(header)

        card = CardWidget(self)
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 12, 16, 12)
        c.setSpacing(10)

        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(BodyLabel("字体缩放倍数", card))
        row.addStretch(1)
        self.lbl_scale = QLabel("-", card)
        try:
            self.lbl_scale.setMinimumWidth(68)
            self.lbl_scale.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        except Exception:
            pass
        row.addWidget(self.lbl_scale)

        self.slider = QSlider(Qt.Horizontal, card)
        # 50..500 -> 0.50..5.00
        self.slider.setRange(50, 500)
        self.slider.setSingleStep(5)
        self.slider.setPageStep(10)
        self.slider.setValue(100)
        try:
            self.slider.setMinimumWidth(260)
        except Exception:
            pass
        self.slider.valueChanged.connect(self._on_slider_changed)
        row.addWidget(self.slider)
        btn_apply = PrimaryPushButton("应用", card)
        btn_apply.clicked.connect(self._apply)
        row.addWidget(btn_apply)
        c.addLayout(row)

        row2 = QHBoxLayout(); row2.setSpacing(8)
        row2.addStretch(1)
        btn_refresh = PushButton("刷新当前值", card)
        btn_refresh.clicked.connect(self._refresh)
        row2.addWidget(btn_refresh)
        btn_reset = PushButton("重置", card)
        btn_reset.clicked.connect(self._reset)
        row2.addWidget(btn_reset)
        c.addLayout(row2)

        lay.addWidget(card)

        self._refresh()

    def _toast(self, kind: str, title: str, content: str, ms: int = 2400):
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

    def _on_slider_changed(self, v: int):
        try:
            self.lbl_scale.setText(f"{v/100.0:.2f}")
        except Exception:
            pass

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
            self._toast('warn', "提示", "未检测到设备")
            return
        out = (self._shell("settings get system font_scale", timeout=6) or "").strip()
        try:
            f = float(out) if out else 1.0
            v = int(round(max(0.5, min(5.0, f)) * 100))
            self.slider.blockSignals(True)
            self.slider.setValue(v)
            self.slider.blockSignals(False)
            self._on_slider_changed(v)
        except Exception:
            pass

    def _apply(self):
        try:
            f = float(self.slider.value()) / 100.0
        except Exception:
            self._toast('warn', "提示", "数值无效")
            return
        out = self._shell(f"settings put system font_scale {f}", timeout=8)
        if out and "Permission" in out:
            self._toast('err', "失败", "权限不足：部分系统需要 Root 或 Shizuku")
            return
        self._toast('ok', "完成", f"已设置字体缩放：{f:.2f}")

    def _reset(self):
        out = self._shell("settings delete system font_scale", timeout=8)
        _ = out
        self._refresh()
        self._toast('ok', "完成", "已重置")
