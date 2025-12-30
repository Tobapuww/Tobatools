"""
ADB Sideload 刷机逻辑
通过 adb sideload 命令刷入 OTA 包
"""
import os
import subprocess
from pathlib import Path
from typing import Callable


class SideloadFlashLogic:
    """ADB Sideload 刷机逻辑"""
    
    def __init__(self, log_callback: Callable[[str], None], adb_path: str = None):
        """
        初始化
        :param log_callback: 日志回调函数
        :param adb_path: ADB 可执行文件路径
        """
        self.log = log_callback
        self._adb_path = adb_path or self._resolve_adb()
        self._stop_flag = False
        self._process = None
    
    def stop(self):
        """停止当前操作"""
        self._stop_flag = True
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except Exception:
                pass
    
    def _resolve_adb(self) -> str:
        """解析 ADB 路径"""
        try:
            from app.services import adb_service
            adb_bin = getattr(adb_service, 'ADB_BIN', None)
            if adb_bin and adb_bin.exists():
                return str(adb_bin)
        except Exception:
            pass
        return 'adb'
    
    def check_device_in_sideload(self) -> tuple[bool, str]:
        """
        检查设备是否处于 sideload 模式
        :return: (是否处于sideload模式, 状态描述)
        """
        try:
            from app.services import adb_service
            
            mode, serial = adb_service.detect_connection_mode()
            
            # 根据检测到的模式返回结果
            if mode == "sideload":
                return True, f"设备处于 Sideload 模式 (序列号: {serial})"
            elif mode == "system":
                return False, "设备处于普通 ADB 模式（需要进入 Recovery sideload）"
            elif mode == "fastbootd":
                return False, "设备处于 FastbootD 模式（请重启到 Recovery）"
            elif mode == "bootloader":
                return False, "设备处于 Bootloader 模式（请重启到 Recovery）"
            elif mode == "offline":
                return False, "设备离线或未授权（请在手机上允许 USB 调试）"
            elif mode == "none":
                return False, "未检测到任何设备"
            else:
                return False, f"设备状态未知: {mode}"
        except Exception as e:
            return False, f"检查设备状态失败: {e}"
    
    def flash_ota(self, ota_path: str) -> bool:
        """
        通过 sideload 刷入 OTA 包
        :param ota_path: OTA 包路径
        :return: 成功返回 True，失败返回 False
        """
        try:
            # 检查文件是否存在
            if not os.path.isfile(ota_path):
                self.log(f"错误: 文件不存在: {ota_path}")
                return False
            
            # 检查设备是否处于 sideload 模式
            self.log("检查设备状态...")
            is_sideload, status_msg = self.check_device_in_sideload()
            
            if not is_sideload:
                self.log("=" * 50)
                self.log(f"错误: {status_msg}")
                self.log("=" * 50)
                self.log("")
                self.log("ADB Sideload 刷机要求:")
                self.log("1. 设备必须重启到 Recovery 模式")
                self.log("2. 在 Recovery 菜单中选择 'Apply update from ADB' 或 'ADB Sideload'")
                self.log("3. 设备通过 USB 数据线连接到电脑")
                self.log("4. 确保已安装正确的 USB 驱动")
                self.log("")
                self.log("当前设备状态不符合要求，无法继续刷入。")
                return False
            
            self.log(f"✓ {status_msg}")
            self.log("")
            
            self.log("检测到 sideload 设备，开始刷入...")
            self.log(f"OTA 包: {os.path.basename(ota_path)}")
            
            # 执行 adb sideload
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            self._process = subprocess.Popen(
                [self._adb_path, 'sideload', ota_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # 实时输出日志
            for line in self._process.stdout:
                if self._stop_flag:
                    self._process.terminate()
                    self.log("用户取消了刷入")
                    return False
                
                line = line.strip()
                if line:
                    self.log(line)
            
            ret = self._process.wait()
            
            if ret == 0:
                self.log("=" * 50)
                self.log("OTA 包刷入完成！")
                self.log("设备将自动重启...")
                self.log("=" * 50)
                return True
            else:
                self.log(f"刷入失败，退出码: {ret}")
                return False
        
        except Exception as e:
            self.log(f"刷入过程发生异常: {e}")
            return False
        finally:
            self._process = None
