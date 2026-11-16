using L = Tobatools.Services.LocalizationService;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Tobatools.Dialogs;
using Tobatools.Models;
using Tobatools.Services;
using Windows.UI;

namespace Tobatools.Pages
{
    public sealed partial class DashboardPage : Page
    {
        private readonly Dictionary<string, TextBlock> _infoLabels = new();
        private bool _loaded;
        private bool _paramsExpanded;

        public DashboardPage()
        {
            InitializeComponent();
            RebootMode.Items.Add(L.Instance.Get("Pages/Dashboard_025"));
            RebootMode.Items.Add("Recovery");
            RebootMode.Items.Add("Bootloader");
            RebootMode.Items.Add("FastbootD");
            RebootMode.Items.Add("EDL (9008)");
            RebootMode.SelectedIndex = 0;

            BuildParamSections();
        }

        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            if (_loaded) return;
            _loaded = true;
            DeviceSession.Instance.StateChanged += OnDeviceChanged;
            Refresh();
        }

        private void OnUnloaded(object sender, RoutedEventArgs e)
        {
            DeviceSession.Instance.StateChanged -= OnDeviceChanged;
            _loaded = false;
        }

        private void OnDeviceChanged() => Refresh();

        private void BuildParamSections()
        {
            // 规格速览：机型身份与硬件概要，始终可见。
            var spec = new (string Key, string Label)[]
            {
                ("cpu_info", L.Instance.Get("Pages/Dashboard_031")),
                ("resolution", L.Instance.Get("Pages/Dashboard_032")),
                ("display_density", L.Instance.Get("Pages/Dashboard_033")),
                ("android_version", L.Instance.Get("Pages/Dashboard_037")),
                ("sdk", L.Instance.Get("Pages/Dashboard_038")),
                ("device", L.Instance.Get("Pages/Dashboard_098")),
            };
            // 状态参数：锁、Root、槽位、内核等关键项，始终可见。
            var param = new (string Key, string Label)[]
            {
                ("bootloader_unlock", L.Instance.Get("Pages/Dashboard_041")),
                ("root_status", L.Instance.Get("Pages/Dashboard_042")),
                ("current_slot", L.Instance.Get("Pages/Dashboard_043")),
                ("kernel", L.Instance.Get("Pages/Dashboard_039")),
                ("storage_type", L.Instance.Get("Pages/Dashboard_034")),
                ("vndk", L.Instance.Get("Pages/Dashboard_040")),
            };
            // 次要项，收进“展开更多参数”。
            var extra = new (string Key, string Label)[]
            {
                ("battery_health", L.Instance.Get("Pages/Dashboard_035")),
                ("battery_cap", L.Instance.Get("Pages/Dashboard_036")),
                ("uptime", L.Instance.Get("Pages/Dashboard_044")),
                ("product", L.Instance.Get("Pages/Dashboard_099")),
                ("baseband", L.Instance.Get("Pages/Dashboard_100")),
                ("bootloader", L.Instance.Get("Pages/Dashboard_101")),
            };
            FillRows(SpecGrid, spec);
            FillRows(ParamGrid, param);
            FillRows(ExtraParams, extra);
        }

        private void FillRows(StackPanel host, (string Key, string Label)[] items)
        {
            foreach (var (key, label) in items)
            {
                var row = BuildRow(label, out var value);
                host.Children.Add(row);
                _infoLabels[key] = value;
            }
        }

        private Grid BuildRow(string label, out TextBlock value)
        {
            var row = new Grid { ColumnSpacing = 16 };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(108) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            var labelBlock = new TextBlock
            {
                Text = label,
                Style = (Style)Application.Current.Resources["CaptionTextStyle"],
                VerticalAlignment = VerticalAlignment.Center,
            };
            value = new TextBlock
            {
                Style = (Style)Application.Current.Resources["BodyTextStyle"],
                IsTextSelectionEnabled = true,
            };
            Grid.SetColumn(labelBlock, 0);
            Grid.SetColumn(value, 1);
            row.Children.Add(labelBlock);
            row.Children.Add(value);
            return row;
        }

        private bool _didFirstShow;
        private bool _pendingConnectNotice;
        private (string banner, string mode, string serial)? _lastConnBanner;

