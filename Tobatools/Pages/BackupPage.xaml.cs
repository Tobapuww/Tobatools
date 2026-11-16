using L = Tobatools.Services.LocalizationService;
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Tobatools.Services;
using Windows.Storage.Pickers;

namespace Tobatools.Pages
{
    public sealed partial class BackupPage : Page
    {
        private static readonly string[] RiskyNames = { "userdata", "metadata", "frp", "cache" };
        private List<string> _partitions = new();
        private List<string> _selected = new();
        private bool _scanning;
        private bool _backing;

        public BackupPage()
        {
            InitializeComponent();
            Loaded += OnLoaded;
        }

        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            if (TxtPath.Text.Length == 0) TxtPath.Text = AppPaths.DefaultDownloadsDir;
            Loaded -= OnLoaded;
        }

        private async void OnBrowse(object sender, RoutedEventArgs e)
        {
            try
            {
                var picker = new FolderPicker();
                picker.FileTypeFilter.Add("*");
                var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
                var folder = await picker.PickSingleFolderAsync();
                if (folder != null) TxtPath.Text = folder.Path;
            }
            catch { }
        }

        private async void OnScanPartitions(object sender, RoutedEventArgs e)
        {
            if (_scanning) return;
            var (mode, serial) = await Task.Run(() => AdbService.DetectConnectionMode());
            if (mode != "system" || string.IsNullOrEmpty(serial))
            {
                ShowTip(L.Instance.Get("Pages/Scrcpy_036"), L.Instance.Get("Pages/Backup_014"));
                return;
            }
            _scanning = true;
            BtnScan.IsEnabled = false;
            Log.ClearLog();
            Log.AppendLog(L.Instance.Get("Pages/Backup_015"));
            try
            {
                var (parts, err) = await Task.Run(() => ScanPartitions(serial));
                if (err.Length > 0)
                {
                    Log.AppendLog(L.Instance.Format("Pages/Backup_016", err), "#f53f3f");
                    ShowTip(L.Instance.Get("Pages/Backup_017"), err);
                    return;
                }
                Log.AppendLog(L.Instance.Format("Pages/Backup_018", parts.Count), "#00b42a");
                _partitions = parts;
                var selected = await ShowPartitionDialogAsync(parts);
                if (selected == null)
                {
                    Log.AppendLog(L.Instance.Get("Pages/Backup_019"), "#86909c");
                    return;
                }
                _selected = selected;
                Log.AppendLog(L.Instance.Format("Pages/Backup_020", _selected.Count), "#d4d4d4");
                if (_selected.Count > 0) ShowTip(L.Instance.Get("Pages/Backup_021"), L.Instance.Format("Pages/Backup_022", _selected.Count));
            }
            catch (Exception ex)
            {
                Log.AppendLog(L.Instance.Format("Pages/Backup_023", ex.Message), "#f53f3f");
            }
            finally
            {
                _scanning = false;
                BtnScan.IsEnabled = true;
            }
        }

