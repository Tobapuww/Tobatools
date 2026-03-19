import os
import subprocess

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from qfluentwidgets import MessageDialog
from app.components.log_widget import LogWidget


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

        self.out = LogWidget()
        layout.addWidget(self.out)

    def _run(self):
        cmd = [self.fastboot_path, 'flashing', 'unlock']
        import uuid
        sid = str(uuid.uuid4())
        self.out.start_step(sid, "发送解锁命令")
        try:
            kw = {}
            if os.name == 'nt':
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                kw.update({'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW})
            subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
            self.out.finish_step(sid, True, "已发送")
            self.out.append_log("请在手机上操作：手机选择 UNLOCK THE BOOTLOADER(音量键选择，电源键确定)")
            MessageDialog("提示", "请在手机上操作：手机选择 UNLOCK THE BOOTLOADER(音量键选择，电源键确定)", self).exec()
        except FileNotFoundError:
            self.out.finish_step(sid, False, "未找到 fastboot")
            MessageDialog("提示", "未找到 fastboot，可将 fastboot.exe 放至 bin 目录或配置系统 PATH。", self).exec()
        except Exception as e:
            self.out.finish_step(sid, False, str(e))
            self.out.append_log(f"启动失败：{e}")
