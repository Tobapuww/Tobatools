from pathlib import Path
import webbrowser

from PySide6.QtCore import QSettings, QThread, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, QApplication
)
from qfluentwidgets import (
    TitleLabel, PushButton, PrimaryPushButton, InfoBar, InfoBarPosition,
    FluentIcon, Theme, setTheme, MessageBox,
    SettingCardGroup, PushSettingCard, SettingCard, CaptionLabel, ComboBox, SmoothScrollArea
)

from app.ui.about import AboutDialog
from app.services.update_checker import UpdateCheckerWorker
from app.version import VERSION


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        try:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        except Exception:
            pass

        self._scroll = SmoothScrollArea(self)
        self._scroll.setWidgetResizable(True)
        try:
            self._scroll.setStyleSheet("QScrollArea {border: none; background: transparent;}")
        except Exception:
            pass
        layout.addWidget(self._scroll)

        container = QWidget()
        try:
            container.setStyleSheet("QWidget {background: transparent;}")
        except Exception:
            pass
        self._scroll.setWidget(container)

        content_layout = QVBoxLayout(container)
        try:
            content_layout.setContentsMargins(24, 24, 24, 24)
            content_layout.setSpacing(12)
        except Exception:
            pass

        # 顶部渐变 Banner（保持不变）
        from PySide6.QtWidgets import QWidget as _W
        banner_w = _W(self)
        try:
            banner_w.setFixedHeight(110)
        except Exception:
            pass
        # Banner 背景交由 Fluent 主题控制
        from PySide6.QtWidgets import QHBoxLayout as _H, QLabel as _L, QVBoxLayout as _V
        banner = _H(banner_w)
        banner.setContentsMargins(24, 18, 24, 18)
        banner.setSpacing(16)
        icon_lbl = _L("", banner_w)
        try:
            icon_lbl.setStyleSheet("background: transparent;")
            icon_lbl.setFixedSize(48, 48)
            icon_lbl.setAlignment(Qt.AlignCenter)
            try:
                _ico = FluentIcon.SETTING.icon()
                icon_lbl.setPixmap(_ico.pixmap(48, 48))
            except Exception:
                pass
        except Exception:
            pass
        title_col = _V(); title_col.setContentsMargins(0,0,0,0); title_col.setSpacing(4)
        t = _L("设置中心", banner_w)
        try:
            t.setStyleSheet("font-size: 22px; font-weight: 600;")
        except Exception:
            pass
        s = _L("主题、下载目录与工具检测", banner_w)
        try:
            s.setStyleSheet("font-size: 14px;")
        except Exception:
            pass
        title_col.addWidget(t); title_col.addWidget(s)
        banner.addWidget(icon_lbl); banner.addLayout(title_col); banner.addStretch(1)
        content_layout.addWidget(banner_w)

        # --- 外观设置 ---
        self.group_appearance = SettingCardGroup("外观", self)
        
        # 主题模式：使用 SettingCard + ComboBox
        self.card_theme = SettingCard(
            FluentIcon.BRUSH,
            "主题模式",
            "切换应用显示主题（浅色/深色/跟随系统）",
            self.group_appearance
        )
        self.combo_theme = ComboBox()
        self.combo_theme.addItems(["跟随系统", "浅色", "深色"])
        self.combo_theme.setMinimumWidth(120)
        self.combo_theme.currentIndexChanged.connect(self._on_theme_changed)
        
        # 将 ComboBox 添加到卡片右侧
        self.card_theme.hBoxLayout.addWidget(self.combo_theme)
        self.card_theme.hBoxLayout.addSpacing(16)
        
        self.group_appearance.addSettingCard(self.card_theme)
        content_layout.addWidget(self.group_appearance)

        # --- 下载设置 ---
        self.group_download = SettingCardGroup("下载", self)
        
        self.card_download = PushSettingCard(
            "修改",
            FluentIcon.DOWNLOAD,
            "下载目录",
            "设置文件下载和解压的默认保存路径",
            self.group_download
        )
        self.card_download.clicked.connect(self._pick_download_dir)
        self.group_download.addSettingCard(self.card_download)
        content_layout.addWidget(self.group_download)

        # --- 工具 ---
        self.group_tools = SettingCardGroup("工具", self)
        
        self.card_check_tools = PushSettingCard(
            "开始检测",
            FluentIcon.DEVELOPER_TOOLS if hasattr(FluentIcon, "DEVELOPER_TOOLS") else FluentIcon.toolbox,
            "工具检测",
            "检查 ADB、Fastboot、7z 等依赖工具是否就绪",
            self.group_tools
        )
        self.card_check_tools.clicked.connect(self._check_bin)
        self.group_tools.addSettingCard(self.card_check_tools)
        content_layout.addWidget(self.group_tools)

        # --- 关于 ---
        self.group_about = SettingCardGroup("关于", self)
        
        self.card_about = PushSettingCard(
            "查看",
            FluentIcon.INFO,
            "应用信息",
            f"当前版本: {VERSION}",
            self.group_about
        )
        self.card_about.clicked.connect(self._show_about)

        self.card_update = PushSettingCard(
            "检查",
            FluentIcon.SYNC if hasattr(FluentIcon, "SYNC") else FluentIcon.UPDATE,
            "检查更新",
            "从云端获取最新版本信息",
            self.group_about
        )
        self.card_update.clicked.connect(self._check_update)

        self.card_repo = PushSettingCard(
            "打开",
            FluentIcon.GITHUB if hasattr(FluentIcon, "GITHUB") else FluentIcon.LINK,
            "拖把工具箱GitHub开源仓库",
            "https://github.com/Tobapuww/Tobatools",
            self.group_about
        )
        self.card_repo.clicked.connect(lambda: self._open_url("https://github.com/Tobapuww/Tobatools"))

        self.card_qq_group = PushSettingCard(
            "加入",
            FluentIcon.CHAT if hasattr(FluentIcon, "CHAT") else FluentIcon.MESSAGE,
            "拖把工具箱官方QQ群",
            "294122499",
            self.group_about
        )
        self.card_qq_group.clicked.connect(lambda: self._open_url("https://qm.qq.com/q/iBPCO3Xrjy"))

        self.card_tg_group = PushSettingCard(
            "加入",
            FluentIcon.SEND if hasattr(FluentIcon, "SEND") else FluentIcon.LINK,
            "拖把工具箱Telegram频道",
            "官方TG频道",
            self.group_about
        )
        self.card_tg_group.clicked.connect(lambda: self._open_url("https://t.me/tuoba384076676"))
        
        self.group_about.addSettingCard(self.card_about)
        self.group_about.addSettingCard(self.card_update)
        self.group_about.addSettingCard(self.card_repo)
        self.group_about.addSettingCard(self.card_qq_group)
        self.group_about.addSettingCard(self.card_tg_group)
        content_layout.addWidget(self.group_about)

        content_layout.addStretch(1)

        # Load Settings
        self._load_settings()

    def _load_settings(self):
        settings = QSettings()
        
        # 1. Update URL migration logic (kept from original)
        try:
            cur_upd = settings.value("update/url", "") or ""
            if "Resilience" in cur_upd and "/.github/workflows/boxver" in cur_upd:
                cur_upd = "https://gitee.com/AQ16/Resilience/raw/Mellifluous/.github/workflows/boxver"
                settings.setValue("update/url", cur_upd)
            if not cur_upd:
                settings.setValue(
                    "update/url",
                    "https://gitee.com/AQ16/Resilience/raw/Mellifluous/.github/workflows/boxver"
                )
        except Exception:
            pass

        # 2. Theme
        mode = settings.value("theme/mode", "system")
        if mode == "light":
            self.combo_theme.setCurrentIndex(1)
        elif mode == "dark":
            self.combo_theme.setCurrentIndex(2)
        else:
            self.combo_theme.setCurrentIndex(0)

        # 3. Download Dir
        dl_dir = settings.value("download/dir", "") or ""
        if not dl_dir:
            dl_dir = "未设置"
        self.card_download.setContent(str(dl_dir))

    def _on_theme_changed(self, index):
        modes = {0: "system", 1: "light", 2: "dark"}
        mode = modes.get(index, "system")
        
        settings = QSettings()
        settings.setValue("theme/mode", mode)
        
        # Apply theme
        if mode == "light":
            setTheme(Theme.LIGHT)
        elif mode == "dark":
            setTheme(Theme.DARK)
        else:
            try:
                auto = getattr(Theme, "AUTO", Theme.LIGHT)
                setTheme(auto)
            except Exception:
                setTheme(Theme.LIGHT)
        # 同步字体/对比度覆盖
        from app.ui.theme import apply_runtime_overlay
        app = QApplication.instance()
        if app is not None:
            apply_runtime_overlay(app, fallback_dark=(mode == "dark"))

    def _pick_download_dir(self):
        current = self.card_download.contentLabel.text()
        if current == "未设置":
            current = ""
        path = QFileDialog.getExistingDirectory(self, "选择下载目录", current)
        if path:
            settings = QSettings()
            settings.setValue("download/dir", path)
            self.card_download.setContent(path)
            InfoBar.success("已保存", f"下载目录已更新", parent=self, position=InfoBarPosition.TOP, isClosable=True)

    def _check_bin(self):
        base = Path(__file__).resolve().parents[2]
        candidates = [base / 'bin', Path.cwd() / 'bin']
        names = {
            'adb': ['adb.exe', 'adb'],
            'fastboot': ['fastboot.exe', 'fastboot'],
            '7z': ['7z.exe', '7za.exe', '7z'],
            'payload-dumper': ['payload-dumper-go.exe', 'payload-dumper.exe', 'payload-dumper-go']
        }
        found = {}
        for tool, files in names.items():
            ok = False
            for folder in candidates:
                for fn in files:
                    if (folder / fn).exists():
                        ok = True
                        break
                if ok:
                    break
            found[tool] = ok
        missing = [k for k, v in found.items() if not v]
        if not missing:
            InfoBar.success("检测完成", "所有工具已就绪", parent=self, position=InfoBarPosition.TOP, isClosable=True)
        else:
            InfoBar.warning("缺少工具", "未找到：" + ", ".join(missing), parent=self, position=InfoBarPosition.TOP, isClosable=True)

    def _show_about(self):
        dlg = AboutDialog(self)
        dlg.exec()

    def _open_url(self, url: str):
        try:
            webbrowser.open(url)
        except Exception:
            InfoBar.error("打开失败", "无法打开链接，请手动复制到浏览器访问", parent=self, position=InfoBarPosition.TOP, isClosable=True)

    def _check_update(self):
        settings = QSettings()
        url = settings.value("update/url", "") or ""
        self._upd_thread = QThread(self)
        self._upd_worker = UpdateCheckerWorker(url, VERSION)
        self._upd_worker.moveToThread(self._upd_thread)
        self._upd_thread.started.connect(self._upd_worker.run)
        self._upd_worker.finished.connect(self._on_update_finished)
        self._upd_worker.finished.connect(self._upd_thread.quit)
        self._upd_worker.finished.connect(self._upd_worker.deleteLater)
        self._upd_thread.finished.connect(self._upd_thread.deleteLater)
        InfoBar.info("检查更新", "正在从云端查询…", parent=self, position=InfoBarPosition.TOP, isClosable=True)
        self._upd_thread.start()

    def _on_update_finished(self, info: dict, err: str):
        if err:
            InfoBar.error("检查失败", err, parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        latest = str(info.get("version", "")).strip()
        notes = info.get("notes", "") or ""
        download = info.get("url", "") or ""
        cur = str(VERSION)
        if latest and latest > cur:
            msg = f"发现新版本：{latest}\n当前版本：{cur}"
            if notes:
                msg += f"\n\n更新内容：\n{notes}"
            box = MessageBox("发现更新", msg, self)
            try:
                box.yesButton.setText("去下载" if download else "确定")
                box.cancelButton.setText("取消")
            except Exception:
                pass
            if box.exec():
                if download:
                    try:
                        webbrowser.open(download)
                    except Exception:
                        pass
        else:
            InfoBar.success("已是最新", f"当前版本：{cur}", parent=self, position=InfoBarPosition.TOP, isClosable=True)

    def cleanup(self):
        try:
            t = getattr(self, '_upd_thread', None)
            if t is not None and t.isRunning():
                try: t.quit(); t.wait(1500)
                except: pass
        except Exception:
            pass
