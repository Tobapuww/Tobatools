from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QProgressBar, QComboBox, QGridLayout
from PySide6.QtCore import Qt, QObject, Signal, QThread, QTimer, QCoreApplication, QRectF
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QFont, QPalette
from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    InfoBar,
    InfoBarPosition,
    MessageDialog,
    MessageBox,
    CardWidget,
    TitleLabel,
    FluentIcon,
    ComboBox,
    PopupTeachingTip,
    FlyoutViewBase,
    BodyLabel,
    SmoothScrollArea,
)
import os
import subprocess
import re
from typing import Optional

from app.services import adb_service


class StatsRingWidget(QWidget):
    def __init__(self, accent: str = "#2BC3A8", parent=None):
        super().__init__(parent)
        self._value = 0
        self._display = "--"
        self._accent = QColor(accent)
        self._track = QColor(134, 144, 156, 80)
        self._thickness = 12
        self.setMinimumSize(130, 130)
        self.setMaximumSize(160, 160)

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


class DeviceInfoTab(QWidget):
    def __init__(self):
        super().__init__()
        self.v_layout = QVBoxLayout(self)
        try:
            self.v_layout.setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass
        self.scroll = SmoothScrollArea(self)
        self.scroll.setWidgetResizable(True)
        try:
            self.scroll.setStyleSheet("QScrollArea {border: none; background: transparent;}")
        except Exception:
            pass
        self.v_layout.addWidget(self.scroll)

        self.container = QWidget()
        try:
            self.container.setStyleSheet("QWidget {background: transparent;}")
        except Exception:
            pass
        self.scroll.setWidget(self.container)

        layout = QVBoxLayout(self.container)
        try:
            layout.setContentsMargins(24, 24, 24, 24)
            layout.setSpacing(20)
        except Exception:
            pass
        self._msg_boxes = []  # keep strong refs to non-modal dialogs
        self._watch_thread = None
        self._watch_worker = None
        # 顶部消息条状态去抖
        self._last_conn_banner = None  # 'connected' | 'disconnected' | None

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
        # Banner 使用默认主题背景，由 QFluentWidgets 控制浅/深色
        banner = QHBoxLayout(banner_w)
        banner.setContentsMargins(24, 18, 24, 18)
        banner.setSpacing(16)

        # 左侧图标：使用 FluentIcon.DEVELOPER_TOOLS 48x48
        icon_lbl = QLabel("", banner_w)
        try:
            icon_lbl.setStyleSheet("background: transparent;")
            icon_lbl.setFixedSize(48, 48)
            icon_lbl.setAlignment(Qt.AlignCenter)
            # 使用 FluentIcon 生成像素图
            try:
                _ico = FluentIcon.DEVELOPER_TOOLS.icon()
                icon_lbl.setPixmap(_ico.pixmap(48, 48))
            except Exception:
                pass
        except Exception:
            pass

        # 中间标题 + 副标题
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        title = QLabel("设备信息", banner_w)
        try:
            title.setStyleSheet("font-size: 22px; font-weight: 600;")
        except Exception:
            pass
        sub = QLabel("一站式设备信息查询", banner_w)
        try:
            sub.setStyleSheet("font-size: 14px;")
        except Exception:
            pass
        title_col.addWidget(title)
        title_col.addWidget(sub)

        banner.addWidget(icon_lbl)
        banner.addLayout(title_col)
        banner.addStretch(1)
        layout.addWidget(banner_w)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        card_conn = CardWidget(self)
        conn_layout = QVBoxLayout(card_conn)
        conn_layout.setContentsMargins(24, 20, 24, 20)
        conn_layout.setSpacing(16)
        
        # 标题
        head1 = QHBoxLayout()
        head1.setSpacing(10)
        head1_icon = QLabel("🔗")
        head1_icon.setStyleSheet("font-size:20px;")
        head1_title = QLabel("连接状态")
        head1_title.setStyleSheet("font-size:18px; font-weight:600;")
        head1.addWidget(head1_icon)
        head1.addWidget(head1_title)
        head1.addStretch(1)
        conn_layout.addLayout(head1)
        
        # 状态显示区（增加背景和内边距，自适应深色模式）
        status_container = QWidget()
        status_container.setObjectName("statusContainer")
        status_container.setStyleSheet("""
            QWidget#statusContainer {
                background: rgba(0, 0, 0, 0.03);
                border-radius: 8px;
                padding: 16px;
            }
            QWidget#statusContainer:dark {
                background: rgba(255, 255, 255, 0.05);
            }
        """)
        status_layout = QVBoxLayout(status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        self.status_label = QLabel("点击 \"刷新设备\" 获取设备信息")
        self.status_label.setStyleSheet("font-size:15px; font-weight:500; background:transparent;")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        
        conn_layout.addWidget(status_container)
        
        # 操作按钮区
        action_bar = QHBoxLayout()
        action_bar.setSpacing(12)
        self.refresh_btn = PrimaryPushButton("刷新设备")
        self.refresh_btn.setFixedHeight(36)
        self.install_btn = PushButton("安装驱动")
        self.install_btn.setFixedHeight(36)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumHeight(12)
        self.progress.setFixedWidth(120)
        self.progress.setVisible(False)
        action_bar.addWidget(self.refresh_btn)
        action_bar.addWidget(self.install_btn)
        action_bar.addWidget(self.progress)
        action_bar.addStretch(1)
        conn_layout.addLayout(action_bar)

        stats_card = CardWidget(self)
        stats_layout = QHBoxLayout(stats_card)
        stats_layout.setContentsMargins(18, 18, 18, 18)
        stats_layout.setSpacing(18)

        self.battery_ring = self._build_ring("电量概览", "#2BC3A8")
        self.storage_ring = self._build_ring("存储概览", "#4098FF")
        stats_layout.addWidget(self.battery_ring["container"])
        stats_layout.addWidget(self.storage_ring["container"])

        info_grid_container = QWidget(self)
        info_layout = QGridLayout(info_grid_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setHorizontalSpacing(16)
        info_layout.setVerticalSpacing(16)

        info_items = [
            ("connection_status", "连接模式", "🛰"),
            ("bootloader_unlock", "Bootloader", "🔐"),
            ("current_slot", "当前槽位", "📳"),
            ("android_version", "Android版本", "🤖"),
            ("kernel", "内核版本", "</>"),
            ("brand", "品牌", "🏷"),
            ("model", "型号", "📱"),
            ("product", "产品", "📦"),
        ]
        self.info_labels = {}
        for idx, (key, label_text, icon_text) in enumerate(info_items):
            row = idx // 4
            col = idx % 4
            card = self._build_info_item(icon_text, label_text)
            info_layout.addWidget(card["container"], row, col)
            self.info_labels[key] = card["value"]

        self.memory_ring = self._build_ring("运行内存", "#A66BFF")

        health_card = CardWidget(self)
        health_layout = QVBoxLayout(health_card)
        health_layout.setContentsMargins(18, 18, 18, 18)
        health_layout.setSpacing(10)
        head_health = QHBoxLayout()
        head_health.setSpacing(8)
        head_health_icon = QLabel("🩺")
        head_health_icon.setStyleSheet("font-size:18px;")
        head_health_title = QLabel("电池健康")
        head_health_title.setStyleSheet("font-size:16px; font-weight:600;")
        head_health.addWidget(head_health_icon)
        head_health.addWidget(head_health_title)
        head_health.addStretch(1)
        health_layout.addLayout(head_health)

        self.battery_health_ring = StatsRingWidget("#FF8A5B")
        health_layout.addWidget(self.battery_health_ring, 0, Qt.AlignHCenter)
        self.battery_health_summary = QLabel("健康度：--")
        self.battery_health_summary.setAlignment(Qt.AlignCenter)
        self.battery_health_summary.setStyleSheet("color:#4e5969;")
        health_layout.addWidget(self.battery_health_summary)

        self.battery_health_rated_label = QLabel("额定容量：-")
        self.battery_health_full_label = QLabel("充满容量：-")
        for lbl in (self.battery_health_rated_label, self.battery_health_full_label):
            lbl.setStyleSheet("color:#565D6A;")
            health_layout.addWidget(lbl)


        card_reboot = CardWidget(self)
        v4 = QVBoxLayout(card_reboot)
        v4.setContentsMargins(18, 18, 18, 18)
        v4.setSpacing(10)
        head4 = QHBoxLayout()
        head4.setSpacing(8)
        head4_icon = QLabel("🔄")
        head4_icon.setStyleSheet("font-size:18px;")
        head4_title = QLabel("快速重启")
        head4_title.setStyleSheet("font-size:16px; font-weight:600;")
        head4.addWidget(head4_icon)
        head4.addWidget(head4_title)
        head4.addStretch(1)
        v4.addLayout(head4)
        row_rb = QHBoxLayout()
        row_rb.setSpacing(10)
        row_rb.addWidget(QLabel("重启至："))
        self.reboot_target = ComboBox()
        self.reboot_target.addItems(["Bootloader", "Recovery", "FastbootD", "系统", "EDL"])
        try:
            self.reboot_target.setFixedHeight(32)
        except Exception:
            pass
        self.reboot_btn = PrimaryPushButton("执行重启")
        row_rb.addWidget(self.reboot_target)
        row_rb.addWidget(self.reboot_btn)
        row_rb.addStretch(1)
        v4.addLayout(row_rb)

        card_donate = CardWidget(self)
        v5 = QVBoxLayout(card_donate)
        v5.setContentsMargins(18, 18, 18, 18)
        v5.setSpacing(10)
        head5 = QHBoxLayout()
        head5.setSpacing(8)
        head5_icon = QLabel("💝")
        head5_icon.setStyleSheet("font-size:18px;")
        head5_title = QLabel("赞赏支持")
        head5_title.setStyleSheet("font-size:16px; font-weight:600;")
        head5.addWidget(head5_icon)
        head5.addWidget(head5_title)
        head5.addStretch(1)
        v5.addLayout(head5)
        self._donate_copy = QLabel("软件好用？给开发者加个鸡腿吧！")
        try:
            self._donate_copy.setStyleSheet("font-size: 16px; font-weight: 600;")
        except Exception:
            pass
        v5.addWidget(self._donate_copy, 0, Qt.AlignHCenter)
        self.donate_btn = PrimaryPushButton("赞赏")
        try:
            self.donate_btn.setFixedHeight(28)
        except Exception:
            pass
        v5.addWidget(self.donate_btn, 0, Qt.AlignHCenter)

        grid.addWidget(card_conn, 0, 0)
        grid.addWidget(stats_card, 0, 1)
        grid.addWidget(health_card, 0, 2)
        grid.addWidget(info_grid_container, 1, 0, 1, 2)
        grid.addWidget(self.memory_ring["container"], 1, 2)
        grid.addWidget(card_reboot, 2, 0)
        grid.addWidget(card_donate, 2, 1, 1, 2)
        self.card_reboot = card_reboot
        layout.addLayout(grid)

        # 赞赏弹出（PopupTeachingTip：带动画，设置为常驻直至手动关闭）
        import os
        def _resolve_donate_img() -> str:
            try:
                app_dir = QCoreApplication.applicationDirPath()
            except Exception:
                app_dir = ''
            fname = '67a6a81e13a2d739e32d25cc76172f36.jpeg'
            # 首选应用目录下 bin
            cand1 = os.path.join(app_dir, 'bin', fname) if app_dir else ''
            # 其次项目根 bin（开发环境）
            cand2 = os.path.join('f:/pythonflash/bin', fname)
            for p in (cand1, cand2):
                try:
                    if p and os.path.exists(p):
                        return p
                except Exception:
                    pass
            return cand2

        class _DonateView(FlyoutViewBase):
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

        def _show_donate_tip():
            try:
                view = _DonateView(_resolve_donate_img(), self)
                tip = PopupTeachingTip(view, self.donate_btn)
                # 强引用与常驻
                self._donate_view = view
                self._donate_tip = tip
                try:
                    tip.setDuration(10000)
                except Exception:
                    pass
                try:
                    view.close_btn.clicked.connect(tip.close)
                except Exception:
                    pass
                tip.show()
            except Exception:
                # 回退使用 MessageBox 展示
                mb = MessageBox("赞赏", "非常感谢你的支持！", self)
                mb.exec()

        try:
            self.donate_btn.clicked.connect(_show_donate_tip)
        except Exception:
            pass

        self.refresh_btn.clicked.connect(self.refresh)
        self.install_btn.clicked.connect(self._install_driver)
        self.reboot_btn.clicked.connect(self._on_reboot_clicked)
        self._watch_thread = None
        self._watch_worker = None

    def _build_ring(self, title: str, accent: str):
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        header = QLabel(title)
        header.setStyleSheet("font-size:16px; font-weight:600;")
        header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        subtitle = QLabel("实时监测")
        subtitle.setStyleSheet("font-size:12px; color:#86909c;")
        ring_widget = StatsRingWidget(accent=accent, parent=card)
        detail = QLabel("-")
        detail.setAlignment(Qt.AlignCenter)
        detail.setStyleSheet("color:#4e5969;")
        layout.addWidget(header)
        layout.addWidget(subtitle)
        layout.addWidget(ring_widget, alignment=Qt.AlignCenter)
        layout.addWidget(detail)
        return {"container": card, "ring": ring_widget, "detail": detail}

    def _build_info_item(self, icon_text: str, label_text: str):
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        head = QHBoxLayout()
        icon = QLabel(icon_text)
        icon.setStyleSheet("font-size:16px;")
        label = QLabel(label_text)
        label.setStyleSheet("font-size:13px; color:#86909c;")
        head.addWidget(icon)
        head.addWidget(label)
        head.addStretch(1)
        value = QLabel("-")
        value.setStyleSheet("font-size:16px; font-weight:600;")
        layout.addLayout(head)
        layout.addWidget(value)
        return {"container": card, "value": value}

    def _extract_percent(self, text: str) -> Optional[int]:
        if not text:
            return None
        match = re.search(r"(\d{1,3})", str(text))
        if not match:
            return None
        try:
            value = int(match.group(1))
        except ValueError:
            return None
        return max(0, min(100, value))

    def _update_battery_ring(self, raw_value: str, display_text: Optional[str] = None):
        if not hasattr(self, "battery_ring"):
            return
        detail = display_text if display_text is not None else (f"{raw_value}%" if raw_value else "-")
        percent = self._extract_percent(raw_value)
        ring_widget = self.battery_ring["ring"]
        if percent is None:
            ring_widget.setValue(0, "--")
        else:
            ring_widget.setValue(percent, f"{percent}%")
        self.battery_ring["detail"].setText(detail)

    def _update_storage_ring(self, raw_line: str, display_text: Optional[str] = None):
        if not hasattr(self, "storage_ring"):
            return
        detail = display_text if display_text is not None else "-"
        percent = None
        if raw_line:
            match = re.search(r"(\d{1,3})%", raw_line)
            if match:
                try:
                    percent = int(match.group(1))
                except ValueError:
                    percent = None
        ring_widget = self.storage_ring["ring"]
        if percent is None:
            ring_widget.setValue(0, "--")
        else:
            ring_widget.setValue(max(0, min(100, percent)), f"{percent}%")
        self.storage_ring["detail"].setText(detail or "-")

    def _update_memory_ring(self, percent_value: str, display_text: Optional[str] = None):
        if not hasattr(self, "memory_ring"):
            return
        detail = display_text if display_text is not None else "-"
        percent = self._extract_percent(percent_value)
        ring_widget = self.memory_ring["ring"]
        if percent is None:
            ring_widget.setValue(0, "--")
        else:
            ring_widget.setValue(percent, f"{percent}%")
        self.memory_ring["detail"].setText(detail or "-")

    def _update_battery_health(self, percent_value: str, rated: Optional[str], full: Optional[str]):
        if not hasattr(self, "battery_health_ring"):
            return
        percent = self._extract_percent(percent_value)
        if percent is None:
            self.battery_health_ring.setValue(0, "--")
            self.battery_health_summary.setText("健康度：--")
        else:
            self.battery_health_ring.setValue(percent, f"{percent}%")
            self.battery_health_summary.setText(f"健康度：{percent}%")
        rated_text = rated if rated else "-"
        full_text = full if full else "-"
        self.battery_health_rated_label.setText(f"额定容量：{rated_text}")
        self.battery_health_full_label.setText(f"充满容量：{full_text}")
    def _set_status_label(self, text: str, color: str = "#00b42a"):
        try:
            self.status_label.setText(text)
            self.status_label.setStyleSheet(f"color:{color};")
        except Exception:
            pass

    def _apply_banner_state(self, state: str):
        if state == 'connected' and self._last_conn_banner != 'connected':
            try:
                InfoBar.success("状态", "设备已连接", parent=self, position=InfoBarPosition.TOP, duration=2000, isClosable=True)
            except Exception:
                pass
            self._last_conn_banner = 'connected'
        elif state == 'disconnected' and self._last_conn_banner != 'disconnected':
            try:
                InfoBar.success("状态", "设备已断开", parent=self, position=InfoBarPosition.TOP, duration=2000, isClosable=True)
            except Exception:
                pass
            self._last_conn_banner = 'disconnected'

    def _reset_info_display(self):
        for label in self.info_labels.values():
            label.setText("-")
        self._update_battery_ring("", "-")
        self._update_storage_ring("", "-")
        self._update_memory_ring("", "-")
        self._update_battery_health("", None, None)

    def refresh(self):
        if not adb_service.check_adb_available():
            self.status_label.setText("未检测到 adb，请先安装或放入 f:/pythonflash/bin")
            for k in getattr(self, 'info_labels', {}):
                self.info_labels[k].setText("-")
            return

        # Run collection in background
        self._start_loading()
        self._run_collect_async()
        return

    def _run_collect_async(self):
        class Worker(QObject):
            finished = Signal(dict)

            def run(self):
                try:
                    data = adb_service.collect_overall_info()
                except Exception:
                    data = {}
                self.finished.emit(data)

        self._thread = QThread(self)
        self._worker = Worker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_collect_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _start_loading(self):
        self.refresh_btn.setEnabled(False)
        self.progress.setVisible(True)

    def _stop_loading(self):
        self.refresh_btn.setEnabled(True)
        self.progress.setVisible(False)

    def _on_collect_finished(self, info: dict):
        try:
            pass
        finally:
            self._stop_loading()
        info = info or {}
        mode = info.get("connection_status", "none")
        serial = info.get("serial", "")

        if mode == "none":
            self._set_status_label("未发现已连接设备", "#86909c")
            self._apply_banner_state(info.get("banner_state", "disconnected"))
            self._reset_info_display()
            return

        if mode == "offline":
            self._set_status_label("设备已连接但离线/未授权，请在手机上授权 USB 调试", "#ff4d4f")
            self._apply_banner_state(info.get("banner_state", "disconnected"))
            self._reset_info_display()
            return

        status_line = info.get("status_line") or f"已连接：{self._cn_connection(mode)}"
        status_color = info.get("status_color", "#00b42a")
        self._set_status_label(status_line, status_color)
        self._apply_banner_state(info.get("banner_state", "connected"))
        self._reset_info_display()

        primary_keys = [
            "connection_status",
            "bootloader_unlock",
            "battery",
            "storage_data",
            "memory_percent",
            "kernel",
            "current_slot",
            "android_version",
            "brand",
            "model",
            "product",
        ]

        display_values = {}
        for key in primary_keys:
            if key not in info:
                continue
            raw_val = str(info.get(key, ""))
            val = raw_val
            if key == "connection_status":
                val = self._cn_connection(val)
            elif key == "bootloader_unlock":
                val = self._cn_unlock(val)
            elif key == "battery":
                self._update_battery_ring(raw_val)
                val = f"{raw_val}%" if raw_val else "-"
            elif key == "storage_data":
                formatted = self._format_storage(raw_val)
                self._update_storage_ring(raw_val, formatted)
                val = formatted
            elif key == "memory_percent":
                summary = info.get("memory_summary", "-")
                self._update_memory_ring(raw_val, summary)
                continue
            elif key == "current_slot":
                val = val.upper() if val else ""

            if key in self.info_labels:
                display_values[key] = val if val else "-"

        for key, label in self.info_labels.items():
            label.setText(display_values.get(key, "-"))

        if "memory_percent" not in info:
            self._update_memory_ring("", "-")

        self._update_battery_health(
            info.get("battery_health_percent", ""),
            info.get("battery_rated_capacity"),
            info.get("battery_full_capacity"),
        )

        serial_val = info.get("serial", "")
        id_for_reg = serial_val
        mode_val = info.get("connection_status", "")
        if mode_val in ("system", "sideload") and serial_val:
            try:
                bid = adb_service.get_board_id(serial_val)
                if bid:
                    id_for_reg = bid
            except Exception:
                pass

    def _cn_connection(self, v: str) -> str:
        mapping = {
            "system": "系统",
            "sideload": "Sideload",
            "fastbootd": "Fastbootd",
            "bootloader": "Bootloader",
            "offline": "离线",
            "none": "未连接",
        }
        return mapping.get(v, v)

    def _cn_unlock(self, v: str) -> str:
        mapping = {
            "unlocked": "已解锁",
            "locked": "已锁定",
            "unknown": "未知",
        }
        return mapping.get(v, v)

    def _format_storage(self, df_line: str) -> str:
        # Expect df -h output last line like: "/dev/block/...  110G  20G  90G  18%  /data"
        if not df_line:
            return "-"
        parts = [p for p in df_line.split() if p]
        # Common patterns: Filesystem Size Used Avail Use% Mounted
        if len(parts) >= 6:
            size = parts[1]
            used = parts[2]
            avail = parts[3]
            return f"已用 {used}  可用 {avail}  总 {size}"
        # Fallback: try to find tokens with size suffix
        tokens = [p for p in parts if any(s in p for s in ["G", "M", "K", "T"]) and not p.endswith("%")]
        if len(tokens) >= 3:
            size, used, avail = tokens[:3]
            return f"已用 {used}  可用 {avail}  总 {size}"
        return df_line

    def _install_driver(self):
        # 使用 adb_service 中统一解析的 BIN_DIR，避免路径问题
        target = adb_service.BIN_DIR / 'adb-device.exe'
        
        if not target.exists():
            InfoBar.error("错误", f"未找到驱动安装程序：{target}", parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
            
        target_str = str(target)
        try:
            if os.name == 'nt':
                try:
                    os.startfile(target_str)
                except Exception:
                    si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    subprocess.Popen([target_str], startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen([target_str])
            InfoBar.info("提示", "已启动驱动安装程序", parent=self, position=InfoBarPosition.TOP, isClosable=True)
        except Exception as e:
            InfoBar.error("错误", f"启动失败：{e}", parent=self, position=InfoBarPosition.TOP, isClosable=True)

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
                adb = str(adb_service.ADB_BIN) if adb_service.ADB_BIN.exists() else "adb"
                fb = str(adb_service.FASTBOOT_BIN) if adb_service.FASTBOOT_BIN.exists() else "fastboot"
                last_fb = ""
                proc = None
                try:
                    try:
                        proc = subprocess.Popen([adb, "track-devices"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True, **_silent())
                    except Exception:
                        proc = None
                    last_emit = 0.0
                    while not self._stop:
                        emitted = False
                        if proc and proc.stdout:
                            try:
                                line = proc.stdout.readline()
                            except Exception:
                                line = ""
                            if line:
                                now = time.time()
                                if now - last_emit > 0.2:
                                    self.changed.emit()
                                    last_emit = now
                                    emitted = True
                        # Light fastboot check if no adb events
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
                    try:
                        if proc and proc.poll() is None:
                            proc.terminate()
                    except Exception:
                        pass

        self._watch_thread = QThread(self)
        self._watch_worker = Watcher()
        self._watch_worker.moveToThread(self._watch_thread)
        self._watch_thread.started.connect(self._watch_worker.run)
        self._watch_worker.changed.connect(self.refresh, Qt.QueuedConnection)
        self._watch_thread.finished.connect(self._watch_thread.deleteLater)
        self._watch_thread.start()

    def closeEvent(self, event):
        try:
            if self._watch_worker:
                self._watch_worker.stop()
            if self._watch_thread:
                self._watch_thread.quit()
                self._watch_thread.wait(1500)
        except Exception:
            pass
        return super().closeEvent(event)

    def cleanup(self):
        try:
            if hasattr(self, '_watch_worker') and self._watch_worker:
                try:
                    self._watch_worker.stop()
                except Exception:
                    pass
            if hasattr(self, '_watch_thread') and self._watch_thread:
                try:
                    if self._watch_thread.isRunning():
                        self._watch_thread.quit(); self._watch_thread.wait(1500)
                except Exception:
                    pass
            if hasattr(self, '_thread') and self._thread:
                try:
                    if self._thread.isRunning():
                        self._thread.quit(); self._thread.wait(1500)
                except Exception:
                    pass
            if hasattr(self, '_thread2') and self._thread2:
                try:
                    if self._thread2.isRunning():
                        self._thread2.quit(); self._thread2.wait(1500)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_reboot_clicked(self):
        mapping = {
            "Bootloader": "bootloader",
            "Recovery": "recovery",
            "FastbootD": "fastbootd",
            "系统": "system",
            "EDL": "edl",
        }
        target_label = self.reboot_target.currentText()
        target = mapping.get(target_label, "bootloader")

        class Worker(QObject):
            def __init__(self, t: str):
                super().__init__()
                self.t = t
            def run(self):
                # fire-and-forget，不关心结果
                try:
                    adb_service.reboot_to(self.t)
                except Exception:
                    pass

        # 在按钮上方的卡片内部显示 2 秒浮出提示
        try:
            InfoBar.info("提示", "重启指令已发送", parent=getattr(self, 'card_reboot', self), position=InfoBarPosition.TOP, duration=2000, isClosable=True)
        except Exception:
            pass

        # 异步执行命令，但不依赖结果
        self._thread2 = QThread(self)
        self._worker2 = Worker(target)
        self._worker2.moveToThread(self._thread2)
        self._thread2.started.connect(self._worker2.run)
        self._thread2.finished.connect(self._thread2.deleteLater)
        self._thread2.finished.connect(self._thread2.deleteLater)
        self._thread2.start()
        # 立即可再次点击
        self.reboot_btn.setEnabled(True)