from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QFileDialog,
)
from app.components.log_widget import LogWidget

from qfluentwidgets import (
    CardWidget,
    PrimaryPushButton,
    PushButton,
    TitleLabel,
    CaptionLabel,
    BodyLabel,
    LineEdit,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    CheckBox,
    SmoothScrollArea,
)

from app.logic.module_manager import ModuleManager, ModuleInfo


class _ListModulesWorker(QObject):
    log = Signal(str)
    finished = Signal(bool, str, list)

    def run(self):
        try:
            mgr = ModuleManager(log_callback=self.log.emit)
            mods = mgr.list_modules()
            self.finished.emit(True, '完成', [asdict(m) for m in mods])
        except Exception as e:
            self.finished.emit(False, str(e), [])


class _ModuleOpWorker(QObject):
    log = Signal(str)
    step_start = Signal(str, str)
    step_finish = Signal(str, bool, str)
    finished = Signal(bool, str)

    def __init__(self, op: str, payload: dict):
        super().__init__()
        self.op = str(op or '')
        self.payload = payload or {}

    def run(self):
        try:
            mgr = ModuleManager(
                log_callback=self.log.emit,
                step_start=self.step_start.emit,
                step_finish=self.step_finish.emit
            )
            if self.op == 'set_enabled':
                mgr.set_enabled(self.payload.get('id', ''), bool(self.payload.get('enabled', True)))
                self.finished.emit(True, '完成')
                return
            if self.op == 'remove':
                mgr.remove_module(self.payload.get('id', ''))
                self.finished.emit(True, '完成')
                return
            if self.op == 'undo_remove':
                mgr.undo_remove_module(self.payload.get('id', ''))
                self.finished.emit(True, '完成')
                return
            if self.op == 'backup':
                p = mgr.backup_module(self.payload.get('id', ''), self.payload.get('dest', ''))
                self.finished.emit(True, p or '完成')
                return
            if self.op == 'install':
                mgr.install_module_zip(self.payload.get('zip', ''))
                self.finished.emit(True, '完成')
                return
            if self.op == 'batch_install':
                mgr.batch_install(list(self.payload.get('zips', []) or []))
                self.finished.emit(True, '完成')
                return
            raise RuntimeError('未知操作: ' + self.op)
        except Exception as e:
            self.finished.emit(False, str(e))


class _ModuleCard(CardWidget):
    def __init__(self, module: ModuleInfo, parent=None):
        super().__init__(parent)
        self.module = module

        is_removed = bool(getattr(module, 'removed', False))
        if is_removed:
            try:
                # light yellow background for "pending removal" modules
                self.setStyleSheet('QWidget{background-color:#fff7e6;}')
            except Exception:
                pass

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)

        name = module.name or module.id
        if is_removed:
            name = name + '  [已移除]'
        elif not module.enabled:
            name = name + '  [已禁用]'
        if is_removed:
            name = f'<s>{name}</s>'
        self.lbl_name = BodyLabel(name, self)
        try:
            self.lbl_name.setTextFormat(Qt.RichText)
        except Exception:
            pass
        top.addWidget(self.lbl_name, 1)

        self.chk_enabled = CheckBox('启用', self)
        self.chk_enabled.setChecked(bool(module.enabled))
        try:
            if getattr(module, 'removed', False):
                self.chk_enabled.setEnabled(False)
        except Exception:
            pass
        top.addWidget(self.chk_enabled)

        self.btn_backup = PushButton('备份', self)
        self.btn_remove = PushButton('撤销移除' if getattr(module, 'removed', False) else '移除', self)
        top.addWidget(self.btn_backup)
        top.addWidget(self.btn_remove)

        lay.addLayout(top)

        mid = QHBoxLayout()
        mid.setSpacing(12)
        ver = (module.version or '').strip()
        vc = (module.version_code or '').strip()
        if vc:
            ver = (ver + f' ({vc})').strip()
        meta = f'ID: {module.id}    版本: {ver or "-"}    作者: {module.author or "-"}'
        if is_removed:
            meta = f'<s>{meta}</s>'
        self.lbl_meta = CaptionLabel(meta, self)
        try:
            self.lbl_meta.setTextFormat(Qt.RichText)
        except Exception:
            pass
        mid.addWidget(self.lbl_meta, 1)
        lay.addLayout(mid)

        desc = (module.description or '').strip()
        if desc:
            d = '简介: ' + desc
            if is_removed:
                d = f'<s>{d}</s>'
            self.lbl_desc = CaptionLabel(d, self)
            try:
                self.lbl_desc.setTextFormat(Qt.RichText)
            except Exception:
                pass
            lay.addWidget(self.lbl_desc)


