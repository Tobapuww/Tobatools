import subprocess
import re
import socket
import struct
import time
import uuid
import shutil
import sys
from typing import Dict, List, Tuple
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
BIN_DIR = ROOT_DIR / "bin"
ADB_BIN = BIN_DIR / "adb.exe" if (BIN_DIR / "adb.exe").exists() else BIN_DIR / "adb"
FASTBOOT_BIN = BIN_DIR / "fastboot.exe" if (BIN_DIR / "fastboot.exe").exists() else BIN_DIR / "fastboot"


class AdbServerError(RuntimeError):
    pass


class _AdbServerClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 5037, timeout: float = 8.0):
        self._host = host
        self._port = int(port)
        self._timeout = float(timeout)

    def _connect(self) -> socket.socket:
        s = socket.create_connection((self._host, self._port), timeout=self._timeout)
        s.settimeout(self._timeout)
        return s

    @staticmethod
    def _encode_service(service: str) -> bytes:
        b = (service or "").encode("utf-8")
        return f"{len(b):04x}".encode("ascii") + b

    @staticmethod
    def _read_exact(sock: socket.socket, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise AdbServerError("adb server closed connection")
            buf.extend(chunk)
        return bytes(buf)

    def _read_status(self, sock: socket.socket) -> None:
        status = self._read_exact(sock, 4)
        if status == b"OKAY":
            return
        if status == b"FAIL":
            msg = self._read_string(sock)
            raise AdbServerError(msg or "adb server FAIL")
        raise AdbServerError(f"unexpected adb status: {status!r}")

    def _read_string(self, sock: socket.socket) -> str:
        ln_hex = self._read_exact(sock, 4)
        try:
            ln = int(ln_hex.decode("ascii"), 16)
        except Exception as e:
            raise AdbServerError(f"invalid length prefix: {ln_hex!r}") from e
        if ln <= 0:
            return ""
        data = self._read_exact(sock, ln)
        return data.decode("utf-8", errors="replace")

    def _request(self, service: str, *, timeout: float | None = None, expect_string: bool = True) -> str:
        s = self._connect()
        try:
            if timeout is not None:
                s.settimeout(float(timeout))
            s.sendall(self._encode_service(service))
            self._read_status(s)
            if not expect_string:
                return ""
            return self._read_string(s)
        finally:
            try:
                s.close()
            except Exception:
                pass

    def host_devices(self, *, timeout: float = 5.0) -> list[tuple[str, str]]:
        payload = self._request("host:devices", timeout=timeout, expect_string=True)
        out: list[tuple[str, str]] = []
        for line in (payload or "").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            out.append((parts[0].strip(), parts[1].strip()))
        return out

    def host_mdns_services(self, *, timeout: float = 5.0) -> str:
        return self._request("host:mdns:services", timeout=timeout, expect_string=True)

    def host_connect(self, hp: str, *, timeout: float = 10.0) -> str:
        return self._request(f"host:connect:{hp}", timeout=timeout, expect_string=True)

    def host_disconnect(self, hp: str | None = None, *, timeout: float = 10.0) -> str:
        if hp:
            return self._request(f"host:disconnect:{hp}", timeout=timeout, expect_string=True)
        return self._request("host:disconnect:", timeout=timeout, expect_string=True)

    def host_pair(self, hp: str, code: str, *, timeout: float = 15.0) -> str:
        return self._request(f"host:pair:{hp}:{code}", timeout=timeout, expect_string=True)

    def shell(self, serial: str, cmd: str, *, timeout: float = 20.0) -> str:
        s = self._connect()
        try:
            s.settimeout(float(timeout))
            s.sendall(self._encode_service(f"host:transport:{serial}"))
            self._read_status(s)
            s.sendall(self._encode_service(f"shell:{cmd}"))
            self._read_status(s)
            chunks: list[bytes] = []
            while True:
                try:
                    b = s.recv(64 * 1024)
                except socket.timeout:
                    break
                if not b:
                    break
                chunks.append(b)
            return b"".join(chunks).decode("utf-8", errors="ignore").strip()
        finally:
            try:
                s.close()
            except Exception:
                pass

    def _sync_open(self, serial: str, *, timeout: float = 30.0) -> socket.socket:
        s = self._connect()
        s.settimeout(float(timeout))
        s.sendall(self._encode_service(f"host:transport:{serial}"))
        self._read_status(s)
        s.sendall(self._encode_service("sync:"))
        self._read_status(s)
        return s

    @staticmethod
    def _sync_send_cmd(sock: socket.socket, cmd4: bytes, payload: bytes = b"") -> None:
        sock.sendall(cmd4 + struct.pack("<I", len(payload)) + payload)

    @staticmethod
    def _sync_recv_header(sock: socket.socket) -> tuple[bytes, int]:
        hdr = _AdbServerClient._read_exact(sock, 8)
        cmd4 = hdr[:4]
        ln = struct.unpack("<I", hdr[4:])[0]
        return cmd4, int(ln)

    def sync_list(self, serial: str, remote_dir: str, *, timeout: float = 20.0) -> list[dict]:
        s = self._sync_open(serial, timeout=timeout)
        try:
            self._sync_send_cmd(s, b"LIST", (remote_dir or "").encode("utf-8"))
            items: list[dict] = []
            while True:
                cmd4, ln = self._sync_recv_header(s)
                if cmd4 == b"DONE":
                    break
                if cmd4 == b"DENT":
                    dent = self._read_exact(s, 16 + ln)
                    mode, size, mtime = struct.unpack("<III", dent[:12])
                    name = dent[16:].decode("utf-8", errors="replace")
                    items.append({"name": name, "mode": int(mode), "size": int(size), "mtime": int(mtime)})
                    continue
                if cmd4 == b"FAIL":
                    msg = self._read_exact(s, ln).decode("utf-8", errors="replace")
                    raise AdbServerError(msg or "sync LIST fail")
                if ln > 0:
                    _ = self._read_exact(s, ln)
            return items
        finally:
            try:
                s.close()
            except Exception:
                pass

    def sync_pull_file(self, serial: str, remote: str, local: str, *, timeout: float = 600.0) -> None:
        s = self._sync_open(serial, timeout=timeout)
        try:
            self._sync_send_cmd(s, b"RECV", (remote or "").encode("utf-8"))
            with open(local, "wb") as f:
                while True:
                    cmd4, ln = self._sync_recv_header(s)
                    if cmd4 == b"DATA":
                        if ln:
                            f.write(self._read_exact(s, ln))
                        continue
                    if cmd4 == b"DONE":
                        break
                    if cmd4 == b"FAIL":
                        msg = self._read_exact(s, ln).decode("utf-8", errors="replace")
                        raise AdbServerError(msg or "sync RECV fail")
                    if ln:
                        _ = self._read_exact(s, ln)
        finally:
            try:
                s.close()
            except Exception:
                pass

    def sync_push_file(self, serial: str, local: str, remote: str, *, mode: int = 0o644, timeout: float = 600.0) -> None:
        s = self._sync_open(serial, timeout=timeout)
        try:
            r = (remote or "").encode("utf-8") + f",{int(mode)}".encode("utf-8")
            self._sync_send_cmd(s, b"SEND", r)
            with open(local, "rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    self._sync_send_cmd(s, b"DATA", chunk)
            self._sync_send_cmd(s, b"DONE", struct.pack("<I", int(time.time())))
            cmd4, ln = self._sync_recv_header(s)
            if cmd4 == b"OKAY":
                if ln:
                    _ = self._read_exact(s, ln)
                return
            if cmd4 == b"FAIL":
                msg = self._read_exact(s, ln).decode("utf-8", errors="replace")
                raise AdbServerError(msg or "sync SEND fail")
            if ln:
                _ = self._read_exact(s, ln)
            raise AdbServerError("unexpected sync response")
        finally:
            try:
                s.close()
            except Exception:
                pass


def _adb_server(timeout: float = 8.0) -> _AdbServerClient:
    return _AdbServerClient(timeout=timeout)


def _ensure_adb_server_running() -> bool:
    try:
        _adb_server(timeout=1.0).host_devices(timeout=1.0)
        return True
    except Exception:
        pass
    try:
        run_adb(["start-server"], timeout=6)
    except Exception:
        pass
    try:
        _adb_server(timeout=2.0).host_devices(timeout=2.0)
        return True
    except Exception:
        return False


def _silent_kwargs():
    try:
        import os as _os
        if _os.name == 'nt':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return {'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW}
    except Exception:
        pass
    return {}


def _run(cmd: List[str], timeout: int = 8) -> str:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout, **_silent_kwargs())
        return out.decode(errors='ignore')
    except subprocess.TimeoutExpired:
        return ""  # 超时，返回空
    except FileNotFoundError:
        return ""  # 命令不存在
    except Exception:
        return ""  # 其他错误


def _adb_bin() -> str:
    return str(ADB_BIN) if ADB_BIN.exists() else "adb"


def run_adb(args: List[str], timeout: int = 10) -> Tuple[int, str]:
    adb = _adb_bin()
    cmd = [adb] + list(args or [])
    try:
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            **_silent_kwargs(),
        )
        return int(r.returncode), (r.stdout or '').strip()
    except subprocess.TimeoutExpired:
        return 124, 'timeout'
    except FileNotFoundError:
        return 127, 'adb not found'
    except Exception as e:
        return 1, str(e)


def _normalize_host_port(host: str, port: str | int) -> str:
    h = str(host or '').strip()
    p = str(port or '').strip()
    if not h:
        return ''
    if ':' in h:
        return h
    if not p:
        return h
    return f"{h}:{p}"


def adb_pair(host: str, port: str | int, pairing_code: str, timeout: int = 15) -> Tuple[int, str]:
    hp = _normalize_host_port(host, port)
    code = str(pairing_code or '').strip()
    if not hp or not code:
        return 2, 'missing host/port or pairing code'
    try:
        _ensure_adb_server_running()
        out = _adb_server(timeout=float(timeout)).host_pair(hp, code, timeout=float(timeout))
        return 0, (out or '').strip()
    except Exception:
        return run_adb(['pair', hp, code], timeout=timeout)


def adb_connect(host: str, port: str | int, timeout: int = 10) -> Tuple[int, str]:
    hp = _normalize_host_port(host, port)
    if not hp:
        return 2, 'missing host/port'
    try:
        _ensure_adb_server_running()
        out = _adb_server(timeout=float(timeout)).host_connect(hp, timeout=float(timeout))
        return 0, (out or '').strip()
    except Exception:
        return run_adb(['connect', hp], timeout=timeout)


def adb_disconnect(host: str | None = None, port: str | int | None = None, timeout: int = 10) -> Tuple[int, str]:
    if host:
        hp = _normalize_host_port(host, port or '')
        try:
            _ensure_adb_server_running()
            out = _adb_server(timeout=float(timeout)).host_disconnect(hp, timeout=float(timeout))
            return 0, (out or '').strip()
        except Exception:
            return run_adb(['disconnect', hp], timeout=timeout)
    try:
        _ensure_adb_server_running()
        out = _adb_server(timeout=float(timeout)).host_disconnect(None, timeout=float(timeout))
        return 0, (out or '').strip()
    except Exception:
        return run_adb(['disconnect'], timeout=timeout)


def adb_mdns_services(timeout: int = 5) -> Tuple[int, str]:
    try:
        _ensure_adb_server_running()
        out = _adb_server(timeout=float(timeout)).host_mdns_services(timeout=float(timeout))
        return 0, (out or '').strip()
    except Exception:
        return run_adb(['mdns', 'services'], timeout=timeout)


def adb_kill_server() -> Tuple[int, str]:
    return run_adb(['kill-server'], timeout=10)


def adb_start_server() -> Tuple[int, str]:
    return run_adb(['start-server'], timeout=10)


def check_adb_available() -> bool:
    # Must be fast and non-blocking (used on UI thread).
    try:
        if ADB_BIN.exists():
            return True
    except Exception:
        pass
    try:
        if shutil.which("adb"):
            return True
    except Exception:
        pass
    # As a last resort, check whether adb server is reachable.
    try:
        c = _adb_server(timeout=0.3)
        c.host_devices(timeout=0.3)
        return True
    except Exception:
        return False


def list_devices() -> List[str]:
    try:
        if not _ensure_adb_server_running():
            return []
        devs = _adb_server(timeout=5.0).host_devices(timeout=5.0)
        return [s for (s, st) in devs if st == "device"]
    except Exception:
        adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"

        # 首次调用可能触发 ADB server 启动，需要等待和重试
        max_retries = 3
        retry_delay = 1.0  # 秒

        for attempt in range(max_retries):
            out = _run([adb, "devices"], timeout=5)
            if "daemon" in out.lower() and "start" in out.lower():
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue

            serials: List[str] = []
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    serials.append(parts[0])

            if serials or attempt == max_retries - 1:
                return serials

            if attempt < max_retries - 1:
                time.sleep(retry_delay)

        return []


def _getprop(serial: str, key: str) -> str:
    try:
        if not serial:
            return ""
        if not _ensure_adb_server_running():
            return ""
        return _adb_server(timeout=3.0).shell(serial, f"getprop {key}", timeout=3.0)
    except Exception:
        adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
        return _run([adb, "-s", serial, "shell", "getprop", key], timeout=3)


def _shell(serial: str, cmd: str) -> str:
    try:
        if not serial:
            return ""
        if not _ensure_adb_server_running():
            return ""
        return _adb_server(timeout=8.0).shell(serial, cmd, timeout=8.0)
    except Exception:
        adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
        return _run([adb, "-s", serial, "shell", cmd], timeout=8)


def _adb_get_state(serial: str) -> str:
    try:
        if not serial:
            return ""
        if not _ensure_adb_server_running():
            return ""
        out = _adb_server(timeout=2.0)._request(f"host-serial:{serial}:get-state", timeout=2.0, expect_string=True)
        return (out or "").strip()
    except Exception:
        adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
        return _run([adb, "-s", serial, "get-state"], timeout=2)


def _fastboot(cmds: List[str], timeout: int = 5) -> str:
    """执行 fastboot 命令，支持自定义超时"""
    fb = str(FASTBOOT_BIN) if FASTBOOT_BIN.exists() else "fastboot"
    return _run([fb] + cmds, timeout=timeout)


def _read_sys_value(serial: str, paths: List[str]) -> int:
    for path in paths:
        cmd = f"if [ -f {path} ]; then cat {path}; fi"
        out = _shell(serial, cmd)
        val = (out or "").strip()
        if not val or "No such file" in val or "Permission denied" in val:
            continue
        try:
            return int(float(val))
        except Exception:
            continue
    return 0


def _meminfo_value(meminfo: str, key: str) -> int:
    pattern = re.compile(rf"^{re.escape(key)}\s*:\s*(\d+)", re.MULTILINE)
    match = pattern.search(meminfo or "")
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def _format_mem_size(kb: int) -> str:
    if kb <= 0:
        return "0 MB"
    gb = kb / (1024 * 1024)
    if gb >= 1:
        return f"{gb:.1f} GB"
    mb = kb / 1024
    return f"{mb:.0f} MB"


def _harmonize_capacity_pair(rated: int, full: int) -> Tuple[int, int]:
    if rated <= 0 or full <= 0:
        return rated, full
    if rated <= full:
        smaller, larger = rated, full
        swap = False
    else:
        smaller, larger = full, rated
        swap = True
    while larger / max(1, smaller) >= 8 and smaller < 10 ** 9:
        smaller *= 10
    if swap:
        return larger, smaller
    return smaller, larger


def _format_capacity(uah: int) -> str:
    if uah <= 0:
        return ""
    mah = uah / 1000
    if mah >= 1000:
        return f"{mah:,.0f} mAh"
    if mah >= 100:
        return f"{mah:.0f} mAh"
    return f"{mah:.1f} mAh"


def detect_connection_mode() -> Tuple[str, str]:
    """Return (mode, serial). mode in: system, sideload, fastbootd, bootloader, offline, none"""
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    # 减少 ADB 超时时间到 2 秒（设备存在时响应很快）
    out = ""
    try:
        if _ensure_adb_server_running():
            devs = _adb_server(timeout=2.0).host_devices(timeout=2.0)
            out = "List of devices attached\n" + "\n".join([f"{s}\t{st}" for (s, st) in devs])
    except Exception:
        out = ""
    if not out:
        out = _run([adb, "devices"], timeout=2)
    found_serial = ""
    if out:
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        start = 1 if lines and lines[0].lower().startswith("list of devices") else 0
        for line in lines[start:]:
            if line.startswith("*"):
                continue
            parts = line.split()
            if not parts:
                continue
            serial = parts[0]
            state = parts[1] if len(parts) > 1 else ""
            found_serial = serial
            if state == "device":
                return ("system", serial)
            if state == "sideload":
                return ("sideload", serial)
            if state in ("offline", "unauthorized"):
                return ("offline", serial)

    fb = str(FASTBOOT_BIN) if FASTBOOT_BIN.exists() else "fastboot"
    # 减少 Fastboot 超时时间到 2 秒
    out = _run([fb, "devices"], timeout=2)
    if out:
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        for line in lines:
            parts = line.split()
            if not parts:
                continue
            serial = parts[0]
            if serial.lower().startswith("(bootloader)"):
                continue
            
            # 使用 getvar is-userspace 精准判断 fastbootd
            # 返回 "yes" = fastbootd, "no" = bootloader
            is_userspace = _run([fb, "-s", serial, "getvar", "is-userspace"], timeout=2)
            if "yes" in (is_userspace or "").lower():
                return ("fastbootd", serial)
            return ("bootloader", serial)

    # Fallback: detect special USB/COM port modes (Windows)
    try:
        port_mode, port_id = _detect_special_port_mode()
        if port_mode != "none":
            return (port_mode, port_id)
    except Exception:
        pass

    return ("none", found_serial)


def _detect_special_port_mode() -> Tuple[str, str]:
    """Detect EDL(9008) / MTK BROM via Windows COM ports.

    Returns (mode, id):
    - ("edl", "COMx") for Qualcomm 9008
    - ("brom", "COMx") for MediaTek preloader/brom/vcom
    - ("none", "") otherwise
    """
    if not sys.platform.startswith("win"):
        return ("none", "")

    ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$items = @()
$items += Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Name, PNPDeviceID
$items += Get-CimInstance Win32_PnPEntity | Where-Object {
    $_.Name -match '\(COM\d+\)' -or $_.Caption -match '\(COM\d+\)'
} | Select-Object @{Name='DeviceID';Expression={
    if ($_.Name -match '\((COM\d+)\)') { $matches[1] }
    elseif ($_.Caption -match '\((COM\d+)\)') { $matches[1] }
    else { '' }
}}, @{Name='Name';Expression={
    if ($_.Name) { $_.Name } elseif ($_.Caption) { $_.Caption } else { '' }
}}, PNPDeviceID
$items | ForEach-Object {
    $dev = [string]$_.DeviceID
    $name = [string]$_.Name
    $pnp = [string]$_.PNPDeviceID
    if ($dev) { Write-Output ($dev + '|' + $name + '|' + $pnp) }
}
"""
    cmd = ["powershell", "-NoProfile", "-Command", ps_script]
    out = _run(cmd, timeout=4)
    if not out:
        return ("none", "")

    seen: set[tuple[str, str]] = set()
    for raw in out.splitlines():
        line = (raw or "").strip()
        if not line:
            continue
        parts = line.split("|", 2)
        com = (parts[0].strip() if len(parts) > 0 else "")
        name = (parts[1].strip() if len(parts) > 1 else "")
        pnp = (parts[2].strip() if len(parts) > 2 else "")
        if not re.match(r"^COM\d+$", com, re.IGNORECASE):
            continue
        key = (com.upper(), name)
        if key in seen:
            continue
        seen.add(key)

        text = f"{name} {pnp}".lower()
        text = text.replace("_", "-")

        # Qualcomm EDL / 9008
        if (
            "9008" in text
            or "qdloader" in text
            or "qualcomm hs-usb" in text
            or "qualcomm usb" in text
            or "emergency download" in text
            or ("qualcomm" in text and "edl" in text)
        ):
            return ("edl", com)

        # MediaTek BROM / Preloader / VCOM
        if (
            ("mediatek" in text or "mtk" in text)
            and (
                "preloader" in text
                or "brom" in text
                or "vcom" in text
                or "usb port" in text
                or "download port" in text
            )
        ):
            return ("brom", com)

    return ("none", "")


def get_device_info(serial: str) -> Dict[str, str]:
    info: Dict[str, str] = {}
    def add(k, v):
        if v is None:
            v = ""
        info[k] = v.strip()

    add("serial", serial)
    add("brand", _getprop(serial, "ro.product.brand"))
    add("model", _getprop(serial, "ro.product.model"))
    add("device", _getprop(serial, "ro.product.device"))
    add("product", _getprop(serial, "ro.product.name"))
    add("android_version", _getprop(serial, "ro.build.version.release"))
    add("sdk", _getprop(serial, "ro.build.version.sdk"))
    add("vndk", _getprop(serial, "ro.build.version.vndk"))
    add("build_display", _getprop(serial, "ro.build.display.id"))
    add("fingerprint", _getprop(serial, "ro.build.fingerprint"))

    # 额外信息（可选）
    battery_dump = _shell(serial, "dumpsys battery")
    battery_level = ""
    for line in battery_dump.splitlines():
        line = line.strip()
        if line.lower().startswith("level:"):
            battery_level = line.split(":", 1)[-1].strip()
            break
    add("battery", battery_level)
    add("bootloader", _getprop(serial, "ro.bootloader"))
    add("baseband", _getprop(serial, "gsm.version.baseband"))
    
    # CPU information
    # 尝试多种方式获取CPU型号
    cpu_model = ""
    
    # 方法1: 从 /proc/cpuinfo 获取
    cpuinfo = _shell(serial, "cat /proc/cpuinfo")
    if cpuinfo:
        for line in cpuinfo.splitlines():
            line = line.strip()
            if line.startswith("Hardware"):
                cpu_model = line.split(":", 1)[-1].strip()
                break
            elif line.startswith("Processor") and not cpu_model:
                cpu_model = line.split(":", 1)[-1].strip()
    
    # 方法2: 从系统属性获取
    if not cpu_model:
        cpu_model = _getprop(serial, "ro.hardware")
    
    # 方法3: 从 /sys/devices/system/cpu/soc 获取
    if not cpu_model:
        soc_id = _read_sys_value(serial, [
            "/sys/devices/system/cpu/soc0/serial_number",
            "/sys/devices/system/cpu/soc0/family",
            "/sys/devices/system/cpu/soc0/id"
        ])
        if soc_id:
            cpu_model = soc_id
    
    # 方法4: 尝试从dmesg获取
    if not cpu_model:
        dmesg = _shell(serial, "dmesg | grep -i 'cpu\\|processor\\|soc' | head -5")
        if dmesg:
            for line in dmesg.splitlines():
                if any(keyword in line.lower() for keyword in ["mt", "snapdragon", "qualcomm", "mediatek", "dimensity"]):
                    # 提取可能的CPU型号
                    import re
                    match = re.search(r'(MT\d+\w*|SDM\d+\w*|SM\d+\w*|Snapdragon\s+\w+|Dimensity\s+\d+\w*)', line, re.IGNORECASE)
                    if match:
                        cpu_model = match.group(1)
                        break
    
    # 如果还是获取不到，使用架构信息作为后备
    if not cpu_model:
        cpu_abi = _getprop(serial, "ro.product.cpu.abi")
        cpu_abi2 = _getprop(serial, "ro.product.cpu.abi2")
        cpu_model = cpu_abi
        if cpu_abi2 and cpu_abi2 != cpu_abi:
            cpu_model = f"{cpu_abi} ({cpu_abi2})"
    
    add("cpu_info", cpu_model or "Unknown")

    # battery health
    rated_capacity = _read_sys_value(serial, [
        "/sys/class/power_supply/battery/charge_full_design",
        "/sys/class/power_supply/BAT0/charge_full_design",
    ])
    full_capacity = _read_sys_value(serial, [
        "/sys/class/power_supply/battery/charge_full",
        "/sys/class/power_supply/BAT0/charge_full",
    ])
    if rated_capacity and full_capacity:
        rated_capacity, full_capacity = _harmonize_capacity_pair(rated_capacity, full_capacity)
        health_pct = max(0, min(100, int(full_capacity / rated_capacity * 100)))
        add("battery_health_percent", str(health_pct))
    if rated_capacity:
        add("battery_rated_capacity", _format_capacity(rated_capacity))
    if full_capacity:
        add("battery_full_capacity", _format_capacity(full_capacity))

    # storage
    df_line = _shell(serial, "df -h /data | tail -n 1")
    add("storage_data", df_line)

    # memory
    meminfo = _shell(serial, "cat /proc/meminfo")
    mem_total = _meminfo_value(meminfo, "MemTotal")
    mem_available = _meminfo_value(meminfo, "MemAvailable")
    if not mem_available:
        mem_available = _meminfo_value(meminfo, "MemFree")
    if mem_total > 0:
        used = max(0, mem_total - (mem_available or 0))
        percent = int(used / mem_total * 100) if mem_total else 0
        percent = max(0, min(100, percent))
        detail = f"已用 {_format_mem_size(used)} / 总 {_format_mem_size(mem_total)}"
        add("memory_percent", str(percent))
        add("memory_summary", detail)

    # kernel
    kern = _shell(serial, "uname -r")
    if not kern:
        kern = _shell(serial, "cat /proc/version")
    add("kernel", kern)

    # slot
    slot_suffix = _getprop(serial, "ro.boot.slot_suffix")
    slot = _getprop(serial, "ro.boot.slot")
    cur_slot = slot or slot_suffix.replace("_", "")
    add("current_slot", cur_slot)

    # bootloader unlock status via props
    vb_state = _getprop(serial, "ro.boot.vbmeta.device_state")  # locked/unlocked
    flash_locked = _getprop(serial, "ro.boot.flash.locked")  # 0 unlocked, 1 locked
    verified_boot = _getprop(serial, "ro.boot.verifiedbootstate")  # green/yellow/orange
    unlocked = "unknown"
    if vb_state:
        unlocked = "unlocked" if vb_state.lower() == "unlocked" else "locked"
    elif flash_locked:
        unlocked = "unlocked" if flash_locked.strip() == "0" else "locked"
    elif verified_boot:
        vb = verified_boot.lower().strip()
        # Common convention: orange indicates unlocked; green usually locked
        if vb == "orange":
            unlocked = "unlocked"
        elif vb == "green":
            unlocked = "locked"
    add("bootloader_unlock", unlocked)
    
    # 获取更多信息
    # 代号
    add("codename", _getprop(serial, "ro.product.device"))
    
    # 序列号（已存在serial字段，这里获取设备序列号）
    device_serial = _shell(serial, "getprop ro.serialno")
    if not device_serial:
        device_serial = _shell(serial, "cat /proc/cmdline | tr ' ' '\\n' | grep androidboot.serialno | cut -d'=' -f2")
    add("device_serial", device_serial.strip() if device_serial else "")
    
    # 已开机时间
    uptime = _shell(serial, "cat /proc/uptime")
    if uptime:
        uptime_seconds = float(uptime.split()[0])
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        if days > 0:
            uptime_str = f"{days}天 {hours}小时 {minutes}分钟"
        elif hours > 0:
            uptime_str = f"{hours}小时 {minutes}分钟"
        else:
            uptime_str = f"{minutes}分钟"
        add("uptime", uptime_str)
    else:
        add("uptime", "")
    
    # 分辨率
    wm = _shell(serial, "wm size")
    if wm and "Physical size:" in wm:
        resolution = wm.split("Physical size:")[1].strip()
        add("resolution", resolution)
    else:
        add("resolution", "")
    
    # 显示密度
    density = _getprop(serial, "ro.sf.lcd_density")
    if not density:
        # 尝试从wm density获取
        wm_density = _shell(serial, "wm density")
        if wm_density and "Physical density:" in wm_density:
            density = wm_density.split("Physical density:")[1].strip()
    add("display_density", density)
    
    # 闪存类型
    emmc = _read_sys_value(serial, [
        "/sys/block/mmcblk0/device/type",
        "/sys/block/mmcblk1/device/type"
    ])
    ufs = _read_sys_value(serial, [
        "/sys/block/sda/device/type",
        "/sys/block/sdb/device/type"
    ])
    storage_type = ""
    if emmc and "mmc" in emmc.lower():
        storage_type = "eMMC"
    elif ufs and "ufs" in ufs.lower():
        storage_type = "UFS"
    else:
        # 尝试通过其他方式判断
        if _read_sys_value(serial, ["/sys/block/sda"]):
            storage_type = "UFS"
        elif _read_sys_value(serial, ["/sys/block/mmcblk0"]):
            storage_type = "eMMC"
    add("storage_type", storage_type)
    
    # Root权限状态
    root_status = "未检测"
    # 检查su命令是否存在
    su_check = _shell(serial, "which su")
    if su_check and su_check.strip():
        root_status = "已Root"
    else:
        # 检查常见root管理器
        magisk = _shell(serial, "which magisk")
        if magisk and magisk.strip():
            root_status = "已Root (Magisk)"
        else:
            # 检查system分区是否可写
            system_rw = _shell(serial, "mount | grep ' /system ' | grep rw")
            if system_rw and system_rw.strip():
                root_status = "已Root"
    add("root_status", root_status)

    return info


def reboot_to(target: str) -> Tuple[bool, str]:
    """Reboot device to target: bootloader, recovery, fastbootd, system, edl.
    Auto-detect current mode and use adb or fastboot accordingly.
    Returns (ok, message).
    """
    target = (target or "").strip().lower()
    if target not in ("bootloader", "recovery", "fastbootd", "system", "edl"):
        return False, f"不支持的目标: {target}"

    mode, serial = detect_connection_mode()
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    fb = str(FASTBOOT_BIN) if FASTBOOT_BIN.exists() else "fastboot"

    def _ok(msg: str):
        return True, msg

    def _fail(msg: str):
        return False, msg

    # If nothing connected
    if mode == "none" or not (serial or mode in ("fastbootd", "bootloader")):
        return _fail("未检测到已连接设备")

    # Map of actions per mode
    if mode in ("system", "sideload"):
        # Use ADB reboot variants
        if target == "system":
            out = _run([adb, "reboot"])  # simple reboot to system
            return _ok(out or "已重启到系统")
        if target == "bootloader":
            out = _run([adb, "reboot", "bootloader"])
            return _ok(out or "正在重启到 Bootloader")
        if target == "fastbootd":
            out = _run([adb, "reboot", "fastboot"])  # userspace fastbootd
            return _ok(out or "正在重启到 FastbootD")
        if target == "recovery":
            out = _run([adb, "reboot", "recovery"])
            return _ok(out or "正在重启到 Recovery")
        if target == "edl":
            # Some devices may accept this; otherwise user must enter from fastboot
            out = _run([adb, "reboot", "edl"])
            if out:
                return _ok(out)
            return _ok("已尝试通过 ADB 进入 EDL（是否成功取决于设备支持）")

    # Fastboot/Bootloader family
    if mode in ("fastbootd", "bootloader"):
        if target == "system":
            out = _run([fb, "reboot"])
            return _ok(out or "正在重启到系统")
        if target == "bootloader":
            out = _run([fb, "reboot-bootloader"]) if mode != "bootloader" else ""
            return _ok(out or "已在 Bootloader 或正在进入 Bootloader")
        if target == "fastbootd":
            # Enter userspace fastboot
            out = _run([fb, "reboot", "fastboot"])  # fastboot reboot fastboot
            return _ok(out or "正在重启到 FastbootD")
        if target == "recovery":
            # Not universally supported, but commonly available
            out = _run([fb, "reboot", "recovery"])
            if out:
                return _ok(out)
            # Fallback OEM command
            out2 = _run([fb, "oem", "reboot-recovery"])  # vendor specific
            return _ok(out2 or "已尝试进入 Recovery（是否成功取决于设备支持）")
        if target == "edl":
            # Qualcomm devices (OnePlus) often support either command
            out = _run([fb, "oem", "edl"])  # try OEM first
            if out:
                return _ok(out)
            out2 = _run([fb, "edl"])  # standard new fastboot cmd
            return _ok(out2 or "已尝试进入 EDL（是否成功取决于设备支持）")

    return _fail("未能执行重启命令")


# -------- ADB File Ops --------
def list_dir(path: str) -> Tuple[List[Dict[str, str]], str]:
    """List directory on device. Returns (items, err).
    Each item: {name, size, type: 'dir'|'file'}
    """
    p = path or "/"
    try:
        serials = list_devices()
        serial = serials[0] if serials else ""
        if serial and _ensure_adb_server_running():
            # Fast path: avoid heavy `ls -l` parsing and avoid SYNC metadata overhead.
            # `ls -1p` appends '/' to dirs (toybox/busybox compatible in most ROMs).
            out = _adb_server(timeout=6.0).shell(serial, f"sh -c \"ls -1p '{p}' 2>/dev/null || toybox ls -1p '{p}' 2>/dev/null\"", timeout=6.0)
            if out and ("No such file" not in out) and ("Permission denied" not in out):
                items: List[Dict[str, str]] = []
                for line in (out or "").splitlines():
                    name = (line or "").strip()
                    if not name:
                        continue
                    is_dir = name.endswith('/')
                    if is_dir:
                        name = name[:-1]
                    items.append({"name": name, "size": "-", "type": ("dir" if is_dir else "file")})
                return items, ""

            # Fallback: SYNC LIST for cases where shell `ls` is restricted/unavailable.
            entries = _adb_server(timeout=10.0).sync_list(serial, p, timeout=10.0)
            items2: List[Dict[str, str]] = []
            for e in entries:
                name = (e.get("name") or "").strip()
                if not name or name in (".", ".."): 
                    continue
                mode = int(e.get("mode") or 0)
                is_dir = bool(mode & 0o040000)
                items2.append({"name": name, "size": str(e.get("size") or "-"), "type": ("dir" if is_dir else "file")})
            return items2, ""
    except Exception:
        pass

    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    out = _run([adb, "shell", "ls", "-l", p], timeout=10)
    if out is None:
        out = ""
    if not out.strip():
        # try without -l
        out2 = _run([adb, "shell", "ls", p], timeout=10)
        if not out2.strip():
            return [], f"无法列出目录：{p}（设备未连接或权限不足）"
        items: List[Dict[str, str]] = []
        for line in out2.split():
            if not line:
                continue
            items.append({"name": line.strip(), "size": "-", "type": "file"})
        return items, ""
    items: List[Dict[str, str]] = []
    for line in out.splitlines():
        s = line.strip()
        if not s or s.startswith("total "):
            continue
        # typical: drwxr-xr-x  2 root root     4096 Jan  1 00:00 Download
        parts = s.split()
        try:
            perm = parts[0]
            is_dir = perm.startswith('d')
            # size usually at index 4 (busybox/toybox may vary). Try last numeric before month name
            size = "-"
            for tok in parts[1:6]:
                if tok.isdigit():
                    size = tok
            name = parts[-1]
            items.append({"name": name, "size": size, "type": ("dir" if is_dir else "file")})
        except Exception:
            # fallback: whole line as name
            items.append({"name": s, "size": "-", "type": "file"})
    return items, ""


def pull_file(remote: str, local: str) -> Tuple[bool, str]:
    """adb pull remote local. Returns (ok, msg)."""
    try:
        serials = list_devices()
        serial = serials[0] if serials else ""
        if serial and _ensure_adb_server_running():
            _adb_server(timeout=600.0).sync_pull_file(serial, remote, local, timeout=600.0)
            return True, "完成"
        raise RuntimeError("no device")
    except Exception as e:
        adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
        try:
            out = _run([adb, "pull", remote, local], timeout=600)
            if out is None:
                out = ""
            return True, out or "完成"
        except Exception:
            return False, str(e)


# -------- Mobile-side Ops (ADB shell) --------
def _adb_shell(args: List[str], timeout: int = 20) -> str:
    try:
        serials = list_devices()
        serial = serials[0] if serials else ""
        if serial and _ensure_adb_server_running():
            cmd = " ".join([str(x) for x in (args or [])])
            return _adb_server(timeout=float(timeout)).shell(serial, cmd, timeout=float(timeout))
    except Exception:
        pass
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    return _run([adb, "shell"] + args, timeout=timeout)


def _sh_quote(s: str) -> str:
    t = str(s or "")
    if not t:
        return "''"
    if "'" not in t:
        return f"'{t}'"
    # close-open pattern: 'foo'"'"'bar'
    return "'" + t.replace("'", "'\"'\"'") + "'"


def adb_shell_serial(serial: str, args: List[str] | str, timeout: int = 20) -> str:
    """Execute a shell command on a specific device serial via adb server socket.

    args can be:
    - list[str]: will be shell-quoted and joined
    - str: passed as-is to shell
    """
    try:
        if not serial:
            return ""
        if not _ensure_adb_server_running():
            return ""
        if isinstance(args, str):
            cmd = args
        else:
            cmd = " ".join([_sh_quote(x) for x in (args or [])])
        return _adb_server(timeout=float(timeout)).shell(serial, cmd, timeout=float(timeout))
    except Exception:
        adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
        if isinstance(args, str):
            return _run([adb, "-s", serial, "shell", args], timeout=timeout)
        return _run([adb, "-s", serial, "shell"] + list(args or []), timeout=timeout)


def adb_pm_path(serial: str, pkg: str, timeout: int = 6) -> str:
    out = adb_shell_serial(serial, ["pm", "path", str(pkg or "").strip()], timeout=timeout)
    remote = ""
    for line in (out or "").splitlines():
        s = (line or "").strip()
        if s.startswith("package:"):
            remote = s.split(":", 1)[1].strip()
            break
    return remote


def adb_pull_file_serial(serial: str, remote: str, local: str, timeout: int = 600) -> Tuple[bool, str]:
    try:
        if not serial:
            return False, "未检测到设备"
        if not _ensure_adb_server_running():
            return False, "ADB server 未就绪"
        _adb_server(timeout=float(timeout)).sync_pull_file(serial, remote, local, timeout=float(timeout))
        return True, "完成"
    except Exception as e:
        adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
        try:
            out = _run([adb, "-s", serial, "pull", remote, local], timeout=timeout)
            return True, out or "完成"
        except Exception:
            return False, str(e)


def adb_install_apk(serial: str, apk_path: str, *, reinstall: bool = False, downgrade: bool = False, timeout: int = 600) -> Tuple[bool, str]:
    """Install APK without invoking `adb install` subprocess.

    Strategy:
    - SYNC push to /data/local/tmp/<uuid>.apk
    - pm install [-r] [-d] <remote>
    - cleanup remote file (best-effort)
    """
    p = str(apk_path or "").strip()
    if not p:
        return False, "APK 路径为空"
    try:
        if not serial:
            return False, "未检测到设备"
        if not _ensure_adb_server_running():
            return False, "ADB server 未就绪"

        remote = f"/data/local/tmp/{uuid.uuid4().hex}.apk"
        _adb_server(timeout=float(timeout)).sync_push_file(serial, p, remote, timeout=float(timeout))

        flags: list[str] = []
        if reinstall:
            flags.append("-r")
        if downgrade:
            flags.append("-d")

        cmd = ["pm", "install"] + flags + [remote]
        out = adb_shell_serial(serial, cmd, timeout=timeout)
        ok = ("Success" in (out or "")) and ("Failure" not in (out or ""))
        # cleanup (ignore failure)
        try:
            adb_shell_serial(serial, ["rm", "-f", remote], timeout=10)
        except Exception:
            pass
        return ok, (out or "").strip()
    except Exception as e:
        return False, str(e)


def path_exists(path: str) -> bool:
    out = _adb_shell(["ls", path], timeout=6)
    return bool(out.strip()) and ("No such file" not in out)


def is_dir(path: str) -> bool:
    out = _adb_shell(["sh", "-c", f"[ -d '{path}' ] && echo d || echo f"], timeout=6)
    return out.strip().startswith('d')


def mkdir_p(path: str) -> Tuple[bool, str]:
    out = _adb_shell(["mkdir", "-p", path], timeout=8)
    ok = True if (out is None or out.strip() == "") else True
    return ok, out or ""


def delete_path(path: str) -> Tuple[bool, str]:
    out = _adb_shell(["rm", "-rf", path], timeout=20)
    return True, out or ""


def move_path(src: str, dst_dir: str) -> Tuple[bool, str]:
    # Ensure target directory exists
    mkdir_p(dst_dir)
    out = _adb_shell(["sh", "-c", f"mv '{src}' '{dst_dir}/'"], timeout=30)
    return True, out or ""


def copy_path(src: str, dst_dir: str) -> Tuple[bool, str]:
    # Try cp -r, fallback to toybox cp -r
    mkdir_p(dst_dir)
    out = _adb_shell(["sh", "-c", f"cp -r '{src}' '{dst_dir}/' || toybox cp -r '{src}' '{dst_dir}/'"], timeout=120)
    return True, out or ""


def rename_path(src: str, new_name: str) -> Tuple[bool, str]:
    parent = src.rsplit('/', 1)[0] if '/' in src else '/'
    out = _adb_shell(["sh", "-c", f"mv '{src}' '{parent}/{new_name}'"], timeout=15)
    return True, out or ""


def stat_path(path: str) -> dict:
    # Use stat if available; fallback to ls -ld and du -s
    info: dict = {"path": path}
    s = _adb_shell(["sh", "-c", f"stat -c '%F|%s|%a|%U|%G|%y' '{path}' || toybox stat -c '%F|%s|%a|%U|%G|%y' '{path}'"], timeout=8)
    if s and '|' in s:
        try:
            ftype, size, perm, user, group, mtime = s.strip().split('|', 5)
            info.update({"type": ftype, "size": size, "perm": perm, "user": user, "group": group, "mtime": mtime})
            return info
        except Exception:
            pass
    # Fallbacks
    ls = _adb_shell(["ls", "-ld", path], timeout=6)
    info["raw_ls"] = ls
    du = _adb_shell(["du", "-s", path], timeout=10)
    info["raw_du"] = du
    return info


def pull_path(remote: str, local_dest: str) -> Tuple[bool, str]:
    """adb pull remote local_dest (支持文件或目录)."""
    try:
        serials = list_devices()
        serial = serials[0] if serials else ""
        if not serial or not _ensure_adb_server_running():
            raise RuntimeError("未检测到设备")

        # Try directory listing; if it fails, treat as file.
        try:
            entries = _adb_server(timeout=20.0).sync_list(serial, remote, timeout=20.0)
        except Exception:
            entries = []

        if entries:
            import os
            os.makedirs(local_dest, exist_ok=True)
            for e in entries:
                name = (e.get('name') or '').strip()
                if not name or name in ('.', '..'):
                    continue
                rpath = (remote.rstrip('/') + '/' + name) if remote not in ('/', '') else ('/' + name)
                mode = int(e.get('mode') or 0)
                is_dir = bool(mode & 0o040000)
                lpath = str(Path(local_dest) / name)
                if is_dir:
                    ok, msg = pull_path(rpath, lpath)
                    if not ok:
                        return False, msg
                else:
                    _adb_server(timeout=3600.0).sync_pull_file(serial, rpath, lpath, timeout=3600.0)
            return True, "完成"

        _adb_server(timeout=3600.0).sync_pull_file(serial, remote, local_dest, timeout=3600.0)
        return True, "完成"
    except Exception as e:
        adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
        try:
            out = _run([adb, "pull", remote, local_dest], timeout=3600)
            if out is None:
                out = ""
            return True, out or "完成"
        except Exception:
            return False, str(e)


def push_path(local_path: str, remote_dir: str) -> Tuple[bool, str]:
    """adb push local_path remote_dir (支持文件或目录)."""
    try:
        serials = list_devices()
        serial = serials[0] if serials else ""
        if not serial or not _ensure_adb_server_running():
            raise RuntimeError("未检测到设备")

        lp = Path(local_path)
        if not lp.exists():
            return False, "本地文件不存在"

        if lp.is_dir():
            mkdir_p(remote_dir)
            for child in lp.iterdir():
                dst = (remote_dir.rstrip('/') + '/' + child.name) if remote_dir not in ('/', '') else ('/' + child.name)
                ok, msg = push_path(str(child), dst)
                if not ok:
                    return False, msg
            return True, "完成"

        r = remote_dir
        if r.endswith('/') or r in ('/', ''):
            r = (r.rstrip('/') + '/' + lp.name) if r not in ('/', '') else ('/' + lp.name)

        _adb_server(timeout=3600.0).sync_push_file(serial, str(lp), r, timeout=3600.0)
        return True, "完成"
    except Exception as e:
        adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
        try:
            out = _run([adb, "push", local_path, remote_dir], timeout=3600)
            if out is None:
                out = ""
            return True, out or "完成"
        except Exception:
            return False, str(e)


def get_board_id(serial: str) -> str:
    """Extract BOARD_ID (oplusboot.serialno) from /proc/cmdline when available."""
    try:
        cmdline = _shell(serial, "cat /proc/cmdline")
    except Exception:
        cmdline = ""
    if not cmdline:
        return ""
    token = "oplusboot.serialno="
    idx = cmdline.find(token)
    if idx == -1:
        return ""
    rest = cmdline[idx + len(token):]
    return (rest.split()[0] if rest else "").strip()


def _mode_cn(mode: str) -> str:
    mapping = {
        "system": "系统",
        "sideload": "Sideload",
        "fastbootd": "FastbootD",
        "bootloader": "Bootloader",
        "edl": "9008 (EDL)",
        "brom": "BROM",
        "offline": "离线",
        "none": "未连接",
    }
    return mapping.get(mode, mode or "未知")


def connection_summary() -> Dict[str, str]:
    mode, serial = detect_connection_mode()
    cn = _mode_cn(mode)
    serial = serial or ""
    summary: Dict[str, str] = {
        "mode": mode,
        "serial": serial,
        "connected": mode in ("system", "sideload", "fastbootd", "bootloader", "edl", "brom"),
        "status_conn": "",
        "status_mode": "",
        "status_line": "",
        "status_color": "#86909c",
        "banner_state": "disconnected",
    }
    if mode in ("system", "sideload"):
        summary["status_conn"] = f"设备：已连接（{cn}）"
        summary["status_mode"] = f"模式：{cn}"
        summary["status_line"] = f"已连接：{cn}"
        summary["status_color"] = "#00b42a"
        summary["banner_state"] = "connected"
    elif mode in ("fastbootd", "bootloader"):
        summary["status_conn"] = f"设备：已连接（{cn}）"
        summary["status_mode"] = f"模式：{cn}"
        summary["status_line"] = f"已连接：{cn}"
        summary["status_color"] = "#00b42a"
        summary["banner_state"] = "connected"
    elif mode in ("edl", "brom"):
        # Port-based modes: no ADB/Fastboot, but device exists at a serial port.
        port = f"（{serial}）" if serial else ""
        summary["status_conn"] = f"设备：已连接（端口{port}）"
        summary["status_mode"] = f"模式：{cn}"
        summary["status_line"] = f"已连接：{cn}{port}"
        summary["status_color"] = "#fa8c16"
        summary["banner_state"] = "connected"
    elif mode == "offline":
        summary["status_conn"] = "设备：已连接但未授权"
        summary["status_mode"] = "模式：离线"
        summary["status_line"] = "设备已连接但离线/未授权，请在手机上授权 USB 调试"
        summary["status_color"] = "#ff4d4f"
        summary["banner_state"] = "disconnected"
    else:
        summary["status_conn"] = "设备：未连接"
        summary["status_mode"] = "模式：未知"
        summary["status_line"] = "未发现已连接设备"
        summary["status_color"] = "#86909c"
        summary["banner_state"] = "disconnected"
    return summary


def collect_overall_info() -> Dict[str, str]:
    summary = connection_summary()
    mode = summary["mode"]
    serial = summary["serial"]
    info: Dict[str, str] = {"connection_status": mode, "serial": serial}
    if mode in ("system", "sideload") and serial:
        dev = get_device_info(serial)
        info.update(dev)
    elif mode in ("fastbootd", "bootloader"):
        # Query via fastboot where possible (使用较短的超时)
        def clean_fastboot_output(output):
            """去除fastboot输出中的冗余前缀和后缀"""
            if not output:
                return output
            
            # 处理多行输出，只取第一行（fastboot getvar通常第一行是结果，后面是finished）
            lines = output.strip().split('\n')
            if not lines:
                return output
                
            first_line = lines[0].strip()
            
            # 去除 (bootloader) 前缀
            clean_output = first_line.replace("(bootloader) ", "")
            
            # 如果第一行包含finish，则截断
            if 'finish' in clean_output.lower():
                finish_pos = clean_output.lower().find('finish')
                clean_output = clean_output[:finish_pos].strip()
            
            return clean_output
        
        prod = _fastboot(["getvar", "product"], timeout=2) or ""
        prod = clean_fastboot_output(prod)
        # 提取 product: 后面的值，去除冗余前缀
        if "product:" in prod:
            product_value = prod.split("product:")[1].strip()
            info["product"] = product_value
        else:
            info["product"] = prod
        
        cur_slot = _fastboot(["getvar", "current-slot"], timeout=2) or ""
        cur_slot = clean_fastboot_output(cur_slot)
        # 提取 current-slot: 或 SLOT: 后面的值，去除冗余前缀
        if "current-slot:" in cur_slot:
            slot_value = cur_slot.split("current-slot:")[1].strip()
            info["current_slot"] = slot_value
        elif "SLOT:" in cur_slot:
            slot_value = cur_slot.split("SLOT:")[1].strip()
            info["current_slot"] = slot_value
        else:
            info["current_slot"] = cur_slot
        
        status = "unknown"
        # 使用 fastboot getvar unlocked 检测bootloader锁状态
        unlock_state = _fastboot(["getvar", "unlocked"], timeout=2) or ""
        unlock_state = clean_fastboot_output(unlock_state)
        if "yes" in unlock_state.lower():
            status = "unlocked"
        elif "no" in unlock_state.lower():
            status = "locked"
        
        if status == "unknown":
            # 备用方法：尝试 secure 变量
            boot_state = _fastboot(["getvar", "secure"], timeout=2) or ""
            boot_state = clean_fastboot_output(boot_state)
            if "no" in boot_state.lower():
                status = "unlocked"
            elif "yes" in boot_state.lower():
                status = "locked"
        info["bootloader_unlock"] = status
        # Not available in fastboot mode
        info.setdefault("battery", "-")
        info.setdefault("storage_data", "-")
        info.setdefault("kernel", "-")
        info.setdefault("android_version", "-")
    info.update(summary)
    return info
