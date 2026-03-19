from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout

from qfluentwidgets import CardWidget, TitleLabel, CaptionLabel, BodyLabel, PushButton, PrimaryPushButton, InfoBar, InfoBarPosition

from app.services import adb_service as svc


class _AccessibilityResetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("一键关闭辅助功能")
        self.resize(920, 520)

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
        h.addWidget(TitleLabel("一键关闭辅助功能/无障碍", header))
        h.addWidget(
            CaptionLabel(
                "用于紧急恢复：关闭 TalkBack、随选朗读、内容放大、色彩校正、颜色反转、高对比度文字等。\n"
                "仅支持关闭（best-effort），部分系统可能需要 Root/Shizuku 才能修改 secure 设置。",
                header,
            )
        )
        lay.addWidget(header)

        card = CardWidget(self)
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 12, 16, 12)
        c.setSpacing(10)

        c.addWidget(BodyLabel("一键执行以下操作（尽力而为）：", card))
        c.addWidget(BodyLabel("- 关闭无障碍总开关，并清空 enabled_accessibility_services", card))
        c.addWidget(BodyLabel("- 关闭：内容放大 / 颜色反转 / 色彩校正(色盲) / 高对比度文字", card))

        row = QHBoxLayout(); row.setSpacing(8)
        row.addStretch(1)
        btn_run = PrimaryPushButton("一键关闭", card)
        btn_run.clicked.connect(self._run)
        row.addWidget(btn_run)
        btn_refresh = PushButton("读取当前状态", card)
        btn_refresh.clicked.connect(self._refresh)
        row.addWidget(btn_refresh)
        c.addLayout(row)

        lay.addWidget(card)

        self._refresh()

    def _toast(self, kind: str, title: str, content: str, ms: int = 2600):
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

    def _shell(self, cmd: str, timeout: int = 10) -> str:
        serial = self._get_serial()
        if not serial:
            return ""
        return svc.adb_shell_serial(serial, cmd, timeout=timeout) or ""

    def _refresh(self):
        if not self._get_serial():
            self._toast('warn', '提示', '未检测到设备')
            return
        en = (self._shell("settings get secure accessibility_enabled", timeout=6) or "").strip()
        services = (self._shell("settings get secure enabled_accessibility_services", timeout=6) or "").strip()
        inv = (self._shell("settings get secure accessibility_display_inversion_enabled", timeout=6) or "").strip()
        dal = (self._shell("settings get secure accessibility_display_daltonizer_enabled", timeout=6) or "").strip()
        mag = (self._shell("settings get secure accessibility_display_magnification_enabled", timeout=6) or "").strip()
        hi = (self._shell("settings get secure high_text_contrast_enabled", timeout=6) or "").strip()

        msg = (
            f"无障碍开关: {en or '-'}\n"
            f"已启用服务: {services if services and services.lower() != 'null' else '(空)'}\n"
            f"颜色反转: {inv or '-'}  色彩校正: {dal or '-'}  内容放大: {mag or '-'}  高对比度: {hi or '-'}"
        )
        self._toast('info', '当前状态', msg, ms=4200)

    def _run(self):
        if not self._get_serial():
            self._toast('warn', '提示', '未检测到设备')
            return

        cmds = [
            "settings put secure accessibility_enabled 0",
            "settings put secure enabled_accessibility_services ''",
            "settings put secure accessibility_display_inversion_enabled 0",
            "settings put secure accessibility_display_daltonizer_enabled 0",
            "settings put secure accessibility_display_magnification_enabled 0",
            "settings put secure high_text_contrast_enabled 0",
            # some ROMs use these keys
            "settings put secure display_inversion_enabled 0",
            "settings put secure accessibility_display_daltonizer 0",
            "settings put secure accessibility_display_daltonizer_enabled 0",
        ]

        perm_denied = False
        for c in cmds:
            out = self._shell(c, timeout=8)
            if out and ("Permission" in out or "denied" in out.lower()):
                perm_denied = True

        if perm_denied:
            self._toast('warn', '已执行', '部分项目可能权限不足（可尝试 Root/Shizuku）')
        else:
            self._toast('ok', '完成', '已尝试关闭辅助功能')

        # post refresh
        self._refresh()
