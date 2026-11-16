using System;
using System.IO;

namespace Tobatools.Services
{
    /// <summary>
    /// 外部工具解析：从 bin 目录 / 运行时根目录 / 系统 PATH 解析可执行文件。
    /// 对应 Python 的 app/logic/image_factory/external_tools.py。
    /// </summary>
    public static class ExternalTools
    {
        public static string AsExeName(string name)
        {
            var n = (name ?? "").Trim();
            if (!n.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)) return n + ".exe";
            return n;
        }

        /// <summary>返回 (path, sourceTag)。sourceTag: bundled-bin / repo-bin / system。</summary>
        public static (string Path, string Source) Resolve(string name)
        {
            var exe = AsExeName(name);

            // 1) 工具目录（AppPaths.BinDir 已优先解析 tools\，其次 bin\）
            var p1 = Path.Combine(AppPaths.BinDir, exe);
            if (File.Exists(p1)) return (p1, "bundled-bin");

            // 2) 运行时根下的 tools\ 与 bin\（兼容两种布局）
            foreach (var sub in new[] { AppPaths.ToolsFolderName, "bin" })
            {
                var p2 = Path.Combine(AppPaths.RuntimeRoot, sub, exe);
                if (File.Exists(p2)) return (p2, "repo-bin");
            }

            // 3) system PATH
            return (name, "system");
        }

        public static string Adb => Resolve("adb").Path;
        public static string Fastboot => Resolve("fastboot").Path;
        public static string MagiskBoot => Resolve("magiskboot").Path;
        public static string Scrcpy => Resolve("scrcpy").Path;
    }
}
