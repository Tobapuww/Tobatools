import os
import json
import zipfile
import requests
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, QSizePolicy, QScrollArea, QTableWidgetItem, QDialog, QHeaderView
)
from PySide6.QtCore import Qt, QObject, Signal, QThread, QTimer
from PySide6.QtGui import QFont
from qfluentwidgets import CardWidget, PrimaryPushButton, PushButton, ProgressBar, TitleLabel, InfoBar, InfoBarPosition, MessageDialog, MessageBox, FluentIcon, TableWidget
from PySide6.QtCore import QSettings


class DownloadWorker(QObject):
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, url: str, dest: str):
        super().__init__()
        self.url = url
        self.dest = dest
        self.threads = 4
        self.is_canceled = False
        self.session = None
        self._verify_zip_threshold = 600 * 1024 * 1024  # 600MB

    def run(self):
        try:
            # 创建独立的session，支持keep-alive
            self.session = requests.Session()

            # 对特定源（如 kcnb.qutama.de 或 .7z 文件）强制采用简单直连 GET，避免分段/HEAD 导致的失败
            url_l = (self.url or "").lower()
            force_simple = ("kcnb.qutama.de" in url_l) or url_l.endswith(".7z")

            total_size = 0
            accept_ranges = False
            if not force_simple:
                head = self.session.head(self.url, allow_redirects=True, timeout=(5, 5))
                total_size = int(head.headers.get('content-length', 0))
                accept_ranges = head.headers.get('accept-ranges', '').lower() == 'bytes'

            os.makedirs(os.path.dirname(self.dest) or '.', exist_ok=True)

            if (not force_simple) and total_size > 0 and accept_ranges and self.threads > 1:
                if self._download_with_threads(total_size):
                    need_retry = False
                    if self._should_verify_zip():
                        need_retry = not self._verify_zip_integrity()
                        if need_retry:
                            try:
                                os.remove(self.dest)
                            except Exception:
                                pass
                    if not need_retry:
                        self.progress.emit(100)
                        self.finished.emit(self.dest)
                        return

            # 简单直连（适用于不支持分段/HEAD的源，或强制单通道下载）
            headers = {"User-Agent": "Mozilla/5.0"}
            response = self.session.get(self.url, headers=headers, stream=True, timeout=(10, 30))
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0

            with open(self.dest, 'wb') as file:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if self.is_canceled:
                        if os.path.exists(self.dest):
                            os.remove(self.dest)
                        self.finished.emit("CANCELED")
                        return
                    if chunk:
                        file.write(chunk)
                        downloaded_size += len(chunk)
                        if total_size > 0:
                            percent = min(99, int(downloaded_size * 100 / total_size))
                            self.progress.emit(percent)

            self.progress.emit(100)
            self.finished.emit(self.dest)
            
        except Exception as e:
            # 清理异常时的文件
            if os.path.exists(self.dest):
                try:
                    os.remove(self.dest)
                except:
                    pass
            self.error.emit(str(e))
        finally:
            # 确保session被关闭
            if self.session:
                self.session.close()

    def cancel(self):
        self.is_canceled = True
        if self.session:
            self.session.close()

    # ---------- Helpers ----------
    def _download_with_threads(self, total_size: int) -> bool:
        import threading
        try:
            with open(self.dest, 'wb') as f:
                f.truncate(total_size)
        except Exception:
            pass

        seg_size = total_size // self.threads
        ranges = []
        start = 0
        for i in range(self.threads):
            end = total_size - 1 if i == self.threads - 1 else start + seg_size - 1
            ranges.append((start, end))
            start = end + 1

        downloaded = 0
        lock = threading.Lock()

        def dl_part(byte_range):
            nonlocal downloaded
            if self.is_canceled:
                return
            headers = {'Range': f'bytes={byte_range[0]}-{byte_range[1]}'}
            try:
                with self.session.get(self.url, headers=headers, stream=True, timeout=(5, 10)) as r:
                    r.raise_for_status()
                    pos = byte_range[0]
                    with open(self.dest, 'rb+') as fpart:
                        fpart.seek(pos)
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            if self.is_canceled:
                                try:
                                    r.close()
                                except Exception:
                                    pass
                                return
                            if not chunk:
                                continue
                            fpart.write(chunk)
                            with lock:
                                downloaded += len(chunk)
                                if total_size > 0:
                                    self.progress.emit(int(downloaded * 100 / total_size))
            except Exception:
                self.is_canceled = True

        threads = []
        for br in ranges:
            t = threading.Thread(target=dl_part, args=(br,), daemon=True)
            threads.append(t)
            t.start()

        while True:
            alive = False
            for t in threads:
                t.join(timeout=0.2)
                if t.is_alive():
                    alive = True
            if not alive:
                break
            if self.is_canceled:
                spins = 0
                while any(t.is_alive() for t in threads) and spins < 15:
                    for t in threads:
                        t.join(timeout=0.2)
                    spins += 1
                break

        if self.is_canceled:
            if os.path.exists(self.dest):
                try:
                    os.remove(self.dest)
                except Exception:
                    pass
            self.finished.emit("CANCELED")
            return False
        return True

    def _should_verify_zip(self) -> bool:
        ext = os.path.splitext(self.dest)[1].lower()
        if ext != ".zip":
            return False
        try:
            size = os.path.getsize(self.dest)
        except Exception:
            return False
        return size <= self._verify_zip_threshold

    def _verify_zip_integrity(self) -> bool:
        try:
            with zipfile.ZipFile(self.dest, 'r') as zf:
                return zf.testzip() is None
        except Exception:
            return False


