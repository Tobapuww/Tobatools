import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QObject, QThread, Signal
from PySide6.QtWidgets import QFileDialog, QCheckBox, QGridLayout, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import (
    CardWidget,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SmoothScrollArea,
)

from app.services import adb_service
from app.logic import SideloadFlashLogic, MiFlashLogic


class _DeviceWatcher(QObject):
    """设备状态监听器（后台线程）"""
    status_changed = Signal(str, str)  # (mode, serial)
    
    def __init__(self):
        super().__init__()
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
    progress_signal = Signal(int, int, int)  # (current_step, total_steps, percentage)
    
    def __init__(self, mode: int, path: str, config_path: Optional[str] = None, parent_tab=None):
        super().__init__()
        self.mode = mode
        self.path = path
        self.config_path = config_path
        self.parent_tab = parent_tab  # 引用父 Tab 以访问刷机方法
        self._cancelled = False
    
    def cancel(self):
        self._cancelled = True
    
    def run(self):
        """在后台线程中执行刷机"""
        try:
            if self.mode == 0:  # 散包刷机
                self._flash_scattered()
            elif self.mode == 1:  # ADB Sideload
                self._flash_sideload()
            elif self.mode == 2:  # 小米线刷脚本
                self._flash_miflash()
        except Exception as e:
            self.log_signal.emit(f"刷机异常: {e}")
            self.finished.emit(False, str(e))
    
    def _flash_scattered(self):
        """散包刷机逻辑"""
        if not self.parent_tab:
            self.finished.emit(False, "内部错误：无法访问刷机逻辑")
            return
        
        self.log_signal.emit("散包刷机模式启动...")
        
        try:
            # 扫描镜像
            images = self.parent_tab._scan_images(self.path)
            count = len(images)
            self.log_signal.emit(f"镜像目录: {self.path}")
            self.log_signal.emit(f"扫描到 {count} 个镜像文件")
            
            if count == 0:
                self.finished.emit(False, "未找到任何 .img 镜像文件")
                return
            
            if not self.config_path:
                self.finished.emit(False, "未选择配置文件")
                return
            
            # 解析配置
            self.log_signal.emit(f"加载配置: {self.config_path}")
            plan = self.parent_tab._parse_config(Path(self.config_path))
            
            if not plan:
                self.finished.emit(False, "配置文件解析失败")
                return
            
            self.log_signal.emit(f"配置解析成功: 设备={','.join(plan.get('devices') or [])}, 步骤数={len(plan['steps'])}")
            
            # 执行刷机计划（在后台线程中）
            watcher = self.parent_tab._watcher_worker if self.parent_tab else None
            self.parent_tab._run_flash_plan_in_thread(
                plan, 
                self.path, 
                self.log_signal.emit,
                progress_callback=lambda c, t, p: self.progress_signal.emit(c, t, p),
                watcher_worker=watcher
            )
            self.finished.emit(True, "散包刷机完成")
            
        except Exception as e:
            self.log_signal.emit(f"散包刷机异常: {e}")
            self.finished.emit(False, str(e))
    
    def _flash_sideload(self):
        """Sideload 刷机逻辑"""
        self.log_signal.emit("=" * 50)
        self.log_signal.emit("ADB Sideload 模式")
        self.log_signal.emit("=" * 50)
        try:
            logic = SideloadFlashLogic(log_callback=self.log_signal.emit)
            success = logic.flash_ota(self.path)
            
            if success:
                self.finished.emit(True, "OTA 包刷入完成")
            else:
                self.finished.emit(False, "OTA 包刷入失败")
        except Exception as e:
            self.log_signal.emit(f"Sideload 刷机异常: {e}")
            self.finished.emit(False, str(e))
    
    def _flash_miflash(self):
        """小米线刷脚本逻辑"""
        self.log_signal.emit("=" * 50)
        self.log_signal.emit("小米线刷脚本模式")
        self.log_signal.emit("=" * 50)
        try:
            logic = MiFlashLogic(log_callback=self.log_signal.emit)
            scripts = logic.list_available_scripts(self.path)
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

            success = logic.execute_flash_script(self.path, script_name=prefer_script)
            
            if success:
                self.finished.emit(True, "线刷脚本执行完成")
            else:
                self.finished.emit(False, "线刷脚本执行失败")
        except Exception as e:
            self.log_signal.emit(f"小米线刷异常: {e}")
            self.finished.emit(False, str(e))


