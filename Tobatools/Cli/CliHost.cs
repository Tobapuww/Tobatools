using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Tobatools.Cli
{
    /// <summary>
    /// 命令行模式入口：解析子命令并分派。
    /// 只在 <c>--cli</c> 启动时使用，正式图形界面不经过这里。
    /// </summary>
    public static class CliHost
    {
        public static int Run(string[] args)
        {
            try
            {
                Tobatools.Services.AppPaths.Initialize();
            }
            catch (Exception ex)
            {
                CliRunner.Warn("初始化应用路径失败：" + ex.Message);
            }

            var commands = CliCommands.All();
            if (args.Length == 0 || IsHelp(args[0]))
            {
                PrintHelp(commands);
                return args.Length == 0 ? 2 : 0;
            }

            var name = args[0].Trim().ToLowerInvariant();
            var cmd = commands.FirstOrDefault(c => c.Name == name)
                      ?? commands.FirstOrDefault(c => c.Name.StartsWith(name, StringComparison.Ordinal));
            if (cmd == null)
            {
                CliRunner.Fail($"未知命令：{args[0]}");
                CliRunner.Info("运行 --cli help 查看可用命令。");
                return 2;
            }

            var rest = args.Skip(1).ToArray();
            if (rest.Any(IsHelp))
            {
                CliRunner.Info($"用法: {cmd.Usage}");
                CliRunner.Info("  " + cmd.Summary);
                return 0;
            }

            try
            {
                return cmd.Handler(rest);
            }
            catch (CliUsageException ex)
            {
                CliRunner.Fail(ex.Message);
                CliRunner.Info($"用法: {cmd.Usage}");
                return 2;
            }
            catch (Exception ex)
            {
                CliRunner.Fail(ex.GetType().Name + ": " + ex.Message);
                CliRunner.Detail(ex.StackTrace ?? "");
                return 1;
            }
        }

        private static bool IsHelp(string token) =>
            token is "-h" or "--help" or "help" or "-?" or "/?";

        private static void PrintHelp(IEnumerable<CliCommand> commands)
        {
            Console.WriteLine("拖把工具箱Pro — 命令行调试模式（开发用，不替代图形界面）");
            Console.WriteLine();
            Console.WriteLine("用法: Tobatools.exe --cli <命令> [参数]");
            Console.WriteLine();
            Console.WriteLine("命令:");
            foreach (var c in commands)
            {
                Console.WriteLine($"  {c.Name,-14} {c.Summary}");
                Console.WriteLine($"  {"",-14} {c.Usage}");
            }
            Console.WriteLine();
            Console.WriteLine("所有命令都支持 --help 查看参数说明。");
        }
    }
}
