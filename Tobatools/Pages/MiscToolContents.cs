using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Tobatools.Controls;
using Tobatools.Dialogs;
using Tobatools.Logic;
using Tobatools.Logic.ImageFactory;
using Tobatools.Services;
using Windows.Storage.Pickers;
using Windows.UI;

namespace Tobatools.Pages
{
    /// <summary>杂项工具定义。</summary>
    public sealed class ToolDef
    {
        public string Id;
        public string Title;
        public string Subtitle;
        public string Glyph;
        public Func<FrameworkElement> Build;

        public ToolDef(string id, string title, string subtitle, string glyph, Func<FrameworkElement> build)
        {
            Id = id; Title = title; Subtitle = subtitle; Glyph = glyph; Build = build;
        }
    }

    /// <summary>杂项工具箱工具注册表：id 到定义。</summary>
    public static class MiscToolContents
    {
        public static readonly List<ToolDef> All = new()
        {
            new("partitionflash", "单分区刷入", "选择镜像并刷入指定分区（可选槽位 / 模式）", "\uE8B7", PartitionFlashContent.Build),
            new("payload", "Payload.bin 处理", "在线或本地提取 payload.bin，支持全量和指定分区", "\uE8A5", PayloadContent.Build),
            new("ofp", "OFP 处理", "解密并提取 .ofp 固件内容", "\uE8A5", OfpContent.Build),

            new("unbrick", "启动异常修复", "移除异常模块配置，恢复因模块冲突导致的无法启动", "\uE7FB", UnbrickContent.Build),
            new("modules", "Magisk模块管理", "管理已安装模块：列表/启用/禁用/备份/移除/安装/批量安装（需 Root 环境）", "\uE7F4", ModuleContent.Build),
            new("adbterminal", "ADB 开发终端", "打开原生终端窗口运行 ADB，适用于开发与维护操作", "\uE756", AdbTerminalContent.Build),
            new("runscript", "运行开发维护脚本", "选择电脑上的 .sh 脚本，推送到手机并在终端交互执行", "\uE756", RunScriptContent.Build),
            new("configcheck", "刷机配置文件检测", "检测配置文件语法错误，显示行号、列号和错误信息", "\uE8A5", ConfigCheckContent.Build),

            new("display", "显示属性修改", "分辨率 / 密度DPI / 最小宽度DP", "\uE7F4", DisplayTweaksContent.Build),
            new("battery", "电池状态模拟", "电量 / 温度 / 充电类型", "\uE9EC", BatterySimContent.Build),
            new("timeout", "锁屏时间修改", "修改 screen_off_timeout", "\uE823", ScreenTimeoutContent.Build),
            new("statusicons", "隐藏状态栏图标", "时间/蓝牙/定位/WiFi/电池等", "\uE71B", StatusBarIconsContent.Build),
            new("fontscale", "字体调节", "字体缩放（最大 5 倍）", "\uE8D2", FontScaleContent.Build),
            new("animscale", "动画速度", "窗口/过渡/动画时长", "\uE768", AnimationScaleContent.Build),
            new("a11yreset", "一键关闭辅助功能", "TalkBack/随选朗读/放大/反色/色彩校正/高对比度", "\uE74D", AccessibilityResetContent.Build),
            new("keysim", "模拟按键", "音量/锁屏/返回/主页/数据流量等", "\uE765", KeySimContent.Build),
        };

        public static ToolDef? Get(string id) => All.FirstOrDefault(t => t.Id == id);

        // ---- 页面内容公共辅助 ----
        public static StackPanel Root() => new() { Spacing = 12 };

        public static TextBlock Section(string text) => new()
        {
            Text = text,
            Style = (Style)Application.Current.Resources["CardTitleStyle"],
            Margin = new Thickness(0, 4, 0, 0)
        };

        public static TextBlock Hint(string text) => new()
        {
            Text = text,
            Style = (Style)Application.Current.Resources["CaptionTextStyle"],
            TextWrapping = TextWrapping.Wrap
        };

        public static Button Accent(string text) => new()
        {
            Content = text,
            Style = (Style)Application.Current.Resources["AccentButtonStyle"]
        };

        public static Button Normal(string text) => new()
        {
            Content = text,
            Style = (Style)Application.Current.Resources["DefaultButtonStyle"]
        };

        public static WrapPanel Actions(params Button[] buttons)
        {
            var sp = new WrapPanel { Spacing = 8 };
            foreach (var b in buttons) sp.Children.Add(b);
            return sp;
        }

        public static void WireButton(Grid g, int col, Action onBtn)
        {
            if (g.Children[col] is Button b) b.Click += (s, e) => onBtn();
        }

        /// <summary>
        /// 行内字段标签，垂直居中，与控件同处一行。
        /// 对应 Python 版 QHBoxLayout 里的 QLabel。
        /// </summary>
        public static TextBlock FieldLabel(string text) => new()
        {
            Text = text,
            Style = (Style)Application.Current.Resources["CardSubtitleStyle"],
            VerticalAlignment = VerticalAlignment.Center,
            TextWrapping = TextWrapping.NoWrap,
        };

        /// <summary>
        /// 执行设备操作。失败（含未连接设备）时提示原因并返回 null。
        /// 调用方必须先判空再显示成功提示，避免“没执行却报成功”。
        /// </summary>
        public static string? Run(Func<string> f)
        {
            try { return f(); }
            catch (Exception ex) { Dlg.Tip("提示", ex.Message); return null; }
        }

        /// <summary>是否已连接系统模式设备（对应 Python 的 _get_serial 判空）。</summary>
        public static bool HasDevice()
        {
            try
            {
                var (mode, serial) = AdbService.DetectConnectionMode();
                return mode == "system" && !string.IsNullOrEmpty(serial);
            }
            catch { return false; }
        }

        /// <summary>将页面加载时的设备查询延迟到空闲时执行，避免阻塞页面渲染。</summary>
        public static void Defer(Action a)
        {
            var dq = Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread();
            if (dq != null)
                dq.TryEnqueue(Microsoft.UI.Dispatching.DispatcherQueuePriority.Low, () => { try { a(); } catch { } });
            else
                try { a(); } catch { }
        }
    }

