import os
import subprocess
import shlex
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QObject, QThread, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QFileDialog,
    QLabel, QComboBox, QLineEdit, QMessageBox, QGridLayout, QDialog, QCheckBox
)
from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, TitleLabel, FluentIcon,
    InfoBar, InfoBarPosition, MessageDialog, SmoothScrollArea, ComboBox,
    SettingCardGroup, PushSettingCard, CaptionLabel
)

from app.services import adb_service as svc


ABL_IMAGE = svc.BIN_DIR / 'add_images' / 'abl.img'


def _resolve_bin(path_like: Optional[Path], fallback_name: str) -> str:
    try:
        if path_like and isinstance(path_like, Path) and path_like.exists():
            return str(path_like)
    except Exception:
        pass
    return fallback_name


class _ProcWorker(QObject):
    output = Signal(str)
    finished = Signal(int)

    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        code = -1
        proc = None
        try:
            # suppress console window on Windows
            popen_kwargs = {}
            try:
                import os as _os
                if _os.name == 'nt':
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    popen_kwargs = {'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW}
            except Exception:
                pass
            # Force UTF-8 decoding with safe fallback to avoid GBK decode errors on Windows
            proc = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                **popen_kwargs,
            )
            for line in iter(proc.stdout.readline, ''):
                if self._stop:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break
                self.output.emit(line.rstrip('\r\n'))
            code = proc.wait()
        except FileNotFoundError:
            self.output.emit("未找到可执行文件，请检查工具是否存在。")
        except Exception as e:
            self.output.emit(f"执行失败：{e}")
            # Ensure the child process does not linger on errors
            try:
                if proc and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        proc.kill()
                        proc.wait()
            except Exception:
                pass
        finally:
            self.finished.emit(code)


class _BootFixWorker(QObject):
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, adb_path: str, fastboot_path: str, abl_img: str, wait_secs: int = 25):
        super().__init__()
        self.adb_path = adb_path or 'adb'
        self.fastboot_path = fastboot_path or 'fastboot'
        self.abl_img = abl_img
        self.wait_secs = wait_secs

    def _silent_kwargs(self):
        kw = {}
        try:
            if os.name == 'nt':
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                kw = {'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW}
        except Exception:
            pass
        return kw

    def _run_cmd(self, cmd, timeout=120):
        try:
            self.log.emit('执行: ' + ' '.join(cmd))
        except Exception:
            pass
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=timeout,
            **self._silent_kwargs()
        )
        out = (proc.stdout or '').strip()
        if out:
            for line in out.splitlines():
                self.log.emit(line)

    def run(self):
        try:
            if not os.path.exists(self.abl_img):
                raise RuntimeError(f'未找到修复镜像: {self.abl_img}')
            self.log.emit('正在重启到 Fastboot (adb reboot fastboot)...')
            self._run_cmd([self.adb_path, 'reboot', 'fastboot'], timeout=30)
            self.log.emit(f'等待设备进入 Fastboot （约 {self.wait_secs} 秒）...')
            time.sleep(self.wait_secs)
            self.log.emit('开始刷写 abl_a ...')
            self._run_cmd([self.fastboot_path, 'flash', 'abl_a', self.abl_img], timeout=120)
            self.log.emit('开始刷写 abl_b ...')
            self._run_cmd([self.fastboot_path, 'flash', 'abl_b', self.abl_img], timeout=120)
            self.log.emit('重启回系统 ...')
            self._run_cmd([self.fastboot_path, 'reboot'], timeout=30)
            self.log.emit('修复已完成，设备正在重启回系统')
            self.finished.emit(True, '修复已完成，设备正在重启回系统')
        except subprocess.CalledProcessError as e:
            msg = (e.stdout or e.stderr or str(e)) if hasattr(e, 'stdout') else str(e)
            self.log.emit(msg)
            self.finished.emit(True, '修复流程已结束')
        except Exception as e:
            self.log.emit(str(e))
            self.finished.emit(True, '修复流程已结束')


