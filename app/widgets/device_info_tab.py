from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QProgressBar, QGridLayout
from PySide6.QtCore import Qt, QObject, Signal, QThread, QTimer, QCoreApplication, QRectF
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QFont, QPalette, QIcon
from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    CardWidget,
    FluentIcon,
    ComboBox,
    PopupTeachingTip,
    FlyoutViewBase,
    BodyLabel,
    SmoothScrollArea,
    LineEdit,
    MessageBoxBase,
)
import os
import subprocess
import re
import time
import secrets
import string
from typing import Optional

from app.services import adb_service


class _WirelessAdbWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, action: str, host: str, connect_port: str, pair_port: str, pair_code: str):
        super().__init__()
        self.action = str(action or '').strip()
        self.host = str(host or '').strip()
        self.connect_port = str(connect_port or '').strip()
        self.pair_port = str(pair_port or '').strip()
        self.pair_code = str(pair_code or '').strip()

    def run(self):
        try:
            if self.action == 'pair':
                code, out = adb_service.adb_pair(self.host, self.pair_port, self.pair_code)
                ok = code == 0
                self.finished.emit(ok, out or ("ok" if ok else "failed"))
                return
            if self.action == 'connect':
                code, out = adb_service.adb_connect(self.host, self.connect_port)
                ok = code == 0
                self.finished.emit(ok, out or ("ok" if ok else "failed"))
                return
            if self.action == 'disconnect':
                code, out = adb_service.adb_disconnect(self.host, self.connect_port)
                ok = code == 0
                self.finished.emit(ok, out or ("ok" if ok else "failed"))
                return
            self.finished.emit(False, 'unknown action')
        except Exception as e:
            self.finished.emit(False, str(e))


