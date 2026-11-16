using System;
using System.IO;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Tobatools.Controls;
using Tobatools.Logic;
using Windows.Storage.Pickers;

namespace Tobatools.Dialogs
{
    /// <summary>Payload.bin 处理：在线或本地提取，支持全量和指定分区。</summary>
    public static class PayloadExtractDialog
    {
        public static async Task Show()
        {
            var card = Dlg.Card();
            var cp = Dlg.CardContent();
            card.Child = cp;

            var row1 = Dlg.InputRow("payload.bin", "本地路径或 http(s) 在线 URL", out var edtPayload, "浏览", () => { });
            cp.Children.Add(row1);
            var row2 = Dlg.InputRow("输出目录", "选择解包输出目录", out var edtOut, "浏览", () => { });
            cp.Children.Add(row2);
            var row3 = Dlg.InputRow("分区过滤", "留空 = 全部；多个用逗号分隔", out var edtParts, "", () => { });
            // 分区行无按钮：隐藏第三列
            if (row3.Children.Count >= 3 && row3.Children[2] is Button b3) b3.Visibility = Visibility.Collapsed;
            cp.Children.Add(row3);

            var act = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10, HorizontalAlignment = HorizontalAlignment.Right };
            var btnRun = new Button { Content = "开始处理", Style = (Style)Application.Current.Resources["AccentButtonStyle"] };
            var btnCancel = new Button { Content = "取消", Style = (Style)Application.Current.Resources["DefaultButtonStyle"], IsEnabled = false };
            act.Children.Add(btnRun); act.Children.Add(btnCancel);
            cp.Children.Add(act);

            var log = new LogView { Height = 260 };
            cp.Children.Add(new TextBlock { Text = "日志输出", Style = (Style)Application.Current.Resources["CardTitleStyle"] });
            cp.Children.Add(log);

            var dlg = Dlg.Build("Payload.bin 处理", "在线或本地提取 payload.bin，支持全量和指定分区", card);

            var payloadPicker = new FileOpenPicker { FileTypeFilter = { ".bin", "*" } };
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
            WinRT.Interop.InitializeWithWindow.Initialize(payloadPicker, hwnd);
            WireButton(row1, 2, async () =>
            {
                var f = await payloadPicker.PickSingleFileAsync();
                if (f != null) edtPayload.Text = f.Path;
            });
            WireButton(row2, 2, async () =>
            {
                var fp = new FolderPicker();
                fp.FileTypeFilter.Add("*");
                var h2 = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(fp, h2);
                var f = await fp.PickSingleFolderAsync();
                if (f != null) edtOut.Text = f.Path;
            });

            PayloadExtractor? worker = null;
            btnRun.Click += async (s, e) =>
            {
                var src = edtPayload.Text.Trim();
                var outDir = edtOut.Text.Trim();
                var parts = edtParts.Text.Trim();
                if (src.Length == 0) { Dlg.Tip("提示", "请输入 payload.bin 路径或在线 URL"); return; }
                if (outDir.Length == 0) { Dlg.Tip("提示", "请输入输出目录"); return; }

                log.ClearLog();
                log.AppendLog("开始处理...");
                log.AppendLog("源: " + src);
                log.AppendLog("输出: " + outDir);
                if (parts.Length > 0) log.AppendLog("分区: " + parts);
                log.AppendLog("");
                btnRun.IsEnabled = false;
                btnCancel.IsEnabled = true;

                worker = new PayloadExtractor
                {
                    Log = s => log.AppendLog(s),
                    StepStart = (id, t) => log.StartStep(id, t),
                    StepFinish = (id, ok, d) => log.FinishStep(id, ok, d)
                };
                bool ok;
                string msg;
                try
                {
                    ok = await Task.Run(() => worker.Extract(src, outDir, parts));
                    msg = ok ? "完成" : "失败";
                }
                catch (Exception ex)
                {
                    ok = false;
                    msg = ex.Message;
                }
                log.AppendLog("");
                log.AppendLog(ok ? "完成" : "失败");
                if (msg.Length > 0) log.AppendLog(msg);
                if (ok) Dlg.Tip("完成", "Payload 处理完成");
                else Dlg.Tip("失败", "Payload 处理失败，请检查日志输出");
                btnRun.IsEnabled = true;
                btnCancel.IsEnabled = false;
                worker = null;
            };

            btnCancel.Click += (s, e) =>
            {
                worker?.Stop();
                log.AppendLog("");
                log.AppendLog("用户取消操作");
                btnRun.IsEnabled = true;
                btnCancel.IsEnabled = false;
            };

            await dlg.ShowAsync();
        }

