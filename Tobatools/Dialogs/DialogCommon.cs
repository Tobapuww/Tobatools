using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Tobatools.Services;

namespace Tobatools.Dialogs
{
    /// <summary>设备 shell 公共辅助。</summary>
    public static class Dev
    {
        public static string RequireSerial()
        {
            var (mode, serial) = AdbService.DetectConnectionMode();
            if (mode != "system" || string.IsNullOrEmpty(serial))
                throw new InvalidOperationException("请连接设备到系统模式并开启 ADB 调试");
            return serial;
        }

        public static string Shell(string cmd, int timeout = 10)
        {
            var serial = RequireSerial();
            return AdbService.AdbShellSerial(serial, cmd, timeout) ?? "";
        }
    }

    public static class Dlg
    {
        public static XamlRoot? Root;

        public static void Tip(string title, string content)
        {
            if (App.Instance?.MainWin?.ActiveToolPage is { } page)
            {
                page.ShowNotice(title, content, false);
                return;
            }
            if (Root == null) return;
            var dlg = new ContentDialog
            {
                Title = title,
                Content = new TextBlock { Text = content, TextWrapping = TextWrapping.Wrap },
                CloseButtonText = "确定",
                XamlRoot = Root
            };
            _ = dlg.ShowAsync();
        }

        public static void Error(string title, string content)
        {
            if (App.Instance?.MainWin?.ActiveToolPage is { } page)
            {
                page.ShowNotice(title, content, true);
                return;
            }
            if (Root == null) return;
            var dlg = new ContentDialog
            {
                Title = title,
                Content = new TextBlock { Text = content, TextWrapping = TextWrapping.Wrap },
                CloseButtonText = "确定",
                XamlRoot = Root
            };
            _ = dlg.ShowAsync();
        }

        public static async Task<bool> Confirm(string title, string content)
        {
            if (Root == null) return false;
            var dlg = new ContentDialog
            {
                Title = title,
                Content = new TextBlock { Text = content, TextWrapping = TextWrapping.Wrap },
                PrimaryButtonText = "确定",
                CloseButtonText = "取消",
                DefaultButton = ContentDialogButton.Close,
                XamlRoot = Root
            };
            return await dlg.ShowAsync() == ContentDialogResult.Primary;
        }

        /// <summary>构造一个标准弹窗：标题+副标题+卡片内容+底部按钮。</summary>
        public static ContentDialog Build(string title, string subtitle, FrameworkElement content, string okText = "", string cancelText = "关闭")
        {
            var header = new StackPanel { Spacing = 2 };
            header.Children.Add(new TextBlock
            {
                Text = title,
                Style = (Style)Application.Current.Resources["PageTitleStyle"]
            });
            header.Children.Add(new TextBlock
            {
                Text = subtitle,
                Style = (Style)Application.Current.Resources["CardSubtitleStyle"]
            });
            var panel = new StackPanel { Spacing = 14, MinWidth = 560, MaxWidth = 760 };
            panel.Children.Add(header);
            panel.Children.Add(content);
            var dlg = new ContentDialog
            {
                Content = new ScrollViewer { MaxHeight = 720, Content = panel, VerticalScrollBarVisibility = ScrollBarVisibility.Auto },
                XamlRoot = Root
            };
            if (!string.IsNullOrEmpty(okText)) dlg.PrimaryButtonText = okText;
            if (!string.IsNullOrEmpty(cancelText)) dlg.CloseButtonText = cancelText;
            return dlg;
        }

        public static Border Card() => new()
        {
            Style = (Style)Application.Current.Resources["CardBorderStyle"]
        };

        public static StackPanel CardContent()
        {
            var sp = new StackPanel { Spacing = 12, Padding = new Thickness(18, 16, 18, 16) };
            return sp;
        }

        public static TextBlock CardTitle(string text) => new()
        {
            Text = text,
            Style = (Style)Application.Current.Resources["CardTitleStyle"]
        };

        /// <summary>输入行：标签 + 输入框 + 按钮。</summary>
        public static Grid InputRow(string label, string placeholder, out TextBox box, string btnText, Action onBtn)
        {
            var g = new Grid { ColumnSpacing = 8 };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            var lbl = new TextBlock
            {
                Text = label,
                Style = (Style)Application.Current.Resources["CardSubtitleStyle"],
                VerticalAlignment = VerticalAlignment.Center
            };
            box = new TextBox { PlaceholderText = placeholder, Style = (Style)Application.Current.Resources["RoundedTextBoxStyle"] };
            Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(box, label);
            var btn = new Button
            {
                Content = btnText,
                Style = (Style)Application.Current.Resources["DefaultButtonStyle"]
            };
            btn.Click += (s, e) => onBtn();
            Grid.SetColumn(lbl, 0); Grid.SetColumn(box, 1); Grid.SetColumn(btn, 2);
            g.Children.Add(lbl); g.Children.Add(box); g.Children.Add(btn);
            return g;
        }
    }
}
