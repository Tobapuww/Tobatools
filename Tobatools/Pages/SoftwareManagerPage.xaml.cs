using L = Tobatools.Services.LocalizationService;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Tobatools.Models;
using Tobatools.Services;
using Windows.Storage.Pickers;
using Windows.Storage.Streams;
using System.Runtime.InteropServices.WindowsRuntime;

namespace Tobatools.Pages
{
    public sealed partial class SoftwareManagerPage : Page
    {
        private readonly ObservableCollection<AppItem> _apps = new();
        private readonly Dictionary<string, string> _labelCache = new();
        private readonly Dictionary<string, ImageSource> _iconCache = new();
        private DispatcherQueueTimer? _fgTimer;
        private CancellationTokenSource? _metadataCancellation;
        private Task? _refreshTask;
        private bool _refreshRequested;
        private bool _appsRequested;
        private bool _active;
        private bool _appsLoaded;
        private bool _operationRunning;
        private bool _dialogOpen;
        private bool _updatingItems;
        private int _disabledVersion;
        private int _generation;
        private int _appsVersion;
        private string _deviceKey = "";
        private string _sessionKey = "";
        private string _serial = "";
        private string _selectedPkg = "";
        private string _currentPkg = "";
        private string _currentActivity = "";

        public SoftwareManagerPage()
        {
            InitializeComponent();
            ListApps.ItemsSource = _apps;
            Loaded += OnLoaded;
            Unloaded += OnUnloaded;
        }

        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            if (_active) return;
            _active = true;
            if (ComboSection.Items.Count == 0)
            {
                ComboSection.Items.Add(L.Instance.Get("Pages/SoftwareManager_045"));
                ComboSection.Items.Add(L.Instance.Get("Pages/SoftwareManager_019"));
                ComboSection.Items.Add(L.Instance.Get("Pages/SoftwareManager_046"));
                ComboSection.SelectedIndex = 0;
            }
            _sessionKey = SessionKey();
            DeviceSession.Instance.StateChanged += OnDeviceStateChanged;
            _fgTimer = (App.Instance?.MainWin?.DispatcherQueue ?? DispatcherQueue).CreateTimer();
            _fgTimer.Interval = TimeSpan.FromSeconds(3);
            _fgTimer.Tick += OnForegroundTick;
            if (ChkAutoRefresh.IsChecked == true) _fgTimer.Start();
            SetNotice(L.Instance.Get("Pages/SoftwareManager_047"), L.Instance.Get("Pages/SoftwareManager_048"), InfoBarSeverity.Informational);
            _ = RequestRefreshAsync(true);
        }

        private void OnUnloaded(object sender, RoutedEventArgs e)
        {
            _active = false;
            DeviceSession.Instance.StateChanged -= OnDeviceStateChanged;
            if (_fgTimer != null)
            {
                _fgTimer.Stop();
                _fgTimer.Tick -= OnForegroundTick;
                _fgTimer = null;
            }
            _refreshRequested = false;
            _appsRequested = false;
            InvalidateDevice();
            _deviceKey = "";
        }

        private static string SessionKey()
        {
            var summary = DeviceSession.Instance.Summary;
            return summary == null ? "" : $"{summary.Serial}|{summary.Mode}|{summary.Connected}";
        }

        private void OnDeviceStateChanged()
        {
            if (!_active) return;
            var key = SessionKey();
            if (key == _sessionKey) return;
            _sessionKey = key;
            // 连接摘要先于完整详情发布；不依赖 Info 是否已经采集完毕。
            InvalidateDevice();
            _deviceKey = "";
            SetNotice(L.Instance.Get("Pages/SoftwareManager_049"), L.Instance.Get("Pages/SoftwareManager_050"), InfoBarSeverity.Informational);
            _ = RequestRefreshAsync(true);
        }

        private void InvalidateDevice()
        {
            _generation++;
            _appsVersion++;
            _metadataCancellation?.Cancel();
            _metadataCancellation?.Dispose();
            _metadataCancellation = null;
            _serial = "";
            _appsLoaded = false;
            _apps.Clear();
            _labelCache.Clear();
            _iconCache.Clear();
            OnClearSelected(this, new RoutedEventArgs());
            _currentPkg = "";
            _currentActivity = "";
            TxtFgPkg.Text = "—";
            TxtFgAct.Text = "—";
            TxtDevice.Text = L.Instance.Get("Pages/SoftwareManager_014");
            TxtAppCount.Text = L.Instance.Get("Pages/SoftwareManager_010");
        }

        private bool IsCurrent(int generation, string serial) =>
            _active && generation == _generation && serial.Length > 0 && serial == _serial;

        private void SetNotice(string title, string message, InfoBarSeverity severity)
        {
            DeviceNotice.Title = title;
            DeviceNotice.Message = message;
            DeviceNotice.Severity = severity;
            DeviceNotice.IsOpen = true;
        }

        private void ShowDeviceWarning()
        {
            if (!DeviceNotice.IsOpen)
                SetNotice(L.Instance.Get("Pages/SoftwareManager_051"), L.Instance.Get("Pages/SoftwareManager_052"), InfoBarSeverity.Warning);
        }