class _WirelessAdbDialog(MessageBoxBase):
    connected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._thread = None
        self._worker = None

        self._mdns_thread = None
        self._mdns_worker = None

        self._last_action = ''

        self._adb_service_id = ''
        self._adb_password = ''
        self._qr_text = ''

        self.titleLabel = QLabel("无线连接")
        self.titleLabel.setStyleSheet("font-size:16px; font-weight:600;")
        self.viewLayout.addWidget(self.titleLabel)

        self.qrLabel = QLabel("请用手机『无线调试-扫码配对』扫描下方二维码。工具会自动尝试连接，若二维码扫描连接失败，请手动重启一次设备无线调试的开关。你也可以在下方手动输入连接信息进行连接。")
        self.qrLabel.setWordWrap(True)
        self.qrLabel.setStyleSheet("color:#565D6A;")
        self.viewLayout.addWidget(self.qrLabel)

        self.btnRestartAdb = PushButton("重启ADB", self)

        self.serviceLabel = QLabel("ServiceID：-")
        self.serviceLabel.setStyleSheet("color:#4e5969;")
        self.viewLayout.addWidget(self.serviceLabel)

        self.qrImg = QLabel(self)
        self.qrImg.setAlignment(Qt.AlignCenter)
        try:
            self.qrImg.setFixedSize(240, 240)
            self.qrImg.setStyleSheet("background: rgba(0,0,0,0.03); border-radius: 10px;")
        except Exception:
            pass
        self.viewLayout.addWidget(self.qrImg, 0, Qt.AlignHCenter)

        row1 = QHBoxLayout(); row1.setSpacing(10)
        row1.addWidget(QLabel("IP"))
        self.ipEdit = LineEdit(self)
        try:
            self.ipEdit.setPlaceholderText("例如 192.168.1.10")
        except Exception:
            pass
        row1.addWidget(self.ipEdit, 2)
        row1.addWidget(QLabel("连接端口"))
        self.connectPortEdit = LineEdit(self)
        try:
            self.connectPortEdit.setPlaceholderText("例如 5555/37099")
            self.connectPortEdit.setFixedWidth(120)
        except Exception:
            pass
        row1.addWidget(self.connectPortEdit)
        self.viewLayout.addLayout(row1)

        row2 = QHBoxLayout(); row2.setSpacing(10)
        row2.addWidget(QLabel("配对端口"))
        self.pairPortEdit = LineEdit(self)
        try:
            self.pairPortEdit.setPlaceholderText("手机显示的配对端口")
            self.pairPortEdit.setFixedWidth(120)
        except Exception:
            pass
        row2.addWidget(self.pairPortEdit)
        row2.addWidget(QLabel("配对码"))
        self.pairCodeEdit = LineEdit(self)
        try:
            self.pairCodeEdit.setPlaceholderText("6 位配对码")
            self.pairCodeEdit.setFixedWidth(140)
        except Exception:
            pass
        row2.addWidget(self.pairCodeEdit)
        row2.addStretch(1)
        self.viewLayout.addLayout(row2)

        row3 = QHBoxLayout(); row3.setSpacing(10)
        self.btnPair = PrimaryPushButton("配对", self)
        self.btnConnect = PrimaryPushButton("连接", self)
        self.btnDisconnect = PushButton("断开", self)
        row3.addWidget(self.btnPair)
        row3.addWidget(self.btnConnect)
        row3.addWidget(self.btnDisconnect)
        row3.addWidget(self.btnRestartAdb)
        row3.addStretch(1)
        self.viewLayout.addLayout(row3)

        self.statusLabel = QLabel("状态：-")
        self.statusLabel.setWordWrap(True)
        self.statusLabel.setStyleSheet("color:#4e5969;")
        self.viewLayout.addWidget(self.statusLabel)

        try:
            self.yesButton.hide()
            self.cancelButton.setText("关闭")
        except Exception:
            pass

        try:
            self.btnPair.clicked.connect(lambda: self._run('pair'))
            self.btnConnect.clicked.connect(lambda: self._run('connect'))
            self.btnDisconnect.clicked.connect(lambda: self._run('disconnect'))
        except Exception:
            pass

        try:
            self.btnRestartAdb.clicked.connect(self._restart_adb)
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self._gen_qr)
            QTimer.singleShot(150, self._start_mdns_scan)
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            self._stop_mdns_scan()
        except Exception:
            pass

        try:
            if self._thread and self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(1200)
        except Exception:
            pass

        try:
            if hasattr(self, '_restart_thread') and self._restart_thread and self._restart_thread.isRunning():
                self._restart_thread.quit()
                self._restart_thread.wait(1200)
        except Exception:
            pass
        return super().closeEvent(event)

    def _random_string(self, n: int) -> str:
        alphabet = string.ascii_lowercase + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(max(1, int(n))))

    def _gen_qr(self):
        self._adb_service_id = 'toba-' + self._random_string(8)
        self._adb_password = self._random_string(8)
        self._qr_text = f"WIFI:T:ADB;S:{self._adb_service_id};P:{self._adb_password};;"
        try:
            self.serviceLabel.setText(f"ServiceID：{self._adb_service_id}")
        except Exception:
            pass
        try:
            self.pairCodeEdit.setText(self._adb_password)
        except Exception:
            pass
        try:
            self.statusLabel.setText('状态：已生成二维码，请在手机无线调试中扫码')
        except Exception:
            pass

        pm = None
        try:
            import qrcode
            try:
                img = qrcode.make(self._qr_text)
                img = img.resize((220, 220))
                img = img.convert('RGBA')
                data = img.tobytes('raw', 'RGBA')
                from PySide6.QtGui import QImage
                qimg = QImage(data, img.size[0], img.size[1], QImage.Format_RGBA8888)
                pm = QPixmap.fromImage(qimg)
            except Exception:
                pm = None
        except Exception:
            pm = None

        if pm is None or pm.isNull():
            try:
                self.qrImg.setText("未安装二维码依赖，已退化为文本：\n" + self._qr_text + "\n\n请安装：pip install qrcode[pil]")
                self.qrImg.setWordWrap(True)
                self.qrImg.setStyleSheet("background: rgba(0,0,0,0.03); border-radius: 10px; padding:10px; color:#4e5969;")
            except Exception:
                pass
            return

        try:
            self.qrImg.setPixmap(pm)
        except Exception:
            pass

    def _restart_adb(self):
        try:
            self.statusLabel.setText("状态：正在重启 ADB Server...")
            self.btnRestartAdb.setEnabled(False)
            
            class _RestartWorker(QObject):
                finished = Signal()
                def run(self):
                    try:
                        adb_service.adb_kill_server()
                        time.sleep(1)
                        adb_service.adb_start_server()
                    except Exception:
                        pass
                    self.finished.emit()

            self._restart_thread = QThread(self)
            self._restart_worker = _RestartWorker()
            self._restart_worker.moveToThread(self._restart_thread)
            self._restart_thread.started.connect(self._restart_worker.run)
            self._restart_worker.finished.connect(lambda: self.statusLabel.setText("状态：ADB 已重启"))
            self._restart_worker.finished.connect(lambda: self.btnRestartAdb.setEnabled(True))
            self._restart_worker.finished.connect(self._restart_thread.quit)
            self._restart_worker.finished.connect(self._restart_worker.deleteLater)
            self._restart_thread.finished.connect(self._restart_thread.deleteLater)
            self._restart_thread.start()
        except Exception as e:
            self.statusLabel.setText(f"状态：重启 ADB 失败 {str(e)}")
            self.btnRestartAdb.setEnabled(True)

    def _start_mdns_scan(self):
        if not self._adb_service_id or not self._adb_password:
            self._gen_qr()

        try:
            if self._mdns_thread and self._mdns_thread.isRunning():
                return
        except Exception:
            pass

        class _MdnsWorker(QObject):
            finished = Signal(bool, str)
            status_update = Signal(str)
            found = Signal(str, str)
            connect_found = Signal(str, str)

            def __init__(self, service_id: str, password: str):
                super().__init__()
                self._service_id = str(service_id or '').strip()
                self._password = str(password or '').strip()
                self._stop = False
                self._last_ip = ''
                self._last_pair_port = ''

            def stop(self):
                self._stop = True

            def run(self):
                # Try using zeroconf if available
                try:
                    import zeroconf
                    self._run_zeroconf()
                except ImportError:
                    self._run_adb()

            def _run_zeroconf(self):
                from zeroconf import Zeroconf, ServiceBrowser, ServiceStateChange
                
                self.status_update.emit("等待设备扫描二维码...")
                
                found_target = {}
                
                def on_service_state_change(zeroconf, service_type, name, state_change):
                    if self._stop:
                        return
                    if state_change is ServiceStateChange.Added:
                        if "_adb-tls-pairing._tcp" in name:
                            self.status_update.emit(f"发现服务: {name}")
                        
                        if self._service_id and self._service_id in name:
                            info = zeroconf.get_service_info(service_type, name)
                            if info:
                                # parsed_addresses() returns list of str
                                addrs = info.parsed_addresses()
                                if addrs:
                                    found_target['ip'] = addrs[0]
                                    found_target['port'] = info.port
                
                zc = Zeroconf()
                browser = ServiceBrowser(zc, "_adb-tls-pairing._tcp.local.", handlers=[on_service_state_change])
                
                deadline = time.time() + 60
                try:
                    while not self._stop and time.time() < deadline:
                        if 'ip' in found_target:
                            ip = found_target['ip']
                            port = found_target['port']
                            try:
                                self.found.emit(str(ip), str(port))
                            except Exception:
                                pass
                            self._last_ip = str(ip)
                            self._last_pair_port = str(port)
                            self.status_update.emit(f"匹配成功! 正在配对 {ip}:{port}")
                            pcode, pout = adb_service.adb_pair(ip, port, self._password, timeout=15)
                            ok = pcode == 0
                            if ok:
                                try:
                                    self._try_find_connect_port_zeroconf()
                                except Exception:
                                    pass
                            self.finished.emit(ok, (pout or '').strip() or ('成功' if ok else '失败'))
                            return
                        time.sleep(0.5)
                finally:
                    zc.close()
                
                if self._stop:
                    return
                self.finished.emit(False, '扫描超时，未找到匹配的配对服务')

            def _try_find_connect_port_zeroconf(self):
                try:
                    from zeroconf import Zeroconf, ServiceBrowser, ServiceStateChange
                except Exception:
                    return

                if not self._last_ip:
                    return

                self.status_update.emit('正在连接设备...')
                found = {}

                def on_conn_state_change(zeroconf, service_type, name, state_change):
                    if self._stop:
                        return
                    if state_change is not ServiceStateChange.Added:
                        return
                    info = zeroconf.get_service_info(service_type, name)
                    if not info:
                        return
                    addrs = info.parsed_addresses()
                    if not addrs:
                        return
                    ip = addrs[0]
                    if ip != self._last_ip:
                        return
                    found['ip'] = ip
                    found['port'] = info.port

                zc2 = Zeroconf()
                browser2 = ServiceBrowser(zc2, '_adb-tls-connect._tcp.local.', handlers=[on_conn_state_change])
                deadline = time.time() + 10
                try:
                    while not self._stop and time.time() < deadline:
                        if 'port' in found:
                            try:
                                self.connect_found.emit(str(found['ip']), str(found['port']))
                            except Exception:
                                pass
                            self.status_update.emit(f"已获取连接端口：{found['port']}")
                            return
                        time.sleep(0.2)
                finally:
                    zc2.close()

                if not self._stop:
                    self.status_update.emit('未能通过 mDNS 获取连接端口，请在手机「无线调试 → IP 地址与端口」中查看并手动填写')

            def _run_adb(self):
                self.status_update.emit("未安装 zeroconf，正在使用 ADB 扫描 (建议: pip install zeroconf)...")
                try:
                    deadline = time.time() + 60
                    # Support both tabs and spaces as separators
                    line_regex = re.compile(r"([^\s]+)\s+_adb-tls-pairing\._tcp\.\s+([^:]+):([0-9]+)")
                    while not self._stop and time.time() < deadline:
                        code, out = adb_service.adb_mdns_services(timeout=5)
                        if code != 0:
                            self.status_update.emit(f"mDNS 查询出错 (code={code})")
                            time.sleep(1)
                            continue
                        if not out:
                            self.status_update.emit("mDNS 列表为空")
                            time.sleep(1)
                            continue

                        found_pairing_services = 0
                        
                        for line in out.splitlines():
                            # Check if line is a pairing service
                            if "_adb-tls-pairing._tcp." not in line:
                                continue
                                
                            found_pairing_services += 1
                            
                            if self._service_id and self._service_id not in line:
                                # Found a pairing service but ID doesn't match
                                continue
                                
                            m = line_regex.search(line)
                            if not m:
                                continue
                            ip = (m.group(2) or '').strip()
                            port = (m.group(3) or '').strip()
                            if not ip or not port:
                                continue

                            try:
                                self.found.emit(str(ip), str(port))
                            except Exception:
                                pass
                            self._last_ip = str(ip)
                            self._last_pair_port = str(port)
                            self.status_update.emit(f"发现匹配服务，尝试配对 {ip}:{port} ...")
                            pcode, pout = adb_service.adb_pair(ip, port, self._password, timeout=15)
                            ok = pcode == 0
                            if ok:
                                try:
                                    self._try_find_connect_port_adb()
                                except Exception:
                                    pass
                            self.finished.emit(ok, (pout or '').strip() or ('成功' if ok else '失败'))
                            return
                        
                        self.status_update.emit(f"扫描中... 发现 {found_pairing_services} 个配对服务 (0 匹配)")
                        time.sleep(1)
                    self.finished.emit(False, '未找到配对服务（请确认手机已扫码且在同一局域网）')
                except Exception as e:
                    self.finished.emit(False, str(e))

            def _try_find_connect_port_adb(self):
                if not self._last_ip:
                    return
                self.status_update.emit('正在连接设备...')
                line_regex = re.compile(r"([^\s]+)\s+_adb-tls-connect\._tcp\.\s+([^:]+):([0-9]+)")
                deadline = time.time() + 10
                while not self._stop and time.time() < deadline:
                    code, out = adb_service.adb_mdns_services(timeout=5)
                    if code != 0 or not out:
                        time.sleep(0.5)
                        continue
                    for line in out.splitlines():
                        if '_adb-tls-connect._tcp.' not in line:
                            continue
                        m = line_regex.search(line)
                        if not m:
                            continue
                        ip = (m.group(2) or '').strip()
                        port = (m.group(3) or '').strip()
                        if ip != self._last_ip:
                            continue
                        if not port:
                            continue
                        try:
                            self.connect_found.emit(str(ip), str(port))
                        except Exception:
                            pass
                        self.status_update.emit(f"已获取连接端口：{port}")
                        return
                    time.sleep(0.5)

                if not self._stop:
                    self.status_update.emit('未能通过 mDNS 获取连接端口（当前 ADB mDNS 列表可能为空），请在手机「无线调试 → IP 地址与端口」中查看并手动填写')

        try:
            self.statusLabel.setText('状态：扫描 mDNS 中…')
        except Exception:
            pass

        self._mdns_thread = QThread(self)
        self._mdns_worker = _MdnsWorker(self._adb_service_id, self._adb_password)
        self._mdns_worker.moveToThread(self._mdns_thread)
        self._mdns_thread.started.connect(self._mdns_worker.run)
        self._mdns_worker.status_update.connect(self.statusLabel.setText)
        self._mdns_worker.found.connect(self._on_mdns_found)
        self._mdns_worker.connect_found.connect(self._on_mdns_connect_found)
        self._mdns_worker.finished.connect(self._on_mdns_finished)
        self._mdns_worker.finished.connect(self._mdns_thread.quit)
        self._mdns_worker.finished.connect(self._mdns_worker.deleteLater)
        self._mdns_thread.finished.connect(self._mdns_thread.deleteLater)
        self._mdns_thread.finished.connect(self._on_mdns_thread_finished)
        self._mdns_thread.start()

    def _on_mdns_found(self, ip: str, pair_port: str):
        try:
            if hasattr(self, 'ipEdit'):
                try:
                    if not str(self.ipEdit.text() or '').strip():
                        self.ipEdit.setText(str(ip))
                except Exception:
                    self.ipEdit.setText(str(ip))
            if hasattr(self, 'pairPortEdit'):
                try:
                    if not str(self.pairPortEdit.text() or '').strip():
                        self.pairPortEdit.setText(str(pair_port))
                except Exception:
                    self.pairPortEdit.setText(str(pair_port))
        except Exception:
            pass

    def _on_mdns_connect_found(self, ip: str, connect_port: str):
        try:
            if hasattr(self, 'connectPortEdit'):
                try:
                    if not str(self.connectPortEdit.text() or '').strip():
                        self.connectPortEdit.setText(str(connect_port))
                except Exception:
                    self.connectPortEdit.setText(str(connect_port))
        except Exception:
            pass

    def _stop_mdns_scan(self):
        try:
            if self._mdns_worker and hasattr(self._mdns_worker, 'stop'):
                self._mdns_worker.stop()
        except Exception:
            pass
        try:
            if self._mdns_thread and self._mdns_thread.isRunning():
                self._mdns_thread.quit()
                self._mdns_thread.wait(1200)
        except Exception:
            pass

    def _on_mdns_finished(self, ok: bool, out: str):
        try:
            msg = (out or '').strip() or ('成功' if ok else '失败')
            self.statusLabel.setText('状态：' + msg)
        except Exception:
            pass

        if ok:
            try:
                QTimer.singleShot(150, lambda: self._run('connect'))
            except Exception:
                pass

    def _on_mdns_thread_finished(self):
        try:
            self._mdns_worker = None
            self._mdns_thread = None
        except Exception:
            pass

    def _set_busy(self, on: bool):
        b = bool(on)
        try:
            self.btnPair.setEnabled(not b)
            self.btnConnect.setEnabled(not b)
            self.btnDisconnect.setEnabled(not b)
        except Exception:
            pass

    def _run(self, action: str):
        try:
            if self._thread and self._thread.isRunning():
                return
        except Exception:
            pass

        try:
            self._last_action = str(action or '').strip()
        except Exception:
            self._last_action = ''

        try:
            host = str(self.ipEdit.text() or '').strip()
        except Exception:
            host = ''
        try:
            cport = str(self.connectPortEdit.text() or '').strip()
        except Exception:
            cport = ''
        try:
            pport = str(self.pairPortEdit.text() or '').strip()
        except Exception:
            pport = ''
        try:
            pcode = str(self.pairCodeEdit.text() or '').strip()
        except Exception:
            pcode = ''

        if action == 'connect' and not host:
            try:
                self.statusLabel.setText('状态：请填写 IP 地址')
            except Exception:
                pass
            self._set_busy(False)
            return

        self._set_busy(True)
        try:
            if action == 'connect' and host and not cport:
                self.statusLabel.setText('状态：未填写连接端口，正在尝试使用默认端口连接…')
            else:
                self.statusLabel.setText('状态：执行中…')
        except Exception:
            pass

        self._thread = QThread(self)
        self._worker = _WirelessAdbWorker(action, host, cport, pport, pcode)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_finished(self, ok: bool, out: str):
        try:
            msg = (out or '').strip() or ('成功' if ok else '失败')
            self.statusLabel.setText('状态：' + msg)
        except Exception:
            pass

        if ok and (self._last_action == 'connect'):
            try:
                self.connected.emit()
            except Exception:
                pass
            try:
                self.close()
            except Exception:
                pass

    def _on_thread_finished(self):
        try:
            self._worker = None
            self._thread = None
        except Exception:
            pass
        self._set_busy(False)


