using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Principal;
using System.Text;
using System.Windows.Forms;

namespace TobatoolsLauncher
{
    /// <summary>
    /// 拖把工具箱Pro 启动器。
    ///
    /// 目标框架 .NET Framework 4.8（Windows 10 1809 起系统内置），
    /// 因此本程序自身不需要任何下载即可运行，可在缺少依赖的机器上
    /// 先检查并安装 .NET 10 桌面运行时与 Windows App Runtime 1.8，
    /// 然后再启动主程序。
    ///
    /// 设计要点：
    ///  - 不依赖主程序目录中的任何文件即可完成检查（只读取 system 信息）。
    ///  - 安装优先用 winget；winget 不可用时回退到官方直链下载安装。
    ///  - 安装需要管理员权限，缺失时以 UAC 提权方式重新启动自身。
    ///  - 全程记录日志到 launcher.log，便于排障。
    /// </summary>
    internal static class Program
    {
        private const string AppExeName = "Tobatools.exe";
        private const string LogFileName = "launcher.log";

        private const string DotnetWingetId = "Microsoft.DotNet.DesktopRuntime.10";
        private const string WinAppRuntimeWingetId = "Microsoft.WindowsAppRuntime.1.8";

        /// <summary>
        /// 当前进程的架构标识（x64 / arm64 / x86），用于选择对应架构的运行时安装包。
        /// 发行版按架构分开打包，启动器必须安装与自身架构一致的运行时，
        /// 否则 x64 程序在 arm64 机器上会缺运行时。
        /// </summary>
        private static string RidSuffix
        {
            get
            {
                switch (System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture)
                {
                    case System.Runtime.InteropServices.Architecture.Arm64:
                        return "arm64";
                    case System.Runtime.InteropServices.Architecture.X86:
                        return "x86";
                    default:
                        return "x64";
                }
            }
        }

        private static string DotnetDirectUrl
        {
            get { return "https://aka.ms/dotnet/10.0/windowsdesktop-runtime-win-" + RidSuffix + ".exe"; }
        }

        private static string WinAppRuntimeDirectUrl
        {
            get { return "https://aka.ms/windowsappsdk/1.8/latest/windowsappruntimeinstall-" + RidSuffix + ".exe"; }
        }

        private static string BaseDir
        {
            get { return AppDomain.CurrentDomain.BaseDirectory; }
        }

        private static string LogPath
        {
            get { return Path.Combine(BaseDir, LogFileName); }
        }

        [STAThread]
        private static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            // 以 --no-wait 递归调用时用于「已提权」分支，避免重复弹窗。
            var elevated = args != null && args.Any(a =>
                string.Equals(a, "--elevated", StringComparison.OrdinalIgnoreCase));

