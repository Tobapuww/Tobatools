using System;
using System.IO;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Tobatools.Controls;
using Tobatools.Logic.ImageFactory;
using Windows.Storage.Pickers;

namespace Tobatools.Dialogs
{
    internal static class ImgDlg
    {
        public static Grid PickRow(string label, string placeholder, out TextBox box, string btnText, Action onBtn)
        {
            var g = new Grid { ColumnSpacing = 8 };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            var lbl = new TextBlock { Text = label, Style = (Style)Application.Current.Resources["CardSubtitleStyle"], VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap, MaxWidth = 108 };
            box = new TextBox { PlaceholderText = placeholder, Style = (Style)Application.Current.Resources["RoundedTextBoxStyle"], MinWidth = 0 };
            AutomationProperties.SetName(box, label);
            var btn = new Button { Content = btnText, Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            btn.Click += (s, e) => onBtn();
            Grid.SetColumn(lbl, 0); Grid.SetColumn(box, 1); Grid.SetColumn(btn, 2);
            g.Children.Add(lbl); g.Children.Add(box); g.Children.Add(btn);
            return g;
        }

        /// <summary>
        /// 创建统一的标签控件（解包 / 打包 等）。
        ///
        /// 原来的 TabWidthMode=Compact 会把标签压到 34~40px，
        /// 中文字符因此被裁切，未选中时几乎只剩一片空白。
        /// 这里改为按内容自适应（SizeToContent），并给标签文字显式前景色，
        /// 保证未选中状态下也清晰可读。
        /// </summary>
        public static TabView MakeTabs(double maxHeight)
        {
            return new TabView
            {
                IsAddTabButtonVisible = false,
                // 按内容自适应宽度，避免中文标签被压缩后无法辨认。
                TabWidthMode = TabViewWidthMode.SizeToContent,
                MaxHeight = maxHeight,
            };
        }

        /// <summary>创建标签页项，并统一标签文字样式。</summary>
        public static TabViewItem MakeTab(string header, UIElement content)
        {
            var text = new TextBlock
            {
                Text = header,
                // 标签宽度随内容走，再给足内边距，中文就不会被切掉。
                Padding = new Thickness(6, 0, 6, 0),
                VerticalAlignment = VerticalAlignment.Center,
                Foreground = (Microsoft.UI.Xaml.Media.Brush)Application.Current.Resources["TextFillColorPrimaryBrush"],
            };
            var item = new TabViewItem
            {
                IsClosable = false,
                Header = text,
                Content = content,
            };
            AutomationProperties.SetName(item, header);
            return item;
        }

        public static async Task<string> PickFolder()
        {
            var fp = new FolderPicker();
            fp.FileTypeFilter.Add("*");
            var h = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
            WinRT.Interop.InitializeWithWindow.Initialize(fp, h);
            var f = await fp.PickSingleFolderAsync();
            return f?.Path ?? "";
        }

        public static async Task<string> PickFile(params string[] filters)
        {
            var fp = new FileOpenPicker();
            foreach (var f in filters) fp.FileTypeFilter.Add(f);
            var h = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
            WinRT.Interop.InitializeWithWindow.Initialize(fp, h);
            var f2 = await fp.PickSingleFileAsync();
            return f2?.Path ?? "";
        }

        public static (Button run, Button cancel, LogView log, StackPanel body, ContentControl bodyHost, StackPanel root) Shell()
        {
            // 页头、卡片和外边距由二级导航宿主统一提供。
            var cp = new StackPanel { Spacing = 12 };
            var act = new WrapPanel { Spacing = 10, HorizontalAlignment = HorizontalAlignment.Stretch };
            var btnRun = new Button { Content = "开始处理", Style = (Style)Application.Current.Resources["AccentButtonStyle"] };
            var btnCancel = new Button { Content = "取消", Style = (Style)Application.Current.Resources["DefaultButtonStyle"], IsEnabled = false };
            act.Children.Add(btnRun); act.Children.Add(btnCancel);
            cp.Children.Add(act);
            var log = new LogView { Height = 220 };
            cp.Children.Add(new TextBlock { Text = "日志输出", Style = (Style)Application.Current.Resources["CardTitleStyle"] });
            cp.Children.Add(log);
            var body = new StackPanel { Spacing = 12 };
            // 使用 Control 宿主统一禁用鼠标和键盘输入，StackPanel 本身没有 IsEnabled。
            var bodyHost = new ContentControl
            {
                Content = body,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                IsTabStop = false,
                Padding = new Thickness(0)
            };
            cp.Children.Insert(0, bodyHost);
            return (btnRun, btnCancel, log, body, bodyHost, cp);
        }

        /// <summary>在 UI 线程捕获输入，再后台执行；离页与取消均等待实际任务结束。</summary>
        public static void WireOperation<T>(StackPanel root, ContentControl bodyHost, Button run, Button cancel,
            LogView log, Func<T> createTool, Func<T, Func<bool>> capture) where T : BaseTool
        {
            var dispatcher = App.Instance?.MainWin?.DispatcherQueue
                ?? throw new InvalidOperationException("主窗口尚未初始化");
            T? tool = null;
            var busy = false;
            var departed = false;
            var cancellationRequested = false;

            void UpdateUi(Action update)
            {
                if (dispatcher.HasThreadAccess) update();
                else dispatcher.TryEnqueue(() => update());
            }

            void RequestStop()
            {
                if (!busy) return;
                cancellationRequested = true;
                tool?.StopRequest();
                cancel.IsEnabled = false;
            }

            root.Loaded += (s, e) =>
            {
                departed = false;
                run.IsEnabled = !busy;
            };
            root.Unloaded += (s, e) =>
            {
                departed = true;
                RequestStop();
            };
            cancel.Click += (s, e) =>
            {
                RequestStop();
                log.AppendLog("已请求取消，正在等待当前任务结束…");
            };
            run.Click += async (s, e) =>
            {
                if (busy || departed) return;
                busy = true;
                cancellationRequested = false;
                run.IsEnabled = false;
                cancel.IsEnabled = true;
                bodyHost.IsEnabled = false;
                log.ClearLog();
                var result = "失败";
                try
                {
                    tool = createTool();
                    tool.Log = text => UpdateUi(() => { if (!departed) log.AppendLog(text); });
                    tool.StepStart = (id, text) => UpdateUi(() => { if (!departed) log.StartStep(id, text); });
                    tool.StepFinish = (id, success, detail) => UpdateUi(() => { if (!departed) log.FinishStep(id, success, detail); });
                    // capture 必须在 await 前调用，返回的委托只能访问普通值和工具实例。
                    var work = capture(tool);
                    var ok = await Task.Run(work);
                    result = ok ? "完成" : "失败";
                }
                catch (OperationCanceledException) { cancellationRequested = true; }
                catch (Exception ex) { result = $"失败：{ex.Message}"; }
                finally
                {
                    UpdateUi(() =>
                    {
                        if (!departed) log.AppendLog(cancellationRequested ? "已取消" : result);
                        tool = null;
                        busy = false;
                        bodyHost.IsEnabled = true;
                        run.IsEnabled = !departed;
                        cancel.IsEnabled = false;
                    });
                }
            };
        }

        public static void Wire(Grid g, int col, Action onBtn)
        {
            if (g.Children[col] is Button b) b.Click += (s, e) => onBtn();
        }
    }