        // 合并按钮、Loaded 和定时器请求：设备检测、前台和应用列表不会相互重叠。
        private Task RequestRefreshAsync(bool apps = false)
        {
            if (!_active) return Task.CompletedTask;
            _refreshRequested = true;
            _appsRequested |= apps;
            if (_refreshTask == null || _refreshTask.IsCompleted)
                _refreshTask = RefreshLoopAsync();
            return _refreshTask;
        }

        private async Task RefreshLoopAsync()
        {
            // 确保 _refreshTask 先赋值，避免同步完成或事件重入造成重复刷新。
            await Task.Yield();
            while (_active && _refreshRequested)
            {
                _refreshRequested = false;
                var loadApps = _appsRequested;
                _appsRequested = false;
                var generation = _generation;
                AppsProgress.Visibility = Visibility.Visible;
                try
                {
                    var states = await Task.Run(() => AdbService.ListDeviceStates());
                    if (!_active || generation != _generation) continue;
                    ApplyDeviceStates(states);
                    var serial = _serial;
                    generation = _generation;
                    if (serial.Length == 0) continue;
                    if (loadApps || !_appsLoaded) await RefreshAppsAsync(serial, generation);
                    if (!IsCurrent(generation, serial)) continue;
                    var (pkg, act) = await Task.Run(() => FetchForeground(serial));
                    if (!IsCurrent(generation, serial)) continue;
                    _currentPkg = pkg;
                    _currentActivity = act;
                    TxtFgPkg.Text = pkg.Length == 0 ? "—" : pkg;
                    TxtFgAct.Text = act.Length == 0 ? "—" : act;
                }
                catch (Exception ex)
                {
                    if (_active && generation == _generation)
                    {
                        InvalidateDevice();
                        _deviceKey = "";
                        TxtDevice.Text = L.Instance.Get("Pages/SoftwareManager_053");
                        TxtAppCount.Text = L.Instance.Get("Pages/SoftwareManager_054");
                        SetNotice(L.Instance.Get("Pages/Dashboard_050"), ex.Message, InfoBarSeverity.Error);
                        Log.AppendLog(L.Instance.Format("Pages/SoftwareManager_055", ex.Message));
                    }
                }
                finally { AppsProgress.Visibility = Visibility.Collapsed; }
            }
        }

        private void ApplyDeviceStates(List<(string Serial, string State)> states)
        {
            var key = string.Join(";", states.OrderBy(s => s.Serial).ThenBy(s => s.State).Select(s => $"{s.Serial}:{s.State}"));
            if (_deviceKey != key)
            {
                InvalidateDevice();
                _deviceKey = key;
            }
            if (states.Count == 1 && states[0].State == "device")
            {
                _serial = states[0].Serial;
                TxtDevice.Text = _serial;
                DeviceNotice.IsOpen = false;
                return;
            }
            _serial = "";
            var message = L.Instance.Get("Pages/SoftwareManager_056");
            var title = L.Instance.Get("Pages/Dashboard_064");
            if (states.Count > 1)
            {
                title = L.Instance.Format("Pages/SoftwareManager_057", states.Count);
                message = L.Instance.Get("Pages/SoftwareManager_058");
            }
            else if (states.Count == 1)
            {
                title = states[0].State switch
                {
                    "unauthorized" => L.Instance.Get("Pages/SoftwareManager_059"),
                    "offline" => L.Instance.Get("Pages/SoftwareManager_060"),
                    "recovery" => L.Instance.Get("Pages/SoftwareManager_061"),
                    "sideload" => L.Instance.Get("Pages/SoftwareManager_062"),
                    _ => L.Instance.Get("Pages/SoftwareManager_063")
                };
                message = states[0].State == "unauthorized" ? L.Instance.Get("Pages/SoftwareManager_064") : L.Instance.Get("Pages/SoftwareManager_065");
            }
            else if (DeviceSession.Instance.Summary?.Mode is "bootloader" or "fastbootd")
            {
                title = L.Instance.Get("Pages/SoftwareManager_066");
                message = L.Instance.Get("Pages/SoftwareManager_067");
            }
            TxtDevice.Text = title;
            TxtAppCount.Text = L.Instance.Get("Pages/SoftwareManager_068");
            SetNotice(title, message, InfoBarSeverity.Warning);
        }

        private static (string, string) FetchForeground(string serial)
        {
            foreach (var args in new[]
            {
                new[] { "dumpsys", "window", "windows" },
                new[] { "dumpsys", "activity", "activities" },
                new[] { "dumpsys", "activity", "top" }
            })
            {
                var result = ScanFocus(AdbService.AdbShellSerial(serial, args, 3) ?? "");
                if (result.Item1.Length > 0) return result;
            }
            return ("", "");
        }

        private static (string, string) ScanFocus(string text)
        {
            var re = new Regex(@"\b(u\d+\s+)?(?<pkg>[a-zA-Z0-9_\.]+)\/(?<act>[a-zA-Z0-9_\.$]+)");
            foreach (var raw in text.Split('\n').Take(400))
            {
                var s = raw.Trim();
                if (!s.Contains("mCurrentFocus") && !s.Contains("mFocusedApp") && !s.Contains("mResumedActivity")) continue;
                var m = re.Match(s);
                if (!m.Success) continue;
                var pkg = m.Groups["pkg"].Value;
                var act = m.Groups["act"].Value;
                if (act.StartsWith('.')) act = pkg + act;
                return (pkg, $"{pkg}/{act}");
            }
            return ("", "");
        }

