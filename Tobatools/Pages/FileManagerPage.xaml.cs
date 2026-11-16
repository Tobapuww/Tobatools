using L = Tobatools.Services.LocalizationService;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Tobatools.Models;
using Tobatools.Services;
using Windows.Storage.Pickers;

namespace Tobatools.Pages
{
    public sealed partial class FileManagerPage : Page
    {
        private readonly ObservableCollection<FileItem> _items = new();
        private string _cwd = "/storage/emulated/0";
        private string _clipboardMode = ""; // copy | cut
        private string _clipboardPath = "";
        private bool _busy;

        public FileManagerPage()
        {
            InitializeComponent();
            ListFiles.ItemsSource = _items;
            Loaded += OnLoaded;
        }

        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            if (_items.Count == 0) _ = RefreshAsync();
            Loaded -= OnLoaded;
        }

        private static string DefaultSerial()
        {
            var devices = AdbService.ListDevices();
            return devices.Count == 1 ? devices[0] : "";
        }

        private async Task RefreshAsync()
        {
            if (_busy) return;
            _busy = true;
            var path = TxtPath.Text?.Trim() ?? "";
            if (path.Length == 0) path = "/storage/emulated/0";
            if (path != "/" && path.EndsWith("/")) path = path.TrimEnd('/');
            _cwd = path;
            try
            {
                var (items, err) = await Task.Run(() => AdbService.ListDir(path));
                _items.Clear();
                if (err.Length > 0)
                {
                    SetStatus(L.Instance.Format("Pages/FileManager_020", err));
                    return;
                }
                foreach (var it in items)
                {
                    var full = path == "/" ? "/" + it.Name : path + "/" + it.Name;
                    _items.Add(new FileItem
                    {
                        Name = it.Name,
                        Size = it.Type == "dir" ? "-" : FmtSize(it.Size),
                        Type = it.Type,
                        FullPath = full
                    });
                }
                SetStatus(L.Instance.Format("Pages/FileManager_021", _items.Count));
            }
            catch (Exception ex)
            {
                SetStatus(L.Instance.Format("Pages/FileManager_020", ex.Message));
            }
            finally
            {
                _busy = false;
            }
        }

        private static string FmtSize(string val)
        {
            if (!long.TryParse(val?.Trim(), out var s) || s < 0) return "-";
            var units = new[] { "KB", "MB", "GB", "TB" };
            double size = s / 1024.0;
            var idx = 0;
            while (size >= 1024.0 && idx < units.Length - 1) { size /= 1024.0; idx++; }
            return size >= 10 ? $"{size:F0} {units[idx]}" : $"{size:F1} {units[idx]}";
        }

        private void OnGo(object sender, RoutedEventArgs e) => _ = RefreshAsync();
        private void OnRefresh(object sender, RoutedEventArgs e) => _ = RefreshAsync();

        private void OnGoUp(object sender, RoutedEventArgs e)
        {
            var p = TxtPath.Text?.Trim() ?? "";
            if (p.Length == 0 || p == "/") return;
            // 设备路径是 POSIX 风格，不能用 System.IO.Path：Windows 上它会按 '\'
            // 处理，把 /storage/emulated/0 变成 \storage\emulated，下发到设备必然失败。
            var trimmed = p.TrimEnd('/');
            if (trimmed.Length == 0) return;                     // p 原本就是 "///" 之类
            var idx = trimmed.LastIndexOf('/');
            var parent = idx < 0 ? "/" : trimmed[..idx];
            if (parent.Length == 0) parent = "/";
            TxtPath.Text = parent;
            _ = RefreshAsync();
        }

        private void OnListDoubleTapped(object sender, DoubleTappedRoutedEventArgs e)
        {
            if ((e.OriginalSource as FrameworkElement)?.DataContext is FileItem item && item.IsDir)
            {
                TxtPath.Text = item.FullPath;
                _ = RefreshAsync();
            }
        }

        private void OnItemClick(object sender, ItemClickEventArgs e)
        {
            // 单击仅选中（IsItemClickEnabled 用于右键定位）
        }

