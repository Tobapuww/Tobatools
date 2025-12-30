import os
import re
import time
import subprocess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFileDialog,
    QTableWidgetItem, QMenu, QInputDialog, QProgressBar
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QThread, QObject, Signal, QTimer
from qfluentwidgets import (
    CardWidget,
    PrimaryPushButton,
    PushButton,
    InfoBar,
    InfoBarPosition,
    TitleLabel,
    TableWidget,
    FluentIcon,
    MessageDialog,
    SmoothScrollArea,
)

from app.services import adb_service


class _ListWorker(QObject):
    finished = Signal(list, str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path or '/storage/emulated/0'

    def run(self):
        try:
            items, err = adb_service.list_dir(self.path)
            self.finished.emit(items or [], err or '')
        except Exception as e:
            self.finished.emit([], str(e))


class _TransferWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, mode: str, src, dst):
        super().__init__()
        self.mode = mode  # 'pull' | 'push'
        self.src = src
        self.dst = dst

    def run(self):
        try:
            ok = True; msg = ''
            if self.mode == 'pull':
                ok, msg = adb_service.pull_path(self.src, self.dst)
            elif self.mode == 'push':
                # 支持多文件
                if isinstance(self.src, (list, tuple)):
                    for p in self.src:
                        ok, msg = adb_service.push_path(p, self.dst)
                        if not ok:
                            break
                else:
                    ok, msg = adb_service.push_path(self.src, self.dst)
            elif self.mode == 'copy':
                # src: remote path; dst: remote dir
                ok, msg = adb_service.copy_path(self.src, self.dst)
            elif self.mode == 'move':
                ok, msg = adb_service.move_path(self.src, self.dst)
            elif self.mode == 'rename':
                # dst: new name
                ok, msg = adb_service.rename_path(self.src, self.dst)
            else:
                ok, msg = False, '未知的传输模式'
            self.finished.emit(ok, msg or '')
        except Exception as e:
            self.finished.emit(False, str(e))


class _StreamTransferWorker(QObject):
    progress = Signal(int)  # percent 0-100
    finished = Signal(bool, str)

    def __init__(self, mode: str, src: str, dst: str, total_bytes: int | None = None):
        super().__init__()
        self.mode = mode  # 'pull'|'push'
        self.src = src
        self.dst = dst
        self.total = total_bytes or 0
        self._proc = None
        self._stopped = False

    def run(self):
        try:
            adb = str(adb_service.ADB_BIN) if getattr(adb_service, 'ADB_BIN', None) and adb_service.ADB_BIN.exists() else 'adb'
            cmd = [adb, 'pull' if self.mode == 'pull' else 'push', '-p', self.src, self.dst]
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # -p 进度通常输出到 stderr
                bufsize=1,
                universal_newlines=True,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            total_bytes = self.total if (self.total and self.total > 0) else 0
            percent_pat = re.compile(r"(\d+)%")
            bracket_pat = re.compile(r"\[(\d+)%\]")
            bytes_pat = re.compile(r"\((\d+)\s+bytes")
            last_emit = 0.0
            last_busy = 0.0
            buf = ''
            saw_pct = False
            done_bytes = 0
            
            while True:
                if self._stopped:
                    if self._proc.poll() is None:
                        self._proc.kill()
                    break
                    
                ch = self._proc.stderr.read(1)
                
                if not ch:
                    if self._proc.poll() is not None:
                        break
                    time.sleep(0.05)
                    # 周期性发出忙碌信号，驱动不确定进度条
                    nowb = time.time()
                    if not saw_pct and nowb - last_busy >= 0.2:
                        self.progress.emit(-1)
                        last_busy = nowb
                    continue
                    
                if ch in ['\r', '\n']:
                    line = buf
                    buf = ''
                    if not line:
                        continue
                    m_pct = percent_pat.search(line) or bracket_pat.search(line)
                    if m_pct:
                        pct = int(m_pct.group(1))
                        saw_pct = True
                        now = time.time()
                        if now - last_emit >= 0.05:
                            self.progress.emit(pct)
                            last_emit = now
                        continue
                    m_bytes = bytes_pat.search(line)
                    if m_bytes:
                        done_bytes = int(m_bytes.group(1))
                        if total_bytes > 0:
                            pct = min(100, int(done_bytes * 100 / total_bytes))
                            saw_pct = True
                            now = time.time()
                            if now - last_emit >= 0.05:
                                self.progress.emit(pct)
                                last_emit = now
                        else:
                            self.progress.emit(-1)
                        continue
                else:
                    buf += ch
                    
            if self._stopped:
                 self.finished.emit(False, "已取消")
                 return

            code = self._proc.wait()
            if code == 0:
                self.progress.emit(100)
                self.finished.emit(True, '')
            else:
                self.finished.emit(False, '传输失败')
                
        except Exception as e:
            try:
                if self._proc and self._proc.poll() is None:
                    self._proc.kill()
            except Exception:
                pass
            self.finished.emit(False, str(e))

    def stop(self):
        self._stopped = True
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.kill()
        except Exception:
            pass


    


