import os

from PySide6.QtCore import QObject, Signal, QThread, Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLabel,
    QFileDialog,
    QMessageBox,
)
from app.components.log_widget import LogWidget

from qfluentwidgets import (
    CardWidget,
    TitleLabel,
    CaptionLabel,
    BodyLabel,
    LineEdit,
    PushButton,
    PrimaryPushButton,
    CheckBox,
)

from app.logic.payload_extractor import PayloadExtractor


class _PayloadWorker(QObject):
    log = Signal(str)
    step_start = Signal(str, str)
    step_finish = Signal(str, bool, str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, source, output_dir, partitions):
        super().__init__()
        self.source = source
        self.output_dir = output_dir
        self.partitions = partitions
        self._stop = False
        self._extractor = None

    def stop(self):
        self._stop = True
        try:
            if self._extractor is not None:
                self._extractor.stop()
        except Exception:
            pass

    def run(self):
        try:
            self._extractor = PayloadExtractor(
                log_callback=self.log.emit,
                step_start=self.step_start.emit,
                step_finish=self.step_finish.emit
            )
            ok = self._extractor.extract(self.source, self.output_dir, self.partitions)
            if ok:
                self.finished.emit()
            else:
                self.error.emit("提取失败")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self._extractor = None


class _PayloadExtractDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("payload.bin 处理")
        self.resize(920, 640)
        self._worker = None
        self._thread = None
        self._changing_mode = False

        layout = QVBoxLayout(self)
        try:
            layout.setContentsMargins(24, 20, 24, 20)
            layout.setSpacing(12)
        except Exception:
            pass

        header = CardWidget(self)
        header_lay = QVBoxLayout(header)
        header_lay.setContentsMargins(16, 14, 16, 14)
        header_lay.setSpacing(4)
        header_lay.addWidget(TitleLabel('Payload.bin 处理', header))
        header_lay.addWidget(CaptionLabel('支持本地 payload.bin/ZIP 提取；也支持在线 OTA ZIP URL 下载后提取', header))
        layout.addWidget(header)

        mode_card = CardWidget(self)
        mode_layout = QHBoxLayout(mode_card)
        mode_layout.setContentsMargins(16, 12, 16, 12)
        mode_layout.setSpacing(10)
        mode_layout.addWidget(BodyLabel('提取模式', mode_card))
        mode_layout.addStretch(1)
        self.mode_local = CheckBox('本地文件提取', mode_card)
        self.mode_local.setChecked(True)
        self.mode_online = CheckBox('在线提取', mode_card)
        mode_layout.addWidget(self.mode_local)
        mode_layout.addWidget(self.mode_online)
        layout.addWidget(mode_card)

        self.local_widget = CardWidget(self)
        local_layout = QVBoxLayout(self.local_widget)
        local_layout.setContentsMargins(16, 12, 16, 12)
        local_layout.setSpacing(8)
        local_layout.addWidget(BodyLabel('本地文件', self.local_widget))

        local_row = QHBoxLayout()
        local_row.setSpacing(8)
        self.local_edit = LineEdit(self.local_widget)
        self.local_edit.setPlaceholderText("选择 payload.bin 或包含 payload.bin 的 ZIP 文件")
        btn_browse = PushButton('浏览...', self.local_widget)
        btn_browse.clicked.connect(self._browse_local)
        local_row.addWidget(self.local_edit, 1)
        local_row.addWidget(btn_browse)
        local_layout.addLayout(local_row)
        layout.addWidget(self.local_widget)

        self.online_widget = CardWidget(self)
        online_layout = QVBoxLayout(self.online_widget)
        online_layout.setContentsMargins(16, 12, 16, 12)
        online_layout.setSpacing(8)
        online_layout.addWidget(BodyLabel('在线 URL', self.online_widget))

        online_row = QHBoxLayout()
        online_row.setSpacing(8)
        self.url_edit = LineEdit(self.online_widget)
        self.url_edit.setPlaceholderText("输入 OTA 更新包 URL（包含 payload.bin 的 ZIP）")
        online_row.addWidget(self.url_edit, 1)
        online_layout.addLayout(online_row)
        layout.addWidget(self.online_widget)
        self.online_widget.setVisible(False)

        partition_group = CardWidget(self)
        partition_layout = QVBoxLayout(partition_group)
        partition_layout.setContentsMargins(16, 12, 16, 12)
        partition_layout.setSpacing(8)
        partition_layout.addWidget(BodyLabel('分区过滤（可选）', partition_group))
        self.partition_edit = LineEdit(partition_group)
        self.partition_edit.setPlaceholderText("例如: boot,vendor,system 或留空提取全部")
        partition_layout.addWidget(self.partition_edit)
        layout.addWidget(partition_group)

        out_group = CardWidget(self)
        out_layout = QVBoxLayout(out_group)
        out_layout.setContentsMargins(16, 12, 16, 12)
        out_layout.setSpacing(8)
        out_layout.addWidget(BodyLabel('输出目录', out_group))

        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self.out_edit = LineEdit(out_group)
        self.out_edit.setPlaceholderText("选择输出目录")
        btn_out = PushButton('浏览...', out_group)
        btn_out.clicked.connect(self._browse_output)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(btn_out)
        out_layout.addLayout(out_row)
        layout.addWidget(out_group)

        btn_layout = QHBoxLayout()
        self.run_btn = PrimaryPushButton('开始提取', self)
        self.run_btn.clicked.connect(self._run_extract)
        self.cancel_btn = PushButton('取消', self)
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.run_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.log = LogWidget()
        layout.addWidget(self.log)

        self.mode_local.toggled.connect(self._on_mode_changed)
        self.mode_online.toggled.connect(self._on_mode_changed)
        self._apply_mode_ui()

    def _on_mode_changed(self):
        if self._changing_mode:
            return
        self._changing_mode = True
        try:
            local = bool(self.mode_local.isChecked())
            online = bool(self.mode_online.isChecked())

            # enforce mutual exclusivity, and keep at least one selected
            if local and online:
                try:
                    sender = self.sender()
                except Exception:
                    sender = None
                if sender is self.mode_online:
                    self.mode_local.setChecked(False)
                else:
                    self.mode_online.setChecked(False)
            elif (not local) and (not online):
                try:
                    sender = self.sender()
                except Exception:
                    sender = None
                if sender is self.mode_online:
                    self.mode_online.setChecked(True)
                else:
                    self.mode_local.setChecked(True)
        finally:
            self._changing_mode = False

        self._apply_mode_ui()

    def _apply_mode_ui(self):
        try:
            local = bool(self.mode_local.isChecked())
        except Exception:
            local = True
        try:
            self.local_widget.setVisible(local)
            self.online_widget.setVisible(not local)
        except Exception:
            pass

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

        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log.clear_log()
        self.log.append_log(f"开始提取...")
        self.log.append_log(f"源: {source}")
        self.log.append_log(f"输出: {out_dir}")
        if partitions:
            self.log.append_log(f"分区: {partitions}")
        else:
            self.log.append_log("分区: 全部")
        self.log.append_log("")

        self._thread = QThread()
        self._worker = _PayloadWorker(source, out_dir, partitions)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(lambda msg: self.log.append_log(msg))
        self._worker.step_start.connect(self.log.start_step, Qt.QueuedConnection)
        self._worker.step_finish.connect(self.log.finish_step, Qt.QueuedConnection)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._thread.start()

    def _cancel(self):
        if self._worker:
            self._worker.stop()
        self.log.append_log("\n用户取消操作")
        self._cleanup()

    def _on_log(self, msg):
        self.log.append_log(msg)

    def _on_finished(self):
        self.log.append_log("\n✅ 提取完成！")
        self._cleanup()

    def _on_error(self, error):
        self.log.append_log(f"\n❌ 错误: {error}")
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
