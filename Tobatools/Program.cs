using System;
using System.Runtime.InteropServices;
using Tobatools.Cli;

namespace Tobatools
{
    /// <summary>
    /// 进程入口。带 <c>--cli</c> 参数时进入命令行调试模式（不创建窗口），
    /// 否则进入正常的 WinUI 图形界面流程。
    /// </summary>
    public static class Program
    {
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AttachConsole(uint dwProcessId);

        private const uint AttachParentProcess = 0xFFFFFFFF;

        [STAThread]
        static int Main(string[] args)
        {
            if (CliRunner.IsCliInvocation(args))
            {
                // WinExe 默认没有控制台，尝试附着到调用方（终端）的控制台。
                AttachConsole(AttachParentProcess);
                try { Console.OutputEncoding = System.Text.Encoding.UTF8; } catch { }
                return CliHost.Run(CliRunner.StripTokens(args));
            }

            global::WinRT.ComWrappersSupport.InitializeComWrappers();
            global::Microsoft.UI.Xaml.Application.Start((p) =>
            {
                var context = new global::Microsoft.UI.Dispatching.DispatcherQueueSynchronizationContext(
                    global::Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread());
                global::System.Threading.SynchronizationContext.SetSynchronizationContext(context);
                new App();
            });
            return 0;
        }
    }
}
