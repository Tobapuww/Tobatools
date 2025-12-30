"""
小米线刷脚本逻辑
执行小米官方线刷包中的 flash_all.bat 脚本
"""
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional


class MiFlashLogic:
    """小米线刷脚本执行逻辑"""
    
    def __init__(self, log_callback: Callable[[str], None]):
        """
        初始化
        :param log_callback: 日志回调函数
        """
        self.log = log_callback
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
    
    def find_flash_script(self, folder_path: str) -> Optional[str]:
        """
        在文件夹中查找线刷脚本
        :param folder_path: 线刷包文件夹路径
        :return: 找到的脚本路径，未找到返回 None
        """
        folder = Path(folder_path)
        
        # 按优先级查找脚本
        scripts = [
            'flash_all.bat',
            'flash_all_lock.bat',
            'flash_all_except_storage.bat'
        ]
        
        for script_name in scripts:
            script_path = folder / script_name
            if script_path.exists():
                return str(script_path)
        
        return None
    
    def execute_flash_script(self, folder_path: str, script_name: str = None) -> bool:
        """
        执行线刷脚本
        :param folder_path: 线刷包文件夹路径
        :param script_name: 脚本名称，None 则自动查找
        :return: 成功返回 True，失败返回 False
        """
        try:
            folder = Path(folder_path)
            
            # 查找脚本
            if script_name:
                script_path = folder / script_name
                if not script_path.exists():
                    self.log(f"错误: 未找到脚本 {script_name}")
                    return False
            else:
                script_path = self.find_flash_script(folder_path)
                if not script_path:
                    self.log("错误: 未找到任何线刷脚本")
                    self.log("支持的脚本: flash_all.bat, flash_all_lock.bat, flash_all_except_storage.bat")
                    return False
                script_path = Path(script_path)
            
            self.log("=" * 50)
            self.log(f"准备执行: {script_path.name}")
            self.log(f"工作目录: {folder_path}")
            self.log("=" * 50)
            
            # 脚本说明
            if 'lock' in script_path.name.lower():
                self.log("注意: 此脚本会重新锁定 Bootloader")
            elif 'except_storage' in script_path.name.lower():
                self.log("注意: 此脚本会保留用户数据")
            else:
                self.log("注意: 此脚本会清除所有数据")
            
            self.log("")
            self.log("开始执行脚本...")
            
            # 执行脚本
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            self._process = subprocess.Popen(
                [str(script_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='gbk',  # 小米脚本通常使用 GBK 编码
                errors='replace',
                cwd=str(folder),  # 在线刷包目录中执行
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # 实时输出日志
            for line in self._process.stdout:
                if self._stop_flag:
                    self._process.terminate()
                    self.log("用户取消了刷机")
                    return False
                
                line = line.strip()
                if line:
                    self.log(line)
            
            ret = self._process.wait()
            
            self.log("")
            self.log("=" * 50)
            if ret == 0:
                self.log("脚本执行完成！")
                self.log("设备将自动重启...")
            else:
                self.log(f"脚本执行失败，退出码: {ret}")
                self.log("请检查:")
                self.log("1. 设备是否处于 Fastboot 模式")
                self.log("2. USB 驱动是否正确安装")
                self.log("3. 线刷包是否完整")
            self.log("=" * 50)
            
            return ret == 0
        
        except Exception as e:
            self.log(f"执行脚本时发生异常: {e}")
            return False
        finally:
            self._process = None
    
    def list_available_scripts(self, folder_path: str) -> list:
        """
        列出文件夹中所有可用的线刷脚本
        :param folder_path: 线刷包文件夹路径
        :return: 脚本名称列表
        """
        folder = Path(folder_path)
        scripts = []
        
        for bat_file in folder.glob('*.bat'):
            if 'flash' in bat_file.name.lower():
                scripts.append(bat_file.name)
        
        return scripts