class FlashTab(QWidget):
    log_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self._source_path: str = ""
        self._config_path: Optional[Path] = None
        self._busy = False
        self._flashing = False
        self._images_dir: Optional[Path] = None
        self._images: Dict[str, Path] = {}
        self._watcher_thread = None  # 设备监听线程
        self._watcher_worker = None  # 设备监听工作对象
        self._flash_thread = None  # 刷机线程
        self._flash_worker = None  # 刷机工作对象

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

        # 合并包选择和配置文件选择到同一行
        src_row = QHBoxLayout()
        self.combo_mode = ComboBox()
        self.combo_mode.addItems([
            "散包刷机（文件夹）",
            "ADB Sideload",
            "小米线刷脚本"
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
        
        self.config_edit = LineEdit()
        self.config_edit.setReadOnly(True)
        self.config_edit.setPlaceholderText("选择刷机配置脚本 (.txt)")
        self.btn_pick_config = PushButton("选择配置")
        self.btn_pick_config.clicked.connect(self._pick_config)

        src_row.addWidget(QLabel("刷机模式:"))
        src_row.addWidget(self.combo_mode, 1)
        src_row.addWidget(self.path_edit, 3)
        src_row.addWidget(self.btn_pick)
        src_row.addSpacing(16)
        src_row.addWidget(QLabel("配置脚本:"))
        src_row.addWidget(self.config_edit, 2)
        src_row.addWidget(self.btn_pick_config)

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
        opt_row.addWidget(self.wipe_check)
        opt_row.addSpacing(16)
        self.keep_root_check = QCheckBox("保留ROOT权限")
        try:
            self.keep_root_check.setToolTip("勾选此项将跳过刷入 boot.img")
        except Exception:
            pass
        opt_row.addWidget(self.keep_root_check)
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
        
        # 进度显示
        from qfluentwidgets import ProgressBar
        progress_container = QWidget()
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setContentsMargins(0, 8, 0, 0)
        progress_layout.setSpacing(8)
        
        self.progress_bar = ProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        
        progress_text_layout = QHBoxLayout()
        self.progress_label = QLabel("当前进度：0%")
        self.progress_label.setStyleSheet("font-size: 13px; color: #606060;")
        self.total_progress_label = QLabel("总进度：0%")
        self.total_progress_label.setStyleSheet("font-size: 13px; color: #606060;")
        progress_text_layout.addWidget(self.progress_label)
        progress_text_layout.addSpacing(16)
        progress_text_layout.addWidget(self.total_progress_label)
        progress_text_layout.addStretch(1)
        
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addLayout(progress_text_layout)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        card_pkg = CardWidget(self)
        v_pkg = QVBoxLayout(card_pkg)
        v_pkg.setContentsMargins(16, 16, 16, 16)
        v_pkg.setSpacing(10)
        h_pkg = QHBoxLayout()
        h_pkg.setSpacing(8)
        h_pkg_icon = QLabel("�")
        h_pkg_icon.setStyleSheet("font-size:16px;")
        h_pkg_title = QLabel("刷机模式")
        h_pkg_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_pkg.addWidget(h_pkg_icon)
        h_pkg.addWidget(h_pkg_title)
        h_pkg.addStretch(1)
        v_pkg.addLayout(h_pkg)
        v_pkg.addLayout(src_row)

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

        card_cfgdl = CardWidget(self)
        v_cfgdl = QVBoxLayout(card_cfgdl)
        v_cfgdl.setContentsMargins(16, 16, 16, 16)
        v_cfgdl.setSpacing(10)
        h_cfgdl = QHBoxLayout()
        h_cfgdl.setSpacing(8)
        h_cfgdl_icon = QLabel("⬇️")
        h_cfgdl_icon.setStyleSheet("font-size:16px;")
        h_cfgdl_title = QLabel("配置文件下载")
        h_cfgdl_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_cfgdl.addWidget(h_cfgdl_icon)
        h_cfgdl.addWidget(h_cfgdl_title)
        h_cfgdl.addStretch(1)
        v_cfgdl.addLayout(h_cfgdl)

        cfgdl_row = QHBoxLayout()
        cfgdl_row.setSpacing(8)
        self.btn_cfg_download = PushButton("打开仓库")
        self.btn_cfg_download.clicked.connect(self._open_cfg_repo)
        cfgdl_row.addWidget(self.btn_cfg_download)
        cfgdl_row.addStretch(1)
        v_cfgdl.addLayout(cfgdl_row)

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
        v_log.addWidget(progress_container)

        grid.addWidget(card_pkg, 0, 0, 1, 3)
        grid.addWidget(card_status, 2, 0, 1, 3)
        grid.addWidget(card_opt, 3, 0)
        grid.addWidget(card_cfgdl, 3, 1)
        grid.addWidget(card_act, 3, 2)
        grid.addWidget(card_log, 4, 0, 1, 3)
        layout.addLayout(grid)

        self.run_btn.clicked.connect(self.start_flash)
        self.cancel_btn.clicked.connect(self.cancel)
        self.save_log_btn.clicked.connect(self.save_log)
        self.log_signal.connect(self.log.append)

        # 启动设备状态监听
        QTimer.singleShot(0, self.refresh_status)
        self._start_device_watcher()

    # ---------- Slots ----------
    def _on_mode_changed(self, index: int):
        """刷机模式切换"""
        if index == 0:  # 散包刷机
            self.path_edit.setPlaceholderText("选择刷机包文件夹路径")
            self.btn_pick.setText("选择目录")
            if hasattr(self, 'card_config'):
                self.card_config.setVisible(True)  # 显示配置文件
        elif index == 1:  # ADB Sideload
            self.path_edit.setPlaceholderText("选择 OTA 升级包 (.zip)")
            self.btn_pick.setText("选择文件")
            if hasattr(self, 'card_config'):
                self.card_config.setVisible(False)  # 隐藏配置文件
        elif index == 2:  # 小米线刷脚本
            self.path_edit.setPlaceholderText("选择线刷包目录（包含 flash_all.bat）")
            self.btn_pick.setText("选择目录")
            if hasattr(self, 'card_config'):
                self.card_config.setVisible(False)  # 隐藏配置文件
        
        # 清空路径
        self.path_edit.clear()
        self._source_path = ""
    
    def _pick_source(self):
        mode = self.combo_mode.currentIndex()
        
        if mode == 0:  # 散包刷机
            path = QFileDialog.getExistingDirectory(self, "选择刷机包目录")
        elif mode == 1:  # ADB Sideload
            path, _ = QFileDialog.getOpenFileName(self, "选择 OTA 包", "", "OTA 包 (*.zip);;All (*.*)")
        elif mode == 2:  # 小米线刷脚本
            path = QFileDialog.getExistingDirectory(self, "选择小米线刷包目录")

        if path:
            self._source_path = path
            self.path_edit.setText(path)

    def _open_cfg_repo(self):
        url = "https://gitee.com/gyah/Tobatools-config-file"
        try:
            webbrowser.open(url)
        except Exception:
            self._toast_warning("打开失败", "无法打开链接，请手动复制到浏览器访问")

    def _pick_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择刷机配置脚本", "", "配置脚本 (*.txt);;所有文件 (*.*)")
        if path:
            self._config_path = Path(path)
            self.config_edit.setText(path)
            self.append_log(f"已选择配置文件: {path}")

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
                self._watcher_thread.wait(3000)  # 最多等待 3 秒
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

    def _scan_images(self, folder: str) -> Dict[str, Path]:
        images: Dict[str, Path] = {}
        try:
            for p in Path(folder).glob('*.img'):
                images[p.name.lower()] = p
        except Exception:
            pass
        return images

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
        if mode in [0, 2]:  # 散包刷机、小米线刷脚本需要文件夹
            if not os.path.isdir(path):
                self._toast_warning("提示", "选择的路径不是有效的文件夹。")
                return
        elif mode == 1:  # Sideload 需要文件
            if not os.path.isfile(path):
                self._toast_warning("提示", "选择的路径不是有效的文件。")
                return
        
        # 配置文件（散包刷机需要）
        config_path = None
        if mode == 0:
            if not self._config_path:
                self._toast_warning("提示", "请先选择刷机配置文件！")
                return
            config_path = str(self._config_path)

        # 设备模式检查
        # - 散包：强制要求 bootloader/fastbootd
        # - Sideload：不检查 fastboot
        # - 小米线刷脚本：不强制拦截（脚本失败与否由脚本自行决定）
        if mode == 0:
            from app.services import adb_service
            device_mode, serial = adb_service.detect_connection_mode()
            if device_mode not in ['bootloader', 'fastbootd']:
                self._toast_warning(
                    "提示",
                    "设备不在 Bootloader/Fastbootd 模式，无法开始刷机\n请先重启到 fastboot / fastbootd"
                )
                return
        elif mode == 2:
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
        mode_names = ["散包刷机", "ADB Sideload", "小米线刷脚本"]
        
        msg_box = MessageBox(
            "确认刷机",
            f"即将开始 {mode_names[mode]}，请确认：\n\n"
            f"📁 路径：{path}\n"
            f"{f'📄 配置：{config_path}' if config_path else ''}"
            f"\n\n⚠️ 刷机有风险，请确保已备份重要数据！\n"
            f"是否继续？",
            self
        )
        msg_box.yesButton.setText("开始刷机")
        msg_box.cancelButton.setText("取消")
        
        if msg_box.exec() != MessageBox.Accepted:
            return
        
        # 清空日志
        self.log.clear()
        
        # 所有模式都使用后台线程
        
        # 禁用控件
        self._set_controls_enabled(False)
        
        # 创建并启动刷机线程
        self._flash_thread = QThread(self)
        self._flash_worker = _FlashWorker(mode, path, config_path, parent_tab=self)
        self._flash_worker.moveToThread(self._flash_thread)
        
        # 暂停设备监听（刷机过程中设备可能短暂无响应）
        if self._watcher_worker:
            self._watcher_worker.pause()
        
        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("当前进度：0%")
        self.total_progress_label.setText("总进度：0%")
        
        # 连接信号
        self._flash_thread.started.connect(self._flash_worker.run)
        self._flash_worker.log_signal.connect(self.append_log)
        self._flash_worker.progress_signal.connect(self._on_progress_update)
        self._flash_worker.finished.connect(self._on_flash_finished)
        
        # 启动线程
        self._flash_thread.start()
        self.append_log("刷机线程已启动...")


    def _set_controls_enabled(self, enabled: bool):
        """启用/禁用控件"""
        self.run_btn.setEnabled(enabled)
        self.combo_mode.setEnabled(enabled)
        self.path_edit.setEnabled(enabled)
        self.btn_pick.setEnabled(enabled)
        self.btn_pick_config.setEnabled(enabled)
        self.config_edit.setEnabled(enabled)
    
    def _on_progress_update(self, current_step: int, total_steps: int, percentage: int):
        """进度更新回调"""
        self.progress_bar.setValue(percentage)
        self.progress_label.setText(f"当前步骤：{current_step}/{total_steps}")
        self.total_progress_label.setText(f"总进度：{percentage}%")
    
    def _on_flash_finished(self, success: bool, message: str):
        """刷机完成回调"""
        # 隐藏进度条
        self.progress_bar.setVisible(False)
        
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
        else:
            self.append_log(f"\n❌ {message}")
            self._toast_warning("失败", message)
    
    def _process_images_and_flash_worker(self, folder: str, config_path: str, log_func):
        """供后台线程调用的散包刷机逻辑"""
        images = self._scan_images(folder)
        count = len(images)
        log_func(f"镜像目录: {folder}")
        log_func(f"扫描到 {count} 个镜像文件")
        
        if count == 0:
            raise Exception("未找到任何 .img 镜像文件")
        
        if not config_path:
            raise Exception("未选择配置文件")
        
        log_func(f"加载配置: {config_path}")
        plan = self._parse_config(Path(config_path))
        
        if not plan:
            raise Exception("配置文件解析失败")
        
        log_func(f"配置解析成功: 设备={','.join(plan.get('devices') or [])}, 步骤数={len(plan['steps'])}")
        
        # 执行刷机计划（在后台线程中）
        self._run_flash_plan_worker(plan, folder, log_func)
    
    def _process_images_and_flash(self, folder):
        """UI 线程调用的散包刷机逻辑（已废弃，保留兼容）"""
        images = self._scan_images(folder)
        count = len(images)
        self.append_log(f"镜像目录: {folder}")
        self.append_log(f"扫描到 {count} 个镜像文件")
        
        if count == 0:
            self._toast_warning("提示", "未找到任何 .img 镜像文件")
            return
        
        if not self._config_path:
            self.append_log("错误: 未选择配置文件")
            self._toast_warning("错误", "请先选择刷机配置文件！")
            return
        
        self.append_log(f"加载配置: {self._config_path}")
        plan = self._parse_config(self._config_path)
        
        if not plan:
            self._toast_warning("错误", "配置文件解析失败！")
            return
        
        self.append_log(f"配置解析成功: 设备={','.join(plan.get('devices') or [])}, 步骤数={len(plan['steps'])}")
        if not self._verify_devices(plan.get('devices', [])):
            self._toast_warning("错误", "设备型号不匹配！")
            return
        self._run_flash_plan(plan, folder)

    def cancel(self):
        try:
            if self._flashing:
                self._flashing = False
                self.append_log("正在取消刷机...")
        except Exception:
            pass
        try:
            self.run_btn.setEnabled(True)
            self.path_edit.setEnabled(True)
            self.btn_pick.setEnabled(True)
            self.btn_pick_config.setEnabled(True)
            self.config_edit.setEnabled(True)
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

    def _popen_kwargs_silent(self) -> dict:
        if os.name == 'nt':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return {'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW}
        return {}

    def _resolve_fastboot(self) -> str:
        fb = adb_service.FASTBOOT_BIN
        if fb and fb.exists():
            return str(fb)
        return 'fastboot'

    def _run_fastboot(self, args: List[str], desc: str = "") -> tuple[bool, str]:
        fb = self._resolve_fastboot()
        cmd = [fb] + args
        try:
            if desc:
                self.append_log(f"执行: {desc}")
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=120,
                **self._popen_kwargs_silent()
            )
            output = result.stdout.strip()
            if output:
                for line in output.split('\n'):
                    if line.strip():
                        self.append_log(line.strip())
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            self.append_log(f"超时: {desc}")
            return False, ""
        except Exception as e:
            self.append_log(f"执行失败: {e}")
            return False, ""

    def _device_mode(self) -> str:
        fb = self._resolve_fastboot()
        try:
            result = subprocess.run(
                [fb, 'getvar', 'is-userspace'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
                **self._popen_kwargs_silent()
            )
            output = result.stdout.lower()
            if 'yes' in output:
                return 'fastbootd'
            return 'bootloader'
        except Exception:
            return 'unknown'

    def _ensure_mode(self, target_mode: str) -> bool:
        current = self._device_mode()
        if current == target_mode:
            return True
        
        self.append_log(f"当前模式: {current}，需要切换到: {target_mode}")
        fb = self._resolve_fastboot()
        
        if target_mode == 'fastbootd':
            self.append_log("正在重启到 fastbootd...")
            success, _ = self._run_fastboot(['reboot', 'fastboot'], "重启到 fastbootd")
            if not success:
                return False

            import time
            time.sleep(3)
            for i in range(10):
                if self._device_mode() == 'fastbootd':
                    self.append_log("已进入 fastbootd 模式")
                    return True
                time.sleep(1)
            self.append_log("切换到 fastbootd 超时")
            return False
        
        elif target_mode == 'bootloader':
            self.append_log("正在重启到 bootloader...")
            success, _ = self._run_fastboot(['reboot', 'bootloader'], "重启到 bootloader")
            if not success:
                return False
            import time
            time.sleep(3)
            for i in range(10):
                if self._device_mode() == 'bootloader':
                    self.append_log("已进入 bootloader 模式")
                    return True
                time.sleep(1)
            self.append_log("切换到 bootloader 超时")
            return False
        
        return False

    def _parse_config(self, config_path: Path) -> Optional[dict]:
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            devices: List[str] = []
            steps = []
            current_mode = None
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if line.startswith('device:'):
                    v = line.split(':', 1)[1].strip()
                    if v:
                        devices.append(v)
                    continue
                
                if line == 'bootloader':
                    current_mode = 'bootloader'
                    steps.append({'type': 'mode', 'mode': 'bootloader'})
                    continue
                
                if line == 'fastbootd':
                    current_mode = 'fastbootd'
                    steps.append({'type': 'mode', 'mode': 'fastbootd'})
                    continue
                
                if line == 'system':
                    steps.append({'type': 'reboot', 'target': 'system'})
                    continue
                
                if line == 'set-a':
                    steps.append({'type': 'set_slot', 'slot': 'a'})
                    continue
                
                if line == 'set-b':
                    steps.append({'type': 'set_slot', 'slot': 'b'})
                    continue
                
                if line == 'wipe-data':
                    continue
                
                if line.startswith('-'):
                    line = line[1:]
                    parts = line.split()
                    partition = parts[0]
                    
                    if len(parts) > 1:
                        if parts[1] == 'disable':
                            steps.append({
                                'type': 'flash',
                                'partition': partition,
                                'disable_avb': True,
                                'mode': current_mode
                            })
                        elif parts[1] == 'del':
                            steps.append({
                                'type': 'delete_logical',
                                'partition': partition,
                                'mode': current_mode
                            })
                        elif parts[1] == 'add' and len(parts) > 2:
                            steps.append({
                                'type': 'create_logical',
                                'partition': partition,
                                'size': parts[2],
                                'mode': current_mode
                            })
                    else:
                        steps.append({
                            'type': 'flash',
                            'partition': partition,
                            'disable_avb': False,
                            'mode': current_mode
                        })
            
            if not devices:
                self.append_log("错误: 配置文件缺少 device: 字段")
                return None
            
            return {
                'devices': devices,
                'steps': steps
            }
        
        except Exception as e:
            self.append_log(f"解析配置文件失败: {e}")
            return None

    def _verify_device(self, expected_device: str) -> bool:
        self.append_log(f"验证设备型号: {expected_device}")
        success, output = self._run_fastboot(['getvar', 'product'], "获取设备型号")
        if not success:
            self.append_log("错误: 无法获取设备型号")
            return False
        
        if expected_device.lower() in output.lower():
            self.append_log(f"设备验证成功: {expected_device}")
            return True
        else:
            self.append_log(f"错误: 设备型号不匹配！期望 {expected_device}，实际: {output}")
            return False

    def _verify_devices(self, expected_devices: List[str]) -> bool:
        expected_devices = [d.strip() for d in (expected_devices or []) if d and d.strip()]
        self.append_log(f"验证设备型号列表: {', '.join(expected_devices)}")
        success, output = self._run_fastboot(['getvar', 'product'], "获取设备型号")
        if not success:
            self.append_log("错误: 无法获取设备型号")
            return False

        product = (output or "").lower()
        for expected in expected_devices:
            if expected.lower() in product:
                self.append_log(f"设备验证成功: {expected}")
                return True

        self.append_log(f"错误: 设备型号不匹配！期望任一 {expected_devices}，实际: {output}")
        return False

    def _flash_partition(self, partition: str, disable_avb: bool = False) -> bool:
        # 处理 _ab 后缀（双槽刷写）
        if partition.endswith('_ab'):
            base_name = partition[:-3]
            if disable_avb:
                self.append_log(f"刷写 {partition} (禁用AVB)")
                for slot in ['a', 'b']:
                    slot_partition = f"{base_name}_{slot}"
                    img_name = f"{base_name}.img"
                    if img_name not in self._images:
                        self.append_log(f"警告: 未找到 {img_name}，跳过")
                        continue
                    img_path = str(self._images[img_name])
                    args = ['--disable-verity', '--disable-verification', 'flash', slot_partition, img_path]
                    success, _ = self._run_fastboot(args, f"刷写 {slot_partition} (禁用AVB)")
                    if not success:
                        return False
            else:
                img_name = f"{base_name}.img"
                if img_name not in self._images:
                    self.append_log(f"警告: 未找到 {img_name}，跳过")
                    return True
                
                if self.keep_root_check.isChecked() and base_name == 'boot':
                    self.append_log(f"跳过 {partition} (保留ROOT权限)")
                    return True
                
                img_path = str(self._images[img_name])
                for slot in ['a', 'b']:
                    slot_partition = f"{base_name}_{slot}"
                    success, _ = self._run_fastboot(['flash', slot_partition, img_path], f"刷写 {slot_partition}")
                    if not success:
                        return False
        
        # 处理 _a 或 _b 后缀（单槽刷写）
        elif partition.endswith('_a') or partition.endswith('_b'):
            base_name = partition[:-2]
            img_name = f"{base_name}.img"
            
            if img_name not in self._images:
                self.append_log(f"警告: 未找到 {img_name}，跳过")
                return True
            
            if self.keep_root_check.isChecked() and base_name == 'boot':
                self.append_log(f"跳过 {partition} (保留ROOT权限)")
                return True
            
            img_path = str(self._images[img_name])
            if disable_avb:
                args = ['--disable-verity', '--disable-verification', 'flash', partition, img_path]
                success, _ = self._run_fastboot(args, f"刷写 {partition} (禁用AVB)")
            else:
                success, _ = self._run_fastboot(['flash', partition, img_path], f"刷写 {partition}")
            return success
        
        # 处理无后缀（单槽刷写，不区分AB）
        else:
            img_name = f"{partition}.img"
            if img_name not in self._images:
                self.append_log(f"警告: 未找到 {img_name}，跳过")
                return True
            
            if self.keep_root_check.isChecked() and partition == 'boot':
                self.append_log(f"跳过 {partition} (保留ROOT权限)")
                return True
            
            img_path = str(self._images[img_name])
            if disable_avb:
                args = ['--disable-verity', '--disable-verification', 'flash', partition, img_path]
                success, _ = self._run_fastboot(args, f"刷写 {partition} (禁用AVB)")
            else:
                success, _ = self._run_fastboot(['flash', partition, img_path], f"刷写 {partition}")
            return success
        
        return True

    def _delete_logical_partition(self, partition: str) -> bool:
        targets = [partition, f"{partition}_a", f"{partition}_b", f"{partition}_a-cow", f"{partition}_b-cow"]
        self.append_log(f"删除逻辑分区: {partition}")
        
        for target in targets:
            success, output = self._run_fastboot(['delete-logical-partition', target], f"删除 {target}")
            if not success:
                if 'not find' in output.lower() or 'not exist' in output.lower():
                    self.append_log(f"提示: {target} 不存在，跳过（这不是错误）")
                else:
                    self.append_log(f"警告: 删除 {target} 失败，继续执行")
        
        return True

    def _create_logical_partition(self, partition: str, size: str) -> bool:
        self.append_log(f"创建逻辑分区: {partition} ({size})")
        success, _ = self._run_fastboot(['create-logical-partition', partition, size], f"创建 {partition}")
        return success

    def _set_active_slot(self, slot: str) -> bool:
        self.append_log(f"设置活动槽位: {slot}")
        success, _ = self._run_fastboot(['set_active', slot], f"设置活动槽位为 {slot}")
        if success:
            self.append_log(f"活动槽位已设置为: {slot}")
        else:
            self.append_log(f"警告: 设置活动槽位失败")
        return success

    def _wipe_data(self) -> bool:
        self.append_log("执行数据清除 (wipe-data)")
        
        success, _ = self._run_fastboot(['erase', 'userdata'], "清除 userdata")
        if not success:
            self.append_log("警告: 清除 userdata 失败")
        
        success, _ = self._run_fastboot(['erase', 'metadata'], "清除 metadata")
        if not success:
            self.append_log("警告: 清除 metadata 失败")
        
        success, _ = self._run_fastboot(['-w'], "执行 fastboot -w")
        if not success:
            self.append_log("警告: fastboot -w 失败")
        
        self.append_log("数据清除完成")
        return True

    def _run_flash_plan_in_thread(self, plan: dict, images_dir: str, log_func, progress_callback=None, watcher_worker=None):
        """在后台线程中执行刷机计划"""
        self._images_dir = Path(images_dir)
        self._images = self._scan_images(images_dir)
        
        log_func("=" * 50)
        log_func("开始执行刷机计划")
        log_func("=" * 50)
        
        # 计算总步骤数
        total_steps = len(plan['steps'])
        
        # 验证设备
        fb = self._resolve_fastboot()
        try:
            result = subprocess.run(
                [fb, 'getvar', 'product'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
                **self._popen_kwargs_silent()
            )
            output = result.stdout.lower()
            device_product = ""
            for line in output.split('\n'):
                if 'product:' in line:
                    device_product = line.split(':', 1)[-1].strip()
                    break
            
            expected_devices = [d.strip() for d in (plan.get('devices') or []) if d and d.strip()]
            if not expected_devices:
                raise Exception("配置文件缺少 device: 字段")

            ok = any(d.lower() in device_product for d in expected_devices)
            if not ok:
                raise Exception(f"设备型号不匹配：期望任一 {expected_devices}, 实际 {device_product}")

            log_func(f"设备验证成功: {device_product} (命中: {expected_devices})")
        except Exception as e:
            log_func(f"❌ 设备验证失败: {e}")
            raise
        
        # 执行步骤
        for i, step in enumerate(plan['steps'], 1):
            step_type = step['type']
            
            # 更新进度
            if progress_callback:
                percentage = int((i / total_steps) * 100)
                progress_callback(i, total_steps, percentage)
            
            if step_type == 'mode':
                target_mode = step['mode']
                log_func(f"切换到 {target_mode} 模式")
                
                # 检查当前模式
                fb = self._resolve_fastboot()
                try:
                    result = subprocess.run(
                        [fb, 'getvar', 'is-userspace'],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=5,
                        **self._popen_kwargs_silent()
                    )
                    output = result.stdout.lower()
                    current_mode = 'fastbootd' if 'yes' in output else 'bootloader'
                except Exception:
                    current_mode = 'unknown'
                
                # 如果已经在目标模式，跳过
                if current_mode == target_mode:
                    log_func(f"  已在 {target_mode} 模式")
                    continue
                
                # 执行模式切换
                if target_mode == 'fastbootd':
                    log_func("  正在重启到 fastbootd...")
                    try:
                        subprocess.run(
                            [fb, 'reboot', 'fastboot'],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            timeout=10,
                            **self._popen_kwargs_silent()
                        )
                    except subprocess.TimeoutExpired:
                        # 超时是正常的，因为设备会断开连接
                        log_func("  设备正在重启...")
                    except Exception as e:
                        log_func(f"  重启命令执行异常: {e}")
                    
                    # 倒计时等待
                    import time
                    wait_seconds = 15
                    for remaining in range(wait_seconds, 0, -1):
                        log_func(f"  等待设备重启... {remaining} 秒")
                        time.sleep(1)
                    log_func("  ✅ 已切换到 fastbootd 模式")
                
                elif target_mode == 'bootloader':
                    log_func("  正在重启到 bootloader...")
                    try:
                        subprocess.run(
                            [fb, 'reboot-bootloader'],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            timeout=10,
                            **self._popen_kwargs_silent()
                        )
                    except subprocess.TimeoutExpired:
                        # 超时是正常的，因为设备会断开连接
                        log_func("  设备正在重启...")
                    except Exception as e:
                        log_func(f"  重启命令执行异常: {e}")
                    
                    # 倒计时等待
                    import time
                    wait_seconds = 10
                    for remaining in range(wait_seconds, 0, -1):
                        log_func(f"  等待设备重启... {remaining} 秒")
                        time.sleep(1)
                    log_func("  ✅ 已切换到 bootloader 模式")
            
            elif step_type == 'flash':
                partition = step['partition']
                disable_avb = step.get('disable_avb', False)
                log_func(f"刷写 {partition}")
                
                # 处理分区名后缀，确定基础分区名
                if partition.endswith('_ab'):
                    # _ab 后缀：双槽刷写
                    is_ab = True
                    base_partition = partition[:-3]
                elif partition.endswith('_a') or partition.endswith('_b'):
                    # _a 或 _b 后缀：单槽刷写
                    is_ab = False
                    base_partition = partition[:-2]
                else:
                    # 无后缀：单槽刷写
                    is_ab = False
                    base_partition = partition
                
                # 查找镜像文件（使用基础分区名）
                img_name = f"{base_partition}.img"
                img_path = self._images.get(img_name.lower())
                
                if not img_path:
                    log_func(f"警告: 未找到 {img_name}，跳过")
                    continue
                
                # 执行刷写
                if is_ab:
                    # 双槽刷写：分别刷写 _a 和 _b
                    for slot in ['a', 'b']:
                        slot_partition = f"{base_partition}_{slot}"
                        cmd = [fb, 'flash', slot_partition, str(img_path)]
                        if disable_avb:
                            cmd.extend(['--disable-verity', '--disable-verification'])
                        
                        try:
                            result = subprocess.run(
                                cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                                timeout=120,
                                **self._popen_kwargs_silent()
                            )
                            if result.returncode == 0:
                                log_func(f"  ✅ {slot_partition} 刷写成功")
                            else:
                                log_func(f"  ❌ {slot_partition} 刷写失败，继续执行")
                        except subprocess.TimeoutExpired:
                            log_func(f"  ❌ {slot_partition} 刷写超时，继续执行")
                else:
                    # 单槽刷写
                    cmd = [fb, 'flash', partition, str(img_path)]
                    if disable_avb:
                        cmd.extend(['--disable-verity', '--disable-verification'])
                    
                    try:
                        result = subprocess.run(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            timeout=120,
                            **self._popen_kwargs_silent()
                        )
                        if result.returncode == 0:
                            log_func(f"✅ {partition} 刷写成功")
                        else:
                            log_func(f"❌ {partition} 刷写失败，继续执行")
                    except subprocess.TimeoutExpired:
                        log_func(f"❌ {partition} 刷写超时，继续执行")
            
            elif step_type == 'delete_logical':
                partition = step['partition']
                log_func(f"删除逻辑分区 {partition}")
                subprocess.run(
                    [fb, 'delete-logical-partition', partition],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=30,
                    **self._popen_kwargs_silent()
                )
            
            elif step_type == 'create_logical':
                partition = step['partition']
                size = step['size']
                log_func(f"创建逻辑分区 {partition} ({size})")
                try:
                    result = subprocess.run(
                        [fb, 'create-logical-partition', partition, size],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        timeout=30,
                        **self._popen_kwargs_silent()
                    )
                    if result.returncode == 0:
                        log_func(f"✅ 逻辑分区 {partition} 创建成功")
                    else:
                        log_func(f"❌ 逻辑分区 {partition} 创建失败，继续执行")
                except subprocess.TimeoutExpired:
                    log_func(f"❌ 逻辑分区 {partition} 创建超时，继续执行")
            
            elif step_type == 'set_slot':
                slot = step['slot']
                log_func(f"设置活动槽位 {slot}")
                subprocess.run(
                    [fb, 'set_active', slot],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=10,
                    **self._popen_kwargs_silent()
                )
            
            elif step_type == 'reboot':
                target = step['target']
                if target == 'bootloader':
                    log_func("重启到 bootloader")
                    try:
                        subprocess.run(
                            [fb, 'reboot-bootloader'],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            timeout=10,
                            **self._popen_kwargs_silent()
                        )
                    except subprocess.TimeoutExpired:
                        log_func("  设备正在重启...")
                    
                    # 临时恢复设备监听，等待设备重启完成
                    if watcher_worker:
                        watcher_worker.resume()
                    
                    import time
                    log_func("  等待设备重启到 bootloader...")
                    time.sleep(8)
                    log_func("  ✅ 设备已重启")
                    
                    # 重新暂停设备监听，继续刷机
                    if watcher_worker:
                        watcher_worker.pause()
                elif target == 'system':
                    # 检查是否需要清除数据
                    if hasattr(self, 'wipe_check'):
                        if self.wipe_check.isChecked():
                            log_func("清除数据 (出厂重置)")
                            
                            # 清除 userdata（可能需要较长时间）
                            log_func("  正在清除 userdata（大分区，请耐心等待）...")
                            try:
                                subprocess.run(
                                    [fb, 'erase', 'userdata'],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    timeout=180,  # 增加到 3 分钟
                                    **self._popen_kwargs_silent()
                                )
                                log_func("  ✅ userdata 清除成功")
                            except subprocess.TimeoutExpired:
                                log_func("  ⚠️ userdata 清除超时，跳过")
                            
                            # 清除 metadata
                            log_func("  正在清除 metadata...")
                            try:
                                subprocess.run(
                                    [fb, 'erase', 'metadata'],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    timeout=60,
                                    **self._popen_kwargs_silent()
                                )
                                log_func("  ✅ metadata 清除成功")
                            except subprocess.TimeoutExpired:
                                log_func("  ⚠️ metadata 清除超时，跳过")
                            
                            # 执行 fastboot -w
                            log_func("  执行 fastboot -w（格式化数据分区）...")
                            try:
                                subprocess.run(
                                    [fb, '-w'],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    timeout=180,  # 增加到 3 分钟
                                    **self._popen_kwargs_silent()
                                )
                                log_func("  ✅ fastboot -w 执行成功")
                            except subprocess.TimeoutExpired:
                                log_func("  ⚠️ fastboot -w 超时，跳过")
                            
                            log_func("  ✅ 数据清除流程完成")
                    
                    log_func("重启到系统")
                    subprocess.run(
                        [fb, 'reboot'],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        timeout=10,
                        **self._popen_kwargs_silent()
                    )
        
        log_func("=" * 50)
        log_func("刷机流程完成")
        log_func("=" * 50)
    
    def _run_flash_plan(self, plan: dict, images_dir: str):
        try:
            self._busy = True
            self._flashing = True
            self._set_controls_enabled(False)
            
            self._images_dir = Path(images_dir)
            self._images = self._scan_images(images_dir)
            
            self.append_log("=" * 50)
            self.append_log("开始执行刷机计划")
            self.append_log("=" * 50)
            
            if not self._verify_devices(plan.get('devices') or []):
                self._toast_warning("错误", "设备型号验证失败！")
                return
            
            for i, step in enumerate(plan['steps'], 1):
                if not self._flashing:
                    self.append_log("用户取消了刷机")
                    break
                
                step_type = step['type']
                
                if step_type == 'mode':
                    if not self._ensure_mode(step['mode']):
                        self.append_log(f"错误: 无法切换到 {step['mode']} 模式")
                        self._toast_warning("错误", f"模式切换失败: {step['mode']}")
                        return
                
                elif step_type == 'flash':
                    if not self._flash_partition(step['partition'], step.get('disable_avb', False)):
                        self.append_log(f"错误: 刷写 {step['partition']} 失败")
                        self._toast_warning("错误", f"刷写分区失败: {step['partition']}")
                        return
                
                elif step_type == 'delete_logical':
                    if not self._delete_logical_partition(step['partition']):
                        self.append_log(f"警告: 删除逻辑分区 {step['partition']} 失败")
                
                elif step_type == 'create_logical':
                    if not self._create_logical_partition(step['partition'], step['size']):
                        self.append_log(f"错误: 创建逻辑分区 {step['partition']} 失败")
                        self._toast_warning("错误", f"创建逻辑分区失败: {step['partition']}")
                        return
                
                elif step_type == 'set_slot':
                    if not self._set_active_slot(step['slot']):
                        self.append_log(f"警告: 设置活动槽位 {step['slot']} 失败，继续执行")
                
                elif step_type == 'reboot':
                    if step['target'] == 'system':
                        if self.wipe_check.isChecked():
                            self._wipe_data()
                        
                        self.append_log("正在重启到系统...")
                        self._run_fastboot(['reboot'], "重启到系统")
                        self.append_log("刷机完成！设备正在重启...")
            
            self.append_log("=" * 50)
            self.append_log("刷机流程完成")
            self.append_log("=" * 50)
            self._toast_success("成功", "刷机完成！")
        
        except Exception as e:
            self.append_log(f"刷机过程发生异常: {e}")
            self._toast_warning("错误", f"刷机异常: {e}")
        
        finally:
            self._busy = False
            self._flashing = False
            self._set_controls_enabled(True)
