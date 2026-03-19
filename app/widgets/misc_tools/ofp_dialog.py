from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, QObject, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog
from app.components.log_widget import LogWidget

from qfluentwidgets import (
    CardWidget,
    PrimaryPushButton,
    PushButton,
    TitleLabel,
    CaptionLabel,
    ComboBox,
    LineEdit,
    SmoothScrollArea,
    InfoBar,
    InfoBarPosition,
)

from app.logic.ofp_processor import OFPProcessor


class _OFPWorker(QObject):
    log = Signal(str)
    step_start = Signal(str, str)
    step_finish = Signal(str, bool, str)
    finished = Signal(bool, str)

    def __init__(self, ofp_path: str, out_dir: str, mode: str):
        super().__init__()
        self.ofp_path = str(ofp_path or '').strip()
        self.out_dir = str(out_dir or '').strip()
        self.mode = str(mode or 'auto').strip().lower()
        self._proc: Optional[OFPProcessor] = None
        self._stop = False

    def stop(self):
        self._stop = True
        try:
            if self._proc is not None:
                self._proc.stop()
        except Exception:
            pass

    def run(self):
        try:
            self._proc = OFPProcessor(
                log_callback=self.log.emit,
                step_start=self.step_start.emit,
                step_finish=self.step_finish.emit
            )
            ok = self._proc.extract(self.ofp_path, self.out_dir, mode=self.mode)
            self.finished.emit(bool(ok), '完成' if ok else '失败')
        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            self._proc = None


class _OFPDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('OFP 处理')
        self.resize(820, 620)

        self._thread: Optional[QThread] = None
        self._worker: Optional[_OFPWorker] = None

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
        header.addWidget(TitleLabel('OFP 处理', self))
        header.addWidget(CaptionLabel('解密并提取 OPPO/realme 的 .ofp 固件（自动识别/高通/MTK）', self))
        layout.addLayout(header)

        card = CardWidget(self)
        v = QVBoxLayout(card)
        try:
            v.setContentsMargins(16, 16, 16, 16)
            v.setSpacing(10)
        except Exception:
            pass

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel('OFP 文件'))
        self.edt_ofp = LineEdit(card)
        try:
            self.edt_ofp.setPlaceholderText('选择 .ofp 文件')
        except Exception:
            pass
        btn_pick = PushButton('浏览', card)
        btn_pick.clicked.connect(self._pick_ofp)
        row1.addWidget(self.edt_ofp)
        row1.addWidget(btn_pick)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel('输出目录'))
        self.edt_out = LineEdit(card)
        try:
            self.edt_out.setPlaceholderText('选择解密输出目录')
        except Exception:
            pass
        btn_out = PushButton('浏览', card)
        btn_out.clicked.connect(self._pick_out)
        row2.addWidget(self.edt_out)
        row2.addWidget(btn_out)
        v.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(8)
        row3.addWidget(QLabel('模式'))
        self.cmb_mode = ComboBox(card)
        self.cmb_mode.addItems(['自动（先高通后MTK）', '高通（QC）', '联发科（MTK）'])
        row3.addWidget(self.cmb_mode)
        row3.addStretch(1)
        self.btn_run = PrimaryPushButton('开始处理', card)
        self.btn_cancel = PushButton('取消', card)
        self.btn_cancel.setEnabled(False)
        self.btn_run.clicked.connect(self._start)
        self.btn_cancel.clicked.connect(self._cancel)
        row3.addWidget(self.btn_run)
        row3.addWidget(self.btn_cancel)
        v.addLayout(row3)

        layout.addWidget(card)

        card_log = CardWidget(self)
        v_log = QVBoxLayout(card_log)
        try:
            v_log.setContentsMargins(16, 16, 16, 16)
            v_log.setSpacing(10)
        except Exception:
            pass
        v_log.addWidget(QLabel('日志输出', self))

        self.txt_log = LogWidget(self)
        v_log.addWidget(self.txt_log)
        layout.addWidget(card_log)

    def _pick_ofp(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 OFP 文件', '', 'OFP (*.ofp);;所有文件 (*.*)')
        if path:
            self.edt_ofp.setText(path)

    def _pick_out(self):
        path = QFileDialog.getExistingDirectory(self, '选择输出目录')
        if path:
            self.edt_out.setText(path)

    def _mode_value(self) -> str:
        i = int(self.cmb_mode.currentIndex())
        if i == 1:
            return 'qc'
        if i == 2:
            return 'mtk'
        return 'auto'

    def _append(self, s: str):
        try:
            self.txt_log.append_log(s)
        except Exception:
            pass

    def _set_running(self, on: bool):
        r = bool(on)
        try:
            self.btn_run.setEnabled(not r)
        except Exception:
            pass
        try:
            self.btn_cancel.setEnabled(r)
        except Exception:
            pass

    def _start(self):
        if self._thread and self._thread.isRunning():
            return

        ofp_path = str(self.edt_ofp.text() or '').strip()
        out_dir = str(self.edt_out.text() or '').strip()
        if not ofp_path or not Path(ofp_path).exists():
            InfoBar.warning('提示', '请选择有效的 .ofp 文件', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        if not out_dir:
            InfoBar.warning('提示', '请选择输出目录', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            pass

        self.txt_log.clear_log()
        self._append('开始处理...')
        self._append('源: ' + ofp_path)
        self._append('输出: ' + out_dir)
        self._append('模式: ' + self._mode_value())
        self._append('')

        self._set_running(True)
        self._thread = QThread(self)
        self._worker = _OFPWorker(ofp_path, out_dir, self._mode_value())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append, Qt.QueuedConnection)
        self._worker.step_start.connect(self.txt_log.start_step, Qt.QueuedConnection)
        self._worker.step_finish.connect(self.txt_log.finish_step, Qt.QueuedConnection)
        self._worker.finished.connect(self._on_finished, Qt.QueuedConnection)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_thread_finished(self):
        self._worker = None
        self._thread = None

    def _on_finished(self, ok: bool, msg: str):
        self._append('')
        self._append('完成' if ok else '失败')
        if msg:
            self._append(str(msg))

        try:
            if ok:
                InfoBar.success('完成', 'OFP 处理完成', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            else:
                InfoBar.error('失败', 'OFP 处理失败，请检查日志输出', parent=self, position=InfoBarPosition.TOP, isClosable=True)
        except Exception:
            pass
        self._set_running(False)

    def _cancel(self):
        try:
            if self._worker is not None:
                self._worker.stop()
        except Exception:
            pass
        self._append('')
        self._append('用户取消操作')
        self._set_running(False)

    def closeEvent(self, event):
        try:
            if self._thread and self._thread.isRunning():
                self._cancel()
                try:
                    self._thread.quit()
                    self._thread.wait(1500)
                except Exception:
                    pass
        except Exception:
            pass
        super().closeEvent(event)
