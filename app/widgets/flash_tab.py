import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QObject, QThread, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QCheckBox, QGridLayout, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout, QWidget, QInputDialog
from qfluentwidgets import (
    CardWidget,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    MessageBox,
    SmoothScrollArea,
)

from app.services import adb_service
from app.logic import SideloadFlashLogic, MiFlashLogic, OJZFlashLogic
from app.logic.ojz import OJZPackageLoader


class _DeviceWatcher(QObject):
    """设备状态监听器（后台线程）"""
    status_changed = Signal(str, str)  # (mode, serial)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = False
        self._paused = False
        self._last_state = ""
    
    def stop(self):
        self._stop = True
    
    def pause(self):
        """暂停监听（刷机过程中使用）"""
        self._paused = True
    
    def resume(self):
        """恢复监听"""
        self._paused = False
    
    def run(self):
        """在后台线程中运行"""
        import time
        from app.services import adb_service
        
        while not self._stop:
            try:
                # 如果暂停，跳过检测
                if not self._paused:
                    mode, serial = adb_service.detect_connection_mode()
                    current_state = f"{mode}:{serial}"
                    
                    # 只在状态变化时发送信号
                    if current_state != self._last_state:
                        self._last_state = current_state
                        self.status_changed.emit(mode, serial)
            except Exception:
                pass  # 静默失败
            
            # 等待 2 秒，但每 0.1 秒检查一次停止标志
            for _ in range(20):
                if self._stop:
                    break
                time.sleep(0.1)


class _FlashWorker(QObject):
    """刷机工作线程"""
    log_signal = Signal(str)
    finished = Signal(bool, str)  # (success, message)
    
    def __init__(self, mode: int, path: str, parent_tab=None):
        super().__init__()
        self.mode = mode
        self.path = path
        self.parent_tab = parent_tab  # 引用父 Tab 以访问刷机方法
        self._cancelled = False
        self._logic = None
    
    def cancel(self):
        self._cancelled = True
        try:
            if self._logic is not None and hasattr(self._logic, 'stop'):
                self._logic.stop()
        except Exception:
            pass
    
    def run(self):
        """在后台线程中执行刷机"""
        try:
            if self.mode == 0:  # ADB Sideload
                self._flash_sideload()
            elif self.mode == 1:  # 小米线刷脚本
                self._flash_miflash()
            elif self.mode == 2:  # 欧加真（OPPO/一加/真我）
                self._flash_ojz()
        except Exception as e:
            self.log_signal.emit(f"刷机异常: {e}")
            self.finished.emit(False, str(e))
    
    def _flash_sideload(self):
        """Sideload 刷机逻辑"""
        self.log_signal.emit("=" * 50)
        self.log_signal.emit("ADB Sideload 模式")
        self.log_signal.emit("=" * 50)
        try:
            self._logic = SideloadFlashLogic(log_callback=self.log_signal.emit)
            success = self._logic.flash_ota(self.path)
            
            if success:
                self.finished.emit(True, "OTA 包刷入完成")
            else:
                self.finished.emit(False, "OTA 包刷入失败")
        except Exception as e:
            self.log_signal.emit(f"Sideload 刷机异常: {e}")
            self.finished.emit(False, str(e))
        finally:
            self._logic = None

    def _flash_ojz(self):
        """欧加真刷机逻辑"""
        self.log_signal.emit("=" * 50)
        self.log_signal.emit("欧加真（OPPO/一加/真我）刷机模式")
        self.log_signal.emit("=" * 50)
        try:
            # 获取选中的子模式
            sub_mode = "常规升级/降级模式"
            try:
                if self.parent_tab and hasattr(self.parent_tab, 'ojz_submode_combo'):
                    sub_mode = self.parent_tab.ojz_submode_combo.currentText()
            except Exception:
                pass

            avb_relaxed = False
            try:
                if self.parent_tab and hasattr(self.parent_tab, 'avb_relaxed_check'):
                    avb_relaxed = bool(self.parent_tab.avb_relaxed_check.isChecked())
            except Exception:
                avb_relaxed = False

            anti_fuse = False
            try:
                if self.parent_tab and hasattr(self.parent_tab, 'anti_fuse_check'):
                    anti_fuse = bool(self.parent_tab.anti_fuse_check.isChecked())
            except Exception:
                anti_fuse = False

            fastbootd_continue = False
            try:
                if self.parent_tab and hasattr(self.parent_tab, '_ojz_fastbootd_continue'):
                    fastbootd_continue = bool(getattr(self.parent_tab, '_ojz_fastbootd_continue'))
            except Exception:
                fastbootd_continue = False

            # 常规模式基于“加载固件”得到的散包目录进行刷写
            images_dir = ""
            try:
                if self.parent_tab and hasattr(self.parent_tab, '_ojz_images_dir'):
                    images_dir = str(getattr(self.parent_tab, '_ojz_images_dir') or '')
            except Exception:
                images_dir = ""

            if sub_mode in {"常规升级/降级模式", "fastbootd模式修复", "super分区异常修复"} and not images_dir:
                self.finished.emit(False, "请先点击“加载固件”，确保散包已解包并校验通过")
                return

            self._logic = OJZFlashLogic(log_callback=self.log_signal.emit)
            package_path = images_dir if (sub_mode in {"常规升级/降级模式", "fastbootd模式修复", "super分区异常修复"}) else self.path
            # 常规模式的清数据由 UI 在刷完后弹窗确认执行；不要在这里提前 fastboot -w
            success = self._logic.flash(
                package_path,
                sub_mode=sub_mode,
                wipe=False,
                avb_relaxed=avb_relaxed,
                anti_fuse=anti_fuse,
                fastbootd_continue=fastbootd_continue,
                super_img_path=str(getattr(self.parent_tab, '_ojz_super_img', '') or ''),
            )
            if success:
                self.finished.emit(True, "欧加真刷机完成")
            else:
                self.finished.emit(False, "欧加真刷机失败")
        except Exception as e:
            self.log_signal.emit(f"欧加真刷机异常: {e}")
            self.finished.emit(False, str(e))
        finally:
            self._logic = None

    def _flash_miflash(self):
        """小米线刷脚本逻辑"""
        self.log_signal.emit("=" * 50)
        self.log_signal.emit("小米线刷脚本模式")
        self.log_signal.emit("=" * 50)
        try:
            self._logic = MiFlashLogic(log_callback=self.log_signal.emit)
            scripts = self._logic.list_available_scripts(self.path)
            if scripts:
                self.log_signal.emit(f"检测到 {len(scripts)} 个脚本: {', '.join(scripts)}")

            prefer_script = None
            try:
                wipe = False
                if self.parent_tab and hasattr(self.parent_tab, 'wipe_check'):
                    wipe = bool(self.parent_tab.wipe_check.isChecked())
                # 勾选“清除数据” => flash_all.bat（会清数据）
                # 未勾选 => flash_all_except_storage.bat（保留数据）
                prefer_script = 'flash_all.bat' if wipe else 'flash_all_except_storage.bat'
                if not (Path(self.path) / prefer_script).exists():
                    prefer_script = None
            except Exception:
                prefer_script = None

            if prefer_script:
                self.log_signal.emit(f"已根据选项选择脚本: {prefer_script}")

            success = self._logic.execute_flash_script(self.path, script_name=prefer_script)

            if success:
                self.finished.emit(True, "线刷脚本执行完成")
            else:
                self.finished.emit(False, "线刷脚本执行失败")
        except Exception as e:
            self.log_signal.emit(f"小米线刷异常: {e}")
            self.finished.emit(False, str(e))
        finally:
            self._logic = None


