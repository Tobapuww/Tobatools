using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Tobatools.Services;

namespace Tobatools.Pages
{
    /// <summary>
    /// 设备端 aapt 标签读取器（对应 Python software_manager_tab.py 的 _BatchLabelWorker aapt 回退）。
    /// 把 bin/aapt-arm-pie 推到 /data/local/tmp/aapt 并 chmod 755，再用 dump badging 取应用名。
    /// 用于没有 launcher nonLocalizedLabel 的包（否则只能显示包名）。
    /// </summary>
    internal sealed class AaptLabelReader : IDisposable
    {
        private const string RemoteAapt = "/data/local/tmp/aapt";
        private readonly string _serial;

        private AaptLabelReader(string serial) => _serial = serial;

        /// <summary>准备设备端 aapt；本地缺少 aapt-arm-pie 时返回 null（调用方退回仅用 launcher 标签）。</summary>
        public static AaptLabelReader? TryCreate(string serial)
        {
            if (string.IsNullOrEmpty(serial)) return null;
            var local = Path.Combine(AppPaths.BinDir, "aapt-arm-pie");
            if (!File.Exists(local)) return null;

            // 设备上已有就不用重复推送（Python 用 ls + 'No such file' 判断）。
            var check = AdbService.AdbShellSerial(serial, new[] { "ls", RemoteAapt }, 5) ?? "";
            var missing = check.Length == 0
                          || check.Contains("No such file", StringComparison.OrdinalIgnoreCase)
                          || check.Contains("cannot", StringComparison.OrdinalIgnoreCase);
            if (missing)
            {
                AdbService.PushPath(local, RemoteAapt);
                AdbService.AdbShellSerial(serial, new[] { "chmod", "755", RemoteAapt }, 5);
            }
            return new AaptLabelReader(serial);
        }

        /// <summary>执行 aapt dump badging，返回原始输出。</summary>
        public string? DumpBadging(string apkPath)
            => AdbService.AdbShellSerial(_serial, new[] { RemoteAapt, "dump", "badging", apkPath }, 10);

        /// <summary>
        /// 从 badging 输出里挑最合适的应用名：中文优先，其次英文，最后默认标签。
        /// 与 Python 的 zh-CN > en > default 顺序一致。
        /// </summary>
        public static string? PickLabel(string badging)
        {
            string def = "", en = "", zh = "";
            foreach (var raw in badging.Split('\n'))
            {
                var line = raw.TrimEnd('\r');
                if (line.StartsWith("application-label-zh-CN:", StringComparison.Ordinal) ||
                    line.StartsWith("application-label-zh_CN:", StringComparison.Ordinal))
                {
                    zh = TrimLabel(line);
                }
                else if (line.StartsWith("application-label-en:", StringComparison.Ordinal) ||
                         line.StartsWith("application-label-en-", StringComparison.Ordinal))
                {
                    if (en.Length == 0) en = TrimLabel(line);
                }
                else if (line.StartsWith("application-label:", StringComparison.Ordinal))
                {
                    def = TrimLabel(line);
                }
            }
            var best = zh.Length > 0 ? zh : en.Length > 0 ? en : def;
            return best.Length > 0 ? best : null;
        }

        private static string TrimLabel(string line)
        {
            var idx = line.IndexOf(':');
            if (idx < 0) return "";
            return line[(idx + 1)..].Trim().Trim('\'');
        }

        public void Dispose()
        {
            // 与 Python 一致：远端 aapt 保留在 /data/local/tmp/aapt，重复使用不重复推送。
        }
    }
}