        /// <summary>
        /// 与 Python device_info_tab.py L1151-1193 一致：连接状态横幅只在 (banner_state, mode, serial)
        /// 真正变化时提示，避免每次刷新都弹一次。
        /// </summary>
        private void UpdateConnNotice(AdbService.ConnectionSummary? summary)
        {
            var mode = summary?.Mode ?? "";
            var serial = summary?.Serial ?? "";
            var bannerState = summary?.BannerState ?? "";
            var key = (bannerState, mode, serial);
            var lastKey = _lastConnBanner;
            var lastMode = lastKey?.mode ?? "";

            if (_didFirstShow && lastKey != null && key != lastKey.Value)
            {
                if (mode is "system" or "sideload" && (_pendingConnectNotice || lastMode is not ("system" or "sideload")))
                {
                    ShowConnNotice(InfoBarSeverity.Success, L.Instance.Get("Pages/Dashboard_086"),
                        L.Instance.Format("Pages/Dashboard_087", ModeCn(mode)));
                    _pendingConnectNotice = false;
                }
                else if (mode is "fastbootd" or "bootloader" or "edl" or "brom")
                {
                    ShowConnNotice(InfoBarSeverity.Informational, L.Instance.Get("Pages/Dashboard_088"),
                        L.Instance.Format("Pages/Dashboard_087", ModeCn(mode)));
                    _pendingConnectNotice = false;
                }
                else if (mode == "offline")
                {
                    ShowConnNotice(InfoBarSeverity.Warning, L.Instance.Get("Pages/Dashboard_089"),
                        L.Instance.Get("Pages/Dashboard_090"));
                }
                else if (mode == "none")
                {
                    ShowConnNotice(InfoBarSeverity.Warning, L.Instance.Get("Pages/Dashboard_091"),
                        L.Instance.Get("Pages/Dashboard_092"));
                }
            }
            _lastConnBanner = key;
            if (!_didFirstShow) _didFirstShow = true;
        }

        private void ShowConnNotice(InfoBarSeverity severity, string title, string message)
        {
            ConnNotice.Severity = severity;
            ConnNotice.Title = title;
            ConnNotice.Message = message;
            ConnNotice.IsOpen = true;
        }

        private string ModeCn(string mode) => AdbService.ModeCn(mode);

