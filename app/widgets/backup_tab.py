import os
import time
import subprocess
import shutil
import zipfile
from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFileDialog, 
    QTextEdit, QProgressBar, QCheckBox, QGridLayout, QGroupBox
)
from PySide6.QtCore import Qt, QThread, QObject, Signal
from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, InfoBar, InfoBarPosition,
    FluentIcon, MessageDialog, SmoothScrollArea, MessageBoxBase, SubtitleLabel,
    StrongBodyLabel, CaptionLabel, ExpandGroupSettingCard, SwitchButton
)

from app.services import adb_service as svc

# ----------------- Workers -----------------

class _ScanWorker(QObject):
    finished = Signal(list, str)  # partitions, error_msg
    log = Signal(str)

    def __init__(self, adb_path: str, serial: str):
        super().__init__()
        self.adb_path = adb_path
        self.serial = serial
        self._stop = False

    def stop(self):
        self._stop = True

    def _run_cmd(self, cmd: List[str], timeout=30) -> str:
        if self._stop:
            raise RuntimeError("Stopped")
        try:
            print(f"[DEBUG] Executing: {cmd}")
            if os.name == 'nt':
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                return subprocess.check_output(
                    cmd, 
                    stderr=subprocess.STDOUT, 
                    timeout=timeout,
                    startupinfo=si,
                    creationflags=subprocess.CREATE_NO_WINDOW
                ).decode('utf-8', errors='ignore').strip()
            else:
                return subprocess.check_output(
                    cmd, 
                    stderr=subprocess.STDOUT, 
                    timeout=timeout
                ).decode('utf-8', errors='ignore').strip()
        except Exception as e:
            print(f"[DEBUG] Command failed: {e}")
            raise RuntimeError(str(e))

    def _adb_shell(self, cmd: str, timeout=10) -> str:
        # Pass the shell command as a single argument to 'adb shell'
        # This avoids local shell interpretation
        return self._run_cmd([self.adb_path, '-s', self.serial, 'shell', cmd], timeout=timeout)

    def run(self):
        print("[DEBUG] ScanWorker run started")
        try:
            self.log.emit("正在初始化连接...")
            
            # 0. Check ADB Path
            if not os.path.exists(self.adb_path):
                self.finished.emit([], f"ADB executable not found at: {self.adb_path}")
                return

            self.log.emit("检查 Root 权限...")
            print("[DEBUG] Checking root...")
            # 1. Check Root
            try:
                # Use a simpler check first
                res = self._adb_shell("id", timeout=5)
                print(f"[DEBUG] id result: {res}")
                
                res_su = self._adb_shell("su -c id", timeout=8)
                print(f"[DEBUG] su check result: {res_su}")
                if "uid=0" not in res_su:
                    self.finished.emit([], "未获取到 Root 权限，无法读取分区表。")
                    return
            except Exception as e:
                print(f"[DEBUG] Root check failed: {e}")
                self.finished.emit([], f"Root 权限检查失败: {e}\n请确认设备已 Root 并授予 Shell 权限。")
                return

            self.log.emit("正在查找分区路径...")
            # 2. Find partitions
            search_paths = [
                "/dev/block/bootdevice/by-name",
                "/dev/block/by-name",
                "/dev/block/platform/*/by-name"
            ]
            
            partitions = []
            
            for p in search_paths:
                try:
                    if '*' in p:
                        base = p.split('*')[0]
                        self.log.emit(f"解析通配符: {p}")
                        ls_base = self._adb_shell(f"ls -d {base}* 2>/dev/null", timeout=5).strip()
                        if ls_base and "No such" not in ls_base:
                            lines = ls_base.splitlines()
                            if lines:
                                p = lines[0].strip() + "/by-name"
                    
                    self.log.emit(f"扫描路径: {p}")
                    # Use ls -1 to ensure one entry per line
                    res = self._adb_shell(f"ls -1 {p}", timeout=5)
                    if res and "No such file" not in res and "Permission denied" not in res:
                        found = [x.strip() for x in res.split() if x.strip()]
                        # Filter out obviously wrong entries
                        partitions = [x for x in found if not x.startswith('/') and not x.startswith('ls:') and x]
                        if partitions:
                            self.log.emit(f"成功找到 {len(partitions)} 个分区。")
                            break
                except Exception as e:
                    print(f"[DEBUG] Path {p} scan error: {e}")
                    self.log.emit(f"路径 {p} 扫描出错: {e}")
                    continue
            
            if not partitions:
                self.finished.emit([], "无法找到分区路径 (/dev/block/by-name 等)。")
            else:
                # Sort partitions
                partitions.sort()
                self.finished.emit(partitions, "")
                
        except Exception as e:
            print(f"[DEBUG] ScanWorker exception: {e}")
            self.finished.emit([], f"扫描流程异常: {str(e)}")


