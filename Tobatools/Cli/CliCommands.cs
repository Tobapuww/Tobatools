using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Tobatools.Logic;
using Tobatools.Logic.ImageFactory;
using Tobatools.Services;

namespace Tobatools.Cli
{
    /// <summary>
    /// 调试用命令行子命令集合。仅用于开发期在真实设备上验证图形界面背后的逻辑，
    /// 不引入任何图形界面之外的新功能。
    /// </summary>
    public static class CliCommands
    {
        public static List<CliCommand> All() => new()
        {
            new("devices", "devices", "列出已连接的设备及各设备状态", Devices),
            new("info", "info [--serial <序列号>]", "输出设备详细信息（对应首页设备概览）", Info),
            new("shell", "shell --cmd <命令> [--serial <序列号>] [--timeout 毫秒]", "在设备上执行 shell 命令", Shell),
            new("setting", "setting --get|--put <命名空间> <键> [值]", "读写系统设置（settings get/put/delete）", Setting),
            new("misc", "misc <工具ID> [--dry-run]", "调用杂项工具的逻辑（如 animscale/fontscale/keysim）", Misc),
            new("modules", "modules --list | --enable <id> | --disable <id> | --remove <id>", "Magisk / KernelSU 模块管理", Modules),
            new("unbrick", "unbrick [--yes]", "执行异常模块修复（Magisk --remove-modules）", Unbrick),
            new("image", "image <super|dtbo|partitionfs|boot|datbr> <操作> [参数]", "镜像工厂离线处理", Image),
            new("payload", "payload --in <payload.bin> --out <目录> [--parts boot,system]", "提取 payload.bin", Payload),
            new("ofp", "ofp --in <固件.ofp> --out <目录>", "解密并提取 OFP 固件", Ofp),
            new("ext4dump", "ext4dump --in <镜像.img>", "转储 ext4 根目录条目（排查解析问题）", Ext4Dump),
#if ENABLE_FLASH
            new("flashplan", "flashplan --dir <镜像目录> [--wipe] [--keep-root] [--json <输出>]", "导出刷机计划（开发期核对与原版一致性，不执行刷写）", FlashPlan),
            new("flashguard", "flashguard", "实测刷机环境守卫：列出命中的远程控制软件（空即为可刷机）", FlashGuard),
            new("flashprobe", "flashprobe", "只读探测 fastboot 设备与模式（getvar is-userspace / product），不刷写", FlashProbe),
            new("flashextract", "flashextract --in <包> [--mode ota|legacy|newport|coloros17]", "测试固件包解包流程（只解包，不刷写）", FlashExtract),
#endif
        };

        // ---------------- devices / info / shell ----------------

        private static int Devices(string[] raw)
        {
            var states = AdbService.ListDeviceStates();
            if (states.Count == 0)
            {
                CliRunner.Warn("未发现任何设备。");
                return 1;
            }
            foreach (var (serial, state) in states)
                Console.WriteLine($"  {serial,-24} {state}");
            var (mode, active) = AdbService.DetectConnectionMode();
            CliRunner.Field("当前模式", AdbService.ModeCn(mode));
            CliRunner.Field("当前序列号", active);
            return 0;
        }