        private void Refresh()
        {
            var summary = DeviceSession.Instance.Summary;
            var info = DeviceSession.Instance.Info;
            UpdateConnNotice(summary);

            string title;
            if (summary != null && summary.Connected)
            {
                var mode = summary.Mode;
                if (mode is "system" or "sideload" && info != null)
                {
                    var preferZh = L.Instance.EffectiveLanguageCode == L.LangZhCN;
                    var marketing = DeviceNameResolver.Instance.Resolve(info.Model, info.Device, preferZh);
                    if (!string.IsNullOrEmpty(marketing))
                    {
                        title = marketing;
                    }
                    else
                    {
                        var parts = new List<string>();
                        if (!string.IsNullOrEmpty(info.Brand)) parts.Add(info.Brand);
                        if (!string.IsNullOrEmpty(info.Model)) parts.Add(info.Model);
                        title = parts.Count > 0 ? string.Join(" ", parts) : L.Instance.Get("Pages/Dashboard_045");
                    }
                }
                else if (mode is "fastbootd" or "bootloader")
                    title = string.IsNullOrEmpty(info?.Product) ? L.Instance.Get("Pages/Dashboard_046") : info.Product;
                else if (mode is "edl" or "brom")
                    title = L.Instance.Get("Pages/Dashboard_047");
                else title = L.Instance.Get("Pages/Dashboard_045");
            }
            else if (summary?.Mode == "unauthorized")
                title = L.Instance.Get("Pages/Dashboard_048");
            else if (summary?.Mode == "offline")
                title = L.Instance.Get("Pages/Dashboard_049");
            else if (summary?.Mode == "error")
                title = L.Instance.Get("Pages/Dashboard_050");
            else
                title = summary == null ? L.Instance.Get("Pages/Dashboard_004") : L.Instance.Get("Pages/Dashboard_051");

            TxtHeroModel.Text = title;
            var statusLine = summary?.StatusLine ?? L.Instance.Get("Pages/Dashboard_005");
            var colorHex = summary?.StatusColor ?? "#86909c";
            TxtHeroStatus.Text = statusLine;
            StatusDot.Fill = new SolidColorBrush(ParseColor(colorHex));
            TxtHeroSerial.Text = L.Instance.Get("Pages/Dashboard_053") + (string.IsNullOrEmpty(summary?.Serial) ? "-" : summary.Serial);

            string unavailable = summary?.Connected == true ? L.Instance.Get("Pages/Dashboard_054") : L.Instance.Get("Pages/Dashboard_055");
            bool hasBattery = int.TryParse(info?.Battery, out int battery) && battery is >= 0 and <= 100;
            RingBattery.SetValue(hasBattery ? battery : 0, hasBattery ? $"{battery}%" : "—", L.Instance.Get("Pages/Dashboard_056"));
            TxtBatteryDetail.Text = hasBattery
                ? (string.IsNullOrWhiteSpace(info?.BatteryHealthPercent) ? L.Instance.Get("Pages/Dashboard_057") : L.Instance.Format("Pages/Dashboard_058", info.BatteryHealthPercent))
                : unavailable;

            var storage = (info?.StorageData ?? "").Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
            int storagePct = 0;
            bool hasStorage = storage.Length >= 5 && storage[4].EndsWith('%') &&
                int.TryParse(storage[4].TrimEnd('%'), out storagePct) && storagePct is >= 0 and <= 100;
            RingStorage.SetValue(hasStorage ? storagePct : 0, hasStorage ? $"{storagePct}%" : "—", L.Instance.Get("Pages/Dashboard_059"));
            TxtStorageDetail.Text = hasStorage ? L.Instance.Format("Pages/Dashboard_060", storage[2], storage[1]) : unavailable;

            bool hasMemory = int.TryParse(info?.MemoryPercent, out int memPct) && memPct is >= 0 and <= 100;
            RingMemory.SetValue(hasMemory ? memPct : 0, hasMemory ? $"{memPct}%" : "—", L.Instance.Get("Pages/Dashboard_061"));
            TxtMemoryDetail.Text = hasMemory ? info?.MemorySummary : unavailable;

            // 规格速览
            SetInfo("cpu_info", info?.CpuInfo ?? "");
            SetInfo("resolution", info?.Resolution ?? "");
            SetInfo("display_density", info?.DisplayDensity ?? "");
            SetInfo("android_version", info?.AndroidVersion ?? "");
            SetInfo("sdk", info?.Sdk ?? "");
            SetInfo("device", string.IsNullOrEmpty(info?.Device) ? info?.Codename ?? "" : info.Device);

            // 状态参数
            SetInfo("bootloader_unlock", TranslateLock(info?.BootloaderUnlock));
            SetInfo("root_status", info?.RootStatus ?? "");
            SetInfo("current_slot", info?.CurrentSlot ?? "");
            SetInfo("kernel", info?.Kernel ?? "");
            SetInfo("storage_type", info?.StorageType ?? "");
            SetInfo("vndk", info?.Vndk ?? "");

            // 折叠次要项
            SetInfo("battery_health", info?.BatteryHealthPercent ?? "");
            SetInfo("battery_cap", string.IsNullOrWhiteSpace(info?.BatteryFullCapacity)
                ? info?.BatteryRatedCapacity ?? "" : info.BatteryFullCapacity);
            SetInfo("uptime", info?.Uptime ?? "");
            SetInfo("product", info?.Product ?? "");
            SetInfo("baseband", info?.Baseband ?? "");
            SetInfo("bootloader", info?.Bootloader ?? "");

            // 设备选择器
            RefreshDeviceSelector();
        }

        private static string TranslateLock(string? s)
        {
            return s?.ToLowerInvariant() switch
            {
                "unlocked" => L.Instance.Get("Pages/Dashboard_062"),
                "locked" => L.Instance.Get("Pages/Dashboard_063"),
                _ => string.IsNullOrEmpty(s) ? "-" : s!,
            };
        }

        private void SetInfo(string key, string value)
        {
            if (_infoLabels.TryGetValue(key, out var tb))
                tb.Text = string.IsNullOrEmpty(value) ? "-" : value;
        }

        private void RefreshDeviceSelector()
        {
            var summary = DeviceSession.Instance.Summary;
            var current = DeviceSession.Instance.Info?.Serial ?? summary?.Serial ?? "";
            var serials = AdbService.ListDevices() ?? new List<string>();

            // 与 Python _refresh_device_selector 一致：当前设备不在列表里时，
            // 先插一条带模式说明的前缀项，再追加所有序列号，最后按前缀选中当前设备。
            var items = new List<string>();
            var mode = summary?.Mode ?? "none";
            if (current.Length > 0 && !serials.Contains(current))
                items.Add($"{current} ({AdbService.ModeCn(mode) ?? "当前"})");
            items.AddRange(serials);
            if (items.Count == 0) items.Add(L.Instance.Get("Pages/Dashboard_064"));

            DeviceSelector.Items.Clear();
            foreach (var item in items) DeviceSelector.Items.Add(item);

            var idx = 0;
            if (current.Length > 0)
            {
                for (int i = 0; i < items.Count; i++)
                {
                    if (items[i].StartsWith(current, StringComparison.Ordinal)) { idx = i; break; }
                }
            }
            DeviceSelector.SelectedIndex = idx;
        }

