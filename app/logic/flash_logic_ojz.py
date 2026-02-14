"""欧加真（OPPO / OnePlus / realme）刷机逻辑"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Iterable, Literal, Optional


class OJZFlashLogic:
    """欧加真刷机逻辑"""

    def __init__(self, log_callback: Callable[[str], None]):
        self.log = log_callback
        self._stop_flag = False
        self._process: Optional[subprocess.Popen] = None
        self._fastboot_path = self._resolve_fastboot()

    def stop(self):
        """请求停止当前操作"""
        self._stop_flag = True
        p = self._process
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def _resolve_fastboot(self) -> str:
        try:
            from app.services import adb_service

            fb = getattr(adb_service, "FASTBOOT_BIN", None)
            if fb is not None:
                try:
                    if hasattr(fb, "exists") and fb.exists():
                        return str(fb)
                except Exception:
                    pass
        except Exception:
            pass
        return "fastboot"

    @staticmethod
    def _add_images_dir() -> Path:
        try:
            root = Path(__file__).resolve().parents[2]
        except Exception:
            root = Path(".").resolve()
        return root / "bin" / "add_images"

    def _wait_for_mode(self, want: str, *, timeout: float = 120.0) -> bool:
        try:
            from app.services import adb_service
        except Exception as e:
            self.log(f"错误: 无法导入 adb_service: {e}")
            return False

        end = time.time() + float(timeout)
        last = ""
        while time.time() < end:
            if self._stop_flag:
                return False
            try:
                mode, serial = adb_service.detect_connection_mode()
                cur = f"{mode}:{serial}"
                if cur != last:
                    last = cur
                    self.log(f"检测设备模式: {mode} ({serial})")
                if mode == want:
                    return True
            except Exception:
                pass
            time.sleep(1.0)
        self.log(f"错误: 等待进入 {want} 模式超时")
        return False

    def _sleep_interruptible(self, seconds: float, *, step: float = 0.2) -> bool:
        end = time.time() + float(seconds)
        while time.time() < end:
            if self._stop_flag:
                return False
            time.sleep(step)
        return True

    def _run_fastboot(self, args: list[str], *, timeout: Optional[float] = None) -> tuple[int, str]:
        if self._stop_flag:
            return 1, "cancelled"

        cmd = [self._fastboot_path] + list(args)
        self.log(f"$ {' '.join(cmd)}")

        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

        out_lines: list[str] = []
        buf = ""
        try:
            assert self._process.stdout is not None
            while True:
                if self._stop_flag:
                    try:
                        self._process.terminate()
                    except Exception:
                        pass
                    return 1, "cancelled"

                chunk = self._process.stdout.read(256)
                if chunk:
                    buf += chunk
                    while True:
                        m = re.search(r"[\r\n]", buf)
                        if not m:
                            break
                        idx = int(m.start())
                        s = buf[:idx].strip("\r\n")
                        buf = buf[idx + 1 :]
                        if s:
                            self.log(s)
                            out_lines.append(s)
                    continue

                if self._process.poll() is not None:
                    break
                time.sleep(0.02)

            tail = buf.strip("\r\n")
            if tail:
                self.log(tail)
                out_lines.append(tail)

            rc = self._process.wait(timeout=timeout)
            return int(rc), "\n".join(out_lines)
        finally:
            self._process = None

    @staticmethod
    def _extract_cow_partitions(fastboot_output: str) -> list[str]:
        out: set[str] = set()
        pat = re.compile(r"\(bootloader\)\s+(?:partition-(?:size|type)|is-logical):(?P<name>[^:]+):", re.IGNORECASE)
        for line in (fastboot_output or "").splitlines():
            if "-cow" not in (line or ""):
                continue
            m = pat.search(line)
            if not m:
                continue
            name = (m.group("name") or "").strip()
            if name:
                out.add(name)
        return sorted(out)

    @staticmethod
    def _parse_has_slot(fastboot_output: str) -> set[str]:
        # Lines like: (bootloader) has-slot:system:yes
        out: set[str] = set()
        pat = re.compile(r"\(bootloader\)\s+has-slot:(?P<name>[^:]+):(?P<val>yes|no)", re.IGNORECASE)
        for line in (fastboot_output or "").splitlines():
            m = pat.search(line)
            if not m:
                continue
            if (m.group("val") or "").lower() == "yes":
                name = (m.group("name") or "").strip()
                if name:
                    out.add(name)
        return out

    def _flash_to_slots(self, base: str, img_path: str, *, has_slot_bases: set[str], both_slots: bool) -> bool:
        if self._stop_flag:
            return False
        if both_slots and base in has_slot_bases:
            targets = [base + "_a", base + "_b"]
        else:
            targets = [self._partition_for_a_slot(base, has_slot=(base in has_slot_bases))]

        for part in targets:
            if self._stop_flag:
                return False
            rc, _ = self._run_fastboot(["flash", part, img_path])
            if rc != 0:
                self.log(f"错误: 刷写失败: {Path(img_path).name} -> {part}")
                return False
        return True

    def _flash_fastbootd_repair(self, images_dir: str, *, continue_logical: bool) -> bool:
        if not images_dir or not Path(images_dir).is_dir():
            self.log("错误: 请先加载固件（散包目录无效）")
            return False

        if continue_logical:
            if not self._wait_for_mode("fastbootd", timeout=120):
                return False
            time.sleep(15)
            logical_bases = {
                "odm",
                "odm_dlkm",
                "product",
                "system",
                "system_dlkm",
                "system_ext",
                "vendor",
                "vendor_dlkm",
                "my_bigball",
                "my_carrier",
                "my_engineering",
                "my_heytap",
                "my_manifest",
                "my_product",
                "my_region",
                "my_stock",
                "my_company",
                "my_preload",
            }

            self.log("获取分区表信息...")
            rc, out = self._run_fastboot(["getvar", "all"])
            if rc != 0:
                self.log("错误: 获取分区表失败")
                return False
            has_slot_bases = self._parse_has_slot(out)

            cow_parts = self._extract_cow_partitions(out)
            if cow_parts:
                self.log(f"检测到 -cow 分区数量: {len(cow_parts)}")
                for name in cow_parts:
                    if self._stop_flag:
                        return False
                    rc_del, _ = self._run_fastboot(["delete-logical-partition", name])
                    if rc_del != 0:
                        self.log(f"警告: 删除 -cow 分区失败: {name}")
            else:
                self.log("未检测到 -cow 分区")

            self.log("开始刷写逻辑分区（仅 A 槽）...")

            img_dir = Path(images_dir)
            add_dir = self._add_images_dir()

            for base in sorted(logical_bases):
                if self._stop_flag:
                    return False

                img_path = img_dir / f"{base}.img"
                if not img_path.exists():
                    if base in {"my_company", "my_preload"}:
                        cand = add_dir / f"{base}.img"
                        if cand.exists():
                            img_path = cand
                            self.log(f"补全分区镜像: 使用 add_images/{base}.img")

                if not img_path.exists():
                    # 仍然允许缺失（常见情况：某些分区在散包中不存在）
                    self.log(f"未找到镜像，跳过: {base}.img")
                    continue

                part = self._partition_for_a_slot(base, has_slot=(base in has_slot_bases))
                rc2, _ = self._run_fastboot(["flash", part, str(img_path)])
                if rc2 != 0:
                    self.log(f"错误: 刷写失败: {img_path.name} -> {part}")
                    return False

            self.log("设置启动槽位为 A...")
            rc_act, _ = self._run_fastboot(["set_active", "a"])
            if rc_act != 0:
                self.log("警告: 设置启动槽位失败（将继续）")
            return True

        # stage1: bootloader only
        if not self._wait_for_mode("bootloader", timeout=120):
            return False

        exclude_logical = {
            "odm",
            "odm_dlkm",
            "product",
            "system",
            "system_dlkm",
            "system_ext",
            "vendor",
            "vendor_dlkm",
            "my_bigball",
            "my_carrier",
            "my_engineering",
            "my_heytap",
            "my_manifest",
            "my_product",
            "my_region",
            "my_stock",
            "my_company",
            "my_preload",
        }

        self.log("获取分区表信息...")
        rc, out = self._run_fastboot(["getvar", "all"])
        if rc != 0:
            self.log("错误: 获取分区表失败")
            return False
        has_slot_bases = self._parse_has_slot(out)

        self.log("开始修复刷写（bootloader 模式，A/B 都刷，逻辑分区跳过）...")
        for img in self._iter_img_files(images_dir):
            if self._stop_flag:
                return False
            stem = img.stem
            if stem in exclude_logical:
                self.log(f"fastbootd修复: 跳过逻辑分区 {stem}.img")
                continue
            if not self._flash_to_slots(stem, str(img), has_slot_bases=has_slot_bases, both_slots=True):
                return False

        self.log("刷写完成，重启到 fastbootd...")
        rc, _ = self._run_fastboot(["reboot", "fastboot"])
        if rc != 0:
            self.log("错误: 重启到 fastbootd 失败")
            return False

        if not self._wait_for_mode("fastbootd", timeout=120):
            return False
        time.sleep(15)

        self.log("设置启动槽位为 A...")
        rc_act, _ = self._run_fastboot(["set_active", "a"])
        if rc_act != 0:
            self.log("警告: 设置启动槽位失败（将继续）")
        return True

    def _flash_super_partition_repair(self, images_dir: str, *, super_img_path: str) -> bool:
        if not images_dir or not Path(images_dir).is_dir():
            self.log("错误: 请先加载固件（散包目录无效）")
            return False

        super_img = Path(super_img_path or "").expanduser()
        if not super_img_path or not super_img.exists() or not super_img.is_file():
            self.log("错误: 未选择有效的 super 镜像文件")
            return False

        logical_bases = {
            "odm",
            "odm_dlkm",
            "product",
            "system",
            "system_dlkm",
            "system_ext",
            "vendor",
            "vendor_dlkm",
            "my_bigball",
            "my_carrier",
            "my_engineering",
            "my_heytap",
            "my_manifest",
            "my_product",
            "my_region",
            "my_stock",
            "my_company",
            "my_preload",
        }

        # stage1: bootloader
        if not self._wait_for_mode("bootloader", timeout=120):
            return False

        self.log("获取分区表信息...")
        rc, out = self._run_fastboot(["getvar", "all"])
        if rc != 0:
            self.log("错误: 获取分区表失败")
            return False
        has_slot_bases = self._parse_has_slot(out)

        self.log("开始 super 修复：bootloader 模式刷写（A/B 都刷，逻辑分区跳过）...")
        for img in self._iter_img_files(images_dir):
            if self._stop_flag:
                return False
            stem = img.stem
            if stem in logical_bases:
                self.log(f"super修复: 跳过逻辑分区 {stem}.img")
                continue
            if not self._flash_to_slots(stem, str(img), has_slot_bases=has_slot_bases, both_slots=True):
                return False

        self.log(f"刷写 super 镜像: {super_img.name}")
        rc_sup, _ = self._run_fastboot(["flash", "super", str(super_img)])
        if rc_sup != 0:
            self.log("错误: flash super 失败")
            return False

        self.log("重启到 fastbootd...")
        rc_rb, _ = self._run_fastboot(["reboot", "fastboot"])
        if rc_rb != 0:
            self.log("错误: 重启到 fastbootd 失败")
            return False
        if not self._wait_for_mode("fastbootd", timeout=120):
            return False
        time.sleep(15)

        self.log("获取分区表信息...")
        rc2, out2 = self._run_fastboot(["getvar", "all"])
        if rc2 != 0:
            self.log("错误: 获取分区表失败")
            return False
        has_slot_bases2 = self._parse_has_slot(out2)

        self.log("创建逻辑分区（A/B）...")
        for base in sorted(logical_bases):
            if self._stop_flag:
                return False
            for slot in ("a", "b"):
                name = f"{base}_{slot}"
                rc_c, _ = self._run_fastboot(["create-logical-partition", name, "1"])
                if rc_c != 0:
                    self.log(f"错误: 创建逻辑分区失败: {name}")
                    return False

        self.log("开始刷写逻辑分区（仅 A 槽）...")
        img_dir = Path(images_dir)
        add_dir = self._add_images_dir()
        for base in sorted(logical_bases):
            if self._stop_flag:
                return False

            img_path = img_dir / f"{base}.img"
            if not img_path.exists():
                if base in {"my_company", "my_preload"}:
                    cand = add_dir / f"{base}.img"
                    if cand.exists():
                        img_path = cand
                        self.log(f"补全分区镜像: 使用 add_images/{base}.img")

            if not img_path.exists():
                self.log(f"未找到镜像，跳过: {base}.img")
                continue

            part = self._partition_for_a_slot(base, has_slot=(base in has_slot_bases2))
            rc_f, _ = self._run_fastboot(["flash", part, str(img_path)])
            if rc_f != 0:
                self.log(f"错误: 刷写失败: {img_path.name} -> {part}")
                return False

        self.log("设置启动槽位为 A...")
        rc_act, _ = self._run_fastboot(["set_active", "a"])
        if rc_act != 0:
            self.log("警告: 设置启动槽位失败（将继续）")
        return True

    @staticmethod
    def _iter_img_files(images_dir: str) -> Iterable[Path]:
        p = Path(images_dir)
        if not p.exists() or not p.is_dir():
            return []
        return sorted([x for x in p.iterdir() if x.is_file() and x.suffix.lower() == ".img"], key=lambda x: x.name.lower())

    @staticmethod
    def _partition_for_a_slot(stem: str, *, has_slot: bool) -> str:
        s = (stem or "").strip()
        if not s:
            return s
        if s.endswith("_a"):
            return s
        if s.endswith("_b"):
            return s[:-2] + "_a"
        return (s + "_a") if has_slot else s

    def _flash_regular_upgrade_downgrade(
        self,
        images_dir: str,
        *,
        wipe: bool,
        avb_relaxed: bool,
        anti_fuse: bool,
    ) -> bool:
        if not images_dir or not Path(images_dir).is_dir():
            self.log("错误: 请先加载固件（散包目录无效）")
            return False

        self.log("准备重启到 fastbootd...")
        rc, _ = self._run_fastboot(["reboot", "fastboot"])
        if rc != 0:
            self.log("错误: 重启到 fastbootd 失败")
            return False
        if not self._wait_for_mode("fastbootd", timeout=120):
            return False
        time.sleep(15)

        self.log("获取分区表信息...")
        rc, out = self._run_fastboot(["getvar", "all"])
        if rc != 0:
            self.log("错误: 获取分区表失败")
            return False

        has_slot_bases = self._parse_has_slot(out)

        cow_parts = self._extract_cow_partitions(out)
        if cow_parts:
            self.log(f"检测到 -cow 分区数量: {len(cow_parts)}")
        else:
            self.log("未检测到 -cow 分区（可能已经清理或 fastboot 输出格式不同）")

        # Delete *-cow partitions ONLY IF they are explicitly listed in getvar output.
        # Do not speculate a/b variants to avoid noisy failures on devices without COW partitions.
        deleted_any = False
        for name in cow_parts:
            if self._stop_flag:
                self.log("已取消")
                return False
            rc2, _ = self._run_fastboot(["delete-logical-partition", name])
            if rc2 == 0:
                deleted_any = True
        if deleted_any:
            self.log("-cow 分区清理完成")

        modem_img: Optional[Path] = None
        self.log("开始刷写散包镜像到 A 槽...")
        anti_fuse_bases = {"abl", "xbl", "xbl_ramdump", "xbl_config"}
        for img in self._iter_img_files(images_dir):
            if self._stop_flag:
                self.log("已取消")
                return False
            stem = img.stem
            if stem.lower().startswith("modem"):
                modem_img = img
                continue

            if anti_fuse and stem in anti_fuse_bases:
                self.log(f"防熔断模式: 跳过刷写 {stem}.img")
                continue

            is_vbmeta_img = stem in {"vbmeta", "vbmeta_system", "vbmeta_vendor"}

            if avb_relaxed and is_vbmeta_img:
                # 宽容 AVB：A/B 都刷（若该分区有槽位），使用 disable flags
                targets: list[str]
                if stem in has_slot_bases:
                    targets = [stem + "_a", stem + "_b"]
                else:
                    targets = [stem]
                for part_name in targets:
                    rc_avb, _ = self._run_fastboot(
                        [
                            "flash",
                            part_name,
                            "--disable-verity",
                            "--disable-verification",
                            str(img),
                        ]
                    )
                    if rc_avb != 0:
                        self.log(f"错误: 刷写失败: {img.name} -> {part_name}")
                        return False
                continue

            part_base = stem
            try:
                if stem.endswith("_a"):
                    part_base = stem[:-2]
                elif stem.endswith("_b"):
                    part_base = stem[:-2]
            except Exception:
                part_base = stem
            part = self._partition_for_a_slot(stem, has_slot=(part_base in has_slot_bases))
            rc3, _ = self._run_fastboot(["flash", part, str(img)])
            if rc3 != 0:
                self.log(f"错误: 刷写失败: {img.name} -> {part}")
                return False

        self.log("刷写完成，重启到 bootloader...")
        rc, _ = self._run_fastboot(["reboot", "bootloader"])
        if rc != 0:
            self.log("错误: 重启到 bootloader 失败")
            return False
        if not self._wait_for_mode("bootloader", timeout=120):
            return False
        time.sleep(15)

        if modem_img is not None:
            self.log(f"补刷 modem 分区: {modem_img.name}")
            modem_part = "modem_a" if ("modem" in has_slot_bases) else "modem"
            rc4, _ = self._run_fastboot(["flash", modem_part, str(modem_img)])
            if rc4 != 0:
                self.log("错误: 补刷 modem 失败")
                return False

        self.log("设置启动槽位为 A...")
        rc, _ = self._run_fastboot(["set_active", "a"])
        if rc != 0:
            self.log("警告: 设置启动槽位失败（将继续）")

        if wipe:
            self.log("执行 fastboot -w 清除数据分区...")
            rc, _ = self._run_fastboot(["-w"])
            if rc != 0:
                self.log("错误: fastboot -w 执行失败")
                return False

        self.log("重启设备...")
        rc, _ = self._run_fastboot(["reboot"])
        if rc != 0:
            self.log("警告: reboot 执行失败")
            return False
        return True

    def flash(
        self,
        package_path: str,
        sub_mode: Literal["常规升级/降级模式", "fastbootd模式修复", "super分区异常修复"],
        *,
        wipe: bool = False,
        avb_relaxed: bool = False,
        anti_fuse: bool = False,
        fastbootd_continue: bool = False,
        super_img_path: str = "",
    ) -> bool:
        """刷机入口"""
        if self._stop_flag:
            self.log("已取消")
            return False

        self.log("=" * 50)
        self.log(f"欧加真刷机模式：{sub_mode}")
        self.log("=" * 50)

        if sub_mode == "常规升级/降级模式":
            ok = self._flash_regular_upgrade_downgrade(
                package_path,
                wipe=wipe,
                avb_relaxed=bool(avb_relaxed),
                anti_fuse=bool(anti_fuse),
            )
            return bool(ok)

        if sub_mode == "fastbootd模式修复":
            ok = self._flash_fastbootd_repair(package_path, continue_logical=bool(fastbootd_continue))
            return bool(ok)

        if sub_mode == "super分区异常修复":
            ok = self._flash_super_partition_repair(package_path, super_img_path=str(super_img_path or ""))
            return bool(ok)

        self.log(f"错误: 未知子模式: {sub_mode}")
        return False
