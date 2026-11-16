using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Tobatools.Controls;
using Tobatools.Logic;
using Tobatools.Services;
using Windows.Graphics;

namespace Tobatools.Dialogs;

/// <summary>
/// 模块安装日志窗口：安装过程实时输出，并允许把输入/按键转发给模块安装脚本。
///
/// 模块脚本常在安装中等待确认（音量键、y/n 等）。`su -c "cmd"` 的 stdin 是
/// /dev/null，脚本读不到任何输入只会卡到超时，因此安装在持久 PTY 会话中执行，
/// 由本窗口把用户输入写进该会话，另外提供音量键注入以应对按键式交互。
/// </summary>
public sealed class ModuleInstallWindow : Window
{
    private readonly LogView _log;
    private readonly TextBox _input;
    private readonly Button _send;
    private readonly Button _close;
    private readonly Button _volUp;
    private readonly Button _volDown;
    private readonly ModuleManager _mgr = new();

    private InteractiveShell? _shell;
    private string? _serial;
    private bool _running;

    public ModuleInstallWindow(string title)
    {
        Title = title;

        var root = new Grid { Padding = new Thickness(16), RowSpacing = 12 };
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        _log = new LogView();
        Grid.SetRow(_log, 0);
        root.Children.Add(_log);

        // 按键交互：模块常要求「音量上/下」确认。
        var keys = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        _volUp = new Button
        {
            Content = "音量 +",
            IsEnabled = false,
            Style = (Style)Application.Current.Resources["DefaultButtonStyle"]
        };
        _volUp.Click += async (s, e) => await SendKeyAsync(24);
        _volDown = new Button
        {
            Content = "音量 -",
            IsEnabled = false,
            Style = (Style)Application.Current.Resources["DefaultButtonStyle"]
        };
        _volDown.Click += async (s, e) => await SendKeyAsync(25);
        keys.Children.Add(new TextBlock
        {
            Text = "按键交互：",
            VerticalAlignment = VerticalAlignment.Center,
            Style = (Style)Application.Current.Resources["CaptionTextStyle"]
        });
        keys.Children.Add(_volUp);
        keys.Children.Add(_volDown);
        Grid.SetRow(keys, 1);
        root.Children.Add(keys);

        // 文本交互：等待 y/n 或其他输入时使用。
        var footer = new Grid { ColumnSpacing = 8 };
        footer.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        footer.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        footer.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        _input = new TextBox { PlaceholderText = "需要输入确认时在此填写（如 y），回车发送", IsEnabled = false };
        _input.KeyDown += async (s, e) =>
        {
            if (e.Key == Windows.System.VirtualKey.Enter) { e.Handled = true; await SendTextAsync(); }
        };
        Grid.SetColumn(_input, 0);
        footer.Children.Add(_input);

        _send = new Button
        {
            Content = "发送",
            IsEnabled = false,
            Style = (Style)Application.Current.Resources["DefaultButtonStyle"]
        };
        _send.Click += async (s, e) => await SendTextAsync();
        Grid.SetColumn(_send, 1);
        footer.Children.Add(_send);

        _close = new Button
        {
            Content = "关闭",
            Style = (Style)Application.Current.Resources["DefaultButtonStyle"]
        };
        _close.Click += (s, e) => Close();
        Grid.SetColumn(_close, 2);
        footer.Children.Add(_close);

        Grid.SetRow(footer, 2);
        root.Children.Add(footer);

        Content = root;

        try
        {
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
            var id = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(hwnd);
            Microsoft.UI.Windowing.AppWindow.GetFromWindowId(id).Resize(new SizeInt32(880, 640));
        }
        catch { }

        Closed += (s, e) =>
        {
            _running = false;
            try { _shell?.Dispose(); } catch { }
            _shell = null;
        };
    }

    public void Start(string zipPath) => _ = RunAsync(new[] { zipPath });

    public void StartBatch(IEnumerable<string> zipPaths) => _ = RunAsync(zipPaths.ToList());

    private async Task RunAsync(IReadOnlyList<string> paths)
    {
        if (_running) return;
        _running = true;
        _log.ClearLog();
        _close.IsEnabled = false;

        try
        {
            var (mode, serial) = await Task.Run(() => AdbService.DetectConnectionMode());
            if (mode != "system" || string.IsNullOrEmpty(serial))
                throw new InvalidOperationException("请确保设备处于系统模式并已连接 ADB");
            _serial = serial;

            _log.AppendLog("建立交互式 root 会话...");
            _shell = await InteractiveShell.StartAsync(serial, root: true, onLine: l => _log.AppendLog(l));
            SetInteractive(true);

            foreach (var p in paths)
            {
                if (paths.Count > 1)
                {
                    _log.AppendLog("");
                    _log.AppendLog("安装: " + p);
                }
                await InstallOneAsync(p);
            }
        }
        catch (Exception ex)
        {
            _log.AppendLog(ex.Message, "#f53f3f");
        }
        finally
        {
            _running = false;
            _close.IsEnabled = true;
            SetInteractive(false);
            try { _shell?.Dispose(); } catch { }
            _shell = null;
        }
    }

