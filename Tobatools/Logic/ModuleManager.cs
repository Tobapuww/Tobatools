using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Tobatools.Services;

namespace Tobatools.Logic
{
    public class ModuleInfo
    {
        public string Id { get; set; } = "";
        public string Name { get; set; } = "";
        public string Version { get; set; } = "";
        public string VersionCode { get; set; } = "";
        public string Author { get; set; } = "";
        public string Description { get; set; } = "";
        public bool Enabled { get; set; } = true;
        public bool Removed { get; set; }
        public string Manager { get; set; } = "magisk"; // magisk | ksu
    }

    /// <summary>Magisk / KernelSU 模块管理器（C# 移植，基于 adb + su 命令）。</summary>
    public class ModuleManager
    {
        public Action<string>? Log { get; set; }
        public Action<string, string>? StepStart { get; set; }
        public Action<string, bool, string>? StepFinish { get; set; }

        private void Emit(string s) { try { Log?.Invoke(s); } catch { } }

        private static string RequireSystemSerial()
        {
            var (mode, serial) = AdbService.DetectConnectionMode();
            if (mode != "system" || string.IsNullOrEmpty(serial))
                throw new InvalidOperationException("请确保设备处于系统模式并已连接 ADB");
            return serial;
        }

        private static string Su(string serial, string cmd, int timeout = 30)
        {
            return AdbService.AdbShellSerial(serial, $"su -c \"{cmd}\"", timeout) ?? "";
        }

        public string DetectManager()
        {
            var serial = RequireSystemSerial();
            try { if (Su(serial, "command -v ksu >/dev/null 2>&1 && echo ksu || echo", 8).Trim().Contains("ksu")) return "ksu"; } catch { }
            try { if (Su(serial, "command -v ksud >/dev/null 2>&1 && echo ksud || echo", 8).Trim().Contains("ksud")) return "ksu"; } catch { }
            try { if (Su(serial, "[ -d /data/adb/ksu/modules ] && echo ksu_dir || echo", 8).Trim().Contains("ksu_dir")) return "ksu"; } catch { }
            try { if (Su(serial, "command -v magisk >/dev/null 2>&1 && echo magisk || echo", 8).Trim().Contains("magisk")) return "magisk"; } catch { }
            try { if (Su(serial, "[ -d /data/adb/modules ] && echo magisk_dir || echo", 8).Trim().Contains("magisk_dir")) return "magisk"; } catch { }
            return "none";
        }

        private static string[] ModuleBaseDirs(string manager)
        {
            if (manager == "magisk") return new[] { "/data/adb/modules" };
            if (manager == "ksu") return new[] { "/data/adb/ksu/modules", "/data/adb/modules" };
            return Array.Empty<string>();
        }

        public List<ModuleInfo> ListModules()
        {
            var serial = RequireSystemSerial();
            var manager = DetectManager();
            if (manager == "none")
                throw new InvalidOperationException("未检测到 Magisk 或 KernelSU 环境（需要 Root，并允许 Shell 获取 su 权限）");
            var modules = new Dictionary<string, ModuleInfo>();
            foreach (var baseDir in ModuleBaseDirs(manager))
            {
                string raw;
                try { raw = Su(serial, $"ls -1 {baseDir} 2>/dev/null", 10); } catch { continue; }
                foreach (var midRaw in raw.Split('\n'))
                {
                    var mid = midRaw.Trim();
                    if (mid.Length == 0 || mid is "." or "..") continue;
                    if (modules.ContainsKey(mid)) continue;
                    var mdir = $"{baseDir}/{mid}";
                    try
                    {
                        var isDir = Su(serial, $"[ -d {mdir} ] && echo d || echo f", 8).Trim();
                        if (!isDir.StartsWith("d")) continue;
                    }
                    catch { continue; }

                    var name = mid; var version = ""; var versionCode = ""; var author = ""; var desc = "";
                    try
                    {
                        var prop = Su(serial, $"cat {mdir}/module.prop 2>/dev/null", 10);
                        foreach (var line in prop.Split('\n'))
                        {
                            if (!line.Contains('=')) continue;
                            var parts = line.Split('=', 2);
                            var k = parts[0].Trim(); var v = parts[1].Trim();
                            switch (k)
                            {
                                case "name": name = v.Length > 0 ? v : name; break;
                                case "version": version = v; break;
                                case "versionCode": versionCode = v; break;
                                case "author": author = v; break;
                                case "description": desc = v; break;
                            }
                        }
                    }
                    catch { }

                    var enabled = true;
                    try { enabled = Su(serial, $"[ -f {mdir}/disable ] && echo 1 || echo 0", 8).Trim() != "1"; } catch { }
                    var removed = false;
                    try { removed = Su(serial, $"[ -f {mdir}/remove ] && echo 1 || echo 0", 8).Trim() == "1"; } catch { }

                    modules[mid] = new ModuleInfo
                    {
                        Id = mid, Name = name, Version = version, VersionCode = versionCode,
                        Author = author, Description = desc, Enabled = enabled, Removed = removed, Manager = manager
                    };
                }
            }
            // 排序与 Python 一致：(removed is False, enabled is False, name, id) 升序，
            // 即“待移除”的模块排在最前，其次按是否禁用、名称、ID。
            return modules.Values
                .OrderBy(x => x.Removed ? 0 : 1)
                .ThenBy(x => x.Enabled ? 0 : 1)
                .ThenBy(x => x.Name.ToLowerInvariant())
                .ThenBy(x => x.Id.ToLowerInvariant())
                .ToList();
        }