    /// <summary>Super 动态分区解/打包。</summary>
    public static class SuperToolDialog
    {
        public static FrameworkElement Build()
        {
            var (btnRun, btnCancel, log, body, bodyHost, root) = ImgDlg.Shell();
            var tab = ImgDlg.MakeTabs(420);
            // 解包
            var unpack = new StackPanel { Spacing = 12, Padding = new Thickness(0, 12, 0, 0) };
            var rowImg = ImgDlg.PickRow("super.img", "选择要解包的 super.img", out var edtImg, "浏览", () => { });
            unpack.Children.Add(rowImg);
            var rowProj = ImgDlg.PickRow("工程目录", "选择镜像工厂工程目录", out var edtProj1, "浏览", () => { });
            unpack.Children.Add(rowProj);
            // 打包
            var pack = new StackPanel { Spacing = 12, Padding = new Thickness(0, 12, 0, 0) };
            var rowPackProj = ImgDlg.PickRow("工程目录", "选择镜像工厂工程目录", out var edtProj2, "浏览", () => { });
            pack.Children.Add(rowPackProj);
            var rowImages = ImgDlg.PickRow("分区镜像目录", "包含各分区 .img 的目录", out var edtImages, "浏览", () => { });
            pack.Children.Add(rowImages);
            var rowOut = ImgDlg.PickRow("输出名称", "默认 super.img", out var edtOut, "", () => { });
            HideBtn(rowOut); pack.Children.Add(rowOut);
            var opts = new WrapPanel { Spacing = 12 };
            var chkSparse = new CheckBox { Content = "生成 sparse 镜像", IsChecked = true, VerticalAlignment = VerticalAlignment.Center };
            var chkReadonly = new CheckBox { Content = "只读分区属性", VerticalAlignment = VerticalAlignment.Center };
            opts.Children.Add(chkSparse); opts.Children.Add(chkReadonly);
            pack.Children.Add(opts);

            tab.TabItems.Add(ImgDlg.MakeTab("解包", unpack));
            tab.TabItems.Add(ImgDlg.MakeTab("打包", pack));
            body.Children.Add(tab);

            // pickers
            ImgDlg.Wire(rowImg, 2, async () => { var p = await ImgDlg.PickFile(".img", "*"); if (p.Length > 0) edtImg.Text = p; });
            ImgDlg.Wire(rowProj, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtProj1.Text = p; });
            ImgDlg.Wire(rowPackProj, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtProj2.Text = p; });
            ImgDlg.Wire(rowImages, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtImages.Text = p; });