class _BackupExecutorWorker(QObject):
    log = Signal(str)
    progress = Signal(int, int)  # current, total
    finished = Signal(bool, str)

    def __init__(self, adb_path: str, out_dir: str, serial: str, 
                 partitions: List[str], use_zip: bool, gen_script: bool):
        super().__init__()
        self.adb_path = adb_path
        self.out_dir = out_dir
        self.serial = serial
        self.partitions = partitions
        self.use_zip = use_zip
        self.gen_script = gen_script
        self._stop = False

    def stop(self):
        self._stop = True

    def _run_cmd(self, cmd: List[str], timeout=30) -> str:
        try:
            if os.name == 'nt':
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                return subprocess.check_output(
                    cmd, 
                    stderr=subprocess.STDOUT, 
                    timeout=timeout,
                    startupinfo=si,
                    creationflags=subprocess.CREATE_NO_WINDOW
                ).decode('utf-8', errors='ignore').strip()
            else:
                return subprocess.check_output(
                    cmd, 
                    stderr=subprocess.STDOUT, 
                    timeout=timeout
                ).decode('utf-8', errors='ignore').strip()
        except Exception as e:
            raise RuntimeError(str(e))

    def _adb_shell(self, cmd: str, timeout=60) -> str:
        return self._run_cmd([self.adb_path, '-s', self.serial, 'shell', cmd], timeout=timeout)

    def run(self):
        try:
            if not self.partitions:
                self.finished.emit(False, "未选择任何分区")
                return

            self.log.emit(f"开始备份 {len(self.partitions)} 个分区...")
            
            # Prepare local folder
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            device_model = svc.get_device_info(self.serial).get('model', 'Unknown').replace(' ', '_')
            backup_name = f"Backup_{device_model}_{timestamp}"
            local_backup_dir = os.path.join(self.out_dir, backup_name)
            os.makedirs(local_backup_dir, exist_ok=True)

            # Find target path again (safe check)
            target_path = ""
            search_paths = [
                "/dev/block/bootdevice/by-name",
                "/dev/block/by-name",
                "/dev/block/platform/*/by-name"
            ]
            for p in search_paths:
                try:
                    if '*' in p:
                        base = p.split('*')[0]
                        ls_base = self._adb_shell(f"ls -d {base}* 2>/dev/null", timeout=5).strip()
                        if ls_base and "No such" not in ls_base:
                            p = ls_base + "/by-name"
                    res = self._adb_shell(f"ls {p}", timeout=5)
                    if res and "No such file" not in res:
                        target_path = p
                        break
                except Exception:
                    continue
            
            if not target_path:
                raise RuntimeError("无法找到分区路径")

            total = len(self.partitions)
            success_parts = []

            for idx, part in enumerate(self.partitions):
                if self._stop:
                    break
                
                self.progress.emit(idx + 1, total)
                self.log.emit(f"[{idx+1}/{total}] 正在备份: {part} ...")
                
                remote_tmp = f"/sdcard/Download/tmp_backup_{part}.img"
                self._adb_shell("mkdir -p /sdcard/Download")
                
                # DD
                dd_cmd = f"su -c 'dd if={target_path}/{part} of={remote_tmp}'"
                try:
                    self._adb_shell(dd_cmd, timeout=3600) # super partition can be HUGE
                except Exception as e:
                    self.log.emit(f"  - 分区 {part} 备份失败 (DD): {e}")
                    continue

                # Pull
                local_img = os.path.join(local_backup_dir, f"{part}.img")
                try:
                    pull_cmd = [self.adb_path, '-s', self.serial, 'pull', remote_tmp, local_img]
                    self._run_cmd(pull_cmd, timeout=3600)
                    success_parts.append(part)
                except Exception as e:
                    self.log.emit(f"  - 分区 {part} 拉取失败: {e}")
                
                # Cleanup
                try:
                    self._adb_shell(f"rm {remote_tmp}", timeout=10)
                except Exception:
                    pass

            if self._stop:
                self.finished.emit(False, "备份已取消")
                return

            # Generate Script
            if self.gen_script and success_parts:
                self.log.emit("正在生成刷机脚本...")
                try:
                    bat_path = os.path.join(local_backup_dir, "flash_all.bat")
                    with open(bat_path, 'w', encoding='utf-8') as f: # Bat needs ANSI usually but utf-8 mostly works if no special chars
                        f.write("@echo off\n")
                        f.write("echo Waiting for device in fastboot...\n")
                        f.write("fastboot devices\n")
                        f.write("pause\n")
                        for p in success_parts:
                            f.write(f"echo Flashing {p}...\n")
                            f.write(f"fastboot flash {p} {p}.img\n")
                        f.write("echo Done!\n")
                        f.write("pause\n")
                    
                    sh_path = os.path.join(local_backup_dir, "flash_all.sh")
                    with open(sh_path, 'w', encoding='utf-8') as f:
                        f.write("#!/bin/bash\n")
                        f.write("echo 'Waiting for device...'\n")
                        f.write("fastboot devices\n")
                        for p in success_parts:
                            f.write(f"echo 'Flashing {p}...'\n")
                            f.write(f"fastboot flash {p} {p}.img\n")
                        f.write("echo 'Done!'\n")
                    # make executable? chmod not needed on windows host usually
                except Exception as e:
                    self.log.emit(f"生成脚本失败: {e}")

            final_path = local_backup_dir

            # Zip
            if self.use_zip and success_parts:
                self.log.emit("正在压缩备份文件...")
                zip_path = os.path.join(self.out_dir, f"{backup_name}.zip")
                
                # Try 7z
                root_dir = Path(__file__).resolve().parents[2]
                p7z = root_dir / 'bin' / '7z.exe'
                used_7z = False
                
                if p7z.exists():
                    try:
                        cmd_7z = [str(p7z), 'a', zip_path, local_backup_dir]
                        self._run_cmd(cmd_7z, timeout=1800)
                        used_7z = True
                    except Exception as e:
                        self.log.emit(f"7z 压缩失败，尝试使用内置 zip: {e}")
                
                if not used_7z:
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for root, _, files in os.walk(local_backup_dir):
                            for file in files:
                                if self._stop: break
                                fp = os.path.join(root, file)
                                arcname = os.path.relpath(fp, self.out_dir)
                                zf.write(fp, arcname)
                
                if not self._stop:
                    # Cleanup folder if zipped
                    try:
                        shutil.rmtree(local_backup_dir)
                    except Exception:
                        pass
                    final_path = zip_path

            if self._stop:
                self.finished.emit(False, "备份已取消")
                return

            self.log.emit(f"备份完成！\n已保存至: {final_path}")
            self.finished.emit(True, final_path)

        except Exception as e:
            self.log.emit(f"错误: {str(e)}")
            self.finished.emit(False, str(e))


