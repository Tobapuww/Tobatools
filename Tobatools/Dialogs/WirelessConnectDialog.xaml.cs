using System;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Tobatools.Services;

namespace Tobatools.Dialogs
{
    public sealed partial class WirelessConnectDialog : ContentDialog
    {
        private bool _busy;

        public WirelessConnectDialog()
        {
            InitializeComponent();
            ConnectHost.Text = SettingsService.Instance.Get("wireless/last_endpoint", "");
            Closing += (_, args) => { if (_busy) args.Cancel = true; };
        }

        private async void OnPairClick(object sender, RoutedEventArgs e)
        {
            if (_busy) return;
            if (!WirelessAdb.TryEndpoint(PairHost.Text, true, out var endpoint, out var error))
            {
                ShowResult(error, InfoBarSeverity.Warning);
                return;
            }
            var code = PairCode.Text?.Trim() ?? "";
            if (!WirelessAdb.IsPairingCode(code))
            {
                ShowResult("请填写设备配对窗口显示的 6 位数字配对码。", InfoBarSeverity.Warning);
                return;
            }
            SetBusy(true);
            ShowResult("正在配对，请保持设备上的配对窗口开启…", InfoBarSeverity.Informational);
            try
            {
                var (rc, message) = await Task.Run(() => AdbService.AdbPair(endpoint, "", code));
                if (rc == 0)
                {
                    PairCode.Text = "";
                    ShowResult("配对成功。请返回设备的无线调试主页，将该页面的 IP 地址和连接端口填入下方，再点击“连接”。配对端口不能当作连接端口。", InfoBarSeverity.Success);
                    // 部分 Android 版本配对后会通过 mDNS 自动连接，统一会话也需及时刷新。
                    DeviceSession.Instance.RefreshNow();
                }
                else ShowResult("配对失败：" + message, InfoBarSeverity.Error);
            }
            catch (Exception ex) { ShowResult("配对异常：" + ex.Message, InfoBarSeverity.Error); }
            finally { SetBusy(false); }
        }

        private async void OnPrimaryClick(ContentDialog sender, ContentDialogButtonClickEventArgs args)
        {
            // WinUI 事件必须获取延迟令牌，才能在 await 后可靠地决定是否关闭对话框。
            args.Cancel = true;
            if (_busy) return;
            if (!WirelessAdb.TryEndpoint(ConnectHost.Text, false, out var endpoint, out var error))
            {
                ShowResult(error, InfoBarSeverity.Warning);
                return;
            }
            var deferral = args.GetDeferral();
            SetBusy(true);
            ShowResult($"正在连接 {endpoint}，最长等待约 10 秒…", InfoBarSeverity.Informational);
            try
            {
                var (rc, message) = await Task.Run(() => AdbService.AdbConnect(endpoint, ""));
                if (rc != 0)
                {
                    ShowResult($"连接失败：{message}\n\n{WirelessAdb.FailureHint(endpoint, message)}", InfoBarSeverity.Error);
                    return;
                }
                SettingsService.Instance.Set("wireless/last_endpoint", endpoint);
                DeviceSession.Instance.RefreshNow();
                ShowResult("ADB 连接成功，正在刷新设备状态。", InfoBarSeverity.Success);
                args.Cancel = false;
            }
            catch (Exception ex) { ShowResult("连接异常：" + ex.Message, InfoBarSeverity.Error); }
            finally
            {
                SetBusy(false);
                deferral.Complete();
            }
        }

        private async void OnAutoPairClick(object sender, RoutedEventArgs e)
        {
            if (_busy) return;
            var code = PairCode.Text?.Trim() ?? "";
            if (!WirelessAdb.IsPairingCode(code))
            {
                ShowResult("请填写设备配对窗口显示的 6 位数字配对码。", InfoBarSeverity.Warning);
                return;
            }
            SetBusy(true);
            ShowResult("正在通过 mDNS 查找配对服务…", InfoBarSeverity.Informational);
            try
            {
                // 与 Python _start_mdns_scan / _run_adb 一致：轮询 adb mdns services，
                // 匹配 _adb-tls-pairing._tcp. 后自动配对，再查 _adb-tls-connect._tcp. 得连接端口。
                var found = await Task.Run(() => FindMdns(_adbPairingService, 60));
                if (found == null)
                {
                    ShowResult("未找到配对服务（请确认手机已扫描配对二维码/显示配对码，且与电脑在同一局域网）。", InfoBarSeverity.Warning);
                    return;
                }
                var (ip, port) = found.Value;
                PairHost.Text = $"{ip}:{port}";
                ShowResult($"发现配对服务，正在配对 {ip}:{port} …", InfoBarSeverity.Informational);
                var (rc, message) = await Task.Run(() => AdbService.AdbPair(ip, port, code));
                if (rc != 0)
                {
                    ShowResult("配对失败：" + message, InfoBarSeverity.Error);
                    return;
                }
                PairCode.Text = "";
                var conn = await Task.Run(() => FindMdns(_adbConnectService, 20));
                if (conn != null)
                {
                    ConnectHost.Text = $"{conn.Value.ip}:{conn.Value.port}";
                    ShowResult($"配对成功，已自动填入连接地址 {ConnectHost.Text}，请点击“连接”。", InfoBarSeverity.Success);
                }
                else
                {
                    ShowResult("配对成功。请在手机的无线调试主页查看 IP 和连接端口并填入下方，再点击“连接”。", InfoBarSeverity.Success);
                }
                DeviceSession.Instance.RefreshNow();
            }
            catch (Exception ex) { ShowResult("自动配对异常：" + ex.Message, InfoBarSeverity.Error); }
            finally { SetBusy(false); }
        }