class _DownloadProgressDialog(QDialog):
    canceled = Signal()

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        try:
            self.setWindowTitle(f"下载：{name}")
        except Exception:
            pass
        self.setModal(False)
        try:
            self.setFixedWidth(480)
        except Exception:
            pass

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        title = TitleLabel("正在下载...")
        desc = QLabel(name)
        try:
            desc.setWordWrap(True)
        except Exception:
            pass
        self.bar = ProgressBar()
        try:
            self.bar.setRange(0, 100)
            self.bar.setValue(0)
        except Exception:
            pass
        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(8)
        row.addStretch(1)
        self.cancel_btn = PushButton("取消")
        row.addWidget(self.cancel_btn)

        lay.addWidget(title)
        lay.addWidget(desc)
        lay.addWidget(self.bar)
        lay.addLayout(row)

        self.cancel_btn.clicked.connect(self.canceled.emit)

    def set_progress(self, v: int):
        try:
            self.bar.setValue(int(v))
        except Exception:
            pass

class FirmwareTab(QWidget):
    def __init__(self):
        super().__init__()
        self.current_download = None  # 只允许一个下载
        self._loader_thread = None
        self._loader_worker = None
        self.all_items = []
        self.init_ui()
        self._ensure_default_source()
        self._start_load()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        try:
            main_layout.setContentsMargins(24, 24, 24, 24)
        except Exception:
            pass

        # 顶部渐变 Banner（~110px）
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
        # Banner 背景交由 Fluent 主题控制
        banner = QHBoxLayout(banner_w)
        banner.setContentsMargins(24, 18, 24, 18)
        banner.setSpacing(16)
        icon_lbl = QLabel("", banner_w)
        try:
            icon_lbl.setStyleSheet("background: transparent;")
            icon_lbl.setFixedSize(48, 48)
            icon_lbl.setAlignment(Qt.AlignCenter)
            try:
                _ico = FluentIcon.DOWNLOAD.icon()
                icon_lbl.setPixmap(_ico.pixmap(48, 48))
            except Exception:
                pass
        except Exception:
            pass
        title_col = QVBoxLayout(); title_col.setContentsMargins(0,0,0,0); title_col.setSpacing(4)
        t = QLabel("固件下载中心", banner_w)
        try:
            t.setStyleSheet("font-size: 22px; font-weight: 600;")
        except Exception:
            pass
        s = QLabel("选择需要的固件版本并下载", banner_w)
        try:
            s.setStyleSheet("font-size: 14px;")
        except Exception:
            pass
        title_col.addWidget(t); title_col.addWidget(s)
        banner.addWidget(icon_lbl); banner.addLayout(title_col); banner.addStretch(1)
        main_layout.addWidget(banner_w)

        # 表格列表（名称 / 适用机型 / 操作）
        self.table = TableWidget(self)
        try:
            self.table.setColumnCount(3)
            self.table.setHorizontalHeaderLabels(["名称", "适用机型", "操作"])
            header = self.table.horizontalHeader()
            header.setStretchLastSection(False)
            header.setSectionResizeMode(QHeaderView.Stretch)
            self.table.setAlternatingRowColors(True)
        except Exception:
            pass
        main_layout.addWidget(self.table)
        try:
            QTimer.singleShot(0, self._apply_table_layout)
        except Exception:
            pass

    def _ensure_default_source(self):
        settings = QSettings()
        url = settings.value("firmware/url", "") or ""
        new_url = "https://gitee.com/AQ16/Resilience/raw/Mellifluous/.github/workflows/firmware_list.json"
        # 强制默认走云端：如果未设置或不是 http/https，则写入云端地址
        try:
            u = (url or "").strip()
            if (not u) or (not (u.lower().startswith("http://") or u.lower().startswith("https://"))):
                settings.setValue("firmware/url", new_url)
        except Exception:
            pass

    def _start_load(self):
        # 启动异步加载
        try:
            settings = QSettings()
            src = settings.value("firmware/url", "") or ""
        except Exception:
            src = ""
        self._loader_thread = QThread(self)
        self._loader_worker = _FirmwareListLoader(src)
        self._loader_worker.moveToThread(self._loader_thread)
        self._loader_thread.started.connect(self._loader_worker.run)
        self._loader_worker.loaded.connect(self._on_loaded)
        self._loader_worker.error.connect(self._on_load_error)
        # quit & cleanup on both success and error
        self._loader_worker.loaded.connect(self._loader_thread.quit)
        self._loader_worker.error.connect(self._loader_thread.quit)
        self._loader_worker.loaded.connect(self._loader_worker.deleteLater)
        self._loader_worker.error.connect(self._loader_worker.deleteLater)
        self._loader_thread.finished.connect(self._loader_thread.deleteLater)
        self._loader_thread.start()

    def populate_table(self):
        try:
            self.table.setRowCount(0)
        except Exception:
            pass
        for item in self.all_items:
            name = item.get("name", "-")
            url = item.get("url", "")
            model = item.get("model", "一加Ace Pro")
            notes = item.get("notes", "") or ""
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(name)
            model_item = QTableWidgetItem(model)
            try:
                name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
                model_item.setFlags(model_item.flags() & ~Qt.ItemIsEditable)
                name_item.setTextAlignment(Qt.AlignCenter)
                model_item.setTextAlignment(Qt.AlignCenter)
            except Exception:
                pass
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, model_item)
            # 操作列
            cell = QWidget()
            h = QHBoxLayout(cell); h.setContentsMargins(0,0,0,0); h.setSpacing(8); h.setAlignment(Qt.AlignCenter)
            if notes.strip():
                log_btn = PushButton("更新日志")
                h.addWidget(log_btn)
                # 传递当前行索引，避免点击按钮时未选中行导致取不到 notes
                log_btn.clicked.connect(lambda _, idx=row: self._show_port_changelog(idx))
            btn = PrimaryPushButton("下载")
            h.addWidget(btn)
            self.table.setCellWidget(row, 2, cell)
            btn.clicked.connect(lambda _, nm=name, u=url: self._on_download(nm, u))

    def _apply_table_layout(self):
        try:
            vw = self.table.viewport().width()
            c0 = int(vw * 0.40)
            c1 = int(vw * 0.40)
            c2 = max(120, vw - c0 - c1)  # 余量给操作列，确保至少120px
            self.table.setColumnWidth(0, c0)
            self.table.setColumnWidth(1, c1)
            self.table.setColumnWidth(2, c2)
        except Exception:
            pass

    def resizeEvent(self, e):
        try:
            self._apply_table_layout()
        except Exception:
            pass
        return super().resizeEvent(e)

    # 兼容旧接口，已不使用
    def create_download_button(self, name: str, url: str):
        return QWidget()

    def _show_port_changelog(self, row_index: int | None = None):
        # 展示指定行或当前选中行的 notes；若无则提示
        try:
            row = row_index if row_index is not None else self.table.currentRow()
            if row < 0 or row >= len(self.all_items):
                InfoBar.info("提示", "请选择包含更新日志的条目", parent=self, position=InfoBarPosition.TOP, isClosable=True)
                return
            notes = self.all_items[row].get('notes', '') or ''
            if not notes:
                InfoBar.info("提示", "该条目无更新日志", parent=self, position=InfoBarPosition.TOP, isClosable=True)
                return
            text = notes
        except Exception:
            text = ""
        dlg = MessageBox("更新日志", text, self)
        try:
            dlg.setClosableOnMaskClicked(True)
            dlg.setDraggable(True)
        except Exception:
            pass
        dlg.exec()

    def _on_loaded(self, items: list):
        try:
            self.all_items = items or []
            self.populate_table()
            InfoBar.success("加载完成", f"共 {len(self.all_items)} 条数据", parent=self, position=InfoBarPosition.TOP, isClosable=True)
        except Exception:
            pass

    def _on_load_error(self, err: str):
        try:
            InfoBar.error("加载失败", err, parent=self, position=InfoBarPosition.TOP, isClosable=True)
        except Exception:
            pass

    def _on_download(self, name: str, url: str):
        """下载按钮点击事件（表格 + 非模态进度对话框）"""
        if not url or url.startswith("https://example.com"):
            InfoBar.warning("警告", "该固件的下载链接不可用或为示例链接！", parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        
        # 检查是否有正在进行的下载
        if self.current_download:
            dlg = MessageDialog("确认下载", "当前已有下载任务在进行，是否取消当前下载并开始新的下载？", self)
            if not dlg.exec():
                return
            self._cancel_current_download()
        
        # 选择保存路径（根据 URL 推断扩展名，优先使用 .7z/.zip 等）
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path_name = os.path.basename(parsed.path)
        _, ext = os.path.splitext(path_name)
        ext = ext if ext else ".zip"
        safe_name = name.replace(' ', '_').replace('/', '_').replace('\\', '_')
        default_filename = f"{safe_name}{ext}"
        filter_str = f"文件 (*{ext});;所有文件 (*.*)"
        # 默认目录：SettingsTab 设置的下载目录
        try:
            settings = QSettings()
            base_dir = settings.value("download/dir", "") or ""
        except Exception:
            base_dir = ""
        if base_dir:
            default_path = os.path.join(base_dir, default_filename)
        else:
            default_path = default_filename
        path, _ = QFileDialog.getSaveFileName(self, "保存固件文件", default_path, filter_str)
        
        if not path:
            return

        # 创建下载工作器和线程
        worker = DownloadWorker(url, path)
        thread = QThread()
        worker.moveToThread(thread)
        
        # 存储当前下载信息
        self.current_download = {'worker': worker, 'thread': thread, 'name': name}

        # 非模态进度对话框
        dlg = _DownloadProgressDialog(name, self)
        self.current_download['dialog'] = dlg
        dlg.canceled.connect(self._cancel_current_download)
        worker.progress.connect(dlg.set_progress)
        dlg.show()

        # 连接信号槽
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_download_finished)
        worker.error.connect(self._on_download_error)
        
        # 线程结束时自动清理线程对象
        thread.finished.connect(thread.deleteLater)
        
        # 启动线程
        thread.start()

    def _cancel_current_download(self):
        """取消当前下载"""
        if not self.current_download:
            return
            
        download_info = self.current_download
        worker = download_info['worker']
        try:
            worker.cancel()
        except Exception:
            pass
        # 关闭对话框
        try:
            dlg = download_info.get('dialog')
            if dlg:
                dlg.close()
        except Exception:
            pass
        # 立刻尝试清理
        self._force_cleanup_download()

    def _force_cleanup_download(self):
        """强制清理下载资源"""
        if not self.current_download:
            return
            
        download_info = self.current_download
        thread = download_info['thread']
        dlg = download_info.get('dialog')
        
        # 强制终止线程
        if thread.isRunning():
            try:
                thread.quit()
                if not thread.wait(1500):
                    thread.terminate()
                    thread.wait()
            except Exception:
                try:
                    thread.terminate(); thread.wait()
                except Exception:
                    pass
        
        try:
            if dlg:
                dlg.close()
        except Exception:
            pass
        
        # 清理资源
        if 'worker' in download_info:
            try:
                download_info['worker'].deleteLater()
            except Exception:
                pass
        
        # 重置当前下载
        self.current_download = None
        
        InfoBar.info("下载取消", "下载已取消", parent=self, position=InfoBarPosition.TOP, isClosable=True)

    def _on_download_finished(self, result: str):
        """下载完成处理"""
        if not self.current_download:
            return
            
        download_info = self.current_download
        thread = download_info['thread']
        name = download_info['name']
        dlg = download_info.get('dialog')
        
        try:
            if dlg:
                dlg.close()
        except Exception:
            pass
        
        # 等待线程结束（最多3秒）
        if thread.isRunning():
            thread.quit()
            if not thread.wait(3000):
                thread.terminate()
                thread.wait()
        
        # 清理worker
        if 'worker' in download_info:
            download_info['worker'].deleteLater()
        
        # 重置当前下载
        self.current_download = None
        
        # 显示结果
        if result == "CANCELED":
            InfoBar.info("下载取消", "下载已成功取消", parent=self, position=InfoBarPosition.TOP, isClosable=True)
        else:
            dlg = MessageDialog("下载成功", f"固件 [{name}] 已成功下载到：\n\n{result}\n\n是否打开文件所在位置？", self)
            if dlg.exec():
                try:
                    os.startfile(os.path.dirname(result))
                except Exception:
                    pass

    def _on_download_error(self, error_msg: str):
        """下载错误处理（卡片内联进度）"""
        if not self.current_download:
            return
            
        download_info = self.current_download
        prog = download_info.get('prog')
        btn = download_info.get('btn')
        thread = download_info['thread']
        
        # 隐藏进度并复位按钮
        if prog:
            prog.setVisible(False)
            prog.setValue(0)
        if btn:
            btn.setEnabled(True)
        
        # 停止线程
        if thread.isRunning():
            thread.quit()
            if not thread.wait(3000):
                thread.terminate()
                thread.wait()
        
        # 清理worker
        if 'worker' in download_info:
            download_info['worker'].deleteLater()
        
        # 重置当前下载
        self.current_download = None
        
        InfoBar.error("下载失败", f"下载固件时出现错误：{error_msg}", parent=self, position=InfoBarPosition.TOP, isClosable=True)

    def cleanup(self):
        # 停止当前下载线程
        try:
            if self.current_download:
                self._cancel_current_download()
                info = self.current_download
                th = info.get('thread')
                if th and th.isRunning():
                    th.quit()
                    th.wait(1500)
        except Exception:
            pass
        # 停止加载线程
        try:
            t = getattr(self, '_loader_thread', None)
            if t is not None and t.isRunning():
                t.quit(); t.wait(1500)
        except Exception:
            pass


