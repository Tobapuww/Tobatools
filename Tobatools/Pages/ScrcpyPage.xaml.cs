using L = Tobatools.Services.LocalizationService;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Tobatools.Services;

namespace Tobatools.Pages
{
    public sealed partial class ScrcpyPage : Page
    {
        private Process? _proc;

        public ScrcpyPage()
        {
            InitializeComponent();
            Loaded += OnLoaded;
        }

        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            ComboMaxSize.Items.Add(L.Instance.Get("Pages/Scrcpy_032")); ComboMaxSize.Items.Add("720"); ComboMaxSize.Items.Add("1080");
            ComboMaxSize.Items.Add("1440"); ComboMaxSize.Items.Add("2160"); ComboMaxSize.Items.Add("4320");
            ComboMaxSize.SelectedIndex = 0;

            ComboFps.Items.Add(L.Instance.Get("Pages/Scrcpy_032")); ComboFps.Items.Add("30"); ComboFps.Items.Add("60"); ComboFps.Items.Add("90");
            ComboFps.Items.Add("120"); ComboFps.Items.Add("144"); ComboFps.Items.Add("165");
            ComboFps.SelectedIndex = 0;

            ComboBitrate.Items.Add(L.Instance.Get("Pages/Scrcpy_032")); ComboBitrate.Items.Add("4M"); ComboBitrate.Items.Add("6M");
            ComboBitrate.Items.Add("8M"); ComboBitrate.Items.Add("12M"); ComboBitrate.Items.Add("20M");
            ComboBitrate.Items.Add("30M"); ComboBitrate.Items.Add("50M");
            ComboBitrate.SelectedIndex = 0;

            ComboVbuf.Items.Add(L.Instance.Get("Pages/Scrcpy_032")); ComboVbuf.Items.Add("50"); ComboVbuf.Items.Add("100");
            ComboVbuf.Items.Add("150"); ComboVbuf.Items.Add("200"); ComboVbuf.Items.Add("300");
            ComboVbuf.Items.Add("500"); ComboVbuf.Items.Add("1000");
            ComboVbuf.SelectedIndex = 0;

            ComboAbuf.Items.Add(L.Instance.Get("Pages/Scrcpy_032")); ComboAbuf.Items.Add("50"); ComboAbuf.Items.Add("100");
            ComboAbuf.Items.Add("150"); ComboAbuf.Items.Add("200"); ComboAbuf.Items.Add("300");
            ComboAbuf.Items.Add("500"); ComboAbuf.Items.Add("1000");
            ComboAbuf.SelectedIndex = 0;

            Loaded -= OnLoaded;
        }

        private static string Selected(ComboBox c) => c.SelectedItem?.ToString()?.Trim() ?? L.Instance.Get("Pages/Scrcpy_032");

        private List<string> BuildCommand(string serial)
        {
            var cmd = new List<string> { ExternalTools.Scrcpy };
            var ms = Selected(ComboMaxSize);
            if (ms != L.Instance.Get("Pages/Scrcpy_032")) cmd.AddRange(new[] { "--max-size", ms });

            var fpsTxt = Selected(ComboFps);
            if (fpsTxt != L.Instance.Get("Pages/Scrcpy_032") && int.TryParse(fpsTxt, out var fps))
            {
                cmd.AddRange(new[] { "--max-fps", Math.Min(fps, 165).ToString() });
            }

            var br = Selected(ComboBitrate);
            if (br != L.Instance.Get("Pages/Scrcpy_032")) cmd.AddRange(new[] { "--video-bit-rate", br });

            var vbuf = Selected(ComboVbuf);
            if (vbuf != L.Instance.Get("Pages/Scrcpy_032")) cmd.AddRange(new[] { "--video-buffer", vbuf });
            var abuf = Selected(ComboAbuf);
            if (abuf != L.Instance.Get("Pages/Scrcpy_032")) cmd.AddRange(new[] { "--audio-buffer", abuf });

            if (ChkAudio.IsChecked != true) cmd.Add("--no-audio");
            if (ChkFullscreen.IsChecked == true) cmd.Add("--fullscreen");
            if (ChkBorderless.IsChecked == true) cmd.Add("--window-borderless");
            if (ChkAlwaysOnTop.IsChecked == true) cmd.Add("--always-on-top");
            if (ChkDisableScreensaver.IsChecked == true) cmd.Add("--disable-screensaver");
            if (ChkStayAwake.IsChecked == true) cmd.Add("--stay-awake");
            if (ChkTurnScreenOff.IsChecked == true) cmd.Add("--turn-screen-off");
            if (ChkShowTouches.IsChecked == true) cmd.Add("--show-touches");
            if (ChkClipSync.IsChecked != true) cmd.Add("--no-clipboard-autosync");
            if (ChkLegacyPaste.IsChecked == true) cmd.Add("--legacy-paste");
            if (ChkForwardAllClicks.IsChecked == true) cmd.Add("--forward-all-clicks");
            if (ChkPrintFps.IsChecked == true) cmd.Add("--print-fps");
            return cmd;
        }