        private static void WireButton(Grid g, int col, Action onBtn)
        {
            if (g.Children[col] is Button b) b.Click += (s, e) => onBtn();
        }
    }

    /// <summary>OFP 处理：解密并提取 .ofp 固件（自动识别/高通/MTK）。</summary>
    public static class OfpDialog
    {
        public static async Task Show()
        {
            var card = Dlg.Card();
            var cp = Dlg.CardContent();
            card.Child = cp;

            var row1 = Dlg.InputRow("OFP 文件", "选择 .ofp 文件", out var edtOfp, "浏览", () => { });
            cp.Children.Add(row1);
            var row2 = Dlg.InputRow("输出目录", "选择解密输出目录", out var edtOut, "浏览", () => { });
            cp.Children.Add(row2);

            var row3 = new Grid { ColumnSpacing = 8 };
            row3.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            row3.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row3.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            row3.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            row3.Children.Add(new TextBlock { Text = "模式", Style = (Style)Application.Current.Resources["CardSubtitleStyle"], VerticalAlignment = VerticalAlignment.Center });
            var combo = new ComboBox { Style = (Style)Application.Current.Resources["RoundedComboBoxStyle"] };
            foreach (var m in new[] { "自动（先高通后MTK）", "高通（QC）", "联发科（MTK）" }) combo.Items.Add(m);
            combo.SelectedIndex = 0;
            Grid.SetColumn(combo, 1); row3.Children.Add(combo);
            var btnRun = new Button { Content = "开始处理", Style = (Style)Application.Current.Resources["AccentButtonStyle"] };
            Grid.SetColumn(btnRun, 2); row3.Children.Add(btnRun);
            var btnCancel = new Button { Content = "取消", Style = (Style)Application.Current.Resources["DefaultButtonStyle"], IsEnabled = false };
            Grid.SetColumn(btnCancel, 3); row3.Children.Add(btnCancel);
            cp.Children.Add(row3);

            var log = new LogView { Height = 260 };
            cp.Children.Add(new TextBlock { Text = "日志输出", Style = (Style)Application.Current.Resources["CardTitleStyle"] });
            cp.Children.Add(log);

            var dlg = Dlg.Build("OFP 处理", "解密并提取 OPPO/realme 的 .ofp 固件（自动识别/高通/MTK）", card);

            var ofpPicker = new FileOpenPicker { FileTypeFilter = { ".ofp", "*" } };
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
            WinRT.Interop.InitializeWithWindow.Initialize(ofpPicker, hwnd);
            WireButton(row1, 2, async () =>
            {
                var f = await ofpPicker.PickSingleFileAsync();
                if (f != null) edtOfp.Text = f.Path;
            });
            WireButton(row2, 2, async () =>
            {
                var fp = new FolderPicker();
                fp.FileTypeFilter.Add("*");
                var h2 = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(fp, h2);
                var f = await fp.PickSingleFolderAsync();
                if (f != null) edtOut.Text = f.Path;
            });

            OfpProcessor? worker = null;
            btnRun.Click += async (s, e) =>
            {
                var ofp = edtOfp.Text.Trim();
                var outDir = edtOut.Text.Trim();
                var mode = combo.SelectedIndex == 1 ? "qc" : (combo.SelectedIndex == 2 ? "mtk" : "auto");
                if (!File.Exists(ofp)) { Dlg.Tip("提示", "请选择有效的 .ofp 文件"); return; }
                if (outDir.Length == 0) { Dlg.Tip("提示", "请选择输出目录"); return; }
                Directory.CreateDirectory(outDir);

                log.ClearLog();
                log.AppendLog("开始处理...");
                log.AppendLog("源: " + ofp);
                log.AppendLog("输出: " + outDir);
                log.AppendLog("模式: " + mode);
                log.AppendLog("");
                btnRun.IsEnabled = false;
                btnCancel.IsEnabled = true;

                worker = new OfpProcessor
                {
                    Log = s => log.AppendLog(s),
                    StepStart = (id, t) => log.StartStep(id, t),
                    StepFinish = (id, ok, d) => log.FinishStep(id, ok, d)
                };
                bool ok;
                string msg;
                try
                {
                    ok = await Task.Run(() => worker.Extract(ofp, outDir, mode));
                    msg = ok ? "完成" : "失败";
                }
                catch (Exception ex)
                {
                    ok = false;
                    msg = ex.Message;
                }
                log.AppendLog("");
                log.AppendLog(ok ? "完成" : "失败");
                if (msg.Length > 0) log.AppendLog(msg);
                if (ok) Dlg.Tip("完成", "OFP 处理完成");
                else Dlg.Tip("失败", "OFP 处理失败，请检查日志输出");
                btnRun.IsEnabled = true;
                btnCancel.IsEnabled = false;
                worker = null;
            };
            btnCancel.Click += (s, e) =>
            {
                worker?.Stop();
                log.AppendLog("");
                log.AppendLog("用户取消操作");
                btnRun.IsEnabled = true;
                btnCancel.IsEnabled = false;
            };

            await dlg.ShowAsync();
        }

        private static void WireButton(Grid g, int col, Action onBtn)
        {
            if (g.Children[col] is Button b) b.Click += (s, e) => onBtn();
        }
    }
}