        private void OnForegroundTick(DispatcherQueueTimer sender, object args) => _ = RequestRefreshAsync();
        private void OnRefreshState(object sender, RoutedEventArgs e) => _ = RequestRefreshAsync();
        private void OnAutoRefreshChanged(object sender, RoutedEventArgs e)
        {
            if (_fgTimer == null) return;
            if (ChkAutoRefresh.IsChecked == true) { _fgTimer.Start(); _ = RequestRefreshAsync(); }
            else _fgTimer.Stop();
        }

        private void OnRefreshApps(object sender, RoutedEventArgs e) => _ = RequestRefreshAsync(true);
        private void OnSearchChanged(object sender, TextChangedEventArgs e)
        {
            if (ListApps != null) ApplyFilter();
        }

        private void ApplyFilter()
        {
            var q = TxtSearch.Text?.Trim() ?? "";
            var selected = _selectedPkg;
            var view = _apps.Where(a => q.Length == 0 || a.Pkg.Contains(q, StringComparison.OrdinalIgnoreCase) || a.Label.Contains(q, StringComparison.OrdinalIgnoreCase)).ToList();
            var selectedItem = view.FirstOrDefault(a => a.Pkg == selected);
            _updatingItems = true;
            try
            {
                ListApps.ItemsSource = q.Length == 0 ? _apps : new ObservableCollection<AppItem>(view);
                ListApps.SelectedItem = selectedItem;
            }
            finally { _updatingItems = false; }
            _selectedPkg = selectedItem?.Pkg ?? "";
            TxtSelected.Text = _selectedPkg.Length > 0 ? _selectedPkg : L.Instance.Get("Pages/SoftwareManager_016");
            if (selected != _selectedPkg)
            {
                _disabledVersion++;
                ListDisabled.ItemsSource = null;
                TxtComponent.Text = "";
            }
            TxtAppCount.Text = _appsLoaded ? L.Instance.Format("Pages/SoftwareManager_069", _apps.Count, view.Count) : L.Instance.Get("Pages/SoftwareManager_010");
        }

        private async Task RefreshAppsAsync(string serial, int generation)
        {
            var showSystem = ChkSystem.IsChecked == true;
            TxtAppCount.Text = L.Instance.Get("Pages/SoftwareManager_070");
            _metadataCancellation?.Cancel();
            _metadataCancellation?.Dispose();
            _metadataCancellation = new CancellationTokenSource();
            var token = _metadataCancellation.Token;
            var version = ++_appsVersion;
            try
            {
                var args = new List<string> { "pm", "list", "packages" };
                if (!showSystem) args.Add("-3");
                var result = await Task.Run(() => RunSerialShell(serial, args, 30));
                if (!IsCurrent(generation, serial) || version != _appsVersion) return;
                if (!CommandSucceeded(result.Code, result.Out)) throw new InvalidOperationException(result.Out);
                var pkgs = result.Out.Split('\n').Select(l => l.Trim()).Where(l => l.StartsWith("package:"))
                    .Select(l => l[8..].Trim()).Where(p => p.Length > 0).Distinct().OrderBy(p => p, StringComparer.OrdinalIgnoreCase).ToList();
                var selected = _selectedPkg;
                _apps.Clear();
                foreach (var pkg in pkgs)
                    _apps.Add(new AppItem { Pkg = pkg, Label = _labelCache.TryGetValue(pkg, out var label) ? label : pkg, Icon = _iconCache.TryGetValue(pkg, out var icon) ? icon : null });
                _selectedPkg = selected;
                _appsLoaded = true;
                ApplyFilter();
                _ = LoadMetadataAsync(serial, generation, version, pkgs, token);
            }
            catch (Exception ex)
            {
                if (!IsCurrent(generation, serial)) return;
                _appsLoaded = false;
                _apps.Clear();
                OnClearSelected(this, new RoutedEventArgs());
                ApplyFilter();
                TxtAppCount.Text = L.Instance.Get("Pages/SoftwareManager_071");
                SetNotice(L.Instance.Get("Pages/SoftwareManager_072"), ex.Message, InfoBarSeverity.Error);
                Log.AppendLog(L.Instance.Format("Pages/SoftwareManager_073", ex.Message));
            }
        }

        private async Task LoadMetadataAsync(string serial, int generation, int version, List<string> pkgs, CancellationToken token)
        {
            try
            {
                // 仅只读查询名称，不再为自动读取标签向设备推送 aapt。
                var labels = await Task.Run(() => FetchLabels(serial, pkgs), token);
                if (!IsCurrent(generation, serial) || version != _appsVersion || token.IsCancellationRequested) return;
                foreach (var kv in labels)
                {
                    _labelCache[kv.Key] = kv.Value;
                    ReplaceAppItem(kv.Key, label: kv.Value);
                }
                ApplyFilter();
                await LoadIconsAsync(serial, generation, version, pkgs.Take(20).ToList(), token);
            }
            catch (OperationCanceledException) { }
            catch (Exception ex) { System.Diagnostics.Debug.WriteLine(L.Instance.Format("Pages/SoftwareManager_074", ex.Message)); }
        }