class StatsRingWidget(QWidget):
    def __init__(self, accent: str = "#2BC3A8", parent=None):
        super().__init__(parent)
        self._value = 0
        self._display = "--"
        self._accent = QColor(accent)
        self._track = QColor(134, 144, 156, 80)
        self._thickness = 10
        self.setMinimumSize(108, 108)
        self.setMaximumSize(132, 132)

    def setAccent(self, accent: str):
        self._accent = QColor(accent)
        self.update()

    def setValue(self, value: int, display: Optional[str] = None):
        try:
            val = int(value)
        except Exception:
            val = 0
        self._value = max(0, min(100, val))
        if display is not None:
            self._display = display or "--"
        self.update()

    def setDisplayText(self, text: str):
        self._display = text or "--"
        self.update()

    def sizeHint(self):
        return self.minimumSize()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(self._thickness, self._thickness, -self._thickness, -self._thickness)
        pen = QPen(self._track, self._thickness)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)

        if self._value > 0:
            pen.setColor(self._accent)
            painter.setPen(pen)
            angle = int((self._value / 100) * 360)
            painter.drawArc(rect, 90 * 16, -angle * 16)

        painter.setPen(self.palette().color(QPalette.WindowText))
        font = painter.font()
        font.setPointSize(18)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, self._display or "--")


