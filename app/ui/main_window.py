from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt

from app.widgets.device_info_tab import DeviceInfoTab
from app.widgets.firmware_tab import FirmwareTab
from app.widgets.flash_tab import FlashTab
from app.widgets.settings_tab import SettingsTab
from app.widgets.scrcpy_tab import ScrcpyTab
from app.widgets.misc_tab import MiscTab
from app.widgets.root_tab import RootTab
from app.ui.about import AboutDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("拖把工具箱")

        # Root container
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        # Top App Bar
        appbar = QWidget()
        appbar.setObjectName("appbar")
        bar = QHBoxLayout(appbar)
        bar.setContentsMargins(16, 10, 16, 10)
        title = QLabel("拖把工具箱")
        title.setProperty("heading", True)
        bar.addWidget(title)
        bar.addStretch(1)
        about_btn = QPushButton("关于")
        bar.addWidget(about_btn)
        about_btn.clicked.connect(self.show_about)

        # Tabs
        self.tabs = QTabWidget()
        self.device_info_tab = DeviceInfoTab()
        self.firmware_tab = FirmwareTab()
        self.flash_tab = FlashTab()
        self.scrcpy_tab = ScrcpyTab()
        self.root_tab = RootTab()
        self.misc_tab = MiscTab()

        self.tabs.addTab(self.device_info_tab, "设备信息")
        self.tabs.addTab(self.firmware_tab, "固件列表")
        self.tabs.addTab(self.flash_tab, "刷机")
        self.tabs.addTab(self.scrcpy_tab, "投屏")
        self.tabs.addTab(self.root_tab, "一键Root")
        self.tabs.addTab(self.misc_tab, "杂项")
        self.tabs.addTab(SettingsTab(self), "设置")

        root_layout.addWidget(appbar)
        root_layout.addWidget(self.tabs)
        self.setCentralWidget(root)

    def show_about(self):
        dlg = AboutDialog(self)
        dlg.exec()