class PartitionSelectionDialog(MessageBoxBase):
    def __init__(self, partitions: List[str], parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("选择需要备份的分区", self)
        self.viewLayout.addWidget(self.titleLabel)

        self.partitions = partitions
        self.checkboxes = {}
        
        # Tools
        tools = QHBoxLayout()
        btn_all = PushButton("全选")
        btn_all.clicked.connect(self.select_all)
        btn_inv = PushButton("反选")
        btn_inv.clicked.connect(self.invert_selection)
        btn_def = PushButton("默认")
        btn_def.clicked.connect(self.select_default)
        tools.addWidget(btn_all)
        tools.addWidget(btn_inv)
        tools.addWidget(btn_def)
        tools.addStretch(1)
        self.viewLayout.addLayout(tools)
        
        # Scroll Area
        self.scroll = SmoothScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(350)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        
        # Grid for normal
        grid_w = QWidget()
        self.grid = QGridLayout(grid_w)
        vbox.addWidget(grid_w)
        
        # Risky
        self.risky_group = ExpandGroupSettingCard(
            FluentIcon.INFO, "不推荐备份的分区", "包含 userdata, metadata, frp 等"
        )
        
        self.risky_container = QWidget()
        self.risky_layout = QVBoxLayout(self.risky_container)
        self.risky_layout.setContentsMargins(16, 0, 16, 16)
        self.risky_group.viewLayout.addWidget(self.risky_container)
        
        vbox.addWidget(self.risky_group)
        
        self.scroll.setWidget(container)
        self.viewLayout.addWidget(self.scroll)
        
        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        
        self.yesButton.clicked.connect(self.accept)
        self.cancelButton.clicked.connect(self.reject)
        
        self.widget.setMinimumWidth(600)
        
        self._populate()

    def _populate(self):
        risky_names = ["userdata", "metadata", "frp", "cache"]
        normal = []
        risky = []
        for p in self.partitions:
            if p.lower() in risky_names:
                risky.append(p)
            else:
                normal.append(p)
                
        # Grid
        row, col = 0, 0
        for p in normal:
            chk = QCheckBox(p)
            chk.setChecked(True)
            self.grid.addWidget(chk, row, col)
            self.checkboxes[p] = chk
            col += 1
            if col > 2:
                col = 0
                row += 1
                
        # Risky
        for p in risky:
            chk = QCheckBox(p)
            chk.setChecked(False)
            self.risky_layout.addWidget(chk)
            self.checkboxes[p] = chk

    def select_all(self):
        for chk in self.checkboxes.values():
            chk.setChecked(True)
            
    def invert_selection(self):
        for chk in self.checkboxes.values():
            chk.setChecked(not chk.isChecked())
            
    def select_default(self):
        risky_names = ["userdata", "metadata", "frp", "cache"]
        for name, chk in self.checkboxes.items():
            if name.lower() in risky_names:
                chk.setChecked(False)
            else:
                chk.setChecked(True)

    def get_selected(self):
        return [n for n, c in self.checkboxes.items() if c.isChecked()]


# ----------------- UI -----------------

class BackupTab(QWidget):
    def __init__(self):
        super().__init__()
        self._scan_thread = None
        self._scan_worker = None
        self._backup_thread = None
        self._backup_worker = None
        self.partitions = []
        self.selected_partitions = []
        self._init_ui()
        
    def _init_ui(self):
        self.v_layout = QVBoxLayout(self)
        try:
            self.v_layout.setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass
            
        self.scroll = SmoothScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea {border: none; background: transparent;}")
        self.v_layout.addWidget(self.scroll)
        
        self.container = QWidget()
        self.scroll.setWidget(self.container)
        self.container.setStyleSheet("QWidget {background: transparent;}")
        
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(24, 24, 24, 24)
        self.layout.setSpacing(16)
        
        self._add_banner()

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # 1. Path Selection
        card_path = CardWidget(self)
        l_path = QVBoxLayout(card_path)
        l_path.setContentsMargins(16, 16, 16, 16)
        title_path = QHBoxLayout()
        title_path.setSpacing(8)
        title_path.addWidget(QLabel("保存目录"), 0, Qt.AlignLeft)
        title_path.addStretch(1)
        l_path.addLayout(title_path)

        r_path = QHBoxLayout()
        r_path.setSpacing(8)
        r_path.addWidget(QLabel("路径:"))
        self.path_edit = QLineEdit()
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self.path_edit.setText(desktop)
        btn_browse = PushButton("浏览")
        btn_browse.clicked.connect(self._browse)
        r_path.addWidget(self.path_edit, 1)
        r_path.addWidget(btn_browse)
        l_path.addLayout(r_path)
        grid.addWidget(card_path, 0, 0)
        
        # 2. Options & Actions
        card_opt = CardWidget(self)
        l_opt = QVBoxLayout(card_opt)
        l_opt.setContentsMargins(16, 16, 16, 16)
        header_opt = QHBoxLayout()
        header_opt.setSpacing(8)
        header_opt.addWidget(QLabel("备份设置"))
        header_opt.addStretch(1)
        l_opt.addLayout(header_opt)
        
        self.chk_zip = QCheckBox("将备份分区打包为一个 ZIP 包")
        self.chk_zip.setChecked(True)
        self.chk_script = QCheckBox("为备份分区生成刷机脚本 (flash_all.bat/sh)")
        self.chk_script.setChecked(True)
        
        l_opt.addWidget(self.chk_zip)
        l_opt.addWidget(self.chk_script)
        
        l_opt.addSpacing(10)
        
        # Buttons
        h_btn = QHBoxLayout()
        h_btn.setSpacing(12)
        self.btn_refresh = PushButton("扫描并选择分区")
        self.btn_refresh.clicked.connect(self._scan_partitions)
        
        self.btn_start = PrimaryPushButton("开始备份")
        self.btn_start.clicked.connect(self._start_backup)
        
        h_btn.addWidget(self.btn_refresh)
        h_btn.addWidget(self.btn_start)
        h_btn.addStretch(1)
        l_opt.addLayout(h_btn)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        l_opt.addWidget(self.progress_bar)
        
        grid.addWidget(card_opt, 0, 1)

        self.layout.addLayout(grid)
        
        # 3. Log
        card_log = CardWidget(self)
        v_log = QVBoxLayout(card_log)
        v_log.setContentsMargins(16, 16, 16, 16)
        h_log = QHBoxLayout()
        h_log.setSpacing(8)
        h_log.addWidget(QLabel("执行日志"))
        h_log.addStretch(1)
        v_log.addLayout(h_log)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("日志输出...")
        self.log_view.setStyleSheet("background: transparent;")
        v_log.addWidget(self.log_view)
        self.layout.addWidget(card_log)
        
        self.layout.addStretch(1)

    def _add_banner(self):
        from PySide6.QtWidgets import QWidget as _W
        banner_w = _W(self)
        try:
            banner_w.setFixedHeight(110)
            banner_w.setAttribute(Qt.WA_TranslucentBackground, True)
        except Exception:
            pass
        banner_w.setStyleSheet("background: transparent;")
        banner = QHBoxLayout(banner_w)
        banner.setContentsMargins(24, 18, 24, 18)
        banner.setSpacing(16)
        
        icon_lbl = QLabel()
        icon_lbl.setStyleSheet("background: transparent;")
        try:
            icon_lbl.setFixedSize(48, 48)
        except Exception:
            pass
        try:
            ico = FluentIcon.SAVE.icon()
            icon_lbl.setPixmap(ico.pixmap(48, 48))
        except Exception:
            pass
            
        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        t = QLabel("基带备份")
        t.setStyleSheet("font-size: 22px; font-weight: 600;")
        s = QLabel("自定义分区备份，支持压缩与脚本生成")
        s.setStyleSheet("font-size: 14px;")
        v.addWidget(t)
        v.addWidget(s)
        
        banner.addWidget(icon_lbl)
        banner.addLayout(v)
        banner.addStretch(1)
        self.layout.addWidget(banner_w)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存目录", self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def _scan_partitions(self):
        try:
            if self._scan_thread and self._scan_thread.isRunning():
                return
        except RuntimeError:
            self._scan_thread = None

        mode, serial = svc.detect_connection_mode()
        if mode != 'system':
            InfoBar.error("错误", "请连接设备至系统模式并开启调试", parent=self, position=InfoBarPosition.TOP)
            return

        self.btn_refresh.setEnabled(False)
        self.log_view.append("正在扫描分区...")
        
        self._scan_thread = QThread(self)
        self._scan_worker = _ScanWorker(str(svc.ADB_BIN), serial)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_worker.log.connect(self.log_view.append, Qt.QueuedConnection)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.finished.connect(self._cleanup_scan_thread)
        self._scan_thread.start()

    def _cleanup_scan_thread(self):
        self._scan_thread = None
        self._scan_worker = None

    def _on_scan_finished(self, partitions, err):
        self.btn_refresh.setEnabled(True)
        if err:
            InfoBar.error("扫描失败", err, parent=self, position=InfoBarPosition.TOP)
            self.log_view.append(f"扫描失败: {err}")
            return
        
        self.partitions = partitions
        self.log_view.append(f"扫描完成，共找到 {len(partitions)} 个分区。")
        
        # Open Dialog
        dlg = PartitionSelectionDialog(partitions, self.window())
        if dlg.exec():
            self.selected_partitions = dlg.get_selected()
            self.log_view.append(f"已选择 {len(self.selected_partitions)} 个分区。")
            if self.selected_partitions:
                InfoBar.success("就绪", f"已选择 {len(self.selected_partitions)} 个分区，请点击“开始备份”", parent=self, position=InfoBarPosition.TOP)
        else:
            self.log_view.append("用户取消了分区选择。")


    def _start_backup(self):
        try:
            if self._backup_thread and self._backup_thread.isRunning():
                InfoBar.warning("提示", "备份任务正在进行", parent=self, position=InfoBarPosition.TOP)
                return
        except RuntimeError:
            self._backup_thread = None

        selected = self.selected_partitions
        if not selected:
            InfoBar.warning("提示", "请先扫描并选择至少一个分区", parent=self, position=InfoBarPosition.TOP)
            return
            
        path = self.path_edit.text()
        if not path or not os.path.exists(path):
            InfoBar.error("错误", "无效的保存路径", parent=self, position=InfoBarPosition.TOP)
            return
            
        mode, serial = svc.detect_connection_mode()
        if mode != 'system':
            InfoBar.error("错误", "请确保设备连接且在线", parent=self, position=InfoBarPosition.TOP)
            return

        # Double check if userdata is selected
        if "userdata" in selected:
            confirm = MessageDialog("警告", "您选择了 userdata 分区，该分区通常非常大且包含个人隐私数据。\n备份极易可能失败且耗时极长。\n确定要继续吗？", self)
            if confirm.exec() != MessageDialog.Accepted:
                return
        
        self.btn_start.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.log_view.clear()
        
        self._backup_thread = QThread(self)
        self._backup_worker = _BackupExecutorWorker(
            str(svc.ADB_BIN), path, serial, selected, 
            self.chk_zip.isChecked(), self.chk_script.isChecked()
        )
        self._backup_worker.moveToThread(self._backup_thread)
        self._backup_thread.started.connect(self._backup_worker.run)
        self._backup_worker.log.connect(self.log_view.append, Qt.QueuedConnection)
        self._backup_worker.progress.connect(self._update_progress, Qt.QueuedConnection)
        self._backup_worker.finished.connect(self._on_backup_finished, Qt.QueuedConnection)
        self._backup_worker.finished.connect(self._backup_thread.quit)
        self._backup_worker.finished.connect(self._backup_worker.deleteLater)
        self._backup_thread.finished.connect(self._backup_thread.deleteLater)
        self._backup_thread.finished.connect(self._cleanup_backup_thread)
        self._backup_thread.start()

    def _update_progress(self, curr, total):
        if total > 0:
            self.progress_bar.setValue(int((curr/total)*100))

    def _on_backup_finished(self, ok, msg):
        self.btn_start.setEnabled(True)
        if ok:
            InfoBar.success("完成", "备份任务结束", parent=self, position=InfoBarPosition.TOP)
            self.log_view.append("[SUCCESS] " + msg)
            try:
                folder = os.path.dirname(msg) if os.path.isfile(msg) else msg
                if os.name == 'nt':
                    os.startfile(folder)
            except:
                pass
        else:
            InfoBar.error("失败", msg, parent=self, position=InfoBarPosition.TOP)
            self.log_view.append("[FAILED] " + msg)

    def _cleanup_backup_thread(self):
        self._backup_thread = None
        self._backup_worker = None

    def cleanup(self):
        if self._scan_worker:
            try:
                self._scan_worker.stop()
            except RuntimeError:
                pass
        if self._scan_thread:
            try:
                self._scan_thread.quit()
                self._scan_thread.wait(1000)
            except RuntimeError:
                pass
            
        if self._backup_worker:
            try:
                self._backup_worker.stop()
            except RuntimeError:
                pass
        if self._backup_thread:
            try:
                self._backup_thread.quit()
                self._backup_thread.wait(1000)
            except RuntimeError:
                pass
