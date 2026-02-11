from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QThread, QTimer, QSettings, Qt
import webbrowser
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
        self._init_queue = []
        self._init_queue_i = 0
        self._closing = False
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
        # Defer heavy tab construction to after window creation to avoid UI freeze.
        # Pages will be created incrementally to keep the event loop responsive.
        try:
            QTimer.singleShot(0, self._init_pages_async)
        except Exception:
            try:
                self._init_pages_async()
            except Exception:
                pass
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

    def _init_pages_async(self):
        try:
            self._init_queue = [
                ("info_tab", DeviceInfoTab, "device_info", FluentIcon.INFO, "设备信息", NavigationItemPosition.TOP),
                ("flash_tab", FlashTab, "flash", getattr(FluentIcon, "COMMAND_PROMPT", FluentIcon.SEND), "刷机", NavigationItemPosition.TOP),
                ("root_tab", RootTab, "root", getattr(FluentIcon, "IOT", FluentIcon.INFO), "一键ROOT", NavigationItemPosition.TOP),
                ("scrcpy_tab", ScrcpyTab, "scrcpy", getattr(FluentIcon, "VIDEO", FluentIcon.PLAY), "投屏", NavigationItemPosition.TOP),
                ("software_tab", SoftwareManagerTab, "software_manager", getattr(FluentIcon, "APPLICATION", FluentIcon.BASKETBALL), "软件管理", NavigationItemPosition.TOP),
                ("file_tab", FileManagerTab, "file_manager", FluentIcon.FOLDER, "文件管理", NavigationItemPosition.TOP),
                ("backup_tab", BackupTab, "backup", getattr(FluentIcon, "SAVE", FluentIcon.FOLDER), "基带备份", NavigationItemPosition.TOP),
                ("misc_tab", MiscTab, "misc", getattr(FluentIcon, "TILES", FluentIcon.SETTING), "杂项", NavigationItemPosition.TOP),
                ("firmware_tab", FirmwareTab, "firmware", FluentIcon.DOWNLOAD, "固件下载", NavigationItemPosition.TOP),
                ("settings_tab", SettingsTab, "settings", FluentIcon.SETTING, "设置", NavigationItemPosition.BOTTOM),
            ]
            self._init_queue_i = 0
            self._init_pages_step()
        except Exception:
            pass

    def _init_pages_step(self):
        try:
            try:
                if getattr(self, '_closing', False):
                    return
            except Exception:
                pass
            if self._init_queue_i >= len(self._init_queue):
                try:
                    if getattr(self, 'info_tab', None) is not None:
                        self.navigationInterface.setCurrentItem(self.info_tab)
                except Exception:
                    pass
                return

            attr, ctor, obj_name, icon, title, pos = self._init_queue[self._init_queue_i]
            self._init_queue_i += 1

            w = ctor()
            try:
                w.setObjectName(obj_name)
            except Exception:
                pass
            try:
                setattr(self, attr, w)
            except Exception:
                pass

            try:
                if pos == NavigationItemPosition.BOTTOM:
                    self.addSubInterface(w, icon, title, position=NavigationItemPosition.BOTTOM)
                else:
                    self.addSubInterface(w, icon, title)
            except Exception:
                try:
                    self.addSubInterface(w, icon, title)
                except Exception:
                    pass

            try:
                QTimer.singleShot(0, self._init_pages_step)
            except Exception:
                self._init_pages_step()
        except Exception:
            pass

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
        try:
            self._closing = True
        except Exception:
            pass
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
