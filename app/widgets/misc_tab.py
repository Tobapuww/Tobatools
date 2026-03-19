import os
import subprocess
import shlex
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QObject, QThread, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QLabel, QComboBox, QLineEdit, QMessageBox, QGridLayout, QDialog, QCheckBox
)

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, TitleLabel, FluentIcon,
    InfoBar, InfoBarPosition, MessageDialog, SmoothScrollArea, ComboBox,
    SettingCardGroup, PushSettingCard, CaptionLabel
)

from app.components.log_widget import LogWidget
from app.services import adb_service as svc

from app.widgets.misc_tools.workers import (
    resolve_bin,
    ProcWorker,
    BootFixWorker,
    GoogleLockWorker,
    MagiskRemoveModulesWorker,
)
from app.widgets.misc_tools.partition_flash_dialog import _PartitionFlashDialog
from app.widgets.misc_tools.payload_extract_dialog import _PayloadExtractDialog
from app.widgets.misc_tools.ofp_dialog import _OFPDialog
from app.widgets.misc_tools.module_manager_dialog import _ModuleManagerDialog
from app.widgets.misc_tools.run_shell_script_dialog import _RunShellScriptDialog
from app.widgets.misc_tools.config_check_dialog import _ConfigCheckDialog
from app.widgets.misc_tools.bootloader_unlock_dialog import _BootloaderUnlockDialog
from app.widgets.misc_tools.display_tweaks_dialog import _DisplayTweaksDialog
from app.widgets.misc_tools.battery_sim_dialog import _BatterySimDialog
from app.widgets.misc_tools.screen_timeout_dialog import _ScreenTimeoutDialog
from app.widgets.misc_tools.statusbar_icons_dialog import _StatusBarIconsDialog
from app.widgets.misc_tools.font_scale_dialog import _FontScaleDialog
from app.widgets.misc_tools.animation_scale_dialog import _AnimationScaleDialog
from app.widgets.misc_tools.accessibility_reset_dialog import _AccessibilityResetDialog
from app.widgets.misc_tools.key_sim_dialog import _KeySimDialog


ABL_IMAGE = svc.BIN_DIR / 'add_images' / 'abl.img'


