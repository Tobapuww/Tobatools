using L = Tobatools.Services.LocalizationService;
using System;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Tobatools.Dialogs;
using Tobatools.Services;
using Windows.UI;

namespace Tobatools.Controls
{
    public sealed partial class DeviceBar : UserControl
    {
        public event EventHandler? StateChanged;

        public DeviceBar()
        {
            InitializeComponent();
            RebootTip.Target = BtnReboot;
            DeviceSession.Instance.StateChanged += OnDeviceChanged;
        }

        private void OnDeviceChanged()
        {
            var summary = DeviceSession.Instance.Summary;
            if (summary == null)
            {
                SetState(L.Instance.Get("Pages/Dashboard_051"), L.Instance.Get("Pages/DeviceBar_004"), "#86909c");
                return;
            }
            if (summary.Connected)
            {
                var info = DeviceSession.Instance.Info;
                var name = info?.DisplayName ?? summary.Serial;
                if (string.IsNullOrEmpty(name)) name = summary.Serial;
                SetState(summary.StatusLine, $"{name}  ·  {summary.Serial}", summary.StatusColor);
            }
            else
            {
                SetState(summary.StatusLine, summary.StatusLine, summary.StatusColor);
            }
            StateChanged?.Invoke(this, EventArgs.Empty);
        }

        private void SetState(string main, string sub, string colorHex)
        {
            TxtStatus.Text = main;
            TxtSerial.Text = sub;
            try { StatusDot.Fill = new SolidColorBrush(ParseColor(colorHex)); } catch { }
        }

        private static Color ParseColor(string hex)
        {
            hex = hex.TrimStart('#');
            if (hex.Length == 6)
                return Color.FromArgb(255, Convert.ToByte(hex.Substring(0, 2), 16), Convert.ToByte(hex.Substring(2, 2), 16), Convert.ToByte(hex.Substring(4, 2), 16));
            return Colors.Gray;
        }

        private async void OnConnectClick(object sender, RoutedEventArgs e)
        {
            var dlg = new WirelessConnectDialog { XamlRoot = XamlRoot };
            var result = await dlg.ShowAsync();
            if (result == ContentDialogResult.Primary)
            {
                DeviceSession.Instance.RefreshNow();
            }
        }

        private void OnRefreshClick(object sender, RoutedEventArgs e)
        {
            DeviceSession.Instance.RefreshNow();
        }

        private async void OnRebootClick(object sender, RoutedEventArgs e)
        {
            var menu = new MenuFlyout();
            menu.Items.Add(MenuItem(L.Instance.Get("Pages/DeviceBar_005"), "system"));
            menu.Items.Add(new MenuFlyoutSeparator());
            menu.Items.Add(MenuItem(L.Instance.Get("Pages/DeviceBar_006"), "recovery"));
            menu.Items.Add(MenuItem(L.Instance.Get("Pages/DeviceBar_007"), "bootloader"));
            menu.Items.Add(MenuItem(L.Instance.Get("Pages/DeviceBar_008"), "fastbootd"));
            menu.Items.Add(MenuItem(L.Instance.Get("Pages/DeviceBar_009"), "edl"));
            menu.ShowAt(BtnReboot, new Windows.Foundation.Point(0, BtnReboot.ActualHeight));

            foreach (var it in menu.Items.OfType<MenuFlyoutItem>())
            {
                var target = (string)it.Tag;
                it.Click += async (s2, e2) =>
                {
                    var (ok, msg) = await Task.Run(() => AdbService.RebootTo(target));
                    DeviceSession.Instance.RefreshNow();
                    RebootTip.Title = ok ? L.Instance.Get("Pages/Dashboard_065") : L.Instance.Get("Pages/Dashboard_066");
                    RebootTip.Subtitle = msg;
                    RebootTip.IsOpen = true;
                };
            }
        }

        private static MenuFlyoutItem MenuItem(string text, string tag)
        {
            return new MenuFlyoutItem { Text = text, Tag = tag };
        }
    }
}