        private static Dictionary<string, string> FetchLabels(string serial, List<string> pkgs)
        {
            var result = new Dictionary<string, string>();
            var output = AdbService.AdbShellSerial(serial, new[] { "cmd", "package", "query-activities", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER" }, 30) ?? "";
            var curPkg = "";
            foreach (var line in output.Split('\n'))
            {
                var s = line.Trim();
                if (s.StartsWith("packageName=")) curPkg = s[12..].Trim();
                else if (s.Contains("nonLocalizedLabel=") && curPkg.Length > 0)
                {
                    var rest = s[(s.IndexOf("nonLocalizedLabel=", StringComparison.Ordinal) + "nonLocalizedLabel=".Length)..];
                    var end = rest.IndexOf(" icon=", StringComparison.Ordinal);
                    var label = (end > 0 ? rest[..end] : rest).Trim();
                    if (label.Length > 0 && label != "null" && pkgs.Contains(curPkg)) result[curPkg] = label;
                }
            }

            // 与 Python 一致：没有 launcher 标签的包，用设备端 aapt 解析 APK 取 application-label。
            var remaining = pkgs.Where(p => !result.ContainsKey(p)).ToList();
            if (remaining.Count == 0) return result;
            try
            {
                using var aapt = AaptLabelReader.TryCreate(serial);
                if (aapt == null) return result;
                var pathOut = AdbService.AdbShellSerial(serial, new[] { "pm", "list", "packages", "-f" }, 30) ?? "";
                var pkgToPath = new Dictionary<string, string>();
                foreach (var line in pathOut.Split('\n'))
                {
                    if (!line.StartsWith("package:")) continue;
                    var rest = line[8..].TrimEnd('\r');
                    var eq = rest.LastIndexOf('=');
                    if (eq <= 0) continue;
                    var apkPath = rest[..eq];
                    var pkgName = rest[(eq + 1)..].Trim();
                    if (remaining.Contains(pkgName)) pkgToPath[pkgName] = apkPath;
                }
                foreach (var pkg in remaining.Take(100))   // Python 同样限制前 100 个
                {
                    if (!pkgToPath.TryGetValue(pkg, out var apkPath)) continue;
                    var badging = aapt.DumpBadging(apkPath);
                    if (string.IsNullOrEmpty(badging)) continue;
                    var label = AaptLabelReader.PickLabel(badging!);
                    if (!string.IsNullOrEmpty(label)) result[pkg] = label!;
                }
            }
            catch { }
            return result;
        }

        private async Task LoadIconsAsync(string serial, int generation, int version, List<string> pkgs, CancellationToken token)
        {
            var paths = await Task.Run(() =>
            {
                var output = AdbService.AdbShellSerial(serial, new[] { "pm", "list", "packages", "-f" }, 30) ?? "";
                var map = new Dictionary<string, string>();
                foreach (var line in output.Split('\n'))
                {
                    var s = line.Trim();
                    if (!s.StartsWith("package:")) continue;
                    var rest = s[8..];
                    var eq = rest.LastIndexOf('=');
                    if (eq > 0) map[rest[(eq + 1)..].Trim()] = rest[..eq];
                }
                return map;
            }, token);
            foreach (var pkg in pkgs)
            {
                if (!IsCurrent(generation, serial) || version != _appsVersion || token.IsCancellationRequested) return;
                if (_iconCache.ContainsKey(pkg) || !paths.TryGetValue(pkg, out var remote)) continue;
                try
                {
                    // shell、pull、ZIP 和临时文件处理全部离开 UI 线程；不向设备写临时副本。
                    var bytes = await Task.Run(() => ReadIconBytes(serial, remote, token), token);
                    if (!IsCurrent(generation, serial) || version != _appsVersion || token.IsCancellationRequested) return;
                    if (bytes == null) continue;
                    var bmp = new BitmapImage();
                    using var ram = new InMemoryRandomAccessStream();
                    await ram.WriteAsync(bytes.AsBuffer());
                    ram.Seek(0);
                    await bmp.SetSourceAsync(ram);
                    if (!IsCurrent(generation, serial) || version != _appsVersion || token.IsCancellationRequested) return;
                    _iconCache[pkg] = bmp;
                    ReplaceAppItem(pkg, icon: bmp);
                }
                catch (OperationCanceledException) { return; }
                catch { /* 无法读取或不支持的图标保留 XAML 默认图标。 */ }
            }
        }

        private static byte[]? ReadIconBytes(string serial, string remote, CancellationToken token)
        {
            var temp = Path.Combine(Path.GetTempPath(), "toba_icon_" + Guid.NewGuid().ToString("N") + ".apk");
            try
            {
                token.ThrowIfCancellationRequested();
                var result = ProcessRunner.RunAsync(AdbService.AdbBin,
                    new[] { "-s", serial, "pull", remote, temp }, timeoutMs: 60000, ct: token).GetAwaiter().GetResult();
                token.ThrowIfCancellationRequested();
                if (!result.Success || !CommandSucceeded(result.ExitCode, result.Output) || !File.Exists(temp)) return null;
                using var zip = System.IO.Compression.ZipFile.OpenRead(temp);
                var candidates = zip.Entries.Where(e => Regex.IsMatch(e.FullName, @"\.(png|webp|jpe?g)$", RegexOptions.IgnoreCase) && e.FullName.Contains("icon", StringComparison.OrdinalIgnoreCase));
                var entry = candidates.OrderBy(e => e.FullName.Contains("ic_launcher", StringComparison.OrdinalIgnoreCase) ? 0 : 1)
                    .ThenBy(e => e.FullName.Contains("xxxhdpi") ? 0 : e.FullName.Contains("xxhdpi") ? 1 : e.FullName.Contains("xhdpi") ? 2 : 3)
                    .ThenBy(e => e.FullName.Length).FirstOrDefault();
                if (entry == null || entry.Length == 0 || entry.Length > 4 * 1024 * 1024) return null;
                using var source = entry.Open();
                using var memory = new MemoryStream();
                source.CopyTo(memory);
                return memory.ToArray();
            }
            finally { try { File.Delete(temp); } catch { } }
        }

        // AppItem 没有属性变更通知；替换集合项让 XAML OneWay 绑定重新读取名称与图标。
        private void ReplaceAppItem(string pkg, string? label = null, ImageSource? icon = null)
        {
            var old = _apps.FirstOrDefault(a => a.Pkg == pkg);
            if (old == null) return;
            var replacement = new AppItem { Pkg = old.Pkg, Label = label ?? old.Label, Icon = icon ?? old.Icon, IsSystem = old.IsSystem };
            _updatingItems = true;
            try
            {
                _apps[_apps.IndexOf(old)] = replacement;
                if (ListApps.ItemsSource is ObservableCollection<AppItem> filtered && !ReferenceEquals(filtered, _apps))
                {
                    var index = filtered.IndexOf(old);
                    if (index >= 0) filtered[index] = replacement;
                }
                if (_selectedPkg == pkg) ListApps.SelectedItem = replacement;
            }
            finally { _updatingItems = false; }
        }

        private void OnAppSelected(object sender, SelectionChangedEventArgs e)
        {
            if (_updatingItems) return;
            _disabledVersion++;
            _selectedPkg = (ListApps.SelectedItem as AppItem)?.Pkg ?? "";
            TxtSelected.Text = _selectedPkg.Length > 0 ? _selectedPkg : L.Instance.Get("Pages/SoftwareManager_016");
            ListDisabled.ItemsSource = null;
            TxtComponent.Text = "";
        }

        private void OnClearSelected(object sender, RoutedEventArgs e)
        {
            _disabledVersion++;
            _selectedPkg = "";
            TxtSelected.Text = L.Instance.Get("Pages/SoftwareManager_016");
            ListApps.SelectedItem = null;
            ListApps.SelectedIndex = -1;
            ListDisabled.ItemsSource = null;
            TxtComponent.Text = "";
        }

        private string TargetPkg() => _selectedPkg.Length > 0 ? _selectedPkg : _currentPkg;
        private static string ShellQuote(string value) => "'" + value.Replace("'", "'\"'\"'") + "'";
        private static (int Code, string Out) RunSerialShell(string serial, IEnumerable<string> args, int timeout) =>
            AdbService.RunAdb(new[] { "-s", serial, "shell", string.Join(" ", args.Select(ShellQuote)) }, timeout);
        private static bool CommandSucceeded(int code, string output) => AdbCommandResult.IsSuccessful(code, output);

        private async Task<bool> ValidateTargetAsync(string serial, int generation)
        {
            if (!IsCurrent(generation, serial)) { ShowDeviceWarning(); return false; }
            try
            {
                var states = await Task.Run(() => AdbService.ListDeviceStates());
                if (!IsCurrent(generation, serial)) return false;
                ApplyDeviceStates(states);
                if (IsCurrent(generation, serial)) return true;
                ShowDeviceWarning();
            }
            catch (Exception ex)
            {
                if (_active && generation == _generation)
                {
                    InvalidateDevice();
                    _deviceKey = "";
                    SetNotice(L.Instance.Get("Pages/Dashboard_050"), ex.Message, InfoBarSeverity.Error);
                }
            }
            return false;
        }

        private async Task<bool> RunOpAsync(string opDesc, List<string> args, string serial, int generation, bool isShell = true, string? package = null)
        {
            var logPackage = package ?? TargetPkg();
            if (_operationRunning) { SetNotice(L.Instance.Get("Pages/SoftwareManager_075"), L.Instance.Get("Pages/SoftwareManager_076"), InfoBarSeverity.Informational); return false; }
            _operationRunning = true;
            var stepId = Guid.NewGuid().ToString("N");
            var started = false;
            try
            {
                if (!await ValidateTargetAsync(serial, generation)) return false;
                Log.StartStep(stepId, opDesc);
                started = true;
                WriteOplog(serial, logPackage, $"{opDesc}: {string.Join(" ", args)}");
                var result = await Task.Run(() => isShell ? RunSerialShell(serial, args, 60) : AdbService.RunAdb(new[] { "-s", serial }.Concat(args), 60));
                var ok = CommandSucceeded(result.Item1, result.Item2);
                foreach (var line in result.Item2.Split('\n')) Log.AppendLog(line.TrimEnd('\r'));
                Log.FinishStep(stepId, ok, ok ? "" : L.Instance.Format("Pages/SoftwareManager_077", result.Item1));
                if (IsCurrent(generation, serial)) _ = RequestRefreshAsync(true);
                return ok;
            }
            catch (Exception ex)
            {
                if (started) Log.FinishStep(stepId, false, ex.Message);
                return false;
            }
            finally { _operationRunning = false; }
        }

        private async Task<bool> ConfirmRisky(string key, string title, string text)
        {
            if (!_active || _dialogOpen) return false;
            var settings = SettingsService.Instance;
            if (settings.GetBool(key, false)) return true;
            var panel = new StackPanel { Spacing = 12 };
            panel.Children.Add(new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap });
            var chk = new CheckBox { Content = L.Instance.Get("Pages/SoftwareManager_078") };
            panel.Children.Add(chk);
            var dlg = new ContentDialog { Title = title, Content = panel, PrimaryButtonText = L.Instance.Get("Pages/SoftwareManager_079"), CloseButtonText = L.Instance.Get("Pages/Scrcpy_044"), DefaultButton = ContentDialogButton.Close, XamlRoot = XamlRoot };
            _dialogOpen = true;
            try
            {
                var ok = await dlg.ShowAsync() == ContentDialogResult.Primary;
                if (ok && chk.IsChecked == true) settings.Set(key, "true");
                return ok;
            }
            finally { _dialogOpen = false; }
        }

        private async Task RiskyOperationAsync(string key, string title, string warning, Func<string, List<string>> arguments, bool isShell = true)
        {
            var serial = _serial;
            var generation = _generation;
            var pkg = TargetPkg();
            if (!IsCurrent(generation, serial)) { ShowDeviceWarning(); return; }
            if (pkg.Length == 0) { ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Get("Pages/SoftwareManager_080")); return; }
            try
            {
                if (!await ConfirmRisky("software_manager/risk/" + key, title,
                    L.Instance.Format("Pages/SoftwareManager_081", pkg, serial, warning))) return;
                await RunOpAsync(title, arguments(pkg), serial, generation, isShell, pkg);
            }
            catch (Exception ex) { if (_active) Log.AppendLog(ex.Message); }
        }