        private static Color ParseColor(string hex)
        {
            hex = hex.TrimStart('#');
            if (hex.Length == 6)
                return Windows.UI.Color.FromArgb(255, Convert.ToByte(hex.Substring(0, 2), 16), Convert.ToByte(hex.Substring(2, 2), 16), Convert.ToByte(hex.Substring(4, 2), 16));
            if (hex.Length == 8)
                return Windows.UI.Color.FromArgb(Convert.ToByte(hex.Substring(0, 2), 16), Convert.ToByte(hex.Substring(2, 2), 16), Convert.ToByte(hex.Substring(4, 2), 16), Convert.ToByte(hex.Substring(6, 2), 16));
            return Windows.UI.Color.FromArgb(255, 134, 144, 156);
        }

        private void OnToggleParams(object sender, RoutedEventArgs e)
        {
            _paramsExpanded = !_paramsExpanded;
            ExtraParams.Visibility = _paramsExpanded ? Visibility.Visible : Visibility.Collapsed;
            BtnToggleParams.Content = L.Instance.Get(_paramsExpanded ? "Pages/Dashboard_096" : "Pages/Dashboard_095");
        }

        private async void OnConnectClick(object sender, RoutedEventArgs e)
        {
            var dlg = new WirelessConnectDialog { XamlRoot = XamlRoot };
            await dlg.ShowAsync();
        }

        private async void OnRefreshClick(object sender, RoutedEventArgs e)
        {
            DeviceSession.Instance.RefreshNow();
            await Task.CompletedTask;
        }

        private bool _rebooting;

        private async void OnRebootClick(object sender, RoutedEventArgs e)
        {
            // Python _do_reboot 在已执行时直接提示并返回，避免重复下发重启指令。
            if (_rebooting)
            {
                ShowTip(L.Instance.Get("Pages/Dashboard_083"), L.Instance.Get("Pages/Dashboard_084"), true);
                return;
            }
            var mapping = new Dictionary<string, string>
            {
                [L.Instance.Get("Pages/Dashboard_025")] = "system",
                ["Recovery"] = "recovery",
                ["Bootloader"] = "bootloader",
                ["FastbootD"] = "fastbootd",
                ["EDL (9008)"] = "edl",
            };
            var target = mapping.GetValueOrDefault(RebootMode.SelectedItem?.ToString() ?? "", "system");
            _rebooting = true;
            try
            {
                var (ok, msg) = await Task.Run(() => AdbService.RebootTo(target));
                DeviceSession.Instance.RefreshNow();
                ShowTip(ok ? L.Instance.Get("Pages/Dashboard_065") : L.Instance.Get("Pages/Dashboard_066"), msg, ok);
            }
            finally { _rebooting = false; }
        }

        private async void OnOpenDeviceManager(object sender, RoutedEventArgs e)
        {
            try { Process.Start(new ProcessStartInfo("devmgmt.msc") { UseShellExecute = true }); }
            catch (Exception ex) { ShowTip(L.Instance.Get("Pages/Dashboard_069"), ex.Message, false); }
        }

        private async void OnRestartAdb(object sender, RoutedEventArgs e)
        {
            // 与 Python 对话框同类逻辑：kill-server 后等待 1 秒再 start-server，并区分成功/失败。
            bool restarted = true;
            string restartMsg = "";
            await Task.Run(() =>
            {
                try
                {
                    AdbService.AdbKillServer();
                    System.Threading.Thread.Sleep(1000);
                    AdbService.AdbStartServer();
                }
                catch (Exception ex) { restarted = false; restartMsg = ex.Message; }
            });
            DeviceSession.Instance.RefreshNow();
            ShowTip(
                restarted ? L.Instance.Get("Pages/Dashboard_067") : L.Instance.Get("Pages/Dashboard_082"),
                restarted ? L.Instance.Get("Pages/Dashboard_068") : restartMsg,
                restarted);
        }

        private void ShowTip(string title, string message, bool success)
        {
            // success 决定提示图标/配色，失败时不再和成功长得一样。
            var panel = new StackPanel { Spacing = 8 };
            var bar = new InfoBar
            {
                IsOpen = true,
                IsClosable = false,
                Severity = success ? InfoBarSeverity.Success : InfoBarSeverity.Error,
                Message = title,
            };
            panel.Children.Add(bar);
            if (!string.IsNullOrWhiteSpace(message))
                panel.Children.Add(new TextBlock { Text = message, TextWrapping = TextWrapping.Wrap });
            var dlg = new ContentDialog
            {
                Title = title,
                Content = panel,
                CloseButtonText = L.Instance.Get("Pages/Dashboard_070"),
                XamlRoot = XamlRoot,
            };
            _ = dlg.ShowAsync();
        }
    }
}
