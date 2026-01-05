from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QThread, QTimer, QSettings, Qt
import webbrowser
import os
import subprocess
import time
from qfluentwidgets import FluentWindow, NavigationItemPosition, FluentIcon, MessageBox

from app.widgets.flash_tab import FlashTab
from app.widgets.firmware_tab import FirmwareTab
from app.widgets.misc_tab import MiscTab
from app.widgets.root_tab import RootTab
from app.widgets.device_info_tab import DeviceInfoTab
from app.widgets.settings_tab import SettingsTab
from app.widgets.scrcpy_tab import ScrcpyTab
from app.widgets.software_manager_tab import SoftwareManagerTab
from app.services.update_checker import UpdateCheckerWorker
from app.version import VERSION
from app.widgets.file_manager_tab import FileManagerTab
from app.widgets.backup_tab import BackupTab


class FluentMainWindow(FluentWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._startup_upd_thread = None
        self._startup_upd_worker = None
        try:
            self.setWindowTitle("拖把工具箱")
        except Exception:
            pass
        # Windows 11: Mica; Windows 10: Acrylic（回退）。两者同时打开由系统自行选择可用材质
        try:
            self.setMicaEffectEnabled(True)
        except Exception:
            pass
        try:
            self.setAcrylicEffectEnabled(True)
        except Exception:
            pass
        try:
            self.setResizeEnabled(True)
        except Exception:
            pass
        try:
            self.setMinimumSize(1422, 822)
        except Exception:
            pass
        try:
            self.resize(877, 1422)
        except Exception:
            pass
        self._init_pages()
        # 让左侧导航也使用亚克力材质（Win11下配合 Mica 更统一）
        try:
            self.navigationInterface.setAcrylicEnabled(True)
        except Exception:
            pass
        # 尝试为自定义标题栏开启材质/透明
        try:
            self.setTitleBarTransparent(True)
        except Exception:
            pass
        try:
            tb = getattr(self, 'titleBar', None)
            if tb is not None:
                try:
                    tb.setAcrylicEnabled(True)
                except Exception:
                    pass
                try:
                    tb.setMicaEffectEnabled(True)
                except Exception:
                    pass
        except Exception:
            pass

        # 延迟到窗口显示后执行一次强制更新检查
        try:
            QTimer.singleShot(200, self._check_update_on_launch)
        except Exception:
            pass

        # 兜底：程序异常退出/未触发 closeEvent 时也要停掉启动更新线程
        try:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._on_about_to_quit)
        except Exception:
            pass

    def _on_about_to_quit(self):
        try:
            t = getattr(self, '_startup_upd_thread', None)
            if t is not None and t.isRunning():
                try:
                    t.quit()
                except Exception:
                    pass
                try:
                    t.wait(1500)
                except Exception:
                    pass
        except Exception:
            pass

    def _init_pages(self):
        self.flash_tab = FlashTab(); self.flash_tab.setObjectName("flash")
        self.firmware_tab = FirmwareTab(); self.firmware_tab.setObjectName("firmware")
        self.file_tab = FileManagerTab(); self.file_tab.setObjectName("file_manager")
        self.backup_tab = BackupTab(); self.backup_tab.setObjectName("backup")
        self.misc_tab = MiscTab(); self.misc_tab.setObjectName("misc")
        self.info_tab = DeviceInfoTab(); self.info_tab.setObjectName("device_info")
        self.settings_tab = SettingsTab(); self.settings_tab.setObjectName("settings")
        self.scrcpy_tab = ScrcpyTab(); self.scrcpy_tab.setObjectName("scrcpy")
        self.root_tab = RootTab(); self.root_tab.setObjectName("root")
        self.software_tab = SoftwareManagerTab(); self.software_tab.setObjectName("software_manager")

        # 从上到下：设备信息、刷机、投屏、杂项、设置
        self.addSubInterface(self.info_tab, FluentIcon.INFO, "设备信息")
        # 刷机使用命令提示符图标
        try:
            self.addSubInterface(self.flash_tab, FluentIcon.COMMAND_PROMPT, "刷机")
        except Exception:
            self.addSubInterface(self.flash_tab, FluentIcon.SEND, "刷机")
        # 一键ROOT 
        try:
            self.addSubInterface(self.root_tab, FluentIcon.IOT, "一键ROOT")
        except Exception:
            self.addSubInterface(self.root_tab, FluentIcon.INFO, "一键ROOT")
        # 投屏（scrcpy）
        try:
            self.addSubInterface(self.scrcpy_tab, FluentIcon.VIDEO, "投屏")
        except Exception:
            self.addSubInterface(self.scrcpy_tab, FluentIcon.PLAY, "投屏")
        # 软件管理
        try:
            self.addSubInterface(self.software_tab, FluentIcon.APPLICATION, "软件管理")
        except Exception:
            self.addSubInterface(self.software_tab, FluentIcon.BASKETBALL, "软件管理")
        # 文件管理（置于杂项上方）
        try:
            self.addSubInterface(self.file_tab, FluentIcon.FOLDER, "文件管理")
        except Exception:
            self.addSubInterface(self.file_tab, FluentIcon.FOLDER, "文件管理")
        # 备份还原
        try:
            self.addSubInterface(self.backup_tab, FluentIcon.SAVE, "基带备份")
        except Exception:
            self.addSubInterface(self.backup_tab, FluentIcon.FOLDER, "基带备份")
        # 杂项使用 Tiles 图标
        try:
            self.addSubInterface(self.misc_tab, FluentIcon.TILES, "杂项")
        except Exception:
            self.addSubInterface(self.misc_tab, FluentIcon.SETTING, "杂项")
        # 固件下载中心
        try:
            self.addSubInterface(self.firmware_tab, FluentIcon.DOWNLOAD, "固件下载")
        except Exception:
            self.addSubInterface(self.firmware_tab, FluentIcon.DOWNLOAD, "固件下载")
        # 设置放到底部
        self.addSubInterface(self.settings_tab, FluentIcon.SETTING, "设置", position=NavigationItemPosition.BOTTOM)

        # 其余页面保留在底部（仅设置）

        self.navigationInterface.setCurrentItem(self.info_tab)

    def _check_update_on_launch(self):
        try:
            settings = QSettings()
            url = settings.value("update/url", "") or ""
            if not url:
                return
            self._startup_upd_thread = QThread(self)
            self._startup_upd_worker = UpdateCheckerWorker(url, VERSION)
            self._startup_upd_worker.moveToThread(self._startup_upd_thread)
            self._startup_upd_thread.started.connect(self._startup_upd_worker.run)
            self._startup_upd_worker.finished.connect(self._on_startup_update_finished)
            self._startup_upd_worker.finished.connect(self._startup_upd_thread.quit)
            self._startup_upd_worker.finished.connect(self._startup_upd_worker.deleteLater)
            self._startup_upd_thread.finished.connect(self._startup_upd_thread.deleteLater)
            self._startup_upd_thread.start()
        except Exception:
            pass

    def _on_startup_update_finished(self, info: dict, err: str):
        try:
            if err:
                return
            latest = str(info.get("version", "")).strip()
            download = info.get("url", "") or ""
            notes = info.get("notes", "") or ""
            cur = str(VERSION)
            if latest and latest > cur:
                msg = f"发现新版本：{latest}\n当前版本：{cur}"
                if notes:
                    msg += f"\n\n更新内容：\n{notes}"
                box = MessageBox("发现更新", msg, self)
                try:
                    # 仅保留一个按钮，移除取消；禁止遮罩关闭
                    box.cancelButton.hide()
                    box.setClosableOnMaskClicked(False)
                    # 禁止窗口右上角关闭
                    box.setWindowFlag(Qt.WindowCloseButtonHint, False)
                except Exception:
                    pass
                if box.exec():  # 模态
                    if download:
                        try:
                            webbrowser.open(download)
                        except Exception:
                            pass
        except Exception:
            pass

    def closeEvent(self, event):
        for w in [
            getattr(self, 'flash_tab', None),
            getattr(self, 'firmware_tab', None),
            getattr(self, 'file_tab', None),
            getattr(self, 'backup_tab', None),
            getattr(self, 'misc_tab', None),
            getattr(self, 'root_tab', None),
            getattr(self, 'software_tab', None),
            getattr(self, 'info_tab', None),
            getattr(self, 'settings_tab', None),
        ]:
            try:
                if w and hasattr(w, 'cleanup'):
                    w.cleanup()
            except Exception:
                pass
        # 额外保险：在 Windows 上结束 adb/fastboot 以避免残留线程/控制台
        try:
            if os.name == 'nt':
                for exe in ('adb.exe', 'fastboot.exe'):
                    try:
                        subprocess.Popen([
                            'taskkill', '/F', '/T', '/IM', exe
                        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
                # 给子进程处理一点时间
                time.sleep(0.2)
        except Exception:
            pass
        # 清理启动更新线程
        try:
            t = getattr(self, '_startup_upd_thread', None)
            if t is not None and t.isRunning():
                try:
                    t.quit()
                except Exception:
                    pass
                try:
                    t.wait(1500)
                except Exception:
                    pass
        except Exception:
            pass
        return super().closeEvent(event)