        private FileItem? SelectedItem()
        {
            if (ListFiles.SelectedItem is FileItem f) return f;
            return null;
        }

        // ---------------- 传输 ----------------

        private void SetProgressVisible(bool visible)
        {
            ProgressCard.Visibility = visible ? Visibility.Visible : Visibility.Collapsed;
        }

        private void SetStatus(string text)
        {
            TxtStatus.Text = text;
            if (text.Length > 0) SetProgressVisible(true);
        }

        private async void OnPullSelected(object sender, RoutedEventArgs e)
        {
            var item = SelectedItem();
            if (item == null) { SetStatus(L.Instance.Get("Pages/FileManager_022")); return; }
            if (item.IsDir) { SetStatus(L.Instance.Get("Pages/FileManager_023")); return; }

            var save = new FileSavePicker();
            save.FileTypeChoices.Add(L.Instance.Get("Pages/FileManager_024"), new List<string> { ".bin", ".zip", ".tar", ".img", ".apk", "*" });
            save.SuggestedFileName = item.Name;
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
            WinRT.Interop.InitializeWithWindow.Initialize(save, hwnd);
            var file = await save.PickSaveFileAsync();
            if (file == null) return;

            await RunTransferAsync("pull", item.FullPath, file.Path, item.FullPath);
        }

        private async Task RunTransferAsync(string mode, string src, string dst, string probePath)
        {
            SetProgressVisible(true);
            ProgressBar.IsIndeterminate = true;
            TxtProgress.Text = L.Instance.Get("Pages/FileManager_025");
            var total = await Task.Run(() => ProbeTotal(probePath));
            try
            {
                bool ok;
                string msg;
                if (mode == "pull") (ok, msg) = await Task.Run(() => AdbService.PullPath(src, dst));
                else if (mode == "push") (ok, msg) = await Task.Run(() => AdbService.PushPath(src, dst));
                else if (mode == "copy") (ok, msg) = await Task.Run(() => AdbService.CopyPath(src, dst));
                else if (mode == "move") (ok, msg) = await Task.Run(() => AdbService.MovePath(src, dst));
                else if (mode == "rename") (ok, msg) = await Task.Run(() => AdbService.RenamePath(src, dst));
                else { ok = false; msg = L.Instance.Get("Pages/FileManager_026"); }

                ProgressBar.IsIndeterminate = false;
                if (ok)
                {
                    ProgressBar.Value = 100;
                    TxtProgress.Text = "100%";
                    SetStatus(L.Instance.Get("Pages/FileManager_027"));
                    if (_clipboardMode == "cut") { _clipboardMode = ""; _clipboardPath = ""; }
                    _ = RefreshAsync();
                }
                else
                {
                    ProgressBar.Value = 0;
                    SetStatus(msg.Length > 0 ? msg : L.Instance.Get("Pages/FileManager_028"));
                }
            }
            catch (Exception ex)
            {
                ProgressBar.IsIndeterminate = false;
                SetStatus(ex.Message);
            }
            finally
            {
                _ = HideProgressSoonAsync();
            }
        }

        private async Task HideProgressSoonAsync()
        {
            await Task.Delay(1500);
            SetProgressVisible(false);
        }

        private long ProbeTotal(string remote)
        {
            try
            {
                var serial = DefaultSerial();
                if (serial.Length > 0)
                {
                    var ls = AdbService.AdbShellSerial(serial, new[] { "ls", "-ld", remote }, 6) ?? "";
                    var outDu = AdbService.AdbShellSerial(serial, new[] { "du", "-s", remote }, 20) ?? "";
                    var first = outDu.Trim().Split(' ', '\t').FirstOrDefault() ?? "0";
                    if (long.TryParse(first, out var kb) && kb > 0) return kb * 1024;
                    _ = ls;
                }
            }
            catch { }
            return 0;
        }

        // ---------------- 右键菜单 ----------------

