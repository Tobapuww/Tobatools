import os
import subprocess
import requests
import zipfile
import shutil
import time
from pathlib import Path
from typing import List, Tuple
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFileDialog, QRadioButton, QTextEdit
from qfluentwidgets import (
    PrimaryPushButton,
    PushButton,
    InfoBar,
    InfoBarPosition,
    MessageDialog,
    CardWidget,
    TitleLabel,
    FluentIcon,
    SmoothScrollArea,
    ComboBox,
    BodyLabel,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject

from app.services import adb_service


import urllib3

# Suppress insecure request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class _AutoRootWorker(QObject):
    log = Signal(str)
    finished = Signal(int)

    def __init__(self, root_type: str, download_url: str, adb_path: str, fastboot_path: str, seven_zip_path: str):
        super().__init__()
        self.root_type = root_type
        self.download_url = download_url
        self.adb = adb_path
        self.fastboot = fastboot_path
        self.seven_zip = seven_zip_path
        self.work_dir = Path("root_work")
        self._stop_flag = False

    def _run_cmd(self, cmd: List[str], timeout=None) -> Tuple[int, str]:
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            out_lines = []
            while True:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    s = line.strip()
                    if s:
                        self.log.emit(s)
                    out_lines.append(s)
                    
            return proc.poll(), "\n".join(out_lines)
        except Exception as e:
            return -1, str(e)

    def run(self):
        try:
            self.work_dir.mkdir(exist_ok=True)
            zip_path = self.work_dir / "root_package.zip"
            
            # 1. 下载
            self.log.emit(f"开始下载 {self.root_type}...")
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
                response = requests.get(self.download_url, stream=True, verify=False, headers=headers)
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._stop_flag:
                            self.log.emit("下载已取消")
                            return
                        f.write(chunk)
                        downloaded += len(chunk)
                self.log.emit("下载完成")
            except Exception as e:
                self.log.emit(f"下载失败: {e}")
                self.finished.emit(-1)
                return

            # 2. 解压
            self.log.emit(f"正在解压...")
            extract_dir = self.work_dir / "extracted"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir()
            
            try:
                # 使用 7z.exe 进行解压
                # 7z x archive.zip -ooutdir -y
                cmd = [self.seven_zip, "x", str(zip_path), f"-o{extract_dir}", "-y"]
                code, out = self._run_cmd(cmd)
                if code != 0:
                     # 尝试回退到 zipfile
                    self.log.emit(f"7z 解压失败，尝试使用内置 zipfile... ({out})")
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
            except Exception as e:
                self.log.emit(f"解压失败: {e}")
                self.finished.emit(-1)
                return

            # 寻找 .apk 和 .img
            apk_file = None
            img_file = None
            for f in extract_dir.rglob("*"):
                if f.suffix.lower() == '.apk' and not apk_file:
                    apk_file = f
                elif f.suffix.lower() == '.img' and not img_file:
                    img_file = f
            
            if not apk_file or not img_file:
                self.log.emit("压缩包内容不完整，需包含一个 .apk 和一个 .img")
                self.finished.emit(-1)
                return
                
            self.log.emit(f"找到 APK: {apk_file.name}")
            self.log.emit(f"找到 IMG: {img_file.name}")

            # 3. 安装 APK
            mode, serial = adb_service.detect_connection_mode()
            if mode != 'system':
                self.log.emit("请确保手机在系统模式并连接 ADB")
                self.finished.emit(-1)
                return

            self.log.emit("推送管理器到设备...")
            code, _ = self._run_cmd([self.adb, "push", str(apk_file), "/sdcard/root_app.apk"])
            if code != 0:
                self.log.emit("推送失败")
                self.finished.emit(-1)
                return

            self.log.emit("安装管理器...")
            self.log.emit("提示：若长时间卡住，请在手机上手动安装 /sdcard/root_app.apk")
            code, _ = self._run_cmd([self.adb, "install", "-r", str(apk_file)])
            if code != 0:
                self.log.emit("安装失败，请尝试手动安装")
            else:
                self.log.emit("APK 安装成功")

            # 4. 重启到 Bootloader
            self.log.emit("重启至 Bootloader...")
            self._run_cmd([self.adb, "reboot", "bootloader"])
            time.sleep(5) # 等待重启

            # 5. 刷入 Boot
            self.log.emit("正在刷入 Boot 镜像...")
            code, _ = self._run_cmd([self.fastboot, "flash", "boot", str(img_file)])
            if code != 0:
                self.log.emit("刷入失败")
                self.finished.emit(-1)
                return

            # 6. 重启系统
            self.log.emit("重启至系统...")
            self._run_cmd([self.fastboot, "reboot"])
            
            self.log.emit("全自动 Root 流程完成！")
            self.finished.emit(0)

        except Exception as e:
            self.log.emit(f"发生未知错误: {e}")
            self.finished.emit(-1)

    def stop(self):
        self._stop_flag = True


class RootTab(QWidget):
    def __init__(self):
        super().__init__()
        self._adb = self._resolve_bin("adb")
        self._fastboot = self._resolve_bin("fastboot")
        self._7z = self._resolve_bin("7z")
        self._thread: QThread | None = None
        self._worker: _AutoRootWorker | None = None
        self._build_ui()

    def _resolve_bin(self, name: str) -> str:
        base = Path(__file__).resolve().parent
        # project bin
        tool = (base / ".." / ".." / "bin" / (name + ".exe")).resolve()
        if tool.exists():
            return str(tool)
        return name

    def _build_ui(self):
        self._outer_layout = QVBoxLayout(self)
        try:
            self._outer_layout.setContentsMargins(0, 0, 0, 0)
            self._outer_layout.setSpacing(0)
        except Exception:
            pass
        self._scroll = SmoothScrollArea(self)
        self._scroll.setWidgetResizable(True)
        try:
            self._scroll.setStyleSheet("QScrollArea {border: none; background: transparent;}")
        except Exception:
            pass
        self._outer_layout.addWidget(self._scroll)

        container = QWidget()
        try:
            container.setStyleSheet("QWidget {background: transparent;}")
        except Exception:
            pass
        self._scroll.setWidget(container)

        lay = QVBoxLayout(container)
        try:
            lay.setContentsMargins(24, 24, 24, 24)
            lay.setSpacing(12)
        except Exception:
            pass

        from PySide6.QtWidgets import QWidget as _W
        banner_w = _W(self)
        try:
            banner_w.setFixedHeight(110)
        except Exception:
            pass
        banner = QHBoxLayout(banner_w)
        banner.setContentsMargins(24, 18, 24, 18)
        banner.setSpacing(16)
        
        icon_lbl = QLabel("", banner_w)
        icon_lbl.setFixedSize(48, 48)
        try:
            _ico = FluentIcon.Shield.icon() if hasattr(FluentIcon, "Shield") else FluentIcon.SETTING.icon()
            icon_lbl.setPixmap(_ico.pixmap(48, 48))
        except:
            pass
            
        title_col = QVBoxLayout(); title_col.setContentsMargins(0,0,0,0); title_col.setSpacing(4)
        t = QLabel("全自动 Root（开发中）", banner_w)
        t.setStyleSheet("font-size: 22px; font-weight: 600;")
        s = QLabel("⚠️ 此功能正在开发中，暂不可用", banner_w)
        s.setStyleSheet("font-size: 14px; color: #FF6B6B;")
        
        title_col.addWidget(t); title_col.addWidget(s)
        banner.addWidget(icon_lbl); banner.addLayout(title_col); banner.addStretch(1)
        lay.addWidget(banner_w)

        # Options Card
        card_opt = CardWidget(self)
        v_opt = QVBoxLayout(card_opt); v_opt.setContentsMargins(16,16,16,16); v_opt.setSpacing(10)
        
        row1 = QHBoxLayout()
        row1.addWidget(BodyLabel("选择 Root 方案:"))
        self.combo_root = ComboBox()
        self.combo_root.addItems(["Sukisu-Ultra", "Magisk", "KernelSU-Next"])
        self.combo_root.setMinimumWidth(200)
        self.combo_root.setEnabled(False)  # 禁用下拉框
        row1.addWidget(self.combo_root)
        row1.addStretch(1)
        
        self.start_btn = PrimaryPushButton("开始 Root")
        self.start_btn.setEnabled(False)  # 禁用按钮
        self.start_btn.setToolTip("此功能正在开发中，暂不可用")
        self.start_btn.clicked.connect(self._start)
        row1.addWidget(self.start_btn)
        
        v_opt.addLayout(row1)
        lay.addWidget(card_opt)

        # Log Card
        card_log = CardWidget(self)
        v_log = QVBoxLayout(card_log)
        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log_view = SmoothScrollArea(self)
        self.log_view.setWidget(self.log)
        self.log_view.setWidgetResizable(True)
        v_log.addWidget(self.log_view)
        
        lay.addWidget(card_log)

    def _start(self):
        # 功能开发中，禁止使用
        InfoBar.warning(
            "功能开发中", 
            "全自动 Root 功能正在开发中，暂不可用。请使用其他方式获取 Root 权限。",
            parent=self, 
            position=InfoBarPosition.TOP,
            duration=3000
        )
        return
        
        # 以下代码暂时禁用
        root_map = {
            "Sukisu-Ultra": "https://gitee.com/gyah/apboot/releases/download/1/sukisuultra.zip",
            "Magisk": "https://gitee.com/gyah/apboot/releases/download/1/magisk.zip",
            "KernelSU-Next": "https://gitee.com/gyah/apboot/releases/download/1/kernelsu-next.zip"
        }
        
        choice = self.combo_root.currentText()
        url = root_map.get(choice)
        
        if not url:
            InfoBar.error("错误", "无效的选择", parent=self, position=InfoBarPosition.TOP)
            return

        confirm = MessageDialog("警告", 
            f"即将在当前设备上执行 {choice} Root 流程。\n\n"
            "步骤：\n1. 下载资源包\n2. 推送并安装管理 APP\n3. 重启到 Bootloader\n4. 刷入 Boot 镜像\n\n"
            "请确保手机已解锁 Bootloader 且处于系统模式（开启 USB 调试）。\n是否继续？", self)
            
        if confirm.exec():
            self.log.clear()
            self.start_btn.setEnabled(False)
            self.combo_root.setEnabled(False)
            
            self._thread = QThread(self)
            self._worker = _AutoRootWorker(choice, url, self._adb, self._fastboot, self._7z)
            self._worker.moveToThread(self._thread)
            
            self._thread.started.connect(self._worker.run)
            self._worker.log.connect(self.log.append)
            self._worker.finished.connect(self._on_finished)
            # 自动清理：worker 结束 -> thread 退出 -> thread 删除
            self._worker.finished.connect(self._thread.quit)
            self._worker.finished.connect(self._worker.deleteLater)
            self._thread.finished.connect(self._thread.deleteLater)
            
            self._thread.start()

    def _on_finished(self, code):
        self.start_btn.setEnabled(True)
        self.combo_root.setEnabled(True)
        if code == 0:
            InfoBar.success("完成", "Root 流程执行完毕", parent=self, position=InfoBarPosition.TOP)
        else:
            InfoBar.error("失败", "Root 流程遇到错误，请查看日志", parent=self, position=InfoBarPosition.TOP)
        
        # 清除引用，但不强制 wait/quit，交由信号链处理
        self._thread = None
        self._worker = None

    def cleanup(self):
        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait(1000)

