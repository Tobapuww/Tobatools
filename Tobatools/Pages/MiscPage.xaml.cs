using L = Tobatools.Services.LocalizationService;
using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Tobatools.Dialogs;

namespace Tobatools.Pages
{
    public sealed partial class MiscPage : Page
    {
        public MiscPage()
        {
            InitializeComponent();
            Loaded += OnLoaded;
        }

        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            Dlg.Root = XamlRoot;
            if (CommonPanel.Children.Count == 0) BuildEntries();
            Loaded -= OnLoaded;
        }

        private void AddEntry(StackPanel panel, string id, string title, string subtitle, string glyph)
        {
            var btn = new Button
            {
                Style = (Style)Application.Current.Resources["ListCardButtonStyle"],
                HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Padding = new Thickness(14, 11, 14, 11)
            };
            var g = new Grid { ColumnSpacing = 12 };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            g.Children.Add(new Border
            {
                Width = 34,
                Height = 34,
                CornerRadius = new CornerRadius(8),
                Background = (Brush)Application.Current.Resources["SubtleFillColorSecondaryBrush"],
                Child = new FontIcon { Glyph = glyph, FontSize = 15, VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Center }
            });
            var text = new StackPanel { Spacing = 2, VerticalAlignment = VerticalAlignment.Center };
            text.Children.Add(new TextBlock { Text = title, Style = (Style)Application.Current.Resources["CardSubtitleStyle"], FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
            text.Children.Add(new TextBlock { Text = subtitle, Style = (Style)Application.Current.Resources["CaptionTextStyle"], TextTrimming = TextTrimming.CharacterEllipsis });
            Grid.SetColumn(text, 1);
            g.Children.Add(text);
            var arrow = new FontIcon { Glyph = "\uE76C", FontSize = 12, VerticalAlignment = VerticalAlignment.Center, Foreground = (Brush)Application.Current.Resources["TextFillColorTertiaryBrush"] };
            Grid.SetColumn(arrow, 2);
            g.Children.Add(arrow);
            btn.Content = g;
            Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(btn, title);
            Microsoft.UI.Xaml.Automation.AutomationProperties.SetAutomationId(btn, "MiscTool_" + id);
            btn.Click += (s, e) => MainWindow.OpenMiscTool(id);
            panel.Children.Add(btn);
        }

        private void BuildEntries()
        {
            // 常用工具
            AddEntry(CommonPanel, "partitionflash", L.Instance.Get("Pages/Misc_008"), L.Instance.Get("Pages/Misc_009"), "\uE8B7");
            AddEntry(CommonPanel, "payload", L.Instance.Get("Pages/Misc_010"), L.Instance.Get("Pages/ImageFactory_016"), "\uE8A5");
            AddEntry(CommonPanel, "ofp", L.Instance.Get("Pages/Misc_011"), L.Instance.Get("Pages/ImageFactory_018"), "\uE8A5");

            // 高级操作
            AddEntry(AdvancedPanel, "unbrick", L.Instance.Get("Pages/Misc_012"), L.Instance.Get("Pages/Misc_013"), "\uE7FB");
            AddEntry(AdvancedPanel, "modules", L.Instance.Get("Pages/Misc_014"), L.Instance.Get("Pages/Misc_015"), "\uE7F4");
            AddEntry(AdvancedPanel, "adbterminal", L.Instance.Get("Pages/Misc_016"), L.Instance.Get("Pages/Misc_017"), "\uE756");
            AddEntry(AdvancedPanel, "runscript", L.Instance.Get("Pages/Misc_018"), L.Instance.Get("Pages/Misc_019"), "\uE756");
            AddEntry(AdvancedPanel, "configcheck", L.Instance.Get("Pages/Misc_020"), L.Instance.Get("Pages/Misc_021"), "\uE8A5");

            // 模拟控制
            AddEntry(SimPanel, "display", L.Instance.Get("Pages/Misc_022"), L.Instance.Get("Pages/Misc_023"), "\uE7F4");
            AddEntry(SimPanel, "battery", L.Instance.Get("Pages/Misc_024"), L.Instance.Get("Pages/Misc_025"), "\uE9EC");
            AddEntry(SimPanel, "timeout", L.Instance.Get("Pages/Misc_026"), L.Instance.Get("Pages/Misc_027"), "\uE823");
            AddEntry(SimPanel, "statusicons", L.Instance.Get("Pages/Misc_028"), L.Instance.Get("Pages/Misc_029"), "\uE71B");
            AddEntry(SimPanel, "fontscale", L.Instance.Get("Pages/Misc_030"), L.Instance.Get("Pages/Misc_031"), "\uE8D2");
            AddEntry(SimPanel, "animscale", L.Instance.Get("Pages/Misc_032"), L.Instance.Get("Pages/Misc_033"), "\uE768");
            AddEntry(SimPanel, "a11yreset", L.Instance.Get("Pages/Misc_034"), L.Instance.Get("Pages/Misc_035"), "\uE74D");
            AddEntry(SimPanel, "keysim", L.Instance.Get("Pages/Misc_036"), L.Instance.Get("Pages/Misc_037"), "\uE765");
        }
    }
}