        private static int Info(string[] raw)
        {
            var a = CliArgs.Parse(raw);
            var (mode, serial) = AdbService.DetectConnectionMode();
            CliRunner.Section("连接");
            CliRunner.Field("模式", AdbService.ModeCn(mode));
            CliRunner.Field("序列号", serial);
            if (mode != "system" || string.IsNullOrEmpty(serial))
            {
                CliRunner.Warn("设备不在系统模式，无法读取详细属性。");
                return 1;
            }
            var info = AdbService.GetDeviceInfo(a.Get("serial", serial));
            CliRunner.Section("设备信息");
            CliRunner.Field("品牌", info.Brand);
            CliRunner.Field("型号", info.Model);
            CliRunner.Field("设备代号", info.Device);
            CliRunner.Field("产品", info.Product);
            CliRunner.Field("Android", info.AndroidVersion);
            CliRunner.Field("SDK", info.Sdk);
            CliRunner.Field("VNDK", info.Vndk);
            CliRunner.Field("版本号", info.BuildDisplay);
            CliRunner.Field("指纹", info.Fingerprint);
            CliRunner.Field("内核", info.Kernel);
            CliRunner.Field("基带", info.Baseband);
            CliRunner.Field("电池", info.Battery);
            CliRunner.Field("电池健康", info.BatteryHealthPercent);
            CliRunner.Field("存储", info.StorageData);
            CliRunner.Field("内存", info.MemorySummary);
            CliRunner.Field("分辨率", info.Resolution);
            CliRunner.Field("密度", info.DisplayDensity);
            CliRunner.Field("当前槽位", info.CurrentSlot);
            CliRunner.Field("BL 状态", info.BootloaderUnlock);
            CliRunner.Field("Root", info.RootStatus);
            CliRunner.Field("运行时长", info.Uptime);
            return 0;
        }

        private static int Shell(string[] raw)
        {
            var a = CliArgs.Parse(raw);
            var cmd = a.Require("cmd", "要在设备上执行的 shell 命令");
            var serial = a.Get("serial", "");
            if (serial.Length == 0)
            {
                var (mode, s) = AdbService.DetectConnectionMode();
                if (mode != "system" || string.IsNullOrEmpty(s))
                    throw new CliUsageException("设备不在系统模式，请先连接并开启 ADB 调试");
                serial = s;
            }
            var output = AdbService.AdbShellSerial(serial, cmd, a.GetInt("timeout", 20));
            Console.WriteLine(output);
            return 0;
        }

        private static int Setting(string[] raw)
        {
            // 文档用法是位置式：setting --get global <键>。
            // 通用解析器会把 global 当成 --get 的取值，这里先把
            // `--get|--put|--delete <命名空间>` 里的命名空间改写成位置参数再解析。
            var normalized = new List<string>();
            for (var i = 0; i < raw.Length; i++)
            {
                var token = raw[i];
                var isMode = token is "--get" or "--put" or "--delete";
                if (isMode
                    && i + 1 < raw.Length
                    && raw[i + 1] is "system" or "secure" or "global")
                {
                    normalized.Add(token);
                    normalized.Add("--namespace");
                    normalized.Add(raw[i + 1]);
                    i++;
                    continue;
                }
                normalized.Add(token);
            }

            var a = CliArgs.Parse(normalized.ToArray());
            var ns = a.Get("namespace", a.Pos(0, ""));
            var get = a.Get("get", "");
            var put = a.Get("put", "");
            var del = a.Get("delete", "");

            // --get 若仍是开关形态（--get 单独出现），键取位置参数。
            if (get.Length == 0 && a.Has("get")) get = a.Pos(0, "");
            if (put.Length == 0 && a.Has("put")) put = a.Pos(0, "");
            if (del.Length == 0 && a.Has("delete")) del = a.Pos(0, "");

            if (get.Length > 0)
            {
                RequireNamespace(ns);
                return PrintShell($"settings get {ns} {get}");
            }
            if (put.Length > 0)
            {
                RequireNamespace(ns);
                var value = a.Get("value", "") is { Length: > 0 } v0 ? v0 : a.Pos(1, "");
                if (value.Length == 0) throw new CliUsageException("缺少参数 --value（要写入的值）");
                return PrintShell($"settings put {ns} {put} {value}");
            }
            if (del.Length > 0)
            {
                RequireNamespace(ns);
                return PrintShell($"settings delete {ns} {del}");
            }
            throw new CliUsageException("需要 --get/--put/--delete 之一");
        }

