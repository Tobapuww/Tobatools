import os
import subprocess
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal


def resolve_bin(path_like, fallback_name: str) -> str:
    try:
        if path_like and hasattr(path_like, 'exists') and path_like.exists():
            return str(path_like)
    except Exception:
        pass
    return fallback_name


class ProcWorker(QObject):
    output = Signal(str)
    finished = Signal(int)

    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        code = -1
        proc: Optional[subprocess.Popen] = None
        try:
            popen_kwargs = {}
            try:
                if os.name == 'nt':
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    popen_kwargs = {'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW}
            except Exception:
                pass

            proc = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                **popen_kwargs,
            )
            for line in iter(proc.stdout.readline, ''):
                if self._stop:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break
                self.output.emit(line.rstrip('\r\n'))
            code = proc.wait()
        except FileNotFoundError:
            self.output.emit("未找到可执行文件，请检查工具是否存在。")
        except Exception as e:
            self.output.emit(f"执行失败：{e}")
            try:
                if proc and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        proc.kill()
                        proc.wait()
            except Exception:
                pass
        finally:
            self.finished.emit(code)


class BootFixWorker(QObject):
    log = Signal(str)
    finished = Signal(bool, str)
    step_start = Signal(str, str)
    step_finish = Signal(str, bool, str)

    def __init__(self, adb_path: str, fastboot_path: str, abl_img: str, wait_secs: int = 25):
        super().__init__()
        self.adb_path = adb_path or 'adb'
        self.fastboot_path = fastboot_path or 'fastboot'
        self.abl_img = abl_img
        self.wait_secs = wait_secs

    def _silent_kwargs(self):
        kw = {}
        try:
            if os.name == 'nt':
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                kw = {'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW}
        except Exception:
            pass
        return kw

    def _run_cmd(self, cmd, timeout=120):
        try:
            self.log.emit('执行: ' + ' '.join(cmd))
        except Exception:
            pass
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=timeout,
            **self._silent_kwargs(),
        )
        out = (proc.stdout or '').strip()
        if out:
            for line in out.splitlines():
                self.log.emit(line)

    def run(self):
        try:
            import uuid
            if not os.path.exists(self.abl_img):
                raise RuntimeError(f'未找到修复镜像: {self.abl_img}')
            
            sid_reboot = str(uuid.uuid4())
            self.step_start.emit(sid_reboot, '重启到 Fastboot')
            # self.log.emit('正在重启到 Fastboot (adb reboot fastboot)...')
            self._run_cmd([self.adb_path, 'reboot', 'fastboot'], timeout=30)
            self.step_finish.emit(sid_reboot, True, "")
            
            self.log.emit(f'等待设备进入 Fastboot （约 {self.wait_secs} 秒）...')
            time.sleep(self.wait_secs)
            
            sid_flash_a = str(uuid.uuid4())
            self.step_start.emit(sid_flash_a, '刷写 abl_a')
            # self.log.emit('开始刷写 abl_a ...')
            self._run_cmd([self.fastboot_path, 'flash', 'abl_a', self.abl_img], timeout=120)
            self.step_finish.emit(sid_flash_a, True, "")
            
            sid_flash_b = str(uuid.uuid4())
            self.step_start.emit(sid_flash_b, '刷写 abl_b')
            # self.log.emit('开始刷写 abl_b ...')
            self._run_cmd([self.fastboot_path, 'flash', 'abl_b', self.abl_img], timeout=120)
            self.step_finish.emit(sid_flash_b, True, "")
            
            sid_done = str(uuid.uuid4())
            self.step_start.emit(sid_done, '重启回系统')
            # self.log.emit('重启回系统 ...')
            self._run_cmd([self.fastboot_path, 'reboot'], timeout=30)
            self.step_finish.emit(sid_done, True, "")
            
            self.log.emit('修复已完成，设备正在重启回系统')
            self.finished.emit(True, '修复已完成，设备正在重启回系统')
        except subprocess.CalledProcessError as e:
            msg = (e.stdout or e.stderr or str(e)) if hasattr(e, 'stdout') else str(e)
            self.log.emit(msg)
            self.finished.emit(True, '修复流程已结束')
        except Exception as e:
            self.log.emit(str(e))
            self.finished.emit(True, '修复流程已结束')


class GoogleLockWorker(QObject):
    log = Signal(str)
    finished = Signal(bool, str)
    step_start = Signal(str, str)
    step_finish = Signal(str, bool, str)

    def __init__(self, adb_path: str):
        super().__init__()
        self.adb_path = adb_path or 'adb'

    def run(self):
        try:
            import uuid
            sid_frp = str(uuid.uuid4())
            self.step_start.emit(sid_frp, "执行 FRP 清除 (需Root)")
            # self.log.emit("尝试请求 Root 权限并执行 FRP 清除...")
            dd_cmd = "dd if=/dev/zero of=/dev/block/bootdevice/by-name/frp"
            cmd = [self.adb_path, 'shell', f"su -c '{dd_cmd}'"]

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.log.emit(f"执行: {' '.join(cmd)}")
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )

            output = proc.stdout.strip()
            if output:
                self.log.emit(f"命令输出: {output}")

            if "permission denied" in output.lower() or "not found" in output.lower():
                self.step_finish.emit(sid_frp, False, "权限拒绝或命令未找到")
                raise RuntimeError("执行失败，请确认设备已 Root 并授权 Shell 获取 Root 权限。")
            
            self.step_finish.emit(sid_frp, True, "")

            sid_reboot = str(uuid.uuid4())
            self.step_start.emit(sid_reboot, "重启设备")
            # self.log.emit("正在重启设备...")
            subprocess.run(
                [self.adb_path, 'reboot'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            self.step_finish.emit(sid_reboot, True, "")

            self.finished.emit(True, "移除指令执行完成，设备正在重启。")
        except Exception as e:
            self.log.emit(f"发生错误: {e}")
            self.finished.emit(False, str(e))


class MagiskRemoveModulesWorker(QObject):
    log = Signal(str)
    finished = Signal(bool, str)
    step_start = Signal(str, str)
    step_finish = Signal(str, bool, str)

    def __init__(self, adb_path: str):
        super().__init__()
        self.adb_path = adb_path or 'adb'

    def run(self):
        try:
            import uuid
            sid_remove = str(uuid.uuid4())
            self.step_start.emit(sid_remove, "移除 Magisk 模块")
            # self.log.emit("尝试执行 Magisk 模块移除指令...")
            cmd = [self.adb_path, 'shell', 'Magisk', '--remove-modules']

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.log.emit(f"执行: {' '.join(cmd)}")
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )

            output = proc.stdout.strip()
            if output:
                self.log.emit(f"命令输出: {output}")

            if "not found" in output.lower() or "inaccessible" in output.lower():
                self.step_finish.emit(sid_remove, False, "命令未找到或不可用")
                raise RuntimeError("执行失败，可能是未安装 Magisk 或指令不支持。")
            
            self.step_finish.emit(sid_remove, True, "")

            sid_reboot = str(uuid.uuid4())
            self.step_start.emit(sid_reboot, "重启设备")
            # self.log.emit("正在重启设备...")
            subprocess.run(
                [self.adb_path, 'reboot'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            self.step_finish.emit(sid_reboot, True, "")

            self.finished.emit(True, "指令执行完成，设备正在重启。")
        except Exception as e:
            self.log.emit(f"发生错误: {e}")
            self.finished.emit(False, str(e))
