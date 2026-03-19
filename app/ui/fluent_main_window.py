from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QThread, QTimer, QSettings, Qt, Signal
import traceback
import webbrowser
from qfluentwidgets import FluentWindow, NavigationItemPosition, FluentIcon, MessageBox

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
    initialized = Signal()

    def __init__(self, parent: QWidget | None = None, *, eager_load: bool = True):
        super().__init__(parent)
        self._startup_upd_thread = None
        self._startup_upd_worker = None
        self._init_queue = []
        self._init_queue_i = 0
        self._closing = False
        self._eager_load = bool(eager_load)
        try:
            self.setWindowTitle("拖把工具箱")
        except Exception:
            pass
        # 监听导航切换事件，以便更新标题栏
        try:
            self.stackedWidget.currentChanged.connect(self._update_title)
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
        # Tabs init strategy:
        # - eager_load=True: build all tabs synchronously (splash will cover startup)
        # - eager_load=False: build incrementally to keep the event loop responsive
        try:
            if self._eager_load:
                self._init_pages_sync()
            else:
                QTimer.singleShot(0, self._init_pages_async)
        except Exception:
            traceback.print_exc()
            try:
                self.initialized.emit()
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
            traceback.print_exc()
            try:
                self.initialized.emit()
            except Exception:
                pass

    def _init_pages_sync(self):
        try:
            queue = [
                ("info_tab", DeviceInfoTab, "device_info", FluentIcon.INFO, "仪表盘", NavigationItemPosition.TOP),
                ("root_tab", RootTab, "root", getattr(FluentIcon, "IOT", FluentIcon.INFO), "Root 权限", NavigationItemPosition.TOP),
                ("scrcpy_tab", ScrcpyTab, "scrcpy", getattr(FluentIcon, "VIDEO", FluentIcon.PLAY), "投屏", NavigationItemPosition.TOP),
                ("software_tab", SoftwareManagerTab, "software_manager", getattr(FluentIcon, "APPLICATION", FluentIcon.BASKETBALL), "软件管理", NavigationItemPosition.TOP),
                ("file_tab", FileManagerTab, "file_manager", FluentIcon.FOLDER, "文件管理", NavigationItemPosition.TOP),
                ("backup_tab", BackupTab, "backup", getattr(FluentIcon, "SAVE", FluentIcon.FOLDER), "基带备份", NavigationItemPosition.TOP),
                ("misc_tab", MiscTab, "misc", getattr(FluentIcon, "TILES", FluentIcon.SETTING), "杂项工具箱", NavigationItemPosition.TOP),
                ("firmware_tab", FirmwareTab, "firmware", FluentIcon.DOWNLOAD, "固件下载", NavigationItemPosition.TOP),
                ("settings_tab", SettingsTab, "settings", FluentIcon.SETTING, "设置", NavigationItemPosition.BOTTOM),
            ]

            for attr, ctor, obj_name, icon, title, pos in queue:
                if getattr(self, '_closing', False):
                    break
                try:
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
                        traceback.print_exc()
                except Exception:
                    traceback.print_exc()

            try:
                if getattr(self, 'info_tab', None) is not None:
                    self.navigationInterface.setCurrentItem(self.info_tab)
                self._update_title()
            except Exception:
                traceback.print_exc()
        finally:
            try:
                self.initialized.emit()
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
                    traceback.print_exc()
                try:
                    self.initialized.emit()
                except Exception:
                    pass
                return

            attr, ctor, obj_name, icon, title, pos = self._init_queue[self._init_queue_i]
            self._init_queue_i += 1

            w = None
            try:
                w = ctor()
            except Exception:
                traceback.print_exc()

            if w is not None:
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
                    traceback.print_exc()

            try:
                QTimer.singleShot(0, self._init_pages_step)
            except Exception:
                self._init_pages_step()
        except Exception:
            traceback.print_exc()
            try:
                QTimer.singleShot(0, self._init_pages_step)
            except Exception:
                pass

    def _update_title(self, *args):
        try:
            # 获取当前选中的组件对象名称（即路由键）
            current_widget = self.stackedWidget.currentWidget()
            if not current_widget:
                return
                
            route_key = current_widget.objectName()
            
            # 由于 sync 模式下 self._init_queue 可能为空，我们需要重建一个查找表
            queue = getattr(self, '_init_queue', [])
            if not queue:
                queue = [
                    ("info_tab", None, "device_info", None, "仪表盘", None),
                    ("root_tab", None, "root", None, "Root 权限", None),
                    ("scrcpy_tab", None, "scrcpy", None, "投屏", None),
                    ("software_tab", None, "software_manager", None, "软件管理", None),
                    ("file_tab", None, "file_manager", None, "文件管理", None),
                    ("backup_tab", None, "backup", None, "基带备份", None),
                    ("misc_tab", None, "misc", None, "杂项工具箱", None),
                    ("firmware_tab", None, "firmware", None, "固件下载", None),
                    ("settings_tab", None, "settings", None, "设置", None),
                ]

            title = "拖把工具箱"
            for queue_item in queue:
                # 队列项格式: (attr, ctor, obj_name, icon, title, pos)
                if queue_item[2] == route_key:
                    title = f"拖把工具箱 - {queue_item[4]}"
                    break
            
            # 更新窗口原生的标题
            self.setWindowTitle(title)
            
            # 更新 QFluentWidgets 自定义标题栏的标题
            if hasattr(self, 'titleBar') and hasattr(self.titleBar, 'titleLabel'):
                self.titleBar.titleLabel.setText(title)
        except Exception:
            import traceback
            traceback.print_exc()

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