        private static (List<string>, string) ScanPartitions(string serial)
        {
            try
            {
                // 1. 检查 Root
                var su = AdbService.AdbShellSerial(serial, "su -c id", 8) ?? "";
                if (!su.Contains("uid=0")) return (new List<string>(), L.Instance.Get("Pages/Backup_024"));

                // 2. 查找分区表
                var searchPaths = new[] { "/dev/block/bootdevice/by-name", "/dev/block/by-name", "/dev/block/platform/*/by-name" };
                foreach (var p in searchPaths)
                {
                    try
                    {
                        string path = p;
                        if (path.Contains('*'))
                        {
                            var basePath = path.Split('*')[0];
                            var lsBase = AdbService.AdbShellSerial(serial, $"ls -d {basePath}* 2>/dev/null", 5) ?? "";
                            if (lsBase.Length > 0 && !lsBase.Contains("No such"))
                            {
                                var first = lsBase.Split('\n').FirstOrDefault()?.Trim() ?? "";
                                if (first.Length > 0) path = first.TrimEnd('/') + "/by-name";
                            }
                        }
                        var res = AdbService.AdbShellSerial(serial, $"ls -1 {path}", 5) ?? "";
                        if (res.Length > 0 && !res.Contains("No such file") && !res.Contains("Permission denied"))
                        {
                            var found = res.Split('\n', ' ', '\t')
                                .Select(x => x.Trim())
                                .Where(x => x.Length > 0 && !x.StartsWith('/') && !x.StartsWith("ls:"))
                                .ToList();
                            if (found.Count > 0)
                            {
                                found.Sort(StringComparer.Ordinal);
                                return (found, "");
                            }
                        }
                    }
                    catch { }
                }
                return (new List<string>(), L.Instance.Get("Pages/Backup_025"));
            }
            catch (Exception e)
            {
                return (new List<string>(), L.Instance.Format("Pages/Backup_023", e.Message));
            }
        }