class _FirmwareListLoader(QObject):
    loaded = Signal(list)
    error = Signal(str)

    def __init__(self, source: str):
        super().__init__()
        self.source = source

    def run(self):
        try:
            src = self.source or ""
            text = ""
            if src.startswith("http://") or src.startswith("https://"):
                resp = requests.get(src, timeout=(5, 10))
                resp.raise_for_status()
                text = resp.text
            else:
                # treat as local path
                path = src
                if path.startswith("file://"):
                    path = path[7:]
                with open(path, 'r', encoding='utf-8') as f:
                    text = f.read()
            data = json.loads(text)
            if not isinstance(data, list):
                raise ValueError("返回数据不是数组")
            # 规范化字段
            items = []
            for it in data:
                if not isinstance(it, dict):
                    continue
                items.append({
                    'name': it.get('name', ''),
                    'model': it.get('model', '一加Ace Pro'),
                    'url': it.get('url', ''),
                    'notes': it.get('notes', '')
                })
            self.loaded.emit(items)
        except Exception as e:
            self.error.emit(str(e))



if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QMainWindow

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = QMainWindow()
    window.setWindowTitle("固件下载工具")
    window.setCentralWidget(FirmwareTab())
    window.resize(800, 600)
    window.show()
    
    sys.exit(app.exec())