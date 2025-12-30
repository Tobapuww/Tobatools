"""
压缩包刷机逻辑
负责解压 ZIP/7z 固件包和处理 payload.bin
"""
import os
import subprocess
import shutil
from pathlib import Path
from typing import List, Callable, Optional


class ArchiveFlashLogic:
    """压缩包解压和处理逻辑"""
    
    def __init__(self, log_callback: Callable[[str], None]):
        """
        初始化
        :param log_callback: 日志回调函数
        """
        self.log = log_callback
        self._stop_flag = False
    
    def stop(self):
        """停止当前操作"""
        self._stop_flag = True
    
    def _resolve_tool(self, tool_name: str, candidates: List[Path]) -> str:
        """解析工具路径"""
        for p in candidates:
            if p.exists():
                return str(p)
        return tool_name
    
    def _run_cmd(self, cmd: List[str], desc: str, show_output: bool = True) -> bool:
        """执行命令"""
        try:
            if not show_output:
                if "Payload" in desc:
                    self.log("正在解包 payload.bin，请稍后...")
                else:
                    self.log(f"正在{desc}，请稍后...")
            else:
                self.log(f"执行 {desc} ...")
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            for line in process.stdout:
                if self._stop_flag:
                    process.terminate()
                    return False
                line = line.strip()
                if line and show_output:
                    self.log(line)
            
            ret = process.wait()
            if ret != 0:
                self.log(f"{desc} 失败，退出码: {ret}")
                return False
            return True
        except Exception as e:
            self.log(f"{desc} 启动失败: {e}")
            return False
    
    def extract_and_process(self, archive_path: str) -> Optional[str]:
        """
        解压固件包并处理
        :param archive_path: 压缩包路径
        :return: 成功返回镜像目录路径，失败返回 None
        """
        try:
            base_dir = Path.cwd()
            unpack_dir = base_dir / "unpack"
            
            self.log(f"准备解压目录: {unpack_dir}")
            if unpack_dir.exists():
                try:
                    shutil.rmtree(unpack_dir)
                except Exception as e:
                    self.log(f"清理旧目录失败: {e}")
                    return None
            unpack_dir.mkdir(parents=True, exist_ok=True)
            
            # 解析 7z 工具路径
            bin_dir = Path(__file__).resolve().parents[2] / 'bin'
            tool_7z = self._resolve_tool('7z', [bin_dir / '7z.exe', bin_dir / '7za.exe'])
            
            # 解压压缩包
            self.log(f"正在解压: {os.path.basename(archive_path)} ...")
            cmd_7z = [tool_7z, 'x', archive_path, f'-o{unpack_dir}', '-y']
            if not self._run_cmd(cmd_7z, "7z 解压"):
                return None
            
            payload_path = unpack_dir / "payload.bin"
            images_dir = unpack_dir / "images"
            
            # 处理 payload.bin
            if payload_path.exists():
                self.log("检测到 payload.bin，准备解包...")
                tool_dumper = self._resolve_tool('payload-dumper-go', [
                    bin_dir / 'payload-dumper-go.exe',
                    bin_dir / 'payload-dumper.exe'
                ])
                
                images_dir.mkdir(exist_ok=True)
                cmd_dump = [tool_dumper, '-o', str(images_dir), str(payload_path)]
                
                if not self._run_cmd(cmd_dump, "Payload 解包", show_output=False):
                    return None
                
                if not any(images_dir.glob("*.img")):
                    self.log("错误: Payload 解包后未发现 .img 文件")
                    return None
                
                return str(images_dir)
            
            # 检查是否已有 images 文件夹
            elif images_dir.exists() and any(images_dir.glob("*.img")):
                self.log("检测到 images 文件夹，直接使用...")
                return str(images_dir)
            
            # 检查解压根目录是否有镜像文件
            else:
                if any(unpack_dir.glob("*.img")):
                    self.log("在解压根目录检测到镜像文件，移动到 images 文件夹...")
                    images_dir.mkdir(exist_ok=True)
                    for img in unpack_dir.glob("*.img"):
                        try:
                            shutil.move(str(img), str(images_dir / img.name))
                        except Exception as e:
                            self.log(f"移动 {img.name} 失败: {e}")
                    
                    if any(images_dir.glob("*.img")):
                        return str(images_dir)
                    else:
                        self.log("错误: 移动镜像文件后仍未找到有效镜像")
                        return None
                else:
                    self.log("错误: 解压后未找到 payload.bin 或有效的镜像文件")
                    return None
        
        except Exception as e:
            self.log(f"解压流程发生异常: {e}")
            return None