        private static string FindModuleDir(string serial, string manager, string moduleId)
        {
            foreach (var baseDir in ModuleBaseDirs(manager))
            {
                var mdir = $"{baseDir}/{moduleId}";
                try
                {
                    if (Su(serial, $"[ -d {mdir} ] && echo 1 || echo 0", 8).Trim() == "1") return mdir;
                }
                catch { }
            }
            return "";
        }

        public void SetEnabled(string moduleId, bool enabled)
        {
            var sid = Guid.NewGuid().ToString("N");
            var action = enabled ? "启用" : "禁用";
            StepStart?.Invoke(sid, $"{action}模块: {moduleId}");
            try
            {
                var serial = RequireSystemSerial();
                var manager = DetectManager();
                if (manager == "none") throw new InvalidOperationException("未检测到 Magisk 或 KernelSU");
                var target = FindModuleDir(serial, manager, moduleId);
                if (target.Length == 0) throw new InvalidOperationException("未找到模块目录: " + moduleId);
                if (enabled) Su(serial, $"rm -f {target}/disable", 20);
                else Su(serial, $"touch {target}/disable", 20);
                StepFinish?.Invoke(sid, true, "");
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(sid, false, e.Message);
                throw;
            }
        }

        public void RemoveModule(string moduleId)
        {
            var sid = Guid.NewGuid().ToString("N");
            StepStart?.Invoke(sid, $"移除模块: {moduleId}");
            try
            {
                var serial = RequireSystemSerial();
                var manager = DetectManager();
                if (manager == "none") throw new InvalidOperationException("未检测到 Magisk 或 KernelSU");
                var target = FindModuleDir(serial, manager, moduleId);
                if (target.Length == 0) throw new InvalidOperationException("未找到模块目录: " + moduleId);
                Su(serial, $"touch {target}/remove", 20);
                StepFinish?.Invoke(sid, true, "");
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(sid, false, e.Message);
                throw;
            }
        }

        public void UndoRemoveModule(string moduleId)
        {
            var sid = Guid.NewGuid().ToString("N");
            StepStart?.Invoke(sid, $"撤销移除: {moduleId}");
            try
            {
                var serial = RequireSystemSerial();
                var manager = DetectManager();
                if (manager == "none") throw new InvalidOperationException("未检测到 Magisk 或 KernelSU");
                var target = FindModuleDir(serial, manager, moduleId);
                if (target.Length == 0) throw new InvalidOperationException("未找到模块目录: " + moduleId);
                Su(serial, $"rm -f {target}/remove", 20);
                StepFinish?.Invoke(sid, true, "");
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(sid, false, e.Message);
                throw;
            }
        }