        private async Task<List<string>?> ShowPartitionDialogAsync(List<string> partitions)
        {
            var normal = partitions.Where(p => !RiskyNames.Contains(p.ToLower())).ToList();
            var risky = partitions.Where(p => RiskyNames.Contains(p.ToLower())).ToList();

            // 普通分区用流式换行面板承载；ItemsWrapGrid 只服务于 ItemsControl，
            // 直接向 Children 添加元素不会渲染，会导致绝大多数分区看不见。
            var normalPanel = new Tobatools.Controls.WrapPanel { Spacing = 12 };
            var normalChecks = new Dictionary<string, CheckBox>();
            foreach (var p in normal)
            {
                var chk = new CheckBox { Content = p, IsChecked = true };
                normalChecks[p] = chk;
                normalPanel.Children.Add(chk);
            }
            var riskyPanel = new StackPanel { Spacing = 4, Margin = new Thickness(16, 4, 16, 12) };
            var riskyChecks = new Dictionary<string, CheckBox>();
            foreach (var p in risky)
            {
                var chk = new CheckBox { Content = p, IsChecked = false };
                riskyChecks[p] = chk;
                riskyPanel.Children.Add(chk);
            }

            var tools = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
            var btnAll = new Button { Content = L.Instance.Get("Pages/Backup_026"), Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnInv = new Button { Content = L.Instance.Get("Pages/Backup_027"), Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnDef = new Button { Content = L.Instance.Get("Pages/Scrcpy_032"), Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            tools.Children.Add(btnAll);
            tools.Children.Add(btnInv);
            tools.Children.Add(btnDef);

            void All(bool v)
            {
                foreach (var c in normalChecks.Values) c.IsChecked = v;
                foreach (var c in riskyChecks.Values) c.IsChecked = v;
            }
            btnAll.Click += (s, a) => All(true);
            btnInv.Click += (s, a) =>
            {
                foreach (var c in normalChecks.Values) c.IsChecked = c.IsChecked != true;
                foreach (var c in riskyChecks.Values) c.IsChecked = c.IsChecked != true;
            };
            btnDef.Click += (s, a) =>
            {
                foreach (var c in normalChecks.Values) c.IsChecked = true;
                foreach (var c in riskyChecks.Values) c.IsChecked = false;
            };

            var scroll = new ScrollViewer { MaxHeight = 360 };
            var body = new StackPanel { Spacing = 8 };
            body.Children.Add(normalPanel);
            if (riskyChecks.Count > 0)
            {
                var riskyHeader = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
                riskyHeader.Children.Add(new FontIcon { Glyph = "\uE946", FontSize = 16 });
                riskyHeader.Children.Add(new TextBlock
                {
                    Text = L.Instance.Get("Pages/Backup_028"),
                    Style = (Style)Application.Current.Resources["CardSubtitleStyle"]
                });
                riskyHeader.Children.Add(new TextBlock
                {
                    Text = L.Instance.Get("Pages/Backup_029"),
                    Style = (Style)Application.Current.Resources["CaptionTextStyle"],
                    VerticalAlignment = VerticalAlignment.Center
                });
                body.Children.Add(riskyHeader);
                body.Children.Add(riskyPanel);
            }
            scroll.Content = body;

            var panel = new StackPanel { Spacing = 12 };
            panel.Children.Add(new TextBlock { Text = L.Instance.Get("Pages/Backup_030"), Style = (Style)Application.Current.Resources["CardTitleStyle"] });
            panel.Children.Add(tools);
            panel.Children.Add(scroll);

            var dlg = new ContentDialog
            {
                Title = L.Instance.Get("Pages/Backup_031"),
                Content = panel,
                PrimaryButtonText = L.Instance.Get("Pages/Dashboard_070"),
                CloseButtonText = L.Instance.Get("Pages/Scrcpy_044"),
                DefaultButton = ContentDialogButton.Primary,
                XamlRoot = XamlRoot
            };
            var r = await dlg.ShowAsync();
            if (r != ContentDialogResult.Primary) return null;

            var result = normalChecks.Concat(riskyChecks)
                .Where(kv => kv.Value.IsChecked == true)
                .Select(kv => kv.Key)
                .ToList();
            return result;
        }

        private async void OnStartBackup(object sender, RoutedEventArgs e)
        {
            if (_backing) return;
            if (_selected.Count == 0) { ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Get("Pages/Backup_032")); return; }
            var path = TxtPath.Text?.Trim() ?? "";
            if (path.Length == 0 || !Directory.Exists(path)) { ShowTip(L.Instance.Get("Pages/Scrcpy_036"), L.Instance.Get("Pages/Backup_033")); return; }
            var (mode, serial) = await Task.Run(() => AdbService.DetectConnectionMode());
            if (mode != "system" || string.IsNullOrEmpty(serial)) { ShowTip(L.Instance.Get("Pages/Scrcpy_036"), L.Instance.Get("Pages/Backup_034")); return; }

            if (_selected.Any(p => p.ToLower() == "userdata"))
            {
                var confirm = new ContentDialog
                {
                    Title = L.Instance.Get("Pages/Backup_035"),
                    Content = new TextBlock
                    {
                        Text = L.Instance.Get("Pages/Backup_036"),
                        TextWrapping = TextWrapping.Wrap
                    },
                    PrimaryButtonText = L.Instance.Get("Pages/SoftwareManager_079"),
                    CloseButtonText = L.Instance.Get("Pages/Scrcpy_044"),
                    DefaultButton = ContentDialogButton.Close,
                    XamlRoot = XamlRoot
                };
                var cr = await confirm.ShowAsync();
                if (cr != ContentDialogResult.Primary) return;
            }

            _backing = true;
            BtnStart.IsEnabled = false;
            Progress.Visibility = Visibility.Visible;
            Progress.Value = 0;
            Log.ClearLog();

            var useZip = ChkZip.IsChecked == true;
            var useScript = ChkScript.IsChecked == true;

            var (ok, msg) = await Task.Run(() => RunBackup(serial, path, _selected, useZip, useScript));

            BtnStart.IsEnabled = true;
            Progress.Visibility = Visibility.Collapsed;
            _backing = false;

            if (ok)
            {
                Log.AppendLog($"[SUCCESS] {msg}", "#00b42a", true);
                ShowTip(L.Instance.Get("Pages/Root_033"), L.Instance.Get("Pages/Backup_037"));
                try
                {
                    var folder = File.Exists(msg) ? Path.GetDirectoryName(msg) : msg;
                    if (!string.IsNullOrEmpty(folder))
                        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(folder) { UseShellExecute = true });
                }
                catch { }
            }
            else
            {
                Log.AppendLog($"[FAILED] {msg}", "#f53f3f", true);
                ShowTip(L.Instance.Get("Pages/Root_037"), msg);
            }
        }

        private (bool, string) RunBackup(string serial, string outDir, List<string> partitions, bool useZip, bool useScript)
        {
            try
            {
                if (partitions.Count == 0) return (false, L.Instance.Get("Pages/Backup_038"));

                // 初始化
                var stepInit = Guid.NewGuid().ToString("N");
                DispatcherQueue.TryEnqueue(() => Log.StartStep(stepInit, L.Instance.Format("Pages/Backup_039", partitions.Count)));
                var timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
                var model = "Unknown";
                try { model = AdbService.GetDeviceInfo(serial).Model?.Trim() ?? "Unknown"; } catch { }
                model = model.Replace(" ", "_");
                var backupName = $"Backup_{model}_{timestamp}";
                var localBackupDir = Path.Combine(outDir, backupName);
                Directory.CreateDirectory(localBackupDir);

                // 找分区路径
                var targetPath = "";
                var searchPaths = new[] { "/dev/block/bootdevice/by-name", "/dev/block/by-name", "/dev/block/platform/*/by-name" };
                foreach (var p in searchPaths)
                {
                    try
                    {
                        var path = p;
                        if (path.Contains('*'))
                        {
                            var basePath = path.Split('*')[0];
                            var lsBase = AdbService.AdbShellSerial(serial, $"ls -d {basePath}* 2>/dev/null", 5) ?? "";
                            if (lsBase.Length > 0 && !lsBase.Contains("No such"))
                            {
                                path = (lsBase.Split('\n').FirstOrDefault()?.Trim() ?? "").TrimEnd('/') + "/by-name";
                            }
                        }
                        var res = AdbService.AdbShellSerial(serial, $"ls {path}", 5) ?? "";
                        if (res.Length > 0 && !res.Contains("No such file")) { targetPath = path; break; }
                    }
                    catch { }
                }
                if (targetPath.Length == 0)
                {
                    DispatcherQueue.TryEnqueue(() => Log.FinishStep(stepInit, false, L.Instance.Get("Pages/Backup_040")));
                    return (false, L.Instance.Get("Pages/Backup_041"));
                }
                DispatcherQueue.TryEnqueue(() => Log.FinishStep(stepInit, true, ""));

                var total = partitions.Count;
                var successParts = new List<string>();

                for (int idx = 0; idx < total; idx++)
                {
                    var part = partitions[idx];
                    var stepId = Guid.NewGuid().ToString("N");
                    DispatcherQueue.TryEnqueue(() =>
                    {
                        Progress.Value = (int)((idx + 1.0) / total * 100);
                        Log.StartStep(stepId, L.Instance.Format("Pages/Backup_042", idx + 1, total, part));
                    });

                    var remoteTmp = $"/sdcard/Download/tmp_backup_{part}.img";
                    try { AdbService.AdbShellSerial(serial, "mkdir -p /sdcard/Download", 10); } catch { }

                    // DD
                    var ddCmd = $"su -c 'dd if={targetPath}/{part} of={remoteTmp}'";
                    var ddOk = true;
                    try { AdbService.AdbShellSerial(serial, ddCmd, 3600); }
                    catch (Exception ex)
                    {
                        ddOk = false;
                        DispatcherQueue.TryEnqueue(() => Log.FinishStep(stepId, false, L.Instance.Format("Pages/Backup_043", ex.Message)));
                        continue;
                    }
                    if (!ddOk) continue;

                    // Pull
                    var localImg = Path.Combine(localBackupDir, $"{part}.img");
                    var (okPull, pullMsg) = AdbService.AdbPullFileSerial(serial, remoteTmp, localImg, 3600);
                    if (okPull && File.Exists(localImg))
                    {
                        successParts.Add(part);
                        DispatcherQueue.TryEnqueue(() => Log.FinishStep(stepId, true, ""));
                    }
                    else
                    {
                        DispatcherQueue.TryEnqueue(() => Log.FinishStep(stepId, false, L.Instance.Format("Pages/Backup_044", pullMsg)));
                    }

                    // Cleanup
                    try { AdbService.AdbShellSerial(serial, $"rm {remoteTmp}", 10); } catch { }
                }

                // 生成脚本
                if (useScript && successParts.Count > 0)
                {
                    var stepScript = Guid.NewGuid().ToString("N");
                    DispatcherQueue.TryEnqueue(() => Log.StartStep(stepScript, L.Instance.Get("Pages/Backup_045")));
                    try
                    {
                        var bat = new List<string> { "@echo off", "echo Waiting for device in fastboot...", "fastboot devices", "pause" };
                        foreach (var p in successParts) { bat.Add($"echo Flashing {p}..."); bat.Add($"fastboot flash {p} {p}.img"); }
                        bat.Add("echo Done!"); bat.Add("pause");
                        File.WriteAllLines(Path.Combine(localBackupDir, "flash_all.bat"), bat);

                        var sh = new List<string> { "#!/bin/bash", "echo 'Waiting for device...'", "fastboot devices" };
                        foreach (var p in successParts) { sh.Add($"echo 'Flashing {p}...'"); sh.Add($"fastboot flash {p} {p}.img"); }
                        sh.Add("echo 'Done!'");
                        File.WriteAllLines(Path.Combine(localBackupDir, "flash_all.sh"), sh);

                        DispatcherQueue.TryEnqueue(() => Log.FinishStep(stepScript, true, ""));
                    }
                    catch (Exception ex)
                    {
                        DispatcherQueue.TryEnqueue(() => Log.FinishStep(stepScript, false, ex.Message));
                    }
                }

                var finalPath = localBackupDir;

                // ZIP
                if (useZip && successParts.Count > 0)
                {
                    var stepZip = Guid.NewGuid().ToString("N");
                    DispatcherQueue.TryEnqueue(() => Log.StartStep(stepZip, L.Instance.Get("Pages/Backup_046")));
                    var zipPath = Path.Combine(outDir, $"{backupName}.zip");
                    var used7z = false;
                    var p7z = Path.Combine(AppPaths.BinDir, "7z.exe");
                    if (File.Exists(p7z))
                    {
                        try
                        {
                            var result = ProcessRunner.Run(p7z, new[] { "a", zipPath, localBackupDir }, null, 1800000);
                            used7z = result.Success;
                        }
                        catch (Exception ex)
                        {
                            DispatcherQueue.TryEnqueue(() => Log.AppendLog(L.Instance.Format("Pages/Backup_047", ex.Message)));
                        }
                    }
                    if (!used7z)
                    {
                        try
                        {
                            ZipFile.CreateFromDirectory(localBackupDir, zipPath, CompressionLevel.Optimal, false);
                            used7z = true;
                        }
                        catch (Exception ex)
                        {
                            DispatcherQueue.TryEnqueue(() => Log.FinishStep(stepZip, false, ex.Message));
                        }
                    }
                    if (used7z)
                    {
                        try { Directory.Delete(localBackupDir, true); } catch { }
                        finalPath = zipPath;
                        DispatcherQueue.TryEnqueue(() => Log.FinishStep(stepZip, true, ""));
                    }
                }

                DispatcherQueue.TryEnqueue(() => Log.AppendLog(L.Instance.Format("Pages/Backup_048", finalPath)));
                return (true, finalPath);
            }
            catch (Exception ex)
            {
                return (false, ex.Message);
            }
        }

        private void OnClearLog(object sender, RoutedEventArgs e) => Log.ClearLog();

        private void ShowTip(string title, string message)
        {
            var dlg = new ContentDialog
            {
                Title = title,
                Content = new TextBlock { Text = message, TextWrapping = TextWrapping.Wrap },
                CloseButtonText = L.Instance.Get("Pages/Dashboard_070"),
                XamlRoot = XamlRoot
            };
            _ = dlg.ShowAsync();
        }
    }
}