        private const string _adbPairingService = "_adb-tls-pairing._tcp.";
        private const string _adbConnectService = "_adb-tls-connect._tcp.";

        /// <summary>轮询 adb mdns services 找匹配服务，返回 (ip, port)；超时返回 null。</summary>
        private static (string ip, string port)? FindMdns(string service, int timeoutSeconds)
        {
            var deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
            var rx = new System.Text.RegularExpressions.Regex(
                @"([^\s]+)\s+" + System.Text.RegularExpressions.Regex.Escape(service) + @"\s+([^:]+):([0-9]+)");
            while (DateTime.UtcNow < deadline)
            {
                var (code, output) = AdbService.AdbMdnsServices(5);
                if (code == 0 && !string.IsNullOrEmpty(output))
                {
                    foreach (var line in output!.Split('\n'))
                    {
                        if (!line.Contains(service, StringComparison.Ordinal)) continue;
                        var m = rx.Match(line);
                        if (!m.Success) continue;
                        var ip = m.Groups[2].Value.Trim();
                        var port = m.Groups[3].Value.Trim();
                        if (ip.Length > 0 && port.Length > 0) return (ip, port);
                    }
                }
                System.Threading.Thread.Sleep(1000);
            }
            return null;
        }

        private async void OnRestartAdbClick(object sender, RoutedEventArgs e)
        {
            if (_busy) return;
            SetBusy(true);
            ShowResult("正在重启 ADB Server…", InfoBarSeverity.Informational);
            try
            {
                var ok = await Task.Run(() =>
                {
                    AdbService.AdbKillServer();
                    System.Threading.Thread.Sleep(1000);
                    AdbService.AdbStartServer();
                    return true;
                });
                ShowResult(ok ? "ADB 已重启。" : "重启 ADB 失败。", ok ? InfoBarSeverity.Success : InfoBarSeverity.Error);
                DeviceSession.Instance.RefreshNow();
            }
            catch (Exception ex) { ShowResult("重启 ADB 失败：" + ex.Message, InfoBarSeverity.Error); }
            finally { SetBusy(false); }
        }

        private async void OnDisconnectClick(object sender, RoutedEventArgs e)
        {
            if (_busy) return;
            SetBusy(true);
            ShowResult("正在断开当前无线连接…", InfoBarSeverity.Informational);
            try
            {
                var (rc, message) = await Task.Run(() => AdbService.AdbDisconnect());
                if (rc == 0) ShowResult(string.IsNullOrWhiteSpace(message) ? "已断开。" : "已断开：" + message, InfoBarSeverity.Success);
                else ShowResult("断开失败：" + message, InfoBarSeverity.Error);
                DeviceSession.Instance.RefreshNow();
            }
            catch (Exception ex) { ShowResult("断开异常：" + ex.Message, InfoBarSeverity.Error); }
            finally { SetBusy(false); }
        }

        private void ShowResult(string text, InfoBarSeverity severity)
        {
            TxtResult.Text = text;
            ResultNotice.Severity = severity;
            ResultNotice.IsOpen = true;
        }

        private void SetBusy(bool busy)
        {
            _busy = busy;
            Busy.IsActive = busy;
            Busy.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
            BtnPair.IsEnabled = !busy;
            BtnAutoPair.IsEnabled = !busy;
            BtnRestartAdb.IsEnabled = !busy;
            BtnDisconnect.IsEnabled = !busy;
            IsPrimaryButtonEnabled = !busy;
            PairHost.IsEnabled = !busy;
            PairCode.IsEnabled = !busy;
            ConnectHost.IsEnabled = !busy;
        }
    }
}
