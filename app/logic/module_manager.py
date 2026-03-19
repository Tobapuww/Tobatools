import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.services import adb_service


@dataclass
class ModuleInfo:
    id: str
    name: str
    version: str
    version_code: str
    author: str
    description: str
    enabled: bool
    removed: bool
    manager: str  # magisk | ksu


class ModuleManager:
    def __init__(self, *, log_callback: Optional[Callable[[str], None]] = None, step_start: Optional[Callable[[str, str], None]] = None, step_finish: Optional[Callable[[str, bool, str], None]] = None):
        self._log = log_callback
        self.step_start = step_start or (lambda _i, _t: None)
        self.step_finish = step_finish or (lambda _i, _s, _m: None)

    def _emit(self, s: str):
        try:
            if self._log is not None:
                self._log(str(s))
        except Exception:
            pass

    def _require_system_serial(self) -> str:
        mode, serial = adb_service.detect_connection_mode()
        if mode != 'system' or not serial:
            raise RuntimeError('请确保设备处于系统模式并已连接 ADB')
        return serial

    def _su(self, serial: str, cmd: str, *, timeout: int = 30) -> str:
        # Use su -c, keep quoting simple by wrapping cmd with double quotes.
        # Note: adb_service will quote the whole string if passed as str.
        return adb_service.adb_shell_serial(serial, f'su -c "{cmd}"', timeout=timeout)

    def detect_manager(self) -> str:
        serial = self._require_system_serial()

        # Prefer KernelSU when both exist, because some KernelSU environments also expose /data/adb/modules
        # which can confuse simple directory probes.
        try:
            out = (self._su(serial, 'command -v ksu >/dev/null 2>&1 && echo ksu || echo', timeout=8) or '').strip()
            if 'ksu' in out:
                return 'ksu'
        except Exception:
            pass

        try:
            out = (self._su(serial, 'command -v ksud >/dev/null 2>&1 && echo ksud || echo', timeout=8) or '').strip()
            if 'ksud' in out:
                return 'ksu'
        except Exception:
            pass

        try:
            out = (self._su(serial, '[ -d /data/adb/ksu/modules ] && echo ksu_dir || echo', timeout=8) or '').strip()
            if 'ksu_dir' in out:
                return 'ksu'
        except Exception:
            pass

        try:
            out = (self._su(serial, 'command -v magisk >/dev/null 2>&1 && echo magisk || echo', timeout=8) or '').strip()
            if 'magisk' in out:
                return 'magisk'
        except Exception:
            pass

        # Fallback by probing directories (Magisk)
        try:
            out = (self._su(serial, '[ -d /data/adb/modules ] && echo magisk_dir || echo', timeout=8) or '').strip()
            if 'magisk_dir' in out:
                return 'magisk'
        except Exception:
            pass

        return 'none'

    def _module_base_dirs(self, manager: str) -> list[str]:
        if manager == 'magisk':
            return ['/data/adb/modules']
        if manager == 'ksu':
            # KernelSU commonly uses /data/adb/ksu/modules; some builds also mirror /data/adb/modules
            return ['/data/adb/ksu/modules', '/data/adb/modules']
        return []

    def list_modules(self) -> list[ModuleInfo]:
        serial = self._require_system_serial()
        manager = self.detect_manager()
        if manager == 'none':
            raise RuntimeError('未检测到 Magisk 或 KernelSU 环境（需要 Root，并允许 Shell 获取 su 权限）')

        modules: dict[str, ModuleInfo] = {}
        for base in self._module_base_dirs(manager):
            try:
                raw = self._su(serial, f'ls -1 {base} 2>/dev/null', timeout=10) or ''
            except Exception:
                continue

            for mid in [x.strip() for x in raw.splitlines() if x.strip()]:
                if mid in ('.', '..'):
                    continue
                if mid in modules:
                    continue

                mdir = f'{base}/{mid}'
                # skip removed modules dir entries that are not dirs
                try:
                    is_dir = (self._su(serial, f'[ -d {mdir} ] && echo d || echo f', timeout=8) or '').strip()
                    if not is_dir.startswith('d'):
                        continue
                except Exception:
                    continue

                # parse module.prop
                name = mid
                version = ''
                version_code = ''
                author = ''
                desc = ''
                try:
                    prop = self._su(serial, f'cat {mdir}/module.prop 2>/dev/null', timeout=10) or ''
                    for line in prop.splitlines():
                        if '=' not in line:
                            continue
                        k, v = line.split('=', 1)
                        k = (k or '').strip()
                        v = (v or '').strip()
                        if k == 'id':
                            pass
                        elif k == 'name':
                            name = v or name
                        elif k == 'version':
                            version = v
                        elif k == 'versionCode':
                            version_code = v
                        elif k == 'author':
                            author = v
                        elif k == 'description':
                            desc = v
                except Exception:
                    pass

                enabled = True
                try:
                    disabled = (self._su(serial, f'[ -f {mdir}/disable ] && echo 1 || echo 0', timeout=8) or '').strip()
                    enabled = (disabled != '1')
                except Exception:
                    enabled = True

                removed = False
                try:
                    rmf = (self._su(serial, f'[ -f {mdir}/remove ] && echo 1 || echo 0', timeout=8) or '').strip()
                    removed = (rmf == '1')
                except Exception:
                    removed = False

                modules[mid] = ModuleInfo(
                    id=mid,
                    name=name,
                    version=version,
                    version_code=version_code,
                    author=author,
                    description=desc,
                    enabled=enabled,
                    removed=removed,
                    manager=manager,
                )

        return sorted(modules.values(), key=lambda x: (x.removed is False, x.enabled is False, x.name.lower(), x.id.lower()))

    def set_enabled(self, module_id: str, enabled: bool) -> None:
        import uuid
        sid = str(uuid.uuid4())
        action = "启用" if enabled else "禁用"
        self.step_start(sid, f"{action}模块: {module_id}")
        
        try:
            serial = self._require_system_serial()
            manager = self.detect_manager()
            if manager == 'none':
                raise RuntimeError('未检测到 Magisk 或 KernelSU')

            base_dirs = self._module_base_dirs(manager)
            if not base_dirs:
                raise RuntimeError('模块目录不可用')

            target = ''
            for base in base_dirs:
                mdir = f'{base}/{module_id}'
                try:
                    ok = (self._su(serial, f'[ -d {mdir} ] && echo 1 || echo 0', timeout=8) or '').strip()
                    if ok == '1':
                        target = mdir
                        break
                except Exception:
                    pass

            if not target:
                raise RuntimeError('未找到模块目录: ' + module_id)

            if enabled:
                # self._emit(f'启用模块: {module_id}')
                self._su(serial, f'rm -f {target}/disable', timeout=20)
            else:
                # self._emit(f'禁用模块: {module_id}')
                self._su(serial, f'touch {target}/disable', timeout=20)
            
            self.step_finish(sid, True, "")
        except Exception as e:
            self.step_finish(sid, False, str(e))
            raise e

    def remove_module(self, module_id: str) -> None:
        import uuid
        sid = str(uuid.uuid4())
        self.step_start(sid, f"移除模块: {module_id}")
        
        try:
            serial = self._require_system_serial()
            manager = self.detect_manager()
            if manager == 'none':
                raise RuntimeError('未检测到 Magisk 或 KernelSU')

            removed = False
            for base in self._module_base_dirs(manager):
                mdir = f'{base}/{module_id}'
                try:
                    ok = (self._su(serial, f'[ -d {mdir} ] && echo 1 || echo 0', timeout=8) or '').strip()
                    if ok != '1':
                        continue
                    # self._emit(f'标记移除模块: {module_id}')
                    self._su(serial, f'touch {mdir}/remove', timeout=20)
                    removed = True
                    break
                except Exception:
                    pass

            if not removed:
                raise RuntimeError('未找到模块目录: ' + module_id)
            
            self.step_finish(sid, True, "")
        except Exception as e:
            self.step_finish(sid, False, str(e))
            raise e

    def undo_remove_module(self, module_id: str) -> None:
        import uuid
        sid = str(uuid.uuid4())
        self.step_start(sid, f"撤销移除: {module_id}")
        
        try:
            serial = self._require_system_serial()
            manager = self.detect_manager()
            if manager == 'none':
                raise RuntimeError('未检测到 Magisk 或 KernelSU')

            undone = False
            for base in self._module_base_dirs(manager):
                mdir = f'{base}/{module_id}'
                try:
                    ok = (self._su(serial, f'[ -d {mdir} ] && echo 1 || echo 0', timeout=8) or '').strip()
                    if ok != '1':
                        continue
                    # self._emit(f'撤销移除模块: {module_id}')
                    self._su(serial, f'rm -f {mdir}/remove', timeout=20)
                    undone = True
                    break
                except Exception:
                    pass

            if not undone:
                raise RuntimeError('未找到模块目录: ' + module_id)
            
            self.step_finish(sid, True, "")
        except Exception as e:
            self.step_finish(sid, False, str(e))
            raise e

    def backup_module(self, module_id: str, local_dest_dir: str) -> str:
        import uuid
        sid = str(uuid.uuid4())
        self.step_start(sid, f"备份模块: {module_id}")
        
        try:
            serial = self._require_system_serial()
            manager = self.detect_manager()
            if manager == 'none':
                raise RuntimeError('未检测到 Magisk 或 KernelSU')

            base_dirs = self._module_base_dirs(manager)
            target = ''
            for base in base_dirs:
                mdir = f'{base}/{module_id}'
                try:
                    ok = (self._su(serial, f'[ -d {mdir} ] && echo 1 || echo 0', timeout=8) or '').strip()
                    if ok == '1':
                        target = mdir
                        break
                except Exception:
                    pass

            if not target:
                raise RuntimeError('未找到模块目录: ' + module_id)

            ts = time.strftime('%Y%m%d_%H%M%S')
            remote_dir = f'/sdcard/TobatoolsBackups/modules'
            remote_file = f'{remote_dir}/{module_id}_{ts}.tar.gz'

            # self._emit('准备备份...')
            self._su(serial, f'mkdir -p {remote_dir}', timeout=20)

            # Prefer toybox/busybox tar if available
            tar_cmd = f"tar -czf '{remote_file}' -C '{target}' ."
            out = self._su(serial, f"{tar_cmd} 2>/dev/null || busybox tar -czf '{remote_file}' -C '{target}' . 2>/dev/null || toybox tar -czf '{remote_file}' -C '{target}' . 2>/dev/null", timeout=120)
            if out:
                for line in out.splitlines():
                    self._emit(line)

            local_dest = str(Path(local_dest_dir).resolve())
            Path(local_dest).mkdir(parents=True, exist_ok=True)
            local_file = str(Path(local_dest) / Path(remote_file).name)
            ok, msg = adb_service.pull_file(remote_file, local_file)
            if not ok:
                raise RuntimeError('拉取备份失败: ' + (msg or ''))

            # self._emit('备份完成: ' + local_file)
            self.step_finish(sid, True, "")
            return local_file
        except Exception as e:
            self.step_finish(sid, False, str(e))
            raise e

    def install_module_zip(self, zip_path: str) -> None:
        import uuid
        z = Path(zip_path)
        sid = str(uuid.uuid4())
        self.step_start(sid, f"安装模块: {z.name}")
        
        try:
            if not z.exists() or not z.is_file():
                raise FileNotFoundError(str(z))

            serial = self._require_system_serial()
            manager = self.detect_manager()
            if manager == 'none':
                raise RuntimeError('未检测到 Magisk 或 KernelSU')

            remote = f"/sdcard/{z.name}"
            adb = str(adb_service.ADB_BIN) if adb_service.ADB_BIN.exists() else 'adb'

            self._emit('推送模块压缩包到设备...')
            out = adb_service._run([adb, '-s', serial, 'push', str(z), remote], timeout=600) or ''
            if out:
                for line in out.splitlines():
                    self._emit(line)

            if manager == 'magisk':
                self._emit('开始安装 (Magisk)...')
                # magisk --install-module /sdcard/xxx.zip
                out = self._su(serial, f"magisk --install-module '{remote}'", timeout=600) or ''
                if out:
                    for line in out.splitlines():
                        self._emit(line)
                self.step_finish(sid, True, "Magisk安装完成")
                return

            # KernelSU: best-effort, different variants exist (ksu/ksud)
            self._emit('开始安装 (KernelSU)...')

            has_ksu = (self._su(serial, 'command -v ksu >/dev/null 2>&1 && echo 1 || echo 0', timeout=8) or '').strip() == '1'
            has_ksud = (self._su(serial, 'command -v ksud >/dev/null 2>&1 && echo 1 || echo 0', timeout=8) or '').strip() == '1'

            cmds: list[str] = []
            if has_ksu:
                cmds.append(f"ksu module install '{remote}'")
                cmds.append(f"ksu module install --zip '{remote}'")
            if has_ksud:
                cmds.append(f"ksud module install '{remote}'")
                cmds.append(f"ksud module install --zip '{remote}'")

            if not cmds:
                raise RuntimeError('未找到 KernelSU 命令行工具（ksu/ksud）。请使用 KernelSU 管理器手动安装模块。')

            last_out = ''
            success = False
            for c in cmds:
                out = self._su(serial, c, timeout=600) or ''
                last_out = out
                if out:
                    for line in out.splitlines():
                        self._emit(line)
                lo = out.lower()
                if 'not found' in lo or 'unknown command' in lo or 'usage:' in lo:
                    continue
                # assume executed
                success = True
                break
            
            if success:
                self.step_finish(sid, True, "KernelSU安装完成")
                return

            if last_out:
                raise RuntimeError('KernelSU 安装命令执行失败：' + last_out.strip())
            raise RuntimeError('KernelSU 安装命令执行失败')
        except Exception as e:
            self.step_finish(sid, False, str(e))
            raise e

    def batch_install(self, zip_paths: list[str]) -> None:
        for p in zip_paths:
            self._emit('')
            self._emit('安装: ' + str(p))
            self.install_module_zip(p)