        private static void RequireNamespace(string ns)
        {
            if (ns is not ("system" or "secure" or "global"))
                throw new CliUsageException("--namespace 必须是 system / secure / global");
        }

        private static int PrintShell(string cmd)
        {
            var (mode, serial) = AdbService.DetectConnectionMode();
            if (mode != "system" || string.IsNullOrEmpty(serial))
                throw new CliUsageException("设备不在系统模式，请先连接并开启 ADB 调试");
            var output = AdbService.AdbShellSerial(serial, cmd, 15);
            CliRunner.Detail(cmd);
            Console.WriteLine(output);
            return 0;
        }

        // ---------------- 杂项工具 ----------------

        private static int Misc(string[] raw)
        {
            var a = CliArgs.Parse(raw);
            var id = a.Pos(0, "");
            if (id.Length == 0) throw new CliUsageException("需要工具 ID，例如 animscale");
            var (mode, serial) = AdbService.DetectConnectionMode();
            if (mode != "system" || string.IsNullOrEmpty(serial))
                throw new CliUsageException("设备不在系统模式，请先连接并开启 ADB 调试");

            string Sh(string cmd, int timeout = 10) => AdbService.AdbShellSerial(serial, cmd, timeout) ?? "";

            switch (id.ToLowerInvariant())
            {
                case "animscale":
                {
                    foreach (var key in new[] { "window_animation_scale", "transition_animation_scale", "animator_duration_scale" })
                        CliRunner.Field(key, Sh($"settings get global {key}", 6).Trim());
                    return 0;
                }
                case "fontscale":
                {
                    CliRunner.Field("font_scale", Sh("settings get system font_scale", 6).Trim());
                    return 0;
                }
                case "timeout":
                {
                    var raw1 = Sh("settings get system screen_off_timeout", 6).Trim();
                    CliRunner.Field("screen_off_timeout", raw1);
                    if (long.TryParse(raw1, out var ms)) CliRunner.Field("等于秒数", (ms / 1000).ToString());
                    return 0;
                }
                case "display":
                {
                    CliRunner.Field("wm size", Sh("wm size", 10).Trim());
                    CliRunner.Field("wm density", Sh("wm density", 10).Trim());
                    CliRunner.Field("smallest_width", Sh("settings get secure smallest_width", 6).Trim());
                    return 0;
                }
                case "statusicons":
                {
                    CliRunner.Field("icon_blacklist", Sh("settings get secure icon_blacklist", 6).Trim());
                    return 0;
                }
                case "battery":
                {
                    var dump = Sh("dumpsys battery", 8);
                    foreach (var line in dump.Split('\n'))
                    {
                        var t = line.Trim();
                        if (t.StartsWith("level:") || t.StartsWith("temperature:") || t.StartsWith("plugged:") || t.StartsWith("status:"))
                            CliRunner.Detail(t);
                    }
                    return 0;
                }
                case "a11yreset":
                {
                    foreach (var key in new[]
                    {
                        "accessibility_enabled", "enabled_accessibility_services",
                        "accessibility_display_inversion_enabled", "accessibility_display_daltonizer_enabled",
                        "accessibility_display_magnification_enabled", "high_text_contrast_enabled"
                    })
                        CliRunner.Field(key, Sh($"settings get secure {key}", 6).Trim());
                    return 0;
                }
                case "keysim":
                {
                    var code = a.Get("send", "");
                    if (code.Length == 0)
                    {
                        CliRunner.Info("读取当前状态；使用 --send <按键码> 发送按键，--data on|off 切换数据流量。");
                        return 0;
                    }
                    CliRunner.Detail($"input keyevent {code}");
                    Console.WriteLine(Sh($"input keyevent {code}", 6));
                    return 0;
                }
                default:
                    throw new CliUsageException($"未知工具 ID：{id}（可用：animscale/fontscale/timeout/display/statusicons/battery/a11yreset/keysim）");
            }
        }

        // ---------------- 模块管理 ----------------