class _OJZLoadWorker(QObject):
    """欧加真：加载固件（解包/校验）工作线程"""

    log_signal = Signal(str)
    finished = Signal(bool, str, str)  # success, message, images_dir

    def __init__(self, ota_path: str, out_dir: str):
        super().__init__()
        self.ota_path = ota_path
        self.out_dir = out_dir
        self._loader: Optional[OJZPackageLoader] = None

    def cancel(self):
        try:
            if self._loader is not None:
                self._loader.stop()
        except Exception:
            pass

    def run(self):
        try:
            self._loader = OJZPackageLoader(log_callback=self.log_signal.emit)
            ok = self._loader.extract_all_from_ota(self.ota_path, self.out_dir)
            if not ok:
                self.finished.emit(False, "固件解包失败", "")
                return

            count = self._loader.count_partition_images(self.out_dir)
            self.log_signal.emit(f"解包完成，检测到分区镜像数量: {count}")
            if count < 46:
                self.finished.emit(False, f"分区数量不足（{count}/46），请更换固件包", "")
                return

            self.finished.emit(True, "固件加载完成", self.out_dir)
        except Exception as e:
            self.log_signal.emit(f"加载固件异常: {e}")
            self.finished.emit(False, str(e), "")
        finally:
            self._loader = None


class _OJZWipeWorker(QObject):
    """欧加真：可选的清除数据并重启（fastboot -w && fastboot reboot）"""

    log_signal = Signal(str)
    finished = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self._stop = False
        self._process = None

    def cancel(self):
        self._stop = True
        p = self._process
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def _resolve_fastboot(self) -> str:
        try:
            from app.services import adb_service

            fb = getattr(adb_service, 'FASTBOOT_BIN', None)
            if fb is not None and hasattr(fb, 'exists') and fb.exists():
                return str(fb)
        except Exception:
            pass
        return 'fastboot'

    def _run_cmd(self, args: list[str]) -> int:
        if self._stop:
            return 1
        import subprocess
        import os

        fb = self._resolve_fastboot()
        cmd = [fb] + list(args)
        self.log_signal.emit(f"$ {' '.join(cmd)}")

        startupinfo = None
        creationflags = 0
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        buf = ""
        out_lines: list[str] = []
        try:
            assert self._process.stdout is not None
            while True:
                if self._stop:
                    try:
                        self._process.terminate()
                    except Exception:
                        pass
                    return 1

                chunk = self._process.stdout.read(256)
                if chunk:
                    buf += chunk
                    while True:
                        import re

                        m = re.search(r"[\r\n]", buf)
                        if not m:
                            break
                        idx = int(m.start())
                        s = buf[:idx].strip("\r\n")
                        buf = buf[idx + 1 :]
                        if s:
                            self.log_signal.emit(s)
                            out_lines.append(s)
                    continue

                if self._process.poll() is not None:
                    break
                import time

                time.sleep(0.02)

            tail = buf.strip("\r\n")
            if tail:
                self.log_signal.emit(tail)
                out_lines.append(tail)

            return int(self._process.wait())
        finally:
            self._process = None

    def run(self):
        try:
            self.log_signal.emit("准备清除数据分区（fastboot -w）...")
            rc = self._run_cmd(['-w'])
            if rc != 0:
                self.finished.emit(False, 'fastboot -w 执行失败')
                return
            self.log_signal.emit("清除完成，重启设备...")
            rc2 = self._run_cmd(['reboot'])
            if rc2 != 0:
                self.finished.emit(False, 'fastboot reboot 执行失败')
                return
            self.finished.emit(True, '已清除数据并重启')
        except Exception as e:
            self.finished.emit(False, str(e))