        private async void OnStart(object sender, RoutedEventArgs e)
        {
            if (_proc != null && !_proc.HasExited)
            {
                ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Get("Pages/Scrcpy_033"));
                return;
            }

            var serial = await SelectDeviceSerialAsync();
            if (string.IsNullOrEmpty(serial)) return;

            var cmd = BuildCommand(serial);
            cmd.Insert(1, "-s");
            cmd.Insert(2, serial);

            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = cmd[0],
                    UseShellExecute = true,
                    WorkingDirectory = AppPaths.BinDir,
                };
                for (int i = 1; i < cmd.Count; i++) psi.ArgumentList.Add(cmd[i]);
                _proc = Process.Start(psi);
                ShowTip(L.Instance.Get("Pages/Scrcpy_034"), L.Instance.Get("Pages/Scrcpy_035"));
                BtnStart.IsEnabled = false;
                BtnStop.IsEnabled = true;
            }
            catch (System.IO.FileNotFoundException)
            {
                ShowTip(L.Instance.Get("Pages/Scrcpy_036"), L.Instance.Get("Pages/Scrcpy_037"));
            }
            catch (Exception ex)
            {
                ShowTip(L.Instance.Get("Pages/Scrcpy_036"), L.Instance.Format("Pages/Scrcpy_038", ex.Message));
            }
        }

        private void OnStop(object sender, RoutedEventArgs e)
        {
            try
            {
                if (_proc != null && !_proc.HasExited)
                {
                    _proc.Kill(entireProcessTree: true);
                    ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Get("Pages/Scrcpy_039"));
                }
            }
            catch (Exception ex)
            {
                ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Format("Pages/Scrcpy_040", ex.Message));
            }
            finally
            {
                _proc = null;
                BtnStart.IsEnabled = true;
                BtnStop.IsEnabled = false;
            }
        }

        private async Task<string?> SelectDeviceSerialAsync()
        {
            var devices = await Task.Run(() => AdbService.ListDevices());
            if (devices.Count == 0)
            {
                ShowTip(L.Instance.Get("Pages/Root_030"), L.Instance.Get("Pages/Scrcpy_041"));
                return null;
            }
            if (devices.Count == 1) return devices[0];

            // 多个设备：弹出选择框
            var panel = new StackPanel { Spacing = 10 };
            panel.Children.Add(new TextBlock { Text = L.Instance.Get("Pages/Scrcpy_042"), TextWrapping = TextWrapping.Wrap });
            var combo = new ComboBox { MinWidth = 320, HorizontalAlignment = HorizontalAlignment.Stretch };
            foreach (var d in devices)
            {
                var model = "";
                try { model = (AdbService.AdbShellSerial(d, "getprop ro.product.model", 5) ?? "").Trim(); } catch { }
                combo.Items.Add(string.IsNullOrEmpty(model) ? d : $"{d}  ({model})");
            }
            combo.SelectedIndex = 0;
            panel.Children.Add(combo);

            var dlg = new ContentDialog
            {
                Title = L.Instance.Get("Pages/Scrcpy_043"),
                Content = panel,
                PrimaryButtonText = L.Instance.Get("Pages/Dashboard_070"),
                CloseButtonText = L.Instance.Get("Pages/Scrcpy_044"),
                DefaultButton = ContentDialogButton.Primary,
                XamlRoot = XamlRoot
            };
            var r = await dlg.ShowAsync();
            if (r != ContentDialogResult.Primary || combo.SelectedIndex < 0) return null;
            return devices[combo.SelectedIndex];
        }

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
