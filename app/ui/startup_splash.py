from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize, QPropertyAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QRadialGradient, QLinearGradient
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGraphicsOpacityEffect


class StartupSplash(QWidget):
    def __init__(self, *, icon_path: str, light: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self._bg = None
        self._pulse = 0.0
        self._pulse_dir = 1.0
        self._closing = False
        self._light = bool(light)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._pix = QPixmap(str(Path(icon_path))) if icon_path else QPixmap()

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 34, 40, 30)
        root.setSpacing(16)

        self.logo = QLabel(self)
        self.logo.setAlignment(Qt.AlignCenter)
        if not self._pix.isNull():
            self.logo.setPixmap(self._pix.scaled(QSize(176, 176), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        root.addWidget(self.logo, 0, Qt.AlignHCenter)

        self.title = QLabel("拖把工具箱", self)
        self.title.setAlignment(Qt.AlignCenter)
        f = QFont()
        try:
            f.setPointSize(20)
            f.setBold(True)
        except Exception:
            pass
        self.title.setFont(f)
        self.title.setStyleSheet(
            "color: rgba(18, 18, 20, 230);" if self._light else "color: rgba(255, 255, 255, 235);"
        )
        root.addWidget(self.title)

        self.status = QLabel("正在启动...", self)
        self.status.setAlignment(Qt.AlignCenter)
        f2 = QFont()
        try:
            f2.setPointSize(11)
        except Exception:
            pass
        self.status.setFont(f2)
        self.status.setStyleSheet(
            "color: rgba(18, 18, 20, 200);" if self._light else "color: rgba(255, 255, 255, 210);"
        )
        root.addWidget(self.status)

        self._dots_timer = QTimer(self)
        self._dots_timer.timeout.connect(self._tick_dots)
        self._dots_timer.start(350)
        self._dots_i = 0
        self._base_status = "正在启动"

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self._pulse_timer.start(16)

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)

        self._fade_in = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_in.setDuration(260)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)

        self.resize(520, 392)

        try:
            self._opacity.setOpacity(0.0)
            self._fade_in.start()
        except Exception:
            pass

    def fade_out_and_close(self, *, duration_ms: int = 220):
        if self._closing:
            return
        self._closing = True
        try:
            anim = QPropertyAnimation(self._opacity, b"opacity", self)
            anim.setDuration(int(duration_ms))
            try:
                anim.setStartValue(float(self._opacity.opacity()))
            except Exception:
                anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.finished.connect(self.close)
            # Keep reference
            self._fade_out = anim
            anim.start()
        except Exception:
            try:
                self.close()
            except Exception:
                pass

    def set_status(self, text: str):
        s = (text or "").strip()
        if not s:
            s = "正在启动"
        self._base_status = s
        self._dots_i = 0
        self._apply_status_text()

    def center_on_screen(self):
        try:
            scr = self.screen()
            geo = scr.availableGeometry() if scr else None
            if geo:
                x = geo.x() + (geo.width() - self.width()) // 2
                y = geo.y() + (geo.height() - self.height()) // 2
                self.move(x, y)
        except Exception:
            pass

    def _tick_dots(self):
        self._dots_i = (self._dots_i + 1) % 4
        self._apply_status_text()

    def _apply_status_text(self):
        dots = "." * self._dots_i
        self.status.setText(f"{self._base_status}{dots}")

    def _tick_pulse(self):
        self._pulse += 0.018 * self._pulse_dir
        if self._pulse >= 1.0:
            self._pulse = 1.0
            self._pulse_dir = -1.0
        elif self._pulse <= 0.0:
            self._pulse = 0.0
            self._pulse_dir = 1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect().adjusted(0, 0, -1, -1)
        radius = 26

        # IMPORTANT (Windows): avoid effects that draw outside the window bounds on layered windows.
        # All painting here stays within 'r' to prevent UpdateLayeredWindowIndirect errors.

        # base glass panel
        base_grad = QLinearGradient(r.topLeft(), r.bottomRight())
        if self._light:
            base_grad.setColorAt(0.0, QColor(248, 249, 252, 245))
            base_grad.setColorAt(0.5, QColor(244, 246, 250, 248))
            base_grad.setColorAt(1.0, QColor(236, 238, 244, 245))
        else:
            base_grad.setColorAt(0.0, QColor(18, 18, 22, 232))
            base_grad.setColorAt(0.5, QColor(20, 20, 26, 238))
            base_grad.setColorAt(1.0, QColor(14, 14, 18, 232))
        p.setPen(Qt.NoPen)
        p.setBrush(base_grad)
        p.drawRoundedRect(r, radius, radius)

        # breathing glow (layered)
        cx = r.center().x()
        cy = int(r.top() + r.height() * 0.38)
        rr = int(min(r.width(), r.height()) * (0.80 + 0.06 * self._pulse))
        if self._light:
            a1 = int(92 + 88 * self._pulse)
            a2 = int(24 + 36 * self._pulse)
        else:
            a1 = int(140 + 110 * self._pulse)
            a2 = int(42 + 48 * self._pulse)
        grad = QRadialGradient(cx, cy, rr)
        grad.setColorAt(0.0, QColor(42, 116, 218, a1))
        grad.setColorAt(0.42, QColor(42, 116, 218, a2))
        grad.setColorAt(1.0, QColor(42, 116, 218, 0))
        p.setBrush(grad)
        p.drawRoundedRect(r, radius, radius)

        # subtle vignette
        v = QRadialGradient(cx, cy, int(min(r.width(), r.height()) * 0.95))
        v.setColorAt(0.0, QColor(0, 0, 0, 0))
        v.setColorAt(1.0, QColor(0, 0, 0, 40 if self._light else 95))
        p.setBrush(v)
        p.drawRoundedRect(r, radius, radius)

        # inner shadow to add depth (stays inside bounds)
        inner = QLinearGradient(r.topLeft(), r.bottomLeft())
        if self._light:
            inner.setColorAt(0.0, QColor(255, 255, 255, int(110 + 40 * self._pulse)))
            inner.setColorAt(0.22, QColor(255, 255, 255, 0))
            inner.setColorAt(0.82, QColor(0, 0, 0, 0))
            inner.setColorAt(1.0, QColor(0, 0, 0, 28))
        else:
            inner.setColorAt(0.0, QColor(255, 255, 255, 16))
            inner.setColorAt(0.18, QColor(255, 255, 255, 0))
            inner.setColorAt(0.85, QColor(0, 0, 0, 0))
            inner.setColorAt(1.0, QColor(0, 0, 0, 34))
        p.setBrush(inner)
        p.drawRoundedRect(r, radius, radius)

        # glass border highlight
        p.setBrush(Qt.NoBrush)
        if self._light:
            p.setPen(QColor(255, 255, 255, int(140 + 40 * self._pulse)))
        else:
            p.setPen(QColor(255, 255, 255, int(46 + 24 * self._pulse)))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius - 1, radius - 1)

        p.end()