class DonateView(FlyoutViewBase):
    def __init__(self, img_path: str, parent=None):
        super().__init__(parent)
        vb = QVBoxLayout(self)
        vb.setContentsMargins(20, 16, 20, 16)
        vb.setSpacing(12)
        self.label = BodyLabel("感谢支持！")
        self.pic = QLabel()
        try:
            pm = QPixmap(img_path)
            if not pm.isNull():
                pm = pm.scaledToWidth(260, Qt.SmoothTransformation)
                self.pic.setPixmap(pm)
        except Exception:
            pass
        self.close_btn = PushButton("关闭")
        vb.addWidget(self.label)
        vb.addWidget(self.pic, 0, Qt.AlignCenter)
        vb.addWidget(self.close_btn, 0, Qt.AlignRight)


class DeviceInfoTab(QWidget):
    def __init__(self):
        super().__init__()
        self._msg_boxes = []
        self._watch_thread = None
        self._watch_worker = None
        self._wifi_thread = None
        self._wifi_worker = None
        self._last_conn_banner = None
        self._pending_connect_notice = False
        self._did_first_show = False
        self._loading_infobar = None

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        self.v_layout = QVBoxLayout(self)
        self.v_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = SmoothScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea {border: none; background: transparent;}")
        self.v_layout.addWidget(self.scroll)

        self.container = QWidget()
        self.container.setStyleSheet("QWidget {background: transparent;}")
        self.scroll.setWidget(self.container)

        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(16)

        self._build_hero_card()
        self._build_rings_row()
        self._build_info_grids()
        self._build_power_menu()
        self._build_action_zone()
        self.layout.addStretch(1)

    def showEvent(self, event):
        super().showEvent(event)
        if self._did_first_show:
            return
        self._did_first_show = True
        try:
            self.refresh()
        except Exception:
            pass
        try:
            self._start_watcher()
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            if self._watch_worker is not None:
                self._watch_worker.stop()
        except Exception:
            pass
        try:
            if self._watch_thread is not None and self._watch_thread.isRunning():
                self._watch_thread.quit()
                self._watch_thread.wait(1500)
        except Exception:
            pass
        return super().closeEvent(event)

    def _build_hero_card(self):
        self.hero_card = CardWidget(self)
        lay = QHBoxLayout(self.hero_card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(16)

        self.hero_icon = QLabel()
        self.hero_icon.setFixedSize(56, 56)
        self.hero_icon.setText("📱")
        self.hero_icon.setStyleSheet("font-size: 44px;")
        self.hero_icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.hero_icon)

        info_lay = QVBoxLayout()
        info_lay.setSpacing(4)
        self.lbl_hero_model = QLabel("未连接设备")
        self.lbl_hero_model.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.lbl_hero_status = QLabel("状态：离线")
        self.lbl_hero_status.setStyleSheet("font-size: 14px; color: #ff4d4f; font-weight: 500;")
        self.lbl_hero_serial = QLabel("序列号：-")
        self.lbl_hero_serial.setStyleSheet("font-size: 13px; color: #86909c;")
        info_lay.addWidget(self.lbl_hero_model)
        info_lay.addWidget(self.lbl_hero_status)
        info_lay.addWidget(self.lbl_hero_serial)
        info_lay.addStretch(1)
        lay.addLayout(info_lay)

        lay.addStretch(1)

        self.layout.addWidget(self.hero_card)

    def _build_rings_row(self):
        row_w = QWidget()
        row_lay = QHBoxLayout(row_w)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(16)

        def _make_ring_card(title, accent, icon_str):
            card = CardWidget()
            lay = QVBoxLayout(card)
            lay.setContentsMargins(16, 16, 16, 16)
            lay.setSpacing(8)
            
            head_lay = QHBoxLayout()
            icon = QLabel(icon_str)
            icon.setStyleSheet("font-size:16px;")
            header = QLabel(title)
            header.setStyleSheet("font-size:15px; font-weight:bold;")
            head_lay.addWidget(icon)
            head_lay.addWidget(header)
            head_lay.addStretch(1)
            lay.addLayout(head_lay)
            
            ring = StatsRingWidget(accent, parent=card)
            detail = QLabel("-")
            detail.setAlignment(Qt.AlignCenter)
            detail.setStyleSheet("color:#86909c; font-size:13px; font-weight: 500;")
            lay.addWidget(ring, alignment=Qt.AlignCenter)
            lay.addWidget(detail)
            return card, ring, detail

        self.card_bat, self.ring_battery, self.lbl_bat_detail = _make_ring_card("电池电量", "#2BC3A8", "🔋")
        self.card_sto, self.ring_storage, self.lbl_sto_detail = _make_ring_card("存储空间", "#4098FF", "💾")
        self.card_mem, self.ring_memory, self.lbl_mem_detail = _make_ring_card("运行内存", "#A66BFF", "🧠")

        row_lay.addWidget(self.card_bat)
        row_lay.addWidget(self.card_sto)
        row_lay.addWidget(self.card_mem)

        self.layout.addWidget(row_w)

    def _build_info_grids(self):
        row_w = QWidget()
        row_lay = QHBoxLayout(row_w)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(16)

        self.info_labels = {}

        def _make_grid_card(title, icon_str, items):
            card = CardWidget()
            lay = QVBoxLayout(card)
            lay.setContentsMargins(18, 18, 18, 18)
            lay.setSpacing(12)
            
            head_lay = QHBoxLayout()
            icon = QLabel(icon_str)
            icon.setStyleSheet("font-size:18px;")
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-size:16px; font-weight:bold;")
            head_lay.addWidget(icon)
            head_lay.addWidget(title_lbl)
            head_lay.addStretch(1)
            lay.addLayout(head_lay)

            grid = QGridLayout()
            grid.setSpacing(12)
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(10)
            for i, (key, label_text) in enumerate(items):
                row = i // 2
                col = i % 2
                lbl_name = QLabel(label_text)
                lbl_name.setStyleSheet("color:#86909c; font-size:13px;")
                lbl_val = QLabel("-")
                lbl_val.setStyleSheet("font-size:14px; font-weight:500;")
                lbl_val.setWordWrap(True)
                item_lay = QVBoxLayout()
                item_lay.setSpacing(4)
                item_lay.addWidget(lbl_name)
                item_lay.addWidget(lbl_val)
                grid.addLayout(item_lay, row, col)
                self.info_labels[key] = lbl_val
            
            lay.addLayout(grid)
            lay.addStretch(1)
            return card

        hw_items = [
            ("brand", "品牌"), ("model", "型号"),
            ("cpu_info", "CPU处理器"), ("resolution", "屏幕分辨率"),
            ("display_density", "屏幕密度(DPI)"), ("storage_type", "存储类型"),
            ("battery_health", "电池健康度"), ("battery_cap", "电池容量")
        ]
        sys_items = [
            ("android_version", "Android版本"), ("sdk", "SDK版本"),
            ("kernel", "内核版本"), ("vndk", "VNDK版本"),
            ("bootloader_unlock", "Bootloader锁"), ("root_status", "Root权限"),
            ("current_slot", "当前A/B槽位"), ("uptime", "本次开机时间")
        ]

        self.card_hw = _make_grid_card("硬件参数", "📱", hw_items)
        self.card_sys = _make_grid_card("系统信息", "⚙️", sys_items)

        row_lay.addWidget(self.card_hw, 1)
        row_lay.addWidget(self.card_sys, 1)

        self.layout.addWidget(row_w)

    def _build_power_menu(self):
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        head_lay = QHBoxLayout()
        icon = QLabel("⚡")
        icon.setStyleSheet("font-size:18px;")
        title = QLabel("电源菜单")
        title.setStyleSheet("font-size:15px; font-weight:bold;")
        head_lay.addWidget(icon)
        head_lay.addWidget(title)
        head_lay.addStretch(1)
        lay.addLayout(head_lay)

        # Body: Vertical layout
        # Row 1: Combo
        self.reboot_mode_combo = ComboBox(card)
        items = ["重启系统", "Recovery", "Bootloader", "FastbootD", "EDL (9008)"]
        try:
            self.reboot_mode_combo.addItems(items)
        except Exception:
            for item in items:
                self.reboot_mode_combo.addItem(item)
        self.reboot_mode_combo.setFixedHeight(36)
        
        # Row 2: Button
        self.btn_reboot_exec = PrimaryPushButton("执行重启")
        self.btn_reboot_exec.setIcon(FluentIcon.POWER_BUTTON)
        self.btn_reboot_exec.setFixedHeight(36)

        lay.addWidget(self.reboot_mode_combo)
        lay.addWidget(self.btn_reboot_exec)
        lay.addStretch(1)

        self.card_power = card

    def _build_action_zone(self):
        self.action_row_widget = QWidget()
        row_lay = QHBoxLayout(self.action_row_widget)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(16)

        # --- Card 1: Device Selection ---
        device_card = CardWidget()
        device_lay = QVBoxLayout(device_card)
        device_lay.setContentsMargins(16, 16, 16, 16)
        device_lay.setSpacing(12)

        device_head = QHBoxLayout()
        device_icon = QLabel("📟")
        device_icon.setStyleSheet("font-size:18px;")
        device_title = QLabel("设备选择")
        device_title.setStyleSheet("font-size:15px; font-weight:bold;")
        device_head.addWidget(device_icon)
        device_head.addWidget(device_title)
        device_head.addStretch(1)
        device_lay.addLayout(device_head)

        self.device_selector = ComboBox(device_card)
        self.device_selector.setFixedHeight(36)
        
        self.btn_refresh = PrimaryPushButton(FluentIcon.SYNC, "刷新设备")
        self.btn_refresh.setFixedHeight(36)

        device_lay.addWidget(self.device_selector)
        device_lay.addWidget(self.btn_refresh)
        device_lay.addStretch(1)

        # --- Card 3: Common Tools ---
        action_card = CardWidget()
        action_lay = QVBoxLayout(action_card)
        action_lay.setContentsMargins(16, 16, 16, 16)
        action_lay.setSpacing(12)

        action_head = QHBoxLayout()
        action_icon = QLabel("🛠️")
        action_icon.setStyleSheet("font-size:18px;")
        action_title = QLabel("常用工具")
        action_title.setStyleSheet("font-size:15px; font-weight:bold;")
        action_head.addWidget(action_icon)
        action_head.addWidget(action_title)
        action_head.addStretch(1)
        action_lay.addLayout(action_head)

        # Row 1: Tool Selector
        self.tool_selector = ComboBox(action_card)
        self.tool_selector.addItems(["无线调试", "重启 ADB 服务", "设备管理器"])
        self.tool_selector.setFixedHeight(36)
        
        # Row 2: Run Button
        self.btn_run_tool = PrimaryPushButton("执行工具")
        self.btn_run_tool.setIcon(FluentIcon.PLAY)
        self.btn_run_tool.setFixedHeight(36)

        action_lay.addWidget(self.tool_selector)
        action_lay.addWidget(self.btn_run_tool)
        action_lay.addStretch(1)

        # Add to main row
        # 1:1:1 ratio
        row_lay.addWidget(device_card, 1)
        row_lay.addWidget(self.card_power, 1)
        row_lay.addWidget(action_card, 1)
        self.layout.addWidget(self.action_row_widget)
        

    def _connect_signals(self):
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_reboot_exec.clicked.connect(self._do_selected_reboot)
        self.btn_run_tool.clicked.connect(self._run_selected_tool)
        self.device_selector.currentTextChanged.connect(self._on_device_selector_changed)

    def refresh(self):
        try:
            info = adb_service.collect_overall_info()
        except Exception:
            info = {}

        mode = str(info.get("mode", "") or "")
        serial = str(info.get("serial", "") or "")
        status_line = str(info.get("status_line", "") or "未发现已连接设备")
        status_color = str(info.get("status_color", "") or "#86909c")
        banner_state = str(info.get("banner_state", "") or "")

        try:
            banner_key = (banner_state, mode, serial)
            last_key = getattr(self, "_last_conn_banner", None)
            last_mode = last_key[1] if isinstance(last_key, tuple) and len(last_key) >= 2 else ""
            if self._did_first_show and last_key is not None and banner_key != last_key:
                if mode in ("system", "sideload") and (self._pending_connect_notice or last_mode not in ("system", "sideload")):
                    InfoBar.success(
                        "设备已连接",
                        f"当前模式：{self._cn_connection(mode) or mode}",
                        parent=self,
                        position=InfoBarPosition.TOP,
                        duration=2200,
                        isClosable=True,
                    )
                    self._pending_connect_notice = False
                elif mode in ("fastbootd", "bootloader", "edl", "brom"):
                    InfoBar.info(
                        "设备模式变化",
                        f"当前模式：{self._cn_connection(mode) or mode}",
                        parent=self,
                        position=InfoBarPosition.TOP,
                        duration=2200,
                        isClosable=True,
                    )
                    self._pending_connect_notice = False
                elif mode == "offline":
                    InfoBar.warning(
                        "设备未授权",
                        "请在手机上授权 USB 调试",
                        parent=self,
                        position=InfoBarPosition.TOP,
                        duration=2600,
                        isClosable=True,
                    )
                elif mode == "none":
                    InfoBar.warning(
                        "设备已断开",
                        "未发现已连接设备",
                        parent=self,
                        position=InfoBarPosition.TOP,
                        duration=2000,
                        isClosable=True,
                    )
            self._last_conn_banner = banner_key
        except Exception:
            pass

        try:
            self._refresh_device_selector(serial)
        except Exception:
            pass

        if mode in ("system", "sideload") and serial:
            brand = str(info.get("brand", "") or "").strip()
            model = str(info.get("model", "") or "").strip()
            title = " ".join([p for p in [brand, model] if p]).strip() or "已连接设备"
        elif mode in ("fastbootd", "bootloader"):
            product = str(info.get("product", "") or "").strip()
            title = product or "Fastboot 设备"
        elif mode in ("edl", "brom"):
            title = "端口模式设备"
        elif mode == "offline":
            title = "设备未授权"
        else:
            title = "未连接设备"

        try:
            self.lbl_hero_model.setText(title)
            self.lbl_hero_status.setText(f"状态：{status_line}")
            self.lbl_hero_status.setStyleSheet(f"font-size: 14px; color: {status_color}; font-weight: 500;")
            self.lbl_hero_serial.setText(f"序列号：{serial or '-'}")
        except Exception:
            pass

        battery = str(info.get("battery", "") or "").strip()
        try:
            battery_num = int(float(battery)) if battery not in ("", "-") else 0
        except Exception:
            battery_num = 0
        try:
            self.ring_battery.setValue(battery_num, f"{battery_num}%")
            self.lbl_bat_detail.setText(
                f"健康度：{info.get('battery_health_percent') or info.get('battery_health') or '-'}"
            )
        except Exception:
            pass

        storage_percent = 0
        storage_detail = str(info.get("storage_data", "") or "-").strip()
        try:
            parts = storage_detail.split()
            if len(parts) >= 5:
                pct = parts[4].strip()
                if pct.endswith("%"):
                    storage_percent = max(0, min(100, int(pct[:-1])))
        except Exception:
            storage_percent = 0
        try:
            self.ring_storage.setValue(storage_percent, f"{storage_percent}%")
            self.lbl_sto_detail.setText(storage_detail or "-")
        except Exception:
            pass

        memory_percent = 0
        try:
            memory_percent = int(float(str(info.get("memory_percent", "0") or "0")))
        except Exception:
            memory_percent = 0
        try:
            self.ring_memory.setValue(memory_percent, f"{memory_percent}%")
            self.lbl_mem_detail.setText(str(info.get("memory_summary", "") or "-"))
        except Exception:
            pass

        label_map = {
            "brand": info.get("brand", ""),
            "model": info.get("model", ""),
            "cpu_info": info.get("cpu_info", ""),
            "resolution": info.get("resolution", ""),
            "display_density": info.get("display_density", ""),
            "storage_type": info.get("storage_type", ""),
            "battery_health": info.get("battery_health_percent", "") or info.get("battery_health", ""),
            "battery_cap": info.get("battery_full_capacity", "") or info.get("battery_rated_capacity", ""),
            "android_version": info.get("android_version", ""),
            "sdk": info.get("sdk", ""),
            "kernel": info.get("kernel", ""),
            "vndk": info.get("vndk", ""),
            "build_display": info.get("build_display", ""),
            "current_slot": info.get("current_slot", ""),
            "bootloader_unlock": info.get("bootloader_unlock", ""),
            "root_status": info.get("root_status", ""),
            "device_serial": info.get("device_serial", "") or serial,
            "uptime": info.get("uptime", ""),
        }
        for key, value in label_map.items():
            try:
                if key in self.info_labels:
                    self.info_labels[key].setText(str(value or "-"))
            except Exception:
                pass

    def _on_device_selector_changed(self, text):
        # Add your logic here to handle the device selector change
        pass

    def _run_selected_tool(self):
        text = self.tool_selector.currentText()
        if text == "无线调试":
            self._open_wireless_dialog()
        elif text == "重启 ADB 服务":
            self._restart_adb()
        elif text == "设备管理器":
            self._open_device_manager()

    def _open_wireless_dialog(self):
        try:
            dlg = _WirelessAdbDialog(self)
            try:
                dlg.connected.connect(self._on_wireless_connected, Qt.QueuedConnection)
            except Exception:
                pass
            dlg.exec()
        except Exception as e:
            InfoBar.error("错误", f"无法打开无线调试窗口: {e}", parent=self, position=InfoBarPosition.TOP, duration=3000, isClosable=True)

    def _on_wireless_connected(self):
        self._pending_connect_notice = True
        try:
            InfoBar.info("正在连接", "已发送连接请求，正在等待设备上线", parent=self, position=InfoBarPosition.TOP, duration=2200, isClosable=True)
        except Exception:
            pass
        try:
            self.refresh()
        except Exception:
            pass

    def _cn_connection(self, mode: str) -> str:
        mapping = {
            "system": "系统",
            "sideload": "Sideload",
            "fastbootd": "FastbootD",
            "bootloader": "Bootloader",
            "offline": "未授权",
            "edl": "EDL",
            "brom": "BROM",
            "none": "未连接",
        }
        return mapping.get(str(mode or "").strip(), str(mode or "").strip())

    def _start_watcher(self):
        class Watcher(QObject):
            changed = Signal()
            def __init__(self):
                super().__init__()
                self._stop = False
            def stop(self):
                self._stop = True
            def run(self):
                import subprocess, time, os
                def _silent():
                    try:
                        if os.name == 'nt':
                            si = subprocess.STARTUPINFO()
                            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                            return {'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW}
                    except Exception:
                        pass
                    return {}
                fb = str(adb_service.FASTBOOT_BIN) if adb_service.FASTBOOT_BIN.exists() else "fastboot"
                last_adb = ""
                last_fb = ""
                try:
                    last_emit = 0.0
                    while not self._stop:
                        emitted = False
                        try:
                            mode, serial = adb_service.detect_connection_mode()
                            devs = adb_service.list_devices()
                            cur = f"{mode}:{serial}:{','.join(devs or [])}"
                        except Exception:
                            cur = ""

                        if cur != last_adb:
                            last_adb = cur
                            now = time.time()
                            if now - last_emit > 0.2:
                                self.changed.emit()
                                last_emit = now
                                emitted = True
                        if not emitted:
                            try:
                                out = subprocess.check_output([fb, "devices"], stderr=subprocess.STDOUT, timeout=1, **_silent()).decode(errors='ignore')
                            except Exception:
                                out = ""
                            out = (out or "").strip()
                            if out != last_fb:
                                last_fb = out
                                self.changed.emit()
                        time.sleep(2.5)
                finally:
                    return

        self._watch_thread = QThread(self)
        self._watch_worker = Watcher()
        self._watch_worker.moveToThread(self._watch_thread)
        self._watch_thread.started.connect(self._watch_worker.run)
        self._watch_worker.changed.connect(self.refresh, Qt.QueuedConnection)
        self._watch_thread.finished.connect(self._watch_thread.deleteLater)
        self._watch_thread.start()

    def _open_device_manager(self):
        try:
            if os.name == 'nt':
                os.startfile('devmgmt.msc')
                InfoBar.success("成功", "已打开设备管理器", parent=self, position=InfoBarPosition.TOP, duration=2000, isClosable=True)
            else:
                InfoBar.warning("提示", "设备管理器仅支持 Windows 系统", parent=self, position=InfoBarPosition.TOP, duration=2000, isClosable=True)
        except Exception as e:
            InfoBar.error("错误", f"无法打开设备管理器: {e}", parent=self, position=InfoBarPosition.TOP, duration=3000, isClosable=True)

    def _refresh_device_selector(self, current_serial: str = ""):
        try:
            serials = adb_service.list_devices()
        except Exception:
            serials = []
        try:
            mode, detected_serial = adb_service.detect_connection_mode()
        except Exception:
            mode, detected_serial = "", ""

        selected = current_serial or detected_serial or ""
        items = []
        if selected and selected not in serials:
            items.append(f"{selected} ({self._cn_connection(mode) or '当前'})")
        for s in serials:
            items.append(s)
        if not items:
            items = ["未检测到设备"]

        try:
            self.device_selector.clear()
        except Exception:
            pass
        try:
            self.device_selector.addItems(items)
        except Exception:
            for item in items:
                self.device_selector.addItem(item)
        try:
            idx = 0
            if selected:
                for i, item in enumerate(items):
                    if item.startswith(selected):
                        idx = i
                        break
            self.device_selector.setCurrentIndex(idx)
        except Exception:
            pass

    def _do_selected_reboot(self):
        try:
            text = str(self.reboot_mode_combo.currentText() or "").strip()
        except Exception:
            text = ""
        mapping = {
            "重启系统": "system",
            "Recovery": "recovery",
            "Bootloader": "bootloader",
            "FastbootD": "fastbootd",
            "EDL (9008)": "edl",
        }
        self._do_reboot(mapping.get(text, "system"))

    def _do_reboot(self, target: str):
        class Worker(QObject):
            finished = Signal()
            def __init__(self, t: str):
                super().__init__()
                self.t = t
            def run(self):
                try:
                    adb_service.reboot_to(self.t)
                except Exception:
                    pass
                try:
                    self.finished.emit()
                except Exception:
                    pass

        try:
            InfoBar.info("提示", "重启指令已发送", parent=getattr(self, 'card_power', self), position=InfoBarPosition.TOP, duration=2000, isClosable=True)
        except Exception:
            pass

        self._thread2 = QThread(self)
        self._worker2 = Worker(target)
        self._worker2.moveToThread(self._thread2)
        self._thread2.started.connect(self._worker2.run)
        try:
            self._worker2.finished.connect(self._thread2.quit)
            self._worker2.finished.connect(self._worker2.deleteLater)
            self._thread2.finished.connect(self._thread2.deleteLater)
        except Exception:
            pass
        self._thread2.start()

    def _resolve_donate_img(self) -> str:
        try:
            app_dir = QCoreApplication.applicationDirPath()
        except Exception:
            app_dir = ''
        fname = '67a6a81e13a2d739e32d25cc76172f36.jpeg'
        cand1 = os.path.join(app_dir, 'bin', fname) if app_dir else ''
        cand2 = os.path.join('f:/pythonflash/bin', fname)
        for p in (cand1, cand2):
            if p and os.path.exists(p):
                return p
        return cand2

    def _show_donate_tip(self):
        try:
            view = DonateView(self._resolve_donate_img(), self)
            tip = PopupTeachingTip(view, self.btn_donate)
            self._donate_view = view
            self._donate_tip = tip
            try:
                tip.setDuration(10000)
                view.close_btn.clicked.connect(tip.close)
            except Exception:
                pass
            tip.show()
        except Exception:
            mb = MessageBox("赞赏", "非常感谢你的支持！", self)
            mb.exec()