class FlashTab(QWidget):
    log_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self._source_path: str = ""
        self._busy = False
        self._flashing = False
        self._last_flash_mode = -1
        self._last_ojz_submode = ""
        self._ojz_fastbootd_continue = False
        self._ojz_fastbootd_in_continuation = False
        self._watcher_thread = None  # 设备监听线程
        self._watcher_worker = None  # 设备监听工作对象
        self._flash_thread = None  # 刷机线程
        self._flash_worker = None  # 刷机工作对象

        self._ojz_load_thread = None
        self._ojz_load_worker = None
        self._ojz_images_dir: str = ""

        try:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.cleanup)
        except Exception:
            pass

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

        layout = QVBoxLayout(container)
        try:
            layout.setContentsMargins(24, 24, 24, 24)
        except Exception:
            pass

        banner_w = QWidget(self)
        try:
            banner_w.setFixedHeight(110)
        except Exception:
            pass
        try:
            banner_w.setStyleSheet("background: transparent;")
        except Exception:
            pass
        try:
            banner_w.setAttribute(Qt.WA_TranslucentBackground, True)
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
                _ico = FluentIcon.COMMAND_PROMPT.icon()
                icon_lbl.setPixmap(_ico.pixmap(48, 48))
            except Exception:
                pass
        except Exception:
            pass

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)

        title = QLabel("刷机中心", banner_w)
        try:
            title.setStyleSheet("font-size: 22px; font-weight: 600;")
        except Exception:
            pass
        sub = QLabel("智能一键刷机", banner_w)
        try:
            sub.setStyleSheet("font-size: 14px;")
        except Exception:
            pass

        title_col.addWidget(title)
        title_col.addWidget(sub)
        banner.addWidget(icon_lbl)
        banner.addLayout(title_col)
        banner.addStretch(1)
        layout.addWidget(banner_w)

        # 刷机包选择
        src_row = QHBoxLayout()
        self.combo_mode = ComboBox()
        self.combo_mode.addItems([
            "ADB Sideload",
            "小米线刷脚本",
            "欧加真（OPPO/一加/真我）刷机模式",
        ])
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        
        self.path_edit = LineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("选择刷机包文件夹路径")
        try:
            self.path_edit.setClearButtonEnabled(False)
        except Exception:
            pass

        self.btn_pick = PushButton("选择目录")
        self.btn_pick.clicked.connect(self._pick_source)

        src_row.addWidget(QLabel("刷机模式:"))
        src_row.addWidget(self.combo_mode, 1)
        src_row.addWidget(self.path_edit, 3)
        src_row.addWidget(self.btn_pick)

        # OJZ 子模式选择与帮助（仅当选择 OJZ 模式时显示）
        ojz_row = QHBoxLayout()
        self.ojz_submode_label = QLabel("刷机类型:")
        self.ojz_submode_combo = ComboBox()
        self.ojz_submode_combo.addItems([
            "常规升级/降级模式",
            "fastbootd模式修复",
            "super分区异常修复",
        ])
        self.ojz_submode_combo.setCurrentIndex(0)
        self.btn_ojz_help = PushButton("？")
        self.btn_ojz_help.setFixedSize(36, 32)
        self.btn_ojz_help.clicked.connect(self._show_ojz_help)
        self.btn_ojz_load = PrimaryPushButton("加载固件")
        self.btn_ojz_load.clicked.connect(self._load_ojz_firmware)
        ojz_row.addWidget(self.ojz_submode_label)
        ojz_row.addWidget(self.ojz_submode_combo, 1)
        ojz_row.addWidget(self.btn_ojz_help)
        ojz_row.addWidget(self.btn_ojz_load)
        ojz_row.addStretch(1)
        # 默认隐藏 OJZ 子模式行
        self.ojz_row_widget = QWidget()
        self.ojz_row_widget.setLayout(ojz_row)
        self.ojz_row_widget.setVisible(False)

        status_row = QHBoxLayout()
        self.status_conn = QLabel("设备：未连接")
        self.status_mode = QLabel("模式：未知")
        self.refresh_btn = PushButton("刷新状态")
        self.refresh_btn.clicked.connect(self.refresh_status)
        status_row.addWidget(self.status_conn)
        status_row.addSpacing(12)
        status_row.addWidget(self.status_mode)
        status_row.addStretch(1)
        status_row.addWidget(self.refresh_btn)

        opt_row = QHBoxLayout()
        self.wipe_check = QCheckBox("清除数据(出厂重置)")
        self.wipe_check.setChecked(False)
        self.avb_relaxed_check = QCheckBox("宽容AVB")
        self.avb_relaxed_check.setChecked(False)
        self.anti_fuse_check = QCheckBox("欧加真防熔断")
        self.anti_fuse_check.setChecked(False)
        opt_row.addWidget(self.wipe_check)
        opt_row.addWidget(self.avb_relaxed_check)
        opt_row.addWidget(self.anti_fuse_check)
        opt_row.addStretch(1)

        run_row = QHBoxLayout()
        self.run_btn = PrimaryPushButton("开始刷机")
        self.cancel_btn = PushButton("取消")
        self.cancel_btn.setEnabled(True)
        self.save_log_btn = PushButton("保存日志")
        run_row.addWidget(self.run_btn)
        run_row.addWidget(self.cancel_btn)
        run_row.addWidget(self.save_log_btn)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        try:
            from PySide6.QtCore import Qt as _Qt
            self.log.setVerticalScrollBarPolicy(_Qt.ScrollBarAlwaysOff)
            self.log.setHorizontalScrollBarPolicy(_Qt.ScrollBarAlwaysOff)
            self.log.setStyleSheet("background: transparent;")
        except Exception:
            pass
        self.log_view = SmoothScrollArea(self)
        try:
            self.log_view.setWidget(self.log)
            self.log_view.setWidgetResizable(True)
        except Exception:
            pass
        
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        card_pkg = CardWidget(self)
        v_pkg = QVBoxLayout(card_pkg)
        v_pkg.setContentsMargins(16, 16, 16, 16)
        v_pkg.setSpacing(10)
        h_pkg = QHBoxLayout()
        h_pkg.setSpacing(8)
        h_pkg_icon = QLabel("📦")
        h_pkg_icon.setStyleSheet("font-size:16px;")
        h_pkg_title = QLabel("刷机模式")
        h_pkg_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_pkg.addWidget(h_pkg_icon)
        h_pkg.addWidget(h_pkg_title)
        h_pkg.addStretch(1)
        v_pkg.addLayout(h_pkg)
        v_pkg.addLayout(src_row)
        v_pkg.addWidget(self.ojz_row_widget)

        card_status = CardWidget(self)
        v_stat = QVBoxLayout(card_status)
        v_stat.setContentsMargins(16, 16, 16, 16)
        v_stat.setSpacing(10)
        h_stat = QHBoxLayout()
        h_stat.setSpacing(8)
        h_stat_icon = QLabel("🔌")
        h_stat_icon.setStyleSheet("font-size:16px;")
        h_stat_title = QLabel("设备状态")
        h_stat_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_stat.addWidget(h_stat_icon)
        h_stat.addWidget(h_stat_title)
        h_stat.addStretch(1)
        v_stat.addLayout(h_stat)
        v_stat.addLayout(status_row)

        card_opt = CardWidget(self)
        v_opt = QVBoxLayout(card_opt)
        v_opt.setContentsMargins(16, 16, 16, 16)
        v_opt.setSpacing(10)
        h_opt = QHBoxLayout()
        h_opt.setSpacing(8)
        h_opt_icon = QLabel("⚙️")
        h_opt_icon.setStyleSheet("font-size:16px;")
        h_opt_title = QLabel("选项")
        h_opt_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_opt.addWidget(h_opt_icon)
        h_opt.addWidget(h_opt_title)
        h_opt.addStretch(1)
        v_opt.addLayout(h_opt)
        v_opt.addLayout(opt_row)

        card_act = CardWidget(self)
        v_act = QVBoxLayout(card_act)
        v_act.setContentsMargins(16, 16, 16, 16)
        v_act.setSpacing(10)
        h_act = QHBoxLayout()
        h_act.setSpacing(8)
        h_act_icon = QLabel("▶️")
        h_act_icon.setStyleSheet("font-size:16px;")
        h_act_title = QLabel("操作")
        h_act_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_act.addWidget(h_act_icon)
        h_act.addWidget(h_act_title)
        h_act.addStretch(1)
        v_act.addLayout(h_act)
        v_act.addLayout(run_row)

        card_log = CardWidget(self)
        v_log = QVBoxLayout(card_log)
        v_log.setContentsMargins(16, 16, 16, 16)
        v_log.setSpacing(10)
        h_log = QHBoxLayout()
        h_log.setSpacing(8)
        h_log_icon = QLabel("📝")
        h_log_icon.setStyleSheet("font-size:16px;")
        h_log_title = QLabel("刷机日志")
        h_log_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_log.addWidget(h_log_icon)
        h_log.addWidget(h_log_title)
        h_log.addStretch(1)
        v_log.addLayout(h_log)
        v_log.addWidget(self.log_view)

        grid.addWidget(card_pkg, 0, 0, 1, 2)
        grid.addWidget(card_status, 2, 0, 1, 2)
        grid.addWidget(card_opt, 3, 0)
        grid.addWidget(card_act, 3, 1)
        grid.addWidget(card_log, 4, 0, 1, 2)
        layout.addLayout(grid)

        self.run_btn.clicked.connect(self.start_flash)
        self.cancel_btn.clicked.connect(self.cancel)
        self.save_log_btn.clicked.connect(self.save_log)
        self.log_signal.connect(self.log.append)

        try:
            self.anti_fuse_check.toggled.connect(self._on_anti_fuse_toggled)
        except Exception:
            pass

        # 启动设备状态监听
        QTimer.singleShot(0, self.refresh_status)
        self._start_device_watcher()

    # ---------- Slots ----------
    def _on_mode_changed(self, index: int):
        """刷机模式切换"""
        if index == 0:  # ADB Sideload
            self.path_edit.setPlaceholderText("选择 OTA 升级包 (.zip)")
            self.btn_pick.setText("选择文件")
            self.ojz_row_widget.setVisible(False)
        elif index == 1:  # 小米线刷脚本
            self.path_edit.setPlaceholderText("选择线刷包目录（包含 flash_all.bat）")
            self.btn_pick.setText("选择目录")
            self.ojz_row_widget.setVisible(False)
        elif index == 2:  # 欧加真
            self.path_edit.setPlaceholderText("选择OTA全量包或解包后的散包目录")
            self.btn_pick.setText("选择")
            self.ojz_row_widget.setVisible(True)
        
        # 清空路径
        self.path_edit.clear()
        self._source_path = ""
    
    def _pick_source(self):
        mode = self.combo_mode.currentIndex()
        
        if mode == 0:  # ADB Sideload
            path, _ = QFileDialog.getOpenFileName(self, "选择 OTA 包", "", "OTA 包 (*.zip);;All (*.*)")
        elif mode == 1:  # 小米线刷脚本
            path = QFileDialog.getExistingDirectory(self, "选择小米线刷包目录")
        elif mode == 2:  # 欧加真
            path, _ = QFileDialog.getOpenFileName(self, "选择刷机包", "", "All (*.*)")
            if not path:
                path = QFileDialog.getExistingDirectory(self, "选择刷机目录")

        if path:
            self._source_path = path
            self.path_edit.setText(path)
            if mode == 2:
                self._ojz_images_dir = ""

    def _show_ojz_help(self):
        """显示欧加真子模式帮助弹窗"""
        help_text = (
            "常规升级/降级模式：\n"
            "适用于设备状态正常（可以正常开机时或已知的分区刷写错误）的刷机操作，建议优先选择。\n\n"
            "fastbootd模式修复：\n"
            "适用于设备只能进入bootloader模式，但无法进入fastbootd用户空间的情况。\n"
            "注意：此模式下。你必须选择与你设备已经搭载的相同安卓版本的固件包 例如：设备目前运行15.0.0.700，你需要选择15.X.X.XXX，而不是14.X.X.XXX。\n\n"
            "super分区异常修复：\n"
            "适用于常规刷机时，屡次报错刷不进或多次刷机完成后无法开机的情况。\n\n"
            "当设备处于黑屏无反应的状态时，不适用于以上的所有办法，则需要进行EDL刷机，你需要前往就近的售后服务中心进行处理。\n"
            "友情提示：当你被所谓的格机脚本或外挂恶意损毁设备的情形，那么很不幸，即便是前往售后服务中心也是无济于事的。"
        )
        msg = MessageBox("如何选择🧐", help_text, self)
        msg.yesButton.setText("知道了")
        msg.cancelButton.setVisible(False)
        msg.exec()

    def _load_ojz_firmware(self):
        """欧加真：加载固件（解包 payload -> 镜像目录）"""
        if self._ojz_load_thread and self._ojz_load_thread.isRunning():
            self._toast_warning("提示", "正在加载固件，请稍候...")
            return

        if self.combo_mode.currentIndex() != 2:
            self._toast_warning("提示", "请先切换到欧加真刷机模式")
            return

        src = self.path_edit.text().strip()
        if not src:
            self._toast_warning("提示", "请先选择 OTA 全量包或散包目录")
            return

        # 如果用户直接选择了解包后的目录，则只做数量校验
        if os.path.isdir(src):
            count = OJZPackageLoader.count_partition_images(src)
            self.append_log(f"散包目录镜像数量: {count}")
            if count < 46:
                self._toast_warning("错误", f"分区数量不足（{count}/46）")
                return
            self._ojz_images_dir = src
            self._toast_success("成功", "固件已加载")
            return

        # OTA zip 解包
        if not os.path.isfile(src):
            self._toast_warning("提示", "选择的路径无效")
            return

        ota_parent = str(Path(src).resolve().parent)
        min_free = 25 * 1024 * 1024 * 1024
        free = OJZPackageLoader.free_space_bytes(ota_parent)
        out_dir = ota_parent
        if free < min_free:
            # 让用户选择解包目录（有足够空间）
            picked = QFileDialog.getExistingDirectory(self, "磁盘空间不足，请选择解包输出目录")
            if not picked:
                self._toast_warning("已取消", "未选择输出目录")
                return
            free2 = OJZPackageLoader.free_space_bytes(picked)
            if free2 < min_free:
                self._toast_warning("错误", "输出目录磁盘空间仍不足 25GB")
                return
            out_dir = picked

        # 默认输出到 out_dir 下的同名文件夹
        stem = Path(src).stem
        images_dir = str(Path(out_dir) / f"{stem}_extracted")

        self.log.clear()
        self.append_log(f"开始加载固件: {src}")
        self.append_log(f"解包输出目录: {images_dir}")

        self.btn_ojz_load.setEnabled(False)
        self._ojz_load_thread = QThread(self)
        self._ojz_load_worker = _OJZLoadWorker(src, images_dir)
        self._ojz_load_worker.moveToThread(self._ojz_load_thread)

        self._ojz_load_thread.started.connect(self._ojz_load_worker.run)
        self._ojz_load_worker.log_signal.connect(self.append_log)
        self._ojz_load_worker.finished.connect(self._on_ojz_load_finished)
        self._ojz_load_thread.start()

    def _on_ojz_load_finished(self, success: bool, message: str, images_dir: str):
        try:
            if self._ojz_load_thread:
                self._ojz_load_thread.quit()
                self._ojz_load_thread.wait(3000)
        except Exception:
            pass
        self._ojz_load_thread = None
        self._ojz_load_worker = None
        self.btn_ojz_load.setEnabled(True)

        if success:
            self._ojz_images_dir = images_dir
            self.append_log(f"\n✅ {message}")
            self._toast_success("成功", message)
        else:
            self._ojz_images_dir = ""
            self.append_log(f"\n❌ {message}")
            self._toast_warning("失败", message)

    # ---------- Public API ----------
    def _start_device_watcher(self):
        """启动设备状态监听器（后台线程）"""
        if self._watcher_thread is not None:
            return  # 已经在运行
        
        self._watcher_thread = QThread(self)
        self._watcher_worker = _DeviceWatcher()
        self._watcher_worker.moveToThread(self._watcher_thread)
        
        # 连接信号
        self._watcher_thread.started.connect(self._watcher_worker.run)
        self._watcher_worker.status_changed.connect(self._on_device_status_changed)
        try:
            self._watcher_thread.finished.connect(self._watcher_thread.deleteLater)
            self._watcher_worker.destroyed.connect(lambda: None)
        except Exception:
            pass
        
        # 启动线程
        self._watcher_thread.start()
    
    def _stop_device_watcher(self):
        """停止设备状态监听器"""
        if self._watcher_worker:
            self._watcher_worker.stop()
        
        if self._watcher_thread:
            try:
                if self._watcher_thread.isRunning():
                    self._watcher_thread.quit()
            except Exception:
                pass
            try:
                self._watcher_thread.wait(3000)
            except Exception:
                pass
            try:
                self._watcher_thread.deleteLater()
            except Exception:
                pass
            self._watcher_thread = None
            self._watcher_worker = None
    
    def _on_device_status_changed(self, mode: str, serial: str):
        """设备状态变化回调（在 UI 线程中执行）"""
        self.refresh_status()
    
    def refresh_status(self):
        """刷新设备状态显示"""
        summary = adb_service.connection_summary()
        self.status_conn.setText(summary.get("status_conn", "设备：未连接"))
        self.status_mode.setText(summary.get("status_mode", "模式：未知"))

    def start_flash(self):
        """启动刷机"""
        if self._flash_thread and self._flash_thread.isRunning():
            self._toast_warning("提示", "刷机正在进行中...")
            return
        
        mode = self.combo_mode.currentIndex()
        path = self.path_edit.text().strip()

        if not path:
            self._toast_warning("提示", "请先选择文件或目录。")
            return

        # 验证路径
        if mode == 1:  # 小米线刷脚本需要文件夹
            if not os.path.isdir(path):
                self._toast_warning("提示", "选择的路径不是有效的文件夹。")
                return
        elif mode == 0:  # Sideload 需要文件
            if not os.path.isfile(path):
                self._toast_warning("提示", "选择的路径不是有效的文件。")
                return
        elif mode == 2:  # 欧加真：允许文件或文件夹
            if not (os.path.isfile(path) or os.path.isdir(path)):
                self._toast_warning("提示", "选择的路径无效。")
                return

        # 设备模式提示（小米线刷脚本）
        if mode == 1:
            try:
                from app.services import adb_service
                device_mode, serial = adb_service.detect_connection_mode()
                if device_mode not in ['bootloader', 'fastbootd']:
                    self._toast_warning(
                        "提示",
                        "当前设备不在 Bootloader/Fastbootd 模式，线刷脚本可能会失败\n你仍然可以继续"
                    )
            except Exception:
                pass
        from qfluentwidgets import MessageBox
        mode_names = ["ADB Sideload", "小米线刷脚本", "欧加真（OPPO/一加/真我）刷机模式"]
        
        msg_box = MessageBox(
            "确认刷机",
            f"即将开始 {mode_names[mode]}，请确认：\n\n"
            f"📁 路径：{path}\n"
            f"\n\n⚠️ 刷机有风险，请确保已备份重要数据！\n"
            f"是否继续？",
            self
        )
        msg_box.yesButton.setText("开始刷机")
        msg_box.cancelButton.setText("取消")
        
        if msg_box.exec() != MessageBox.Accepted:
            return

        if mode == 2:
            try:
                sub_mode = self.ojz_submode_combo.currentText()
            except Exception:
                sub_mode = ""

            if sub_mode == "super分区异常修复":
                super_img = self._prompt_ojz_super_image()
                if not super_img:
                    return
                self._ojz_super_img = str(super_img)
        
        # 清空日志
        self.log.clear()

        # 记录本次刷机上下文（用于结束后的 UI 流程，比如 OJZ 的可选清数据弹窗）
        self._last_flash_mode = mode
        try:
            self._last_ojz_submode = self.ojz_submode_combo.currentText() if mode == 2 else ""
        except Exception:
            self._last_ojz_submode = ""
        
        # 所有模式都使用后台线程
        
        # 禁用控件
        self._set_controls_enabled(False)
        self._flashing = True
        
        # 创建并启动刷机线程
        self._flash_thread = QThread(self)
        self._flash_worker = _FlashWorker(mode, path, parent_tab=self)
        self._flash_worker.moveToThread(self._flash_thread)
        
        # 暂停设备监听（刷机过程中设备可能短暂无响应）
        if self._watcher_worker:
            self._watcher_worker.pause()
        
        # 连接信号
        self._flash_thread.started.connect(self._flash_worker.run)
        self._flash_worker.log_signal.connect(self.append_log)
        self._flash_worker.finished.connect(self._on_flash_finished)
        
        # 启动线程
        self._flash_thread.start()
        self.append_log("刷机线程已启动...")

    def _prompt_ojz_super_image(self) -> str:
        base_dir = Path(__file__).resolve().parents[2] / 'bin' / 'super'
        if not base_dir.exists() or not base_dir.is_dir():
            self._toast_warning('提示', '未找到 bin/super 目录')
            return ''

        brands = sorted([p.name for p in base_dir.iterdir() if p.is_dir()])
        if not brands:
            self._toast_warning('提示', 'bin/super 下没有可用机型目录')
            return ''

        brand, ok = QInputDialog.getItem(self, '选择品牌', '请选择设备品牌:', brands, 0, False)
        if not ok or not brand:
            return ''

        brand_dir = base_dir / str(brand)
        models = sorted([p.name for p in brand_dir.iterdir() if p.is_dir()])
        if not models:
            self._toast_warning('提示', f'{brand} 目录下没有可用机型')
            return ''

        model, ok2 = QInputDialog.getItem(self, '选择机型', '请选择设备机型:', models, 0, False)
        if not ok2 or not model:
            return ''

        model_dir = brand_dir / str(model)
        imgs = sorted([p for p in model_dir.iterdir() if p.is_file() and p.suffix.lower() == '.img'], key=lambda x: x.name.lower())
        if not imgs:
            self._toast_warning('提示', '该机型目录下未找到 super 镜像')
            return ''

        if len(imgs) == 1:
            return str(imgs[0])

        img_names = [p.name for p in imgs]
        chosen, ok3 = QInputDialog.getItem(self, '选择 super 镜像', '请选择 super 镜像文件:', img_names, 0, False)
        if not ok3 or not chosen:
            return ''
        return str(model_dir / str(chosen))


    def _set_controls_enabled(self, enabled: bool):
        """启用/禁用控件"""
        self.run_btn.setEnabled(enabled)
        self.combo_mode.setEnabled(enabled)
        self.path_edit.setEnabled(enabled)
        self.btn_pick.setEnabled(enabled)
    
    def _on_flash_finished(self, success: bool, message: str):
        """刷机完成回调"""
        self._flashing = False
        # 恢复设备监听
        if self._watcher_worker:
            self._watcher_worker.resume()
        
        # 清理线程
        if self._flash_thread:
            self._flash_thread.quit()
            self._flash_thread.wait(3000)
            self._flash_thread = None
            self._flash_worker = None
        
        # 启用控件
        self._set_controls_enabled(True)
        
        # 显示结果
        if success:
            self.append_log(f"\n✅ {message}")
            self._toast_success("成功", message)

            # OJZ 常规模式：刷机完成后再询问是否清除数据（降级必须清）
            if self._last_flash_mode == 2 and self._last_ojz_submode == "常规升级/降级模式":
                self._prompt_ojz_wipe_and_reboot()

            # OJZ fastbootd 修复：阶段1完成后，询问是否继续刷逻辑分区
            if (
                self._last_flash_mode == 2
                and self._last_ojz_submode == "fastbootd模式修复"
                and not self._ojz_fastbootd_in_continuation
            ):
                self._prompt_ojz_fastbootd_continue()
        else:
            self.append_log(f"\n❌ {message}")
            self._toast_warning("失败", message)

    def _prompt_ojz_wipe_and_reboot(self):
        from qfluentwidgets import MessageBox

        default_wipe = False
        try:
            default_wipe = bool(self.wipe_check.isChecked())
        except Exception:
            default_wipe = False

        box = MessageBox(
            "是否格式化数据分区？",
            "常规刷机流程已完成。\n\n"
            "如果你在进行降级操作，通常必须清除数据分区，否则可能无法正常开机。\n\n"
            "是否立即执行 fastboot -w 清除数据并重启到系统？",
            self,
        )
        box.yesButton.setText("清除数据并重启")
        box.cancelButton.setText("不清除")

        # 勾选“清除数据” => 默认选择清除（回车直接执行 yes）
        try:
            if default_wipe and hasattr(box, 'yesButton'):
                box.yesButton.setDefault(True)
                box.yesButton.setFocus()
            elif hasattr(box, 'cancelButton'):
                box.cancelButton.setDefault(True)
                box.cancelButton.setFocus()
        except Exception:
            pass

        if box.exec() != MessageBox.Accepted:
            return

        if self._ojz_wipe_thread and self._ojz_wipe_thread.isRunning():
            self._toast_warning("提示", "正在清除数据，请稍候...")
            return

        self._set_controls_enabled(False)
        self.cancel_btn.setEnabled(True)

        self._ojz_wipe_thread = QThread(self)
        self._ojz_wipe_worker = _OJZWipeWorker()
        self._ojz_wipe_worker.moveToThread(self._ojz_wipe_thread)
        self._ojz_wipe_thread.started.connect(self._ojz_wipe_worker.run)
        self._ojz_wipe_worker.log_signal.connect(self.append_log)
        self._ojz_wipe_worker.finished.connect(self._on_ojz_wipe_finished)
        self._ojz_wipe_thread.start()

    def _on_anti_fuse_toggled(self, checked: bool):
        if not checked:
            return
        box = MessageBox(
            "提示",
            "Tips：防熔断模式是指防止设备EDL刷机熔断并防降级回滚，部分机型可能无效（只影响欧加真机型常规刷机，其他模式无效）",
            self,
        )
        box.yesButton.setText("知道了")
        box.cancelButton.setVisible(False)
        box.exec()

    def _prompt_ojz_fastbootd_continue(self):
        """fastbootd 修复：阶段1完成后提示是否继续刷入逻辑分区（只刷 A 槽）"""
        from qfluentwidgets import MessageBox

        box = MessageBox(
            "修复已完成",
            "已完成 fastbootd 修复的第一阶段（bootloader 分区刷写）。\n\n"
            "是否继续刷入逻辑分区（仅刷 A 槽）？",
            self,
        )
        box.yesButton.setText("继续刷逻辑分区")
        box.cancelButton.setText("结束")
        if box.exec() != MessageBox.Accepted:
            return

        if not getattr(self, '_ojz_images_dir', ''):
            self._toast_warning("提示", "未检测到已加载的散包目录")
            return

        if self._flash_thread and self._flash_thread.isRunning():
            self._toast_warning("提示", "刷机正在进行中...")
            return

        # start stage2
        self._ojz_fastbootd_continue = True
        self._ojz_fastbootd_in_continuation = True

        self.append_log("\n开始 fastbootd 修复第二阶段（刷逻辑分区，仅 A 槽）...")
        self._set_controls_enabled(False)
        self._flashing = True

        self._flash_thread = QThread(self)
        self._flash_worker = _FlashWorker(2, str(self._ojz_images_dir), parent_tab=self)
        self._flash_worker.moveToThread(self._flash_thread)

        if self._watcher_worker:
            self._watcher_worker.pause()

        self._flash_thread.started.connect(self._flash_worker.run)
        self._flash_worker.log_signal.connect(self.append_log)
        self._flash_worker.finished.connect(self._on_ojz_fastbootd_continue_finished)

        self._flash_thread.start()

    def _on_ojz_fastbootd_continue_finished(self, success: bool, message: str):
        # Clear the one-shot flag regardless of outcome
        self._ojz_fastbootd_continue = False
        self._ojz_fastbootd_in_continuation = False
        self._on_flash_finished(success, message)

    def _on_ojz_wipe_finished(self, success: bool, message: str):
        try:
            if self._ojz_wipe_thread:
                self._ojz_wipe_thread.quit()
                self._ojz_wipe_thread.wait(3000)
        except Exception:
            pass
        self._ojz_wipe_thread = None
        self._ojz_wipe_worker = None

        self._set_controls_enabled(True)

        if success:
            self.append_log(f"\n✅ {message}")
            self._toast_success("成功", message)
        else:
            self.append_log(f"\n❌ {message}")
            self._toast_warning("失败", message)

    def cancel(self):
        try:
            if self._flashing:
                self._flashing = False
                self.append_log("正在取消刷机...")
        except Exception:
            pass
        try:
            if self._flash_worker is not None:
                self._flash_worker.cancel()
        except Exception:
            pass
        try:
            if self._ojz_wipe_worker is not None:
                self._ojz_wipe_worker.cancel()
        except Exception:
            pass
        try:
            if self._ojz_load_worker is not None:
                self._ojz_load_worker.cancel()
        except Exception:
            pass
        try:
            self.run_btn.setEnabled(True)
            self.path_edit.setEnabled(True)
            self.btn_pick.setEnabled(True)
        except Exception:
            pass
        self.append_log("已请求取消当前任务")

    def save_log(self):
        text = self.log.toPlainText()
        if not text.strip():
            self._toast_info("提示", "当前没有可保存的日志。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存日志", "刷机日志.txt", "文本文件 (*.txt);;所有文件 (*.*)")
        if not path:
            return
        try:
            Path(path).write_text(text, encoding="utf-8")
            self._toast_success("提示", "日志已保存")
        except Exception as e:
            self._toast_warning("错误", f"保存失败: {e}")

    def cleanup(self):
        """清理资源"""
        self._stop_device_watcher()
        
        # 停止刷机线程
        if self._flash_thread and self._flash_thread.isRunning():
            if self._flash_worker:
                self._flash_worker.cancel()
            self._flash_thread.quit()
            self._flash_thread.wait(3000)
            self._flash_thread = None
            self._flash_worker = None
        
        self.cancel()

    def closeEvent(self, event):
        try:
            self.cleanup()
        except Exception:
            pass
        return super().closeEvent(event)

    # ---------- Small helpers ----------
    def append_log(self, text: str):
        self.log_signal.emit(text)

    def _toast_success(self, title: str, content: str, ms: int = 2500):
        InfoBar.success(title, content, parent=self, position=InfoBarPosition.TOP, duration=ms, isClosable=True)

    def _toast_warning(self, title: str, content: str):
        try:
            InfoBar.warning(title, content, parent=self, position=InfoBarPosition.TOP, duration=3000, isClosable=True)
        except Exception:
            pass

    def _toast_info(self, title: str, content: str, ms: int = 2500):
        InfoBar.info(title, content, parent=self, position=InfoBarPosition.TOP, duration=ms, isClosable=True)
