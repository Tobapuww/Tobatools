import os
import subprocess
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QCheckBox, QSpinBox, QComboBox, QDialog, QDialogButtonBox
)
from pathlib import Path
from qfluentwidgets import CardWidget, PushButton as FluentPushButton, PrimaryPushButton as FluentPrimaryPushButton, FluentIcon, CheckBox, ComboBox, InfoBar, InfoBarPosition, MessageDialog, SmoothScrollArea, BodyLabel


def _silent_popen_kwargs() -> dict:
    try:
        if os.name == 'nt':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return {'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW}
    except Exception:
        pass
    return {}


class ScrcpyTab(QWidget):
    def __init__(self):
        super().__init__()
        self._proc: subprocess.Popen | None = None
        self._scrcpy_path = self._resolve_scrcpy()
        self._build_ui()

    def _resolve_adb(self) -> str:
        base = Path(__file__).resolve().parent
        bin1 = (base / ".." / ".." / "bin" / "adb.exe").resolve()
        if bin1.exists():
            return str(bin1)
        bin2 = (Path.cwd() / "bin" / "adb.exe").resolve()
        if bin2.exists():
            return str(bin2)
        return "adb"

    def _list_adb_devices(self) -> list[dict]:
        adb = self._resolve_adb()
        try:
            result = subprocess.run(
                [adb, "devices", "-l"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                **_silent_popen_kwargs(),
            )
        except Exception:
            return []

        out = (result.stdout or "").splitlines()
        devices: list[dict] = []
        for line in out:
            line = line.strip()
            if not line:
                continue
            if line.lower().startswith("list of devices"):
                continue
            if line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial = parts[0]
            state = parts[1]
            if state != "device":
                continue
            model = ""
            device_code = ""
            for p in parts[2:]:
                if p.startswith("model:"):
                    model = p.split(":", 1)[1]
                elif p.startswith("device:"):
                    device_code = p.split(":", 1)[1]
            devices.append({"serial": serial, "model": model, "device": device_code})
        return devices

    def _select_device_serial(self) -> str | None:
        devices = self._list_adb_devices()
        if len(devices) == 0:
            InfoBar.warning("提示", "未检测到可用的 ADB 设备。", parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return None
        if len(devices) == 1:
            return devices[0]["serial"]

        dlg = QDialog(self)
        dlg.setWindowTitle("选择投屏设备")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("检测到多个设备，请选择要投屏的设备：", dlg))
        combo = QComboBox(dlg)
        for d in devices:
            label = d["serial"]
            if d.get("model") or d.get("device"):
                label += f"  ({d.get('model') or d.get('device')})"
            combo.addItem(label, d["serial"])
        lay.addWidget(combo)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dlg)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return None
        return combo.currentData()

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

        main_h_layout = QHBoxLayout()
        main_h_layout.setSpacing(24)
        
        left_col = QVBoxLayout()
        left_col.setSpacing(24)
        
        self._build_config_card(left_col)
        self._build_action_card(left_col)
        left_col.addStretch(1)
        
        right_col = QVBoxLayout()
        right_col.setSpacing(24)
        self._build_info_card(right_col)
        
        left_w = QWidget()
        left_w.setLayout(left_col)
        right_w = QWidget()
        right_w.setLayout(right_col)
        
        main_h_layout.addWidget(left_w, 6)
        main_h_layout.addWidget(right_w, 4)
        lay.addLayout(main_h_layout)

        self.run_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._stop)

    def _build_config_card(self, parent_lay):
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(20)
        
        head = QHBoxLayout()
        icon = QLabel("⚙️")
        icon.setStyleSheet("font-size:18px;")
        title = QLabel("投屏配置")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        head.addWidget(icon)
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)
        
        from PySide6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setSpacing(16)
        
        # row 0
        grid.addWidget(QLabel("分辨率:"), 0, 0)
        self.max_size_cb = ComboBox()
        self.max_size_cb.addItems(["默认", "720", "1080", "1440", "2160", "4320"])
        self.max_size_cb.setFixedHeight(36)
        grid.addWidget(self.max_size_cb, 0, 1)
        
        grid.addWidget(QLabel("帧率:"), 0, 2)
        self.fps_cb = ComboBox()
        self.fps_cb.addItems(["默认", "30", "60", "90", "120", "144", "165"])
        self.fps_cb.setFixedHeight(36)
        grid.addWidget(self.fps_cb, 0, 3)
        
        grid.addWidget(QLabel("码率:"), 0, 4)
        self.bitrate_cb = ComboBox()
        self.bitrate_cb.addItems(["默认", "4M", "6M", "8M", "12M", "20M", "30M", "50M"])
        self.bitrate_cb.setFixedHeight(36)
        grid.addWidget(self.bitrate_cb, 0, 5)
        
        # row 1
        grid.addWidget(QLabel("视缓冲:"), 1, 0)
        self.vbuf_cb = ComboBox()
        self.vbuf_cb.addItems(["默认", "50", "100", "150", "200", "300", "500", "1000"])
        self.vbuf_cb.setFixedHeight(36)
        grid.addWidget(self.vbuf_cb, 1, 1)
        
        grid.addWidget(QLabel("音缓冲:"), 1, 2)
        self.abuf_cb = ComboBox()
        self.abuf_cb.addItems(["默认", "50", "100", "150", "200", "300", "500", "1000"])
        self.abuf_cb.setFixedHeight(36)
        grid.addWidget(self.abuf_cb, 1, 3)
        
        self.enable_audio = CheckBox("启用音频")
        self.enable_audio.setChecked(True)
        grid.addWidget(self.enable_audio, 1, 4, 1, 2)
        
        lay.addLayout(grid)
        
        # 行为复选框区
        behaviors_lay = QGridLayout()
        behaviors_lay.setSpacing(12)
        self.fullscreen = CheckBox("启动全屏")
        self.borderless = CheckBox("无边框")
        self.always_on_top = CheckBox("置顶显示")
        self.disable_screensaver = CheckBox("禁用屏保")
        self.stay_awake = CheckBox("保持唤醒")
        self.turn_screen_off = CheckBox("息屏投屏")
        self.show_touches = CheckBox("显示触摸")
        self.clip_sync = CheckBox("剪切板同步")
        self.clip_sync.setChecked(True)
        self.legacy_paste = CheckBox("兼容粘贴")
        self.forward_all_clicks = CheckBox("转发所有点击")
        self.print_fps = CheckBox("打印FPS")
        
        behaviors_lay.addWidget(self.fullscreen, 0, 0)
        behaviors_lay.addWidget(self.borderless, 0, 1)
        behaviors_lay.addWidget(self.always_on_top, 0, 2)
        behaviors_lay.addWidget(self.disable_screensaver, 0, 3)
        behaviors_lay.addWidget(self.stay_awake, 1, 0)
        behaviors_lay.addWidget(self.turn_screen_off, 1, 1)
        behaviors_lay.addWidget(self.show_touches, 1, 2)
        behaviors_lay.addWidget(self.clip_sync, 1, 3)
        behaviors_lay.addWidget(self.legacy_paste, 2, 0)
        behaviors_lay.addWidget(self.forward_all_clicks, 2, 1)
        behaviors_lay.addWidget(self.print_fps, 2, 2)
        
        lay.addLayout(behaviors_lay)
        parent_lay.addWidget(card)
        
    def _build_action_card(self, parent_lay):
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)
        
        head = QHBoxLayout()
        icon = QLabel("🚀")
        icon.setStyleSheet("font-size:18px;")
        title = QLabel("操作控制")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        head.addWidget(icon)
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)
        
        btn_lay = QHBoxLayout()
        btn_lay.setSpacing(16)
        self.run_btn = FluentPrimaryPushButton(FluentIcon.PLAY, "开始投屏")
        self.run_btn.setFixedHeight(36)
        self.stop_btn = FluentPushButton(FluentIcon.PAUSE, "停止投屏")
        self.stop_btn.setFixedHeight(36)
        self.stop_btn.setEnabled(False)
        btn_lay.addWidget(self.run_btn, 1)
        btn_lay.addWidget(self.stop_btn, 1)
        lay.addLayout(btn_lay)
        
        parent_lay.addWidget(card)
        
    def _build_info_card(self, parent_lay):
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)
        
        head = QHBoxLayout()
        icon = QLabel("�")
        icon.setStyleSheet("font-size:18px;")
        title = QLabel("使用说明")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        head.addWidget(icon)
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)
        
        content = BodyLabel(
            "1. 投屏功能基于 scrcpy 实现，支持极低延迟。\n\n"
            "2. 如果有多个设备，点击“开始投屏”时会弹出选择框。\n\n"
            "3. 推荐使用有线连接，如使用无线投屏，可在“设备管理”页先连接设备。\n\n"
            "4. 投屏窗口将以独立形式弹出，不会阻塞当前界面。\n\n"
            "5. 音频转发功能仅支持 Android 11 及以上系统。\n\n"
            "6. 若投屏黑屏，尝试降低分辨率或关闭音视频缓冲。"
        )
        content.setWordWrap(True)
        content.setStyleSheet("color:#4e5969; font-size:14px; line-height: 1.6;")
        lay.addWidget(content)
        lay.addStretch(1)
        
        parent_lay.addWidget(card)

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
        if self._proc and self._proc.poll() is None:
            InfoBar.info("提示", "投屏已在运行中。", parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return

        serial = self._select_device_serial()
        if not serial:
            return

        cmd = self._build_command()
        # Force scrcpy to use the chosen device when multiple ADB devices exist.
        if len(cmd) >= 1:
            cmd = [cmd[0], "-s", str(serial)] + cmd[1:]
        
        try:
            # 直接启动 scrcpy 进程，不捕获输出，让它在独立窗口运行
            self._proc = subprocess.Popen(cmd)
            InfoBar.success("成功", "scrcpy 已启动", parent=self, position=InfoBarPosition.TOP, duration=2000, isClosable=True)
            self.run_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        except FileNotFoundError:
            InfoBar.error("错误", "未找到 scrcpy 可执行文件", parent=self, position=InfoBarPosition.TOP, duration=3000, isClosable=True)
        except Exception as e:
            InfoBar.error("错误", f"启动 scrcpy 失败: {e}", parent=self, position=InfoBarPosition.TOP, duration=3000, isClosable=True)

    def _stop(self):
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                InfoBar.info("提示", "已发送停止信号", parent=self, position=InfoBarPosition.TOP, duration=2000, isClosable=True)
        except Exception as e:
            InfoBar.warning("提示", f"停止失败: {e}", parent=self, position=InfoBarPosition.TOP, duration=2000, isClosable=True)
        finally:
            self._proc = None
            self.run_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def cleanup(self):
        try:
            if hasattr(self, '_proc') and self._proc:
                if self._proc.poll() is None:
                    self._proc.terminate()
                    self._proc.wait(timeout=2)
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            self.cleanup()
        except Exception:
            pass
        return super().closeEvent(event)
