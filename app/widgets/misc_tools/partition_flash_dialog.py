import os
import subprocess
from typing import Optional

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QLabel,
    QLineEdit,
    QFileDialog,
    QMessageBox,
    QCheckBox,
)
from app.components.log_widget import LogWidget

from qfluentwidgets import (
    CardWidget,
    PrimaryPushButton,
    PushButton,
    TitleLabel,
    CaptionLabel,
    ComboBox,
    SmoothScrollArea,
    MessageDialog,
)

from app.widgets.misc_tools.workers import ProcWorker


class _PartitionFlashDialog(QDialog):
    def __init__(self, fastboot_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("单分区刷入")
        self.fastboot_path = fastboot_path
        self._thread: Optional[QThread] = None
        self._worker: Optional[ProcWorker] = None

        layout = QVBoxLayout(self)
        try:
            layout.setContentsMargins(24, 20, 24, 20)
            layout.setSpacing(12)
        except Exception:
            pass

        header = QVBoxLayout()
        try:
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(2)
        except Exception:
            pass
        header.addWidget(TitleLabel("单分区刷入", self))
        header.addWidget(CaptionLabel("手动填写分区名并选择镜像刷入（可选槽位 / 模式）", self))
        layout.addLayout(header)

        card_params = CardWidget(self)
        v_params = QVBoxLayout(card_params)
        try:
            v_params.setContentsMargins(16, 16, 16, 16)
            v_params.setSpacing(10)
        except Exception:
            pass

        row1 = QHBoxLayout()
        self.part_edit = QLineEdit(self)
        self.part_edit.setPlaceholderText("手动输入分区名，例如：boot / vendor_boot / system")
        self.slot_combo = ComboBox(self)
        self.slot_combo.addItems(["不指定", "_a", "_b"])
        self.mode_combo = ComboBox(self)
        self.mode_combo.addItems(["fastbootd", "bootloader"])
        self.auto_switch = QCheckBox("自动切换模式")
        self.auto_switch.setChecked(True)
        row1.addWidget(QLabel("分区"))
        row1.addWidget(self.part_edit)
        row1.addWidget(QLabel("槽位"))
        row1.addWidget(self.slot_combo)
        row1.addWidget(QLabel("目标模式"))
        row1.addWidget(self.mode_combo)
        row1.addWidget(self.auto_switch)
        v_params.addLayout(row1)

        row2 = QHBoxLayout()
        self.img_edit = QLineEdit()
        self.img_edit.setPlaceholderText("选择要刷入的 .img 文件")
        btn_pick = PushButton("选择镜像")
        btn_pick.clicked.connect(self._pick_img)
        self.run_btn = PrimaryPushButton("刷入分区")
        self.run_btn.clicked.connect(self._flash_partition)
        row2.addWidget(QLabel("镜像"))
        row2.addWidget(self.img_edit)
        row2.addWidget(btn_pick)
        row2.addStretch(1)
        row2.addWidget(self.run_btn)
        v_params.addLayout(row2)

        layout.addWidget(card_params)

        card_log = CardWidget(self)
        v_log = QVBoxLayout(card_log)
        try:
            v_log.setContentsMargins(16, 16, 16, 16)
            v_log.setSpacing(10)
        except Exception:
            pass
        v_log.addWidget(QLabel("输出日志", self))

        self.out = LogWidget()
        v_log.addWidget(self.out)

        layout.addWidget(card_log)

    def _pick_img(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择镜像", "", "镜像 (*.img);;所有文件 (*.*)")
        if path:
            self.img_edit.setText(path)

    def _ensure_mode(self, target: str) -> bool:
        fb = self.fastboot_path
        import uuid
        sid = str(uuid.uuid4())
        self.out.start_step(sid, f"切换到 {target} 模式")
        try:
            if target == 'fastbootd':
                subprocess.check_call([fb, 'reboot', 'fastboot'])
            else:
                subprocess.check_call([fb, 'reboot-bootloader'])
            self.out.append_log("等待设备重连(15s)...")
            import time as _t
            _t.sleep(15)
            self.out.finish_step(sid, True, "")
            return True
        except Exception as e:
            self.out.finish_step(sid, False, str(e))
            self.out.append_log(f"切换模式失败：{e}")
            return False

    def _flash_partition(self):
        img = self.img_edit.text().strip()
        part = self.part_edit.text().strip()
        if not img or not os.path.isfile(img):
            QMessageBox.warning(self, "提示", "请选择有效的镜像文件")
            return
        if not part:
            QMessageBox.warning(self, "提示", "请输入分区名")
            return
        if any(c.isspace() for c in part):
            QMessageBox.warning(self, "提示", "分区名不能包含空格")
            return
        slot = self.slot_combo.currentText()
        final_part = part
        if slot != "不指定":
            if not (final_part.endswith('_a') or final_part.endswith('_b')):
                final_part = final_part + slot
        target_mode = self.mode_combo.currentText()

        cmd = [self.fastboot_path, 'flash', final_part, img]
        confirm_text = "\n".join([
            "即将执行分区刷入，请确认以下信息无误：",
            f"分区：{final_part}",
            f"槽位：{slot}",
            f"目标模式：{target_mode}",
            f"镜像文件：{os.path.basename(img)}",
            f"镜像路径：{img}",
            "",
            "最终命令:",
            " ".join(cmd),
        ])
        dlg = MessageDialog("最后确认", confirm_text, self)
        try:
            dlg.yesButton.setText("确认刷入")
            dlg.cancelButton.setText("取消")
        except Exception:
            pass
        if dlg.exec() != QDialog.Accepted:
            return

        if self.auto_switch.isChecked():
            if not self._ensure_mode(target_mode):
                return
        self._run_proc(cmd)

    def _run_proc(self, cmd):
        if hasattr(self, '_thread') and self._thread and self._thread.isRunning():
            QMessageBox.information(self, "提示", "已有任务在执行中")
            return
        
        import uuid
        self._current_step_id = str(uuid.uuid4())
        # Parse partition from cmd for better step name
        # cmd is [fastboot, flash, partition, img]
        part = "?"
        if len(cmd) >= 3 and cmd[1] == 'flash':
            part = cmd[2]
        
        self.out.start_step(self._current_step_id, f"刷入分区 {part}")
        # self.out.append_log("运行: " + " ".join(cmd))
        
        self._thread = QThread(self)
        self._worker = ProcWorker(cmd)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.output.connect(self.out.append_log, Qt.QueuedConnection)
        self._worker.finished.connect(self._on_finished, Qt.QueuedConnection)
        self._thread.start()

    def _on_finished(self, code: int):
        # self.out.append_log(f"完成，退出码: {code}")
        if hasattr(self, '_current_step_id') and self._current_step_id:
            success = (code == 0)
            msg = "" if success else f"Code {code}"
            self.out.finish_step(self._current_step_id, success, msg)
            self._current_step_id = None
            
        try:
            if self._thread:
                self._thread.quit(); self._thread.wait(1500)
        except Exception:
            pass
        self._thread = None
        self._worker = None
