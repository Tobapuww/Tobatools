import os
import subprocess
import datetime
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer, QSettings
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFileDialog,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
)

from qfluentwidgets import (
    CardWidget,
    PrimaryPushButton,
    PushButton,
    LineEdit,
    CheckBox,
    InfoBar,
    InfoBarPosition,
    FluentIcon,
    SmoothScrollArea,
    MessageBoxBase,
    SubtitleLabel,
    BodyLabel,
    ListWidget,
)

from app.services import adb_service


class _RiskConfirmDialog(MessageBoxBase):
    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(title, self)
        self.viewLayout.addWidget(self.titleLabel)

        self.textLabel = BodyLabel(text, self)
        try:
            self.textLabel.setWordWrap(True)
        except Exception:
            pass
        self.viewLayout.addWidget(self.textLabel)

        self._dont_remind = CheckBox("不再提醒", self)
        self.viewLayout.addWidget(self._dont_remind)

        try:
            self.yesButton.setText("继续")
            self.cancelButton.setText("取消")
        except Exception:
            pass

    def dont_remind(self) -> bool:
        try:
            return bool(self._dont_remind.isChecked())
        except Exception:
            return False


class _PackageInputDialog(MessageBoxBase):
    def __init__(self, title: str, label: str, default_text: str, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(title, self)
        self.viewLayout.addWidget(self.titleLabel)

        self.label = BodyLabel(label, self)
        self.viewLayout.addWidget(self.label)

        self.edit = LineEdit(self)
        try:
            self.edit.setText(default_text or "")
        except Exception:
            pass
        self.viewLayout.addWidget(self.edit)

        try:
            self.yesButton.setText("确定")
            self.cancelButton.setText("取消")
        except Exception:
            pass

    def text(self) -> str:
        try:
            return str(self.edit.text() or '').strip()
        except Exception:
            return ''


class _AdbCmdWorker(QObject):
    output = Signal(str)
    finished = Signal(int)

    def __init__(self, cmd: list[str]):
        super().__init__()
        self._cmd = cmd
        self._proc: subprocess.Popen | None = None
        self._stop = False

    def stop(self):
        self._stop = True
        try:
            if self._proc is not None:
                self._proc.terminate()
        except Exception:
            pass

    def run(self):
        code = -1
        try:
            popen_kwargs = {}
            try:
                if os.name == 'nt':
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    popen_kwargs = {'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW}
            except Exception:
                pass

            self.output.emit("启动命令: " + " ".join(self._cmd))
            self._proc = subprocess.Popen(
                self._cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                **popen_kwargs,
            )
            assert self._proc.stdout is not None
            for line in iter(self._proc.stdout.readline, ''):
                if self._stop:
                    break
                self.output.emit(line.rstrip('\r\n'))
            code = self._proc.wait()
        except FileNotFoundError:
            self.output.emit("未找到 adb，请确认 bin/adb.exe 存在或系统 PATH 已配置")
            code = -1
        except Exception as e:
            self.output.emit(f"ADB 执行异常: {e}")
            code = -1
        finally:
            self.finished.emit(code)


class _ForegroundWorker(QObject):
    result = Signal(str, str)  # pkg, act

    def __init__(self):
        super().__init__()
        self._busy = False

    def fetch(self, adb: str, serial: str):
        if self._busy:
            return
        self._busy = True
        pkg = ''
        act = ''
        try:
            # Try resumed activity first (Android 10+)
            try:
                r = subprocess.run(
                    [adb, '-s', serial, 'shell', 'dumpsys', 'activity', 'activities'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=3,
                )
                out = r.stdout or ""
                for line in out.splitlines():
                    s = line.strip()
                    if 'ResumedActivity' in s or 'mResumedActivity' in s:
                        parts = s.split()
                        for p in parts:
                            if '/' in p and '.' in p and p.count('/') == 1:
                                act = p.strip('}').strip()
                                if act.startswith('u0'):
                                    continue
                                break
                        break
            except Exception:
                pass

            if act and '/' in act:
                pkg = act.split('/', 1)[0]

            if not pkg:
                # Fallback: window current focus
                try:
                    r = subprocess.run(
                        [adb, '-s', serial, 'shell', 'dumpsys', 'window', 'windows'],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        timeout=3,
                    )
                    out = r.stdout or ""
                    for line in out.splitlines():
                        s = line.strip()
                        if 'mCurrentFocus' in s or 'mFocusedApp' in s:
                            for tok in s.replace('{', ' ').replace('}', ' ').split():
                                if '/' in tok and '.' in tok:
                                    act = tok
                                    break
                            if act:
                                break
                except Exception:
                    pass
                if act and '/' in act:
                    pkg = act.split('/', 1)[0]
        finally:
            self._busy = False
            try:
                self.result.emit((pkg or '').strip(), (act or '').strip())
            except Exception:
                pass


class SoftwareManagerTab(QWidget):
    _fg_request = Signal(str, str)  # adb, serial

    def __init__(self):
        super().__init__()
        self._thread: QThread | None = None
        self._worker: _AdbCmdWorker | None = None
        self._pending_op_desc: str | None = None
        self._installing: bool = False

        self._fg_thread: QThread | None = None
        self._fg_worker: _ForegroundWorker | None = None

        self._apps_thread: QThread | None = None
        self._apps_worker: _AdbCmdWorker | None = None
        self._apps_out: list[str] = []

        self._disabled_thread: QThread | None = None
        self._disabled_worker: _AdbCmdWorker | None = None
        self._disabled_out: list[str] = []

        self._label_thread: QThread | None = None
        self._label_worker: _AdbCmdWorker | None = None
        self._label_out: list[str] = []
        self._label_pkg: str = ''
        self._label_cache: dict[str, str] = {}

        self._selected_apk: str = ""
        self._selected_pkg: str = ""
        self._current_pkg: str = ""
        self._current_activity: str = ""
        self._timer: QTimer | None = None

        self._build_ui()
        self._start_foreground_worker()
        self._start_foreground_timer()

        try:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.cleanup)
        except Exception:
            pass

    # -------- UI --------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        try:
            outer.setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass

        scroll = SmoothScrollArea(self)
        scroll.setWidgetResizable(True)
        try:
            scroll.setStyleSheet("QScrollArea {border: none; background: transparent;}")
        except Exception:
            pass
        outer.addWidget(scroll)

        container = QWidget()
        try:
            container.setStyleSheet("QWidget {background: transparent;}")
        except Exception:
            pass
        scroll.setWidget(container)

        lay = QVBoxLayout(container)
        try:
            lay.setContentsMargins(24, 24, 24, 24)
        except Exception:
            pass
        lay.setSpacing(12)

        # 顶部 Banner（与其他 Tab 风格一致）
        banner_w = QWidget(self)
        try:
            banner_w.setFixedHeight(110)
        except Exception:
            pass
        banner = QHBoxLayout(banner_w)
        banner.setContentsMargins(24, 18, 24, 18)
        banner.setSpacing(16)

        icon_lbl = QLabel("", banner_w)
        try:
            icon_lbl.setStyleSheet("background: transparent;")
            icon_lbl.setFixedSize(48, 48)
            icon_lbl.setAlignment(Qt.AlignCenter)
            try:
                _ico = FluentIcon.APPLICATION.icon()
                icon_lbl.setPixmap(_ico.pixmap(48, 48))
            except Exception:
                pass
        except Exception:
            pass

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        title = QLabel("软件管理", banner_w)
        try:
            title.setStyleSheet("font-size: 22px; font-weight: 600;")
        except Exception:
            pass
        sub = QLabel("安装 APK / 启动或冻结 / 导出 APK", banner_w)
        try:
            sub.setStyleSheet("font-size: 14px;")
        except Exception:
            pass
        title_col.addWidget(title)
        title_col.addWidget(sub)

        banner.addWidget(icon_lbl)
        banner.addLayout(title_col)
        banner.addStretch(1)
        lay.addWidget(banner_w)

        body_row = QHBoxLayout()
        body_row.setSpacing(12)

        # 左侧：已安装应用列表
        card_apps = CardWidget(container)
        v_apps = QVBoxLayout(card_apps)
        v_apps.setContentsMargins(16, 16, 16, 16)
        v_apps.setSpacing(10)

        h_apps = QHBoxLayout(); h_apps.setSpacing(8)
        icon_apps = QLabel("")
        try:
            icon_apps.setFixedSize(16, 16)
            icon_apps.setPixmap(FluentIcon.APPLICATION.icon().pixmap(16, 16))
        except Exception:
            pass
        h_apps.addWidget(icon_apps)
        h_apps.addWidget(QLabel("已安装应用"))
        h_apps.addStretch(1)
        self.btn_clear_selected = PushButton("清除选中", card_apps)
        try:
            self.btn_clear_selected.setIcon(FluentIcon.CLEAR_SELECTION)
        except Exception:
            pass
        h_apps.addWidget(self.btn_clear_selected)
        self.btn_refresh_apps = PushButton("刷新", card_apps)
        try:
            self.btn_refresh_apps.setIcon(FluentIcon.SYNC)
        except Exception:
            pass
        h_apps.addWidget(self.btn_refresh_apps)
        v_apps.addLayout(h_apps)

        self.edt_app_search = LineEdit(card_apps)
        try:
            self.edt_app_search.setPlaceholderText("搜索包名…")
        except Exception:
            pass
        v_apps.addWidget(self.edt_app_search)

        self.cb_show_system_apps = CheckBox("显示系统应用", card_apps)
        v_apps.addWidget(self.cb_show_system_apps)

        # Prefer Fluent ListWidget for modern look
        try:
            self.list_apps = ListWidget(card_apps)
        except Exception:
            self.list_apps = QListWidget(card_apps)
        try:
            self.list_apps.setMinimumWidth(360)
            # 强化高亮样式（与 Fluent 主题配色尽量一致）
            self.list_apps.setStyleSheet(
                "QListWidget::item { padding: 6px 8px; }"
                "QListWidget::item:selected { background: rgba(42, 116, 218, 0.18); border-radius: 6px; }"
            )
        except Exception:
            pass
        v_apps.addWidget(self.list_apps)

        body_row.addWidget(card_apps, 4)

        # 右侧：设备/安装/操作
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        # 设备与前台应用信息（实时）
        card_state = CardWidget(container)
        v_state = QVBoxLayout(card_state)
        v_state.setContentsMargins(16, 16, 16, 16)
        v_state.setSpacing(10)

        h_state = QHBoxLayout(); h_state.setSpacing(8)
        icon_state = QLabel("")
        try:
            icon_state.setFixedSize(16, 16)
            icon_state.setPixmap(FluentIcon.INFO.icon().pixmap(16, 16))
        except Exception:
            pass
        h_state.addWidget(icon_state)
        h_state.addWidget(QLabel("当前前台信息"))
        h_state.addStretch(1)
        self.btn_refresh_state = PushButton("刷新", card_state)
        try:
            self.btn_refresh_state.setIcon(FluentIcon.SYNC)
        except Exception:
            pass
        h_state.addWidget(self.btn_refresh_state)
        v_state.addLayout(h_state)

        self.lbl_pkg = QLabel("前台包名：-")
        self.lbl_act = QLabel("当前Activity：-")
        self.lbl_dev = QLabel("设备：-")
        self.lbl_selected = QLabel("已选包名：-")
        for w in (self.lbl_pkg, self.lbl_act, self.lbl_dev, self.lbl_selected):
            w.setTextInteractionFlags(Qt.TextSelectableByMouse)
        try:
            # 前台信息字号略大，便于查看
            self.lbl_dev.setStyleSheet("font-size: 14px;")
            self.lbl_pkg.setStyleSheet("font-size: 14px;")
            self.lbl_act.setStyleSheet("font-size: 14px;")
            # 已选包名更醒目
            self.lbl_selected.setStyleSheet("font-size: 15px; font-weight: 600; color: #2A74DA;")
        except Exception:
            pass
        v_state.addWidget(self.lbl_dev)
        v_state.addWidget(self.lbl_selected)
        v_state.addWidget(self.lbl_pkg)
        v_state.addWidget(self.lbl_act)
        right_col.addWidget(card_state)

        # APK 安装（简化）
        card_apk = CardWidget(container)
        v_apk = QVBoxLayout(card_apk)
        v_apk.setContentsMargins(16, 16, 16, 16)
        v_apk.setSpacing(10)

        h_apk = QHBoxLayout(); h_apk.setSpacing(8)
        icon_apk = QLabel("")
        try:
            icon_apk.setFixedSize(16, 16)
            icon_apk.setPixmap(FluentIcon.DOWNLOAD.icon().pixmap(16, 16))
        except Exception:
            pass
        h_apk.addWidget(icon_apk)
        h_apk.addWidget(QLabel("安装 APK"))
        h_apk.addStretch(1)
        v_apk.addLayout(h_apk)

        row_install = QHBoxLayout(); row_install.setSpacing(8)
        self.cb_reinstall = CheckBox("覆盖安装(-r)", card_apk)
        self.btn_install = PrimaryPushButton("安装APK", card_apk)
        try:
            self.btn_install.setIcon(FluentIcon.FOLDER)
        except Exception:
            pass
        row_install.addWidget(self.cb_reinstall)
        row_install.addStretch(1)
        row_install.addWidget(self.btn_install)
        v_apk.addLayout(row_install)

        self.install_progress = QProgressBar(card_apk)
        try:
            # indeterminate
            self.install_progress.setRange(0, 0)
            self.install_progress.setTextVisible(True)
            self.install_progress.setFormat("正在安装…")
            self.install_progress.setVisible(False)
        except Exception:
            pass
        v_apk.addWidget(self.install_progress)
        right_col.addWidget(card_apk)

        # 基于当前包名的操作
        card_ops = CardWidget(container)
        v_ops = QVBoxLayout(card_ops)
        v_ops.setContentsMargins(16, 16, 16, 16)
        v_ops.setSpacing(10)

        h_ops = QHBoxLayout(); h_ops.setSpacing(8)
        icon_ops = QLabel("")
        try:
            icon_ops.setFixedSize(16, 16)
            icon_ops.setPixmap(FluentIcon.SETTING.icon().pixmap(16, 16))
        except Exception:
            pass
        h_ops.addWidget(icon_ops)
        h_ops.addWidget(QLabel("应用操作（基于选中包名，未选择时基于当前前台包名）"))
        h_ops.addStretch(1)
        v_ops.addLayout(h_ops)

        row_ops1 = QHBoxLayout(); row_ops1.setSpacing(8)
        self.btn_freeze = PushButton("冻结", card_ops)
        self.btn_unfreeze = PushButton("解冻", card_ops)
        self.btn_force_stop = PushButton("强行停止", card_ops)
        row_ops1.addWidget(self.btn_freeze)
        row_ops1.addWidget(self.btn_unfreeze)
        row_ops1.addWidget(self.btn_force_stop)
        row_ops1.addStretch(1)
        v_ops.addLayout(row_ops1)

        row_ops_perm = QHBoxLayout(); row_ops_perm.setSpacing(8)
        self.btn_open_permissions = PushButton("权限设置", card_ops)
        row_ops_perm.addWidget(self.btn_open_permissions)
        row_ops_perm.addStretch(1)
        v_ops.addLayout(row_ops_perm)

        row_ops2 = QHBoxLayout(); row_ops2.setSpacing(8)
        self.btn_uninstall = PushButton("卸载", card_ops)
        self.btn_uninstall_keep = PushButton("保留数据卸载", card_ops)
        self.btn_clear_data = PushButton("清除数据", card_ops)
        self.btn_pull_apk = PushButton("提取APK到电脑", card_ops)
        row_ops2.addWidget(self.btn_uninstall)
        row_ops2.addWidget(self.btn_uninstall_keep)
        row_ops2.addWidget(self.btn_clear_data)
        row_ops2.addWidget(self.btn_pull_apk)
        row_ops2.addStretch(1)
        v_ops.addLayout(row_ops2)

        row_ops3 = QHBoxLayout(); row_ops3.setSpacing(8)
        self.btn_disable_activity = PushButton("禁用当前Activity", card_ops)
        self.cb_root_disable_activity = CheckBox("使用root权限禁用", card_ops)
        row_ops3.addWidget(self.btn_disable_activity)
        row_ops3.addWidget(self.cb_root_disable_activity)
        row_ops3.addStretch(1)
        self.btn_open_oplog = PushButton("打开操作记录", card_ops)
        try:
            self.btn_open_oplog.setIcon(FluentIcon.DOCUMENT)
        except Exception:
            pass
        row_ops3.addWidget(self.btn_open_oplog)
        v_ops.addLayout(row_ops3)

        note = QLabel("提示：冻结/解冻可能需要更高权限（部分系统需 root/设备管理员）。")
        note.setWordWrap(True)
        v_ops.addWidget(note)
        right_col.addWidget(card_ops)

        # 应用信息
        card_info = CardWidget(container)
        v_info = QVBoxLayout(card_info)
        v_info.setContentsMargins(16, 16, 16, 16)
        v_info.setSpacing(10)
        h_dis = QHBoxLayout(); h_dis.setSpacing(8)
        h_dis.addWidget(QLabel("已禁用组件"))
        h_dis.addStretch(1)
        self.btn_refresh_disabled = PushButton("刷新禁用列表", card_info)
        h_dis.addWidget(self.btn_refresh_disabled)
        v_info.addLayout(h_dis)

        try:
            self.list_disabled = ListWidget(card_info)
        except Exception:
            self.list_disabled = QListWidget(card_info)
        try:
            self.list_disabled.setMinimumHeight(140)
        except Exception:
            pass
        v_info.addWidget(self.list_disabled)

        row_enable = QHBoxLayout(); row_enable.setSpacing(8)
        self.edt_component = LineEdit(card_info)
        try:
            self.edt_component.setPlaceholderText("输入组件：包名/类名 或 直接从列表选择")
        except Exception:
            pass
        self.btn_enable_component = PushButton("恢复组件(pm enable)", card_info)
        row_enable.addWidget(self.edt_component)
        row_enable.addWidget(self.btn_enable_component)
        v_info.addLayout(row_enable)

        right_col.addWidget(card_info)

        right_col.addStretch(1)
        body_row.addLayout(right_col, 6)
        lay.addLayout(body_row)

        # signals
        self.btn_refresh_state.clicked.connect(self._refresh_foreground_now)
        self.btn_clear_selected.clicked.connect(self._clear_selected_pkg)
        self.btn_refresh_apps.clicked.connect(self._refresh_apps)
        self.edt_app_search.textChanged.connect(self._apply_app_filter)
        self.cb_show_system_apps.stateChanged.connect(self._refresh_apps)
        self.list_apps.itemSelectionChanged.connect(self._on_app_selected)
        self.btn_install.clicked.connect(self._install_apk)
        self.btn_freeze.clicked.connect(self._freeze_app)
        self.btn_unfreeze.clicked.connect(self._unfreeze_app)
        self.btn_uninstall.clicked.connect(self._uninstall_app)
        self.btn_force_stop.clicked.connect(self._force_stop_app)
        self.btn_uninstall_keep.clicked.connect(self._uninstall_keep_data)
        self.btn_clear_data.clicked.connect(self._clear_data)
        self.btn_pull_apk.clicked.connect(self._pull_apk)
        self.btn_open_oplog.clicked.connect(self._open_oplog)
        self.btn_disable_activity.clicked.connect(self._disable_current_activity)
        self.btn_open_permissions.clicked.connect(self._open_app_permissions)
        self.btn_refresh_disabled.clicked.connect(self._refresh_disabled_components)
        self.btn_enable_component.clicked.connect(self._enable_component)

    # -------- helpers --------
    def _noop(self, _s: str):
        return

    def _oplog_path(self) -> Path:
        root = Path(__file__).resolve().parents[2]
        logs_dir = root / 'logs'
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return logs_dir / 'software_ops.txt'

    def _write_oplog(self, serial: str, pkg: str, op: str):
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"{ts}\t{serial}\t{pkg}\t{op}\n"
        try:
            self._oplog_path().open('a', encoding='utf-8').write(line)
        except Exception:
            # fallback best-effort
            try:
                with self._oplog_path().open('a', encoding='utf-8', errors='ignore') as f:
                    f.write(line)
            except Exception:
                pass

    def _open_oplog(self):
        p = self._oplog_path()
        try:
            if not p.exists():
                p.write_text('', encoding='utf-8')
        except Exception:
            pass
        try:
            os.startfile(str(p))
            return
        except Exception:
            pass
        try:
            webbrowser.open(p.as_uri())
        except Exception:
            pass

    def _toast(self, kind: str, title: str, content: str, ms: int = 2500):
        try:
            if kind == 'ok':
                InfoBar.success(title, content, parent=self, position=InfoBarPosition.TOP, duration=ms, isClosable=True)
            elif kind == 'warn':
                InfoBar.warning(title, content, parent=self, position=InfoBarPosition.TOP, duration=ms, isClosable=True)
            else:
                InfoBar.info(title, content, parent=self, position=InfoBarPosition.TOP, duration=ms, isClosable=True)
        except Exception:
            pass

    def _confirm_risky(self, key: str, title: str, text: str) -> bool:
        try:
            settings = QSettings()
            if bool(settings.value(key, False)):
                return True
        except Exception:
            settings = None

        dlg = _RiskConfirmDialog(title, text, self)
        ok = bool(dlg.exec())
        if ok:
            try:
                if dlg.dont_remind() and settings is not None:
                    settings.setValue(key, True)
            except Exception:
                pass
        return ok

    def _pause_foreground_timer(self):
        try:
            if self._timer is not None and self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass

    def _resume_foreground_timer(self):
        try:
            if self._timer is not None and not self._timer.isActive():
                self._timer.start()
        except Exception:
            pass

    def _get_default_serial(self) -> str:
        serials: list[str] = []
        try:
            serials = adb_service.list_devices()
        except Exception:
            serials = []
        if not serials:
            return ''
        if len(serials) > 1:
            # 保持默认连接设备：多设备时不弹框，直接提示用户处理环境（关模拟器/拔掉多余设备）
            return ''
        return serials[0]

    def _resolve_adb(self) -> str:
        try:
            adb = adb_service.ADB_BIN
            if adb and adb.exists():
                return str(adb)
        except Exception:
            pass
        return 'adb'

    def _run_adb_cmd(self, args: list[str], op_desc: str | None = None):
        if self._thread and self._thread.isRunning():
            self._toast('info', '提示', '任务正在运行中，请稍后…')
            return

        serial = self._get_default_serial()
        if not serial:
            try:
                serials = adb_service.list_devices()
            except Exception:
                serials = []
            if not serials:
                self._toast('warn', '提示', '未检测到设备')
            else:
                self._toast('warn', '提示', f'检测到多个设备({len(serials)})，请仅保留一个设备后再操作')
            return

        adb = self._resolve_adb()
        cmd = [adb, '-s', serial] + args

        self._pause_foreground_timer()
        self._pending_op_desc = op_desc

        self._thread = QThread(self)
        self._worker = _AdbCmdWorker(cmd)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.output.connect(self._noop)
        self._worker.finished.connect(self._on_cmd_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_cmd_finished(self, code: int):
        # NOTE: must run in UI thread; connect to this QObject-bound slot
        try:
            title = '完成' if code == 0 else '失败'
            prefix = (self._pending_op_desc + ' - ') if self._pending_op_desc else ''
            self._toast('ok' if code == 0 else 'warn', title, f"{prefix}命令返回码: {code}")
        except Exception:
            pass
        try:
            # stop indeterminate progress for install
            if self._installing:
                self._set_installing(False)
        except Exception:
            pass

    def _set_installing(self, on: bool):
        self._installing = bool(on)
        try:
            if hasattr(self, 'install_progress') and self.install_progress is not None:
                self.install_progress.setVisible(self._installing)
        except Exception:
            pass
        try:
            if hasattr(self, 'btn_install') and self.btn_install is not None:
                self.btn_install.setEnabled(not self._installing)
        except Exception:
            pass
        try:
            if hasattr(self, 'cb_reinstall') and self.cb_reinstall is not None:
                self.cb_reinstall.setEnabled(not self._installing)
        except Exception:
            pass

    def _on_thread_finished(self):
        self._worker = None
        self._thread = None
        self._pending_op_desc = None
        self._resume_foreground_timer()

    # -------- actions --------
    def _install_apk(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 APK', '', 'APK (*.apk);;所有文件 (*.*)')
        if not path:
            return
        if not Path(path).exists():
            self._toast('warn', '提示', '选择的 APK 文件不存在')
            return
        self._selected_apk = path
        serial = self._get_default_serial()
        if not serial:
            try:
                serials = adb_service.list_devices()
            except Exception:
                serials = []
            if not serials:
                self._toast('warn', '提示', '未检测到设备')
            else:
                self._toast('warn', '提示', f'检测到多个设备({len(serials)})，请仅保留一个设备后再操作')
            return
        self._write_oplog(serial, '-', f"install {'-r' if self.cb_reinstall.isChecked() else ''} {Path(path).name}".strip())
        args = ['install']
        if self.cb_reinstall.isChecked():
            args.append('-r')
        args.append(path)
        self._set_installing(True)
        self._run_adb_cmd(args, op_desc='安装APK')

    def _pkg(self) -> str:
        s = (self._selected_pkg or '').strip()
        if s:
            return s
        return (self._current_pkg or '').strip()

    def _on_app_selected(self):
        try:
            items = self.list_apps.selectedItems() if self.list_apps else []
        except Exception:
            items = []
        if not items:
            self._selected_pkg = ''
            try:
                self.lbl_selected.setText('已选包名：-')
            except Exception:
                pass
            return
        pkg = ''
        try:
            pkg = str(items[0].data(Qt.UserRole) or '').strip()
        except Exception:
            pkg = ''
        if not pkg:
            pkg = str(items[0].text() or '').strip()
        self._selected_pkg = pkg
        try:
            self.lbl_selected.setText(f'已选包名：{pkg}')
        except Exception:
            pass
        try:
            # 选中后滚动到可见区域
            self.list_apps.scrollToItem(items[0])
        except Exception:
            pass

        # Lazy load label
        try:
            if pkg and pkg not in self._label_cache:
                self._fetch_label_for_pkg(pkg)
        except Exception:
            pass

    def _clear_selected_pkg(self):
        self._selected_pkg = ''
        try:
            if self.list_apps:
                self.list_apps.clearSelection()
        except Exception:
            pass
        try:
            self.lbl_selected.setText('已选包名：-')
        except Exception:
            pass
        # revert to foreground package for operations; clear component UI
        try:
            if self.list_disabled:
                self.list_disabled.clear()
        except Exception:
            pass
        try:
            if self.edt_component:
                self.edt_component.clear()
        except Exception:
            pass

    def _apply_app_filter(self):
        q = ''
        try:
            q = str(self.edt_app_search.text() or '').strip().lower()
        except Exception:
            q = ''
        try:
            for i in range(self.list_apps.count()):
                it = self.list_apps.item(i)
                # search both display text and raw package
                pkg = ''
                try:
                    pkg = str(it.data(Qt.UserRole) or '')
                except Exception:
                    pkg = ''
                txt = ((it.text() or '') + ' ' + pkg).lower()
                it.setHidden(bool(q) and q not in txt)
        except Exception:
            pass

    def _refresh_apps(self):
        if self._apps_thread and self._apps_thread.isRunning():
            self._toast('info', '提示', '正在刷新应用列表…')
            return
        serial = self._get_default_serial()
        if not serial:
            try:
                serials = adb_service.list_devices()
            except Exception:
                serials = []
            if not serials:
                self._toast('warn', '提示', '未检测到设备')
            else:
                self._toast('warn', '提示', f'检测到多个设备({len(serials)})，请仅保留一个设备后再操作')
            return

        adb = self._resolve_adb()
        show_system = False
        try:
            show_system = bool(self.cb_show_system_apps.isChecked())
        except Exception:
            show_system = False

        args = ['shell', 'pm', 'list', 'packages']
        if not show_system:
            args.append('-3')
        cmd = [adb, '-s', serial] + args

        self._apps_out = []
        self._apps_thread = QThread(self)
        self._apps_worker = _AdbCmdWorker(cmd)
        self._apps_worker.moveToThread(self._apps_thread)
        self._apps_thread.started.connect(self._apps_worker.run)
        self._apps_worker.output.connect(self._on_apps_output)
        self._apps_worker.finished.connect(self._apps_thread.quit)
        self._apps_worker.finished.connect(self._apps_worker.deleteLater)
        self._apps_thread.finished.connect(self._apps_thread.deleteLater)
        self._apps_thread.finished.connect(self._on_apps_thread_finished)
        self._apps_thread.start()

    def _on_apps_output(self, line: str):
        try:
            self._apps_out.append(line)
        except Exception:
            pass

    def _on_apps_thread_finished(self):
        try:
            out = '\n'.join(self._apps_out)
            pkgs: list[str] = []
            for line in out.splitlines():
                s = (line or '').strip()
                if s.startswith('package:'):
                    pkgs.append(s.split(':', 1)[1].strip())
            pkgs = sorted(set([p for p in pkgs if p]))

            cur = self._selected_pkg
            self.list_apps.clear()
            for p in pkgs:
                label = self._label_cache.get(p, '')
                text = f"{label}\n{p}" if label else p
                it = QListWidgetItem(text)
                try:
                    it.setData(Qt.UserRole, p)
                    it.setToolTip(p)
                except Exception:
                    pass
                self.list_apps.addItem(it)
            self._apply_app_filter()
            if cur:
                for i in range(self.list_apps.count()):
                    try:
                        if str(self.list_apps.item(i).data(Qt.UserRole) or '') == cur:
                            self.list_apps.setCurrentRow(i)
                            break
                    except Exception:
                        pass
                    if self.list_apps.item(i).text() == cur:
                        self.list_apps.setCurrentRow(i)
                        break
        except Exception:
            pass
        self._apps_worker = None
        self._apps_thread = None
        self._apps_out = []

    def _fetch_label_for_pkg(self, pkg: str):
        if not pkg:
            return
        if self._label_thread and self._label_thread.isRunning():
            return
        serial = self._get_default_serial()
        if not serial:
            return
        adb = self._resolve_adb()
        cmd = [adb, '-s', serial, 'shell', 'dumpsys', 'package', pkg]
        self._label_pkg = pkg
        self._label_out = []
        self._label_thread = QThread(self)
        self._label_worker = _AdbCmdWorker(cmd)
        self._label_worker.moveToThread(self._label_thread)
        self._label_thread.started.connect(self._label_worker.run)
        self._label_worker.output.connect(self._on_label_output)
        self._label_worker.finished.connect(self._label_thread.quit)
        self._label_worker.finished.connect(self._label_worker.deleteLater)
        self._label_thread.finished.connect(self._label_thread.deleteLater)
        self._label_thread.finished.connect(self._on_label_thread_finished)
        self._label_thread.start()

    def _on_label_output(self, line: str):
        try:
            self._label_out.append(line)
        except Exception:
            pass

    def _on_label_thread_finished(self):
        pkg = self._label_pkg
        try:
            text = '\n'.join(self._label_out)
            label = ''
            for raw in text.splitlines():
                s = (raw or '').strip()
                # common formats:
                # application-label:'Chrome'
                # application-label:Chrome
                if s.startswith('application-label:'):
                    label = s.split(':', 1)[1].strip().strip("'")
                    break
                if s.startswith('application-label='):
                    label = s.split('=', 1)[1].strip().strip("'")
                    break
            if pkg and label:
                self._label_cache[pkg] = label

            # update visible item if present
            if pkg and label:
                for i in range(self.list_apps.count()):
                    it = self.list_apps.item(i)
                    try:
                        if str(it.data(Qt.UserRole) or '') == pkg:
                            it.setText(f"{label}\n{pkg}")
                            break
                    except Exception:
                        continue
        except Exception:
            pass
        self._label_worker = None
        self._label_thread = None
        self._label_out = []
        self._label_pkg = ''

    def _open_app_permissions(self):
        pkg = self._pkg()
        if not pkg:
            self._toast('warn', '提示', '请先选择应用或确保已获取到前台包名')
            return
        serial = self._get_default_serial()
        if serial:
            self._write_oplog(serial, pkg, 'open-permissions')
        # Application details page (contains permissions entry)
        self._run_adb_cmd(
            ['shell', 'am', 'start', '-a', 'android.settings.APPLICATION_DETAILS_SETTINGS', '-d', f'package:{pkg}'],
            op_desc='打开权限设置',
        )

    def _refresh_disabled_components(self):
        pkg = self._pkg()
        if not pkg:
            self._toast('warn', '提示', '请先选择应用或确保已获取到前台包名')
            return
        if self._disabled_thread and self._disabled_thread.isRunning():
            self._toast('info', '提示', '正在刷新禁用组件列表…')
            return
        serial = self._get_default_serial()
        if not serial:
            try:
                serials = adb_service.list_devices()
            except Exception:
                serials = []
            if not serials:
                self._toast('warn', '提示', '未检测到设备')
            else:
                self._toast('warn', '提示', f'检测到多个设备({len(serials)})，请仅保留一个设备后再操作')
            return
        adb = self._resolve_adb()
        cmd = [adb, '-s', serial, 'shell', 'dumpsys', 'package', pkg]
        self._disabled_out = []
        try:
            self.list_disabled.clear()
        except Exception:
            pass
        self._disabled_thread = QThread(self)
        self._disabled_worker = _AdbCmdWorker(cmd)
        self._disabled_worker.moveToThread(self._disabled_thread)
        self._disabled_thread.started.connect(self._disabled_worker.run)
        self._disabled_worker.output.connect(self._on_disabled_output)
        self._disabled_worker.finished.connect(self._disabled_thread.quit)
        self._disabled_worker.finished.connect(self._disabled_worker.deleteLater)
        self._disabled_thread.finished.connect(self._disabled_thread.deleteLater)
        self._disabled_thread.finished.connect(self._on_disabled_thread_finished)
        self._disabled_thread.start()

    def _on_disabled_output(self, line: str):
        try:
            self._disabled_out.append(line)
        except Exception:
            pass

    def _on_disabled_thread_finished(self):
        try:
            text = '\n'.join(self._disabled_out)
            comps: list[str] = []
            in_block = False
            for raw in text.splitlines():
                line = raw.rstrip('\r\n')
                s = line.strip()
                if s.startswith('disabledComponents:'):
                    in_block = True
                    continue
                if in_block:
                    if not s:
                        break
                    # lines are usually like: com.xxx/.SomeActivity
                    if ' ' in s:
                        s = s.split()[0]
                    comps.append(s)
            comps = sorted(set([c for c in comps if c]))
            self.list_disabled.clear()
            for c in comps:
                self.list_disabled.addItem(QListWidgetItem(c))
        except Exception:
            pass
        self._disabled_worker = None
        self._disabled_thread = None
        self._disabled_out = []

    def _enable_component(self):
        pkg = self._pkg()
        if not pkg:
            self._toast('warn', '提示', '请先选择应用或确保已获取到前台包名')
            return
        comp = ''
        try:
            items = self.list_disabled.selectedItems() if self.list_disabled else []
        except Exception:
            items = []
        if items:
            comp = str(items[0].text() or '').strip()
        if not comp:
            try:
                comp = str(self.edt_component.text() or '').strip()
            except Exception:
                comp = ''
        if not comp:
            self._toast('warn', '提示', '请输入组件或从列表选择')
            return
        serial = self._get_default_serial()
        if serial:
            self._write_oplog(serial, pkg, f'enable-component {comp}')
        self._run_adb_cmd(['shell', 'pm', 'enable', comp], op_desc='恢复组件')

    def _freeze_app(self):
        pkg = self._pkg()
        if not pkg:
            self._toast('warn', '提示', '未获取到前台包名')
            return
        if not self._confirm_risky(
            'software_manager/risk/freeze',
            '确认冻结应用',
            '冻结会禁用应用（可能导致桌面图标消失/无法打开）。\n不同系统行为可能不同，部分设备需要更高权限。\n\n是否继续？',
        ):
            return
        serial = self._get_default_serial()
        if serial:
            self._write_oplog(serial, pkg, 'freeze')
        self._run_adb_cmd(['shell', 'pm', 'disable-user', '--user', '0', pkg], op_desc='冻结')

    def _unfreeze_app(self):
        default_pkg = self._pkg()
        dlg = _PackageInputDialog('解冻应用', '请输入需要解冻的包名：', default_pkg, self)
        if not dlg.exec():
            return
        pkg = dlg.text()
        if not pkg:
            self._toast('warn', '提示', '包名不能为空')
            return
        serial = self._get_default_serial()
        if serial:
            self._write_oplog(serial, pkg, 'unfreeze')
        self._run_adb_cmd(['shell', 'pm', 'enable', pkg], op_desc='解冻')

    def _uninstall_app(self):
        pkg = self._pkg()
        if not pkg:
            self._toast('warn', '提示', '未获取到前台包名')
            return
        if not self._confirm_risky(
            'software_manager/risk/uninstall',
            '确认卸载应用',
            '卸载会删除该应用。\n如应用包含重要数据，请先备份。\n\n是否继续？',
        ):
            return
        serial = self._get_default_serial()
        if serial:
            self._write_oplog(serial, pkg, 'uninstall')
        self._run_adb_cmd(['uninstall', pkg], op_desc='卸载')

    def _force_stop_app(self):
        pkg = self._pkg()
        if not pkg:
            self._toast('warn', '提示', '未获取到前台包名')
            return
        if not self._confirm_risky(
            'software_manager/risk/force_stop',
            '确认强行停止',
            '强行停止会立即结束应用进程，可能导致当前操作丢失或数据未保存。\n\n是否继续？',
        ):
            return
        serial = self._get_default_serial()
        if serial:
            self._write_oplog(serial, pkg, 'force-stop')
        self._run_adb_cmd(['shell', 'am', 'force-stop', pkg], op_desc='强行停止')

    def _uninstall_keep_data(self):
        pkg = self._pkg()
        if not pkg:
            self._toast('warn', '提示', '未获取到前台包名')
            return
        if not self._confirm_risky(
            'software_manager/risk/uninstall_keep',
            '确认保留数据卸载',
            '该操作会卸载应用但尝试保留数据（并非所有系统都保证）。\n可能导致后续安装异常或数据残留。\n\n是否继续？',
        ):
            return
        serial = self._get_default_serial()
        if serial:
            self._write_oplog(serial, pkg, 'uninstall-keep-data')
        # Uninstall for user 0 and keep data
        self._run_adb_cmd(['shell', 'pm', 'uninstall', '-k', '--user', '0', pkg], op_desc='保留数据卸载')

    def _clear_data(self):
        pkg = self._pkg()
        if not pkg:
            self._toast('warn', '提示', '未获取到前台包名')
            return
        if not self._confirm_risky(
            'software_manager/risk/clear_data',
            '确认清除数据',
            '清除数据会删除该应用的所有本地数据与登录状态。\n\n是否继续？',
        ):
            return
        serial = self._get_default_serial()
        if serial:
            self._write_oplog(serial, pkg, 'clear-data')
        self._run_adb_cmd(['shell', 'pm', 'clear', pkg], op_desc='清除数据')

    def _pull_apk(self):
        pkg = self._pkg()
        if not pkg:
            self._toast('warn', '提示', '未获取到前台包名')
            return
        dst, _ = QFileDialog.getSaveFileName(self, '保存 APK 到电脑', f"{pkg}.apk", 'APK (*.apk);;所有文件 (*.*)')
        if not dst:
            return

        serial = self._get_default_serial()
        if not serial:
            try:
                serials = adb_service.list_devices()
            except Exception:
                serials = []
            if not serials:
                self._toast('warn', '提示', '未检测到设备')
            else:
                self._toast('warn', '提示', f'检测到多个设备({len(serials)})，请仅保留一个设备后再操作')
            return

        adb = self._resolve_adb()
        # get remote apk path
        try:
            res = subprocess.run(
                [adb, '-s', serial, 'shell', 'pm', 'path', pkg],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=6,
            )
            out = (res.stdout or '').strip()
        except Exception as e:
            self._toast('warn', '错误', f'获取 APK 路径失败: {e}')
            return

        remote = ''
        for line in out.splitlines():
            line = line.strip()
            if line.startswith('package:'):
                remote = line.split(':', 1)[1].strip()
                break
        if not remote:
            self._toast('warn', '提示', f'未找到 {pkg} 的安装路径')
            return

        self._write_oplog(serial, pkg, f"pull-apk {dst}")
        cmd = [adb, '-s', serial, 'pull', remote, dst]
        self._run_host_cmd(cmd, op_desc='提取APK')

    def _normalize_component(self, pkg: str, act: str) -> str:
        s = (act or '').strip()
        if not s:
            return ''
        if '/' not in s:
            return ''
        p, a = s.split('/', 1)
        p = p.strip()
        a = a.strip()
        if not p:
            p = pkg
        if a.startswith('.'):
            a = p + a
        return f"{p}/{a}"

    def _disable_current_activity(self):
        pkg = self._pkg()
        act = (self._current_activity or '').strip()
        if not pkg or not act:
            self._toast('warn', '提示', '未获取到当前 Activity')
            return

        comp = self._normalize_component(pkg, act)
        if not comp:
            self._toast('warn', '提示', '当前 Activity 解析失败，无法禁用')
            return

        use_root = False
        try:
            use_root = bool(self.cb_root_disable_activity.isChecked())
        except Exception:
            use_root = False

        risk_text = (
            f"即将禁用当前 Activity 组件：\n{comp}\n\n"
            "影响：该界面可能无法再打开，应用功能可能异常。\n"
            "恢复需要重新启用组件（可能需要同等权限）。\n"
            "为了让效果立即可见，将在禁用后强行停止该应用进程。\n"
        )
        if use_root:
            risk_text += "\n已选择使用 Root 执行：需要设备已 Root 且 su 可用。\n"
            risk_text += "执行时手机可能弹出 Root 授权，请注意确认。\n"
        risk_text += "\n是否继续？"

        if not self._confirm_risky(
            'software_manager/risk/disable_activity_root' if use_root else 'software_manager/risk/disable_activity',
            '确认禁用当前Activity',
            risk_text,
        ):
            return

        serial = self._get_default_serial()
        if serial:
            self._write_oplog(serial, pkg, f"disable-activity{'-root' if use_root else ''} {comp}")

        if use_root:
            self._run_adb_cmd(['shell', 'su', '-c', f'pm disable-user --user 0 {comp}'], op_desc='禁用Activity(root)')
        else:
            # Disable component then force-stop to make effect visible immediately
            self._run_adb_cmd(['shell', 'sh', '-c', f'pm disable-user --user 0 {comp} && am force-stop {pkg}'], op_desc='禁用Activity')

    def _run_host_cmd(self, cmd: list[str], op_desc: str | None = None):
        if self._thread and self._thread.isRunning():
            self._toast('info', '提示', '任务正在运行中，请稍后…')
            return

        self._pause_foreground_timer()
        self._pending_op_desc = op_desc
        self._thread = QThread(self)
        self._worker = _AdbCmdWorker(cmd)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.output.connect(self._noop)
        self._worker.finished.connect(self._on_cmd_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _start_foreground_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._refresh_foreground_now)
        self._timer.start()
        self._refresh_foreground_now()

    def _start_foreground_worker(self):
        if self._fg_thread is not None:
            return
        self._fg_thread = QThread(self)
        self._fg_worker = _ForegroundWorker()
        self._fg_worker.moveToThread(self._fg_thread)
        self._fg_request.connect(self._fg_worker.fetch, Qt.QueuedConnection)
        self._fg_worker.result.connect(self._on_foreground_result)
        self._fg_thread.start()

    def _on_foreground_result(self, pkg: str, act: str):
        self._current_pkg = (pkg or '').strip()
        self._current_activity = (act or '').strip()
        self.lbl_pkg.setText(f"前台包名：{self._current_pkg or '-'}")
        self.lbl_act.setText(f"当前Activity：{self._current_activity or '-'}")

    def _refresh_foreground_now(self):
        serial = self._get_default_serial()
        if not serial:
            try:
                serials = adb_service.list_devices()
            except Exception:
                serials = []
            if not serials:
                self.lbl_dev.setText("设备：未检测到")
            else:
                self.lbl_dev.setText(f"设备：检测到多个设备({len(serials)})")
            self.lbl_pkg.setText("前台包名：-")
            self.lbl_act.setText("当前Activity：-")
            self._current_pkg = ""
            self._current_activity = ""
            return

        self.lbl_dev.setText(f"设备：{serial}")

        if self._fg_worker is None:
            return
        adb = self._resolve_adb()
        self._fg_request.emit(adb, serial)

    def cleanup(self):
        try:
            if self._timer is not None:
                try:
                    self._timer.stop()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if self._worker:
                self._worker.stop()
        except Exception:
            pass
        try:
            if self._thread and self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(1500)
        except Exception:
            pass

        try:
            if self._apps_worker:
                self._apps_worker.stop()
        except Exception:
            pass
        try:
            if self._apps_thread and self._apps_thread.isRunning():
                self._apps_thread.quit()
                self._apps_thread.wait(1500)
        except Exception:
            pass

        try:
            if self._disabled_worker:
                self._disabled_worker.stop()
        except Exception:
            pass
        try:
            if self._disabled_thread and self._disabled_thread.isRunning():
                self._disabled_thread.quit()
                self._disabled_thread.wait(1500)
        except Exception:
            pass

        try:
            if self._label_worker:
                self._label_worker.stop()
        except Exception:
            pass
        try:
            if self._label_thread and self._label_thread.isRunning():
                self._label_thread.quit()
                self._label_thread.wait(1500)
        except Exception:
            pass

        try:
            if self._fg_thread and self._fg_thread.isRunning():
                self._fg_thread.quit()
                self._fg_thread.wait(1500)
        except Exception:
            pass
        self._fg_worker = None
        self._fg_thread = None

    def closeEvent(self, event):
        try:
            self.cleanup()
        except Exception:
            pass
        return super().closeEvent(event)
