import subprocess
import re
from typing import Dict, List, Tuple
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
BIN_DIR = ROOT_DIR / "bin"
ADB_BIN = BIN_DIR / "adb.exe" if (BIN_DIR / "adb.exe").exists() else BIN_DIR / "adb"
FASTBOOT_BIN = BIN_DIR / "fastboot.exe" if (BIN_DIR / "fastboot.exe").exists() else BIN_DIR / "fastboot"


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
        return out.decode(errors='ignore').strip()
    except subprocess.TimeoutExpired:
        return ""  # 超时，返回空
    except FileNotFoundError:
        return ""  # 命令不存在
    except Exception:
        return ""  # 其他错误


def check_adb_available() -> bool:
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    return bool(_run([adb, "version"]))


def list_devices() -> List[str]:
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    out = _run([adb, "devices"], timeout=2)  # 减少超时到 2 秒
    serials: List[str] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _getprop(serial: str, key: str) -> str:
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    return _run([adb, "-s", serial, "shell", "getprop", key], timeout=3)  # 减少超时到 3 秒


def _shell(serial: str, cmd: str) -> str:
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    return _run([adb, "-s", serial, "shell", cmd], timeout=8)


def _adb_get_state(serial: str) -> str:
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    return _run([adb, "-s", serial, "get-state"], timeout=2)  # 减少超时到 2 秒


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

    return ("none", found_serial)


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
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    p = path or "/"
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
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    try:
        out = _run([adb, "pull", remote, local], timeout=600)
        if out is None:
            out = ""
        # adb pull returns 0 already if _run succeeded; provide brief message
        return True, out or "完成"
    except Exception as e:
        return False, str(e)


# -------- Mobile-side Ops (ADB shell) --------
def _adb_shell(args: List[str], timeout: int = 20) -> str:
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    return _run([adb, "shell"] + args, timeout=timeout)


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
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    try:
        out = _run([adb, "pull", remote, local_dest], timeout=3600)
        if out is None:
            out = ""
        return True, out or "完成"
    except Exception as e:
        return False, str(e)


def push_path(local_path: str, remote_dir: str) -> Tuple[bool, str]:
    """adb push local_path remote_dir (支持文件或目录)."""
    adb = str(ADB_BIN) if ADB_BIN.exists() else "adb"
    try:
        out = _run([adb, "push", local_path, remote_dir], timeout=3600)
        if out is None:
            out = ""
        return True, out or "完成"
    except Exception as e:
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
        "connected": mode in ("system", "sideload", "fastbootd", "bootloader"),
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
        prod = _fastboot(["getvar", "product"], timeout=2) or ""
        info["product"] = prod.replace("(bootloader) ", "").strip()
        cur_slot = _fastboot(["getvar", "current-slot"], timeout=2) or ""
        info["current_slot"] = cur_slot.replace("(bootloader) ", "").strip()
        status = "unknown"
        boot_state = _fastboot(["getvar", "secure"], timeout=2) or ""
        if "no" in boot_state.lower():
            status = "unlocked"
        elif "yes" in boot_state.lower():
            status = "locked"
        if status == "unknown":
            # Try OEM device-info (OnePlus/Pixel etc.)
            devinfo = _fastboot(["oem", "device-info"], timeout=3) or ""
            lo = devinfo.lower()
            if "device unlocked: true" in lo or "unlocked: yes" in lo:
                status = "unlocked"
            elif "device unlocked: false" in lo or "unlocked: no" in lo:
                status = "locked"
        info["bootloader_unlock"] = status
        # Not available in fastboot mode
        info.setdefault("battery", "-")
        info.setdefault("storage_data", "-")
        info.setdefault("kernel", "-")
        info.setdefault("android_version", "-")
    info.update(summary)
    return info
