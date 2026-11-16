// 方案参考自 TIK（GPL-3.0，另附非商业条款）: https://github.com/ColdWindScholar/TIK
using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using Tobatools.Services;

namespace Tobatools.Logic.ImageFactory
{
    /// <summary>镜像工厂工程目录结构。</summary>
    public sealed class ImageFactoryProject
    {
        public string Root { get; }
        public ImageFactoryProject(string root) => Root = root;
        public string ExtractedDir => Path.Combine(Root, "extracted");
        public string ConfigDir => Path.Combine(Root, "config");
        public string OutDir => Path.Combine(Root, "out");
        public void Ensure()
        {
            Directory.CreateDirectory(Root);
            Directory.CreateDirectory(ExtractedDir);
            Directory.CreateDirectory(ConfigDir);
            Directory.CreateDirectory(OutDir);
        }
    }

    /// <summary>外部工具解析（bundled bin → repo bin → system PATH）。</summary>
    public static class ExtTool
    {
        public static string Resolve(string name, out string source)
        {
            var exe = name;
            if (!exe.ToLowerInvariant().EndsWith(".exe")) exe += ".exe";
            try
            {
                var p = Path.Combine(AppPaths.BinDir, exe);
                if (File.Exists(p)) { source = "bundled-bin"; return p; }
            }
            catch { }
            try
            {
                var root = AppPaths.RuntimeRoot;
                // 兼容两种布局：当前 tools\ 与旧版 bin\
                foreach (var sub in new[] { AppPaths.ToolsFolderName, "bin" })
                {
                    var p = Path.Combine(root, sub, exe);
                    if (File.Exists(p)) { source = "repo-bin"; return p; }
                }
            }
            catch { }
            // 3) 可选回退：TIK-master（Python 明确标注「不推荐、需显式开启」，默认关闭）。
            try
            {
                var allow = (Environment.GetEnvironmentVariable("TOBATOOLS_ALLOW_TIK_MASTER_BIN") ?? "").Trim();
                if (allow is "1" or "true" or "True" or "YES" or "yes")
                {
                    var tik = Path.Combine(AppPaths.RuntimeRoot, "TIK-master", "bin");
                    if (Directory.Exists(tik))
                    {
                        if (OperatingSystem.IsWindows())
                        {
                            foreach (var arch in new[] { "AMD64", "ARM64", "x86" })
                            {
                                var cand = Path.Combine(tik, "Windows", arch, exe);
                                if (File.Exists(cand)) { source = "tik-master"; return cand; }
                            }
                        }
                        else
                        {
                            foreach (var sysName in new[] { "Linux", "Darwin", "Android" })
                            foreach (var arch in new[] { "x86_64", "aarch64", "arm64" })
                            {
                                var cand = Path.Combine(tik, sysName, arch, name);
                                if (File.Exists(cand)) { source = "tik-master"; return cand; }
                            }
                        }
                    }
                }
            }
            catch { }
            source = "system";
            return name;
        }

        public static string Resolve(string name) => Resolve(name, out _);
    }

    /// <summary>流式运行外部进程（对应 Python run_stream）。</summary>
    public static class ExtProc
    {
        public static async Task<ProcessResult> RunAsync(
            IEnumerable<string> cmd,
            string? cwd = null,
            IDictionary<string, string>? env = null,
            Action<string>? log = null,
            Func<bool>? shouldStop = null,
            int timeoutMs = 0)
        {
            var args = new List<string>(cmd);
            var file = args[0];
            args.RemoveAt(0);
            log?.Invoke("执行: " + string.Join(" ", cmd));
            return await ProcessRunner.RunAsync(file, args, cwd, log, shouldStop, timeoutMs, env);
        }

        public static ProcessResult Run(
            IEnumerable<string> cmd, string? cwd = null, Action<string>? log = null,
            Func<bool>? shouldStop = null, int timeoutMs = 0)
        {
            return RunAsync(cmd, cwd, null, log, shouldStop, timeoutMs).GetAwaiter().GetResult();
        }
    }

    public static class FsDetect
    {
        /// <summary>
        /// 读取恰好 count 个字节。Stream.Read 允许短读，镜像结构字段长度固定，
        /// 短读会静默产出错位数据。
        /// </summary>
        private static void ReadExact(Stream s, byte[] buffer, int offset, int count)
        {
            int done = 0;
            while (done < count)
            {
                int got = s.Read(buffer, offset + done, count - done);
                if (got <= 0) throw new EndOfStreamException($"需要 {count} 字节，只读到 {done} 字节。");
                done += got;
            }
        }

        /// <summary>检测分区镜像文件系统类型：ext4 / erofs / unknown。</summary>
        public static string Detect(string imagePath)
        {
            try
            {
                using var f = File.OpenRead(imagePath);
                f.Seek(1024, SeekOrigin.Begin);
                var b = new byte[4];
                ReadExact(f, b, 0, 4);
                if (b[0] == 0xE2 && b[1] == 0xE1 && b[2] == 0xF5 && b[3] == 0xE0) return "erofs";
                f.Seek(1080, SeekOrigin.Begin);
                ReadExact(f, b, 0, 2);
                if (b[0] == 0x53 && b[1] == 0xEF) return "ext4";
            }
            catch { return "unknown"; }
            return "unknown";
        }
    }
}