    /// <summary>单分区刷入（fastboot）。</summary>
    public static class PartitionFlashContent
    {
        private static bool _busy;

        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            // 对齐 Python 版 partition_flash_dialog.py 的 row1：
            //   row1.addWidget(QLabel("分区")); row1.addWidget(self.part_edit)
            //   row1.addWidget(QLabel("槽位")); row1.addWidget(self.slot_combo)
            //   row1.addWidget(QLabel("目标模式")); row1.addWidget(self.mode_combo)
            //   row1.addWidget(self.auto_switch)
            // 即「标签与控件处在同一行」，输入框吸收剩余宽度。
            var row1 = new Grid { ColumnSpacing = 8 };
            row1.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });   // 分区
            row1.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row1.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });   // 槽位
            row1.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row1.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });   // 目标模式
            row1.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row1.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });   // 自动切换

            var partEdit = new TextBox
            {
                PlaceholderText = "手动输入分区名，例如：boot / vendor_boot / system",
                Style = (Style)Application.Current.Resources["RoundedTextBoxStyle"],
                MinWidth = 160,
                HorizontalAlignment = HorizontalAlignment.Stretch,
            };
            var slotCombo = new ComboBox { Style = (Style)Application.Current.Resources["RoundedComboBoxStyle"], MinWidth = 88 };
            foreach (var s in new[] { "不指定", "_a", "_b" }) slotCombo.Items.Add(s);
            slotCombo.SelectedIndex = 0;

            var modeCombo = new ComboBox { Style = (Style)Application.Current.Resources["RoundedComboBoxStyle"], MinWidth = 120 };
            foreach (var s in new[] { "fastbootd", "bootloader" }) modeCombo.Items.Add(s);
            modeCombo.SelectedIndex = 0;

            var autoSwitch = new CheckBox { Content = "自动切换模式", IsChecked = true, VerticalAlignment = VerticalAlignment.Center };

            void AddCell(FrameworkElement el, int col)
            {
                Grid.SetColumn(el, col);
                row1.Children.Add(el);
            }
            AddCell(MiscToolContents.FieldLabel("分区"), 0);
            AddCell(partEdit, 1);
            AddCell(MiscToolContents.FieldLabel("槽位"), 2);
            AddCell(slotCombo, 3);
            AddCell(MiscToolContents.FieldLabel("目标模式"), 4);
            AddCell(modeCombo, 5);
            AddCell(autoSwitch, 6);
            cp.Children.Add(row1);

            // 对齐 row2：镜像输入框 + 选择镜像 + 刷入分区（按钮文字沿用 Python 的「刷入分区」）。
            var row2 = new Grid { ColumnSpacing = 8 };
            row2.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row2.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row2.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row2.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var imgEdit = new TextBox
            {
                PlaceholderText = "选择要刷入的 .img 文件",
                Style = (Style)Application.Current.Resources["RoundedTextBoxStyle"],
                MinWidth = 160,
                HorizontalAlignment = HorizontalAlignment.Stretch,
            };
            var btnPick = new Button { Content = "选择镜像", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnRun = new Button { Content = "刷入分区", Style = (Style)Application.Current.Resources["AccentButtonStyle"] };

            void AddCell2(FrameworkElement el, int col)
            {
                Grid.SetColumn(el, col);
                row2.Children.Add(el);
            }
            AddCell2(MiscToolContents.FieldLabel("镜像"), 0);
            AddCell2(imgEdit, 1);
            AddCell2(btnPick, 2);
            AddCell2(btnRun, 3);
            cp.Children.Add(row2);

            var log = new LogView { Height = 240 };
            cp.Children.Add(MiscToolContents.Section("输出日志"));
            cp.Children.Add(log);

            btnPick.Click += async (s, e) =>
            {
                var picker = new FileOpenPicker();
                picker.FileTypeFilter.Add(".img");
                picker.FileTypeFilter.Add("*");
                var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
                var f = await picker.PickSingleFileAsync();
                if (f != null) imgEdit.Text = f.Path;
            };

            btnRun.Click += async (s, e) =>
            {
                // 与 Python _run_proc 一致：已有任务在执行时提示并返回，避免并发刷入。
                if (_busy) { Dlg.Tip("提示", "已有任务在执行中"); return; }
                var fastboot = ExtTool.Resolve("fastboot");
                var img = imgEdit.Text.Trim();
                var part = partEdit.Text.Trim();
                if (!File.Exists(img)) { Dlg.Tip("提示", "请选择有效的镜像文件"); return; }
                if (part.Length == 0) { Dlg.Tip("提示", "请输入分区名"); return; }
                if (part.Any(char.IsWhiteSpace)) { Dlg.Tip("提示", "分区名不能包含空格"); return; }
                var slot = (string)slotCombo.SelectedItem ?? "不指定";
                var finalPart = part;
                if (slot != "不指定" && !finalPart.EndsWith("_a") && !finalPart.EndsWith("_b"))
                    finalPart += slot;
                var targetMode = (string)modeCombo.SelectedItem ?? "fastbootd";
                var cmd = new[] { fastboot, "flash", finalPart, img };

                var confirmText = string.Join("\n", new[]
                {
                    "即将执行分区维护刷入，请确认以下信息无误：",
                    $"分区：{finalPart}",
                    $"槽位：{slot}",
                    $"目标模式：{targetMode}",
                    $"镜像文件：{Path.GetFileName(img)}",
                    $"镜像路径：{img}",
                    "",
                    "风险提示：",
                    "1. 该功能仅适用于你本人合法持有且已正常解锁的开发设备。",
                    "2. 错误的分区名、模式或镜像文件可能导致设备无法启动。",
                    "3. 本工具不提供绕过解锁、破解或安全限制规避能力。",
                    "4. 请确认镜像来源可信，并了解当前机型的分区用途后再继续。",
                    "",
                    "最终命令:",
                    string.Join(" ", cmd)
                });
                if (!await Dlg.Confirm("最后确认", confirmText)) return;

                log.ClearLog();
                btnRun.IsEnabled = false;
                _busy = true;
                try
                {
                    var stepId = Guid.NewGuid().ToString("N");
                    log.StartStep(stepId, $"刷入分区 {finalPart}");

                    var switched = true;
                    if (autoSwitch.IsChecked == true)
                    {
                        var sidMode = Guid.NewGuid().ToString("N");
                        log.StartStep(sidMode, $"切换到 {targetMode} 模式");
                        try
                        {
                            var bootArgs = targetMode == "fastbootd"
                                ? new[] { "reboot", "fastboot" }
                                : new[] { "reboot-bootloader" };
                            // 异步执行，避免阻塞 UI 线程导致界面卡死。
                            await ProcessRunner.RunAsync(
                                fastboot, bootArgs, AppPaths.BinDir, timeoutMs: 30000);

                            log.AppendLog("等待设备重连(15s)...");
                            // Task.Delay 不阻塞 UI，界面保持响应。
                            await Task.Delay(15000);
                            log.FinishStep(sidMode, true, "");
                        }
                        catch (Exception ex)
                        {
                            log.FinishStep(sidMode, false, ex.Message);
                            log.AppendLog($"切换模式失败：{ex.Message}", "#f53f3f");
                            switched = false;
                        }
                    }

                    if (switched)
                    {
                        var res = await ProcessRunner.RunAsync(fastboot, cmd.Skip(1), AppPaths.BinDir, s => log.AppendLog(s), () => false, 600000);
                        log.FinishStep(stepId, res.ExitCode == 0, res.ExitCode == 0 ? "" : $"Code {res.ExitCode}");
                    }
                    else
                    {
                        log.FinishStep(stepId, false, "切换模式失败");
                    }
                }
                finally
                {
                    // 无论成功、失败或异常都恢复按钮，避免卡在禁用状态。
                    _busy = false;
                    btnRun.IsEnabled = true;
                }
            };

            return cp;
        }

    }
    /// <summary>Payload.bin 处理。</summary>
    public static class PayloadContent
    {
        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            var row1 = Dlg.InputRow("payload.bin", "本地路径或 http(s) 在线 URL", out var edtPayload, "浏览", () => { });
            cp.Children.Add(row1);
            var row2 = Dlg.InputRow("输出目录", "选择解包输出目录", out var edtOut, "浏览", () => { });
            cp.Children.Add(row2);
            var row3 = Dlg.InputRow("分区过滤", "留空 = 全部；多个用逗号分隔", out var edtParts, "", () => { });
            if (row3.Children.Count >= 3 && row3.Children[2] is Button b3) b3.Visibility = Visibility.Collapsed;
            cp.Children.Add(row3);

            var act = MiscToolContents.Actions();
            var btnRun = MiscToolContents.Accent("开始处理");
            var btnCancel = MiscToolContents.Normal("取消");
            btnCancel.IsEnabled = false;
            act.Children.Add(btnRun); act.Children.Add(btnCancel);
            act.HorizontalAlignment = HorizontalAlignment.Right;
            cp.Children.Add(act);

            var log = new LogView { Height = 260 };
            cp.Children.Add(MiscToolContents.Section("日志输出"));
            cp.Children.Add(log);

            var payloadPicker = new FileOpenPicker { FileTypeFilter = { ".bin", "*" } };
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
            WinRT.Interop.InitializeWithWindow.Initialize(payloadPicker, hwnd);
            MiscToolContents.WireButton(row1, 2, async () =>
            {
                var f = await payloadPicker.PickSingleFileAsync();
                if (f != null) edtPayload.Text = f.Path;
            });
            MiscToolContents.WireButton(row2, 2, async () =>
            {
                var fp = new FolderPicker();
                fp.FileTypeFilter.Add("*");
                var h2 = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(fp, h2);
                var f = await fp.PickSingleFolderAsync();
                if (f != null) edtOut.Text = f.Path;
            });

            PayloadExtractor? worker = null;
            var departed = false;
            var cancelled = false;
            cp.Loaded += (_, _) => departed = false;
            cp.Unloaded += (_, _) => { departed = true; cancelled = true; worker?.Stop(); };
            btnRun.Click += async (s, e) =>
            {
                if (worker != null || departed) return;
                cancelled = false;
                var src = edtPayload.Text.Trim();
                var outDir = edtOut.Text.Trim();
                var parts = edtParts.Text.Trim();
                if (src.Length == 0) { Dlg.Tip("提示", "请输入 payload.bin 路径或在线 URL"); return; }
                if (outDir.Length == 0) { Dlg.Tip("提示", "请输入输出目录"); return; }

                log.ClearLog();
                log.AppendLog("开始处理...");
                log.AppendLog("   " + src);
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
                log.AppendLog(cancelled ? "已取消" : (ok ? "完成" : "失败"));
                if (!cancelled && msg.Length > 0) log.AppendLog(msg);
                if (!departed && !cancelled)
                {
                    if (ok) Dlg.Tip("完成", "Payload 处理完成");
                    else Dlg.Error("失败", "Payload 处理失败，请检查日志输出");
                }
                btnRun.IsEnabled = !departed;
                btnCancel.IsEnabled = false;
                worker = null;
            };

            btnCancel.Click += (s, e) =>
            {
                cancelled = true;
                worker?.Stop();
                log.AppendLog("已请求取消，正在等待当前任务结束…");
                btnCancel.IsEnabled = false;
            };

            return cp;
        }
    }

    /// <summary>OFP 处理。</summary>
    public static class OfpContent
    {
        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

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
            cp.Children.Add(MiscToolContents.Section("日志输出"));
            cp.Children.Add(log);

            var ofpPicker = new FileOpenPicker { FileTypeFilter = { ".ofp", "*" } };
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
            WinRT.Interop.InitializeWithWindow.Initialize(ofpPicker, hwnd);
            MiscToolContents.WireButton(row1, 2, async () =>
            {
                var f = await ofpPicker.PickSingleFileAsync();
                if (f != null) edtOfp.Text = f.Path;
            });
            MiscToolContents.WireButton(row2, 2, async () =>
            {
                var fp = new FolderPicker();
                fp.FileTypeFilter.Add("*");
                var h2 = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(fp, h2);
                var f = await fp.PickSingleFolderAsync();
                if (f != null) edtOut.Text = f.Path;
            });

            OfpProcessor? worker = null;
            var departed = false;
            var cancelled = false;
            cp.Loaded += (_, _) => departed = false;
            cp.Unloaded += (_, _) => { departed = true; cancelled = true; worker?.Stop(); };
            btnRun.Click += async (s, e) =>
            {
                if (worker != null || departed) return;
                cancelled = false;
                var ofp = edtOfp.Text.Trim();
                var outDir = edtOut.Text.Trim();
                var mode = combo.SelectedIndex == 1 ? "qc" : (combo.SelectedIndex == 2 ? "mtk" : "auto");
                if (!File.Exists(ofp)) { Dlg.Tip("提示", "请选择有效的 .ofp 文件"); return; }
                if (outDir.Length == 0) { Dlg.Tip("提示", "请选择输出目录"); return; }

                log.ClearLog();
                log.AppendLog("开始处理...");
                log.AppendLog("   " + ofp);
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
                    ok = await Task.Run(() =>
                    {
                        Directory.CreateDirectory(outDir);
                        return worker.Extract(ofp, outDir, mode);
                    });
                    msg = ok ? "完成" : "失败";
                }
                catch (Exception ex)
                {
                    ok = false;
                    msg = ex.Message;
                }
                log.AppendLog("");
                log.AppendLog(cancelled ? "已取消" : (ok ? "完成" : "失败"));
                if (!cancelled && msg.Length > 0) log.AppendLog(msg);
                if (!departed && !cancelled)
                {
                    if (ok) Dlg.Tip("完成", "OFP 处理完成");
                    else Dlg.Error("失败", "OFP 处理失败，请检查日志输出");
                }
                btnRun.IsEnabled = !departed;
                btnCancel.IsEnabled = false;
                worker = null;
            };
            btnCancel.Click += (s, e) =>
            {
                cancelled = true;
                worker?.Stop();
                log.AppendLog("已请求取消，正在等待当前任务结束…");
                btnCancel.IsEnabled = false;
            };

            return cp;
        }
    }

    /// <summary>启动异常修复（Magisk --remove-modules）。</summary>
    public static class UnbrickContent
    {
        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            var info = MiscToolContents.Hint("此功能用于移除异常模块配置，以恢复系统启动。\n操作逻辑：adb shell Magisk --remove-modules\n前提：手机 ADB 连接正常（开机卡 Logo 或 Recovery 模式），设备支持对应的模块恢复指令。");
            cp.Children.Add(info);

            var log = new LogView { Height = 220 };
            cp.Children.Add(MiscToolContents.Section("执行日志"));
            cp.Children.Add(log);

            var btnRun = MiscToolContents.Accent("开始修复");
            btnRun.HorizontalAlignment = HorizontalAlignment.Right;
            cp.Children.Add(btnRun);

            btnRun.Click += async (s, e) =>
            {
                var (mode, serial) = AdbService.DetectConnectionMode();
                if (string.IsNullOrEmpty(serial))
                {
                    Dlg.Tip("提示", "未检测到设备，请确保 ADB 连接正常");
                    return;
                }
                var confirmText = string.Join("\n", new[]
                {
                    "此功能用于移除异常模块配置，以恢复系统启动。",
                    "",
                    "操作逻辑：",
                    "adb shell Magisk --remove-modules",
                    "",
                    "前提条件：",
                    "1. 手机 ADB 连接正常（开机卡 Logo 或 Recovery 模式）",
                    "2. 当前设备支持对应的模块恢复指令",
                    "",
                    "是否继续？"
                });
                if (!await Dlg.Confirm("启动异常修复", confirmText)) return;

                log.ClearLog();
                log.AppendLog("开始执行启动异常修复流程...");
                var stepId = Guid.NewGuid().ToString("N");
                log.StartStep(stepId, "移除异常模块");
                log.AppendLog("执行: adb shell Magisk --remove-modules");
                try
                {
                    var outStr = AdbService.AdbShellSerial(serial, "Magisk --remove-modules", 60) ?? "";
                    foreach (var l in outStr.Split('\n')) if (l.Trim().Length > 0) log.AppendLog(l);
                    log.AppendLog("命令输出: " + outStr.Trim());
                    var low = outStr.ToLowerInvariant();
                    // 静默成功是正常结果，只有明确的“不可用”输出才算失败。
                    if (low.Contains("not found") || low.Contains("inaccessible") || low.Contains("no such"))
                    {
                        log.FinishStep(stepId, false, "命令未找到或不可用");
                        Dlg.Error("失败", "执行失败，当前设备不支持该模块恢复指令。");
                        return;
                    }
                    log.FinishStep(stepId, true, "");
                }
                catch (Exception ex)
                {
                    log.FinishStep(stepId, false, ex.Message);
                    Dlg.Tip("失败", ex.Message);
                    return;
                }
                var stepReboot = Guid.NewGuid().ToString("N");
                log.StartStep(stepReboot, "重启设备");
                try
                {
                    AdbService.RebootTo("system");
                    log.FinishStep(stepReboot, true, "");
                    Dlg.Tip("完成", "恢复指令执行完成，设备正在重启。");
                }
                catch (Exception ex)
                {
                    log.FinishStep(stepReboot, false, ex.Message);
                    Dlg.Tip("失败", ex.Message);
                }
            };

            return cp;
        }
    }

    /// <summary>Magisk 模块管理。</summary>
    public static class ModuleContent
    {
        private static ModuleManager? _mgr;
        private static StackPanel? _listPanel;
        private static bool _busy;

        public static FrameworkElement Build()
        {
            _mgr = new ModuleManager();
            var cp = MiscToolContents.Root();

            var header = new Grid { ColumnSpacing = 8 };
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            var btnRefresh = new Button { Content = "刷新列表", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnInstall = new Button { Content = "安装模块 ZIP", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnBatch = new Button { Content = "批量安装", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnUndoAll = new Button { Content = "撤销全部移除", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            Grid.SetColumn(btnRefresh, 1); Grid.SetColumn(btnInstall, 2); Grid.SetColumn(btnBatch, 3); Grid.SetColumn(btnUndoAll, 4);
            header.Children.Add(new TextBlock { Text = "已安装模块", Style = (Style)Application.Current.Resources["CardTitleStyle"], VerticalAlignment = VerticalAlignment.Center });
            header.Children.Add(btnRefresh); header.Children.Add(btnInstall); header.Children.Add(btnBatch); header.Children.Add(btnUndoAll);
            cp.Children.Add(header);

            _listPanel = new StackPanel { Spacing = 8 };
            var scroll = new ScrollViewer { MaxHeight = 420, Content = _listPanel, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
            cp.Children.Add(scroll);

            btnRefresh.Click += async (s, e) => await Load();
            btnInstall.Click += async (s, e) =>
            {
                var picker = new FileOpenPicker();
                picker.FileTypeFilter.Add(".zip");
                var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
                var f = await picker.PickSingleFileAsync();
                if (f == null) return;
                if (!await ConfirmRun()) return;
                var win = new Tobatools.Dialogs.ModuleInstallWindow("模块安装日志");
                win.Activate();
                win.Start(f.Path);
                await Load();
            };
            btnBatch.Click += async (s, e) =>
            {
                var picker = new FileOpenPicker();
                picker.FileTypeFilter.Add(".zip");
                var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
                var files = await picker.PickMultipleFilesAsync();
                if (files == null || files.Count == 0) return;
                if (!await ConfirmRun()) return;
                var win = new Tobatools.Dialogs.ModuleInstallWindow("模块批量安装日志");
                win.Activate();
                win.StartBatch(files.Select(x => x.Path));
                await Load();
            };
            btnUndoAll.Click += async (s, e) =>
            {
                if (!await ConfirmRun()) return;
                await Run(async () =>
                {
                    var list = await Task.Run(() => _mgr!.ListModules());
                    foreach (var m in list.Where(x => x.Removed))
                        await Task.Run(() => _mgr!.UndoRemoveModule(m.Id));
                });
                await Load();
            };

            _ = Load();
            return cp;
        }

        private static Task<bool> ConfirmRun()
        {
            return Dlg.Confirm("确认", "即将对设备模块进行操作，请确认模块与设备均为你本人合法持有。\n继续吗？");
        }

        private static async Task Run(Func<Task> action)
        {
            if (_busy) { Dlg.Tip("提示", "任务正在进行中"); return; }
            _busy = true;
            try { await action(); }
            catch (Exception ex) { Dlg.Error("失败", ex.Message); }
            finally { _busy = false; }
        }

        private static async Task Load()
        {
            if (_busy) return;
            _busy = true;
            try
            {
                List<ModuleInfo> list;
                try { list = await Task.Run(() => _mgr!.ListModules()); }
                catch (Exception)
                {
                    _listPanel!.Children.Clear();
                    _listPanel.Children.Add(new TextBlock { Text = "未检测到 Magisk / KernelSU 环境或未授权", Style = (Style)Application.Current.Resources["CaptionTextStyle"] });
                    return;
                }
                _listPanel!.Children.Clear();
                if (list.Count == 0)
                {
                    _listPanel.Children.Add(new TextBlock { Text = "未安装任何模块", Style = (Style)Application.Current.Resources["CaptionTextStyle"] });
                    return;
                }
                foreach (var m in list)
                {
                    var border = new Border
                    {
                        Style = (Style)Application.Current.Resources["CardBorderSubtleStyle"],
                        Padding = new Thickness(14, 10, 14, 10)
                    };
                    var g = new Grid { ColumnSpacing = 10 };
                    g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                    g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
                    var info = new StackPanel { Spacing = 2 };
                    var titleLine = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
                    var nameText = new TextBlock { Text = m.Name, Style = (Style)Application.Current.Resources["CardSubtitleStyle"], FontWeight = Microsoft.UI.Text.FontWeights.SemiBold, TextWrapping = TextWrapping.Wrap };
                    // Python 待移除模块名称显示删除线。
                    if (m.Removed) nameText.TextDecorations = Windows.UI.Text.TextDecorations.Strikethrough;
                    titleLine.Children.Add(nameText);
                    if (!m.Enabled) titleLine.Children.Add(new TextBlock { Text = "已禁用", Style = (Style)Application.Current.Resources["CaptionTextStyle"], Foreground = new SolidColorBrush(Microsoft.UI.Colors.Orange), VerticalAlignment = VerticalAlignment.Center });
                    if (m.Removed) titleLine.Children.Add(new TextBlock { Text = "待移除", Style = (Style)Application.Current.Resources["CaptionTextStyle"], Foreground = new SolidColorBrush(Microsoft.UI.Colors.IndianRed), VerticalAlignment = VerticalAlignment.Center });
                    info.Children.Add(titleLine);

                    // 与 Python 一致：ID / 版本（含 versionCode）/ 作者 同一行，待移除时加删除线。
                    var ver = (m.Version ?? "").Trim();
                    var vc = (m.VersionCode ?? "").Trim();
                    if (vc.Length > 0) ver = (ver + $" ({vc})").Trim();
                    var metaText = new TextBlock
                    {
                        Text = $"ID: {m.Id}    版本: {(ver.Length > 0 ? ver : "-")}    作者 {(m.Author.Length > 0 ? m.Author : "-")}",
                        Style = (Style)Application.Current.Resources["CaptionTextStyle"],
                        TextWrapping = TextWrapping.Wrap
                    };
                    if (m.Removed) metaText.TextDecorations = Windows.UI.Text.TextDecorations.Strikethrough;
                    info.Children.Add(metaText);

                    if (m.Description.Length > 0)
                    {
                        var descText = new TextBlock
                        {
                            Text = "简介: " + m.Description,
                            Style = (Style)Application.Current.Resources["CaptionTextStyle"],
                            TextWrapping = TextWrapping.Wrap
                        };
                        if (m.Removed) descText.TextDecorations = Windows.UI.Text.TextDecorations.Strikethrough;
                        info.Children.Add(descText);
                    }
                    g.Children.Add(info);

                    var btns = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, VerticalAlignment = VerticalAlignment.Center };
                    var btnToggle = new Button { Content = m.Enabled ? "禁用" : "启用", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
                    var btnBackup = new Button { Content = "备份", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
                    var btnRemove = new Button { Content = m.Removed ? "撤销移除" : "移除", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
                    btns.Children.Add(btnToggle); btns.Children.Add(btnBackup); btns.Children.Add(btnRemove);
                    Grid.SetColumn(btns, 1);
                    g.Children.Add(btns);
                    border.Child = g;

                    var id = m.Id;
                    var removed = m.Removed;
                    btnToggle.Click += async (s, e) =>
                    {
                        await Run(async () => await Task.Run(() => _mgr!.SetEnabled(id, !m.Enabled)));
                        await Load();
                    };
                    btnBackup.Click += async (s, e) =>
                    {
                        var folder = new FolderPicker();
                        folder.FileTypeFilter.Add("*");
                        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                        WinRT.Interop.InitializeWithWindow.Initialize(folder, hwnd);
                        var f = await folder.PickSingleFolderAsync();
                        if (f == null) return;
                        await Run(async () =>
                        {
                            var dest = await Task.Run(() => _mgr!.BackupModule(id, f.Path));
                            Dlg.Tip("已备份", $"已备份到: {dest}");
                        });
                    };
                    btnRemove.Click += async (s, e) =>
                    {
                        if (!await Dlg.Confirm("确认", removed ? "确定撤销该模块的移除标记？" : $"确定移除模块 {m.Name}？（移除将在重启后生效）"))
                            return;
                        await Run(async () =>
                        {
                            if (removed) await Task.Run(() => _mgr!.UndoRemoveModule(id));
                            else await Task.Run(() => _mgr!.RemoveModule(id));
                        });
                        await Load();
                    };
                    _listPanel.Children.Add(border);
                }
            }
            finally { _busy = false; }
        }
    }

    /// <summary>ADB 开发终端。</summary>
    public static class AdbTerminalContent
    {
        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            var info = MiscToolContents.Hint("即将打开 ADB 开发终端。\n1. 该入口适用于开发调试、设备维护与日志排查。\n2. 在终端中执行的命令由你自行控制，错误命令可能影响设备状态。\n3. 本工具不提供绕过安全限制、破解或非法解锁能力。");
            cp.Children.Add(info);

            var btnRun = MiscToolContents.Accent("打开终端");
            btnRun.HorizontalAlignment = HorizontalAlignment.Right;
            cp.Children.Add(btnRun);

            btnRun.Click += async (s, e) =>
            {
                var confirmText = string.Join("\n", new[]
                {
                    "即将打开 ADB 开发终端。",
                    "",
                    "说明：",
                    "1. 该入口适用于开发调试、设备维护与日志排查。",
                    "2. 在终端中执行的命令由你自行控制，错误命令可能影响设备状态。",
                    "3. 本工具不提供绕过安全限制、破解或非法解锁能力。",
                    "",
                    "是否继续？"
                });
                if (!await Dlg.Confirm("确认打开 ADB 开发终端", confirmText)) return;
                try
                {
                    ProcessRunner.StartDetached("cmd.exe", new[] { "/K", "adb" }, AppPaths.BinDir);
                }
                catch (Exception ex)
                {
                    Dlg.Error("失败", $"无法打开终端：{ex.Message}");
                }
            };

            return cp;
        }
    }

    /// <summary>运行开发维护脚本。</summary>
    public static class RunScriptContent
    {
        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            cp.Children.Add(new TextBlock { Text = "脚本路径", Style = (Style)Application.Current.Resources["CardSubtitleStyle"] });
            var row = new Grid { ColumnSpacing = 8 };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            var edt = new TextBox { PlaceholderText = "选择要运行的 .sh 脚本", Style = (Style)Application.Current.Resources["RoundedTextBoxStyle"] };
            row.Children.Add(edt);
            var btnPick = new Button { Content = "选择", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            Grid.SetColumn(btnPick, 1); row.Children.Add(btnPick);
            var btnRun = new Button { Content = "运行", Style = (Style)Application.Current.Resources["AccentButtonStyle"] };
            Grid.SetColumn(btnRun, 2); row.Children.Add(btnRun);
            cp.Children.Add(row);

            var chkRoot = new CheckBox { Content = "使用 Root(su) 执行" };
            var chkBash = new CheckBox { Content = "使用 bash 执行(兼容脚本)" };
            var opts = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 16 };
            opts.Children.Add(chkRoot); opts.Children.Add(chkBash);
            cp.Children.Add(opts);

            var log = new LogView { Height = 140 };
            cp.Children.Add(log);

            btnPick.Click += async (s, e) =>
            {
                var picker = new FileOpenPicker();
                picker.FileTypeFilter.Add(".sh");
                picker.FileTypeFilter.Add("*");
                var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
                var f = await picker.PickSingleFileAsync();
                if (f != null) edt.Text = f.Path;
            };

            btnRun.Click += async (s, e) =>
            {
                var script = edt.Text.Trim();
                if (script.Length == 0) { Dlg.Tip("提示", "请先选择脚本"); return; }
                if (!File.Exists(script)) { Dlg.Tip("提示", "脚本文件不存在"); return; }
                var riskText = string.Join("\n", new[]
                {
                    "该功能会将本地 Shell 脚本推送到设备并执行。",
                    "",
                    "风险提示：",
                    "1. 仅适用于你本人合法持有且已开启调试的开发设备。",
                    "2. 脚本可能修改系统设置、应用状态或设备文件。",
                    "3. 若启用 Root 执行，手机端可能弹出高权限授权提示。",
                    "4. 请确保脚本来源可信，并清楚脚本内容后再继续。",
                    "",
                    "是否继续？"
                });
                if (!await Dlg.Confirm("确认运行开发维护脚本", riskText)) return;

                log.ClearLog();
                btnRun.IsEnabled = false;
                var sidCheck = Guid.NewGuid().ToString("N");
                log.StartStep(sidCheck, "检查设备连接");
                var (mode, serial) = AdbService.DetectConnectionMode();
                if (mode != "system")
                {
                    log.FinishStep(sidCheck, false, "非系统模式");
                    Dlg.Tip("提示", "请在系统模式下连接设备后再运行脚本");
                    btnRun.IsEnabled = true;
                    return;
                }
                if (string.IsNullOrEmpty(serial))
                {
                    log.FinishStep(sidCheck, false, "无设备");
                    Dlg.Tip("提示", "未检测到设备序列号");
                    btnRun.IsEnabled = true;
                    return;
                }
                log.FinishStep(sidCheck, true, serial);

                var sidPrep = Guid.NewGuid().ToString("N");
                log.StartStep(sidPrep, "准备脚本环境");
                var hash = Math.Abs(script.GetHashCode()) & 0x7fffffff;
                var remote = $"/data/local/tmp/{Path.GetFileNameWithoutExtension(script)}_{hash & 0xfffffff}.sh";
                var adb = ExtTool.Resolve("adb");
                var useRoot = chkRoot.IsChecked == true;
                var useBash = chkBash.IsChecked == true;
                if (!useBash)
                {
                    try
                    {
                        var first = File.ReadLines(script).FirstOrDefault() ?? "";
                        if (first.TrimStart().StartsWith("#!") && first.Contains("bash", StringComparison.OrdinalIgnoreCase))
                            useBash = true;
                    }
                    catch { }
                }
                try
                {
                    log.FinishStep(sidPrep, true, "");
                }
                catch (Exception ex)
                {
                    log.FinishStep(sidPrep, false, ex.Message);
                    Dlg.Tip("失败", $"无法启动终端：{ex.Message}");
                    btnRun.IsEnabled = true;
                    return;
                }

                var sidLaunch = Guid.NewGuid().ToString("N");
                log.StartStep(sidLaunch, "启动终端窗口");
                var runner = useBash ? "bash" : "sh";
                var lines = new List<string>
                {
                    "@echo off",
                    "chcp 65001 >nul",
                    $"\"{adb}\" -s {serial} push \"{script}\" {remote}",
                    "if errorlevel 1 goto end",
                    $"\"{adb}\" -s {serial} shell -t chmod 755 {remote}",
                    "if errorlevel 1 goto end",
                    useRoot ? $"\"{adb}\" -s {serial} shell -t su -c '{runner} {remote}'"
                            : $"\"{adb}\" -s {serial} shell -t {runner} {remote}",
                    "echo.",
                    "echo 脚本执行结束，进入 ADB Shell（可继续交互）。",
                    useRoot ? $"\"{adb}\" -s {serial} shell -t su" : $"\"{adb}\" -s {serial} shell -t",
                    ":end"
                };
                var cmdPath = Path.Combine(AppPaths.TempDir, $"tobatools_run_sh_{hash & 0xfffffff}.cmd");
                File.WriteAllText(cmdPath, string.Join("\r\n", lines), new UTF8Encoding(false));
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = "cmd.exe",
                        Arguments = $"/K \"{cmdPath}\"",
                        WorkingDirectory = AppPaths.BinDir,
                        UseShellExecute = true,
                        CreateNoWindow = false
                    });
                    log.FinishStep(sidLaunch, true, "已弹出");
                    Dlg.Tip("已启动", "已弹出终端窗口，请在终端内交互运行");
                }
                catch (Exception ex)
                {
                    log.FinishStep(sidLaunch, false, ex.Message);
                    Dlg.Tip("失败", $"无法启动终端：{ex.Message}");
                }
                btnRun.IsEnabled = true;
            };

            return cp;
        }
    }

    /// <summary>刷机配置文件检测。</summary>
    public static class ConfigCheckContent
    {
        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            var row = new Grid { ColumnSpacing = 8 };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            var edtPath = new TextBox { PlaceholderText = "选择要检测的刷机配置文件", IsReadOnly = true, Style = (Style)Application.Current.Resources["RoundedTextBoxStyle"] };
            row.Children.Add(edtPath);
            var btnPick = new Button { Content = "选择文件", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            Grid.SetColumn(btnPick, 1); row.Children.Add(btnPick);
            cp.Children.Add(row);

            var summary = new TextBlock { Text = "", Style = (Style)Application.Current.Resources["CardTitleStyle"], Margin = new Thickness(0, 4, 0, 0) };
            cp.Children.Add(summary);

            var txt = new TextBox
            {
                Text = "",
                IsReadOnly = true,
                TextWrapping = TextWrapping.Wrap,
                AcceptsReturn = true,
                MinHeight = 260,
                MaxHeight = 420,
                FontFamily = (FontFamily)Application.Current.Resources["MonoFont"],
                FontSize = 12.5
            };
            ScrollViewer.SetVerticalScrollBarVisibility(txt, ScrollBarVisibility.Auto);
            cp.Children.Add(txt);

            btnPick.Click += async (s, e) =>
            {
                var picker = new FileOpenPicker();
                picker.FileTypeFilter.Add(".txt");
                picker.FileTypeFilter.Add("*");
                var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
                var file = await picker.PickSingleFileAsync();
                if (file == null) return;
                var path = file.Path;
                edtPath.Text = path;

                string[] lines;
                try { lines = File.ReadAllLines(path); }
                catch (Exception ex) { Dlg.Error("错误", $"无法读取文件: {ex.Message}"); return; }

                var errors = new List<Dictionary<string, string>>();
                var warnings = new List<Dictionary<string, string>>();
                var hasDevice = false;
                var hasMode = false;
                string? currentMode = null;
                var validModes = new HashSet<string> { "bootloader", "fastbootd" };
                var validCommands = new HashSet<string> { "system", "wipe-data", "set-a", "set-b" };

                for (int i = 0; i < lines.Length; i++)
                {
                    var originalLine = lines[i];
                    var line = originalLine.Trim();
                    int col = originalLine.Length - originalLine.TrimStart().Length + 1;
                    if (line.Length == 0 || line.StartsWith("#")) continue;
                    if (line.StartsWith("device:"))
                    {
                        hasDevice = true;
                        var deviceId = line.Contains(':') ? line.Split(':', 2)[1].Trim() : "";
                        if (deviceId.Length == 0)
                            errors.Add(E(line, i + 1, col + 7, "错误", "device: 后面缺少设备型号", "示例: device:codename"));
                        continue;
                    }
                    if (validModes.Contains(line))
                    {
                        hasMode = true;
                        currentMode = line;
                        continue;
                    }
                    if (validCommands.Contains(line))
                    {
                        if (line == "wipe-data")
                            warnings.Add(E(line, i + 1, col, "警告", "wipe-data 已被 UI 控制，配置文件中的此行将被忽略", "删除此行，由工具箱 UI 复选框控制"));
                        continue;
                    }
                    if (line.StartsWith("-"))
                    {
                        if (currentMode == null)
                        {
                            errors.Add(E(line, i + 1, col, "错误", "分区指令必须在 bootloader 或 fastbootd 模式之后", "在此行之前添加 bootloader 或 fastbootd"));
                            continue;
                        }
                        var body = line[1..];
                        var parts = body.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                        if (parts.Length == 0)
                        {
                            errors.Add(E(line, i + 1, col + 1, "错误", "分区名称为空", "示例: -boot_ab 或 -recovery"));
                            continue;
                        }
                        var partition = parts[0];
                        if (parts.Length > 1)
                        {
                            var cmd = parts[1];
                            if (cmd == "disable")
                            {
                                if (!partition.StartsWith("vbmeta"))
                                    warnings.Add(E(line, i + 1, col + partition.Length + 2, "警告", "disable 通常只用于 vbmeta 分区", "请确认是否需要禁用 AVB"));
                            }
                            else if (cmd == "del")
                            {
                                if (currentMode != "fastbootd")
                                    errors.Add(E(line, i + 1, col + partition.Length + 2, "错误", "逻辑分区删除必须在 fastbootd 模式下", "在此行之前添加 fastbootd"));
                            }
                            else if (cmd == "add")
                            {
                                if (currentMode != "fastbootd")
                                    errors.Add(E(line, i + 1, col + partition.Length + 2, "错误", "逻辑分区创建必须在 fastbootd 模式下", "在此行之前添加 fastbootd"));
                                if (parts.Length < 3)
                                    errors.Add(E(line, i + 1, col + partition.Length + 6, "错误", "add 命令缺少分区大小", "示例: -my_product add 1M"));
                            }
                            else
                            {
                                warnings.Add(E(line, i + 1, col + partition.Length + 2, "警告", $"未知的命令 {cmd}", "支持的命令: disable, del, add"));
                            }
                        }
                        continue;
                    }
                    errors.Add(E(line, i + 1, col, "错误", line.Length > 30 ? $"未知的指令 {line[..30]}..." : $"未知的指令 {line}", "支持: device:, bootloader, fastbootd, -partition, system"));
                }

                if (!hasDevice)
                    errors.Insert(0, E("", 1, 1, "错误", "配置文件缺少 device: 字段", "在文件开头添加: device:OP5551L1"));
                if (!hasMode)
                    warnings.Insert(0, E("", 1, 1, "警告", "配置文件中没有模式切换指令", "建议添加 bootloader 或 fastbootd"));

                var sumText = $"错误: {errors.Count} 个  |  警告: {warnings.Count} 个";
                if (errors.Count > 0) summary.Foreground = new SolidColorBrush(Microsoft.UI.Colors.IndianRed);
                else if (warnings.Count > 0) summary.Foreground = new SolidColorBrush(Color.FromArgb(255, 250, 173, 20));
                else { sumText = "✅ 没有发现问题"; summary.Foreground = new SolidColorBrush(Color.FromArgb(255, 82, 196, 26)); }
                summary.Text = sumText;

                var sb = new StringBuilder();
                if (errors.Count > 0)
                {
                    sb.AppendLine("\n=== 错误 (Errors) ===");
                    foreach (var err in errors)
                    {
                        sb.AppendLine($"\n❌ 行 {err["line"]}, 列 {err["col"]}: {err["type"]}");
                        sb.AppendLine($"   {err["msg"]}");
                        if (err.ContainsKey("suggestion")) sb.AppendLine($"   建议: {err["suggestion"]}");
                    }
                }
                if (warnings.Count > 0)
                {
                    sb.AppendLine("\n\n=== 警告 (Warnings) ===");
                    foreach (var warn in warnings)
                    {
                        sb.AppendLine($"\n⚠️  行 {warn["line"]}, 列 {warn["col"]}: {warn["type"]}");
                        sb.AppendLine($"   {warn["msg"]}");
                        if (warn.ContainsKey("suggestion")) sb.AppendLine($"   建议: {warn["suggestion"]}");
                    }
                }
                if (errors.Count == 0 && warnings.Count == 0)
                {
                    sb.AppendLine("\n✅ 配置文件语法正确，没有发现问题！");
                    sb.AppendLine("\n可以安全使用此配置文件进行刷机。");
                }
                txt.Text = sb.ToString();
            };

            return cp;
        }

        private static Dictionary<string, string> E(string line, int ln, int col, string type, string msg, string suggestion)
            => new() { { "line", ln.ToString() }, { "col", col.ToString() }, { "type", type }, { "msg", msg }, { "suggestion", suggestion } };
    }

    /// <summary>显示属性修改。</summary>
    public static class DisplayTweaksContent
    {
        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            var rowRes = Dlg.InputRow("分辨率 (例如 1080x2400)", "留空表示不修改", out var edtRes, "应用", () => { });
            var rowDen = Dlg.InputRow("密度DPI (例如 420)", "留空表示不修改", out var edtDen, "应用", () => { });
            var rowSw = Dlg.InputRow("最小宽度DP (例如 411)", "留空表示不修改", out var edtSw, "应用", () => { });
            cp.Children.Add(rowRes);
            cp.Children.Add(rowDen);
            cp.Children.Add(rowSw);

            var act = new WrapPanel { Spacing = 8, HorizontalAlignment = HorizontalAlignment.Right };
            var btnRefresh = new Button { Content = "刷新当前值", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnReset = new Button { Content = "重置(WM)", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            act.Children.Add(btnRefresh);
            act.Children.Add(btnReset);
            cp.Children.Add(act);

            MiscToolContents.WireButton(rowRes, 2, () =>
            {
                var val = edtRes.Text.Trim();
                if (val.Length == 0) { Dlg.Tip("提示", "分辨率为空"); return; }
                if (!val.Contains("x")) { Dlg.Tip("提示", "分辨率格式应类似 1080x2400"); return; }
                var outStr = MiscToolContents.Run(() => Dev.Shell($"wm size {val}", 10));
                if (outStr == null) return;
                Dlg.Tip("完成", outStr.Trim().Length > 0 ? outStr.Trim() : "已应用分辨率");
            });
            MiscToolContents.WireButton(rowDen, 2, () =>
            {
                var val = edtDen.Text.Trim();
                if (val.Length == 0) { Dlg.Tip("提示", "密度为空"); return; }
                if (!val.All(char.IsDigit)) { Dlg.Tip("提示", "密度应为数字"); return; }
                var outStr = MiscToolContents.Run(() => Dev.Shell($"wm density {val}", 10));
                if (outStr == null) return;
                Dlg.Tip("完成", outStr.Trim().Length > 0 ? outStr.Trim() : "已应用密度");
            });
            MiscToolContents.WireButton(rowSw, 2, () =>
            {
                var val = edtSw.Text.Trim();
                if (val.Length == 0) { Dlg.Tip("提示", "最小宽度为空"); return; }
                if (!val.All(char.IsDigit)) { Dlg.Tip("提示", "最小宽度应为数字"); return; }
                var outStr = MiscToolContents.Run(() => Dev.Shell($"settings put secure smallest_width {val}", 10));
                if (outStr == null) return;
                if (outStr.Contains("Permission"))
                { Dlg.Error("失败", "权限不足：部分系统需要 Root 或 Shizuku"); return; }
                Dlg.Tip("完成", outStr.Trim().Length > 0 ? outStr.Trim() : "已应用最小宽度");
            });
            btnRefresh.Click += async (s, e) => { Refresh(edtRes, edtDen, edtSw); await Task.CompletedTask; };
            btnReset.Click += (s, e) =>
            {
                var o1 = MiscToolContents.Run(() => Dev.Shell("wm size reset", 10));
                var o2 = MiscToolContents.Run(() => Dev.Shell("wm density reset", 10));
                if (o1 == null || o2 == null) return;
                Refresh(edtRes, edtDen, edtSw);
                var msg = "已重置\n";
                if (!string.IsNullOrEmpty(o1)) msg += o1.Trim() + "\n";
                if (!string.IsNullOrEmpty(o2)) msg += o2.Trim();
                Dlg.Tip("完成", msg.Trim());
            };

            MiscToolContents.Defer(() => Refresh(edtRes, edtDen, edtSw));
            return cp;
        }

        private static void Refresh(TextBox edtRes, TextBox edtDen, TextBox edtSw)
        {
            try
            {
                var outSize = Dev.Shell("wm size", 6);
                var outDen = Dev.Shell("wm density", 6);
                var sw = Dev.Shell("settings get secure smallest_width", 6).Trim();
                edtRes.Text = ParseWm(outSize, "size");
                edtDen.Text = ParseWm(outDen, "density");
                edtSw.Text = (sw.Length > 0 && sw.ToLowerInvariant() != "null") ? sw : "";
            }
            catch { }
        }

        private static string ParseWm(string output, string what)
        {
            if (string.IsNullOrEmpty(output)) return "";
            foreach (var line in output.Split('\n'))
            {
                var t = line.Trim();
                if (t.Contains($"Physical {what}:"))
                    return t.Split($"Physical {what}:", 2)[1].Trim();
                if (t.StartsWith($"physical {what}:"))
                    return t.Split(':', 2)[1].Trim();
            }
            foreach (var line in output.Split('\n'))
            {
                var t = line.Trim();
                if (t.Contains($"Override {what}:"))
                    return t.Split($"Override {what}:", 2)[1].Trim();
            }
            return "";
        }
    }

    /// <summary>电池状态模拟。</summary>
    public static class BatterySimContent
    {
        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            var rowLevel = Dlg.InputRow("电量 (0-100)", "", out var edtLevel, "应用", () => { });
            var rowTemp = Dlg.InputRow("温度 (℃)", "", out var edtTemp, "应用", () => { });
            cp.Children.Add(rowLevel);
            cp.Children.Add(rowTemp);

            var rowPlug = new Grid { ColumnSpacing = 8 };
            rowPlug.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            rowPlug.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            rowPlug.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            rowPlug.Children.Add(new TextBlock { Text = "充电状态", Style = (Style)Application.Current.Resources["CardSubtitleStyle"], VerticalAlignment = VerticalAlignment.Center });
            var comboPlug = new ComboBox { Style = (Style)Application.Current.Resources["RoundedComboBoxStyle"] };
            var plugItems = new[] { "非充电", "无线充电", "USB充电", "直流充电" };
            foreach (var it in plugItems) comboPlug.Items.Add(it);
            comboPlug.SelectedIndex = 0;
            Grid.SetColumn(comboPlug, 1);
            rowPlug.Children.Add(comboPlug);
            var btnPlug = new Button { Content = "应用", Style = (Style)Application.Current.Resources["AccentButtonStyle"] };
            Grid.SetColumn(btnPlug, 2);
            rowPlug.Children.Add(btnPlug);
            cp.Children.Add(rowPlug);

            var act = new WrapPanel { Spacing = 8, HorizontalAlignment = HorizontalAlignment.Right };
            var btnRefresh = new Button { Content = "刷新当前值", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnReset = new Button { Content = "重置模拟", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            act.Children.Add(btnRefresh);
            act.Children.Add(btnReset);
            cp.Children.Add(act);

            void Refresh()
            {
                if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                var dump = MiscToolContents.Run(() => Dev.Shell("dumpsys battery", 8));
                if (dump == null) return;
                var level = "";
                var tempC = "";
                var plugged = "";
                foreach (var line in dump.Split('\n'))
                {
                    var t = line.Trim();
                    if (t.StartsWith("level:")) level = t.Split(new[] { ':' }, 2)[1].Trim();
                    else if (t.StartsWith("temperature:"))
                    {
                        var raw = t.Split(new[] { ':' }, 2)[1].Trim();
                    // 设备以 0.1℃ 为单位上报，显示时换算成摄氏度。
                    if (double.TryParse(raw, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var tv))
                            tempC = (tv / 10.0).ToString(System.Globalization.CultureInfo.InvariantCulture);
                        else tempC = raw;
                    }
                    else if (t.StartsWith("plugged:")) plugged = t.Split(new[] { ':' }, 2)[1].Trim();
                }
                edtLevel.Text = level;
                edtTemp.Text = tempC;
                var idx = 0;
                if (plugged == "4") idx = 1;
                else if (plugged == "2") idx = 2;
                else if (plugged == "1") idx = 3;
                comboPlug.SelectedIndex = idx;
            }

            MiscToolContents.WireButton(rowLevel, 2, () =>
            {
                var v = edtLevel.Text.Trim();
                if (v.Length == 0 || !v.All(char.IsDigit)) { Dlg.Tip("提示", "请输入 0-100 的电量"); return; }
                var n = int.Parse(v);
                if (n < 0 || n > 100) { Dlg.Tip("提示", "电量范围 0-100"); return; }
                var outStr = MiscToolContents.Run(() => Dev.Shell($"dumpsys battery set level {n}", 8));
                if (outStr == null) return;
                Dlg.Tip("完成", "已设置电量");
            });
            MiscToolContents.WireButton(rowTemp, 2, () =>
            {
                var v = edtTemp.Text.Trim();
                if (v.Length == 0) { Dlg.Tip("提示", "请输入温度"); return; }
                if (!double.TryParse(v, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var c))
                { Dlg.Tip("提示", "温度应为数字"); return; }
                // 设备接口单位是 0.1℃，必须乘以 10 后取整（Python: int(round(c*10.0))）。
                var t = (int)Math.Round(c * 10.0, MidpointRounding.AwayFromZero);
                var outStr = MiscToolContents.Run(() => Dev.Shell($"dumpsys battery set temperature {t}", 8));
                if (outStr == null) return;
                Dlg.Tip("完成", "已设置温度");
            });
            btnPlug.Click += (s, e) =>
            {
                var idx = comboPlug.SelectedIndex;
                if (idx < 0) idx = 0;
                // dumpsys battery set plugged: 0 电池 / 1 直流(ac) / 2 USB / 4 无线
                var plugged = idx == 1 ? "4" : (idx == 2 ? "2" : (idx == 3 ? "1" : "0"));
                var outStr = MiscToolContents.Run(() =>
                {
                    Dev.Shell("dumpsys battery set ac 0", 6);
                    Dev.Shell("dumpsys battery set usb 0", 6);
                    Dev.Shell("dumpsys battery set wireless 0", 6);
                    if (plugged == "1") Dev.Shell("dumpsys battery set ac 1", 6);
                    else if (plugged == "2") Dev.Shell("dumpsys battery set usb 1", 6);
                    else if (plugged == "4") Dev.Shell("dumpsys battery set wireless 1", 6);
                    Dev.Shell($"dumpsys battery set plugged {plugged}", 6);
                    return "";
                });
                if (outStr == null) return;
                Dlg.Tip("完成", "已设置充电状态");
            };
            btnRefresh.Click += (s, e) => Refresh();
            btnReset.Click += (s, e) =>
            {
                var outStr = MiscToolContents.Run(() => Dev.Shell("dumpsys battery reset", 10));
                if (outStr == null) return;
                Refresh();
                Dlg.Tip("完成", outStr.Trim().Length > 0 ? outStr.Trim() : "已重置");
            };

            MiscToolContents.Defer(Refresh);

            return cp;
        }
    }

    /// <summary>锁屏时间修改。</summary>
    public static class ScreenTimeoutContent
    {
        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            var row = Dlg.InputRow("锁屏时间 (秒)", "例如 30", out var edtSec, "应用", () => { });
            cp.Children.Add(row);
            var tips = MiscToolContents.Hint("读取/修改 screen_off_timeout（单位毫秒）");
            cp.Children.Add(tips);

            var act = new WrapPanel { Spacing = 8, HorizontalAlignment = HorizontalAlignment.Right };
            var btnRefresh = new Button { Content = "刷新当前值", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            act.Children.Add(btnRefresh);
            cp.Children.Add(act);

            void Refresh()
            {
                if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                var outStr = MiscToolContents.Run(() => Dev.Shell("settings get system screen_off_timeout", 6));
                if (outStr == null) return;
                var sec = "";
                if (long.TryParse(outStr.Trim(), out var ms)) sec = (ms / 1000).ToString();
                edtSec.Text = sec;
            }

            MiscToolContents.WireButton(row, 2, () =>
            {
                var v = edtSec.Text.Trim();
                if (v.Length == 0 || !v.All(char.IsDigit)) { Dlg.Tip("提示", "请输入秒数"); return; }
                var sec = long.Parse(v);
                if (sec < 5) { Dlg.Tip("提示", "秒数太小"); return; }
                var ms = sec * 1000;
                var outStr = MiscToolContents.Run(() => Dev.Shell($"settings put system screen_off_timeout {ms}", 8));
                if (outStr == null) return;
                if (outStr.Contains("Permission"))
                { Dlg.Error("失败", "权限不足：部分系统需要 Root 或 Shizuku"); return; }
                Dlg.Tip("完成", "已设置锁屏时间");
            });
            btnRefresh.Click += (s, e) => Refresh();

            MiscToolContents.Defer(Refresh);

            return cp;
        }
    }

    /// <summary>隐藏状态栏图标。</summary>
    public static class StatusBarIconsContent
    {
        private static readonly (string, string)[] Presets =
        {
            ("clock","时间"),("bluetooth","蓝牙"),("location","定位"),("headset","耳机"),("battery","电池"),
            ("wifi","WiFi"),("alarm_clock","闹钟"),("nfc","NFC"),("volume","声音"),("mobile","信号"),
            ("airplane","飞行模式"),("rotate","旋转"),("seconds","时间显示秒")
        };

        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            cp.Children.Add(MiscToolContents.Hint("选择要隐藏的图标："));

            var checks = new Dictionary<string, CheckBox>();
            var wrap = new ItemsWrapGrid { MaximumRowsOrColumns = 4, Margin = new Thickness(0, 0, 0, 8) };
            foreach (var (key, label) in Presets)
            {
                var chk = new CheckBox { Content = label, Tag = key };
                checks[key] = chk;
                wrap.Children.Add(chk);
            }
            cp.Children.Add(wrap);

            var act = new WrapPanel { Spacing = 8, HorizontalAlignment = HorizontalAlignment.Right };
            var btnRefresh = new Button { Content = "刷新当前", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnApply = new Button { Content = "应用", Style = (Style)Application.Current.Resources["AccentButtonStyle"] };
            var btnClear = new Button { Content = "清空(全部显示)", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            act.Children.Add(btnRefresh); act.Children.Add(btnApply); act.Children.Add(btnClear);
            cp.Children.Add(act);

            void Refresh()
            {
                if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                var outStr = MiscToolContents.Run(() => Dev.Shell("settings get secure icon_blacklist", 6));
                if (outStr == null) return;
                var cur = outStr.Trim();
                // 设备可能返回 "null" 表示未设置。
                var hidden = cur.Length == 0 || cur.Equals("null", StringComparison.OrdinalIgnoreCase)
                    ? new HashSet<string>()
                    : cur.Split(',').Select(x => x.Trim()).Where(x => x.Length > 0).ToHashSet();
                foreach (var kv in checks) kv.Value.IsChecked = hidden.Contains(kv.Key);
            }

            // 勾选的图标拼接后一次性写入（Python 的“应用”行为）。
            btnApply.Click += (s, e) =>
            {
                if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                var keys = checks.Where(kv => kv.Value.IsChecked == true).Select(kv => kv.Key);
                var val = string.Join(",", keys);
                var outStr = MiscToolContents.Run(() => Dev.Shell($"settings put secure icon_blacklist '{val}'", 8));
                if (outStr == null) return;
                if (outStr.Contains("Permission"))
                { Dlg.Error("失败", "权限不足：部分系统需要 Root 或 Shizuku"); return; }
                Dlg.Tip("完成", "已应用");
            };
            btnRefresh.Click += (s, e) => Refresh();
            btnClear.Click += (s, e) =>
            {
                if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                var outStr = MiscToolContents.Run(() => Dev.Shell("settings delete secure icon_blacklist", 8));
                if (outStr == null) return;
                Refresh();
                Dlg.Tip("完成", "已清空");
            };

            MiscToolContents.Defer(Refresh);
            return cp;
        }
    }

    /// <summary>字体调节。</summary>
    public static class FontScaleContent
    {
        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            var row = new Grid { ColumnSpacing = 12 };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            // Python 范围 50..500（0.50–5.00）。
            var slider = new Slider { Minimum = 50, Maximum = 500, Value = 100, StepFrequency = 5, MinWidth = 240 };
            var lbl = new TextBlock { Text = "1.00", Style = (Style)Application.Current.Resources["CardSubtitleStyle"], MinWidth = 48, VerticalAlignment = VerticalAlignment.Center, TextAlignment = TextAlignment.Right };
            Grid.SetColumn(lbl, 1);
            row.Children.Add(slider); row.Children.Add(lbl);
            cp.Children.Add(row);
            slider.ValueChanged += (s, e) => lbl.Text = (e.NewValue / 100.0).ToString("F2");

            var act = new WrapPanel { Spacing = 8, HorizontalAlignment = HorizontalAlignment.Right };
            var btnApply = new Button { Content = "应用", Style = (Style)Application.Current.Resources["AccentButtonStyle"] };
            var btnRefresh = new Button { Content = "刷新当前值", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnReset = new Button { Content = "重置", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            act.Children.Add(btnRefresh); act.Children.Add(btnApply); act.Children.Add(btnReset);
            cp.Children.Add(act);

            void Refresh()
            {
                if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                var outStr = MiscToolContents.Run(() => Dev.Shell("settings get system font_scale", 6));
                if (outStr == null) return;
                var cur = outStr.Trim();
                var f = 1.0;
                if (cur.Length > 0) double.TryParse(cur, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out f);
                // Python 回读时钳制到 0.5–5.0。
                var v = (int)Math.Round(Math.Max(0.5, Math.Min(5.0, f)) * 100);
                slider.Value = v;
                lbl.Text = (v / 100.0).ToString("F2");
            }

            btnApply.Click += (s, e) =>
            {
                var f = slider.Value / 100.0;
                if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                // Python 直接以 float 字符串写入（不补零）。
                var text = f.ToString("0.######", System.Globalization.CultureInfo.InvariantCulture);
                var outStr = MiscToolContents.Run(() => Dev.Shell($"settings put system font_scale {text}", 8));
                if (outStr == null) return;
                if (outStr.Contains("Permission", StringComparison.Ordinal))
                { Dlg.Error("失败", "权限不足：部分系统需要 Root 或 Shizuku"); return; }
                Dlg.Tip("完成", $"已设置字体缩放：{f:F2}");
            };
            btnRefresh.Click += (s, e) => Refresh();
            btnReset.Click += (s, e) =>
            {
                if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                var outStr = MiscToolContents.Run(() => Dev.Shell("settings delete system font_scale", 8));
                if (outStr == null) return;
                Refresh();
                Dlg.Tip("完成", "已重置");
            };

            MiscToolContents.Defer(Refresh);
            return cp;
        }
    }

    /// <summary>动画速度。</summary>
    public static class AnimationScaleContent
    {
        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            var keys = new[] { ("window_animation_scale", "窗口缩放"), ("transition_animation_scale", "过渡缩放"), ("animator_duration_scale", "动画时长") };
            var pending = new List<(Slider, string)>();
            var refreshers = new List<Action>();
            foreach (var (key, label) in keys)
            {
                // 标签、滑块、数值、应用按钮同一行，与 Python 版逐项对应。
                var row = new Grid { ColumnSpacing = 10, Margin = new Thickness(0, 2, 0, 2) };
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
                var lbl0 = new TextBlock { Text = label, Style = (Style)Application.Current.Resources["CardSubtitleStyle"], VerticalAlignment = VerticalAlignment.Center, MinWidth = 90 };
                // Python 范围 0..500（0.00–5.00），单步 10。
                var slider = new Slider { Minimum = 0, Maximum = 500, Value = 100, StepFrequency = 10, MinWidth = 220 };
                var lbl = new TextBlock { Text = "1.00", Style = (Style)Application.Current.Resources["CardSubtitleStyle"], MinWidth = 48, VerticalAlignment = VerticalAlignment.Center, TextAlignment = TextAlignment.Right };
                var key1 = key;
                slider.ValueChanged += (s, e) => lbl.Text = (e.NewValue / 100.0).ToString("F2");
                var btnOne = new Button { Content = "应用", Style = (Style)Application.Current.Resources["AccentButtonStyle"] };
                btnOne.Click += (s, e) => ApplyOne(key1, slider.Value / 100.0);
                Grid.SetColumn(lbl0, 0); Grid.SetColumn(slider, 1); Grid.SetColumn(lbl, 2); Grid.SetColumn(btnOne, 3);
                row.Children.Add(lbl0); row.Children.Add(slider); row.Children.Add(lbl); row.Children.Add(btnOne);
                cp.Children.Add(row);
                pending.Add((slider, key));
                refreshers.Add(() => RefreshOne(slider, lbl, key1));
            }

            var act = new WrapPanel { Spacing = 8, HorizontalAlignment = HorizontalAlignment.Right };
            var btnRefresh = new Button { Content = "刷新当前值", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnReset = new Button { Content = "重置", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            act.Children.Add(btnRefresh); act.Children.Add(btnReset);
            cp.Children.Add(act);

            btnRefresh.Click += (s, e) =>
            {
                if (!HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                foreach (var r in refreshers) r();
                Dlg.Tip("完成", "已刷新当前值");
            };
            btnReset.Click += (s, e) =>
            {
                if (!HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                var del = MiscToolContents.Run(() =>
                {
                    Dev.Shell("settings delete global window_animation_scale", 8);
                    Dev.Shell("settings delete global transition_animation_scale", 8);
                    Dev.Shell("settings delete global animator_duration_scale", 8);
                    return "";
                });
                if (del == null) return;
                foreach (var r in refreshers) r();
                Dlg.Tip("完成", "已重置");
            };

            MiscToolContents.Defer(() =>
            {
                if (!HasDevice()) return;
                foreach (var r in refreshers) r();
            });

            return cp;
        }

        private static bool HasDevice()
        {
            try { var (mode, serial) = AdbService.DetectConnectionMode(); return mode == "system" && !string.IsNullOrEmpty(serial); }
            catch { return false; }
        }

        private static void RefreshOne(Slider slider, TextBlock lbl, string key)
        {
            try
            {
                var cur = Dev.Shell($"settings get global {key}", 6).Trim();
                if (!double.TryParse(cur, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var f)) f = 1;
                // Python 回读时钳制到 0.0–5.0 并四舍五入到百分比。
                var v = (int)Math.Round(Math.Max(0.0, Math.Min(5.0, f)) * 100);
                slider.Value = v;
                lbl.Text = (v / 100.0).ToString("F2");
            }
            catch { }
        }

        private static void ApplyOne(string key, double f)
        {
            if (!HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
            if (f < 0 || f > 5.0) { Dlg.Tip("提示", "范围 0-5"); return; }
            var s = f.ToString("0.######", System.Globalization.CultureInfo.InvariantCulture);
            var outStr = MiscToolContents.Run(() => Dev.Shell($"settings put global {key} {s}", 8));
            if (outStr == null) return;
            if (outStr.Contains("Permission", StringComparison.Ordinal))
            {
                Dlg.Error("失败", "权限不足：部分系统需要 Root 或 Shizuku");
                return;
            }
            Dlg.Tip("完成", $"已设置：{f:F2}");
        }
    }

    /// <summary>一键关闭辅助功能。</summary>
    public static class AccessibilityResetContent
    {
        private static readonly string[] Commands =
        {
            "settings put secure accessibility_enabled 0",
            "settings put secure enabled_accessibility_services ''",
            "settings put secure accessibility_display_inversion_enabled 0",
            "settings put secure accessibility_display_daltonizer_enabled 0",
            "settings put secure accessibility_display_magnification_enabled 0",
            "settings put secure high_text_contrast_enabled 0",
            "settings put secure display_inversion_enabled 0",
            "settings put secure accessibility_display_daltonizer 0",
            "settings put secure accessibility_display_daltonizer_enabled 0",
        };

        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            cp.Children.Add(MiscToolContents.Hint("一键执行以下操作（尽力而为）："));
            cp.Children.Add(MiscToolContents.Hint("- 关闭无障碍总开关，并清空 enabled_accessibility_services"));
            cp.Children.Add(MiscToolContents.Hint("- 关闭：内容放大 / 颜色反转 / 色彩校正(色盲) / 高对比度文字"));

            var info = new TextBlock
            {
                Text = "",
                Style = (Style)Application.Current.Resources["CardSubtitleStyle"],
                TextWrapping = TextWrapping.Wrap
            };
            cp.Children.Add(info);

            var act = new WrapPanel { Spacing = 8, HorizontalAlignment = HorizontalAlignment.Right };
            var btnRefresh = new Button { Content = "读取当前状态", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btn = new Button { Content = "一键关闭", Style = (Style)Application.Current.Resources["AccentButtonStyle"] };
            act.Children.Add(btnRefresh); act.Children.Add(btn);
            cp.Children.Add(act);

            void Refresh()
            {
                if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                var en = MiscToolContents.Run(() => Dev.Shell("settings get secure accessibility_enabled", 6));
                var services = MiscToolContents.Run(() => Dev.Shell("settings get secure enabled_accessibility_services", 6));
                var inv = MiscToolContents.Run(() => Dev.Shell("settings get secure accessibility_display_inversion_enabled", 6));
                var dal = MiscToolContents.Run(() => Dev.Shell("settings get secure accessibility_display_daltonizer_enabled", 6));
                var mag = MiscToolContents.Run(() => Dev.Shell("settings get secure accessibility_display_magnification_enabled", 6));
                var hi = MiscToolContents.Run(() => Dev.Shell("settings get secure high_text_contrast_enabled", 6));
                if (en == null || services == null || inv == null || dal == null || mag == null || hi == null) return;
                static string Raw(string v) => v.Trim() is "" or "null" ? "-" : v.Trim();
                var svcText = services.Trim();
                if (svcText.Length == 0 || svcText.Equals("null", StringComparison.OrdinalIgnoreCase)) svcText = "(空)";
                info.Text =
                    $"无障碍开关 {Raw(en)}\n" +
                    $"已启用服务 {svcText}\n" +
                    $"颜色反转: {Raw(inv)}  色彩校正: {Raw(dal)}  内容放大: {Raw(mag)}  高对比度: {Raw(hi)}";
            }

            btn.Click += async (s, e) =>
            {
                if (!await Dlg.Confirm("确认", "确定要关闭全部辅助功能设置吗？\n这可能影响读屏、放大手势、高对比度等无障碍功能。"))
                    return;
                if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                try { info.Text = "正在执行..."; } catch { }
                var permDenied = false;
                var failed = false;
                foreach (var c in Commands)
                {
                    try
                    {
                        var r = Dev.Shell(c, 8) ?? "";
                        if (r.Contains("Permission", StringComparison.Ordinal) ||
                            r.ToLowerInvariant().Contains("denied")) permDenied = true;
                    }
                    catch { failed = true; }
                }
                if (failed) { Dlg.Tip("提示", "部分命令执行失败"); Refresh(); return; }
                if (permDenied) Dlg.Tip("已执行", "部分项目可能权限不足（可尝试 Root/Shizuku）");
                else Dlg.Tip("完成", "已尝试关闭辅助功能");
                Refresh();
            };
            btnRefresh.Click += (s, e) => Refresh();

            MiscToolContents.Defer(Refresh);

            return cp;
        }
    }

    /// <summary>模拟按键。</summary>
    public static class KeySimContent
    {
        private static readonly (string, int)[] Keys =
        {
            ("音量 +", 24),("音量 -", 25),("静音/取消静音", 164),("锁屏/电源键", 26),
            ("返回", 4),("主页", 3),("最近任务", 187),("通知栏", 83)
        };

        public static FrameworkElement Build()
        {
            var cp = MiscToolContents.Root();

            cp.Children.Add(MiscToolContents.Hint("点击按钮即可发送按键事件："));

            var wrap = new ItemsWrapGrid { MaximumRowsOrColumns = 3, Margin = new Thickness(0, 0, 0, 8) };
            foreach (var (label, code) in Keys)
            {
                var btn = new Button
                {
                    Content = label,
                    Style = (Style)Application.Current.Resources["AccentButtonStyle"],
                    MinWidth = 120,
                    Margin = new Thickness(0, 0, 8, 8)
                };
                btn.Click += (s, e) =>
                {
                    if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                    var outStr = MiscToolContents.Run(() => Dev.Shell($"input keyevent {code}", 6));
                    if (outStr == null) return;
                    Dlg.Tip("已发送", $"keyevent {code}");
                };
                wrap.Children.Add(btn);
            }
            cp.Children.Add(wrap);

            var act = new WrapPanel { Spacing = 8, HorizontalAlignment = HorizontalAlignment.Right };
            var btnDataOn = new Button { Content = "数据流量：开启", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            var btnDataOff = new Button { Content = "数据流量：关闭", Style = (Style)Application.Current.Resources["DefaultButtonStyle"] };
            act.Children.Add(btnDataOn); act.Children.Add(btnDataOff);
            cp.Children.Add(act);

            // svc data 只接受 enable / disable。
            void SvcData(bool on)
            {
                if (!MiscToolContents.HasDevice()) { Dlg.Tip("提示", "未检测到设备"); return; }
                var cmd = on ? "svc data enable" : "svc data disable";
                var outStr = MiscToolContents.Run(() => Dev.Shell(cmd, 8));
                if (outStr == null) return;
                if (outStr.Contains("Permission", StringComparison.Ordinal) ||
                    outStr.ToLowerInvariant().Contains("denied"))
                { Dlg.Error("失败", "权限不足：部分系统不允许 shell 控制数据流量"); return; }
                Dlg.Tip("完成", "已尝试切换数据流量");
            }
            btnDataOn.Click += (s, e) => SvcData(true);
            btnDataOff.Click += (s, e) => SvcData(false);

            return cp;
        }
    }
}