        private void OnFreeze(object sender, RoutedEventArgs e) => _ = RiskyOperationAsync("freeze", L.Instance.Get("Pages/SoftwareManager_082"), L.Instance.Get("Pages/SoftwareManager_083"), pkg => new() { "pm", "disable-user", "--user", "0", pkg });
        private void OnForceStop(object sender, RoutedEventArgs e) => _ = RiskyOperationAsync("force_stop", L.Instance.Get("Pages/SoftwareManager_084"), L.Instance.Get("Pages/SoftwareManager_085"), pkg => new() { "am", "force-stop", pkg });
        private void OnUninstall(object sender, RoutedEventArgs e) => _ = RiskyOperationAsync("uninstall", L.Instance.Get("Pages/SoftwareManager_086"), L.Instance.Get("Pages/SoftwareManager_087"), pkg => new() { "uninstall", pkg }, false);
        private void OnUninstallKeep(object sender, RoutedEventArgs e) => _ = RiskyOperationAsync("uninstall_keep", L.Instance.Get("Pages/SoftwareManager_088"), L.Instance.Get("Pages/SoftwareManager_089"), pkg => new() { "pm", "uninstall", "-k", "--user", "0", pkg });
        private void OnClearData(object sender, RoutedEventArgs e) => _ = RiskyOperationAsync("clear_data", L.Instance.Get("Pages/SoftwareManager_090"), L.Instance.Get("Pages/SoftwareManager_091"), pkg => new() { "pm", "clear", pkg });