        private FileItem? ContextItem()
        {
            if (ListFiles.SelectedItem is FileItem f) return f;
            return null;
        }

        private async void OnMenuOpen(object sender, RoutedEventArgs e)
        {
            var item = ContextItem();
            if (item is { IsDir: true })
            {
                TxtPath.Text = item.FullPath;
                await RefreshAsync();
            }
        }

        private async void OnMenuExport(object sender, RoutedEventArgs e)
        {
            var item = ContextItem();
            if (item == null) return;
            if (item.IsDir)
            {
                var folder = new FolderPicker();
                folder.FileTypeFilter.Add("*");
                var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(folder, hwnd);
                var f = await folder.PickSingleFolderAsync();
                if (f == null) return;
                var dest = System.IO.Path.Combine(f.Path, item.Name);
                await RunTransferAsync("pull", item.FullPath, dest, item.FullPath);
            }
            else
            {
                var save = new FileSavePicker();
                save.FileTypeChoices.Add(L.Instance.Get("Pages/FileManager_024"), new List<string> { ".bin", ".zip", ".tar", ".img", ".apk", "*" });
                save.SuggestedFileName = item.Name;
                var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(save, hwnd);
                var file = await save.PickSaveFileAsync();
                if (file == null) return;
                await RunTransferAsync("pull", item.FullPath, file.Path, item.FullPath);
            }
        }

        private void OnMenuCopy(object sender, RoutedEventArgs e)
        {
            var item = ContextItem();
            if (item == null) return;
            _clipboardMode = "copy";
            _clipboardPath = item.FullPath;
            SetStatus(L.Instance.Get("Pages/FileManager_029"));
        }

        private void OnMenuCut(object sender, RoutedEventArgs e)
        {
            var item = ContextItem();
            if (item == null) return;
            _clipboardMode = "cut";
            _clipboardPath = item.FullPath;
            SetStatus(L.Instance.Get("Pages/FileManager_030"));
        }

        private void OnMenuPaste(object sender, RoutedEventArgs e)
        {
            if (_clipboardMode.Length == 0 || _clipboardPath.Length == 0) { SetStatus(L.Instance.Get("Pages/FileManager_031")); return; }
            _ = RunTransferAsync(_clipboardMode == "copy" ? "copy" : "move", _clipboardPath, _cwd, _clipboardPath);
        }

        private async void OnMenuRename(object sender, RoutedEventArgs e)
        {
            var item = ContextItem();
            if (item == null) return;
            var input = new TextBox { Text = item.Name, MinWidth = 300, Margin = new Thickness(0, 12, 0, 0) };
            var dlg = new ContentDialog
            {
                Title = L.Instance.Get("Pages/FileManager_006"),
                Content = new StackPanel { Children = { new TextBlock { Text = L.Instance.Get("Pages/FileManager_032") }, input } },
                PrimaryButtonText = L.Instance.Get("Pages/Dashboard_070"),
                CloseButtonText = L.Instance.Get("Pages/Scrcpy_044"),
                XamlRoot = XamlRoot
            };
            var r = await dlg.ShowAsync();
            if (r != ContentDialogResult.Primary) return;
            var newName = input.Text?.Trim() ?? "";
            if (newName.Length == 0 || newName == item.Name) return;
            await RunTransferAsync("rename", item.FullPath, newName, item.FullPath);
        }

        private async void OnMenuDelete(object sender, RoutedEventArgs e)
        {
            var item = ContextItem();
            if (item == null) return;
            // Python file_manager_tab.py 明确不弹确认框，直接执行删除。
            var (ok, msg) = await Task.Run(() => AdbService.DeletePath(item.FullPath));
            if (ok) { SetStatus(L.Instance.Get("Pages/FileManager_035")); _ = RefreshAsync(); }
            else SetStatus(msg.Length > 0 ? msg : L.Instance.Get("Pages/FileManager_036"));
        }