        private static int Modules(string[] raw)
        {
            var a = CliArgs.Parse(raw);
            var mgr = new ModuleManager { Log = s => CliRunner.Detail(s) };
            if (a.Has("list"))
            {
                CliRunner.Section("已安装模块");
                CliRunner.Field("管理器", mgr.DetectManager());
                foreach (var m in mgr.ListModules())
                {
                    var flags = m.Removed ? " [待移除]" : (m.Enabled ? "" : " [已禁用]");
                    Console.WriteLine($"  {m.Id}{flags}");
                    CliRunner.Detail($"名称: {m.Name}  版本: {m.Version} ({m.VersionCode})  作者: {m.Author}");
                    if (m.Description.Length > 0) CliRunner.Detail("简介: " + m.Description);
                }
                return 0;
            }
            if (a.Get("enable", "") is { Length: > 0 } en) { mgr.SetEnabled(en, true); CliRunner.Ok("已启用 " + en); return 0; }
            if (a.Get("disable", "") is { Length: > 0 } dis) { mgr.SetEnabled(dis, false); CliRunner.Ok("已禁用 " + dis); return 0; }
            if (a.Get("remove", "") is { Length: > 0 } rm) { mgr.RemoveModule(rm); CliRunner.Ok("已标记移除 " + rm); return 0; }
            if (a.Get("undo", "") is { Length: > 0 } un) { mgr.UndoRemoveModule(un); CliRunner.Ok("已撤销移除 " + un); return 0; }
            if (a.Get("install", "") is { Length: > 0 } zip) return InstallInteractive(zip, a.Get("answer", ""));
            throw new CliUsageException("需要 --list/--enable/--disable/--remove/--undo/--install 之一");
        }

        /// <summary>
        /// 在持久 root PTY 会话中安装模块，用于验证交互式安装链路。
        /// --answer 会在脚本等待输入时按行发送，便于脚本化验证 stdin 是否真的送达。
        /// </summary>
        private static int InstallInteractive(string zip, string answers)
        {
            var (mode, serial) = AdbService.DetectConnectionMode();
            if (mode != "system" || string.IsNullOrEmpty(serial))
                throw new CliUsageException("设备不在系统模式，请先连接并开启 ADB 调试");

            using var shell = Services.InteractiveShell
                .StartAsync(serial, root: true, onLine: l => CliRunner.Detail(l))
                .GetAwaiter().GetResult();

            var mgr = new ModuleManager();
            var manager = mgr.DetectManager();
            CliRunner.Field("管理器", manager);
            if (manager == "none") { CliRunner.Fail("未检测到 Magisk 或 KernelSU"); return 1; }

            var remote = "/sdcard/" + System.IO.Path.GetFileName(zip);
            CliRunner.Step("推送 " + remote);
            var push = ProcessRunner.Run(AdbService.AdbBin, new[] { "-s", serial, "push", zip, remote }, timeoutMs: 600_000);
            if (!push.Success) { CliRunner.Fail("推送失败: " + push.Output.Trim()); return 1; }

            var cmd = manager == "magisk"
                ? $"magisk --install-module '{remote}'"
                : $"ksud module install '{remote}'";

            CliRunner.Step("执行 " + cmd);
            var task = shell.RunAsync(cmd);

            // 若给了答案，等脚本就绪后逐行发送。
            if (answers.Length > 0)
            {
                System.Threading.Tasks.Task.Run(async () =>
                {
                    await System.Threading.Tasks.Task.Delay(3000);
                    foreach (var ans in answers.Split('|'))
                    {
                        await shell.SendAsync(ans);
                        CliRunner.Detail("> " + ans);
                        await System.Threading.Tasks.Task.Delay(1500);
                    }
                });
            }

            var (ok, output) = task.GetAwaiter().GetResult();
            CliRunner.Field("完成", ok ? "是" : "超时");
            if (!ok) { CliRunner.Fail("安装超时"); return 1; }
            CliRunner.Ok("安装流程结束");
            return 0;
        }