        private async void OnUnfreeze(object sender, RoutedEventArgs e)
        {
            var serial = _serial;
            var generation = _generation;
            if (!IsCurrent(generation, serial)) { ShowDeviceWarning(); return; }
            if (_dialogOpen) return;
            var input = new TextBox { Text = TargetPkg(), Header = L.Instance.Get("Pages/SoftwareManager_092"), MinWidth = 240 };
            var dlg = new ContentDialog { Title = L.Instance.Get("Pages/SoftwareManager_027"), Content = input, PrimaryButtonText = L.Instance.Get("Pages/Dashboard_070"), CloseButtonText = L.Instance.Get("Pages/Scrcpy_044"), XamlRoot = XamlRoot };
            _dialogOpen = true;
            try
            {
                if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
                var pkg = input.Text?.Trim() ?? "";
                if (pkg.Length > 0) await RunOpAsync(L.Instance.Get("Pages/SoftwareManager_093"), new() { "pm", "enable", pkg }, serial, generation, package: pkg);
            }
            catch (Exception ex) { if (_active) Log.AppendLog(ex.Message); }
            finally { _dialogOpen = false; }
        }

        private void OnOpenPermissions(object sender, RoutedEventArgs e)
        {
            var pkg = TargetPkg();
            if (pkg.Length == 0) { ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Get("Pages/SoftwareManager_080")); return; }
            _ = RunOpAsync(L.Instance.Get("Pages/SoftwareManager_094"), new() { "am", "start", "-a", "android.settings.APPLICATION_DETAILS_SETTINGS", "-d", $"package:{pkg}" }, _serial, _generation);
        }

        private async void OnDisableActivity(object sender, RoutedEventArgs e)
        {
            var serial = _serial;
            var generation = _generation;
            var pkg = _currentPkg;
            var comp = NormalizeComponent(pkg, _currentActivity);
            var useRoot = ChkRootDisable.IsChecked == true;
            if (!IsCurrent(generation, serial)) { ShowDeviceWarning(); return; }
            if (pkg.Length == 0 || comp.Length == 0) { ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Get("Pages/SoftwareManager_095")); return; }
            var risk = L.Instance.Format("Pages/SoftwareManager_096", comp) + (useRoot ? L.Instance.Get("Pages/SoftwareManager_097") : L.Instance.Get("Pages/SoftwareManager_098")) + L.Instance.Get("Pages/SoftwareManager_099");
            try
            {
                if (!await ConfirmRisky(useRoot ? "software_manager/risk/disable_activity_root" : "software_manager/risk/disable_activity", L.Instance.Get("Pages/SoftwareManager_100"), risk)) return;
                var command = $"pm disable-user --user 0 {ShellQuote(comp)}";
                if (!useRoot) command += $" && am force-stop {ShellQuote(pkg)}";
                await RunOpAsync(useRoot ? L.Instance.Get("Pages/SoftwareManager_101") : L.Instance.Get("Pages/SoftwareManager_102"), new() { useRoot ? "su" : "sh", "-c", command }, serial, generation);
            }
            catch (Exception ex) { if (_active) Log.AppendLog(ex.Message); }
        }

        private static string NormalizeComponent(string pkg, string act)
        {
            var parts = act.Trim().Split('/', 2);
            if (parts.Length != 2 || parts[1].Length == 0) return "";
            var p = parts[0].Length > 0 ? parts[0] : pkg;
            return $"{p}/{(parts[1].StartsWith('.') ? p + parts[1] : parts[1])}";
        }

        private void OnInstallApk(object sender, RoutedEventArgs e) => _ = PickAndInstallAsync();
        private async Task PickAndInstallAsync()
        {
            if (_operationRunning) return;
            var serial = _serial;
            var generation = _generation;
            if (!IsCurrent(generation, serial)) { ShowDeviceWarning(); return; }
            var downgrade = ChkDowngrade.IsChecked == true;
            var reinstall = ChkReinstall.IsChecked == true || downgrade;
            _operationRunning = true;
            BtnInstall.IsEnabled = false;
            try
            {
                var picker = new FileOpenPicker();
                picker.FileTypeFilter.Add(".apk");
                WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin));
                var files = await picker.PickMultipleFilesAsync();
                if (files == null || files.Count == 0) return;
                var paths = files.Select(f => f.Path).ToList();
                InstallProgress.Visibility = Visibility.Visible;
                for (var i = 0; i < paths.Count; i++)
                {
                    if (!await ValidateTargetAsync(serial, generation)) break;
                    var path = paths[i];
                    var args = new List<string> { "-s", serial, "install" };
                    if (reinstall) args.Add("-r");
                    if (downgrade) args.Add("-d");
                    args.Add(path);
                    var stepId = Guid.NewGuid().ToString("N");
                    Log.StartStep(stepId, L.Instance.Format("Pages/SoftwareManager_103", i + 1, paths.Count));
                    WriteOplog(serial, "-", $"install{(reinstall ? " -r" : "")}{(downgrade ? " -d" : "")} {path}");
                    try
                    {
                        var result = await Task.Run(() => AdbService.RunAdb(args, 600));
                        var ok = CommandSucceeded(result.Code, result.Out) && result.Out.Contains("Success", StringComparison.OrdinalIgnoreCase);
                        foreach (var line in result.Out.Split('\n')) Log.AppendLog(line.TrimEnd('\r'));
                        Log.FinishStep(stepId, ok, ok ? "" : L.Instance.Get("Pages/SoftwareManager_104"));
                    }
                    catch (Exception ex) { Log.FinishStep(stepId, false, ex.Message); }
                }
                if (IsCurrent(generation, serial)) _ = RequestRefreshAsync(true);
            }
            catch (Exception ex) { if (_active) Log.AppendLog(L.Instance.Format("Pages/SoftwareManager_105", ex.Message)); }
            finally
            {
                _operationRunning = false;
                BtnInstall.IsEnabled = true;
                InstallProgress.Visibility = Visibility.Collapsed;
            }
        }

        private void OnDowngradeChanged(object sender, RoutedEventArgs e)
        {
            if (ChkDowngrade.IsChecked == true) ChkReinstall.IsChecked = true;
        }

        private async void OnPullApk(object sender, RoutedEventArgs e)
        {
            if (_operationRunning) return;
            var serial = _serial;
            var generation = _generation;
            var pkg = TargetPkg();
            if (!IsCurrent(generation, serial)) { ShowDeviceWarning(); return; }
            if (pkg.Length == 0) { ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Get("Pages/SoftwareManager_080")); return; }
            _operationRunning = true;
            var stepId = Guid.NewGuid().ToString("N");
            var started = false;
            try
            {
                var save = new FileSavePicker();
                save.FileTypeChoices.Add("APK", new List<string> { ".apk" });
                save.SuggestedFileName = $"{pkg}.apk";
                WinRT.Interop.InitializeWithWindow.Initialize(save, WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin));
                var file = await save.PickSaveFileAsync();
                if (file == null || !await ValidateTargetAsync(serial, generation)) return;
                var localPath = file.Path;
                Log.StartStep(stepId, L.Instance.Get("Pages/SoftwareManager_106"));
                started = true;
                var remote = await Task.Run(() => AdbService.AdbPmPath(serial, pkg, 6));
                if (!IsCurrent(generation, serial)) { Log.FinishStep(stepId, false, L.Instance.Get("Pages/SoftwareManager_107")); return; }
                if (remote.Length == 0) { Log.FinishStep(stepId, false, L.Instance.Format("Pages/SoftwareManager_108", pkg)); return; }
                WriteOplog(serial, pkg, $"pull-apk {localPath}");
                var result = await Task.Run(() => AdbService.RunAdb(new[] { "-s", serial, "pull", remote, localPath }, 600));
                var ok = CommandSucceeded(result.Code, result.Out);
                foreach (var line in result.Out.Split('\n')) Log.AppendLog(line.TrimEnd('\r'));
                Log.FinishStep(stepId, ok, ok ? "" : L.Instance.Get("Pages/SoftwareManager_109"));
            }
            catch (Exception ex)
            {
                if (started) Log.FinishStep(stepId, false, ex.Message);
                else if (_active) Log.AppendLog(L.Instance.Format("Pages/SoftwareManager_110", ex.Message));
            }
            finally { _operationRunning = false; }
        }

        private void OnSectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (ComboSection.SelectedIndex < 0) return;
            SecInstall.Visibility = ComboSection.SelectedIndex == 0 ? Visibility.Visible : Visibility.Collapsed;
            SecOps.Visibility = ComboSection.SelectedIndex == 1 ? Visibility.Visible : Visibility.Collapsed;
            SecComponent.Visibility = ComboSection.SelectedIndex == 2 ? Visibility.Visible : Visibility.Collapsed;
        }

        private void OnRefreshDisabled(object sender, RoutedEventArgs e) => _ = RefreshDisabledAsync();
        private async Task RefreshDisabledAsync()
        {
            var version = ++_disabledVersion;
            var pkg = TargetPkg();
            var serial = _serial;
            var generation = _generation;
            if (!IsCurrent(generation, serial)) { ShowDeviceWarning(); return; }
            if (pkg.Length == 0) { ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Get("Pages/SoftwareManager_080")); return; }
            try
            {
                var result = await Task.Run(() => RunSerialShell(serial, new[] { "dumpsys", "package", pkg }, 30));
                if (!IsCurrent(generation, serial) || version != _disabledVersion || TargetPkg() != pkg) return;
                if (!CommandSucceeded(result.Code, result.Out)) throw new InvalidOperationException(result.Out);
                var comps = new List<string>();
                var inBlock = false;
                foreach (var raw in result.Out.Split('\n'))
                {
                    var s = raw.Trim();
                    if (s.StartsWith("disabledComponents:")) { inBlock = true; continue; }
                    if (!inBlock) continue;
                    if (s.Length == 0 || s.EndsWith(':') || s.Contains('=')) break;
                    comps.Add(NormalizeComponent(pkg, s.Contains('/') ? s : pkg + "/" + s));
                }
                ListDisabled.ItemsSource = comps.Where(c => c.Length > 0).Distinct().OrderBy(c => c).ToList();
            }
            catch (Exception ex) { if (IsCurrent(generation, serial)) Log.AppendLog(L.Instance.Format("Pages/SoftwareManager_111", ex.Message)); }
        }

        private void OnEnableComponent(object sender, RoutedEventArgs e)
        {
            var pkg = TargetPkg();
            if (pkg.Length == 0) { ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Get("Pages/SoftwareManager_080")); return; }
            var comp = ListDisabled.SelectedItem as string;
            if (string.IsNullOrEmpty(comp)) comp = TxtComponent.Text?.Trim() ?? "";
            if (comp.Length == 0) { ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Get("Pages/SoftwareManager_112")); return; }
            _ = RunOpAsync(L.Instance.Get("Pages/SoftwareManager_043"), new() { "pm", "enable", comp }, _serial, _generation);
        }

        private static string OplogPath()
        {
            var dir = AppPaths.LogsDir;
            try { Directory.CreateDirectory(dir); } catch { }
            return Path.Combine(dir, "software_ops.txt");
        }
        private void WriteOplog(string serial, string pkg, string op)
        {
            try { File.AppendAllText(OplogPath(), $"{DateTime.Now:yyyy-MM-dd HH:mm:ss}\t{serial}\t{pkg}\t{op}\n"); }
            catch { }
        }
        private void OnOpenOplog(object sender, RoutedEventArgs e)
        {
            try
            {
                var p = OplogPath();
                if (!File.Exists(p)) File.WriteAllText(p, "");
                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(p) { UseShellExecute = true });
            }
            catch { }
        }
        private void OnClearLog(object sender, RoutedEventArgs e) => Log.ClearLog();
        private void ShowTip(string title, string message) => SetNotice(title, message, InfoBarSeverity.Informational);
    }
}
