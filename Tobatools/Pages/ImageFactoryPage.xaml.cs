using L = Tobatools.Services.LocalizationService;
using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Tobatools.Dialogs;

namespace Tobatools.Pages
{
    public sealed partial class ImageFactoryPage : Page
    {
        public ImageFactoryPage()
        {
            InitializeComponent();
            Loaded += OnLoaded;
        }

        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            Dlg.Root = XamlRoot;
            if (FirmwarePanel.Children.Count == 0) BuildEntries();
            Loaded -= OnLoaded;
        }

        private void AddEntry(StackPanel panel, string title, string subtitle, string glyph, Action onClick)
        {
            var btn = new Button
            {
                Style = (Style)Application.Current.Resources["ListCardButtonStyle"],
                HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Padding = new Thickness(16, 12, 16, 12)
            };
            var g = new Grid { ColumnSpacing = 12 };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            g.Children.Add(new FontIcon { Glyph = glyph, FontSize = 18, VerticalAlignment = VerticalAlignment.Center });
            var text = new StackPanel { Spacing = 2, VerticalAlignment = VerticalAlignment.Center };
            text.Children.Add(new TextBlock { Text = title, Style = (Style)Application.Current.Resources["BodyTextStyle"], FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
            text.Children.Add(new TextBlock { Text = subtitle, Style = (Style)Application.Current.Resources["CaptionTextStyle"], TextTrimming = TextTrimming.CharacterEllipsis });
            Grid.SetColumn(text, 1);
            g.Children.Add(text);
            var arrow = new FontIcon { Glyph = "\uE76C", FontSize = 12, VerticalAlignment = VerticalAlignment.Center };
            Grid.SetColumn(arrow, 2);
            g.Children.Add(arrow);
            btn.Content = g;
            Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(btn, title);
            btn.Click += (s, e) => onClick();
            panel.Children.Add(btn);
        }

        private void BuildEntries()
        {
            AddEntry(FirmwarePanel, L.Instance.Get("Pages/ImageFactory_015"), L.Instance.Get("Pages/ImageFactory_016"), "\uE8A5", () => MainWindow.OpenImageTool("payload"));
            AddEntry(FirmwarePanel, L.Instance.Get("Pages/ImageFactory_017"), L.Instance.Get("Pages/ImageFactory_018"), "\uE8A5", () => MainWindow.OpenImageTool("ofp"));

            AddEntry(SuperPanel, L.Instance.Get("Pages/ImageFactory_019"), L.Instance.Get("Pages/ImageFactory_020"), "\uE8B7", () => MainWindow.OpenImageTool("super"));

            AddEntry(DtboPanel, L.Instance.Get("Pages/ImageFactory_021"), L.Instance.Get("Pages/ImageFactory_022"), "\uE8B7", () => MainWindow.OpenImageTool("dtbo"));

            AddEntry(FsPanel, L.Instance.Get("Pages/ImageFactory_023"), L.Instance.Get("Pages/ImageFactory_024"), "\uE8B7", () => MainWindow.OpenImageTool("partitionfs"));

            AddEntry(BootPanel, L.Instance.Get("Pages/ImageFactory_025"), L.Instance.Get("Pages/ImageFactory_026"), "\uE8B7", () => MainWindow.OpenImageTool("boot"));

            AddEntry(DatBrPanel, L.Instance.Get("Pages/ImageFactory_027"), L.Instance.Get("Pages/ImageFactory_028"), "\uE8B7", () => MainWindow.OpenImageTool("datbr"));
        }
    }
}