class MiscTab(QWidget):
    log_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self._thread: Optional[QThread] = None
        self._worker: Optional[ProcWorker] = None
        self._boot_fix_thread: Optional[QThread] = None
        self._boot_fix_worker: Optional[BootFixWorker] = None
        self._frp_thread: Optional[QThread] = None
        self._frp_worker: Optional[GoogleLockWorker] = None
        self._unbrick_thread: Optional[QThread] = None
        self._unbrick_worker: Optional[MagiskRemoveModulesWorker] = None
        self._native_proc: Optional[subprocess.Popen] = None
        self._native_timer: Optional[QTimer] = None

        adb_bin = getattr(svc, 'ADB_BIN', None)
        fastboot_bin = getattr(svc, 'FASTBOOT_BIN', None)
        self.adb_path = resolve_bin(adb_bin if adb_bin else None, 'adb')
        self.fastboot_path = resolve_bin(fastboot_bin if fastboot_bin else None, 'fastboot')

        self._init_ui()

    def _init_ui(self):
        self.v_layout = QVBoxLayout(self)
        self.v_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = SmoothScrollArea(self)
        self.v_layout.addWidget(self.scroll_area)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea {border: none; background: transparent;}")

        self.scroll_widget = QWidget(self.scroll_area)
        self.scroll_widget.setStyleSheet("QWidget {background: transparent;}")
        self.scroll_area.setWidget(self.scroll_widget)

        self.layout = QVBoxLayout(self.scroll_widget)
        self.layout.setContentsMargins(32, 32, 32, 32)
        self.layout.setSpacing(24)

        main_h_layout = QHBoxLayout()
        main_h_layout.setSpacing(24)

        left_col = QVBoxLayout()
        left_col.setSpacing(24)
        
        self.common_group = SettingCardGroup("常用工具", self)
        self._build_common_tools()
        left_col.addWidget(self.common_group)
        
        self.advanced_group = SettingCardGroup("高级操作", self)
        self._build_advanced_tools()
        left_col.addWidget(self.advanced_group)
        
        left_col.addStretch(1)

        right_col = QVBoxLayout()
        right_col.setSpacing(24)
        
        self.sim_group = SettingCardGroup("模拟控制", self)
        self._build_sim_tools()
        right_col.addWidget(self.sim_group)
        
        right_col.addStretch(1)

        left_w = QWidget()
        left_w.setLayout(left_col)
        right_w = QWidget()
        right_w.setLayout(right_col)

        main_h_layout.addWidget(left_w, 1)
        main_h_layout.addWidget(right_w, 1)

        self.layout.addLayout(main_h_layout)

        # Log Widget
        self.log_widget = LogWidget(self)
        self.log_widget.setFixedHeight(200)
        self.layout.addWidget(self.log_widget)

    def _build_common_tools(self):
        self.card_flash = PushSettingCard("打开", FluentIcon.TILES, "单分区刷入", "选择镜像并刷入指定分区（可选槽位 / 模式）", self.common_group)
        self.card_flash.clicked.connect(self._open_partition_flash)

        self.card_payload = PushSettingCard("打开", getattr(FluentIcon, "ZIP_FOLDER", FluentIcon.FOLDER), "Payload.bin 处理", "在线或本地提取 payload.bin，支持全量和指定分区", self.common_group)
        self.card_payload.clicked.connect(self._open_payload_extract)

        self.card_ofp = PushSettingCard("打开", getattr(FluentIcon, "ZIP_FOLDER", FluentIcon.FOLDER), "OFP 处理", "解密并提取 OPPO/realme 的 .ofp 固件", self.common_group)
        self.card_ofp.clicked.connect(self._open_ofp_tool)

        self.common_group.addSettingCard(self.card_flash)
        self.common_group.addSettingCard(self.card_payload)
        self.common_group.addSettingCard(self.card_ofp)

    def _build_advanced_tools(self):
        self.card_unlock = PushSettingCard("执行", getattr(FluentIcon, "UNPIN", getattr(FluentIcon, "UNLOCK", FluentIcon.SETTING)), "解锁 Bootloader", "进入 Bootloader 后执行 fastboot flashing unlock", self.advanced_group)
        self.card_unlock.clicked.connect(self._open_bootloader_unlock)

        self.card_repair = PushSettingCard("修复", getattr(FluentIcon, "BROOM", getattr(FluentIcon, "WIFI", FluentIcon.SETTING)), "修复 Bootloader (Ace Pro)", "修复 Ace Pro Bootloader 闪退", self.advanced_group)
        self.card_repair.clicked.connect(self._repair_bootloader)

        self.card_frp = PushSettingCard("执行", getattr(FluentIcon, "DELETE", FluentIcon.REMOVE), "移除 Google 锁", "移除因未退出 Google 账号导致的 FRP 锁（需 Root）", self.advanced_group)
        self.card_frp.clicked.connect(self._remove_google_lock)

        self.card_unbrick = PushSettingCard("执行", getattr(FluentIcon, "MEDICAL", FluentIcon.HELP), "极速救砖 (Magisk)", "恢复因刷入错误的 Magisk 模块导致的不开机", self.advanced_group)
        self.card_unbrick.clicked.connect(self._fast_unbrick)

        self.card_module_manager = PushSettingCard("打开", getattr(FluentIcon, "APPLICATION", FluentIcon.SETTING), "模块管理器 (Magisk/KernelSU)", "管理已安装模块：列表/启用/禁用/备份/移除/安装/批量安装（需 Root）", self.advanced_group)
        self.card_module_manager.clicked.connect(self._open_module_manager)

        self.card_tee = PushSettingCard("修复", getattr(FluentIcon, "FINGERPRINT", FluentIcon.HELP), "欧加真高通机型强行烧录可信执行环境TEE（实验性）", "通过烧录修复 TEE 假死导致的无法绑定国铁/开启无敌裸奔环境", self.advanced_group)
        self.card_tee.clicked.connect(self._repair_tee)

        self.card_adb = PushSettingCard("打开", getattr(FluentIcon, "COMMAND_PROMPT", FluentIcon.CODE), "ADB 终端", "打开原生终端窗口运行 ADB", self.advanced_group)
        self.card_adb.clicked.connect(self._open_adb_terminal)

        self.card_run_sh = PushSettingCard("打开", getattr(FluentIcon, "COMMAND_PROMPT", FluentIcon.CODE), "运行 Shell 脚本", "选择电脑上的 .sh 脚本，推送到手机并在终端交互执行", self.advanced_group)
        self.card_run_sh.clicked.connect(self._open_run_shell_script)

        self.card_config_check = PushSettingCard("检测", getattr(FluentIcon, "DOCUMENT", FluentIcon.DOCUMENT), "刷机配置文件检测", "检测配置文件语法错误，显示行号、列号和错误信息", self.advanced_group)
        self.card_config_check.clicked.connect(self._check_flash_config)

        self.advanced_group.addSettingCard(self.card_unlock)
        self.advanced_group.addSettingCard(self.card_repair)
        self.advanced_group.addSettingCard(self.card_frp)
        self.advanced_group.addSettingCard(self.card_unbrick)
        self.advanced_group.addSettingCard(self.card_module_manager)
        self.advanced_group.addSettingCard(self.card_tee)
        self.advanced_group.addSettingCard(self.card_adb)
        self.advanced_group.addSettingCard(self.card_run_sh)
        self.advanced_group.addSettingCard(self.card_config_check)

    def _build_sim_tools(self):
        self.card_display_tweaks = PushSettingCard("打开", getattr(FluentIcon, "DESKTOP", FluentIcon.SETTING), "显示属性修改", "分辨率 / 密度DPI / 最小宽度DP", self.sim_group)
        self.card_display_tweaks.clicked.connect(self._open_display_tweaks)

        self.card_battery_sim = PushSettingCard("打开", getattr(FluentIcon, "BATTERY", FluentIcon.POWER_BUTTON), "电池状态模拟", "电量 / 温度 / 充电类型", self.sim_group)
        self.card_battery_sim.clicked.connect(self._open_battery_sim)

        self.card_screen_timeout = PushSettingCard("打开", getattr(FluentIcon, "CLOCK", FluentIcon.HISTORY), "锁屏时间修改", "修改 screen_off_timeout", self.sim_group)
        self.card_screen_timeout.clicked.connect(self._open_screen_timeout)

        self.card_statusbar_icons = PushSettingCard("打开", getattr(FluentIcon, "VIEW", FluentIcon.HIDE), "隐藏状态栏图标", "时间/蓝牙/定位/WiFi/电池等", self.sim_group)
        self.card_statusbar_icons.clicked.connect(self._open_statusbar_icons)

        self.card_font_scale = PushSettingCard("打开", getattr(FluentIcon, "FONT", FluentIcon.EDIT), "字体调节", "字体缩放（最大 5 倍）", self.sim_group)
        self.card_font_scale.clicked.connect(self._open_font_scale)

        self.card_anim_scale = PushSettingCard("打开", getattr(FluentIcon, "AIRPLANE", FluentIcon.SPEED_HIGH), "动画速度", "窗口/过渡/动画时长", self.sim_group)
        self.card_anim_scale.clicked.connect(self._open_animation_scale)

        self.card_acc_reset = PushSettingCard("打开", getattr(FluentIcon, "REMOVE", FluentIcon.CLEAR_SELECTION), "一键关闭辅助功能", "TalkBack/随选朗读/放大/反色/色彩校正/高对比度", self.sim_group)
        self.card_acc_reset.clicked.connect(self._open_accessibility_reset)

        self.card_key_sim = PushSettingCard("打开", getattr(FluentIcon, "KEYBOARD", FluentIcon.GAME), "模拟按键", "音量/锁屏/返回/主页/数据流量等", self.sim_group)
        self.card_key_sim.clicked.connect(self._open_key_sim)

        self.sim_group.addSettingCard(self.card_display_tweaks)
        self.sim_group.addSettingCard(self.card_battery_sim)
        self.sim_group.addSettingCard(self.card_screen_timeout)
        self.sim_group.addSettingCard(self.card_statusbar_icons)
        self.sim_group.addSettingCard(self.card_font_scale)
        self.sim_group.addSettingCard(self.card_anim_scale)
        self.sim_group.addSettingCard(self.card_acc_reset)
        self.sim_group.addSettingCard(self.card_key_sim)

    def _append(self, text: str):
        self.log_widget.append_log(text)
        self.log_signal.emit(text)

    def cleanup(self):
        try:
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
            if hasattr(self, '_thread') and self._thread:
                try:
                    if self._thread.isRunning():
                        self._thread.quit()
                        self._thread.wait(1500)
                except Exception:
                    pass
            if hasattr(self, '_boot_fix_thread') and self._boot_fix_thread:
                try:
                    if self._boot_fix_thread.isRunning():
                        self._boot_fix_thread.quit()
                        self._boot_fix_thread.wait(1500)
                except Exception:
                    pass
            if hasattr(self, '_frp_thread') and self._frp_thread:
                try:
                    if self._frp_thread.isRunning():
                        self._frp_thread.quit()
                        self._frp_thread.wait(1500)
                except Exception:
                    pass
            if hasattr(self, '_unbrick_thread') and self._unbrick_thread:
                try:
                    if self._unbrick_thread.isRunning():
                        self._unbrick_thread.quit()
                        self._unbrick_thread.wait(1500)
                except Exception:
                    pass
        except Exception:
            pass

    def _open_partition_flash(self):
        dlg = _PartitionFlashDialog(self.fastboot_path, self)
        dlg.exec()

    def _open_payload_extract(self):
        dlg = _PayloadExtractDialog(self)
        dlg.exec()

    def _open_ofp_tool(self):
        dlg = _OFPDialog(self)
        dlg.exec()

    def _open_module_manager(self):
        dlg = _ModuleManagerDialog(self)
        dlg.exec()

    def _open_run_shell_script(self):
        dlg = _RunShellScriptDialog(self.adb_path, self)
        dlg.exec()

    def _open_adb_terminal(self):
        try:
            bin_dir = None
            try:
                bin_dir = str(getattr(svc, 'BIN_DIR', None) or '').strip() or None
            except Exception:
                bin_dir = None
            if os.name == 'nt':
                subprocess.Popen(
                    ['cmd.exe', '/K', 'adb'],
                    cwd=bin_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                subprocess.Popen(['adb'], cwd=bin_dir)
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
                    errors.append({'line': line_num, 'col': col + 7, 'type': '错误', 'msg': 'device: 后面缺少设备型号', 'suggestion': '示例: device:codename'})
                continue
            
            if line in valid_modes:
                has_mode = True
                current_mode = line
                continue
            
            if line in valid_commands:
                if line == 'wipe-data':
                    warnings.append({'line': line_num, 'col': col, 'type': '警告', 'msg': 'wipe-data 已被 UI 控制，配置文件中的此行将被忽略', 'suggestion': '删除此行，由工具箱 UI 复选框控制'})
                continue
            
            if line.startswith('-'):
                if not current_mode:
                    errors.append({'line': line_num, 'col': col, 'type': '错误', 'msg': '分区指令必须在 bootloader 或 fastbootd 模式之后', 'suggestion': '在此行之前添加 bootloader 或 fastbootd'})
                    continue
                
                line = line[1:]
                parts = line.split()
                if not parts:
                    errors.append({'line': line_num, 'col': col + 1, 'type': '错误', 'msg': '分区名称为空', 'suggestion': '示例: -boot_ab 或 -recovery'})
                    continue
                
                partition = parts[0]
                
                if len(parts) > 1:
                    cmd = parts[1]
                    if cmd == 'disable':
                        if not partition.startswith('vbmeta'):
                            warnings.append({'line': line_num, 'col': col + len(partition) + 2, 'type': '警告', 'msg': 'disable 通常只用于 vbmeta 分区', 'suggestion': '请确认是否需要禁用 AVB'})
                    elif cmd == 'del':
                        if current_mode != 'fastbootd':
                            errors.append({'line': line_num, 'col': col + len(partition) + 2, 'type': '错误', 'msg': '逻辑分区删除必须在 fastbootd 模式下', 'suggestion': '在此行之前添加 fastbootd'})
                    elif cmd == 'add':
                        if current_mode != 'fastbootd':
                            errors.append({'line': line_num, 'col': col + len(partition) + 2, 'type': '错误', 'msg': '逻辑分区创建必须在 fastbootd 模式下', 'suggestion': '在此行之前添加 fastbootd'})
                        if len(parts) < 3:
                            errors.append({'line': line_num, 'col': col + len(partition) + 6, 'type': '错误', 'msg': 'add 命令缺少分区大小', 'suggestion': '示例: -my_product add 1M'})
                    else:
                        warnings.append({'line': line_num, 'col': col + len(partition) + 2, 'type': '警告', 'msg': f'未知的命令: {cmd}', 'suggestion': '支持的命令: disable, del, add'})
                continue
            
            errors.append({'line': line_num, 'col': col, 'type': '错误', 'msg': f'未知的指令: {line[:30]}...' if len(line) > 30 else f'未知的指令: {line}', 'suggestion': '支持: device:, bootloader, fastbootd, -partition, system'})
        
        if not has_device:
            errors.insert(0, {'line': 1, 'col': 1, 'type': '错误', 'msg': '配置文件缺少 device: 字段', 'suggestion': '在文件开头添加: device:OP5551L1'})
        
        if not has_mode:
            warnings.append({'line': 1, 'col': 1, 'type': '警告', 'msg': '配置文件中没有模式切换指令', 'suggestion': '建议添加 bootloader 或 fastbootd'})
        
        dlg = _ConfigCheckDialog(path, errors, warnings, self)
        dlg.exec()

    def _open_bootloader_unlock(self):
        dlg = _BootloaderUnlockDialog(self.fastboot_path, self)
        dlg.exec()

    def _open_display_tweaks(self):
        dlg = _DisplayTweaksDialog(self)
        dlg.exec()

    def _open_battery_sim(self):
        dlg = _BatterySimDialog(self)
        dlg.exec()

    def _open_screen_timeout(self):
        dlg = _ScreenTimeoutDialog(self)
        dlg.exec()

    def _open_statusbar_icons(self):
        dlg = _StatusBarIconsDialog(self)
        dlg.exec()

    def _open_font_scale(self):
        dlg = _FontScaleDialog(self)
        dlg.exec()

    def _open_animation_scale(self):
        dlg = _AnimationScaleDialog(self)
        dlg.exec()

    def _open_accessibility_reset(self):
        dlg = _AccessibilityResetDialog(self)
        dlg.exec()

    def _open_key_sim(self):
        dlg = _KeySimDialog(self)
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
        self._append('开始修复 Bootloader：Ace Pro 专用流程')
        self._boot_fix_thread = QThread()
        self._boot_fix_worker = BootFixWorker(self.adb_path, self.fastboot_path, str(ABL_IMAGE))
        self._boot_fix_worker.moveToThread(self._boot_fix_thread)
        self._boot_fix_thread.started.connect(self._boot_fix_worker.run)
        self._boot_fix_worker.log.connect(self._append, Qt.QueuedConnection)
        self._boot_fix_worker.step_start.connect(self.log_widget.start_step, Qt.QueuedConnection)
        self._boot_fix_worker.step_finish.connect(self.log_widget.finish_step, Qt.QueuedConnection)
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

        self._append('开始执行移除 Google 锁流程...')
        
        self._frp_thread = QThread()
        self._frp_worker = GoogleLockWorker(self.adb_path)
        self._frp_worker.moveToThread(self._frp_thread)
        
        self._frp_thread.started.connect(self._frp_worker.run)
        self._frp_worker.log.connect(self._append, Qt.QueuedConnection)
        self._frp_worker.step_start.connect(self.log_widget.start_step, Qt.QueuedConnection)
        self._frp_worker.step_finish.connect(self.log_widget.finish_step, Qt.QueuedConnection)
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

        self._append('开始执行极速救砖流程...')
        
        self._unbrick_thread = QThread()
        self._unbrick_worker = MagiskRemoveModulesWorker(self.adb_path)
        self._unbrick_worker.moveToThread(self._unbrick_thread)
        
        self._unbrick_thread.started.connect(self._unbrick_worker.run)
        self._unbrick_worker.log.connect(self._append, Qt.QueuedConnection)
        self._unbrick_worker.step_start.connect(self.log_widget.start_step, Qt.QueuedConnection)
        self._unbrick_worker.step_finish.connect(self.log_widget.finish_step, Qt.QueuedConnection)
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
