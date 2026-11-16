using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using System.Threading.Tasks;

namespace Tobatools.Services;

/// <summary>
/// 持久交互式 adb shell 会话：分配远端 PTY 并进入 root shell，
/// 用于需要在安装过程中按键/输入回应的模块脚本。
///
/// 为什么不直接用 `adb shell su -c "cmd"`：su 以非交互方式执行命令，
/// 其 stdin 是 /dev/null，脚本里的 read / 按键确认永远读不到数据而卡到超时。
/// 只有持久 PTY 会话能让 stdin 真正送达脚本。
/// </summary>
public sealed class InteractiveShell : IDisposable
{
    private readonly Process _proc;
    private readonly Action<string> _onLine;
    private readonly StringBuilder _pending = new();
    private readonly object _lock = new();

    // 当前“命令收集器”：RunAsync 期间接管输出，平时输出直接进日志。
    private Action<string>? _collector;

    private volatile bool _alive = true;
    public bool Alive => _alive;

    private InteractiveShell(Process proc, Action<string> onLine)
    {
        _proc = proc;
        _onLine = onLine;
    }

    /// <summary>启动会话；root=true 时自动进入 su。</summary>
    public static async Task<InteractiveShell> StartAsync(string serial, bool root, Action<string> onLine)
    {
        var psi = new ProcessStartInfo
        {
            FileName = AdbService.AdbBin,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        // 双 -t 强制分配远端 PTY：单 -t 在本地 stdin 非终端时会被 adb 拒绝。
        foreach (var a in new[] { "-s", serial, "shell", "-t", "-t" })
            psi.ArgumentList.Add(a);

        var proc = new Process { StartInfo = psi };
        if (!proc.Start()) throw new InvalidOperationException("无法启动 adb shell 会话");

        var shell = new InteractiveShell(proc, onLine);
        shell.Pump(proc.StandardOutput);
        shell.Pump(proc.StandardError);

        if (root)
        {
            await Task.Delay(400);
            await shell.SendAsync("su");
            await Task.Delay(1000);
        }

        // 关闭终端回显：否则 PTY 会把我们写入的整行命令再吐回来，
        // 既刷屏日志，又可能因终端宽度被折行切断哨兵标记导致完成判定失效。
        await shell.SendAsync("stty -echo 2>/dev/null; export PS1=''");
        await Task.Delay(300);
        return shell;
    }

    private void Pump(System.IO.StreamReader reader)
    {
        _ = Task.Run(async () =>
        {
            try
            {
                var buf = new char[512];
                int n;
                while ((n = await reader.ReadAsync(buf.AsMemory(0, buf.Length))) > 0)
                    Feed(new string(buf, 0, n));
            }
            catch { }
            finally { _alive = false; }
        });
    }

    private void Feed(string chunk)
    {
        List<string> ready = new();
        lock (_lock)
        {
            _pending.Append(chunk);
            var all = _pending.ToString();
            int idx;
            while ((idx = all.IndexOfAny(new[] { '\r', '\n' })) >= 0)
            {
                var line = all[..idx];
                all = all[(idx + 1)..];
                if (line.Length == 0) continue;
                ready.Add(line);
            }
            _pending.Clear();
            _pending.Append(all);
        }
        foreach (var line in ready)
        {
            // PTY 回显的是我们写入的整行命令（cmd; echo <marker>），
            // 只剔除以 "echo " 关联哨兵的这行回显，避免误伤正常输出。
            if (IsSentinelEcho(line)) continue;
            try { _onLine?.Invoke(line); } catch { }
            var c = _collector;
            if (c != null) { try { c(line); } catch { } }
        }
    }

    private const string ShellSentinelPrefix = "__DSH_";

    private static bool IsSentinelEcho(string line)
    {
        // 形如 "<cmd>; echo __DSH_xxxxxxxxxx__"
        int at = line.IndexOf(ShellSentinelPrefix, StringComparison.Ordinal);
        if (at < 0) return false;
        return line.LastIndexOf("echo ", at, StringComparison.Ordinal) >= 0
               || line.TrimStart().StartsWith(ShellSentinelPrefix, StringComparison.Ordinal);
    }

    /// <summary>向会话写入一行。</summary>
    public async Task SendAsync(string line)
    {
        if (!_alive) throw new InvalidOperationException("会话已结束");
        await _proc.StandardInput.WriteLineAsync(line);
        await _proc.StandardInput.FlushAsync();
    }

    /// <summary>执行一条命令，等待哨兵标记出现，返回该命令期间的输出。</summary>
    public async Task<(bool ok, string output)> RunAsync(string cmd, int timeoutMs = 600_000)
    {
        var marker = "__DSH_" + Guid.NewGuid().ToString("N")[..10] + "__";
        var lines = new List<string>();
        var tcs = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);

        lock (_lock)
        {
            _collector = l =>
            {
                if (l.Contains(marker)) { tcs.TrySetResult(true); return; }
                lock (lines) lines.Add(l);
            };
        }

        try
        {
            await SendAsync($"{cmd}; echo {marker}");
            var done = await Task.WhenAny(tcs.Task, Task.Delay(timeoutMs));
            bool ok = done == tcs.Task;
            lock (lines) return (ok, string.Join("\n", lines));
        }
        finally
        {
            lock (_lock) { _collector = null; }
        }
    }

    public void Dispose()
    {
        _alive = false;
        try { _proc.StandardInput.WriteLine("exit"); _proc.StandardInput.Flush(); } catch { }
        try { if (!_proc.WaitForExit(800)) _proc.Kill(entireProcessTree: true); } catch { }
        try { _proc.Dispose(); } catch { }
    }
}