    private async Task InstallOneAsync(string zipPath)
    {
        var z = new System.IO.FileInfo(zipPath);
        var sid = Guid.NewGuid().ToString("N");
        _log.StartStep(sid, $"安装模块: {z.Name}");
        try
        {
            if (!z.Exists) throw new System.IO.FileNotFoundException(zipPath);
            var serial = _serial!;
            var manager = await Task.Run(() => _mgr.DetectManager());
            if (manager == "none") throw new InvalidOperationException("未检测到 Magisk 或 KernelSU");

            var remote = $"/sdcard/{z.Name}";
            _log.AppendLog("推送模块压缩包到设备...");
            var push = await ProcessRunner.RunAsync(
                AdbService.AdbBin,
                new[] { "-s", serial, "push", zipPath, remote },
                onOutput: line => _log.AppendLog(line),
                timeoutMs: 600_000);
            if (!push.Success) throw new InvalidOperationException("推送失败: " + push.Output.Trim());

            if (manager == "magisk")
            {
                _log.AppendLog("开始安装 (Magisk)...");
                var (ok, output) = await _shell!.RunAsync($"magisk --install-module '{remote}'");
                if (!ok) throw new InvalidOperationException("Magisk 安装超时");
                if (LooksLikeFailure(output)) throw new InvalidOperationException("Magisk 安装失败：" + Trim(output));
                _log.FinishStep(sid, true, "Magisk安装完成");
                return;
            }

            _log.AppendLog("开始安装 (KernelSU)...");
            var hasKsu = (await _shell!.RunAsync("command -v ksu >/dev/null 2>&1 && echo ksu_yes || echo ksu_no")).output.Contains("ksu_yes");
            var hasKsud = (await _shell.RunAsync("command -v ksud >/dev/null 2>&1 && echo ksud_yes || echo ksud_no")).output.Contains("ksud_yes");

            var cmds = new List<string>();
            if (hasKsu) { cmds.Add($"ksu module install '{remote}'"); cmds.Add($"ksu module install --zip '{remote}'"); }
            if (hasKsud) { cmds.Add($"ksud module install '{remote}'"); cmds.Add($"ksud module install --zip '{remote}'"); }
            if (cmds.Count == 0)
                throw new InvalidOperationException("未找到 KernelSU 命令行工具（ksu/ksud）。请使用 KernelSU 管理器手动安装模块。");

            foreach (var c in cmds)
            {
                _log.AppendLog("$ " + c);
                var (ok, output) = await _shell.RunAsync(c);
                if (!ok) throw new InvalidOperationException("KernelSU 安装超时");
                if (LooksLikeFailure(output)) continue;
                _log.FinishStep(sid, true, "KernelSU安装完成");
                return;
            }
            throw new InvalidOperationException("KernelSU 安装命令执行失败");
        }
        catch (Exception e)
        {
            _log.FinishStep(sid, false, e.Message);
            throw;
        }
    }

    private static bool LooksLikeFailure(string output)
    {
        if (string.IsNullOrWhiteSpace(output)) return false;
        var o = output.ToLowerInvariant();
        return o.Contains("not found") || o.Contains("unknown command") ||
               o.Contains("no such file") || o.Contains("failed") || o.Contains("error");
    }

    private static string Trim(string s)
    {
        s = s.Trim();
        return s.Length > 400 ? s[..400] + "..." : s;
    }

    private async Task SendTextAsync()
    {
        if (_shell == null) return;
        var text = _input.Text ?? "";
        try
        {
            await _shell.SendAsync(text);
            _log.AppendLog("> " + text, "#4098ff");
            _input.Text = "";
        }
        catch (Exception ex) { _log.AppendLog("发送失败: " + ex.Message, "#f53f3f"); }
    }

    private async Task SendKeyAsync(int code)
    {
        if (_serial == null) return;
        try
        {
            await Task.Run(() => AdbService.AdbShellSerial(_serial, $"input keyevent {code}", 15));
            _log.AppendLog($"→ 已发送按键 keyevent {code}", "#4098ff");
        }
        catch (Exception ex) { _log.AppendLog("按键发送失败: " + ex.Message, "#f53f3f"); }
    }

    private void SetInteractive(bool on)
    {
        DispatcherQueue.TryEnqueue(() =>
        {
            _input.IsEnabled = on;
            _send.IsEnabled = on;
            _volUp.IsEnabled = on;
            _volDown.IsEnabled = on;
        });
    }
}
