using System;
using System.IO;

namespace Tobatools.Services
{
    /// <summary>
    /// 路径服务：定位运行时根目录、bin 目录、应用数据目录、下载目录等。
    /// 对应 Python 的 app/services/app_paths.py。
    /// </summary>
    public static class AppPaths
    {
        public const string AppDataFolderName = "Tobatools";

        private static string? _runtimeRoot;
        private static string? _binDir;
        private static string? _appData;
        private static string? _downloads;

        /// <summary>
        /// 判定目录是否为「真正的工具目录」：必须含 adb 或 fastboot 可执行文件。
        /// 仅凭目录存在不可靠——项目下的 bin\ 只有 x64 构建输出，
        /// 误选它会导致运行时找不到任何工具。
        /// </summary>
        private static bool ContainsTools(string dir)
        {
            try
            {
                if (!Directory.Exists(dir)) return false;
                return File.Exists(Path.Combine(dir, "adb.exe")) ||
                       File.Exists(Path.Combine(dir, "fastboot.exe")) ||
                       File.Exists(Path.Combine(dir, "7z.exe"));
            }
            catch { return false; }
        }

        /// <summary>工具目录名。独立于构建输出的 bin\，避免两者混淆。</summary>
        public const string ToolsFolderName = "tools";

        /// <summary>程序运行时根目录（含 tools/app 的目录）。</summary>
        public static string RuntimeRoot
        {
            get
            {
                if (_runtimeRoot != null) return _runtimeRoot;
                var exeDir = AppContext.BaseDirectory;

                // 自 exe 目录向上查找，优先认定「确实含工具」的目录为运行时根，
                // 避免项目目录下的空 bin\（仅含 x64 构建输出）影响判断。
                var dir = new DirectoryInfo(exeDir);
                string? firstToolsRoot = null;
                string? firstBinRoot = null;
                while (dir != null)
                {
                    if (ContainsTools(Path.Combine(dir.FullName, ToolsFolderName)))
                    {
                        _runtimeRoot = dir.FullName;
                        return _runtimeRoot;
                    }
                    var bin = Path.Combine(dir.FullName, "bin");
                    if (Directory.Exists(bin))
                    {
                        firstBinRoot ??= dir.FullName;
                        if (ContainsTools(bin))
                        {
                            _runtimeRoot = dir.FullName;
                            return _runtimeRoot;
                        }
                    }
                    // 兼容旧版 Python 布局（仓库根含 app/ 目录）
                    if (Directory.Exists(Path.Combine(dir.FullName, "app")))
                    {
                        _runtimeRoot = dir.FullName;
                        return _runtimeRoot;
                    }
                    dir = dir.Parent;
                }
                if (firstToolsRoot != null) { _runtimeRoot = firstToolsRoot; return _runtimeRoot; }
                if (firstBinRoot != null) { _runtimeRoot = firstBinRoot; return _runtimeRoot; }
                _runtimeRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));
                return _runtimeRoot;
            }
        }

        /// <summary>
        /// 外部工具所在目录。
        /// 优先 tools\（当前布局），其次 bin\（旧布局），最后 app_packages\bin。
        /// 只接受确实含工具文件的目录。
        /// </summary>
        public static string BinDir
        {
            get
            {
                if (_binDir != null) return _binDir;
                var root = RuntimeRoot;
                foreach (var cand in new[]
                {
                    Path.Combine(root, ToolsFolderName),
                    Path.Combine(root, "bin"),
                    Path.Combine(root, "app_packages", "bin"),
                })
                {
                    if (ContainsTools(cand)) { _binDir = cand; return _binDir; }
                }
                // 都找不到时按当前布局给出默认值，便于错误信息指向正确位置。
                _binDir = Path.Combine(root, ToolsFolderName);
                return _binDir;
            }
        }

        public static string AppDataDir
        {
            get
            {
                if (_appData != null) return _appData;
                var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                _appData = Path.Combine(local, AppDataFolderName);
                Directory.CreateDirectory(_appData);
                return _appData;
            }
        }

        public static string EnsureSubDir(string name)
        {
            var path = Path.Combine(AppDataDir, name);
            Directory.CreateDirectory(path);
            return path;
        }

        public static string LogsDir => EnsureSubDir("logs");

        public static string WorkDir => EnsureSubDir("work");

        public static string TempDir => EnsureSubDir("temp");

        public static string DefaultDownloadsDir
        {
            get
            {
                if (_downloads != null) return _downloads;
                var known = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                _downloads = Path.Combine(known, "Downloads");
                Directory.CreateDirectory(_downloads);
                return _downloads;
            }
        }

        public static bool IsStoreDistribution =>
            Environment.GetEnvironmentVariable("TOBATOOLS_STORE_DISTRIBUTION") is string v &&
            v.Trim().ToLowerInvariant() is not ("0" or "false" or "no" or "off" or "");

        public static void Initialize()
        {
            // 触发热初始化
            _ = RuntimeRoot;
            _ = BinDir;
            _ = AppDataDir;
            _ = DefaultDownloadsDir;
        }
    }
}