        private static int Unbrick(string[] raw)
        {
            var a = CliArgs.Parse(raw);
            if (!a.GetBool("yes"))
            {
                CliRunner.Warn("该操作会移除全部 Magisk 模块配置并重启设备。确认请加 --yes。");
                return 2;
            }
            var (mode, serial) = AdbService.DetectConnectionMode();
            if (mode != "system" || string.IsNullOrEmpty(serial))
                throw new CliUsageException("设备不在系统模式，请先连接并开启 ADB 调试");
            CliRunner.Step("执行 adb shell Magisk --remove-modules");
            var output = AdbService.AdbShellSerial(serial, "Magisk --remove-modules", 60) ?? "";
            CliRunner.Detail("命令输出: " + output.Trim());
            var low = output.ToLowerInvariant();
            if (low.Contains("not found") || low.Contains("inaccessible") || low.Contains("no such"))
            {
                CliRunner.Fail("执行失败，当前设备不支持该模块恢复指令。");
                return 1;
            }
            CliRunner.Step("重启设备");
            AdbService.RebootTo("system");
            CliRunner.Ok("恢复指令执行完成，设备正在重启。");
            return 0;
        }

        // ---------------- 镜像工厂 ----------------

        private static int Image(string[] raw)
        {
            var a = CliArgs.Parse(raw);
            var tool = a.Pos(0, "");
            var op = a.Pos(1, "");
            var proj = a.Require("project", "镜像工厂工程目录");
            if (tool.Length == 0 || op.Length == 0)
                throw new CliUsageException("需要工具名与操作，例如 image super unpack --project ...");

            void Log(string s) => CliRunner.Detail(s);
            switch (tool.ToLowerInvariant())
            {
                case "super":
                {
                    var t = new SuperImageTool { Log = Log };
                    if (op == "unpack") t.Unpack(a.Require("in", "super.img 路径"), proj);
                    else
                        t.Pack(proj, a.Require("images", ".img 分区目录"), a.Get("out", "super.img"),
                            a.Get("name", "super"), a.Get("group", "qti_dynamic_partitions"),
                            a.GetInt("meta", 65536), a.GetInt("block", 4096),
                            !a.GetBool("no-sparse"), a.GetBool("readonly"),
                            a.Has("size") ? a.GetLong("size", 0) : null);
                    break;
                }
                case "dtbo":
                {
                    var t = new DtboTool { Log = Log };
                    if (op == "unpack") t.Unpack(a.Require("in", "dtbo.img 路径"), proj, !a.GetBool("no-decompress"));
                    else t.Pack(proj, a.Require("dts", "*.dts 目录"), a.Get("out", "dtbo.img"));
                    break;
                }
                case "partitionfs":
                {
                    var fs = a.Get("fs", "auto");
                    string src = "";
                    if (op == "unpack")
                    {
                        src = a.Require("in", "分区镜像");
                        if (fs == "auto")
                        {
                            fs = FsDetect.Detect(src);
                            CliRunner.Detail($"识别: {fs}");
                            if (fs == "unknown")
                                throw new CliUsageException("无法识别镜像文件系统类型，请用 --fs ext4|erofs 指定");
                        }
                    }
                    else if (fs == "auto")
                    {
                        // 与 Python _PartitionFsPackWorker.run 一致：
                        // 存在 config/<name>_fs_config 时按 ext4，否则按 erofs。
                        var folder = a.Require("dir", "内容目录");
                        var folderName = Path.GetFileName(folder.TrimEnd('/', '\\'));
                        var hasCfg = folderName.Length > 0 &&
                                     File.Exists(Path.Combine(proj, "config", folderName + "_fs_config"));
                        fs = hasCfg ? "ext4" : "erofs";
                        CliRunner.Detail($"识别: {fs}");
                    }
                    if (op == "unpack")
                    {
                        if (fs == "erofs") new ErofsTool { Log = Log }.Unpack(src, proj, a.Get("name", ""));
                        else new Ext4ImageTool { Log = Log }.Extract(src, proj);
                    }
                    else
                    {
                        if (fs == "erofs") new ErofsTool { Log = Log }.Pack(proj, a.Require("dir", "内容目录"), a.Get("out", ""), a.Get("compress", "lz4hc"));
                        else
                        {
                            long? target = a.Has("size") ? a.GetLong("size", 0) : null;
                            new Ext4ImageTool { Log = Log }.Pack(proj, a.Require("dir", "内容目录"), a.Get("out", ""),
                                a.Get("label", ""), a.Get("mount", ""), a.GetInt("block", 4096),
                                a.GetBool("grow"), target);
                        }
                    }
                    break;
                }
                case "boot":
                {
                    var t = new BootTool { Log = Log };
                    if (op == "unpack") t.Unpack(a.Require("in", "boot.img"), proj, a.Get("name", ""));
                    else t.Pack(proj, a.Require("dir", "解包目录"), a.Get("out", ""), a.Get("orig", ""));
                    break;
                }
                case "datbr":
                {
                    var t = new DatBrTool { Log = Log };
                    if (op == "unpack")
                        t.Unpack(proj, a.Require("transfer", "transfer.list"), a.Require("dat", "new.dat 或 .br"), a.Get("name", ""));
                    else
                        t.Pack(proj, a.Require("in", ".img"), a.Get("name", ""), a.GetInt("version", 4), !a.GetBool("no-br"));
                    break;
                }
                default:
                    throw new CliUsageException($"未知镜像工具：{tool}（可用：super/dtbo/partitionfs/boot/datbr）");
            }
            CliRunner.Ok("完成，输出位于 " + Path.Combine(proj, "out"));
            return 0;
        }

