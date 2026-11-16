using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Tobatools.Services
{
    public sealed class ProcessResult
    {
        public int ExitCode { get; set; }
        public string Output { get; set; } = "";
        public bool TimedOut { get; set; }
        public bool Cancelled { get; set; }
        public bool Success => ExitCode == 0 && !TimedOut && !Cancelled;
    }

    /// <summary>
    /// 进程运行器：静默启动、实时回传输出、支持取消/超时。
    /// 对应 Python 的 ProcWorker / run_stream。
    /// </summary>
    public static class ProcessRunner
    {
        public static async Task<ProcessResult> RunAsync(
            string? fileName,
            IEnumerable<string>? args = null,
            string? workingDir = null,
            Action<string>? onOutput = null,
            Func<bool>? shouldStop = null,
            int timeoutMs = 0,
            IDictionary<string, string>? env = null,
            CancellationToken ct = default)
        {
            if (string.IsNullOrEmpty(fileName))
            {
                throw new ArgumentException("可执行文件路径不能为空。", nameof(fileName));
            }

            var psi = new ProcessStartInfo
            {
                FileName = fileName,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };
            if (workingDir != null) psi.WorkingDirectory = workingDir;
            if (args != null)
            {
                foreach (var a in args) psi.ArgumentList.Add(a);
            }
            if (env != null)
            {
                foreach (var kv in env) psi.Environment[kv.Key] = kv.Value;
            }

            var result = new ProcessResult();
            var lines = new StringBuilder();
            object lockObj = new();

            using var proc = new Process { StartInfo = psi };
            try { proc.Start(); }
            catch (System.ComponentModel.Win32Exception ex)
            {
                throw new System.IO.FileNotFoundException($"未找到可执行文件: {fileName}", ex);
            }

            var readTasks = new List<Task>();
            readTasks.Add(ReadStreamAsync(proc.StandardOutput, s => OnLine(s, onOutput, lines, lockObj)));
            readTasks.Add(ReadStreamAsync(proc.StandardError, s => OnLine(s, onOutput, lines, lockObj)));

            // 取消/停止监控
            using var reg = ct.Register(() => { try { Kill(proc); } catch { } });

            var runTask = Task.Run(() =>
            {
                while (!proc.HasExited)
                {
                    if (ct.IsCancellationRequested)
                    {
                        result.Cancelled = true;
                        Kill(proc);
                        break;
                    }
                    if (shouldStop != null && shouldStop())
                    {
                        result.Cancelled = true;
                        Kill(proc);
                        break;
                    }
                    Thread.Sleep(100);
                }
            });

            try
            {
                var waitTask = proc.WaitForExitAsync(ct);
                if (timeoutMs > 0)
                {
                    var done = await Task.WhenAny(waitTask, Task.Delay(timeoutMs, ct));
                    if (done != waitTask)
                    {
                        result.TimedOut = true;
                        Kill(proc);
                        await waitTask;
                    }
                }
                else
                {
                    await waitTask;
                }
            }
            catch (OperationCanceledException)
            {
                result.Cancelled = true;
                Kill(proc);
            }
            catch (Exception)
            {
                // 进程已退出等情况
            }

            try { await Task.WhenAll(readTasks); } catch { }
            try { proc.WaitForExit(); } catch { }
            result.ExitCode = proc.HasExited ? proc.ExitCode : -1;
            result.Output = lines.ToString();
            return result;
        }

        private static void OnLine(string s, Action<string>? onOutput, StringBuilder lines, object lockObj)
        {
            if (string.IsNullOrEmpty(s)) return;
            lock (lockObj) { lines.AppendLine(s); }
            onOutput?.Invoke(s);
        }

        private static async Task ReadStreamAsync(StreamReader reader, Action<string> onLine)
        {
            try
            {
                string? line;
                while ((line = await reader.ReadLineAsync()) != null)
                {
                    onLine(line);
                }
            }
            catch { }
        }

        private static void Kill(Process p)
        {
            try { if (!p.HasExited) p.Kill(entireProcessTree: true); } catch { }
        }

        /// <summary>
        /// 同步快捷方式（适合短命令）。
        ///
        /// 必须用 Task.Run 把整个异步流程挪到线程池：
        /// RunAsync 内部有大量 await，若直接在 UI 线程上同步等待，
        /// 其后续续体需要回到已被阻塞的 UI 线程才能执行，
        /// 会形成经典死锁——界面完全卡死而子进程仍在运行。
        /// 这在单分区刷入（先 reboot 再等待重连）时表现得最明显。
        /// </summary>
        public static ProcessResult Run(
            string fileName,
            IEnumerable<string>? args = null,
            string? workingDir = null,
            int timeoutMs = 60000)
        {
            var argList = args?.ToArray();
            return Task.Run(() => RunAsync(fileName, argList, workingDir, timeoutMs: timeoutMs))
                       .GetAwaiter().GetResult();
        }

        /// <summary>静默启动新控制台（用于打开 ADB 终端等）。</summary>
        public static void StartDetached(string fileName, IEnumerable<string>? args = null, string? workingDir = null)
        {
            var psi = new ProcessStartInfo
            {
                FileName = fileName,
                UseShellExecute = true,
                WorkingDirectory = workingDir ?? AppPaths.BinDir,
            };
            foreach (var a in args ?? Enumerable.Empty<string>()) psi.ArgumentList.Add(a);
            Process.Start(psi);
        }
    }
}
