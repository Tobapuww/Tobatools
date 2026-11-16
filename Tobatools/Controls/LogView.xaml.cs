using L = Tobatools.Services.LocalizationService;
using System;
using System.Collections.Generic;
using Microsoft.UI;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace Tobatools.Controls
{
    /// <summary>
    /// 精美的日志组件：普通日志 + 步骤化日志（开始输出 "xxx... "，完成时追加 OK / Error）。
    /// 对应 Python 的 app/components/log_widget.py。
    /// </summary>
    public sealed partial class LogView : UserControl
    {
        private readonly Dictionary<string, TextBlock> _stepBlocks = new();


        public LogView()
        {
            InitializeComponent();
        }

        public void ClearLog()
        {
            if (!DispatcherQueue.HasThreadAccess)
            {
                DispatcherQueue.TryEnqueue(ClearLog);
                return;
            }
            LinesPanel.Children.Clear();
            _stepBlocks.Clear();
            EmptyHint.Visibility = Visibility.Visible;
        }

        public void AppendLog(string text, string? color = null, bool bold = false)
        {
            if (!DispatcherQueue.HasThreadAccess)
            {
                DispatcherQueue.TryEnqueue(() => AppendLog(text, color, bold));
                return;
            }
            var s = text ?? "";
            const int maxLen = 4000;
            if (s.Length > maxLen) s = s[..maxLen] + " ... [truncated]";

            var tb = new TextBlock
            {
                Text = s,
                Style = (Style)Application.Current.Resources["LogTextStyle"],
            };
            if (color != null)
            {
                tb.Foreground = new SolidColorBrush(ParseColor(color));
            }
            if (bold) tb.FontWeight = FontWeights.SemiBold;
            LinesPanel.Children.Add(tb);
            EmptyHint.Visibility = Visibility.Collapsed;
            ScrollToEnd();
        }

        public void StartStep(string stepId, string text)
        {
            if (!DispatcherQueue.HasThreadAccess)
            {
                DispatcherQueue.TryEnqueue(() => StartStep(stepId, text));
                return;
            }
            var tb = new TextBlock
            {
                Text = $"{text}... ",
                Style = (Style)Application.Current.Resources["LogStepTextStyle"],
            };
            LinesPanel.Children.Add(tb);
            _stepBlocks[stepId] = tb;
            EmptyHint.Visibility = Visibility.Collapsed;
            ScrollToEnd();
        }

        public void FinishStep(string stepId, bool success, string detail = "")
        {
            if (!DispatcherQueue.HasThreadAccess)
            {
                DispatcherQueue.TryEnqueue(() => FinishStep(stepId, success, detail));
                return;
            }
            if (!_stepBlocks.TryGetValue(stepId, out var tb)) return;
            var status = success ? "OK" : "Error";
            var sb = tb.Text ?? "";
            tb.Text = sb + status + (string.IsNullOrEmpty(detail) ? "" : $" ({detail})");
            tb.Style = (Style)Application.Current.Resources[success ? "LogSuccessTextStyle" : "LogErrorTextStyle"];
            _stepBlocks.Remove(stepId);
            ScrollToEnd();
        }

        private void ScrollToEnd()
        {
            if (ScrollView == null) return;
            ScrollView.ChangeView(null, ScrollView.ScrollableHeight, null, true);
        }

        private static Windows.UI.Color ParseColor(string hex)
        {
            try
            {
                hex = hex.TrimStart('#');
                if (hex.Length == 6)
                    return Color.FromArgb(255, Convert.ToByte(hex.Substring(0, 2), 16), Convert.ToByte(hex.Substring(2, 2), 16), Convert.ToByte(hex.Substring(4, 2), 16));
                if (hex.Length == 8)
                    return Color.FromArgb(Convert.ToByte(hex.Substring(0, 2), 16), Convert.ToByte(hex.Substring(2, 2), 16), Convert.ToByte(hex.Substring(4, 2), 16), Convert.ToByte(hex.Substring(6, 2), 16));
            }
            catch { }
            return Colors.Black;
        }
    }
}