class FileManagerTab(QWidget):
    def __init__(self):
        super().__init__()
        self._thread = None
        self._worker = None
        self._tx_thread = None
        self._tx_worker = None
        self._clipboard = {"mode": None, "paths": []}  # mode: 'copy'|'cut'
        self._cwd = '/storage/emulated/0'
        self._build_ui()
        self._did_first_show = False

    def _build_ui(self):
        outer = QVBoxLayout(self)
        try:
            outer.setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass
        self.scroll = SmoothScrollArea(self)
        self.scroll.setWidgetResizable(True)
        try:
            self.scroll.setStyleSheet("QScrollArea {border: none; background: transparent;}")
        except Exception:
            pass
        outer.addWidget(self.scroll)

        container = QWidget()
        try:
            container.setStyleSheet("QWidget {background: transparent;}")
        except Exception:
            pass
        self.scroll.setWidget(container)

        root = QVBoxLayout(container)
        try:
            root.setContentsMargins(24, 24, 24, 24)
        except Exception:
            pass

        # 顶部 Banner，与其它标签页风格一致
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
            _ico = FluentIcon.FOLDER.icon()
            icon_lbl.setPixmap(_ico.pixmap(48, 48))
        except Exception:
            pass
        title_col = QVBoxLayout(); title_col.setContentsMargins(0,0,0,0); title_col.setSpacing(4)
        t = QLabel("文件管理器", banner_w)
        try:
            t.setStyleSheet("font-size: 22px; font-weight: 600;")
        except Exception:
            pass
        s = QLabel("包含基础功能的手机端文件管理工具（导入导出进度不准确，需要手动确认文件状态）", banner_w)
        try:
            s.setStyleSheet("font-size: 14px;")
        except Exception:
            pass
        title_col.addWidget(t); title_col.addWidget(s)
        banner.addWidget(icon_lbl); banner.addLayout(title_col); banner.addStretch(1)
        root.addWidget(banner_w)

        card = CardWidget(self)
        lay = QVBoxLayout(card); lay.setContentsMargins(16,16,16,16); lay.setSpacing(10)

        # path row
        row = QHBoxLayout(); row.setSpacing(8)
        self.path_edit = QLineEdit(self._cwd)
        self.btn_up = PushButton('上级')
        self.btn_go = PrimaryPushButton('打开')
        self.btn_refresh = PushButton('刷新')
        row.addWidget(QLabel('路径:'))
        row.addWidget(self.path_edit)
        row.addWidget(self.btn_up)
        row.addWidget(self.btn_go)
        row.addWidget(self.btn_refresh)
        lay.addLayout(row)

        # 列表表格（与其它页一致的 TableWidget）
        self.table = TableWidget(self)
        try:
            self.table.setColumnCount(3)
            self.table.setHorizontalHeaderLabels(["名称", "大小", "类型"])
            header = self.table.horizontalHeader()
            header.setStretchLastSection(False)
            from PySide6.QtWidgets import QHeaderView
            header.setSectionResizeMode(QHeaderView.Stretch)
            self.table.setAlternatingRowColors(True)
            self.table.setSelectionBehavior(self.table.SelectRows)
            self.table.setEditTriggers(self.table.NoEditTriggers)
            # 右键菜单绑定到 viewport，确保在单元格/空白处都能触发
            self.table.viewport().setContextMenuPolicy(Qt.CustomContextMenu)
            # 兼容部分环境：同时在表格本体也启用自定义菜单策略
            self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        except Exception:
            pass
        lay.addWidget(self.table)

        # actions
        act = QHBoxLayout(); act.setSpacing(8)
        self.btn_pull = PrimaryPushButton('拉取到本地')
        act.addStretch(1)
        act.addWidget(self.btn_pull)
        lay.addLayout(act)

        root.addWidget(card)

        # 底部内嵌进度条（默认隐藏）
        prog_row = QHBoxLayout(); prog_row.setContentsMargins(0, 0, 0, 0); prog_row.setSpacing(8)
        self.prog_label = QLabel('0%', self)
        self.prog_bar = QProgressBar(self)
        self.prog_bar.setRange(0, 100)
        self.prog_wrap = QWidget(self)
        _wrap_l = QHBoxLayout(self.prog_wrap); _wrap_l.setContentsMargins(0,0,0,0); _wrap_l.setSpacing(8)
        _wrap_l.addWidget(self.prog_label)
        _wrap_l.addWidget(self.prog_bar, 1)
        self.status_label = QLabel('', self)
        _wrap_l.addWidget(self.status_label)
        self.prog_wrap.setVisible(False)
        root.addWidget(self.prog_wrap)

        # signals
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_go.clicked.connect(self._open_entered)
        self.btn_up.clicked.connect(self._go_up)
        self.btn_pull.clicked.connect(self._pull_selected)
        self.table.cellDoubleClicked.connect(self._enter_item)
        try:
            self.table.viewport().customContextMenuRequested.connect(self._on_ctx_menu)
            self.table.customContextMenuRequested.connect(self._on_ctx_menu_widget)
        except Exception:
            pass
        

    def _refresh(self):
        # start worker to list
        path = self.path_edit.text().strip() or '/storage/emulated/0'
        # 避免并发列目录线程：若已有线程在跑，先尝试停止
        try:
            if self._thread and self._thread.isRunning():
                return
        except Exception:
            pass
        self._cwd = path
        self._thread = QThread(self)
        self._worker = _ListWorker(path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        # 强制使用排队连接，确保在主线程更新 UI
        self._worker.finished.connect(self._on_list_finished, Qt.QueuedConnection)
        
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._cleanup_list_thread)
        self._thread.start()

    def _cleanup_list_thread(self):
        self._thread = None
        self._worker = None

    def _on_list_finished(self, items: list, err: str):
        if err:
            QTimer.singleShot(0, lambda: self._set_status(f'列目录失败：{err}'))
            return
        try:
            self.table.setRowCount(0)
        except Exception:
            pass
        for it in items:
            name = it.get('name', '')
            size = it.get('size', '')
            typ = it.get('type', '')
            # 显示规则：文件夹不显示大小，类型中文；文件按 KB/MB/GB 显示
            if (typ or '').lower() == 'dir':
                disp_size = '-'
                disp_type = '文件夹'
            else:
                disp_type = '文件'
                disp_size = self._fmt_size(size)
            row = self.table.rowCount(); self.table.insertRow(row)
            name_item = QTableWidgetItem(name)
            # 设置图标
            try:
                if disp_type == '文件夹':
                    ico = FluentIcon.FOLDER.icon()
                else:
                    # 文档图标（若不可用回退）
                    try:
                        ico = FluentIcon.DOCUMENT.icon()
                    except Exception:
                        ico = FluentIcon.FILE.icon() if hasattr(FluentIcon, 'FILE') else FluentIcon.DOCUMENT.icon()
                name_item.setIcon(ico)
            except Exception:
                pass
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(disp_size))
            self.table.setItem(row, 2, QTableWidgetItem(disp_type))
        QTimer.singleShot(0, lambda: self._set_status(f'共 {len(items)} 项'))

    def _open_entered(self):
        self._refresh()

    def _go_up(self):
        p = self.path_edit.text().strip() or '/storage/emulated/0'
        if p == '/':
            return
        parent = os.path.dirname(p.rstrip('/'))
        if not parent:
            parent = '/'
        self.path_edit.setText(parent)
        self._refresh()

    def _enter_item(self, row: int, col: int):
        name = self.table.item(row, 0).text() if self.table.item(row,0) else ''
        typ = self.table.item(row, 2).text() if self.table.item(row,2) else ''
        if not name:
            return
        if typ == '文件夹':
            newp = (self._cwd.rstrip('/') + '/' + name) if self._cwd != '/' else ('/' + name)
            self.path_edit.setText(newp)
            self._refresh()

    def _pull_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QTimer.singleShot(0, lambda: self._set_status('请选择文件'))
            return
        name = self.table.item(row, 0).text() if self.table.item(row,0) else ''
        typ = self.table.item(row, 2).text() if self.table.item(row,2) else ''
        if typ == '文件夹':
            QTimer.singleShot(0, lambda: self._set_status('暂不支持拉取文件夹'))
            return
        remote = (self._cwd.rstrip('/') + '/' + name) if self._cwd != '/' else ('/' + name)
        local, _ = QFileDialog.getSaveFileName(self, '保存到本地', name)
        if not local:
            return
        self._start_stream_transfer('pull', remote, local, self._probe_total(remote))

    def cleanup(self):
        try:
            if self._thread and self._thread.isRunning():
                self._thread.quit(); self._thread.wait(800)
        except Exception:
            pass
        try:
            if self._tx_thread and self._tx_thread.isRunning():
                self._tx_thread.quit(); self._tx_thread.wait(1000)
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            self.cleanup()
        except Exception:
            pass
        return super().closeEvent(event)

    def contextMenuEvent(self, event):
        try:
            # 仅当右键发生在表格区域时弹出
            gp = event.globalPos()
            vp = self.table.viewport()
            vp_rect = vp.rect()
            vp_pos = vp.mapFromGlobal(gp)
            if vp_rect.contains(vp_pos):
                self._on_ctx_menu(vp_pos)
                return
        except Exception:
            pass
        return super().contextMenuEvent(event)

    def showEvent(self, event):
        try:
            if not getattr(self, '_did_first_show', False):
                self._did_first_show = True
                self._refresh()
        except Exception:
            pass
        return super().showEvent(event)

    def _fmt_size(self, val) -> str:
        try:
            s = int(val) if isinstance(val, (int,)) or str(val).isdigit() else -1
        except Exception:
            s = -1
        if s < 0:
            return '-'
        units = ['KB', 'MB', 'GB', 'TB']
        # 以 KB 起步
        size = s / 1024.0
        unit_idx = 0
        while size >= 1024.0 and unit_idx < len(units) - 1:
            size /= 1024.0
            unit_idx += 1
        # 显示到一位小数（>=10 则取整）
        if size >= 10:
            return f"{int(size)} {units[unit_idx]}"
        return f"{size:.1f} {units[unit_idx]}"

    def _on_ctx_menu(self, pos):
        row = self.table.indexAt(pos).row()
        if row < 0:
            return
        name = self.table.item(row, 0).text() if self.table.item(row,0) else ''
        typ = self.table.item(row, 2).text() if self.table.item(row,2) else ''
        menu = QMenu(self)
        act_open = QAction('打开', self)
        act_export = QAction('导出', self)
        act_copy = QAction('复制', self)
        act_cut = QAction('剪切', self)
        act_paste = QAction('粘贴', self)
        act_rename = QAction('重命名', self)
        act_delete = QAction('删除', self)
        act_props = QAction('属性', self)
        act_import_files = QAction('导入文件', self)
        act_import_dir = QAction('导入文件夹', self)
        act_refresh = QAction('刷新', self)
        act_open.setEnabled(typ == '文件夹')
        act_open.triggered.connect(lambda: self._enter_item(row, 0))
        act_export.triggered.connect(lambda: self._export_item(name, typ))
        act_copy.triggered.connect(lambda: self._clipboard_set('copy', name))
        act_cut.triggered.connect(lambda: self._clipboard_set('cut', name))
        act_paste.triggered.connect(self._paste_items)
        act_rename.triggered.connect(lambda: self._rename_item(name))
        act_delete.triggered.connect(lambda: self._delete_item(name))
        act_props.triggered.connect(lambda: self._show_props(name))
        act_import_files.triggered.connect(self._import_files)
        act_import_dir.triggered.connect(self._import_folder)
        act_refresh.triggered.connect(self._refresh)
        menu.addAction(act_open)
        menu.addAction(act_export)
        menu.addSeparator()
        menu.addAction(act_copy)
        menu.addAction(act_cut)
        menu.addAction(act_paste)
        menu.addSeparator()
        menu.addAction(act_rename)
        menu.addAction(act_delete)
        menu.addAction(act_props)
        menu.addSeparator()
        menu.addAction(act_import_files)
        menu.addAction(act_import_dir)
        menu.addSeparator()
        menu.addAction(act_refresh)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _export_item(self, name: str, typ: str):
        remote = (self._cwd.rstrip('/') + '/' + name) if self._cwd != '/' else ('/' + name)
        if typ == '文件夹':
            local_dir = QFileDialog.getExistingDirectory(self, '选择导出位置')
            if not local_dir:
                return
            dest = os.path.join(local_dir, os.path.basename(name))
            self._start_stream_transfer('pull', remote, dest, self._probe_total(remote))
        else:
            local, _ = QFileDialog.getSaveFileName(self, '导出文件到本地', name)
            if not local:
                return
            self._start_stream_transfer('pull', remote, local, self._probe_total(remote))

    def _import_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, '选择要导入的文件')
        if not files:
            return
        # 估算总大小（本地）
        total = 0
        try:
            for p in files:
                try:
                    total += os.path.getsize(p)
                except Exception:
                    pass
        except Exception:
            total = 0
        # 逐个 push，进度对话框逐个显示
        # 简化：若多文件，无法单对话框展示合并进度，这里逐个弹出
        for p in files:
            self._start_stream_transfer('push', p, self._cwd, os.path.getsize(p) if os.path.exists(p) else 0)

    def _import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择要导入的文件夹')
        if not folder:
            return
        # 文件夹大小估算代价较高，这里置 0，由 adb 输出提供进度（若有）
        self._start_stream_transfer('push', folder, self._cwd, 0)

    def _start_transfer(self, mode: str, src, dst):
        # 防并发：如有正在执行的传输，先结束
        try:
            if self._tx_thread and self._tx_thread.isRunning():
                InfoBar.info('提示', '正在进行传输，请稍候...', parent=self, position=InfoBarPosition.TOP, isClosable=True)
                return
        except Exception:
            pass
        self._tx_thread = QThread(self)
        self._tx_worker = _TransferWorker(mode, src, dst)
        self._tx_worker.moveToThread(self._tx_thread)
        self._tx_thread.started.connect(self._tx_worker.run)
        self._tx_worker.finished.connect(self._on_transfer_finished, Qt.QueuedConnection)
        self._tx_worker.finished.connect(self._tx_thread.quit)
        self._tx_worker.finished.connect(self._tx_worker.deleteLater)
        self._tx_thread.finished.connect(self._tx_thread.deleteLater)
        self._tx_thread.finished.connect(self._cleanup_tx_thread)
        self._tx_thread.start()

    def _cleanup_tx_thread(self):
        self._tx_thread = None
        self._tx_worker = None

    def _on_transfer_finished(self, ok: bool, msg: str):
        if ok:
            QTimer.singleShot(0, lambda: self._set_status('操作已完成'))
            # 完成后刷新列表（例如导入后显示新文件）
            self._refresh()
            # 剪切模式粘贴后清空剪切板
            if self._clipboard.get('mode') == 'cut':
                self._clipboard = {"mode": None, "paths": []}
        else:
            QTimer.singleShot(0, lambda: self._set_status(msg or '操作失败'))

    # ---------- Clipboard & Operations ----------
    def _clipboard_set(self, mode: str, name: str):
        remote = (self._cwd.rstrip('/') + '/' + name) if self._cwd != '/' else ('/' + name)
        self._clipboard = {"mode": mode, "paths": [remote]}
        QTimer.singleShot(0, lambda: self._set_status('已复制' if mode=='copy' else '已剪切'))

    def _paste_items(self):
        mode = self._clipboard.get('mode')
        paths = self._clipboard.get('paths') or []
        if not mode or not paths:
            self._set_status('剪贴板为空')
            return
        src = paths[0]
        dst_dir = self._cwd
        if mode == 'copy':
            self._start_transfer('copy', src, dst_dir)
        elif mode == 'cut':
            self._start_transfer('move', src, dst_dir)

    def _rename_item(self, name: str):
        new_name, ok = QInputDialog.getText(self, '重命名', '新名称：', text=name)
        if not ok or not new_name or new_name == name:
            return
        remote = (self._cwd.rstrip('/') + '/' + name) if self._cwd != '/' else ('/' + name)
        self._start_transfer('rename', remote, new_name)

    def _show_props(self, name: str):
        remote = (self._cwd.rstrip('/') + '/' + name) if self._cwd != '/' else ('/' + name)
        info = {}
        try:
            info = adb_service.stat_path(remote) or {}
        except Exception as e:
            InfoBar.error('错误', f'获取属性失败：{e}', parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        def _fallback_type() -> str:
            try:
                return '目录' if adb_service.is_dir(remote) else '文件'
            except Exception:
                return '-'
        ftype = info.get('type') or _fallback_type()
        raw_size = info.get('size', '-')
        size_disp = self._fmt_size(raw_size)
        mtime = info.get('mtime', info.get('raw_mtime', '-'))
        perm = info.get('perm', '-')
        user = info.get('user', '-')
        group = info.get('group', '-')
        detail_lines = [
            f'名称：{name}',
            f'路径：{remote}',
            f'类型：{ftype}',
            f'大小：{size_disp}',
            f'权限：{perm}',
            f'所有者：{user}:{group}',
            f'修改时间：{mtime}',
        ]
        raw_ls = info.get('raw_ls'); raw_du = info.get('raw_du')
        if raw_ls:
            detail_lines.append(f'ls -ld：{raw_ls.strip()}')
        if raw_du:
            detail_lines.append(f'du -s：{raw_du.strip()}')
        msg = '\n'.join(detail_lines)
        dlg = MessageDialog('属性', msg, self)
        dlg.yesButton.setText('关闭')
        dlg.cancelButton.setVisible(False)
        dlg.exec()

    def _delete_item(self, name: str):
        remote = (self._cwd.rstrip('/') + '/' + name) if self._cwd != '/' else ('/' + name)
        # 无模态弹窗，直接执行删除（如需确认我可再加）
        ok, msg = adb_service.delete_path(remote)
        if ok:
            self._set_status('已删除')
            self._refresh()
        else:
            self._set_status(msg or '删除失败')

    def _probe_total(self, remote: str) -> int:
        try:
            info = adb_service.stat_path(remote)
            sz = int(info.get('size', '0')) if info.get('size') else 0
            if sz > 0:
                return sz
        except Exception:
            pass
        # 目录时尝试 du -s（近似，以KB为单位）
        try:
            out = adb_service._adb_shell(["du", "-s", remote], timeout=20)
            # format: "<KB>\t<path>"
            kb = int((out.strip().split() or ['0'])[0])
            return kb * 1024
        except Exception:
            return 0

    def _start_stream_transfer(self, mode: str, src: str, dst: str, total: int | None = None):
        # 防并发
        try:
            if self._tx_thread and self._tx_thread.isRunning():
                InfoBar.info('提示', '正在进行传输，请稍候...', parent=self, position=InfoBarPosition.TOP, isClosable=True)
                return
        except Exception:
            pass
        self._tx_thread = QThread(self)
        worker = _StreamTransferWorker(mode, src, dst, total or 0)
        self._tx_worker = worker
        worker.moveToThread(self._tx_thread)
        self._tx_thread.started.connect(worker.run)
        # inline progress
        self._progress_reset()
        
        # Connect signals to slots using QueuedConnection
        worker.progress.connect(self._on_stream_progress, Qt.QueuedConnection)
        worker.finished.connect(self._on_stream_finished, Qt.QueuedConnection)
        
        worker.finished.connect(self._tx_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self._tx_thread.finished.connect(self._tx_thread.deleteLater)
        self._tx_thread.finished.connect(self._cleanup_tx_thread)
        self._tx_thread.start()

    def _on_stream_progress(self, pct: int):
        self._progress_update(pct)

    def _on_stream_finished(self, ok: bool, msg: str):
        self._progress_complete(ok, msg)
        self._on_transfer_finished(ok, msg)

    def _progress_reset(self):
        def _do():
            try:
                self.prog_bar.setValue(0)
                self.prog_label.setText('0%')
                # 初始未知总量：设置为不确定模式，待收到百分比再恢复
                self.prog_bar.setMaximum(0)
                self.prog_wrap.setVisible(True)
            except Exception:
                pass
        QTimer.singleShot(0, _do)

    def _progress_update(self, percent: int):
        try:
            if percent is None or int(percent) < 0:
                # 不确定模式
                self.prog_bar.setMaximum(0)
                self.prog_label.setText('进行中...')
                self.prog_wrap.setVisible(True)
                return
            # 切回确定模式
            if self.prog_bar.maximum() != 100:
                self.prog_bar.setMaximum(100)
            p = max(0, min(100, int(percent)))
            self.prog_bar.setValue(p)
            self.prog_label.setText(f'{p}%')
        except Exception:
            pass

    def _progress_complete(self, ok: bool, msg: str):
        def _do():
            try:
                # 确保切回确定模式再设置数值
                if self.prog_bar.maximum() != 100:
                    self.prog_bar.setMaximum(100)
                self.prog_bar.setValue(100 if ok else 0)
                if ok:
                    self.prog_label.setText('100%')
                if not ok and msg:
                    self.status_label.setText(msg)
                # 停留片刻再隐藏，便于用户看到结束状态
                QTimer.singleShot(1200, lambda: self.prog_wrap.setVisible(False))
            except Exception:
                pass
        QTimer.singleShot(0, _do)

    def _set_status(self, text: str):
        try:
            self.status_label.setText(text or '')
            if text:
                self.prog_wrap.setVisible(True)
                QTimer.singleShot(3000, lambda: self.prog_wrap.setVisible(False))
        except Exception:
            pass
