import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFileDialog

from qfluentwidgets import (
    CardWidget,
    TitleLabel,
    CaptionLabel,
    BodyLabel,
    LineEdit,
    PushButton,
    PrimaryPushButton,
    InfoBar,
    InfoBarPosition,
    CheckBox,
)

from app.components.log_widget import LogWidget
from app.services import adb_service as svc


class _RunShellScriptDialog(QDialog):
    def __init__(self, adb_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('运行 Shell 脚本')
        self.resize(720, 400)

        self.adb_path = str(adb_path or '').strip() or 'adb'

        outer = QVBoxLayout(self)
        try:
            outer.setContentsMargins(24, 20, 24, 20)
            outer.setSpacing(12)
        except Exception:
            pass

        header = CardWidget(self)
        header_lay = QVBoxLayout(header)
        header_lay.setContentsMargins(16, 14, 16, 14)
        header_lay.setSpacing(4)
        header_lay.addWidget(TitleLabel('运行电脑上的 .sh 脚本', header))
        header_lay.addWidget(CaptionLabel('会将脚本推送到手机后执行，并弹出 Windows 终端进行交互；脚本结束后保留在 adb shell 状态', header))
        outer.addWidget(header)

        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        lay.addWidget(BodyLabel('脚本路径', card))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.edt_script = LineEdit(card)
        self.edt_script.setPlaceholderText('选择要运行的 .sh 脚本')
        self.btn_pick = PushButton('选择', card)
        self.btn_run = PrimaryPushButton('运行', card)
        row.addWidget(self.edt_script, 1)
        row.addWidget(self.btn_pick)
        row.addWidget(self.btn_run)
        lay.addLayout(row)

        opt_row = QHBoxLayout()
        opt_row.setSpacing(8)
        self.chk_root = CheckBox('使用 Root(su) 执行', card)
        self.chk_bash = CheckBox('使用 bash 执行(兼容脚本)', card)
        opt_row.addWidget(self.chk_root)
        opt_row.addWidget(self.chk_bash)
        opt_row.addStretch(1)
        lay.addLayout(opt_row)

        outer.addWidget(card)

        # Log Widget
        self.log = LogWidget(self)
        self.log.setFixedHeight(120)
        outer.addWidget(self.log)

        self.btn_pick.clicked.connect(self._pick)
        self.btn_run.clicked.connect(self._run)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 shell 脚本', '', 'Shell Script (*.sh);;所有文件 (*.*)')
        if path:
            self.edt_script.setText(path)

    def _run(self):
        script = self.edt_script.text().strip()
        if not script:
            InfoBar.warning('提示', '请先选择脚本', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        p = Path(script)
        if not p.exists() or not p.is_file():
            InfoBar.warning('提示', '脚本文件不存在', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return

        self.log.clear_log()
        
        import uuid
        sid_check = str(uuid.uuid4())
        self.log.start_step(sid_check, "检查设备连接")

        mode, serial = svc.detect_connection_mode()
        if mode != 'system':
            self.log.finish_step(sid_check, False, "非系统模式")
            InfoBar.warning('提示', '请在系统模式下连接设备后再运行脚本', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        if not serial:
            self.log.finish_step(sid_check, False, "无设备")
            InfoBar.warning('提示', '未检测到设备序列号', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        self.log.finish_step(sid_check, True, serial)

        sid_prep = str(uuid.uuid4())
        self.log.start_step(sid_prep, "准备脚本环境")

        remote = f'/data/local/tmp/{p.stem}_{abs(hash(str(p))) & 0xfffffff}.sh'

        adb = self.adb_path
        adb_args = [adb, '-s', serial]

        bin_dir = None
        try:
            bin_dir = str(getattr(svc, 'BIN_DIR', None) or '').strip() or None
        except Exception:
            bin_dir = None

        try:
            if os.name == 'nt':
                def _cmd(args: list[str]) -> str:
                    return subprocess.list2cmdline(args)

                use_root = False
                try:
                    use_root = bool(self.chk_root.isChecked())
                except Exception:
                    use_root = False

                use_bash = False
                try:
                    use_bash = bool(self.chk_bash.isChecked())
                except Exception:
                    use_bash = False

                # auto-detect bash scripts by shebang
                if not use_bash:
                    try:
                        with open(str(p), 'rb') as f:
                            first = f.readline(256)
                        try:
                            first_s = first.decode('utf-8', errors='ignore').strip().lower()
                        except Exception:
                            first_s = ''
                        if first_s.startswith('#!') and ('bash' in first_s):
                            use_bash = True
                    except Exception:
                        pass

                push_cmd = _cmd(adb_args + ['push', str(p), remote])
                chmod_cmd = _cmd(adb_args + ['shell', '-t', 'chmod', '755', remote])

                runner = 'bash' if use_bash else 'sh'
                if use_root:
                    run_cmd = _cmd(adb_args + ['shell', '-t', 'su', '-c', f'{runner} {remote}'])
                    shell_cmd = _cmd(adb_args + ['shell', '-t', 'su'])
                else:
                    run_cmd = _cmd(adb_args + ['shell', '-t', runner, remote])
                    shell_cmd = _cmd(adb_args + ['shell', '-t'])

                lines = [
                    '@echo off',
                    'chcp 65001 >nul',
                    push_cmd,
                    'if errorlevel 1 goto end',
                    chmod_cmd,
                    'if errorlevel 1 goto end',
                    run_cmd,
                    'echo.',
                    'echo 脚本执行结束，进入 ADB Shell（可继续交互）。',
                    shell_cmd,
                    ':end',
                ]

                fd, cmd_path = tempfile.mkstemp(prefix='tobatools_run_sh_', suffix='.cmd', text=True)
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8', newline='\r\n') as f:
                        f.write('\r\n'.join(lines))
                except Exception:
                    try:
                        os.close(fd)
                    except Exception:
                        pass
                    raise

                self.log.finish_step(sid_prep, True, "")
                
                sid_launch = str(uuid.uuid4())
                self.log.start_step(sid_launch, "启动终端窗口")
                subprocess.Popen(
                    ['cmd.exe', '/K', cmd_path],
                    cwd=bin_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
                self.log.finish_step(sid_launch, True, "已弹出")
            else:
                self.log.append_log("非 Windows 环境，直接 Push...")
                subprocess.Popen(adb_args + ['push', str(p), remote], cwd=bin_dir)
                self.log.finish_step(sid_prep, True, "Push initiated")
        except Exception as e:
            self.log.finish_step(sid_prep, False, str(e))
            InfoBar.error('失败', f'无法启动终端：{e}', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return

        InfoBar.success('已启动', '已弹出终端窗口，请在终端内交互运行', parent=self, position=InfoBarPosition.TOP, isClosable=True)