        private static int Payload(string[] raw)
        {
            var a = CliArgs.Parse(raw);
            var input = a.Require("in", "payload.bin 路径");
            var outDir = a.Require("out", "输出目录");
            var parts = a.Get("parts", "");
            var ex = new PayloadExtractor { Log = s => CliRunner.Detail(s) };
            var ok = ex.Extract(input, outDir, parts);
            if (ok) CliRunner.Ok("提取完成: " + outDir);
            else CliRunner.Fail("提取失败");
            return ok ? 0 : 1;
        }

        private static int Ofp(string[] raw)
        {
            var a = CliArgs.Parse(raw);
            var input = a.Require("in", ".ofp 固件路径");
            var outDir = a.Require("out", "输出目录");
            var p = new OfpProcessor { Log = s => CliRunner.Detail(s) };
            var ok = p.Extract(input, outDir, a.Get("mode", "auto"));
            if (ok) CliRunner.Ok("处理完成: " + outDir);
            else CliRunner.Fail("处理失败");
            return ok ? 0 : 1;
        }

        private static int Ext4Dump(string[] raw)
        {
            var a = CliArgs.Parse(raw);
            var input = a.Require("in", "ext4 镜像路径");
            using var fs = File.OpenRead(input);
            var vol = new Ext4Volume(fs);
            CliRunner.Field("块大小", vol.BlockSize.ToString());
            CliRunner.Field("块数", vol.BlockCount.ToString());
            CliRunner.Field("组数", vol.GroupDescriptors.Count.ToString());
            CliRunner.Field("inode 大小", vol.Sb.SInodeSize.ToString());
            CliRunner.Field("每组 inode", vol.Sb.SInodesPerGroup.ToString());
            CliRunner.Field("incompat", "0x" + vol.Sb.SFeatureIncompat.ToString("X"));
            CliRunner.Field("挂载点", vol.MountPoint);
            CliRunner.Section("根目录条目");
            void Dump(Ext4Volume.Ext4Inode dir, string prefix, int depth)
            {
                foreach (var (name, inode, type) in dir.OpenDir())
                {
                    Console.WriteLine($"  {prefix}ino={inode,-8} type={type,-4} {name}");
                    if (name is "." or "..") continue;
                    if (type != 2 || depth >= 2) continue;
                    var child = vol.GetInode(inode, type);
                    Dump(child, prefix + "  ", depth + 1);
                }
            }
            Dump(vol.Root, "", 0);
            return 0;        }

#if ENABLE_FLASH
        /// <summary>
        /// 导出刷机计划供开发期核对。只读，不执行任何 fastboot 命令。
        /// 用于逐步骤比对 C# 与原版 Python 计划是否一致，避免顺序偏差导致刷机故障。
        /// </summary>
        private static int FlashPlan(string[] raw)
        {
            var a = CliArgs.Parse(raw);
            var dir = a.Require("dir", "镜像所在目录");
            if (!Directory.Exists(dir))
            {
                CliRunner.Fail("目录不存在: " + dir);
                return 1;
            }

            var wipe = a.Has("wipe");
            var keepRoot = a.Has("keep-root");

            var images = FlashPlanBuilder.ScanImages(dir);
            CliRunner.Field("镜像数量", images.Count.ToString());
            CliRunner.Field("wipe", wipe ? "true" : "false");
            CliRunner.Field("keepRoot", keepRoot ? "true" : "false");

            var plan = FlashPlanBuilder.Build(images, wipe, keepRoot, s => CliRunner.Detail(s));
            CliRunner.Field("步骤数", plan.Count.ToString());
            CliRunner.Section("刷机计划");

            for (var i = 0; i < plan.Count; i++)
            {
                var st = plan[i];
                Console.WriteLine($"  {i,3}  {st.Mode,-10}  {string.Join(' ', st.Args)}    // {st.Description}");
            }

            // 可选：导出 JSON 供脚本比对（路径参数统一替换为 <IMG>，避免机器差异）
            var jsonPath = a.Get("json", "");
            if (!string.IsNullOrEmpty(jsonPath))
            {
                var sb = new System.Text.StringBuilder();
                sb.Append('[');
                for (var i = 0; i < plan.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append("{\"mode\":").Append(JsonStr(plan[i].Mode));
                    sb.Append(",\"args\":[");
                    var args = plan[i].Args.Select(x =>
                        x.StartsWith(dir, StringComparison.OrdinalIgnoreCase) ? "<IMG>" : x);
                    sb.Append(string.Join(',', args.Select(JsonStr)));
                    sb.Append("]}");
                }
                sb.Append(']');
                File.WriteAllText(jsonPath, sb.ToString(), new System.Text.UTF8Encoding(false));
                CliRunner.Ok("计划已导出: " + jsonPath);
            }

            return 0;
        }