class _GoogleLockWorker(QObject):
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, adb_path: str):
        super().__init__()
        self.adb_path = adb_path or 'adb'

    def run(self):
        try:
            self.log.emit("尝试请求 Root 权限并执行 FRP 清除...")
            # 构建 dd 命令
            dd_cmd = "dd if=/dev/zero of=/dev/block/bootdevice/by-name/frp"
            # 尝试使用 su -c 执行
            cmd = [self.adb_path, 'shell', f"su -c '{dd_cmd}'"]
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            self.log.emit(f"执行: {' '.join(cmd)}")
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            output = proc.stdout.strip()
            if output:
                self.log.emit(f"命令输出: {output}")
            
            # 简单检查是否有权限错误
            if "permission denied" in output.lower() or "not found" in output.lower():
                raise RuntimeError("执行失败，请确认设备已 Root 并授权 Shell 获取 Root 权限。")
            
            self.log.emit("正在重启设备...")
            subprocess.run(
                [self.adb_path, 'reboot'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            self.finished.emit(True, "移除指令执行完成，设备正在重启。")
            
        except Exception as e:
            self.log.emit(f"发生错误: {e}")
            self.finished.emit(False, str(e))


class _MagiskRemoveModulesWorker(QObject):
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, adb_path: str):
        super().__init__()
        self.adb_path = adb_path or 'adb'

    def run(self):
        try:
            self.log.emit("尝试执行 Magisk 模块移除指令...")
            # Command: adb shell Magisk --remove-modules
            cmd = [self.adb_path, 'shell', 'Magisk', '--remove-modules']
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            self.log.emit(f"执行: {' '.join(cmd)}")
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            output = proc.stdout.strip()
            if output:
                self.log.emit(f"命令输出: {output}")
            
            if "not found" in output.lower() or "inaccessible" in output.lower():
                raise RuntimeError("执行失败，可能是未安装 Magisk 或指令不支持。")
            
            self.log.emit("正在重启设备...")
            subprocess.run(
                [self.adb_path, 'reboot'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            self.finished.emit(True, "指令执行完成，设备正在重启。")
            
        except Exception as e:
            self.log.emit(f"发生错误: {e}")
            self.finished.emit(False, str(e))




class MiscTab(QWidget):
    log_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self._thread: Optional[QThread] = None
        self._worker: Optional[_ProcWorker] = None
        self._boot_fix_thread: Optional[QThread] = None
        self._boot_fix_worker: Optional[_BootFixWorker] = None
        self._frp_thread: Optional[QThread] = None
        self._frp_worker: Optional[_GoogleLockWorker] = None
        self._unbrick_thread: Optional[QThread] = None
        self._unbrick_worker: Optional[_MagiskRemoveModulesWorker] = None
        self._native_proc: Optional[subprocess.Popen] = None
        self._native_timer: Optional[QTimer] = None

        adb_bin = getattr(svc, 'ADB_BIN', None)
        fastboot_bin = getattr(svc, 'FASTBOOT_BIN', None)
        self.adb_path = _resolve_bin(adb_bin if adb_bin else None, 'adb')
        self.fastboot_path = _resolve_bin(fastboot_bin if fastboot_bin else None, 'fastboot')

        # 工具箱式入口（保留原 Banner 标题布局） - 启用滚动
        self.v_layout = QVBoxLayout(self)
        self.v_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = SmoothScrollArea(self)
        self.v_layout.addWidget(self.scroll_area)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea {border: none; background: transparent;}")

        self.scroll_widget = QWidget(self.scroll_area)
        self.scroll_widget.setStyleSheet("QWidget {background: transparent;}")
        self.scroll_area.setWidget(self.scroll_widget)

        layout = QVBoxLayout(self.scroll_widget)
        try:
            layout.setContentsMargins(24, 24, 24, 24)
            layout.setSpacing(12)
        except Exception:
            pass

        # 顶部渐变 Banner（与原布局保持一致）
        from PySide6.QtWidgets import QWidget as _W
        banner_w = _W(self)
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
                _ico = FluentIcon.TILES.icon()
                icon_lbl.setPixmap(_ico.pixmap(48, 48))
            except Exception:
                pass
        except Exception:
            pass
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        t = QLabel("杂项工具箱", banner_w)
        try:
            t.setStyleSheet("font-size: 22px; font-weight: 600;")
        except Exception:
            pass
        s = QLabel("常用工具与不常用的工具合集", banner_w)
        try:
            s.setStyleSheet("font-size: 14px;")
        except Exception:
            pass
        title_col.addWidget(t)
        title_col.addWidget(s)
        banner.addWidget(icon_lbl)
        banner.addLayout(title_col)
        banner.addStretch(1)
        layout.addWidget(banner_w)

        # 常用工具分组
        self.common_group = SettingCardGroup("常用工具", self)
        self.card_flash = PushSettingCard(
            "打开",
            FluentIcon.TILES,
            "单分区刷入",
            "选择镜像并刷入指定分区（可选槽位 / 模式）",
            self.common_group,
        )
        self.card_flash.clicked.connect(self._open_partition_flash)

        self.card_payload = PushSettingCard(
            "打开",
            FluentIcon.ZIP_FOLDER if hasattr(FluentIcon, "ZIP_FOLDER") else FluentIcon.FOLDER,
            "payload.bin 处理",
            "在线或本地提取 payload.bin，支持全量和指定分区",
            self.common_group,
        )
        self.card_payload.clicked.connect(self._open_payload_extract)

        self.common_group.addSettingCard(self.card_flash)
        self.common_group.addSettingCard(self.card_payload)
        layout.addWidget(self.common_group)

        # 高级操作分组
        self.advanced_group = SettingCardGroup("高级操作", self)
        self.card_unlock = PushSettingCard(
            "执行",
            FluentIcon.UNPIN if hasattr(FluentIcon, "UNPIN") else FluentIcon.LOCK,
            "解锁 Bootloader",
            "进入 Bootloader 后执行 fastboot flashing unlock",
            self.advanced_group,
        )
        self.card_unlock.clicked.connect(self._open_bootloader_unlock)

        self.card_repair = PushSettingCard(
            "修复",
            FluentIcon.BROOM if hasattr(FluentIcon, "BROOM") else FluentIcon.REPAIR,
            "修复 Bootloader (Ace Pro)",
            "修复 Ace Pro Bootloader 闪退",
            self.advanced_group,
        )
        self.card_repair.clicked.connect(self._repair_bootloader)

        self.card_frp = PushSettingCard(
            "执行",
            FluentIcon.DELETE if hasattr(FluentIcon, "DELETE") else FluentIcon.REMOVE,
            "移除 Google 锁",
            "移除因未退出 Google 账号导致的 FRP 锁（需 Root）",
            self.advanced_group,
        )
        self.card_frp.clicked.connect(self._remove_google_lock)

        self.card_unbrick = PushSettingCard(
            "执行",
            FluentIcon.MEDICAL if hasattr(FluentIcon, "MEDICAL") else FluentIcon.HELP,
            "极速救砖 (Magisk)",
            "恢复因刷入错误的 Magisk 模块导致的不开机",
            self.advanced_group,
        )
        self.card_unbrick.clicked.connect(self._fast_unbrick)

        self.card_tee = PushSettingCard(
            "修复",
            FluentIcon.FINGERPRINT if hasattr(FluentIcon, "FINGERPRINT") else FluentIcon.HELP,
            "修复 TEE（可信执行环境）",
            "修复 TEE 假死导致的无法绑定国铁/开启无敌裸奔环境",
            self.advanced_group,
        )
        self.card_tee.clicked.connect(self._repair_tee)

        self.card_adb = PushSettingCard(
            "打开",
            FluentIcon.COMMAND_PROMPT if hasattr(FluentIcon, "COMMAND_PROMPT") else FluentIcon.CODE,
            "ADB 终端",
            "打开原生终端窗口运行 ADB",
            self.advanced_group,
        )
        self.card_adb.clicked.connect(self._open_adb_terminal)

        self.card_config_check = PushSettingCard(
            "检测",
            FluentIcon.DOCUMENT if hasattr(FluentIcon, "DOCUMENT") else FluentIcon.DOCUMENT,
            "刷机配置文件检测",
            "检测配置文件语法错误，显示行号、列号和错误信息",
            self.advanced_group,
        )
        self.card_config_check.clicked.connect(self._check_flash_config)

        self.advanced_group.addSettingCard(self.card_unlock)
        self.advanced_group.addSettingCard(self.card_repair)
        self.advanced_group.addSettingCard(self.card_frp)
        self.advanced_group.addSettingCard(self.card_unbrick)
        self.advanced_group.addSettingCard(self.card_tee)
        self.advanced_group.addSettingCard(self.card_adb)
        self.advanced_group.addSettingCard(self.card_config_check)
        layout.addWidget(self.advanced_group)

        layout.addStretch(1)

    def _append(self, text: str):
        self.log_signal.emit(text)

    def _pick_img(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择镜像", "", "镜像 (*.img);;所有文件 (*.*)")
        if path:
            self.img_edit.setText(path)

    def _ensure_mode(self, target: str) -> bool:
        fb = self.fastboot_path
        try:
            if target == 'fastbootd':
                subprocess.check_call([fb, 'reboot', 'fastboot'])
            else:
                subprocess.check_call([fb, 'reboot-bootloader'])
            self._append("等待设备重连(15s)...")
            QTimer.singleShot(0, lambda: None)
            import time as _t
            _t.sleep(15)
            return True
        except Exception as e:
            self._append(f"切换模式失败：{e}")
            return False

    def _flash_partition(self):
        img = self.img_edit.text().strip()
        part = self.part_combo.currentText().strip()
        if not img or not os.path.isfile(img):
            MessageDialog("提示", "请选择有效的镜像文件", self).exec()
            return
        if not part:
            MessageDialog("提示", "请输入分区名", self).exec()
            return
        slot = self.slot_combo.currentText()
        if slot != "不指定":
            # 仅在未显式写 _a/_b 时追加
            if not (part.endswith('_a') or part.endswith('_b')):
                part = part + slot
        target_mode = self.mode_combo.currentText()
        if self.auto_switch.isChecked():
            if not self._ensure_mode(target_mode):
                return
        cmd = [self.fastboot_path, 'flash', part, img]
        self._run_proc(cmd)

    def _run_adb(self):
        # 已改为独立终端界面，不再在此处实现
        pass

    def _run_proc(self, cmd):
        if self._thread and self._thread.isRunning():
            QMessageBox.information(self, "提示", "已有任务在执行中")
            return
        # self.out.clear()
        self._append("运行: " + " ".join(cmd))
        self._thread = QThread(self)
        self._worker = _ProcWorker(cmd)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.output.connect(self._append, Qt.QueuedConnection)
        self._worker.finished.connect(self._on_finished, Qt.QueuedConnection)
        self._thread.start()

    def _on_finished(self, code: int):
        self._append(f"完成，退出码: {code}")
        try:
            if self._thread:
                self._thread.quit()
                self._thread.wait(1500)
        except Exception:
            pass
        self._thread = None
        self._worker = None

    def cleanup(self):
        try:
            # stop native poll timer and process
            if hasattr(self, '_native_timer') and self._native_timer:
                try:
                    self._native_timer.stop()
                    self._native_timer.deleteLater()
                except Exception:
                    pass
                self._native_timer = None
            if hasattr(self, '_native_proc') and self._native_proc:
                try:
                    if self._native_proc and self._native_proc.poll() is None:
                        self._native_proc.terminate()
                except Exception:
                    pass
                self._native_proc = None
            # stop running worker thread
            if hasattr(self, '_thread') and self._thread:
                try:
                    if self._thread.isRunning():
                        self._thread.quit(); self._thread.wait(1500)
                except Exception:
                    pass
            if hasattr(self, '_boot_fix_thread') and self._boot_fix_thread:
                try:
                    if self._boot_fix_thread.isRunning():
                        self._boot_fix_thread.quit(); self._boot_fix_thread.wait(1500)
                except Exception:
                    pass
            if hasattr(self, '_frp_thread') and self._frp_thread:
                try:
                    if self._frp_thread.isRunning():
                        self._frp_thread.quit(); self._frp_thread.wait(1500)
                except Exception:
                    pass
            if hasattr(self, '_unbrick_thread') and self._unbrick_thread:
                try:
                    if self._unbrick_thread.isRunning():
                        self._unbrick_thread.quit(); self._unbrick_thread.wait(1500)
                except Exception:
                    pass
        except Exception:
            pass

    # 工具箱入口回调
    def _open_partition_flash(self):
        dlg = _PartitionFlashDialog(self.fastboot_path, self)
        dlg.exec()

    def _open_payload_extract(self):
        dlg = _PayloadExtractDialog(self)
        dlg.exec()

    def _open_adb_terminal(self):
        try:
            if os.name == 'nt':
                subprocess.Popen(['cmd.exe', '/K', self.adb_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen([self.adb_path])
        except Exception as e:
            QMessageBox.critical(self, "失败", f"无法打开终端：{e}")

    def _check_flash_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择刷机配置文件", "", "配置文件 (*.txt);;所有文件 (*.*)")
        if not path:
            return
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            MessageDialog("错误", f"无法读取文件: {e}", self).exec()
            return
        
        errors = []
        warnings = []
        has_device = False
        has_mode = False
        current_mode = None
        
        valid_modes = {'bootloader', 'fastbootd'}
        valid_commands = {'system', 'wipe-data', 'set-a', 'set-b'}
        
        for line_num, line in enumerate(lines, 1):
            original_line = line
            line = line.strip()
            col = len(original_line) - len(original_line.lstrip()) + 1
            
            if not line or line.startswith('#'):
                continue
            
            if line.startswith('device:'):
                has_device = True
                device_id = line.split(':', 1)[1].strip() if ':' in line else ''
                if not device_id:
                    errors.append({
                        'line': line_num,
                        'col': col + 7,
                        'type': '错误',
                        'msg': 'device: 后面缺少设备型号',
                        'suggestion': '示例: device:codename'
                    })
                continue
            
            if line in valid_modes:
                has_mode = True
                current_mode = line
                continue
            
            if line in valid_commands:
                if line == 'wipe-data':
                    warnings.append({
                        'line': line_num,
                        'col': col,
                        'type': '警告',
                        'msg': 'wipe-data 已被 UI 控制，配置文件中的此行将被忽略',
                        'suggestion': '删除此行，由工具箱 UI 复选框控制'
                    })
                continue
            
            if line.startswith('-'):
                if not current_mode:
                    errors.append({
                        'line': line_num,
                        'col': col,
                        'type': '错误',
                        'msg': '分区指令必须在 bootloader 或 fastbootd 模式之后',
                        'suggestion': '在此行之前添加 bootloader 或 fastbootd'
                    })
                    continue
                
                line = line[1:]
                parts = line.split()
                if not parts:
                    errors.append({
                        'line': line_num,
                        'col': col + 1,
                        'type': '错误',
                        'msg': '分区名称为空',
                        'suggestion': '示例: -boot_ab 或 -recovery'
                    })
                    continue
                
                partition = parts[0]
                
                if len(parts) > 1:
                    cmd = parts[1]
                    if cmd == 'disable':
                        if not partition.startswith('vbmeta'):
                            warnings.append({
                                'line': line_num,
                                'col': col + len(partition) + 2,
                                'type': '警告',
                                'msg': 'disable 通常只用于 vbmeta 分区',
                                'suggestion': '请确认是否需要禁用 AVB'
                            })
                    elif cmd == 'del':
                        if current_mode != 'fastbootd':
                            errors.append({
                                'line': line_num,
                                'col': col + len(partition) + 2,
                                'type': '错误',
                                'msg': '逻辑分区删除必须在 fastbootd 模式下',
                                'suggestion': '在此行之前添加 fastbootd'
                            })
                    elif cmd == 'add':
                        if current_mode != 'fastbootd':
                            errors.append({
                                'line': line_num,
                                'col': col + len(partition) + 2,
                                'type': '错误',
                                'msg': '逻辑分区创建必须在 fastbootd 模式下',
                                'suggestion': '在此行之前添加 fastbootd'
                            })
                        if len(parts) < 3:
                            errors.append({
                                'line': line_num,
                                'col': col + len(partition) + 6,
                                'type': '错误',
                                'msg': 'add 命令缺少分区大小',
                                'suggestion': '示例: -my_product add 1M'
                            })
                    else:
                        warnings.append({
                            'line': line_num,
                            'col': col + len(partition) + 2,
                            'type': '警告',
                            'msg': f'未知的命令: {cmd}',
                            'suggestion': '支持的命令: disable, del, add'
                        })
                continue
            
            errors.append({
                'line': line_num,
                'col': col,
                'type': '错误',
                'msg': f'未知的指令: {line[:30]}...' if len(line) > 30 else f'未知的指令: {line}',
                'suggestion': '支持: device:, bootloader, fastbootd, -partition, system'
            })
        
        if not has_device:
            errors.insert(0, {
                'line': 1,
                'col': 1,
                'type': '错误',
                'msg': '配置文件缺少 device: 字段',
                'suggestion': '在文件开头添加: device:OP5551L1'
            })
        
        if not has_mode:
            warnings.append({
                'line': 1,
                'col': 1,
                'type': '警告',
                'msg': '配置文件中没有模式切换指令',
                'suggestion': '建议添加 bootloader 或 fastbootd'
            })
        
        dlg = _ConfigCheckDialog(path, errors, warnings, self)
        dlg.exec()


    def _open_bootloader_unlock(self):
        dlg = _BootloaderUnlockDialog(self.fastboot_path, self)
        dlg.exec()

    def _repair_tee(self):
        InfoBar.info("提示", "功能开发中...", parent=self, position=InfoBarPosition.TOP, isClosable=True)

    def _repair_bootloader(self):
        if self._boot_fix_thread and self._boot_fix_thread.isRunning():
            InfoBar.info('提示', '修复任务正在进行', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        mode, serial = svc.detect_connection_mode()
        if mode != 'system':
            InfoBar.warning('提示', '请在系统模式下连接设备后再尝试', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        if not ABL_IMAGE.exists():
            InfoBar.error('错误', f'修复镜像不存在: {ABL_IMAGE}', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        confirm_text = """该功能仅支持一加 Ace Pro（已解锁）使用，其它机型请勿尝试。
若设备未解锁导致 Fastboot 闪退，请使用 ColorOS 助手降级到 13.1 后再解锁。
确认继续？"""
        dlg = MessageDialog('确认修复', confirm_text, self)
        if dlg.exec() == MessageDialog.Rejected:
            self._append('已取消修复操作')
            return
        # self.out.clear()
        self._append('开始修复 Bootloader：Ace Pro 专用流程')
        self._boot_fix_thread = QThread()
        self._boot_fix_worker = _BootFixWorker(self.adb_path, self.fastboot_path, str(ABL_IMAGE))
        self._boot_fix_worker.moveToThread(self._boot_fix_thread)
        self._boot_fix_thread.started.connect(self._boot_fix_worker.run)
        self._boot_fix_worker.log.connect(self._append, Qt.QueuedConnection)
        self._boot_fix_worker.finished.connect(self._on_boot_fix_finished, Qt.QueuedConnection)
        self._boot_fix_worker.finished.connect(self._boot_fix_thread.quit)
        self._boot_fix_worker.finished.connect(self._boot_fix_worker.deleteLater)
        self._boot_fix_thread.finished.connect(self._boot_fix_thread.deleteLater)
        self._boot_fix_thread.start()

    def _remove_google_lock(self):
        if self._frp_thread and self._frp_thread.isRunning():
            InfoBar.info('提示', '任务正在进行中', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return

        mode, serial = svc.detect_connection_mode()
        if mode != 'system':
            InfoBar.warning('提示', '请在系统模式下连接设备并开启调试后再尝试', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return

        confirm_text = """此功能用于移除因忘记退出 Google 账号导致的无法进入主屏幕。

操作逻辑：
adb shell su -c 'dd if=/dev/zero of=/dev/block/bootdevice/by-name/frp'

前提条件：
1. 手机处于系统模式或TWRP recovery模式（开启adb功能）且连接正常
2. 手机已获取 Root 权限(仅系统模式)
3. 执行期间需留意手机弹窗，授予 Shell Root 权限

是否继续？"""
        dlg = MessageDialog('移除 Google 锁', confirm_text, self)
        if dlg.exec() == MessageDialog.Rejected:
            return

        # self.out.clear()
        self._append('开始执行移除 Google 锁流程...')
        
        self._frp_thread = QThread()
        self._frp_worker = _GoogleLockWorker(self.adb_path)
        self._frp_worker.moveToThread(self._frp_thread)
        
        self._frp_thread.started.connect(self._frp_worker.run)
        self._frp_worker.log.connect(self._append, Qt.QueuedConnection)
        self._frp_worker.finished.connect(self._on_frp_finished, Qt.QueuedConnection)
        self._frp_worker.finished.connect(self._frp_thread.quit)
        self._frp_worker.finished.connect(self._frp_worker.deleteLater)
        self._frp_thread.finished.connect(self._frp_thread.deleteLater)
        
        self._frp_thread.start()

    def _on_frp_finished(self, ok: bool, msg: str):
        if ok:
            InfoBar.success('完成', msg, parent=self, position=InfoBarPosition.TOP, isClosable=True)
        else:
            InfoBar.error('失败', msg, parent=self, position=InfoBarPosition.TOP, isClosable=True)
        self._append(msg)
        
        # Cleanup
        try:
            if self._frp_thread:
                self._frp_thread.quit()
                self._frp_thread.wait(1500)
        except Exception:
            pass
        self._frp_thread = None
        self._frp_worker = None

    def _fast_unbrick(self):
        if self._unbrick_thread and self._unbrick_thread.isRunning():
            InfoBar.info('提示', '任务正在进行中', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return

        mode, serial = svc.detect_connection_mode()
        if not serial:
            InfoBar.warning('提示', '未检测到设备，请确保 ADB 连接正常', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
             
        confirm_text = """此功能用于移除所有 Magisk 模块以恢复系统启动。
        
操作逻辑：
adb shell Magisk --remove-modules

前提条件：
1. 手机 ADB 连接正常（开机卡 Logo 或 Recovery 模式）
2. 仅支持 Magisk 管理器（不支持 KernelSU）

是否继续？"""
        dlg = MessageDialog('极速救砖', confirm_text, self)
        if dlg.exec() == MessageDialog.Rejected:
            return

        # self.out.clear()
        self._append('开始执行极速救砖流程...')
        
        self._unbrick_thread = QThread()
        self._unbrick_worker = _MagiskRemoveModulesWorker(self.adb_path)
        self._unbrick_worker.moveToThread(self._unbrick_thread)
        
        self._unbrick_thread.started.connect(self._unbrick_worker.run)
        self._unbrick_worker.log.connect(self._append, Qt.QueuedConnection)
        self._unbrick_worker.finished.connect(self._on_unbrick_finished, Qt.QueuedConnection)
        self._unbrick_worker.finished.connect(self._unbrick_thread.quit)
        self._unbrick_worker.finished.connect(self._unbrick_worker.deleteLater)
        self._unbrick_thread.finished.connect(self._unbrick_thread.deleteLater)
        
        self._unbrick_thread.start()

    def _on_unbrick_finished(self, ok: bool, msg: str):
        if ok:
            InfoBar.success('完成', msg, parent=self, position=InfoBarPosition.TOP, isClosable=True)
        else:
            InfoBar.error('失败', msg, parent=self, position=InfoBarPosition.TOP, isClosable=True)
        self._append(msg)
        
        # Cleanup
        try:
            if self._unbrick_thread:
                self._unbrick_thread.quit()
                self._unbrick_thread.wait(1500)
        except Exception:
            pass
        self._unbrick_thread = None
        self._unbrick_worker = None

    def _on_boot_fix_finished(self, ok: bool, msg: str):
        self._append(msg or '修复流程已结束，设备正在重启')
        InfoBar.success('完成', msg or '修复完成', parent=self, position=InfoBarPosition.TOP, isClosable=True)
        try:
            if self._boot_fix_thread:
                self._boot_fix_thread.quit()
                self._boot_fix_thread.wait(1500)
        except Exception:
            pass
        self._boot_fix_thread = None
        self._boot_fix_worker = None


# --------------- 子界面实现 ---------------

class _PartitionFlashDialog(QDialog):
    def __init__(self, fastboot_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("单分区刷入")
        self.fastboot_path = fastboot_path
        self._thread: Optional[QThread] = None
        self._worker: Optional[_ProcWorker] = None

        layout = QVBoxLayout(self)
        # 预置分区
        base_parts = "abl aop aop_config bluetooth boot cpucp devcfg dsp dtbo engineering_cdt featenabler hyp imagefv keymaster modem oplusstanvbk oplus_sec qupfw recovery shrm splash tz uefi uefisecapp vendor_boot xbl xbl_config xbl_ramdump".split()
        vbmeta_parts = ["vbmeta", "vbmeta_system", "vbmeta_vendor"]
        logical_parts = "my_bigball my_carrier my_company my_engineering my_heytap my_manifest my_preload my_product my_region my_stock odm odm_dlkm product system system_ext vendor vendor_dlkm".split()
        extra_parts = ["boot", "recovery", "modem", "vendor_boot", "dtbo"]
        partitions = []
        for p in base_parts + vbmeta_parts + logical_parts + extra_parts:
            if p not in partitions:
                partitions.append(p)

        row1 = QHBoxLayout()
        self.part_combo = ComboBox(self); self.part_combo.addItems(partitions)
        self.slot_combo = ComboBox(self); self.slot_combo.addItems(["不指定", "_a", "_b"]) 
        self.mode_combo = ComboBox(self); self.mode_combo.addItems(["fastbootd", "bootloader"]) 
        self.auto_switch = QCheckBox("自动切换模式"); self.auto_switch.setChecked(True)
        row1.addWidget(QLabel("分区")); row1.addWidget(self.part_combo)
        row1.addWidget(QLabel("槽位")); row1.addWidget(self.slot_combo)
        row1.addWidget(QLabel("目标模式")); row1.addWidget(self.mode_combo)
        row1.addWidget(self.auto_switch)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.img_edit = QLineEdit(); self.img_edit.setPlaceholderText("选择要刷入的 .img 文件")
        btn_pick = QPushButton("选择镜像"); btn_pick.clicked.connect(self._pick_img)
        self.run_btn = QPushButton("刷入分区"); self.run_btn.clicked.connect(self._flash_partition)
        row2.addWidget(QLabel("镜像")); row2.addWidget(self.img_edit); row2.addWidget(btn_pick); row2.addWidget(self.run_btn)
        layout.addLayout(row2)

        self.out = QTextEdit(); self.out.setReadOnly(True)
        try:
            from PySide6.QtCore import Qt as _Qt
            self.out.setVerticalScrollBarPolicy(_Qt.ScrollBarAlwaysOff)
            self.out.setHorizontalScrollBarPolicy(_Qt.ScrollBarAlwaysOff)
        except Exception:
            pass
        self.out_view = SmoothScrollArea(self)
        try:
            self.out_view.setWidget(self.out)
            self.out_view.setWidgetResizable(True)
        except Exception:
            pass
        layout.addWidget(self.out_view)

    def _pick_img(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择镜像", "", "镜像 (*.img);;所有文件 (*.*)")
        if path:
            self.img_edit.setText(path)

    def _ensure_mode(self, target: str) -> bool:
        fb = self.fastboot_path
        try:
            if target == 'fastbootd':
                subprocess.check_call([fb, 'reboot', 'fastboot'])
            else:
                subprocess.check_call([fb, 'reboot-bootloader'])
            self.out.append("等待设备重连(15s)...")
            import time as _t
            _t.sleep(15)
            return True
        except Exception as e:
            self.out.append(f"切换模式失败：{e}")
            return False

    def _flash_partition(self):
        img = self.img_edit.text().strip()
        part = self.part_combo.currentText().strip()
        if not img or not os.path.isfile(img):
            QMessageBox.warning(self, "提示", "请选择有效的镜像文件")
            return
        if not part:
            QMessageBox.warning(self, "提示", "请输入分区名")
            return
        slot = self.slot_combo.currentText()
        if slot != "不指定":
            if not (part.endswith('_a') or part.endswith('_b')):
                part = part + slot
        target_mode = self.mode_combo.currentText()
        if self.auto_switch.isChecked():
            if not self._ensure_mode(target_mode):
                return
        cmd = [self.fastboot_path, 'flash', part, img]
        self._run_proc(cmd)

    def _run_proc(self, cmd):
        if hasattr(self, '_thread') and self._thread and self._thread.isRunning():
            QMessageBox.information(self, "提示", "已有任务在执行中")
            return
        self.out.clear()
        self.out.append("运行: " + " ".join(cmd))
        self._thread = QThread(self)
        self._worker = _ProcWorker(cmd)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.output.connect(self.out.append, Qt.QueuedConnection)
        self._worker.finished.connect(self._on_finished, Qt.QueuedConnection)
        self._thread.start()

    def _on_finished(self, code: int):
        self.out.append(f"完成，退出码: {code}")
        try:
            if self._thread:
                self._thread.quit(); self._thread.wait(1500)
        except Exception:
            pass
        self._thread = None
        self._worker = None


class _ConfigCheckDialog(QDialog):
    def __init__(self, config_path: str, errors: list, warnings: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置文件检测结果")
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        info_label = QLabel(f"文件: {os.path.basename(config_path)}")
        info_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(info_label)
        
        summary = QLabel(f"错误: {len(errors)} 个  |  警告: {len(warnings)} 个")
        if errors:
            summary.setStyleSheet("color: #ff4d4f; font-size: 13px;")
        elif warnings:
            summary.setStyleSheet("color: #faad14; font-size: 13px;")
        else:
            summary.setText("✅ 没有发现问题")
            summary.setStyleSheet("color: #52c41a; font-size: 13px; font-weight: bold;")
        layout.addWidget(summary)
        
        result_text = QTextEdit()
        result_text.setReadOnly(True)
        result_text.setStyleSheet("font-family: 'Consolas', 'Courier New', monospace; font-size: 12px;")
        
        content = []
        
        if errors:
            content.append("\n=== 错误 (Errors) ===")
            for err in errors:
                content.append(f"\n❌ 行 {err['line']}, 列 {err['col']}: {err['type']}")
                content.append(f"   {err['msg']}")
                if 'suggestion' in err:
                    content.append(f"   建议: {err['suggestion']}")
        
        if warnings:
            content.append("\n\n=== 警告 (Warnings) ===")
            for warn in warnings:
                content.append(f"\n⚠️  行 {warn['line']}, 列 {warn['col']}: {warn['type']}")
                content.append(f"   {warn['msg']}")
                if 'suggestion' in warn:
                    content.append(f"   建议: {warn['suggestion']}")
        
        if not errors and not warnings:
            content.append("\n✅ 配置文件语法正确，没有发现问题！")
            content.append("\n可以安全使用此配置文件进行刷机。")
        
        result_text.setPlainText('\n'.join(content))
        layout.addWidget(result_text)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)


class _BootloaderUnlockDialog(QDialog):
    def __init__(self, fastboot_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("解锁 Bootloader")
        self.fastboot_path = fastboot_path or 'fastboot'
        layout = QVBoxLayout(self)

        tip = QLabel("请先将手机重启至 bootloader 模式后，再点击下方按钮开始解锁（注意：解锁bootloader会清除手机中的全部数据！！）")
        layout.addWidget(tip)

        row = QHBoxLayout()
        self.run_btn = QPushButton("开始解锁")
        self.run_btn.clicked.connect(self._run)
        row.addStretch(1)
        row.addWidget(self.run_btn)
        layout.addLayout(row)

        self.out = QTextEdit(); self.out.setReadOnly(True)
        layout.addWidget(self.out)

    def _run(self):
        cmd = [self.fastboot_path, 'flashing', 'unlock']
        try:
            kw = {}
            if os.name == 'nt':
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                kw.update({'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW})
            subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
            self.out.append("已下发命令：fastboot flashing unlock")
            self.out.append("请在手机上操作：手机选择 UNLOCK THE BOOTLOADER(音量键选择，电源键确定)")
            MessageDialog("提示", "请在手机上操作：手机选择 UNLOCK THE BOOTLOADER(音量键选择，电源键确定)", self).exec()
        except FileNotFoundError:
            MessageDialog("提示", "未找到 fastboot，可将 fastboot.exe 放至 bin 目录或配置系统 PATH。", self).exec()
        except Exception as e:
            self.out.append(f"启动失败：{e}")


class _PayloadExtractDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("payload.bin 处理")
        self.resize(700, 500)
        self._worker = None
        self._thread = None
        
        layout = QVBoxLayout(self)
        
        # 模式选择
        mode_group = QWidget()
        mode_layout = QHBoxLayout(mode_group)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.mode_local = QCheckBox("本地文件提取")
        self.mode_local.setChecked(True)
        self.mode_online = QCheckBox("在线提取")
        mode_layout.addWidget(QLabel("提取模式:"))
        mode_layout.addWidget(self.mode_local)
        mode_layout.addWidget(self.mode_online)
        mode_layout.addStretch(1)
        layout.addWidget(mode_group)
        
        # 本地文件输入
        self.local_widget = QWidget()
        local_layout = QHBoxLayout(self.local_widget)
        local_layout.setContentsMargins(0, 0, 0, 0)
        self.local_edit = QLineEdit()
        self.local_edit.setPlaceholderText("选择 payload.bin 或包含 payload.bin 的 ZIP 文件")
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._browse_local)
        local_layout.addWidget(QLabel("文件路径:"))
        local_layout.addWidget(self.local_edit)
        local_layout.addWidget(btn_browse)
        layout.addWidget(self.local_widget)
        
        # 在线 URL 输入
        self.online_widget = QWidget()
        online_layout = QHBoxLayout(self.online_widget)
        online_layout.setContentsMargins(0, 0, 0, 0)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("输入 OTA 更新包 URL（包含 payload.bin 的 ZIP）")
        online_layout.addWidget(QLabel("URL:"))
        online_layout.addWidget(self.url_edit)
        layout.addWidget(self.online_widget)
        self.online_widget.setVisible(False)
        
        # 分区选择
        partition_group = QWidget()
        partition_layout = QVBoxLayout(partition_group)
        partition_layout.setContentsMargins(0, 0, 0, 0)
        partition_label = QLabel("要提取的分区（留空提取全部）:")
        self.partition_edit = QLineEdit()
        self.partition_edit.setPlaceholderText("例如: boot,vendor,system 或留空提取全部")
        partition_layout.addWidget(partition_label)
        partition_layout.addWidget(self.partition_edit)
        layout.addWidget(partition_group)
        
        # 输出目录
        out_group = QWidget()
        out_layout = QHBoxLayout(out_group)
        out_layout.setContentsMargins(0, 0, 0, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("选择输出目录")
        btn_out = QPushButton("浏览...")
        btn_out.clicked.connect(self._browse_output)
        out_layout.addWidget(QLabel("输出目录:"))
        out_layout.addWidget(self.out_edit)
        out_layout.addWidget(btn_out)
        layout.addWidget(out_group)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("开始提取")
        self.run_btn.clicked.connect(self._run_extract)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.run_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        
        # 日志输出
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        
        # 信号连接
        self.mode_local.toggled.connect(self._on_mode_changed)
        self.mode_online.toggled.connect(self._on_mode_changed)
    
    def _on_mode_changed(self):
        if self.mode_local.isChecked():
            self.mode_online.setChecked(False)
            self.local_widget.setVisible(True)
            self.online_widget.setVisible(False)
        elif self.mode_online.isChecked():
            self.mode_local.setChecked(False)
            self.local_widget.setVisible(False)
            self.online_widget.setVisible(True)
    
    def _browse_local(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "", 
            "Payload 文件 (payload.bin *.zip);;所有文件 (*.*)"
        )
        if path:
            self.local_edit.setText(path)
    
    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.out_edit.setText(path)
    
    def _run_extract(self):
        # 验证输入
        if self.mode_local.isChecked():
            source = self.local_edit.text().strip()
            if not source or not os.path.exists(source):
                QMessageBox.warning(self, "提示", "请选择有效的文件")
                return
        else:
            source = self.url_edit.text().strip()
            if not source or not source.startswith('http'):
                QMessageBox.warning(self, "提示", "请输入有效的 HTTP/HTTPS URL")
                return
        
        out_dir = self.out_edit.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "提示", "请选择输出目录")
            return
        
        os.makedirs(out_dir, exist_ok=True)
        
        partitions = self.partition_edit.text().strip()
        
        # 禁用按钮
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log.clear()
        self.log.append(f"开始提取...")
        self.log.append(f"源: {source}")
        self.log.append(f"输出: {out_dir}")
        if partitions:
            self.log.append(f"分区: {partitions}")
        else:
            self.log.append("分区: 全部")
        self.log.append("")
        
        # 创建工作线程
        self._thread = QThread(self)
        self._worker = _PayloadWorker(source, out_dir, partitions)
        self._worker.moveToThread(self._thread)
        
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._on_log)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        
        self._thread.start()
    
    def _cancel(self):
        if self._worker:
            self._worker.stop()
        self.log.append("\n用户取消操作")
        self._cleanup()
    
    def _on_log(self, msg):
        self.log.append(msg)
    
    def _on_finished(self):
        self.log.append("\n✅ 提取完成！")
        self._cleanup()
    
    def _on_error(self, error):
        self.log.append(f"\n❌ 错误: {error}")
        self._cleanup()
    
    def _cleanup(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
    
    def closeEvent(self, event):
        if self._thread and self._thread.isRunning():
            reply = QMessageBox.question(
                self, "确认", "提取正在进行中，确定要关闭吗？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            if self._worker:
                self._worker.stop()
        self._cleanup()
        super().closeEvent(event)


class _PayloadWorker(QObject):
    log = Signal(str)
    finished = Signal()
    error = Signal(str)
    
    def __init__(self, source, output_dir, partitions):
        super().__init__()
        self.source = source
        self.output_dir = output_dir
        self.partitions = partitions
        self._stop = False
    
    def stop(self):
        self._stop = True
    
    def run(self):
        try:
            # 构建命令
            cmd = ['python', '-m', 'payload_dumper']
            
            # 添加分区参数
            if self.partitions:
                cmd.extend(['--partitions', self.partitions])
            
            # 添加输出目录
            cmd.extend(['--out', self.output_dir])
            
            # 添加源文件/URL
            cmd.append(self.source)
            
            self.log.emit(f"执行命令: {' '.join(cmd)}")
            self.log.emit("")
            
            # 执行命令
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            
            # 实时输出日志
            while True:
                if self._stop:
                    process.terminate()
                    return
                
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                
                if line:
                    self.log.emit(line.rstrip())
            
            # 检查退出码
            returncode = process.wait()
            if returncode == 0:
                self.finished.emit()
            else:
                self.error.emit(f"进程退出码: {returncode}")
                
        except Exception as e:
            self.error.emit(str(e))
