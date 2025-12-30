import os
import shlex
import subprocess
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QCheckBox, QSpinBox, QComboBox, QTextEdit
)
from pathlib import Path
from qfluentwidgets import CardWidget, PushButton as FluentPushButton, PrimaryPushButton as FluentPrimaryPushButton, FluentIcon, CheckBox, ComboBox, InfoBar, InfoBarPosition, MessageDialog, SmoothScrollArea


class _ScrcpyWorker(QObject):
    finished = Signal(int)
    output = Signal(str)

    def __init__(self, cmd: list[str], cwd: str | None = None):
        super().__init__()
        self._cmd = cmd
        self._cwd = cwd
        self._proc: subprocess.Popen | None = None

    def run(self):
        try:
            self.output.emit("启动命令: " + " ".join(shlex.quote(x) for x in self._cmd))
            self._proc = subprocess.Popen(
                self._cmd,
                cwd=self._cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
            )
            for line in iter(self._proc.stdout.readline, ""):
                if not line:
                    break
                self.output.emit(line.rstrip())
            code = self._proc.wait()
        except FileNotFoundError:
            self.output.emit("未找到 scrcpy 可执行文件，请确认 f:/pythonflash/bin/scrcpy.exe 是否存在")
            code = -1
        except Exception as e:
            self.output.emit(f"运行 scrcpy 失败: {e}")
            code = -1
        finally:
            self.finished.emit(code)

    def terminate(self):
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
        except Exception:
            pass