            try
            {
                Log("=== 启动器开始 ===");
                Log("目录: " + BaseDir);

                var appPath = Path.Combine(BaseDir, AppExeName);

                // --check：只报告状态，不弹窗、不启动、不安装。
                var checkOnly = args != null && args.Any(a =>
                    string.Equals(a, "--check", StringComparison.OrdinalIgnoreCase));

                // 主程序不在时直接报错，避免安装完依赖却无法启动。
                if (!File.Exists(appPath))
                {
                    if (checkOnly)
                    {
                        var miss = "主程序: 缺失\n" + appPath;
                        Log(miss.Replace("\n", " | "));
                        try
                        {
                            File.WriteAllText(Path.Combine(BaseDir, "launcher-check.txt"), miss, Encoding.UTF8);
                        }
                        catch { }
                        return 2;
                    }
                    Error("找不到主程序：\n" + appPath +
                          "\n\n请确认已完整解压压缩包（不要直接在压缩包内运行）。");
                    return 2;
                }

                var needDotnet = !HasDotnetDesktop10();
                var needWinApp = !HasWindowsAppRuntime18();

                Log("需要 .NET 10 桌面运行时: " + needDotnet);
                Log("需要 Windows App Runtime 1.8: " + needWinApp);

                // 仅检查不启动，便于排障与自动化验证。
                if (args != null && args.Any(a =>
                        string.Equals(a, "--check", StringComparison.OrdinalIgnoreCase)))
                {
                    var report = "主程序: " + (File.Exists(appPath) ? "存在" : "缺失") + "\n" +
                                 ".NET 10 桌面运行时: " + (needDotnet ? "缺失" : "已安装") + "\n" +
                                 "Windows App Runtime 1.8: " + (needWinApp ? "缺失" : "已安装");
                    Log(report.Replace("\n", " | "));
                    // WinExe 无控制台，写入文件供检查；同时尽量输出到父控制台。
                    try
                    {
                        File.WriteAllText(Path.Combine(BaseDir, "launcher-check.txt"), report, Encoding.UTF8);
                    }
                    catch { }
                    return 0;
                }

                if (needDotnet || needWinApp)
                {
                    if (!ConfirmInstall(needDotnet, needWinApp)) return 0;

                    // 安装组件需要管理员权限；已提权则直接继续。
                    if (!IsAdministrator() && !elevated)
                    {
                        Log("请求管理员权限重新启动...");
                        RelaunchElevated();
                        return 0;
                    }

                    if (needDotnet)
                    {
                        Log("开始安装 .NET 10 桌面运行时...");
                        if (!InstallViaWingetOrDirect(DotnetWingetId, "Microsoft .NET Windows Desktop Runtime 10.0",
                                DotnetDirectUrl, "dotnet-desktop-10.exe"))
                        {
                            Error(".NET 10 桌面运行时安装失败，请手动安装后重试。\n\n" +
                                  "命令：winget install " + DotnetWingetId +
                                  "\n\n日志：" + LogPath);
                            return 3;
                        }
                    }

                    if (needWinApp)
                    {
                        Log("开始安装 Windows App Runtime 1.8...");
                        if (!InstallViaWingetOrDirect(WinAppRuntimeWingetId, "Windows App Runtime 1.8",
                                WinAppRuntimeDirectUrl, "windowsappruntime-1.8.exe"))
                        {
                            Error("Windows App Runtime 1.8 安装失败，请手动安装后重试。\n\n" +
                                  "命令：winget install " + WinAppRuntimeWingetId +
                                  "\n\n日志：" + LogPath);
                            return 4;
                        }
                    }

                    // 安装程序偶尔需要一点时间完成注册，稍作等待再复核。
                    System.Threading.Thread.Sleep(1500);
                    var stillMissing = new StringBuilder();
                    if (!HasDotnetDesktop10()) stillMissing.AppendLine("· .NET 10 桌面运行时");
                    if (!HasWindowsAppRuntime18()) stillMissing.AppendLine("· Windows App Runtime 1.8");
                    if (stillMissing.Length > 0)
                    {
                        Error("安装已执行，但仍未检测到以下组件：\n" + stillMissing +
                              "\n请重启电脑后重试，或手动安装。\n\n日志：" + LogPath);
                        return 5;
                    }
                    Log("依赖检查通过。");
                }

                Log("启动主程序：" + appPath);
                StartApp(appPath);
                return 0;
            }
            catch (Exception ex)
            {
                Log("异常: " + ex);
                Error("启动失败：\n" + ex.Message + "\n\n日志：" + LogPath);
                return 1;
            }
        }

        private static void StartApp(string appPath)
        {
            var psi = new ProcessStartInfo
            {
                FileName = appPath,
                WorkingDirectory = BaseDir,
                UseShellExecute = true,
            };
            Process.Start(psi);
        }