        public string BackupModule(string moduleId, string localDestDir)
        {
            var sid = Guid.NewGuid().ToString("N");
            StepStart?.Invoke(sid, $"备份模块: {moduleId}");
            try
            {
                var serial = RequireSystemSerial();
                var manager = DetectManager();
                if (manager == "none") throw new InvalidOperationException("未检测到 Magisk 或 KernelSU");
                var target = FindModuleDir(serial, manager, moduleId);
                if (target.Length == 0) throw new InvalidOperationException("未找到模块目录: " + moduleId);
                var ts = DateTime.Now.ToString("yyyyMMdd_HHmmss");
                var remoteDir = "/sdcard/TobatoolsBackups/modules";
                var remoteFile = $"{remoteDir}/{moduleId}_{ts}.tar.gz";
                Su(serial, $"mkdir -p {remoteDir}", 20);
                var tarCmd = $"tar -czf '{remoteFile}' -C '{target}' .";
                var outStr = Su(serial, $"{tarCmd} 2>/dev/null || busybox tar -czf '{remoteFile}' -C '{target}' . 2>/dev/null || toybox tar -czf '{remoteFile}' -C '{target}' . 2>/dev/null", 120);
                foreach (var line in outStr.Split('\n')) if (line.Trim().Length > 0) Emit(line);
                Directory.CreateDirectory(localDestDir);
                var localFile = Path.Combine(localDestDir, Path.GetFileName(remoteFile));
                var (ok, msg) = AdbService.AdbPullFileSerial(serial, remoteFile, localFile, 600);
                if (!ok) throw new InvalidOperationException("拉取备份失败: " + msg);
                StepFinish?.Invoke(sid, true, "");
                return localFile;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(sid, false, e.Message);
                throw;
            }
        }

        public void InstallModuleZip(string zipPath)
        {
            var z = new FileInfo(zipPath);
            var sid = Guid.NewGuid().ToString("N");
            StepStart?.Invoke(sid, $"安装模块: {z.Name}");
            try
            {
                if (!z.Exists) throw new FileNotFoundException(zipPath);
                var serial = RequireSystemSerial();
                var manager = DetectManager();
                if (manager == "none") throw new InvalidOperationException("未检测到 Magisk 或 KernelSU");
                var remote = $"/sdcard/{z.Name}";
                Emit("推送模块压缩包到设备...");
                var (rc, pushOut) = AdbService.RunAdb(new[] { "-s", serial, "push", zipPath, remote }, 600);
                foreach (var line in pushOut.Split('\n')) if (line.Trim().Length > 0) Emit(line);

                if (manager == "magisk")
                {
                    Emit("开始安装 (Magisk)...");
                    var outStr = Su(serial, $"magisk --install-module '{remote}'", 600);
                    foreach (var line in outStr.Split('\n')) if (line.Trim().Length > 0) Emit(line);
                    StepFinish?.Invoke(sid, true, "Magisk安装完成");
                    return;
                }

                Emit("开始安装 (KernelSU)...");
                var hasKsu = Su(serial, "command -v ksu >/dev/null 2>&1 && echo 1 || echo 0", 8).Trim() == "1";
                var hasKsud = Su(serial, "command -v ksud >/dev/null 2>&1 && echo 1 || echo 0", 8).Trim() == "1";
                var cmds = new List<string>();
                if (hasKsu) { cmds.Add($"ksu module install '{remote}'"); cmds.Add($"ksu module install --zip '{remote}'"); }
                if (hasKsud) { cmds.Add($"ksud module install '{remote}'"); cmds.Add($"ksud module install --zip '{remote}'"); }
                if (cmds.Count == 0)
                    throw new InvalidOperationException("未找到 KernelSU 命令行工具（ksu/ksud）。请使用 KernelSU 管理器手动安装模块。");
                var lastOut = "";
                var success = false;
                foreach (var c in cmds)
                {
                    var outStr = Su(serial, c, 600);
                    lastOut = outStr;
                    foreach (var line in outStr.Split('\n')) if (line.Trim().Length > 0) Emit(line);
                    var lo = outStr.ToLowerInvariant();
                    if (lo.Contains("not found") || lo.Contains("unknown command") || lo.Contains("usage:")) continue;
                    success = true;
                    break;
                }
                if (success) { StepFinish?.Invoke(sid, true, "KernelSU安装完成"); return; }
                if (lastOut.Length > 0) throw new InvalidOperationException("KernelSU 安装命令执行失败：" + lastOut.Trim());
                throw new InvalidOperationException("KernelSU 安装命令执行失败");
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(sid, false, e.Message);
                throw;
            }
        }

        public void BatchInstall(IEnumerable<string> zipPaths)
        {
            foreach (var p in zipPaths)
            {
                Emit("");
                Emit("安装: " + p);
                InstallModuleZip(p);
            }
        }
    }
}
