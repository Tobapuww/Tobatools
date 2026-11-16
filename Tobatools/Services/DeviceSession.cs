using System;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.UI.Dispatching;
using Tobatools.Models;

namespace Tobatools.Services
{
    /// <summary>统一设备会话：串行检测，先发布连接状态，再采集详情，所有通知回到主窗口线程。</summary>
    public class DeviceSession
    {
        public static DeviceSession Instance { get; } = new();
        private CancellationTokenSource? _cts;
        private DispatcherQueue? _dispatcher;
        private readonly object _lock = new();
        private readonly SemaphoreSlim _refreshSignal = new(0, 1);
        private readonly SemaphoreSlim _pollGate = new(1, 1);

        public AdbService.ConnectionSummary? Summary { get; private set; }
        public DeviceInfo? Info { get; private set; }
        public event Action? StateChanged;
        public bool IsConnected => Summary?.Connected == true;
        private DeviceSession() { }

        // 必须由创建窗口的 UI 线程传入，不能在后台使用 Window.Current。
        public void Start(DispatcherQueue dispatcher)
        {
            ArgumentNullException.ThrowIfNull(dispatcher);
            lock (_lock)
            {
                if (_cts != null) return;
                _dispatcher = dispatcher;
                var cts = new CancellationTokenSource();
                _cts = cts;
                _ = Task.Run(() => PollLoop(cts.Token));
            }
        }

        public void Stop()
        {
            lock (_lock)
            {
                _cts?.Cancel();
                _cts = null;
            }
        }

        /// <summary>合并重复刷新请求，避免按钮点击与定时轮询同时采集设备信息。</summary>
        public void RefreshNow()
        {
            try { _refreshSignal.Release(); }
            catch (SemaphoreFullException) { }
        }

        private async Task PollLoop(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                try
                {
                    await _pollGate.WaitAsync(ct).ConfigureAwait(false);
                    try { RefreshCore(ct); }
                    finally { _pollGate.Release(); }
                    await _refreshSignal.WaitAsync(TimeSpan.FromSeconds(3), ct).ConfigureAwait(false);
                }
                catch (OperationCanceledException) { break; }
                catch (Exception ex) { Debug.WriteLine($"Device poll failed: {ex}"); }
            }
        }

        private void RefreshCore(CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            AdbService.ConnectionSummary summary;
            try { summary = AdbService.GetConnectionSummary(); }
            catch (Exception ex)
            {
                summary = new AdbService.ConnectionSummary
                {
                    Mode = "error", StatusLine = "设备检测失败：" + ex.Message,
                    StatusConn = "设备检测失败", StatusColor = "#D13438"
                };
                Publish(summary, null, ct);
                return;
            }

            // 连接结果无需等待几十个 getprop / shell 查询结束。
            Publish(summary, null, ct);
            DeviceInfo? info = null;
            try
            {
                ct.ThrowIfCancellationRequested();
                if (summary.Connected && summary.Mode == "system" && !string.IsNullOrEmpty(summary.Serial))
                    info = AdbService.GetDeviceInfo(summary.Serial);
                else if (summary.Mode is "fastbootd" or "bootloader")
                    info = AdbService.CollectOverallInfo();
            }
            catch (OperationCanceledException) { throw; }
            catch (Exception ex) { Debug.WriteLine($"Device details failed: {ex}"); }
            if (info != null) Publish(summary, info, ct);
        }

        private void Publish(AdbService.ConnectionSummary summary, DeviceInfo? info, CancellationToken ct)
        {
            if (ct.IsCancellationRequested) return;
            var dispatcher = _dispatcher;
            if (dispatcher == null) return;
            bool queued = dispatcher.TryEnqueue(() =>
            {
                if (ct.IsCancellationRequested) return;
                bool sameDevice = Summary?.Serial == summary.Serial && Summary?.Mode == summary.Mode;
                Summary = summary;
                Info = info ?? (sameDevice && summary.Connected ? Info : null);
                // 单个页面异常不能阻止其他页面接收设备更新。
                var handlers = StateChanged;
                if (handlers == null) return;
                foreach (Action handler in handlers.GetInvocationList())
                {
                    try { handler(); }
                    catch (Exception ex) { Debug.WriteLine($"Device UI update failed: {ex}"); }
                }
            });
            if (!queued) Debug.WriteLine("Device UI update skipped: dispatcher is shutting down.");
        }
    }
}