            ImgDlg.WireOperation(root, bodyHost, btnRun, btnCancel, log, () => new SuperImageTool(), tool =>
            {
                var isPack = tab.SelectedIndex == 1;
                var img = edtImg.Text.Trim();
                var proj = edtProj1.Text.Trim();
                var proj2 = edtProj2.Text.Trim();
                var images = edtImages.Text.Trim();
                var output = edtOut.Text.Trim();
                var sparse = chkSparse.IsChecked == true;
                var readOnly = chkReadonly.IsChecked == true;
                return () =>
                {
                    if (!isPack)
                    {
                        if (!File.Exists(img)) throw new InvalidOperationException("请选择有效的 super.img");
                        if (proj.Length == 0) throw new InvalidOperationException("请选择工程目录");
                        return tool.Unpack(img, proj);
                    }
                    if (proj2.Length == 0) throw new InvalidOperationException("请选择工程目录");
                    if (!Directory.Exists(images)) throw new InvalidOperationException("请选择有效的分区镜像目录");
                    return tool.Pack(proj2, images, output, sparse: sparse, readonly_: readOnly);
                };
            });
            return root;
        }

        private static void HideBtn(Grid g)
        {
            if (g.Children.Count >= 3 && g.Children[2] is Button b) b.Visibility = Visibility.Collapsed;
        }
    }

    /// <summary>DTBO 解/打包。</summary>
    public static class DtboToolDialog
    {
        public static FrameworkElement Build()
        {
            var (btnRun, btnCancel, log, body, bodyHost, root) = ImgDlg.Shell();
            var tab = ImgDlg.MakeTabs(420);
            var unpack = new StackPanel { Spacing = 12, Padding = new Thickness(0, 12, 0, 0) };
            var rowImg = ImgDlg.PickRow("dtbo.img", "选择要解包的 dtbo.img", out var edtImg, "浏览", () => { });
            unpack.Children.Add(rowImg);
            var rowProj1 = ImgDlg.PickRow("工程目录", "选择镜像工厂工程目录", out var edtProj1, "浏览", () => { });
            unpack.Children.Add(rowProj1);
            var chkDecomp = new CheckBox { Content = "解压压缩的 DT 条目", IsChecked = true };
            unpack.Children.Add(chkDecomp);

            var pack = new StackPanel { Spacing = 12, Padding = new Thickness(0, 12, 0, 0) };
            var rowProj2 = ImgDlg.PickRow("工程目录", "选择镜像工厂工程目录", out var edtProj2, "浏览", () => { });
            pack.Children.Add(rowProj2);
            var rowDts = ImgDlg.PickRow("dts 目录", "包含 .dts 文件的目录", out var edtDts, "浏览", () => { });
            pack.Children.Add(rowDts);
            var rowOut = ImgDlg.PickRow("输出名称", "默认 dtbo.img", out var edtOut, "", () => { });
            HideBtn(rowOut); pack.Children.Add(rowOut);
            var rowPage = ImgDlg.PickRow("page_size", "默认 4096", out var edtPage, "", () => { });
            HideBtn(rowPage); pack.Children.Add(rowPage);

            tab.TabItems.Add(ImgDlg.MakeTab("解包", unpack));
            tab.TabItems.Add(ImgDlg.MakeTab("打包", pack));
            body.Children.Add(tab);

            ImgDlg.Wire(rowImg, 2, async () => { var p = await ImgDlg.PickFile(".img", "*"); if (p.Length > 0) edtImg.Text = p; });
            ImgDlg.Wire(rowProj1, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtProj1.Text = p; });
            ImgDlg.Wire(rowProj2, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtProj2.Text = p; });
            ImgDlg.Wire(rowDts, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtDts.Text = p; });

            ImgDlg.WireOperation(root, bodyHost, btnRun, btnCancel, log, () => new DtboTool(), tool =>
            {
                var isPack = tab.SelectedIndex == 1;
                var img = edtImg.Text.Trim();
                var proj = edtProj1.Text.Trim();
                var proj2 = edtProj2.Text.Trim();
                var dts = edtDts.Text.Trim();
                var output = edtOut.Text.Trim();
                var pageText = edtPage.Text.Trim();
                var decompress = chkDecomp.IsChecked == true;
                return () =>
                {
                    if (!isPack)
                    {
                        if (!File.Exists(img)) throw new InvalidOperationException("请选择有效的 dtbo.img");
                        if (proj.Length == 0) throw new InvalidOperationException("请选择工程目录");
                        return tool.Unpack(img, proj, decompress);
                    }
                    if (proj2.Length == 0) throw new InvalidOperationException("请选择工程目录");
                    if (!Directory.Exists(dts)) throw new InvalidOperationException("请选择有效的 dts 目录");
                    int page = 4096;
                    if (pageText.Length > 0 && !int.TryParse(pageText, out page))
                        throw new InvalidOperationException("page_size 应为整数");
                    return tool.Pack(proj2, dts, output, page);
                };
            });
            return root;
        }

        private static void HideBtn(Grid g)
        {
            if (g.Children.Count >= 3 && g.Children[2] is Button b) b.Visibility = Visibility.Collapsed;
        }
    }

    /// <summary>文件系统 / 分区镜像（ext4 / erofs）解打包。</summary>
    public static class PartitionFsToolDialog
    {
        public static FrameworkElement Build()
        {
            var (btnRun, btnCancel, log, body, bodyHost, root) = ImgDlg.Shell();
            var tab = ImgDlg.MakeTabs(460);
            // 解包
            var unpack = new StackPanel { Spacing = 12, Padding = new Thickness(0, 12, 0, 0) };
            var rowImg = ImgDlg.PickRow("分区镜像", "选择分区镜像（ext4/erofs）", out var edtImg, "浏览", () => { });
            unpack.Children.Add(rowImg);

            // 识别结果 + 解包模式：与 Python 一致，默认 auto 由镜像头自动判定。
            var rowDetect = new Grid { ColumnSpacing = 8 };
            rowDetect.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            rowDetect.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            rowDetect.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            rowDetect.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            var lblDetectTitle = new TextBlock
            {
                Text = "识别结果",
                Style = (Style)Application.Current.Resources["CardSubtitleStyle"],
                VerticalAlignment = VerticalAlignment.Center
            };
            rowDetect.Children.Add(lblDetectTitle);
            var lblDetect = new TextBlock
            {
                Text = "unknown",
                Style = (Style)Application.Current.Resources["CaptionTextStyle"],
                VerticalAlignment = VerticalAlignment.Center
            };
            Grid.SetColumn(lblDetect, 1); rowDetect.Children.Add(lblDetect);
            var lblModeTitle = new TextBlock
            {
                Text = "解包模式",
                Style = (Style)Application.Current.Resources["CardSubtitleStyle"],
                VerticalAlignment = VerticalAlignment.Center
            };
            Grid.SetColumn(lblModeTitle, 2); rowDetect.Children.Add(lblModeTitle);
            var unpackCombo = new ComboBox { Style = (Style)Application.Current.Resources["RoundedComboBoxStyle"], MinWidth = 110 };
            foreach (var f in new[] { "auto", "ext4", "erofs" }) unpackCombo.Items.Add(f);
            unpackCombo.SelectedIndex = 0;
            Grid.SetColumn(unpackCombo, 3); rowDetect.Children.Add(unpackCombo);
            unpack.Children.Add(rowDetect);

            var rowProj1 = ImgDlg.PickRow("工程目录", "选择镜像工厂工程目录", out var edtProj1, "浏览", () => { });
            unpack.Children.Add(rowProj1);
            var chkCfg = new CheckBox { Content = "生成 config（fs_config / file_contexts）", IsChecked = true };
            unpack.Children.Add(chkCfg);
            // 打包
            var pack = new StackPanel { Spacing = 12, Padding = new Thickness(0, 12, 0, 0) };
            var rowProj2 = ImgDlg.PickRow("工程目录", "选择镜像工厂工程目录", out var edtProj2, "浏览", () => { });
            pack.Children.Add(rowProj2);
            var rowFolder = ImgDlg.PickRow("内容目录", "要打包的目录", out var edtFolder, "浏览", () => { });
            pack.Children.Add(rowFolder);
            var rowOut = ImgDlg.PickRow("输出名称", "默认 <名称>.img", out var edtOut, "", () => { });
            HideBtn(rowOut); pack.Children.Add(rowOut);
            var fsRow = new WrapPanel { Spacing = 12 };
            var fsCombo = new ComboBox { Header = "打包文件系统", Style = (Style)Application.Current.Resources["RoundedComboBoxStyle"], MinWidth = 140 };
            // auto：存在 config/<name>_fs_config 时按 ext4，否则 erofs（与 Python 一致）。
            foreach (var f in new[] { "auto", "ext4", "erofs" }) fsCombo.Items.Add(f);
            fsCombo.SelectedIndex = 0;
            fsRow.Children.Add(fsCombo);
            var compCombo = new ComboBox { Header = "EROFS 压缩", Style = (Style)Application.Current.Resources["RoundedComboBoxStyle"], MinWidth = 140 };
            foreach (var c in new[] { "lz4hc", "lz4", "zstd" }) compCombo.Items.Add(c);
            compCombo.SelectedIndex = 0;
            fsRow.Children.Add(compCombo);
            pack.Children.Add(fsRow);
            var chkGrow = new CheckBox { Content = "允许增长（允许输出镜像大于原镜像）" };
            pack.Children.Add(chkGrow);

            tab.TabItems.Add(ImgDlg.MakeTab("解包", unpack));
            tab.TabItems.Add(ImgDlg.MakeTab("打包", pack));
            body.Children.Add(tab);

            ImgDlg.Wire(rowImg, 2, async () => { var p = await ImgDlg.PickFile(".img", "*"); if (p.Length > 0) edtImg.Text = p; });
            ImgDlg.Wire(rowProj1, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtProj1.Text = p; });
            ImgDlg.Wire(rowProj2, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtProj2.Text = p; });
            ImgDlg.Wire(rowFolder, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtFolder.Text = p; });

            // 解包工具由「解包模式」决定，打包工具由「打包文件系统」决定，两者互不影响。
            ImgDlg.WireOperation<BaseTool>(root, bodyHost, btnRun, btnCancel, log, () =>
                {
                    var isPack = tab.SelectedIndex == 1;
                    if (!isPack)
                    {
                        var rawMode = (string?)unpackCombo.SelectedItem ?? "auto";
                        var text = edtImg.Text.Trim();
                        var mode = rawMode == "auto" ? FsDetect.Detect(text) : rawMode;
                        return mode == "erofs" ? new ErofsTool() : new Ext4ImageTool();
                    }
                    var packMode = (string?)fsCombo.SelectedItem ?? "auto";
                    if (packMode == "auto")
                    {
                        var folderName = Path.GetFileName(edtFolder.Text.Trim().TrimEnd('\\', '/'));
                        var dir = edtProj2.Text.Trim();
                        var hasCfg = dir.Length > 0 && folderName.Length > 0 &&
                                     File.Exists(Path.Combine(dir, "config", folderName + "_fs_config"));
                        packMode = hasCfg ? "ext4" : "erofs";
                    }
                    return packMode == "erofs" ? new ErofsTool() : new Ext4ImageTool();
                }, tool =>
            {
                var isPack = tab.SelectedIndex == 1;
                var img = edtImg.Text.Trim();
                var proj = edtProj1.Text.Trim();
                var proj2 = edtProj2.Text.Trim();
                var folder = edtFolder.Text.Trim();
                var output = edtOut.Text.Trim();
                var compress = (string?)compCombo.SelectedItem ?? "lz4hc";
                var generateConfigs = chkCfg.IsChecked == true;
                var allowGrow = chkGrow.IsChecked == true;
                return () =>
                {
                    if (!isPack)
                    {
                        if (!File.Exists(img)) throw new InvalidOperationException("请选择有效的分区镜像");
                        if (proj.Length == 0) throw new InvalidOperationException("请选择工程目录");
                        var rawMode = unpackCombo.SelectedItem as string ?? "auto";
                        var detected = FsDetect.Detect(img);
                        var fs = rawMode == "auto" ? detected : rawMode;
                        log.AppendLog($"识别: {detected}");
                        if (fs is not ("ext4" or "erofs"))
                            throw new InvalidOperationException($"无法识别文件系统类型: {fs}");
                        log.AppendLog($"解包模式: {fs}");
                        if (tool is ErofsTool erofs) return erofs.Unpack(img, proj);
                        return ((Ext4ImageTool)tool).Extract(img, proj, generateConfigs);
                    }
                    if (proj2.Length == 0) throw new InvalidOperationException("请选择工程目录");
                    if (!Directory.Exists(folder)) throw new InvalidOperationException("请选择有效的内容目录");
                    if (tool is ErofsTool erofsPack)
                        return erofsPack.Pack(proj2, folder, output, compress, allowGrow);
                    return ((Ext4ImageTool)tool).Pack(proj2, folder, output, allowGrow: allowGrow);
                };
            });

            // 输入镜像后即时刷新「识别结果」。
            edtImg.TextChanged += (s, e) =>
            {
                var p = edtImg.Text.Trim();
                lblDetect.Text = p.Length > 0 && File.Exists(p) ? FsDetect.Detect(p) : "unknown";
            };
            return root;
        }

        private static void HideBtn(Grid g)
        {
            if (g.Children.Count >= 3 && g.Children[2] is Button b) b.Visibility = Visibility.Collapsed;
        }
    }

    /// <summary>Boot 镜像解/打包。</summary>
    public static class BootToolDialog
    {
        public static FrameworkElement Build()
        {
            var (btnRun, btnCancel, log, body, bodyHost, root) = ImgDlg.Shell();
            var tab = ImgDlg.MakeTabs(420);
            var unpack = new StackPanel { Spacing = 12, Padding = new Thickness(0, 12, 0, 0) };
            var rowImg = ImgDlg.PickRow("boot 镜像", "选择要解包的 boot 镜像", out var edtImg, "浏览", () => { });
            unpack.Children.Add(rowImg);
            var rowProj1 = ImgDlg.PickRow("工程目录", "选择镜像工厂工程目录", out var edtProj1, "浏览", () => { });
            unpack.Children.Add(rowProj1);
            var pack = new StackPanel { Spacing = 12, Padding = new Thickness(0, 12, 0, 0) };
            var rowProj2 = ImgDlg.PickRow("工程目录", "选择镜像工厂工程目录", out var edtProj2, "浏览", () => { });
            pack.Children.Add(rowProj2);
            var rowFolder = ImgDlg.PickRow("解包目录", "解包输出目录（含 ramdisk 等）", out var edtFolder, "浏览", () => { });
            pack.Children.Add(rowFolder);
            var rowOrig = ImgDlg.PickRow("原始 boot 镜像", "留空自动从 meta 读取", out var edtOrig, "浏览", () => { });
            pack.Children.Add(rowOrig);
            var rowOut = ImgDlg.PickRow("输出名称", "默认 <名称>.img", out var edtOut, "", () => { });
            HideBtn(rowOut); pack.Children.Add(rowOut);

            // Magisk 修补：对应 Python 的「Magisk 修补」卡片。
            var patch = new StackPanel { Spacing = 12, Padding = new Thickness(0, 12, 0, 0) };
            var rowProj3 = ImgDlg.PickRow("工程目录", "选择镜像工厂工程目录", out var edtProj3, "浏览", () => { });
            patch.Children.Add(rowProj3);
            var rowPatchBoot = ImgDlg.PickRow("Boot 镜像", "选择要修补的 boot.img / init_boot.img", out var edtPatchBoot, "浏览", () => { });
            patch.Children.Add(rowPatchBoot);
            var rowApk = ImgDlg.PickRow("Magisk APK", "选择 magisk.apk", out var edtApk, "浏览", () => { });
            patch.Children.Add(rowApk);
            var rowPatchOut = ImgDlg.PickRow("输出文件名", "例如 magisk_patched-boot.img（留空自动）", out var edtPatchOut, "", () => { });
            HideBtn(rowPatchOut); patch.Children.Add(rowPatchOut);
            patch.Children.Add(new TextBlock
            {
                Text = "使用 Magisk 的 boot_patch.sh 在本地修补 boot 镜像，输出到工程 out 目录。",
                Style = (Style)Application.Current.Resources["CaptionTextStyle"],
                TextWrapping = TextWrapping.Wrap
            });

            tab.TabItems.Add(ImgDlg.MakeTab("解包", unpack));
            tab.TabItems.Add(ImgDlg.MakeTab("打包", pack));
            tab.TabItems.Add(ImgDlg.MakeTab("Magisk 修补", patch));
            body.Children.Add(tab);

            ImgDlg.Wire(rowImg, 2, async () => { var p = await ImgDlg.PickFile(".img", "*"); if (p.Length > 0) edtImg.Text = p; });
            ImgDlg.Wire(rowProj1, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtProj1.Text = p; });
            ImgDlg.Wire(rowProj2, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtProj2.Text = p; });
            ImgDlg.Wire(rowFolder, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtFolder.Text = p; });
            ImgDlg.Wire(rowOrig, 2, async () => { var p = await ImgDlg.PickFile(".img", "*"); if (p.Length > 0) edtOrig.Text = p; });
            ImgDlg.Wire(rowProj3, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtProj3.Text = p; });
            ImgDlg.Wire(rowPatchBoot, 2, async () => { var p = await ImgDlg.PickFile(".img", "*"); if (p.Length > 0) edtPatchBoot.Text = p; });
            ImgDlg.Wire(rowApk, 2, async () => { var p = await ImgDlg.PickFile(".apk", "*"); if (p.Length > 0) edtApk.Text = p; });

            ImgDlg.WireOperation(root, bodyHost, btnRun, btnCancel, log, () => new BootTool(), tool =>
            {
                var index = tab.SelectedIndex;
                var img = edtImg.Text.Trim();
                var proj = edtProj1.Text.Trim();
                var proj2 = edtProj2.Text.Trim();
                var folder = edtFolder.Text.Trim();
                var output = edtOut.Text.Trim();
                var original = edtOrig.Text.Trim();
                var proj3 = edtProj3.Text.Trim();
                var patchBoot = edtPatchBoot.Text.Trim();
                var apk = edtApk.Text.Trim();
                var patchOut = edtPatchOut.Text.Trim();
                return () =>
                {
                    if (index == 2)
                    {
                        if (proj3.Length == 0) throw new InvalidOperationException("请选择工程目录");
                        if (!File.Exists(patchBoot)) throw new InvalidOperationException("请选择有效的 Boot 镜像");
                        if (!File.Exists(apk)) throw new InvalidOperationException("请选择有效的 magisk.apk");
                        return tool.PatchWithMagisk(proj3, patchBoot, apk, patchOut);
                    }
                    if (index == 0)
                    {
                        if (!File.Exists(img)) throw new InvalidOperationException("请选择有效的 boot 镜像");
                        if (proj.Length == 0) throw new InvalidOperationException("请选择工程目录");
                        return tool.Unpack(img, proj);
                    }
                    if (proj2.Length == 0) throw new InvalidOperationException("请选择工程目录");
                    if (!Directory.Exists(folder)) throw new InvalidOperationException("请选择有效的解包目录");
                    return tool.Pack(proj2, folder, output, original);
                };
            });
            return root;
        }

        private static void HideBtn(Grid g)
        {
            if (g.Children.Count >= 3 && g.Children[2] is Button b) b.Visibility = Visibility.Collapsed;
        }
    }

    /// <summary>OTA 增量包 DAT/BR 转换。</summary>
    public static class DatBrToolDialog
    {
        public static FrameworkElement Build()
        {
            var (btnRun, btnCancel, log, body, bodyHost, root) = ImgDlg.Shell();
            var tab = ImgDlg.MakeTabs(420);
            var unpack = new StackPanel { Spacing = 12, Padding = new Thickness(0, 12, 0, 0) };
            var rowTl = ImgDlg.PickRow("transfer.list", "选择 OTA 增量包的 transfer.list", out var edtTl, "浏览", () => { });
            unpack.Children.Add(rowTl);
            var rowDat = ImgDlg.PickRow("new.dat(.br)", "选择 new.dat 或 new.dat.br", out var edtDat, "浏览", () => { });
            unpack.Children.Add(rowDat);
            var rowProj1 = ImgDlg.PickRow("工程目录", "输出转换后的 .img", out var edtProj1, "浏览", () => { });
            unpack.Children.Add(rowProj1);

            var pack = new StackPanel { Spacing = 12, Padding = new Thickness(0, 12, 0, 0) };
            var rowImg = ImgDlg.PickRow("分区镜像", "选择要打包的 .img", out var edtImg, "浏览", () => { });
            pack.Children.Add(rowImg);
            var rowProj2 = ImgDlg.PickRow("工程目录", "输出 .transfer.list / .new.dat(.br)", out var edtProj2, "浏览", () => { });
            pack.Children.Add(rowProj2);
            var chkBr = new CheckBox { Content = "生成 .br（brotli 压缩）", IsChecked = true };
            pack.Children.Add(chkBr);

            tab.TabItems.Add(ImgDlg.MakeTab("DAT/BR -> IMG", unpack));
            tab.TabItems.Add(ImgDlg.MakeTab("IMG -> DAT/BR", pack));
            body.Children.Add(tab);

            ImgDlg.Wire(rowTl, 2, async () => { var p = await ImgDlg.PickFile(".list", ".txt", "*"); if (p.Length > 0) edtTl.Text = p; });
            ImgDlg.Wire(rowDat, 2, async () => { var p = await ImgDlg.PickFile(".dat", ".br", "*"); if (p.Length > 0) edtDat.Text = p; });
            ImgDlg.Wire(rowProj1, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtProj1.Text = p; });
            ImgDlg.Wire(rowImg, 2, async () => { var p = await ImgDlg.PickFile(".img", "*"); if (p.Length > 0) edtImg.Text = p; });
            ImgDlg.Wire(rowProj2, 2, async () => { var p = await ImgDlg.PickFolder(); if (p.Length > 0) edtProj2.Text = p; });

            ImgDlg.WireOperation(root, bodyHost, btnRun, btnCancel, log, () => new DatBrTool(), tool =>
            {
                var isPack = tab.SelectedIndex == 1;
                var tl = edtTl.Text.Trim();
                var dat = edtDat.Text.Trim();
                var proj = edtProj1.Text.Trim();
                var img = edtImg.Text.Trim();
                var proj2 = edtProj2.Text.Trim();
                var compressBr = chkBr.IsChecked == true;
                return () =>
                {
                    if (!isPack)
                    {
                        if (!File.Exists(tl)) throw new InvalidOperationException("请选择有效的 transfer.list");
                        if (!File.Exists(dat)) throw new InvalidOperationException("请选择有效的 new.dat / new.dat.br");
                        if (proj.Length == 0) throw new InvalidOperationException("请选择工程目录");
                        return tool.Unpack(proj, tl, dat);
                    }
                    if (!File.Exists(img)) throw new InvalidOperationException("请选择有效的分区镜像");
                    if (proj2.Length == 0) throw new InvalidOperationException("请选择工程目录");
                    return tool.Pack(proj2, img, compressBr: compressBr);
                };
            });
            return root;
        }
    }
}