        /// <summary>检测 .NET 10 桌面运行时是否已安装（按当前进程架构判断）。</summary>
        private static bool HasDotnetDesktop10()
        {
            try
            {
                // 1) 共享框架目录：C:\Program Files\dotnet\shared\Microsoft.WindowsDesktop.App\10.x.y
                foreach (var root in new[]
                {
                    @"C:\Program Files\dotnet\shared\Microsoft.WindowsDesktop.App",
                    @"C:\Program Files (x86)\dotnet\shared\Microsoft.WindowsDesktop.App"
                })
                {
                    if (!Directory.Exists(root)) continue;
                    foreach (var dir in Directory.GetDirectories(root))
                    {
                        var name = Path.GetFileName(dir);
                        if (name.StartsWith("10.", StringComparison.Ordinal)) return true;
                    }
                }

                // 2) 注册表（dotnet 安装时写入）
                //    x64 机器上 32 位视图需走 WOW6432Node，因此两种路径都查。
                using (var baseKey = Microsoft.Win32.Registry.LocalMachine)
                {
                    foreach (var arch in new[] { "x64", "arm64", "x86" })
                    {
                        foreach (var sub in new[]
                        {
                            @"SOFTWARE\dotnet\Setup\InstalledVersions\" + arch + @"\sharedfx\Microsoft.WindowsDesktop.App",
                            @"SOFTWARE\WOW6432Node\dotnet\Setup\InstalledVersions\" + arch + @"\sharedfx\Microsoft.WindowsDesktop.App"
                        })
                        {
                            using (var key = baseKey.OpenSubKey(sub))
                            {
                                if (key == null) continue;
                                foreach (var valueName in key.GetValueNames())
                                {
                                    if (valueName.StartsWith("10.", StringComparison.Ordinal)) return true;
                                }
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Log("检测 .NET 运行时出错: " + ex.Message);
            }
            return false;
        }

        /// <summary>
        /// 检测 Windows App Runtime 1.8 是否已安装。
        /// 该运行时以 MSIX 框架包形式部署，查注册表不可靠，
        /// 因此通过 WindowsApps 目录与 Appx 清单文件判断。
        /// </summary>
        private static bool HasWindowsAppRuntime18()
        {
            try
            {
                // 1) 已注册的 Appx 包（当前用户）
                var psi = new ProcessStartInfo
                {
                    FileName = "powershell.exe",
                    Arguments = "-NoProfile -NonInteractive -Command " +
                                "\"(Get-AppxPackage -Name 'Microsoft.WindowsAppRuntime.1.8*' | Measure-Object).Count\"",
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true,
                };
                using (var p = Process.Start(psi))
                {
                    var output = p.StandardOutput.ReadToEnd();
                    p.WaitForExit(15000);
                    int count;
                    if (int.TryParse(output.Trim(), out count) && count > 0) return true;
                }

                // 2) 系统级安装目录
                var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
                var windowsApps = Path.Combine(programFiles, "WindowsApps");
                if (Directory.Exists(windowsApps))
                {
                    foreach (var dir in Directory.GetDirectories(windowsApps, "Microsoft.WindowsAppRuntime.1.8*"))
                    {
                        return true;
                    }
                }
            }
            catch (Exception ex)
            {
                Log("检测 Windows App Runtime 出错: " + ex.Message);
            }
            return false;
        }

        private static bool IsAdministrator()
        {
            try
            {
                using (var identity = WindowsIdentity.GetCurrent())
                {
                    var principal = new WindowsPrincipal(identity);
                    return principal.IsInRole(WindowsBuiltInRole.Administrator);
                }
            }
            catch { return false; }
        }

        /// <summary>以管理员权限重新启动自身，并带上 --elevated 标记。</summary>
        private static void RelaunchElevated()
        {
            try
            {
                var exe = System.Reflection.Assembly.GetExecutingAssembly().Location;
                var psi = new ProcessStartInfo
                {
                    FileName = exe,
                    UseShellExecute = true,
                    Verb = "runas",
                    WorkingDirectory = BaseDir,
                    Arguments = "--elevated",
                };
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                Log("提权失败: " + ex.Message);
                Error("需要管理员权限来安装运行组件，但提权被取消或失败。\n\n" +
                      "请右键启动器选择「以管理员身份运行」，或手动执行：\n" +
                      "winget install " + DotnetWingetId + "\n" +
                      "winget install " + WinAppRuntimeWingetId);
            }
        }

        /// <summary>先试 winget，失败则回退官方直链下载安装。</summary>
        private static bool InstallViaWingetOrDirect(string wingetId, string displayName,
            string directUrl, string tempFileName)
        {
            if (IsWingetAvailable())
            {
                Log("使用 winget 安装 " + wingetId);
                var code = RunProcess("winget.exe",
                    "install --id " + wingetId +
                    " --exact --accept-package-agreements --accept-source-agreements --silent",
                    true);
                Log("winget 退出码: " + code);
                if (code == 0) return true;

                // winget 返回 -1978335189 (0x8A15002B) 表示「已安装或无可用升级」，视为成功。
                if (code == -1978335189) return true;
            }
            else
            {
                Log("winget 不可用，改用官方直链下载。");
            }

            return InstallFromDirectUrl(displayName, directUrl, tempFileName);
        }

        private static bool InstallFromDirectUrl(string displayName, string url, string tempFileName)
        {
            var target = Path.Combine(Path.GetTempPath(), tempFileName);
            try
            {
                Log("下载 " + displayName + " -> " + target);
                using (var client = new System.Net.WebClient())
                {
                    client.Headers.Add("User-Agent", "TobatoolsLauncher");
                    client.DownloadFile(url, target);
                }

                if (!File.Exists(target) || new FileInfo(target).Length < 1024 * 1024)
                {
                    Log("下载结果异常，文件过小。");
                    return false;
                }

                Log("静默安装 " + target);
                var code = RunProcess(target, "/install /quiet /norestart", false);
                Log("安装程序退出码: " + code);
                // 3010 = 成功但需重启
                return code == 0 || code == 3010 || code == 1641;
            }
            catch (Exception ex)
            {
                Log("直链安装失败: " + ex.Message);
                return false;
            }
            finally
            {
                try { if (File.Exists(target)) File.Delete(target); } catch { }
            }
        }

        private static bool IsWingetAvailable()
        {
            try
            {
                var code = RunProcess("winget.exe", "--version", false);
                return code == 0;
            }
            catch { return false; }
        }

        private static int RunProcess(string fileName, string arguments, bool shellExecute)
        {
            var psi = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                UseShellExecute = shellExecute,
                CreateNoWindow = !shellExecute,
            };
            if (!shellExecute)
            {
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
            }

            using (var p = Process.Start(psi))
            {
                if (!p.WaitForExit(30 * 60 * 1000))
                {
                    try { p.Kill(); } catch { }
                    Log("进程超时被终止: " + fileName);
                    return -1;
                }
                return p.ExitCode;
            }
        }

        private static bool ConfirmInstall(bool needDotnet, bool needWinApp)
        {
            var text = new StringBuilder();
            text.AppendLine("启动拖把工具箱Pro 需要以下系统组件，当前未安装：");
            text.AppendLine();
            if (needDotnet) text.AppendLine("  · .NET 10 桌面运行时（Microsoft .NET Desktop Runtime 10.0）");
            if (needWinApp) text.AppendLine("  · Windows App Runtime 1.8");
            text.AppendLine();
            text.AppendLine("是否现在自动下载并安装？（需要管理员权限，约 160 MB）");
            text.AppendLine();
            text.AppendLine("选择「否」将退出，你也可以手动安装后重新运行：");
            if (needDotnet) text.AppendLine("  winget install " + DotnetWingetId);
            if (needWinApp) text.AppendLine("  winget install " + WinAppRuntimeWingetId);

            var result = MessageBox.Show(text.ToString(), "拖把工具箱Pro — 缺少运行组件",
                MessageBoxButtons.YesNo, MessageBoxIcon.Information, MessageBoxDefaultButton.Button1);
            return result == DialogResult.Yes;
        }

        private static void Error(string message)
        {
            MessageBox.Show(message, "拖把工具箱Pro",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }

        private static void Log(string message)
        {
            try
            {
                var line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + message;
                File.AppendAllText(LogPath, line + Environment.NewLine, Encoding.UTF8);
            }
            catch { }
        }
    }
}
