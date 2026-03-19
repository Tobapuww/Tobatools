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
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QStackedWidget,
    QSizePolicy,
)

from qfluentwidgets import (
    CardWidget,
    PrimaryPushButton,
    PushButton,
    ComboBox,
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
    CaptionLabel,
)

from app.services import adb_service
from app.components.log_widget import LogWidget


def _silent_popen_kwargs() -> dict:
    try:
        if os.name == 'nt':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return {'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW}
    except Exception:
        pass
    return {}


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

    def __init__(self, serial: str, args: list[str], op_desc: str | None = None):
        super().__init__()
        self._serial = str(serial or '').strip()
        self._args = list(args or [])
        self._op_desc = op_desc
        self._stop = False

    def stop(self):
        self._stop = True
        return

    def run(self):
        code = -1
        try:
            if not self._serial:
                self.output.emit('未检测到设备')
                code = 2
                return

            if self._op_desc:
                try:
                    self.output.emit(self._op_desc)
                except Exception:
                    pass

            if self._args and self._args[0] == 'install':
                # install [-r] [-d] <apk>
                reinstall = ('-r' in self._args)
                downgrade = ('-d' in self._args)
                apk_path = ''
                for a in self._args[1:]:
                    if not str(a).startswith('-'):
                        apk_path = str(a)
                ok, out = adb_service.adb_install_apk(self._serial, apk_path, reinstall=reinstall, downgrade=downgrade, timeout=600)
                if out:
                    for line in str(out).splitlines():
                        self.output.emit(line.rstrip('\r\n'))
                code = 0 if ok else 1
                return

            if self._args and self._args[0] == 'pull':
                # pull <remote> <local>
                remote = self._args[1] if len(self._args) > 1 else ''
                local = self._args[2] if len(self._args) > 2 else ''
                ok, out = adb_service.adb_pull_file_serial(self._serial, str(remote), str(local), timeout=600)
                if out:
                    for line in str(out).splitlines():
                        self.output.emit(line.rstrip('\r\n'))
                code = 0 if ok else 1
                return

            # Default: treat as adb shell invocation.
            if self._args and self._args[0] == 'shell':
                cmd_args = self._args[1:]
            else:
                cmd_args = self._args
            out = adb_service.adb_shell_serial(self._serial, cmd_args, timeout=20)
            if out:
                for line in str(out).splitlines():
                    if self._stop:
                        break
                    self.output.emit(line.rstrip('\r\n'))
            code = 0
        except Exception as e:
            self.output.emit(f"ADB 执行异常: {e}")
            code = -1
        finally:
            self.finished.emit(code)


class _BatchLabelWorker(QObject):
    """Worker to fetch app labels for multiple packages in batch using aapt on device."""
    finished = Signal(dict)  # {pkg: label}

    def __init__(self, serial: str, pkgs: list[str]):
        super().__init__()
        self._serial = str(serial or '').strip()
        self._pkgs = list(pkgs or [])
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        result: dict[str, str] = {}
        remote_aapt = '/data/local/tmp/aapt'

        try:
            # First try cmd package query-activities for apps with nonLocalizedLabel
            out = adb_service.adb_shell_serial(
                self._serial,
                ['cmd', 'package', 'query-activities', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER'],
                timeout=30
            )
            if out:
                current_pkg = ''
                for line in (out or '').splitlines():
                    if self._stop:
                        break
                    s = (line or '').strip()
                    if s.startswith('packageName='):
                        current_pkg = s.split('=', 1)[1].strip()
                    elif 'nonLocalizedLabel=' in s and current_pkg:
                        try:
                            idx = s.find('nonLocalizedLabel=')
                            if idx >= 0:
                                rest = s[idx + len('nonLocalizedLabel='):]
                                end_idx = rest.find(' icon=')
                                if end_idx > 0:
                                    label = rest[:end_idx].strip()
                                else:
                                    label = rest.strip()
                                if label and label != 'null' and current_pkg in self._pkgs:
                                    result[current_pkg] = label
                        except Exception:
                            pass

            # For remaining packages without labels, use aapt on device to parse APK
            remaining = [p for p in self._pkgs if p not in result]
            if remaining and not self._stop:
                # Push aapt-arm-pie to device if not exists
                local_aapt = Path(__file__).resolve().parents[2] / 'bin' / 'aapt-arm-pie'
                if local_aapt.exists():
                    # Check if aapt exists on device
                    check = adb_service.adb_shell_serial(self._serial, ['ls', remote_aapt], timeout=5)
                    if 'No such file' in (check or '') or not check or 'cannot' in (check or '').lower():
                        # Push aapt to device using push_path
                        adb_service.push_path(str(local_aapt), remote_aapt)
                        adb_service.adb_shell_serial(self._serial, ['chmod', '755', remote_aapt], timeout=5)

                    # Get APK paths for all packages in one call
                    path_out = adb_service.adb_shell_serial(self._serial, ['pm', 'list', 'packages', '-f'], timeout=30)
                    pkg_to_path: dict[str, str] = {}
                    for line in (path_out or '').splitlines():
                        if line.startswith('package:'):
                            try:
                                rest = line[8:]
                                eq_idx = rest.rfind('=')
                                if eq_idx > 0:
                                    apk_path = rest[:eq_idx]
                                    pkg_name = rest[eq_idx + 1:].strip()
                                    if pkg_name in remaining:
                                        pkg_to_path[pkg_name] = apk_path
                            except Exception:
                                pass

                    # Parse APKs using aapt on device
                    for pkg in remaining[:100]:  # Limit to 100 packages
                        if self._stop:
                            break
                        if pkg not in pkg_to_path:
                            continue
                        apk_path = pkg_to_path[pkg]
                        try:
                            out = adb_service.adb_shell_serial(
                                self._serial,
                                [remote_aapt, 'dump', 'badging', apk_path],
                                timeout=10
                            )
                            if out:
                                # Prefer zh-CN > en > default label
                                label_default = ''
                                label_en = ''
                                label_zh_cn = ''
                                for line in out.splitlines():
                                    if line.startswith('application-label-zh-CN:') or line.startswith('application-label-zh_CN:'):
                                        label_zh_cn = line.split(':', 1)[1].strip().strip("'")
                                    elif line.startswith('application-label-en:') or line.startswith('application-label-en-'):
                                        if not label_en:
                                            label_en = line.split(':', 1)[1].strip().strip("'")
                                    elif line.startswith('application-label:'):
                                        label_default = line.split(':', 1)[1].strip().strip("'")
                                # Pick best label
                                label = label_zh_cn or label_en or label_default
                                if label:
                                    result[pkg] = label
                        except Exception:
                            pass
        except Exception:
            pass
        finally:
            self.finished.emit(result)


class _ForegroundWorker(QObject):
    result = Signal(str, str)  # pkg, act

    def __init__(self):
        super().__init__()
        self._busy = False

    def fetch(self, serial: str):
        if self._busy:
            return
        self._busy = True
        pkg = ''
        act = ''
        try:
            # Strategy (fast + robust across Android versions):
            # 1) dumpsys window windows: parse mCurrentFocus / mFocusedApp
            # 2) dumpsys activity activities: parse mResumedActivity
            # 3) dumpsys activity top (legacy)
            # NOTE: Do NOT rely on grep/head existing in device shell.
            import re

            def _normalize_component(p: str, a: str) -> tuple[str, str]:
                p = (p or '').strip()
                a = (a or '').strip()
                if not p or not a:
                    return '', ''
                if a.startswith('.'):
                    a = p + a
                return p, f"{p}/{a}"

            # Patterns seen across devices:
            # - mCurrentFocus=Window{.. u0 com.pkg/com.pkg.Act}
            # - mFocusedApp=AppWindowToken{.. token=Token{.. ActivityRecord{.. com.pkg/.Act ..}}}
            # - mResumedActivity: ActivityRecord{.. com.pkg/.Act ..}
            pat_comp = re.compile(r"\b(u\d+\s+)?(?P<pkg>[a-zA-Z0-9_\.]+)\/(?P<act>[a-zA-Z0-9_\.$]+)")
            pat_resumed = re.compile(r"mResumedActivity\s*:\s*ActivityRecord\{[^}]*\s(?P<pkg>[a-zA-Z0-9_\.]+)\/(?P<act>[a-zA-Z0-9_\.$]+)")
            pat_focus = re.compile(r"m(CurrentFocus|FocusedApp)\s*=.*?\s(?P<pkg>[a-zA-Z0-9_\.]+)\/(?P<act>[a-zA-Z0-9_\.$]+)")

            def _scan_lines_for_component(text: str) -> tuple[str, str]:
                if not text:
                    return '', ''
                lines = (text or '').splitlines()
                for raw in lines[:400]:
                    s = (raw or '').strip()
                    if not s:
                        continue
                    m = pat_focus.search(s)
                    if m:
                        return _normalize_component(m.group('pkg'), m.group('act'))
                    m2 = pat_resumed.search(s)
                    if m2:
                        return _normalize_component(m2.group('pkg'), m2.group('act'))
                    # fallback: any pkg/act token on this line
                    if 'mCurrentFocus' in s or 'mFocusedApp' in s or 'mResumedActivity' in s:
                        m3 = pat_comp.search(s)
                        if m3:
                            return _normalize_component(m3.group('pkg'), m3.group('act'))
                return '', ''

            if not pkg:
                try:
                    out1 = adb_service.adb_shell_serial(serial, ['dumpsys', 'window', 'windows'], timeout=2) or ''
                    pkg, act = _scan_lines_for_component(out1)
                except Exception:
                    pass

            if not pkg:
                try:
                    out2 = adb_service.adb_shell_serial(serial, ['dumpsys', 'activity', 'activities'], timeout=2) or ''
                    pkg, act = _scan_lines_for_component(out2)
                except Exception:
                    pass

            if not pkg:
                try:
                    out3 = adb_service.adb_shell_serial(serial, ['dumpsys', 'activity', 'top'], timeout=2) or ''
                    pkg, act = _scan_lines_for_component(out3)
                except Exception:
                    pass

            # 如果top命令失败，尝试更轻量的方法
            if not pkg:
                try:
                    # 使用 am stack list 命令，输出更简洁
                    out = adb_service.adb_shell_serial(serial, ['am', 'stack', 'list'], timeout=1) or ""
                    for line in out.splitlines()[:20]:  # 只读前20行
                        if 'topActivity' in line or 'TaskRecord' in line:
                            for tok in line.split():
                                if '/' in tok and '.' in tok:
                                    act = tok.strip()
                                    pkg = act.split('/', 1)[0]
                                    break
                            if pkg:
                                break
                except Exception:
                    pass
        finally:
            self._busy = False
            try:
                self.result.emit(pkg, act)
            except Exception:
                pass


class _AppCard(CardWidget):
    """Card widget for a single installed app."""
    selected = Signal(object)  # emits self when card is clicked

    def __init__(self, pkg: str, label: str = '', parent=None):
        super().__init__(parent)
        self.pkg = pkg
        self.label = label
        self._selected = False
        self.setObjectName("appCard")

        self.setCursor(Qt.PointingHandCursor)
        try:
            self.setFixedHeight(56)
        except Exception:
            pass

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)

        display = label if label else pkg
        self.lbl_name = BodyLabel(display, self)
        col.addWidget(self.lbl_name)

        if label:
            self.lbl_pkg = CaptionLabel(pkg, self)
            try:
                self.lbl_pkg.setStyleSheet('color: rgba(0,0,0,0.55);')
            except Exception:
                pass
            col.addWidget(self.lbl_pkg)
        else:
            self.lbl_pkg = None

        lay.addLayout(col, 1)

        self._update_style()

    def set_label(self, label: str):
        self.label = label
        try:
            self.lbl_name.setText(label if label else self.pkg)
            if label and self.lbl_pkg is None:
                self.lbl_pkg = CaptionLabel(self.pkg, self)
                try:
                    self.lbl_pkg.setStyleSheet('color: rgba(0,0,0,0.55);')
                except Exception:
                    pass
                self.layout().itemAt(0).layout().addWidget(self.lbl_pkg)
        except Exception:
            pass

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        self._update_style()

    def _update_style(self):
        try:
            if self._selected:
                self.setStyleSheet('#appCard {background-color:rgba(42,116,218,0.15);border-radius:8px;}')
            else:
                self.setStyleSheet('#appCard {background-color:transparent;border-radius:8px;}')
        except Exception:
            pass

    def mousePressEvent(self, event):
        try:
            self.selected.emit(self)
        except Exception:
            pass
        return super().mousePressEvent(event)


class SoftwareManagerTab(QWidget):
    _fg_request = Signal(str)  # serial

    def __init__(self):
        super().__init__()
        self._thread: QThread | None = None
        self._worker: _AdbCmdWorker | None = None
        self._pending_op_desc: str | None = None
        self._installing: bool = False

        self._install_queue: list[str] = []
        self._install_total: int = 0
        self._install_done: int = 0

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

        self._batch_label_thread: QThread | None = None
        self._batch_label_worker: _BatchLabelWorker | None = None
        self._pending_pkgs: list[str] = []

        self._app_cards: list[_AppCard] = []

        self._selected_apk: str = ""
        self._selected_pkg: str = ""
        self._current_pkg: str = ""
        self._current_activity: str = ""
        self._timer: QTimer | None = None
        self._auto_refresh_enabled: bool = True  # 默认开启自动刷新

        self._build_ui()
        self._start_foreground_worker()
        # 前台实时刷新改为首次展示时启动，避免启动阶段阻塞/卡顿
        self._did_first_show = False

        try:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.cleanup)
        except Exception:
            pass

    def showEvent(self, event):
        try:
            if not getattr(self, '_did_first_show', False):
                self._did_first_show = True
                try:
                    # 同步 UI 状态，但不弹 toast
                    try:
                        self.chk_auto_refresh.blockSignals(True)
                        self.chk_auto_refresh.setChecked(bool(self._auto_refresh_enabled))
                    finally:
                        self.chk_auto_refresh.blockSignals(False)
                except Exception:
                    pass

                if self._auto_refresh_enabled:
                    try:
                        if self._timer is None:
                            self._timer = QTimer(self)
                            self._timer.setInterval(1000)
                            self._timer.timeout.connect(self._refresh_foreground_now)
                        if not self._timer.isActive():
                            self._timer.start()
                        QTimer.singleShot(150, self._refresh_foreground_now)
                    except Exception:
                        pass
        except Exception:
            pass
        return super().showEvent(event)

    # -------- UI --------
    def _build_ui(self):
        PAGE_MARGIN = 24
        CARD_MARGIN = 16
        GAP_LG = 12
        GAP_MD = 10
        GAP_SM = 8

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
            lay.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        except Exception:
            pass
        lay.setSpacing(GAP_LG)

        # 顶部 Banner（与其他 Tab 风格一致）
        banner_w = QWidget(self)
        try:
            banner_w.setFixedHeight(110)
        except Exception:
            pass
        banner = QHBoxLayout(banner_w)
        banner.setContentsMargins(PAGE_MARGIN, 18, PAGE_MARGIN, 18)
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

        # 主体布局：左(已装列表) 5 : 右(状态、操作) 7
        main_h_layout = QHBoxLayout()
        main_h_layout.setSpacing(24)
        
        left_col = QVBoxLayout()
        left_col.setSpacing(24)
        self._build_apps_list_card(left_col)
        
        right_col = QVBoxLayout()
        right_col.setSpacing(24)
        self._build_state_card(right_col)
        self._build_ops_panel(right_col)
        
        left_w = QWidget()
        left_w.setLayout(left_col)
        right_w = QWidget()
        right_w.setLayout(right_col)
        
        main_h_layout.addWidget(left_w, 5)
        main_h_layout.addWidget(right_w, 7)
        
        lay.addLayout(main_h_layout)

        # Log Widget
        self.log_widget = LogWidget(container)
        self.log_widget.setFixedHeight(150)
        lay.addWidget(self.log_widget)

        # signals
        self.btn_refresh_state.clicked.connect(self._refresh_foreground_now)
        self.chk_auto_refresh.stateChanged.connect(self._toggle_auto_refresh)
        self.btn_clear_selected.clicked.connect(self._clear_selected_pkg)
        self.btn_refresh_apps.clicked.connect(self._refresh_apps)
        self.edt_app_search.textChanged.connect(self._apply_app_filter)
        self.cb_show_system_apps.stateChanged.connect(self._refresh_apps)
        # Card selection is handled via _AppCard.clicked signal in _add_app_card
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

    def _build_apps_list_card(self, parent_lay):
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)
        
        head = QHBoxLayout()
        icon = QLabel("📦")
        icon.setStyleSheet("font-size:18px;")
        title = QLabel("已安装应用")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        head.addWidget(icon)
        head.addWidget(title)
        head.addStretch(1)
        
        self.btn_clear_selected = PushButton(FluentIcon.CLEAR_SELECTION, "清除选中")
        self.btn_refresh_apps = PushButton(FluentIcon.SYNC, "刷新")
        head.addWidget(self.btn_clear_selected)
        head.addWidget(self.btn_refresh_apps)
        lay.addLayout(head)
        
        self.edt_app_search = LineEdit()
        self.edt_app_search.setPlaceholderText("搜索包名/应用名...")
        self.edt_app_search.setClearButtonEnabled(True)
        lay.addWidget(self.edt_app_search)
        
        self.cb_show_system_apps = CheckBox("显示系统应用")
        lay.addWidget(self.cb_show_system_apps)
        
        self.apps_scroll = SmoothScrollArea()
        self.apps_scroll.setWidgetResizable(True)
        self.apps_scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')
        scroll_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.apps_scroll.setSizePolicy(scroll_policy)
        self.apps_scroll.setMinimumHeight(320)
        self.apps_container = QWidget()
        self.apps_container.setStyleSheet('QWidget{background:transparent;}')
        self.apps_scroll.setWidget(self.apps_container)
        
        self.apps_cards_lay = QVBoxLayout(self.apps_container)
        self.apps_cards_lay.setContentsMargins(0, 0, 0, 0)
        self.apps_cards_lay.setSpacing(6)
        self.apps_cards_lay.addStretch(1)
        
        lay.addWidget(self.apps_scroll, 1)
        self.list_apps = None
        parent_lay.addWidget(card, 1)
        
    def _build_state_card(self, parent_lay):
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)
        
        head = QHBoxLayout()
        icon = QLabel("📱")
        icon.setStyleSheet("font-size:18px;")
        title = QLabel("前台状态监控")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        head.addWidget(icon)
        head.addWidget(title)
        head.addStretch(1)
        
        self.chk_auto_refresh = CheckBox("自动刷新")
        self.btn_refresh_state = PushButton(FluentIcon.SYNC, "立即刷新")
        head.addWidget(self.chk_auto_refresh)
        head.addWidget(self.btn_refresh_state)
        lay.addLayout(head)
        
        from PySide6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setSpacing(12)
        
        # 采用2x2网格展示这四个信息
        def _make_info_item(title_text):
            w = QWidget()
            w.setObjectName("infoItem")
            l = QVBoxLayout(w)
            l.setContentsMargins(12, 10, 12, 10)
            l.setSpacing(4)
            w.setStyleSheet("#infoItem {background: rgba(0,0,0,0.03); border-radius: 8px;}")
            t = CaptionLabel(title_text)
            t.setStyleSheet("color: #86909c;")
            v = BodyLabel('-')
            v.setStyleSheet("color: #1d2129;")
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            l.addWidget(t)
            l.addWidget(v)
            return w, v
            
        w1, self.lbl_dev = _make_info_item("当前设备")
        w2, self.lbl_selected = _make_info_item("列表中选中包名")
        self.lbl_selected.setStyleSheet("color: #2A74DA; font-weight: 600;")
        w3, self.lbl_pkg = _make_info_item("当前前台包名")
        w4, self.lbl_act = _make_info_item("当前 Activity")
        self.lbl_act.setStyleSheet("color: rgba(0,0,0,0.62);")
        
        grid.addWidget(w1, 0, 0)
        grid.addWidget(w2, 0, 1)
        grid.addWidget(w3, 1, 0)
        grid.addWidget(w4, 1, 1)
        
        lay.addLayout(grid)
        parent_lay.addWidget(card)
        
    def _build_ops_panel(self, parent_lay):
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)
        
        head = QHBoxLayout()
        icon = QLabel("🛠️")
        icon.setStyleSheet("font-size:18px;")
        title = QLabel("操作面板")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        head.addWidget(icon)
        head.addWidget(title)
        head.addStretch(1)
        
        self.cmb_section = ComboBox()
        self.cmb_section.addItems(["安装APK", "应用操作", "组件管理"])
        self.cmb_section.setFixedWidth(140)
        head.addWidget(self.cmb_section)
        lay.addLayout(head)
        
        self.stack_section = QStackedWidget()
        
        # Page 1: Install APK
        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.setSpacing(16)
        
        h_apk = QHBoxLayout()
        self.cb_reinstall = CheckBox("覆盖安装/降级")
        self.cb_downgrade = CheckBox("允许降级(如需)")
        h_apk.addWidget(self.cb_reinstall)
        h_apk.addWidget(self.cb_downgrade)
        h_apk.addStretch(1)
        self.btn_install = PrimaryPushButton(FluentIcon.DOWNLOAD, "安装本地 APK")
        h_apk.addWidget(self.btn_install)
        l1.addLayout(h_apk)
        
        self.install_progress = QProgressBar()
        self.install_progress.setRange(0, 0)
        self.install_progress.setTextVisible(True)
        self.install_progress.setFormat("正在安装…")
        self.install_progress.setVisible(False)
        self.install_progress.setStyleSheet(
            "QProgressBar{border:1px solid rgba(0,0,0,0.08);border-radius:8px;background:rgba(0,0,0,0.03);padding:2px;}"
            "QProgressBar::chunk{border-radius:8px;background:rgba(42,116,218,0.55);}"
        )
        l1.addWidget(self.install_progress)
        l1.addStretch(1)
        self.stack_section.addWidget(p1)
        
        def _on_downgrade_changed():
            on = self.cb_downgrade.isChecked()
            if on:
                self.cb_reinstall.setChecked(True)
            self.cb_reinstall.setEnabled(not self._installing and not on)
        self.cb_downgrade.stateChanged.connect(_on_downgrade_changed)
        
        # Page 2: App Ops
        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.setSpacing(16)
        
        op_hint = BodyLabel("默认基于当前前台包名，在左侧列表选中时则基于选中包名。")
        op_hint.setStyleSheet("color: #4e5969;")
        l2.addWidget(op_hint)
        
        row1 = QHBoxLayout()
        self.btn_freeze = PushButton("冻结应用")
        self.btn_unfreeze = PushButton("解冻应用")
        self.btn_force_stop = PushButton("强行停止")
        self.btn_open_permissions = PushButton("权限设置页")
        row1.addWidget(self.btn_freeze)
        row1.addWidget(self.btn_unfreeze)
        row1.addWidget(self.btn_force_stop)
        row1.addWidget(self.btn_open_permissions)
        row1.addStretch(1)
        l2.addLayout(row1)
        
        row2 = QHBoxLayout()
        self.btn_uninstall = PushButton("卸载")
        self.btn_uninstall_keep = PushButton("保留数据卸载")
        self.btn_clear_data = PushButton("清除数据")
        self.btn_pull_apk = PushButton("提取APK到电脑")
        row2.addWidget(self.btn_uninstall)
        row2.addWidget(self.btn_uninstall_keep)
        row2.addWidget(self.btn_clear_data)
        row2.addWidget(self.btn_pull_apk)
        row2.addStretch(1)
        l2.addLayout(row2)
        
        row3 = QHBoxLayout()
        self.btn_disable_activity = PushButton("禁用当前 Activity")
        self.cb_root_disable_activity = CheckBox("Root禁用")
        self.btn_open_oplog = PushButton(FluentIcon.DOCUMENT, "操作记录")
        row3.addWidget(self.btn_disable_activity)
        row3.addWidget(self.cb_root_disable_activity)
        row3.addWidget(self.btn_open_oplog)
        row3.addStretch(1)
        l2.addLayout(row3)
        l2.addStretch(1)
        self.stack_section.addWidget(p2)
        
        # Page 3: Component Mgt
        p3 = QWidget()
        l3 = QVBoxLayout(p3)
        l3.setContentsMargins(0, 0, 0, 0)
        l3.setSpacing(16)
        
        h_dis = QHBoxLayout()
        h_dis.addWidget(QLabel("已禁用组件:"))
        h_dis.addStretch(1)
        self.btn_refresh_disabled = PushButton(FluentIcon.SYNC, "刷新列表")
        h_dis.addWidget(self.btn_refresh_disabled)
        l3.addLayout(h_dis)
        
        self.list_disabled = ListWidget()
        self.list_disabled.setMinimumHeight(140)
        l3.addWidget(self.list_disabled)
        
        row_en = QHBoxLayout()
        self.edt_component = LineEdit()
        self.edt_component.setPlaceholderText("包名/类名，或从上方选择")
        self.btn_enable_component = PushButton("恢复组件")
        row_en.addWidget(self.edt_component)
        row_en.addWidget(self.btn_enable_component)
        l3.addLayout(row_en)
        l3.addStretch(1)
        self.stack_section.addWidget(p3)
        
        lay.addWidget(self.stack_section)
        parent_lay.addWidget(card)
        parent_lay.addStretch(1)
        
        self.cmb_section.currentIndexChanged.connect(self.stack_section.setCurrentIndex)
        self.stack_section.setCurrentIndex(0)

    # -------- helpers --------
    def _append_log(self, text: str):
        try:
            if hasattr(self, 'log_widget'):
                self.log_widget.append_log(str(text))
        except Exception:
            pass

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

        cmd_args = list(args or [])

        self._pause_foreground_timer()
        self._pending_op_desc = op_desc
        
        # 使用 Step-based logging
        if op_desc and hasattr(self, 'log_widget'):
            import uuid
            self._pending_step_id = str(uuid.uuid4())
            self.log_widget.start_step(self._pending_step_id, op_desc)
        else:
            self._pending_step_id = None

        self._thread = QThread(self)
        # op_desc 置为 None，避免 worker 重复输出标题，标题已由 start_step 输出
        self._worker = _AdbCmdWorker(serial, cmd_args, op_desc=None)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.output.connect(self._append_log)
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
            msg = f"{prefix}命令返回码: {code}"
            self._toast('ok' if code == 0 else 'warn', title, msg)
            
            # Step based finish
            if getattr(self, '_pending_step_id', None) and hasattr(self, 'log_widget'):
                success = (code == 0)
                detail = "" if success else f"Code {code}"
                self.log_widget.finish_step(self._pending_step_id, success, detail)
                self._pending_step_id = None
            else:
                if code != 0:
                    self._append_log(f"Error: {msg}")
                else:
                    self._append_log(f"Success: {msg}")
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
                try:
                    force = False
                    if hasattr(self, 'cb_downgrade') and self.cb_downgrade is not None:
                        force = bool(self.cb_downgrade.isChecked())
                except Exception:
                    force = False
                self.cb_reinstall.setEnabled((not self._installing) and (not force))
        except Exception:
            pass
        try:
            if hasattr(self, 'cb_downgrade') and self.cb_downgrade is not None:
                self.cb_downgrade.setEnabled(not self._installing)
        except Exception:
            pass

    def _on_thread_finished(self):
        self._worker = None
        self._thread = None
        self._pending_op_desc = None

        try:
            if self._installing and self._install_queue:
                self._install_next_in_queue()
                return
        except Exception:
            pass

        try:
            if self._installing:
                self._set_installing(False)
        except Exception:
            pass

        self._resume_foreground_timer()

    # -------- actions --------
    def _install_apk(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择 APK（可多选）', '', 'APK (*.apk);;所有文件 (*.*)')
        if not paths:
            return

        ok_paths: list[str] = []
        for p in paths:
            try:
                if p and Path(p).exists():
                    ok_paths.append(p)
            except Exception:
                pass
        if not ok_paths:
            self._toast('warn', '提示', '选择的 APK 文件不存在')
            return

        self._selected_apk = ok_paths[0]
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

        self._install_queue = list(ok_paths)
        self._install_total = len(self._install_queue)
        self._install_done = 0

        self._set_installing(True)
        self._install_next_in_queue()

    def _install_next_in_queue(self):
        if not self._install_queue:
            return
        if self._thread and self._thread.isRunning():
            return

        path = ''
        try:
            path = str(self._install_queue.pop(0) or '').strip()
        except Exception:
            path = ''
        if not path:
            self._install_next_in_queue()
            return

        try:
            if not Path(path).exists():
                self._install_next_in_queue()
                return
        except Exception:
            pass

        try:
            self._selected_apk = path
        except Exception:
            pass

        self._install_done += 1
        try:
            if hasattr(self, 'install_progress') and self.install_progress is not None:
                self.install_progress.setFormat(f"正在安装… ({self._install_done}/{self._install_total})")
        except Exception:
            pass

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
            try:
                self._install_queue = []
            except Exception:
                pass
            return

        try:
            flags = ''
            try:
                force_r = False
                if hasattr(self, 'cb_downgrade') and self.cb_downgrade.isChecked():
                    force_r = True
                if force_r or self.cb_reinstall.isChecked():
                    flags += ' -r'
            except Exception:
                pass
            try:
                if hasattr(self, 'cb_downgrade') and self.cb_downgrade.isChecked():
                    flags += ' -d'
            except Exception:
                pass
            self._write_oplog(serial, '-', f"install{flags} {Path(path).name}".strip())
        except Exception:
            pass

        args = ['install']
        try:
            force_r = False
            if hasattr(self, 'cb_downgrade') and self.cb_downgrade.isChecked():
                force_r = True
            if force_r or self.cb_reinstall.isChecked():
                args.append('-r')
        except Exception:
            pass
        try:
            if hasattr(self, 'cb_downgrade') and self.cb_downgrade.isChecked():
                args.append('-d')
        except Exception:
            pass
        args.append(path)
        self._run_adb_cmd(args, op_desc=f"安装APK ({self._install_done}/{self._install_total})")

    def _pkg(self) -> str:
        s = (self._selected_pkg or '').strip()
        if s:
            return s
        return (self._current_pkg or '').strip()

    def _on_app_selected(self):
        # Legacy method for ListWidget - now handled by _on_app_card_clicked
        pass

    def _clear_selected_pkg(self):
        self._selected_pkg = ''
        # Deselect all cards
        try:
            for c in self._app_cards:
                c.set_selected(False)
        except Exception:
            pass
        try:
            self.lbl_selected.setText('-')
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
            for card in self._app_cards:
                # search both label and package name
                txt = ((card.label or '') + ' ' + (card.pkg or '')).lower()
                card.setVisible((not q) or (q in txt))
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

        show_system = False
        try:
            show_system = bool(self.cb_show_system_apps.isChecked())
        except Exception:
            show_system = False

        args = ['shell', 'pm', 'list', 'packages']
        if not show_system:
            args.append('-3')

        self._apps_out = []
        self._apps_thread = QThread(self)
        self._apps_worker = _AdbCmdWorker(serial, args)
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

            # Show cards immediately with cached labels
            cur = self._selected_pkg
            self._clear_app_cards()
            for p in pkgs:
                label = self._label_cache.get(p, '')
                self._add_app_card(p, label)
            self._apply_app_filter()
            if cur:
                for card in self._app_cards:
                    if card.pkg == cur:
                        self._on_app_card_clicked(card)
                        break

            # Start batch label fetch in background to update labels
            self._pending_pkgs = pkgs
            to_fetch = [p for p in pkgs if p not in self._label_cache]
            if to_fetch:
                self._toast('info', '提示', f'正在获取 {len(to_fetch)} 个应用名称…', ms=3000)
            self._start_batch_label_fetch(pkgs)
        except Exception:
            pass
        self._apps_worker = None
        self._apps_thread = None
        self._apps_out = []

    def _start_batch_label_fetch(self, pkgs: list[str]):
        # Filter out packages we already have labels for
        to_fetch = [p for p in pkgs if p not in self._label_cache]

        if not to_fetch:
            # All labels cached, show cards immediately
            self._show_app_cards_with_labels()
            return

        serial = self._get_default_serial()
        if not serial:
            # No device, show cards without labels
            self._show_app_cards_with_labels()
            return

        if self._batch_label_thread and self._batch_label_thread.isRunning():
            # Already fetching, will show when done
            return

        self._batch_label_thread = QThread(self)
        self._batch_label_worker = _BatchLabelWorker(serial, to_fetch)
        self._batch_label_worker.moveToThread(self._batch_label_thread)
        self._batch_label_thread.started.connect(self._batch_label_worker.run)
        self._batch_label_worker.finished.connect(self._on_batch_label_finished, Qt.QueuedConnection)
        self._batch_label_worker.finished.connect(self._batch_label_thread.quit)
        self._batch_label_worker.finished.connect(self._batch_label_worker.deleteLater)
        self._batch_label_thread.finished.connect(self._batch_label_thread.deleteLater)
        self._batch_label_thread.start()

    def _on_batch_label_finished(self, labels: dict):
        try:
            # Update cache with new labels
            if labels:
                self._label_cache.update(labels)
                # Update existing cards with new labels
                updated = 0
                for card in self._app_cards:
                    if card.pkg in labels:
                        card.set_label(labels[card.pkg])
                        updated += 1
                if updated > 0:
                    self._toast('ok', '完成', f'已获取 {updated} 个应用名称', ms=2000)
        except Exception:
            pass
        try:
            self._batch_label_worker = None
            self._batch_label_thread = None
        except Exception:
            pass
        self._pending_pkgs = []

    def _clear_app_cards(self):
        try:
            for c in self._app_cards:
                try:
                    c.setParent(None)
                    c.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass
        self._app_cards = []
        try:
            while self.apps_cards_lay.count() > 0:
                item = self.apps_cards_lay.takeAt(0)
                w = item.widget()
                if w is not None:
                    try:
                        w.setParent(None)
                        w.deleteLater()
                    except Exception:
                        pass
            self.apps_cards_lay.addStretch(1)
        except Exception:
            pass

    def _add_app_card(self, pkg: str, label: str = ''):
        card = _AppCard(pkg, label, self.apps_container)
        self._app_cards.append(card)
        card.selected.connect(self._on_app_card_clicked)
        # Insert before stretch
        idx = max(0, self.apps_cards_lay.count() - 1)
        self.apps_cards_lay.insertWidget(idx, card)

    def _on_app_card_clicked(self, card: _AppCard):
        # Deselect all other cards
        for c in self._app_cards:
            c.set_selected(c is card)
        self._selected_pkg = card.pkg
        try:
            self.lbl_selected.setText(card.pkg)
        except Exception:
            pass
        # Lazy load label
        try:
            if card.pkg and card.pkg not in self._label_cache:
                self._fetch_label_for_pkg(card.pkg)
        except Exception:
            pass

    def _fetch_label_for_pkg(self, pkg: str):
        if not pkg:
            return
        if self._label_thread and self._label_thread.isRunning():
            return
        serial = self._get_default_serial()
        if not serial:
            return
        cmd = ['shell', 'dumpsys', 'package', pkg]
        self._label_pkg = pkg
        self._label_out = []
        self._label_thread = QThread(self)
        self._label_worker = _AdbCmdWorker(serial, cmd)
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

            # update visible card if present
            if pkg and label:
                for card in self._app_cards:
                    if card.pkg == pkg:
                        card.set_label(label)
                        break
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
        cmd = ['shell', 'dumpsys', 'package', pkg]
        self._disabled_out = []
        try:
            self.list_disabled.clear()
        except Exception:
            pass
        self._disabled_thread = QThread(self)
        self._disabled_worker = _AdbCmdWorker(serial, cmd)
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

        remote = ''
        try:
            remote = adb_service.adb_pm_path(serial, pkg, timeout=6)
        except Exception as e:
            self._toast('warn', '错误', f'获取 APK 路径失败: {e}')
            return
        if not remote:
            self._toast('warn', '提示', f'未找到 {pkg} 的安装路径')
            return

        self._write_oplog(serial, pkg, f"pull-apk {dst}")
        self._run_adb_cmd(['pull', remote, dst], op_desc='提取APK')

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

    def _toggle_auto_refresh(self, state):
        """切换自动刷新状态"""
        self._auto_refresh_enabled = (state == Qt.CheckState.Checked.value or state == 2)
        
        # Avoid toasting when change is not from user interaction.
        user_initiated = True
        try:
            user_initiated = bool(getattr(self, 'chk_auto_refresh', None) and self.chk_auto_refresh.hasFocus())
        except Exception:
            user_initiated = True

        if self._auto_refresh_enabled:
            # 开启自动刷新
            if self._timer is None:
                self._timer = QTimer(self)
                self._timer.setInterval(3000)
                self._timer.timeout.connect(self._refresh_foreground_now)
            if not self._timer.isActive():
                self._timer.start()
                # 立即执行一次
                QTimer.singleShot(100, self._refresh_foreground_now)
            if user_initiated:
                try:
                    InfoBar.success(
                        "自动刷新",
                        "已开启自动刷新，每3秒更新一次",
                        parent=self,
                        position=InfoBarPosition.TOP,
                        duration=2000
                    )
                except Exception:
                    pass
        else:
            # 关闭自动刷新
            if self._timer is not None and self._timer.isActive():
                self._timer.stop()
            if user_initiated:
                try:
                    InfoBar.info(
                        "自动刷新",
                        "已关闭自动刷新，点击“立即刷新”按钮手动获取",
                        parent=self,
                        position=InfoBarPosition.TOP,
                        duration=2000
                    )
                except Exception:
                    pass
    
    def _start_foreground_timer(self):
        """仅在用户开启自动刷新时调用"""
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(3000)
            self._timer.timeout.connect(self._refresh_foreground_now)
        if not self._timer.isActive():
            self._timer.start()

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
        self.lbl_pkg.setText(self._current_pkg or '-')
        self.lbl_act.setText(self._current_activity or '-')

    def _refresh_foreground_now(self):
        serial = self._get_default_serial()
        if not serial:
            try:
                serials = adb_service.list_devices()
            except Exception:
                serials = []
            if not serials:
                self.lbl_dev.setText('未检测到')
            else:
                self.lbl_dev.setText(f'检测到多个设备({len(serials)})')
            self.lbl_pkg.setText('-')
            self.lbl_act.setText('-')
            self._current_pkg = ""
            self._current_activity = ""
            return

        self.lbl_dev.setText(serial)

        if self._fg_worker is None:
            return
        self._fg_request.emit(serial)

    def cleanup(self):
        # 优化清理顺序，先停止定时器，再清理线程
        try:
            if self._timer is not None:
                try:
                    self._timer.stop()
                    self._timer.deleteLater()
                    self._timer = None
                except Exception:
                    pass
        except Exception:
            pass
        
        # 清理前台刷新线程
        try:
            if self._fg_thread and self._fg_thread.isRunning():
                self._fg_thread.quit()
                if not self._fg_thread.wait(1000):
                    self._fg_thread.terminate()
                self._fg_thread = None
                self._fg_worker = None
        except Exception:
            pass
        
        # 清理命令执行线程
        try:
            if self._worker:
                self._worker.stop()
        except Exception:
            pass
        try:
            if self._thread and self._thread.isRunning():
                self._thread.quit()
                if not self._thread.wait(1000):
                    self._thread.terminate()
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
