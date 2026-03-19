from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QSlider, QLabel

from qfluentwidgets import CardWidget, TitleLabel, CaptionLabel, BodyLabel, PushButton, PrimaryPushButton, InfoBar, InfoBarPosition

from app.services import adb_service as svc


class _AnimationScaleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("动画速度")
        self.resize(900, 520)

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
        h.addWidget(TitleLabel("动画速度", header))
        h.addWidget(CaptionLabel("读取/修改 window_animation_scale / transition_animation_scale / animator_duration_scale（建议 0-5）", header))
        lay.addWidget(header)

        card = CardWidget(self)
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 12, 16, 12)
        c.setSpacing(10)

        self.lbl_win = QLabel("-", card)
        self.lbl_trans = QLabel("-", card)
        self.lbl_dur = QLabel("-", card)

        self.sld_win = QSlider(Qt.Horizontal, card)
        self.sld_trans = QSlider(Qt.Horizontal, card)
        self.sld_dur = QSlider(Qt.Horizontal, card)

        for s in (self.sld_win, self.sld_trans, self.sld_dur):
            # 0..500 -> 0.00..5.00
            s.setRange(0, 500)
            s.setSingleStep(10)
            s.setPageStep(25)
            s.setValue(100)
            try:
                s.setMinimumWidth(280)
            except Exception:
                pass

        for l in (self.lbl_win, self.lbl_trans, self.lbl_dur):
            try:
                l.setMinimumWidth(68)
                l.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            except Exception:
                pass

        self.sld_win.valueChanged.connect(lambda v: self._set_lbl(self.lbl_win, v))
        self.sld_trans.valueChanged.connect(lambda v: self._set_lbl(self.lbl_trans, v))
        self.sld_dur.valueChanged.connect(lambda v: self._set_lbl(self.lbl_dur, v))

        row1 = QHBoxLayout(); row1.setSpacing(8)
        row1.addWidget(BodyLabel("窗口缩放", card))
        row1.addStretch(1)
        row1.addWidget(self.lbl_win)
        row1.addWidget(self.sld_win)
        btn1 = PrimaryPushButton("应用", card)
        btn1.clicked.connect(lambda: self._apply_one("window_animation_scale", float(self.sld_win.value()) / 100.0))
        row1.addWidget(btn1)
        c.addLayout(row1)

        row2 = QHBoxLayout(); row2.setSpacing(8)
        row2.addWidget(BodyLabel("过渡缩放", card))
        row2.addStretch(1)
        row2.addWidget(self.lbl_trans)
        row2.addWidget(self.sld_trans)
        btn2 = PrimaryPushButton("应用", card)
        btn2.clicked.connect(lambda: self._apply_one("transition_animation_scale", float(self.sld_trans.value()) / 100.0))
        row2.addWidget(btn2)
        c.addLayout(row2)

        row3 = QHBoxLayout(); row3.setSpacing(8)
        row3.addWidget(BodyLabel("动画时长", card))
        row3.addStretch(1)
        row3.addWidget(self.lbl_dur)
        row3.addWidget(self.sld_dur)
        btn3 = PrimaryPushButton("应用", card)
        btn3.clicked.connect(lambda: self._apply_one("animator_duration_scale", float(self.sld_dur.value()) / 100.0))
        row3.addWidget(btn3)
        c.addLayout(row3)

        row_actions = QHBoxLayout(); row_actions.setSpacing(8)
        row_actions.addStretch(1)
        btn_refresh = PushButton("刷新当前值", card)
        btn_refresh.clicked.connect(self._refresh)
        row_actions.addWidget(btn_refresh)
        btn_reset = PushButton("重置", card)
        btn_reset.clicked.connect(self._reset)
        row_actions.addWidget(btn_reset)
        c.addLayout(row_actions)

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

    def _set_lbl(self, lbl: QLabel, v: int):
        try:
            lbl.setText(f"{v/100.0:.2f}")
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

    def _get(self, key: str) -> str:
        return (self._shell(f"settings get global {key}", timeout=6) or "").strip()

    def _refresh(self):
        if not self._get_serial():
            self._toast('warn', "提示", "未检测到设备")
            return
        try:
            w = float(self._get("window_animation_scale") or "1")
            t = float(self._get("transition_animation_scale") or "1")
            d = float(self._get("animator_duration_scale") or "1")
            wv = int(round(max(0.0, min(5.0, w)) * 100))
            tv = int(round(max(0.0, min(5.0, t)) * 100))
            dv = int(round(max(0.0, min(5.0, d)) * 100))
            for s, v in ((self.sld_win, wv), (self.sld_trans, tv), (self.sld_dur, dv)):
                s.blockSignals(True)
                s.setValue(v)
                s.blockSignals(False)
            self._set_lbl(self.lbl_win, wv)
            self._set_lbl(self.lbl_trans, tv)
            self._set_lbl(self.lbl_dur, dv)
        except Exception:
            pass

    def _apply_one(self, key: str, f: float):
        if f < 0 or f > 5.0:
            self._toast('warn', "提示", "范围 0-5")
            return
        out = self._shell(f"settings put global {key} {f}", timeout=8)
        if out and "Permission" in out:
            self._toast('err', "失败", "权限不足：部分系统需要 Root 或 Shizuku")
            return
        self._toast('ok', "完成", f"已设置：{f:.2f}")

    def _reset(self):
        self._shell("settings delete global window_animation_scale", timeout=8)
        self._shell("settings delete global transition_animation_scale", timeout=8)
        self._shell("settings delete global animator_duration_scale", timeout=8)
        self._refresh()
        self._toast('ok', "完成", "已重置")