        private async void OnMenuProps(object sender, RoutedEventArgs e)
        {
            var item = ContextItem();
            if (item == null) return;
            var serial = DefaultSerial();
            var stat = "";
            var ls = "";
            var du = "";
            try
            {
                if (serial.Length > 0)
                {
                    // 与 Python stat_path 一致：优先 stat -c，取不到再退回 ls -ld / du -s。
                    // 用字符串重载直接交给 `adb shell`，避免数组重载的 ShQuote 二次转义
                    // 把 `sh -c` 里的引号破坏掉（Android 17 上 toybox stat 会因此调不通）。
                    var statCmd =
                        $"stat -c '%F|%s|%a|%U|%G|%y' '{item.FullPath}' 2>/dev/null" +
                        $" || toybox stat -c '%F|%s|%a|%U|%G|%y' '{item.FullPath}' 2>/dev/null";
                    stat = (AdbService.AdbShellSerial(serial, statCmd, 8) ?? "").Trim();
                    ls = (AdbService.AdbShellSerial(serial, new[] { "ls", "-ld", item.FullPath }, 6) ?? "").Trim();
                    du = (AdbService.AdbShellSerial(serial, new[] { "du", "-s", item.FullPath }, 10) ?? "").Trim();
                }
            }
            catch { }

            var ftype = item.IsDir ? L.Instance.Get("Pages/FileManager_040") : L.Instance.Get("Pages/FileManager_024");
            var sizeDisp = item.Size;
            var perm = "-";
            var user = "-";
            var group = "-";
            var mtime = "-";
            if (stat.Length > 0 && stat.Contains('|'))
            {
                var parts = stat.Split('|', 6);
                if (parts.Length == 6)
                {
                    ftype = parts[0].Trim();
                    sizeDisp = FmtSize(parts[1].Trim());
                    perm = parts[2].Trim();
                    user = parts[3].Trim();
                    group = parts[4].Trim();
                    mtime = parts[5].Trim();
                }
            }

            var lines = new List<string>
            {
                L.Instance.Format("Pages/FileManager_037", item.Name),
                L.Instance.Format("Pages/FileManager_038", item.FullPath),
                L.Instance.Format("Pages/FileManager_039", ftype),
                L.Instance.Format("Pages/FileManager_041", sizeDisp),
                $"{L.Instance.Get("Pages/FileManager_063")}{perm}",
                $"{L.Instance.Get("Pages/FileManager_064")}{user}:{group}",
                $"{L.Instance.Get("Pages/FileManager_065")}{mtime}",
            };
            if (ls.Length > 0) lines.Add($"ls -ld：{ls}");
            if (du.Length > 0) lines.Add($"du -s：{du}");
            var dlg = new ContentDialog
            {
                Title = L.Instance.Get("Pages/FileManager_008"),
                Content = new ScrollViewer { MaxHeight = 360, Content = new TextBlock { Text = string.Join("\n", lines), TextWrapping = TextWrapping.Wrap } },
                CloseButtonText = L.Instance.Get("Pages/FileManager_042"),
                XamlRoot = XamlRoot
            };
            _ = dlg.ShowAsync();
        }

        private async void OnMenuImportFiles(object sender, RoutedEventArgs e)
        {
            var picker = new FileOpenPicker();
            picker.FileTypeFilter.Add("*");
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
            WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
            var files = await picker.PickMultipleFilesAsync();
            if (files == null || files.Count == 0) return;
            foreach (var f in files)
            {
                var total = new FileInfo(f.Path).Length;
                await RunTransferAsync("push", f.Path, _cwd, "");
                _ = total;
            }
        }

        private async void OnMenuImportFolder(object sender, RoutedEventArgs e)
        {
            var folder = new FolderPicker();
            folder.FileTypeFilter.Add("*");
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
            WinRT.Interop.InitializeWithWindow.Initialize(folder, hwnd);
            var f = await folder.PickSingleFolderAsync();
            if (f == null) return;
            await RunTransferAsync("push", f.Path, _cwd, "");
        }

        private void OnMenuRefresh(object sender, RoutedEventArgs e) => _ = RefreshAsync();
    }
}
