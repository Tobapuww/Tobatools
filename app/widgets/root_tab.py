import os
import subprocess
import requests
import zipfile
import shutil
import gzip
import time
from pathlib import Path
from typing import List, Tuple
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFileDialog, QGridLayout
from qfluentwidgets import (
    PrimaryPushButton,
    PushButton,
    InfoBar,
    InfoBarPosition,
    CardWidget,
    TitleLabel,
    FluentIcon,
    SmoothScrollArea,
    ComboBox,
    BodyLabel,
    CaptionLabel,
    LineEdit,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject

from app.services import adb_service
from app.components.log_widget import LogWidget


import urllib3

# Suppress insecure request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


ROOT_MANAGERS: list[dict] = [
    {
        "name": "SukiSU",
        "url": "https://gitee.com/gyah/Tobatools-config-file/releases/download/1/SukiSU_v4.1.2_40545-release.apk",
        "pkg": "com.sukisu.ultra",
    },
    {
        "name": "KernelSU",
        "url": "https://gitee.com/gyah/Tobatools-config-file/releases/download/1/KernelSU_v3.1.0_32302-release.apk",
        "pkg": "me.weishu.kernelsu",
    },
    {
        "name": "KernelSU Next",
        "url": "https://gitee.com/gyah/Tobatools-config-file/releases/download/1/KernelSU_Next_v3.1.0_33024-release.apk",
        "pkg": "me.weishu.kernelsu",
    },
    {
        "name": "Kitsune Magisk",
        "url": "https://gitee.com/gyah/Tobatools-config-file/releases/download/1/Kitsune%20Magisk%20v27.2.apk",
        "pkg": "com.topjohnwu.magisk",
    },
    {
        "name": "Magisk",
        "url": "https://gitee.com/gyah/Tobatools-config-file/releases/download/1/Magisk-v30.7%20(1).apk",
        "pkg": "com.topjohnwu.magisk",
    },
    {
        "name": "MKSU",
        "url": "https://gitee.com/gyah/Tobatools-config-file/releases/download/1/MKSU.apk",
        "pkg": "me.weishu.kernelsu",
    },
    {
        "name": "FolkPatch",
        "url": "https://gitee.com/gyah/Tobatools-config-file/releases/download/1/FolkPatch_114024_4.0.0_on_main-release.apk",
        "pkg": "",
    },
    {
        "name": "APatch",
        "url": "https://gitee.com/gyah/Tobatools-config-file/releases/download/1/APatch.apk",
        "pkg": "",
    },
    {
        "name": "Magisk Canary(alpha)",
        "url": "https://gitee.com/gyah/Tobatools-config-file/releases/download/1/e8a58776-alpha-30700.apk",
        "pkg": "com.topjohnwu.magisk",
    },
]


class _GuidedRootWorker(QObject):
    log = Signal(str)
    finished = Signal(int)
    stage = Signal(str)
    step_start = Signal(str, str)
    step_finish = Signal(str, bool, str)

    def __init__(
        self,
        *,
        boot_img: str,
        manager_name: str,
        manager_url: str,
        manager_pkg: str,
        flash_partition: str,
        adb_path: str,
        fastboot_path: str,
    ):
        super().__init__()
        self.boot_img = str(boot_img or "").strip()
        self.manager_name = str(manager_name or "").strip()
        self.manager_url = str(manager_url or "").strip()
        self.manager_pkg = str(manager_pkg or "").strip()
        self.flash_partition = str(flash_partition or "boot").strip() or "boot"
        self.adb = adb_path
        self.fastboot = fastboot_path
        self.work_dir = Path("root_work")
        self._stop_flag = False

    def _run_cmd(self, cmd: List[str], timeout=None, *, quiet: bool = False) -> Tuple[int, str]:
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
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            out_lines = []
            while True:
                if proc.stdout is None:
                    break
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    s = line.strip()
                    if s and not quiet:
                        self.log.emit(s)
                    out_lines.append(s)
                    
            return proc.poll(), "\n".join(out_lines)
        except Exception as e:
            return -1, str(e)

    def run(self):
        import uuid
        try:
            self.work_dir.mkdir(exist_ok=True)
            boot_path = Path(self.boot_img)
            if not boot_path.exists() or not boot_path.is_file():
                self.log.emit("boot.img 路径无效")
                self.finished.emit(-1)
                return

            mode, serial = adb_service.detect_connection_mode()
            if mode != 'system' or not serial:
                self.log.emit("请确保手机在系统模式并连接 ADB")
                self.finished.emit(-1)
                return

            # 1) 下载管理器
            sid_dl = str(uuid.uuid4())
            self.stage.emit("download_apk")
            self.step_start.emit(sid_dl, f"下载管理器 ({self.manager_name})")
            
            apk_local = self.work_dir / "root_manager.apk"
            # self.log.emit(f"下载管理器：{self.manager_name}")
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
                resp = requests.get(self.manager_url, stream=True, verify=False, headers=headers, timeout=30)
                resp.raise_for_status()
                with open(apk_local, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if self._stop_flag:
                            self.step_finish.emit(sid_dl, False, "已取消")
                            self.log.emit("已取消")
                            self.finished.emit(-2)
                            return
                        if chunk:
                            f.write(chunk)
                # self.log.emit("APK 下载完成")
                self.step_finish.emit(sid_dl, True, "")
            except Exception as e:
                self.log.emit(f"APK 下载失败：{e}")
                self.step_finish.emit(sid_dl, False, str(e))
                self.finished.emit(-1)
                return

            # 2) 推送 boot.img + APK
            sid_push = str(uuid.uuid4())
            self.stage.emit("push_files")
            self.step_start.emit(sid_push, "推送文件到手机")
            
            remote_dir = "/sdcard/Download/tobatools_root"
            remote_boot = remote_dir + "/boot.img"
            remote_apk = remote_dir + "/root_manager.apk"
            # self.log.emit("推送文件到手机 Download...")
            self._run_cmd([self.adb, "-s", serial, "shell", "mkdir", "-p", remote_dir])
            code, out = self._run_cmd([self.adb, "-s", serial, "push", str(boot_path), remote_boot])
            if code != 0:
                self.log.emit(f"boot.img 推送失败：{out}")
                self.step_finish.emit(sid_push, False, "boot.img 推送失败")
                self.finished.emit(-1)
                return
            code, out = self._run_cmd([self.adb, "-s", serial, "push", str(apk_local), remote_apk])
            if code != 0:
                self.log.emit(f"APK 推送失败：{out}")
                self.step_finish.emit(sid_push, False, "APK 推送失败")
                self.finished.emit(-1)
                return
            # self.log.emit(f"已推送到：{remote_dir}")
            self.step_finish.emit(sid_push, True, "")

            # 3) 安装 APK（静默失败不阻断）
            sid_install = str(uuid.uuid4())
            self.stage.emit("install_apk")
            self.step_start.emit(sid_install, "安装 Root 管理器")
            
            self.log.emit("尝试安装管理器（静默安装可能在部分机型失败）")
            self.log.emit("================ 重要提示 ================")
            self.log.emit("请观察手机屏幕，确认是否弹出安装界面")
            self.log.emit("如未弹出安装界面，请手动在文件管理器中安装：")
            self.log.emit("/sdcard/Download/tobatools_root/root_manager.apk")
            self.log.emit("========================================")
            self._run_cmd([self.adb, "-s", serial, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", f"file://{remote_apk}", "-t", "application/vnd.android.package-archive"])
            # attempt silent install as well
            self._run_cmd([self.adb, "-s", serial, "install", "-r", str(apk_local)])
            self.step_finish.emit(sid_install, True, "请求已发送")

            # 4) 轮询检测安装成功（如果提供了包名）
            self.stage.emit("wait_install")
            if self.manager_pkg:
                sid_check_install = str(uuid.uuid4())
                self.step_start.emit(sid_check_install, f"检测安装 ({self.manager_pkg})")
                # self.log.emit(f"检测安装：{self.manager_pkg}")
                installed = False
                for i in range(60):
                    if self._stop_flag:
                        self.step_finish.emit(sid_check_install, False, "取消")
                        self.log.emit("已取消")
                        self.finished.emit(-2)
                        return
                    code, out = self._run_cmd([self.adb, "-s", serial, "shell", "pm", "path", self.manager_pkg], quiet=True)
                    if code == 0 and (out or "").strip().startswith("package:"):
                        installed = True
                        break
                    time.sleep(2)
                if installed:
                    # self.log.emit("已检测到管理器安装成功")
                    self.step_finish.emit(sid_check_install, True, "")
                else:
                    self.log.emit("未检测到安装成功，请手动完成安装")
                    self.step_finish.emit(sid_check_install, True, "未检测到，请手动确认")
            else:
                self.log.emit("未提供管理器包名：将跳过自动检测，需你手动确认安装")

            # 5) 打开管理器（如果提供了包名）
            self.stage.emit("open_manager")
            if self.manager_pkg:
                self.log.emit("尝试打开管理器...若未打开，请手动打开")
                self._run_cmd([self.adb, "-s", serial, "shell", "monkey", "-p", self.manager_pkg, "-c", "android.intent.category.LAUNCHER", "1"])
            
            sid_patch = str(uuid.uuid4())
            self.step_start.emit(sid_patch, "等待用户修补 Boot 镜像")
            self.log.emit("================ 关键操作 ================")
            self.log.emit("请在 Root 管理器中选择：‘选择并修补 boot’")
            self.log.emit("并选择以下文件：")
            self.log.emit("Download/tobatools_root/boot.img")
            self.log.emit("修补完成后，工具箱会自动进行下一步流程，无需操作手机。")
            self.log.emit("========================================")

            # 6) 轮询 Download 新增 .img
            self.stage.emit("wait_patched")
            # self.log.emit("开始轮询手机 Download 查找新增镜像（不刷屏输出）...")

            # 彻底废弃所有复杂的 shell 命令，全盘用 Python 原生解析
            # 用最基础的 adb shell ls -1 <dir> 列出文件名，再按需查 stat
            def _get_img_files() -> dict:
                files = {}
                for d in ["/sdcard/Download", "/sdcard/Download/tobatools_root"]:
                    code, out = self._run_cmd([self.adb, "-s", serial, "shell", "ls", "-1", d], quiet=True)
                    if code != 0 or not out:
                        continue
                    for line in out.splitlines():
                        filename = line.strip()
                        if not filename or "No such file" in filename or "Permission denied" in filename:
                            continue
                        if filename.endswith(".img") or filename.endswith(".img.gz"):
                            full_path = f"{d}/{filename}"
                            if full_path == "/sdcard/Download/tobatools_root/boot.img":
                                continue
                            
                            # 获取大小和修改时间作为签名，避免同名覆盖检测不到
                            sc, sout = self._run_cmd(
                                [self.adb, "-s", serial, "shell", f"stat -c '%Y %s' '{full_path}' 2>/dev/null || stat -f '%m %z' '{full_path}' 2>/dev/null || echo ''"],
                                quiet=True
                            )
                            sig = sout.strip() if sc == 0 else ""
                            files[full_path] = sig
                return files

            baseline_map = _get_img_files()
            # try:
            #     print("[root][poll] baseline_count=", len(baseline_map))
            #     for p in sorted(list(baseline_map.keys()))[:10]:
            #         print(f"[root][poll] baseline: {p} -> {baseline_map[p]}")
            # except Exception:
            #     pass
            patched_remote = ""
            for i in range(900):
                if self._stop_flag:
                    self.step_finish.emit(sid_patch, False, "取消")
                    self.log.emit("已取消")
                    self.finished.emit(-2)
                    return

                cur_map = _get_img_files()

                new_paths = [p for p in cur_map.keys() if p not in baseline_map]
                changed_paths = [p for p in cur_map.keys() if (p in baseline_map and cur_map[p] != baseline_map[p])]

                # try:
                #     if i % 5 == 0:
                #         print(
                #             "[root][poll] tick=", i,
                #             "cur_count=", len(cur_map),
                #             "new=", len(new_paths),
                #             "changed=", len(changed_paths),
                #         )
                #         if new_paths:
                #             for p in sorted(new_paths)[:5]:
                #                 print("[root][poll] new:", p)
                #         if changed_paths:
                #             for p in sorted(changed_paths)[:5]:
                #                 print("[root][poll] changed:", p)
                # except Exception:
                #     pass

                cand = ""
                if new_paths:
                    cand = sorted(new_paths)[-1]
                elif changed_paths:
                    cand = sorted(changed_paths)[-1]

                if cand:
                    # try:
                    #     print("[root][poll] picked:", cand)
                    # except Exception:
                    #     pass
                    patched_remote = cand
                    break
                time.sleep(2)
            if not patched_remote:
                self.step_finish.emit(sid_patch, False, "超时未检测到镜像")
                self.log.emit("超时：未检测到新增 .img")
                self.finished.emit(-1)
                return
            self.step_finish.emit(sid_patch, True, f"检测到 {Path(patched_remote).name}")
            # self.log.emit(f"检测到修补镜像：{patched_remote}")

            # 7) 拉取到电脑
            sid_pull = str(uuid.uuid4())
            self.stage.emit("pull_patched")
            self.step_start.emit(sid_pull, "拉取修补镜像")
            
            patched_local = self.work_dir / Path(patched_remote).name
            # self.log.emit("正在拉取镜像到电脑...")
            code, out = self._run_cmd([self.adb, "-s", serial, "pull", patched_remote, str(patched_local)])
            if code != 0 or not patched_local.exists():
                self.step_finish.emit(sid_pull, False, f"拉取失败: {out}")
                self.log.emit(f"拉取失败：{out}")
                self.finished.emit(-1)
                return

            flash_img = patched_local
            try:
                if str(patched_local).lower().endswith(".img.gz"):
                    out_img = self.work_dir / (patched_local.stem)
                    self.log.emit("检测到 .img.gz，正在解压...")
                    with gzip.open(patched_local, 'rb') as f_in, open(out_img, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                    if out_img.exists():
                        flash_img = out_img
                        self.log.emit(f"解压完成：{out_img}")
            except Exception as e:
                self.log.emit(f"解压失败（将尝试直接刷写原文件）：{e}")

            # self.log.emit(f"已拉取：{patched_local}")
            self.step_finish.emit(sid_pull, True, "")

            # 8) 重启 bootloader 并刷写
            sid_flash = str(uuid.uuid4())
            self.stage.emit("flash")
            self.step_start.emit(sid_flash, f"刷入修补镜像 ({self.flash_partition})")
            
            self.log.emit("重启至 bootloader...")
            self._run_cmd([self.adb, "-s", serial, "reboot", "bootloader"])
            self.log.emit("已进入 bootloader，额外等待 15 秒以确保 fastboot 连接稳定...")
            time.sleep(15)
            # self.log.emit(f"刷写分区：{self.flash_partition}")
            code, out = self._run_cmd([self.fastboot, "flash", self.flash_partition, str(flash_img)])
            if code != 0:
                self.step_finish.emit(sid_flash, False, "刷写失败")
                self.log.emit(f"刷写失败：{out}")
                self.finished.emit(-1)
                return
            self.step_finish.emit(sid_flash, True, "")

            # 9) 重启
            sid_reboot = str(uuid.uuid4())
            self.stage.emit("reboot")
            self.step_start.emit(sid_reboot, "重启系统")
            # self.log.emit("刷写成功，正在重启系统...")
            self._run_cmd([self.fastboot, "reboot"])
            self.step_finish.emit(sid_reboot, True, "")
            
            self.log.emit("Root 流程完成（后续请在管理器里按需设置/授予权限）")
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
        self._thread: QThread | None = None
        self._worker: _GuidedRootWorker | None = None
        self._build_ui()
        self._refresh_device_info()

    def closeEvent(self, event):
        try:
            self.cleanup()
        except Exception:
            pass
        try:
            return super().closeEvent(event)
        except Exception:
            try:
                event.accept()
            except Exception:
                pass

    def _resolve_bin(self, name: str) -> str:
        base = Path(__file__).resolve().parent
        tool = (base / ".." / ".." / "bin" / (name + ".exe")).resolve()
        if tool.exists():
            return str(tool)
        return name

    def _build_ui(self):
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
        self.layout.setContentsMargins(32, 32, 32, 32)
        self.layout.setSpacing(24)

        main_h_layout = QHBoxLayout()
        main_h_layout.setSpacing(24)
        
        left_col = QVBoxLayout()
        left_col.setSpacing(24)
        
        self._build_status_card(left_col)
        self._build_options_card(left_col)
        self._build_action_card(left_col)
        left_col.addStretch(1)
        
        right_col = QVBoxLayout()
        right_col.setSpacing(24)
        self._build_log_card(right_col)
        
        left_w = QWidget()
        left_w.setLayout(left_col)
        right_w = QWidget()
        right_w.setLayout(right_col)
        
        main_h_layout.addWidget(left_w, 4)
        main_h_layout.addWidget(right_w, 5)
        
        self.layout.addLayout(main_h_layout)

    def _build_status_card(self, parent_layout):
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        head_lay = QHBoxLayout()
        icon = QLabel("📱")
        icon.setStyleSheet("font-size: 20px;")
        title = QLabel("设备信息")
        title.setStyleSheet("font-size: 17px; font-weight: bold;")
        head_lay.addWidget(icon)
        head_lay.addWidget(title)
        head_lay.addStretch(1)
        lay.addLayout(head_lay)

        status_row = QHBoxLayout()
        self.lbl_dev = QLabel("未检测到设备")
        self.lbl_dev.setStyleSheet("font-size: 15px; font-weight: 500;")
        self.lbl_suggest = QLabel("分区建议：-")
        self.lbl_suggest.setStyleSheet("font-size: 14px; color: #86909c;")
        self.lbl_suggest.setWordWrap(True)
        
        info_lay = QVBoxLayout()
        info_lay.setSpacing(4)
        info_lay.addWidget(self.lbl_dev)
        info_lay.addWidget(self.lbl_suggest)
        
        btn_refresh = PushButton(FluentIcon.SYNC, "刷新状态")
        btn_refresh.setFixedHeight(32)
        btn_refresh.clicked.connect(self._refresh_device_info)
        
        status_row.addLayout(info_lay, 1)
        status_row.addWidget(btn_refresh)
        
        lay.addLayout(status_row)
        parent_layout.addWidget(card)

    def _build_options_card(self, parent_layout):
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        head_lay = QHBoxLayout()
        icon = QLabel("⚙️")
        icon.setStyleSheet("font-size: 20px;")
        title = QLabel("Root 设置")
        title.setStyleSheet("font-size: 17px; font-weight: bold;")
        head_lay.addWidget(icon)
        head_lay.addWidget(title)
        head_lay.addStretch(1)
        lay.addLayout(head_lay)

        # Image Selection
        row_boot = QHBoxLayout()
        row_boot.setSpacing(12)
        self.edt_boot = LineEdit()
        self.edt_boot.setReadOnly(True)
        self.edt_boot.setPlaceholderText("选择原版 boot.img / init_boot.img")
        self.edt_boot.setFixedHeight(36)
        btn_pick = PushButton(FluentIcon.FOLDER, "浏览镜像")
        btn_pick.setFixedHeight(36)
        btn_pick.clicked.connect(self._pick_boot)
        row_boot.addWidget(self.edt_boot, 1)
        row_boot.addWidget(btn_pick)
        lay.addLayout(row_boot)

        # Manager Selection
        row_mgr = QHBoxLayout()
        row_mgr.setSpacing(12)
        self.combo_mgr = ComboBox()
        self.combo_mgr.addItems([m["name"] for m in ROOT_MANAGERS])
        self.combo_mgr.setFixedHeight(36)
        self.combo_mgr.currentIndexChanged.connect(self._on_mgr_changed)
        
        self.edt_pkg = LineEdit()
        self.edt_pkg.setPlaceholderText("管理器包名")
        self.edt_pkg.setFixedHeight(36)
        
        row_mgr.addWidget(self.combo_mgr, 1)
        row_mgr.addWidget(self.edt_pkg, 1)
        lay.addLayout(row_mgr)

        self._on_mgr_changed(0)

        # Partition Selection
        row_part = QHBoxLayout()
        row_part.setSpacing(12)
        part_label = QLabel("刷写分区：")
        part_label.setStyleSheet("font-size: 14px; font-weight: 500;")
        self.combo_part = ComboBox()
        self.combo_part.addItems(["boot", "init_boot", "vendor_boot"])
        self.combo_part.setFixedHeight(36)
        row_part.addWidget(part_label)
        row_part.addWidget(self.combo_part, 1)
        lay.addLayout(row_part)

        parent_layout.addWidget(card)

    def _build_action_card(self, parent_layout):
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 24, 24, 24)
        
        self.btn_start = PrimaryPushButton(FluentIcon.PLAY, "开始 Root")
        self.btn_start.setFixedHeight(44)
        self.btn_start.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.btn_start.clicked.connect(self._start)
        
        self.btn_cancel = PushButton(FluentIcon.CLOSE, "终止任务")
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        
        lay.addWidget(self.btn_start)
        lay.addSpacing(12)
        lay.addWidget(self.btn_cancel)
        
        parent_layout.addWidget(card)

    def _build_log_card(self, parent_layout):
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(16)

        head_lay = QHBoxLayout()
        icon = QLabel("📝")
        icon.setStyleSheet("font-size: 20px;")
        title = QLabel("执行日志")
        title.setStyleSheet("font-size: 17px; font-weight: bold;")
        head_lay.addWidget(icon)
        head_lay.addWidget(title)
        head_lay.addStretch(1)
        
        self.btn_clear_log = PushButton(FluentIcon.DELETE, "清空")
        self.btn_clear_log.setFixedHeight(30)
        self.btn_clear_log.clicked.connect(lambda: self.log.clear_log())
        head_lay.addWidget(self.btn_clear_log)
        
        lay.addLayout(head_lay)

        self.log = LogWidget()
        lay.addWidget(self.log, 1)
        parent_layout.addWidget(card, 1)

    def _start(self):
        if self._thread and self._thread.isRunning():
            InfoBar.info("提示", "已有任务在执行中", parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return

        boot_img = (self.edt_boot.text() or "").strip()
        if not boot_img:
            InfoBar.warning("提示", "请先选择 boot.img", parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return
        if not Path(boot_img).exists():
            InfoBar.warning("提示", "boot.img 路径不存在", parent=self, position=InfoBarPosition.TOP, isClosable=True)
            return

        idx = int(self.combo_mgr.currentIndex())
        mgr = ROOT_MANAGERS[idx]
        mgr_name = mgr.get("name", "")
        mgr_url = mgr.get("url", "")
        mgr_pkg = (self.edt_pkg.text() or "").strip()
        part = str(self.combo_part.currentText() or "boot").strip() or "boot"

        self.log.clear_log()
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        self._thread = QThread(self)
        self._worker = _GuidedRootWorker(
            boot_img=boot_img,
            manager_name=mgr_name,
            manager_url=mgr_url,
            manager_pkg=mgr_pkg,
            flash_partition=part,
            adb_path=self._adb,
            fastboot_path=self._fastboot,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self.log.append_log)
        self._worker.step_start.connect(self.log.start_step)
        self._worker.step_finish.connect(self.log.finish_step)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        InfoBar.info("开始", "Root 向导已启动，请按日志提示操作", parent=self, position=InfoBarPosition.TOP, isClosable=True)
        self._thread.start()

    def _on_finished(self, code):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        if code == 0:
            InfoBar.success("完成", "Root 流程执行完毕", parent=self, position=InfoBarPosition.TOP)
        elif code == -2:
            InfoBar.info("已取消", "任务已取消", parent=self, position=InfoBarPosition.TOP, isClosable=True)
        else:
            InfoBar.error("失败", "Root 流程遇到错误，请查看日志", parent=self, position=InfoBarPosition.TOP)

    def _on_thread_finished(self):
        self._thread = None
        self._worker = None

    def _cancel(self):
        try:
            if self._worker:
                self._worker.stop()
        except Exception:
            pass

        try:
            if self._thread and self._thread.isRunning():
                self._thread.quit()
        except Exception:
            pass

    def _pick_boot(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 boot 镜像", "", "镜像 (*.img);;所有文件 (*.*)")
        if path:
            self.edt_boot.setText(path)

    def _on_mgr_changed(self, index: int):
        try:
            m = ROOT_MANAGERS[int(index)]
            pkg = str(m.get("pkg", "") or "")
            if not (self.edt_pkg.text() or "").strip():
                self.edt_pkg.setText(pkg)
        except Exception:
            pass

    def _refresh_device_info(self):
        try:
            mode, serial = adb_service.detect_connection_mode()
            if mode != 'system' or not serial:
                self.lbl_dev.setText("未检测到系统模式设备")
                self.lbl_dev.setStyleSheet("font-size: 15px; font-weight: bold; color: #ff4d4f;")
                self.lbl_suggest.setText("分区建议：-")
                return

            brand = (adb_service.adb_shell_serial(serial, "getprop ro.product.brand", timeout=6) or "").strip()
            model = (adb_service.adb_shell_serial(serial, "getprop ro.product.model", timeout=6) or "").strip()
            android = (adb_service.adb_shell_serial(serial, "getprop ro.build.version.release", timeout=6) or "").strip()
            rom = (adb_service.adb_shell_serial(serial, "getprop ro.build.display.id", timeout=6) or "").strip()
            kernel = (adb_service.adb_shell_serial(serial, "uname -r", timeout=6) or "").strip()

            self.lbl_dev.setText(f"{brand} {model} | Android {android} | {rom}\n内核: {kernel}")
            self.lbl_dev.setStyleSheet("font-size: 15px; font-weight: 500; color: #00b42a;")

            suggested = "boot"
            try:
                k0 = kernel.split('-', 1)[0]
                parts = k0.split('.')
                major = int(parts[0]) if len(parts) > 0 else 0
                minor = int(parts[1]) if len(parts) > 1 else 0
                if major > 5 or (major == 5 and minor >= 15):
                    suggested = "init_boot"
            except Exception:
                suggested = "boot"

            self.lbl_suggest.setText(f"分区建议：内核 < 5.15 推荐 boot；内核 ≥ 5.15 推荐 init_boot\n当前建议：{suggested}")
            try:
                if suggested in ("boot", "init_boot", "vendor_boot"):
                    self.combo_part.setCurrentText(suggested)
            except Exception:
                pass
        except Exception:
            try:
                self.lbl_dev.setText("获取设备信息失败")
                self.lbl_dev.setStyleSheet("font-size: 15px; font-weight: bold; color: #ff4d4f;")
            except Exception:
                pass

    def cleanup(self):
        try:
            if self._worker:
                self._worker.stop()
        except Exception:
            pass
        try:
            if self._thread and self._thread.isRunning():
                self._thread.quit()
        except Exception:
            pass