        /// <summary>
        /// 实测刷机环境守卫。只读检测，不修改任何状态。
        /// 输出为空表示可刷机；否则列出命中的远程控制软件。
        /// </summary>
        private static int FlashGuard(string[] raw)
        {
            CliRunner.Section("刷机环境检查");
            var ruleFile = Path.Combine(AppPaths.BinDir, "remote_rules.dat");
            CliRunner.Field("规则文件", ruleFile);
            CliRunner.Field("文件存在", File.Exists(ruleFile) ? "是" : "否");

            var hits = FlashEnvironmentGuard.CheckFlashEnvironment();
            CliRunner.Field("命中数量", hits.Count.ToString());

            if (hits.Count == 0)
            {
                CliRunner.Ok("可刷机（未检测到远程控制软件）");
                return 0;
            }

            CliRunner.Warn("检测到远程控制软件，禁止刷机：");
            foreach (var h in hits) Console.WriteLine("  - " + h);
            return 1;
        }

        /// <summary>
        /// 只读探测 fastboot 设备与模式。仅执行 getvar，不刷写任何分区。
        /// 用于验证模式判定逻辑对真实设备的解析是否正确。
        /// </summary>
        private static int FlashProbe(string[] raw)
        {
            CliRunner.Section("Fastboot 只读探测");
            var fb = new FastbootService(s => CliRunner.Detail(s));
            CliRunner.Field("fastboot", AdbService.FastbootBin);

            var hasDev = fb.HasDeviceAsync().GetAwaiter().GetResult();
            CliRunner.Field("设备在线", hasDev ? "是" : "否");
            if (!hasDev)
            {
                CliRunner.Warn("未检测到 fastboot / fastbootd 设备。");
                return 1;
            }

            var mode = fb.GetDeviceModeAsync().GetAwaiter().GetResult();
            CliRunner.Field("判定模式", mode);

            var taro = fb.CheckProductAsync("taro").GetAwaiter().GetResult();
            CliRunner.Field("product 含 taro", taro ? "是" : "否");

            var fb1 = fb.CheckProductAsync("OP5551L1").GetAwaiter().GetResult();
            var fb2 = fb.CheckProductAsync("OP5913L1").GetAwaiter().GetResult();
            CliRunner.Field("product 含 OP5551L1", fb1 ? "是" : "否");
            CliRunner.Field("product 含 OP5913L1", fb2 ? "是" : "否");
            return 0;
        }