class ScrcpyTab(QWidget):
    def __init__(self):
        super().__init__()
        self._thread: QThread | None = None
        self._worker: _ScrcpyWorker | None = None
        self._scrcpy_path = self._resolve_scrcpy()
        self._build_ui()

    def _resolve_scrcpy(self) -> str:
        base = Path(__file__).resolve().parent  # app/widgets
        bin1 = (base / ".." / ".." / "bin" / "scrcpy.exe").resolve()
        if bin1.exists():
            return str(bin1)
        bin2 = (Path.cwd() / "bin" / "scrcpy.exe").resolve()
        if bin2.exists():
            return str(bin2)
        return "scrcpy"  # 退回 PATH

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

        lay = QVBoxLayout(container)
        try:
            lay.setContentsMargins(24, 24, 24, 24)
        except Exception:
            pass

        # 顶部渐变 Banner（~110px）
        from PySide6.QtWidgets import QWidget as _W
        banner_w = _W(self)
        try:
            banner_w.setFixedHeight(110)
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
                _ico = FluentIcon.VIDEO.icon()
                icon_lbl.setPixmap(_ico.pixmap(48, 48))
            except Exception:
                pass
        except Exception:
            pass
        title_col = QVBoxLayout(); title_col.setContentsMargins(0,0,0,0); title_col.setSpacing(4)
        title = QLabel("投屏中心", banner_w)
        try:
            title.setStyleSheet("font-size: 22px; font-weight: 600;")
        except Exception:
            pass
        sub = QLabel("scrcpy 一键投屏", banner_w)
        try:
            sub.setStyleSheet("font-size: 14px;")
        except Exception:
            pass
        title_col.addWidget(title); title_col.addWidget(sub)
        banner.addWidget(icon_lbl); banner.addLayout(title_col); banner.addStretch(1)
        lay.addWidget(banner_w)

        # 行1：分辨率、帧率、码率（改用预设下拉）
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("最大分辨率(像素):"))
        self.max_size_cb = ComboBox()
        self.max_size_cb.addItems(["默认", "720", "1080", "1440", "2160", "4320"])  # 4320=8K
        row1.addWidget(self.max_size_cb)
        row1.addSpacing(12)
        row1.addWidget(QLabel("最大帧率(FPS):"))
        self.fps_cb = ComboBox()
        self.fps_cb.addItems(["默认", "30", "60", "90", "120", "144", "165"])  # 最高 165
        row1.addWidget(self.fps_cb)
        row1.addSpacing(12)
        row1.addWidget(QLabel("视频码率:"))
        self.bitrate_cb = ComboBox()
        self.bitrate_cb.addItems(["默认", "4M", "6M", "8M", "12M", "20M", "30M", "50M"]) 
        row1.addWidget(self.bitrate_cb)
        row1.addStretch(1)
        # 参数行先构造，稍后放入卡片

        # 行2：缓冲、音频
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("视频缓冲(ms):"))
        self.vbuf_cb = ComboBox(); self.vbuf_cb.addItems(["默认", "50", "100", "150", "200", "300", "500", "1000"]) 
        row2.addWidget(self.vbuf_cb)
        row2.addSpacing(12)
        row2.addWidget(QLabel("音频缓冲(ms):"))
        self.abuf_cb = ComboBox(); self.abuf_cb.addItems(["默认", "50", "100", "150", "200", "300", "500", "1000"]) 
        row2.addWidget(self.abuf_cb)
        row2.addSpacing(12)
        self.enable_audio = CheckBox("启用音频")
        self.enable_audio.setChecked(True)
        row2.addWidget(self.enable_audio)
        row2.addStretch(1)
        #

        # 行3：窗口与交互
        row3 = QHBoxLayout()
        self.fullscreen = CheckBox("启动时全屏")
        self.borderless = CheckBox("无边框窗口")
        self.always_on_top = CheckBox("置顶")
        self.disable_screensaver = CheckBox("禁用屏保")
        self.stay_awake = CheckBox("保持唤醒")
        self.turn_screen_off = CheckBox("关闭屏幕")
        self.show_touches = CheckBox("显示触摸")
        row3.addWidget(self.fullscreen)
        row3.addWidget(self.borderless)
        row3.addWidget(self.always_on_top)
        row3.addWidget(self.disable_screensaver)
        row3.addWidget(self.stay_awake)
        row3.addWidget(self.turn_screen_off)
        row3.addWidget(self.show_touches)
        row3.setSpacing(6)
        row3.addStretch(1)
        #

        # 行4：剪贴板与点击
        row4 = QHBoxLayout()
        self.clip_sync = CheckBox("剪切板同步")
        self.clip_sync.setChecked(True)
        self.legacy_paste = CheckBox("兼容粘贴(legacy)")
        self.forward_all_clicks = CheckBox("转发所有点击")
        self.print_fps = CheckBox("打印FPS")
        row4.addWidget(self.clip_sync)
        row4.addWidget(self.legacy_paste)
        row4.addWidget(self.forward_all_clicks)
        row4.addWidget(self.print_fps)
        row4.addStretch(1)
        #

        # 行5：按钮与日志
        row5 = QHBoxLayout()
        self.run_btn = FluentPrimaryPushButton("开始投屏")
        self.stop_btn = FluentPushButton("停止")
        try:
            self.run_btn.setFixedHeight(36)
            self.stop_btn.setFixedHeight(32)
        except Exception:
            pass
        self.stop_btn.setEnabled(False)
        row5.addWidget(self.run_btn)
        row5.addWidget(self.stop_btn)
        row5.addStretch(1)
        #

        self.log = QTextEdit(); self.log.setReadOnly(True)
        try:
            from PySide6.QtCore import Qt as _Qt
            self.log.setVerticalScrollBarPolicy(_Qt.ScrollBarAlwaysOff)
            self.log.setHorizontalScrollBarPolicy(_Qt.ScrollBarAlwaysOff)
            self.log.setStyleSheet("background: transparent;")
        except Exception:
            pass
        self.log_view = SmoothScrollArea(self)
        try:
            self.log_view.setWidget(self.log)
            self.log_view.setWidgetResizable(True)
        except Exception:
            pass
        # 采用卡片式布局容纳以上各块
        from PySide6.QtWidgets import QGridLayout as _Grid
        grid = _Grid(); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(12)

        # 视频参数卡片
        card_video = CardWidget(self)
        v_video = QVBoxLayout(card_video); v_video.setContentsMargins(16,20,16,24); v_video.setSpacing(14)
        h_video = QHBoxLayout(); h_video.setSpacing(8)
        h_video_icon = QLabel("🎞"); h_video_icon.setStyleSheet("font-size:16px;")
        h_video_title = QLabel("视频参数"); h_video_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_video.addWidget(h_video_icon); h_video.addWidget(h_video_title); h_video.addStretch(1)
        v_video.addLayout(h_video); v_video.addLayout(row1)

        # 缓冲与音频卡片
        card_buf = CardWidget(self)
        v_buf = QVBoxLayout(card_buf); v_buf.setContentsMargins(16,20,16,24); v_buf.setSpacing(14)
        h_buf = QHBoxLayout(); h_buf.setSpacing(8)
        h_buf_icon = QLabel("🔊"); h_buf_icon.setStyleSheet("font-size:16px;")
        h_buf_title = QLabel("缓冲与音频"); h_buf_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_buf.addWidget(h_buf_icon); h_buf.addWidget(h_buf_title); h_buf.addStretch(1)
        v_buf.addLayout(h_buf); v_buf.addLayout(row2)

        # 窗口与交互卡片
        card_win = CardWidget(self)
        v_win = QVBoxLayout(card_win); v_win.setContentsMargins(16,16,16,16); v_win.setSpacing(10)
        h_win = QHBoxLayout(); h_win.setSpacing(8)
        h_win_icon = QLabel("🪟"); h_win_icon.setStyleSheet("font-size:16px;")
        h_win_title = QLabel("窗口与交互"); h_win_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_win.addWidget(h_win_icon); h_win.addWidget(h_win_title); h_win.addStretch(1)
        v_win.addLayout(h_win); v_win.addLayout(row3)

        # 剪贴板与点击卡片
        card_clip = CardWidget(self)
        v_clip = QVBoxLayout(card_clip); v_clip.setContentsMargins(16,16,16,16); v_clip.setSpacing(10)
        h_clip = QHBoxLayout(); h_clip.setSpacing(8)
        h_clip_icon = QLabel("📋"); h_clip_icon.setStyleSheet("font-size:16px;")
        h_clip_title = QLabel("剪贴板与点击"); h_clip_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_clip.addWidget(h_clip_icon); h_clip.addWidget(h_clip_title); h_clip.addStretch(1)
        v_clip.addLayout(h_clip); v_clip.addLayout(row4)

        # 操作卡片
        card_act = CardWidget(self)
        v_act = QVBoxLayout(card_act); v_act.setContentsMargins(16,20,16,24); v_act.setSpacing(14)
        h_act = QHBoxLayout(); h_act.setSpacing(8)
        h_act_icon = QLabel("▶️"); h_act_icon.setStyleSheet("font-size:16px;")
        h_act_title = QLabel("操作"); h_act_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_act.addWidget(h_act_icon); h_act.addWidget(h_act_title); h_act.addStretch(1)
        v_act.addLayout(h_act); v_act.addLayout(row5)

        # 日志卡片
        card_log = CardWidget(self)
        v_log = QVBoxLayout(card_log); v_log.setContentsMargins(16,16,16,16); v_log.setSpacing(10)
        h_log = QHBoxLayout(); h_log.setSpacing(8)
        h_log_icon = QLabel("📝"); h_log_icon.setStyleSheet("font-size:16px;")
        h_log_title = QLabel("日志输出"); h_log_title.setStyleSheet("font-size:16px; font-weight:600;")
        h_log.addWidget(h_log_icon); h_log.addWidget(h_log_title); h_log.addStretch(1)
        v_log.addLayout(h_log); v_log.addWidget(self.log_view)

        grid.addWidget(card_video, 0, 0, 1, 2)
        grid.addWidget(card_buf, 1, 0, 1, 2)
        grid.addWidget(card_win, 2, 0)
        grid.addWidget(card_clip, 2, 1)
        grid.addWidget(card_act, 3, 0, 1, 2)
        grid.addWidget(card_log, 4, 0, 1, 2)
        lay.addLayout(grid)

        self.run_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._stop)

    def _build_command(self) -> list[str]:
        cmd: list[str] = [self._scrcpy_path]
        # 分辨率（默认不限制）
        ms = self.max_size_cb.currentText().strip()
        if ms and ms != "默认":
            cmd += ["--max-size", ms]
        # 帧率（最高 165）
        fps_txt = self.fps_cb.currentText().strip()
        if fps_txt and fps_txt != "默认":
            try:
                fps_val = min(int(fps_txt), 165)
                cmd += ["--max-fps", str(fps_val)]
            except Exception:
                pass
        # 码率
        br = self.bitrate_cb.currentText().strip()
        if br and br != "默认":
            cmd += ["--video-bit-rate", br]
        # 缓冲
        vbuf_txt = self.vbuf_cb.currentText().strip()
        if vbuf_txt and vbuf_txt != "默认":
            cmd += ["--video-buffer", vbuf_txt]
        abuf_txt = self.abuf_cb.currentText().strip()
        if abuf_txt and abuf_txt != "默认":
            cmd += ["--audio-buffer", abuf_txt]
        # 音频
        if not self.enable_audio.isChecked():
            cmd += ["--no-audio"]
        # 窗口/行为
        if self.fullscreen.isChecked():
            cmd += ["--fullscreen"]
        if self.borderless.isChecked():
            cmd += ["--window-borderless"]
        if self.always_on_top.isChecked():
            cmd += ["--always-on-top"]
        if self.disable_screensaver.isChecked():
            cmd += ["--disable-screensaver"]
        if self.stay_awake.isChecked():
            cmd += ["--stay-awake"]
        if self.turn_screen_off.isChecked():
            cmd += ["--turn-screen-off"]
        if self.show_touches.isChecked():
            cmd += ["--show-touches"]
        # 剪贴板与点击
        if not self.clip_sync.isChecked():
            cmd += ["--no-clipboard-autosync"]
        if self.legacy_paste.isChecked():
            cmd += ["--legacy-paste"]
        if self.forward_all_clicks.isChecked():
            cmd += ["--forward-all-clicks"]
        if self.print_fps.isChecked():
            cmd += ["--print-fps"]
        return cmd

    def _start(self):
        if self._thread and self._thread.isRunning():
            InfoBar.info("提示", "投屏已在运行中。", parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        cmd = self._build_command()
        self.log.clear()
        self._thread = QThread(self)
        self._worker = _ScrcpyWorker(cmd)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.output.connect(self.log.append)
        self._worker.finished.connect(lambda code: self.log.append(f"scrcpy 退出，代码 {code}"))
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.finished.connect(lambda: self.stop_btn.setEnabled(False))
        self._thread.finished.connect(lambda: self.run_btn.setEnabled(True))
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._thread.start()

    def _stop(self):
        if self._worker:
            self._worker.terminate()
        # 等待线程结束，避免 QThread 未退出被销毁
        if self._thread:
            self._thread.wait(2000)

    def _on_thread_finished(self):
        # 清理引用，防止悬挂
        self._worker = None
        self._thread = None

    # 退出清理，避免 QThread: Destroyed while thread is still running
    def cleanup(self):
        try:
            if hasattr(self, '_worker') and self._worker:
                try:
                    self._worker.terminate()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if hasattr(self, '_thread') and self._thread:
                if self._thread.isRunning():
                    self._thread.quit(); self._thread.wait(1500)
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            self.cleanup()
        except Exception:
            pass
        return super().closeEvent(event)