class _ModuleManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('模块管理器')
        self.resize(980, 680)

        self._thread: Optional[QThread] = None
        self._worker: Optional[QObject] = None

        self._modules: list[ModuleInfo] = []
        self._cards: list[_ModuleCard] = []

        outer = QVBoxLayout(self)
        try:
            outer.setContentsMargins(24, 20, 24, 20)
            outer.setSpacing(12)
        except Exception:
            pass

        header = QWidget(self)
        header_lay = QVBoxLayout(header)
        header_lay.setContentsMargins(0, 0, 0, 0)
        header_lay.setSpacing(2)
        header_lay.addWidget(TitleLabel('Magisk / KernelSU 模块管理', header))
        header_lay.addWidget(CaptionLabel('需要 Root，并允许 adb shell 获取 su 权限；部分操作需要重启后生效', header))
        outer.addWidget(header)

        left_card = CardWidget(self)
        left_lay = QVBoxLayout(left_card)
        left_lay.setContentsMargins(16, 16, 16, 16)
        left_lay.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(BodyLabel('已安装模块', left_card))
        row.addStretch(1)
        self.btn_refresh = PushButton('刷新', left_card)
        self.btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self.btn_refresh)
        left_lay.addLayout(row)

        self.scroll = SmoothScrollArea(left_card)
        self.scroll.setWidgetResizable(True)
        try:
            self.scroll.setStyleSheet('QScrollArea {border: none; background: transparent;}')
        except Exception:
            pass
        left_lay.addWidget(self.scroll, 1)

        self.scroll_container = QWidget(self.scroll)
        try:
            self.scroll_container.setStyleSheet('QWidget {background: transparent;}')
        except Exception:
            pass
        self.scroll.setWidget(self.scroll_container)
        self.cards_lay = QVBoxLayout(self.scroll_container)
        self.cards_lay.setContentsMargins(0, 0, 0, 0)
        self.cards_lay.setSpacing(10)
        self.cards_lay.addStretch(1)

        outer.addWidget(left_card, 10)

        install_card = CardWidget(self)
        install_lay = QVBoxLayout(install_card)
        install_lay.setContentsMargins(16, 16, 16, 16)
        install_lay.setSpacing(8)

        install_lay.addWidget(BodyLabel('安装模块', install_card))
        pick_row = QHBoxLayout()
        pick_row.setSpacing(8)
        self.edt_zip = LineEdit(install_card)
        self.edt_zip.setPlaceholderText('选择模块 zip')
        self.btn_pick_zip = PushButton('选择', install_card)
        self.btn_pick_zip.clicked.connect(self._pick_zip)
        self.btn_install = PrimaryPushButton('安装', install_card)
        self.btn_batch = PushButton('批量安装', install_card)
        self.btn_install.clicked.connect(self._install)
        self.btn_batch.clicked.connect(self._batch_install)

        pick_row.addWidget(self.edt_zip, 1)
        pick_row.addWidget(self.btn_pick_zip)
        pick_row.addWidget(self.btn_install)
        pick_row.addWidget(self.btn_batch)
        install_lay.addLayout(pick_row)

        try:
            self.edt_zip.setMinimumWidth(260)
        except Exception:
            pass

        try:
            install_card.setMinimumHeight(90)
        except Exception:
            pass
        outer.addWidget(install_card, 1)

        log_card = CardWidget(self)
        log_lay = QVBoxLayout(log_card)
        log_lay.setContentsMargins(16, 16, 16, 16)
        log_lay.setSpacing(8)
        log_lay.addWidget(BodyLabel('日志', log_card))
        self.log = LogWidget(log_card)
        try:
            self.log.setMinimumHeight(90)
        except Exception:
            pass
        log_lay.addWidget(self.log, 1)

        outer.addWidget(log_card, 1)

        self._set_busy(False)
        self.refresh()

    def _append(self, s: str):
        try:
            self.log.append_log(str(s))
        except Exception:
            pass

    def _set_busy(self, on: bool):
        busy = bool(on)
        try:
            self.btn_refresh.setEnabled(not busy)
            self.btn_install.setEnabled(not busy)
            self.btn_batch.setEnabled(not busy)
            self.btn_pick_zip.setEnabled(not busy)
            for c in getattr(self, '_cards', []) or []:
                c.chk_enabled.setEnabled(not busy)
                c.btn_backup.setEnabled(not busy)
                c.btn_remove.setEnabled(not busy)
        except Exception:
            pass

    def _start_worker(self, worker: QObject, *, started_msg: str = ''):
        if self._thread is not None and self._thread.isRunning():
            InfoBar.info('提示', '任务正在进行中', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return False

        if started_msg:
            self._append(started_msg)

        self._thread = QThread(self)
        self._worker = worker
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        try:
            worker.log.connect(self._append, Qt.QueuedConnection)
            if hasattr(worker, 'step_start'):
                worker.step_start.connect(self.log.start_step, Qt.QueuedConnection)
            if hasattr(worker, 'step_finish'):
                worker.step_finish.connect(self.log.finish_step, Qt.QueuedConnection)
        except Exception:
            pass

        self._set_busy(True)
        return True

    def _finish_worker(self):
        try:
            if self._thread is not None:
                self._thread.quit()
        except Exception:
            pass

    def _cleanup_thread(self):
        self._worker = None
        self._thread = None
        self._set_busy(False)

    def refresh(self):
        w = _ListModulesWorker()
        if not self._start_worker(w, started_msg='开始刷新模块列表...'):
            return

        w.finished.connect(self._on_list_finished, Qt.QueuedConnection)
        w.finished.connect(self._finish_worker)
        w.finished.connect(w.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_list_finished(self, ok: bool, msg: str, items: list):
        if not ok:
            InfoBar.error('失败', msg, parent=self, position=InfoBarPosition.TOP, isClosable=True)
            self._append(msg)
        else:
            self._append('列表刷新完成')

        self._render_cards(items)

    def _render_cards(self, items: list):
        self._modules = []
        self._clear_cards()

        for d in items or []:
            try:
                m = ModuleInfo(**d)
            except Exception:
                continue
            self._modules.append(m)

        for m in self._modules:
            self._add_card(m)

        InfoBar.success('完成', '模块列表已刷新', parent=self, position=InfoBarPosition.TOP, isClosable=True)

    def _clear_cards(self):
        try:
            for c in self._cards:
                try:
                    c.setParent(None)
                    c.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass
        self._cards = []

        try:
            while self.cards_lay.count() > 0:
                item = self.cards_lay.takeAt(0)
                w = item.widget()
                if w is not None:
                    try:
                        w.setParent(None)
                        w.deleteLater()
                    except Exception:
                        pass
            self.cards_lay.addStretch(1)
        except Exception:
            pass

    def _add_card(self, m: ModuleInfo):
        card = _ModuleCard(m, self.scroll_container)
        self._cards.append(card)

        def _on_toggle(state: int):
            enabled = (state == Qt.Checked)
            self._op_set_enabled(m, enabled, card)

        card.chk_enabled.stateChanged.connect(_on_toggle)
        card.btn_backup.clicked.connect(lambda: self._op_backup(m))
        card.btn_remove.clicked.connect(lambda: self._op_remove_or_undo(m))

        # Insert before stretch
        idx = max(0, self.cards_lay.count() - 1)
        self.cards_lay.insertWidget(idx, card)

    def _op_set_enabled(self, m: ModuleInfo, enabled: bool, card: _ModuleCard):
        w = _ModuleOpWorker('set_enabled', {'id': m.id, 'enabled': enabled})
        if not self._start_worker(w, started_msg=('启用模块...' if enabled else '禁用模块...')):
            try:
                card.chk_enabled.blockSignals(True)
                card.chk_enabled.setChecked(bool(m.enabled))
            finally:
                card.chk_enabled.blockSignals(False)
            return

        w.finished.connect(self._on_op_finished, Qt.QueuedConnection)
        w.finished.connect(self._finish_worker)
        w.finished.connect(w.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _op_undo_remove(self, m: ModuleInfo):
        w = _ModuleOpWorker('undo_remove', {'id': m.id})
        if not self._start_worker(w, started_msg='开始撤销移除...'):
            return

        w.finished.connect(self._on_op_finished, Qt.QueuedConnection)
        w.finished.connect(self._finish_worker)
        w.finished.connect(w.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _op_remove_or_undo(self, m: ModuleInfo):
        if getattr(m, 'removed', False):
            self._op_undo_remove(m)
        else:
            self._op_remove(m)

    def _op_backup(self, m: ModuleInfo):
        dest = QFileDialog.getExistingDirectory(self, '选择备份保存目录')
        if not dest:
            return

        w = _ModuleOpWorker('backup', {'id': m.id, 'dest': dest})
        if not self._start_worker(w, started_msg='开始备份...'):
            return

        w.finished.connect(self._on_backup_finished, Qt.QueuedConnection)
        w.finished.connect(self._finish_worker)
        w.finished.connect(w.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_backup_finished(self, ok: bool, msg: str):
        if ok:
            InfoBar.success('完成', '备份完成', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            if msg:
                self._append('备份文件: ' + msg)
        else:
            InfoBar.error('失败', msg, parent=self, position=InfoBarPosition.TOP, isClosable=True)

    def _op_remove(self, m: ModuleInfo):
        box = MessageBox('确认移除', f'将标记移除模块：\n\n{m.name or m.id}\n\n需要重启后生效。是否继续？', self)
        box.yesButton.setText('继续')
        box.cancelButton.setText('取消')
        if box.exec() != MessageBox.Accepted:
            return

        w = _ModuleOpWorker('remove', {'id': m.id})
        if not self._start_worker(w, started_msg='开始标记移除...'):
            return

        w.finished.connect(self._on_op_finished, Qt.QueuedConnection)
        w.finished.connect(self._finish_worker)
        w.finished.connect(w.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _pick_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择模块压缩包', '', 'ZIP (*.zip);;所有文件 (*.*)')
        if path:
            self.edt_zip.setText(path)

    def _install(self):
        z = self.edt_zip.text().strip()
        if not z:
            InfoBar.warning('提示', '请先选择模块 zip', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        if not Path(z).exists():
            InfoBar.warning('提示', '文件不存在', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return

        w = _ModuleOpWorker('install', {'zip': z})
        if not self._start_worker(w, started_msg='开始安装模块...'):
            return

        w.finished.connect(self._on_install_finished, Qt.QueuedConnection)
        w.finished.connect(self._finish_worker)
        w.finished.connect(w.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _batch_install(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择多个模块 zip', '', 'ZIP (*.zip);;所有文件 (*.*)')
        if not paths:
            return

        box = MessageBox('确认批量安装', f'将安装 {len(paths)} 个模块包。\n\n安装通常需要重启后生效。是否继续？', self)
        box.yesButton.setText('继续')
        box.cancelButton.setText('取消')
        if box.exec() != MessageBox.Accepted:
            return

        w = _ModuleOpWorker('batch_install', {'zips': paths})
        if not self._start_worker(w, started_msg='开始批量安装...'):
            return

        w.finished.connect(self._on_install_finished, Qt.QueuedConnection)
        w.finished.connect(self._finish_worker)
        w.finished.connect(w.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_install_finished(self, ok: bool, msg: str):
        if ok:
            InfoBar.success('完成', '安装流程已结束（可能需要重启生效）', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            self._append('提示：部分模块需要重启后生效')
            self.refresh()
        else:
            InfoBar.error('失败', msg, parent=self, position=InfoBarPosition.TOP, isClosable=True)

    def _on_op_finished(self, ok: bool, msg: str):
        if ok:
            InfoBar.success('完成', '操作完成（可能需要重启生效）', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            self._append('提示：启用/禁用/移除通常需要重启后生效')
            self.refresh()
        else:
            InfoBar.error('失败', msg, parent=self, position=InfoBarPosition.TOP, isClosable=True)
            self.refresh()

    def closeEvent(self, event):
        try:
            if self._thread is not None and self._thread.isRunning():
                InfoBar.info('提示', '后台任务执行中，请稍后再关闭', parent=self, position=InfoBarPosition.TOP, isClosable=True)
                event.ignore()
                return
        except Exception:
            pass
        return super().closeEvent(event)