        private static string JsonStr(string v)
        {
            var sb = new System.Text.StringBuilder("\"");
            foreach (var c in v)
            {
                sb.Append(c switch
                {
                    '"' => "\\\"",
                    '\\' => "\\\\",
                    '\n' => "\\n",
                    '\r' => "\\r",
                    '\t' => "\\t",
                    _ => c.ToString(),
                });
            }
            return sb.Append('"').ToString();
        }

        /// <summary>
        /// 测试固件包解包流程。只解包并报告可用镜像，不执行任何刷写。
        /// </summary>
        private static int FlashExtract(string[] raw)
        {
            var a = CliArgs.Parse(raw);
            var input = a.Require("in", "固件包路径");
            if (!File.Exists(input))
            {
                CliRunner.Fail("文件不存在: " + input);
                return 1;
            }

            var mode = a.Get("mode", "legacy") switch
            {
                "ota" => ArchiveMode.OtaZip,
                "newport" => ArchiveMode.NewPort7z,
                "coloros17" => ArchiveMode.ColorOs17_7z,
                _ => ArchiveMode.Legacy,
            };

            CliRunner.Field("输入", input);
            CliRunner.Field("模式", mode.ToString());
            CliRunner.Field("7z", Path.Combine(AppPaths.BinDir, "7z.exe"));
            CliRunner.Field("payload-dumper-go", Path.Combine(AppPaths.BinDir, "payload-dumper-go.exe"));

            var ex = new ArchiveExtractor(s => CliRunner.Detail(s));
            var res = ex.RunAsync(input, mode).GetAwaiter().GetResult();

            CliRunner.Section("结果");
            CliRunner.Field("成功", res.Success ? "是" : "否");
            CliRunner.Field("镜像目录", res.ImagesDir ?? "(无)");
            CliRunner.Field("临时目录", res.UnpackDir ?? "(已清理)");

            if (res.Success && res.ImagesDir != null)
            {
                var imgs = FlashPlanBuilder.ScanImages(res.ImagesDir);
                CliRunner.Field("镜像数量", imgs.Count.ToString());
                foreach (var k in imgs.Keys.OrderBy(x => x).Take(8))
                    Console.WriteLine("  " + k);
            }

            // 测试用：立即清理，避免占用磁盘
            if (a.Has("cleanup"))
            {
                ArchiveExtractor.TryDeleteDirectory(res.UnpackDir);
                CliRunner.Ok("临时目录已清理");
            }

            return res.Success ? 0 : 1;
        }

#endif
    }
}
