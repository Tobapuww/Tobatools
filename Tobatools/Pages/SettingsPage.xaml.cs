using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Tobatools.Services;
using Windows.Storage.Pickers;

namespace Tobatools.Pages
{
    public sealed partial class SettingsPage : Page
    {
        // 版本号统一从程序集读取，避免与 csproj 的 <Version> 不一致。
        private static readonly string VersionString = GetAssemblyVersion();

        private static string GetAssemblyVersion()
        {
            try
            {
                var asm = typeof(SettingsPage).Assembly;
                var info = System.Reflection.CustomAttributeExtensions
                    .GetCustomAttribute<System.Reflection.AssemblyInformationalVersionAttribute>(asm);
                if (info?.InformationalVersion is string iv && iv.Length > 0)
                {
                    // 去掉 SourceLink 追加的 "+<commit>" 部分
                    var plus = iv.IndexOf('+');
                    return plus > 0 ? iv.Substring(0, plus) : iv;
                }
                var v = asm.GetName().Version;
                return v == null ? "2.0.1" : $"{v.Major}.{v.Minor}.{v.Build}";
            }
            catch
            {
                return "2.0.1";
            }
        }
        private AppearanceService? _appearance;
        private bool _isInitializing = true;
        private bool _updatingAppearance;

        private string[] _themeKeys = { "system", "light", "dark" };
        private string[] _langCodes = {
            LocalizationService.LangSystem,
            LocalizationService.LangZhCN,
            LocalizationService.LangEnUS,
            LocalizationService.LangRuRU,
        };

        public SettingsPage()
        {
            InitializeComponent();
            Loaded += OnLoaded;
            Unloaded += OnUnloaded;
        }

        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            _isInitializing = true;
            try
            {
                ApplyLocalizedTexts();

                // 主题
                if (ComboTheme.Items.Count == 0)
                {
                    var loc = LocalizationService.Instance;
                    ComboTheme.Items.Add(loc.Get("SettingsThemeSystem"));
                    ComboTheme.Items.Add(loc.Get("SettingsThemeLight"));
                    ComboTheme.Items.Add(loc.Get("SettingsThemeDark"));
                }
                var mode = SettingsService.Instance.Get("theme/mode", "system");
                ComboTheme.SelectedIndex = mode switch
                {
                    "light" => 1,
                    "dark" => 2,
                    _ => 0
                };

                // 语言
                if (ComboLanguage.Items.Count == 0)
                {
                    var loc = LocalizationService.Instance;
                    ComboLanguage.Items.Add(loc.Get("SettingsLanguageSystem"));
                    ComboLanguage.Items.Add(loc.Get("SettingsLanguageZhCN"));
                    ComboLanguage.Items.Add(loc.Get("SettingsLanguageEnUS"));
                    ComboLanguage.Items.Add(loc.Get("SettingsLanguageRuRU"));
                }
                var curLang = LocalizationService.Instance.CurrentLanguageCode;
                ComboLanguage.SelectedIndex = Math.Max(0, Array.IndexOf(_langCodes, curLang));
                InfoBarRestart.IsOpen = LocalizationService.Instance.RestartRequired;

                // 下载
                var dl = SettingsService.Instance.Get("download/dir", "");
                if (string.IsNullOrEmpty(dl)) dl = AppPaths.DefaultDownloadsDir;
                TxtDownloadDir.Text = dl;
                TxtVersion.Text = LocalizationService.Instance.Format("SettingsVersionFormat", VersionString);

                // 外观
                if (_appearance != null) _appearance.Changed -= OnAppearanceChanged;
                _appearance = App.Instance?.MainWin?.Appearance;
                if (_appearance != null) _appearance.Changed += OnAppearanceChanged;
                RefreshAppearance();
            }
            finally
            {
                _isInitializing = false;
            }
        }

        private void OnUnloaded(object sender, RoutedEventArgs e)
        {
            if (_appearance != null) _appearance.Changed -= OnAppearanceChanged;
            _appearance = null;
        }

        private void ApplyLocalizedTexts()
        {
            var loc = LocalizationService.Instance;
            PageTitleHeader.Title = loc.Get("SettingsTitle");
            PageTitleHeader.Subtitle = loc.Get("SettingsSubtitle");

            TextAppearanceTitle.Text = loc.Get("SettingsAppearance");
            TextAppearanceDesc.Text = loc.Get("SettingsAppearanceDesc");
            ComboTheme.Header = loc.Get("SettingsTheme");
            TextMaterialNote.Text = loc.Get("SettingsMaterialNote");
            ToggleLiquidGlass.Header = loc.Get("SettingsLiquidGlass");
            SliderGlassBlur.Header = loc.Get("SettingsGlassBlur");
            TxtMaterialStatus.Text = loc.Get("SettingsMaterialLoading");

            TextLanguageTitle.Text = loc.Get("SettingsLanguage");
            TextLanguageDesc.Text = loc.Get("SettingsLanguageDesc");
            ComboLanguage.Header = loc.Get("SettingsLanguage");
            TextRestartHint.Text = loc.Get("SettingsLanguageRestart");


            TextDownloadTitle.Text = loc.Get("SettingsDownload");
            TextDownloadDesc.Text = loc.Get("SettingsDownloadDesc");
            TxtDownloadDir.Header = loc.Get("SettingsDownloadDir");
            BtnPickDownloadDir.Content = loc.Get("CommonBrowse");

            TextAboutTitle.Text = loc.Get("SettingsAbout");
            TextAboutApp.Text = loc.Get("SettingsAboutApp");
            TextAboutView.Text = loc.Get("CommonView");
            TextCheckUpdate.Text = loc.Get("SettingsCheckUpdate");
            TextCheckUpdateDesc.Text = loc.Get("SettingsCheckUpdateDesc");
            TextCheckUpdateBtn.Text = loc.Get("CommonCheck");
            TextWebsite.Text = loc.Get("SettingsWebsite");
            TextWebsiteBtn.Text = loc.Get("CommonVisit");
            TextQQGroup.Text = loc.Get("SettingsQQGroup");
            TextQQGroupBtn.Text = loc.Get("CommonJoin");
            TextTelegram.Text = loc.Get("SettingsTelegram");
            TextTelegramDesc.Text = loc.Get("SettingsTelegramDesc");
            TextTelegramBtn.Text = loc.Get("CommonJoin");
        }

        private void OnAppearanceChanged(object? sender, EventArgs e) => RefreshAppearance();

        private void RefreshAppearance()
        {
            _updatingAppearance = true;
            try
            {
                var loc = LocalizationService.Instance;
                ToggleLiquidGlass.IsEnabled = _appearance != null;
                ToggleLiquidGlass.IsOn = _appearance?.GlassEnabled ?? false;
                SliderGlassBlur.Value = _appearance?.BlurAmount ?? 24;
                SliderGlassBlur.IsEnabled = _appearance is { GlassEnabled: true, EffectsAvailable: true };
                TxtGlassBlur.Text = $"{_appearance?.BlurAmount ?? 24} DIP";
                TxtMaterialStatus.Text = _appearance?.StatusText ?? loc.Get("SettingsMaterialUnavailable");
            }
            finally
            {
                _updatingAppearance = false;
            }
        }

        private void OnLiquidGlassToggled(object sender, RoutedEventArgs e)
        {
            if (_isInitializing || _updatingAppearance || _appearance == null) return;
            _appearance.SetGlassEnabled(ToggleLiquidGlass.IsOn);
            RefreshAppearance();
        }

        private void OnGlassBlurChanged(object sender, Microsoft.UI.Xaml.Controls.Primitives.RangeBaseValueChangedEventArgs e)
        {
            if (_isInitializing || _updatingAppearance || _appearance == null || !SliderGlassBlur.IsEnabled) return;
            _appearance.SetBlurAmount((int)Math.Round(e.NewValue));
            RefreshAppearance();
        }

        private void OnThemeChanged(object sender, SelectionChangedEventArgs e)
        {
            if (_isInitializing || ComboTheme.SelectedIndex < 0) return;
            var mode = _themeKeys[ComboTheme.SelectedIndex];
            SettingsService.Instance.Set("theme/mode", mode);
            App.ApplyTheme(mode);
        }

        private void OnLanguageChanged(object sender, SelectionChangedEventArgs e)
        {
            if (_isInitializing || ComboLanguage.SelectedIndex < 0) return;
            var code = _langCodes[ComboLanguage.SelectedIndex];
            LocalizationService.Instance.SetLanguage(code);
            InfoBarRestart.IsOpen = LocalizationService.Instance.RestartRequired;
        }

        private async void OnPickDownloadDir(object sender, RoutedEventArgs e)
        {
            try
            {
                var picker = new FolderPicker();
                picker.FileTypeFilter.Add("*");
                var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Instance?.MainWin);
                WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
                var folder = await picker.PickSingleFolderAsync();
                if (folder != null)
                {
                    SettingsService.Instance.Set("download/dir", folder.Path);
                    TxtDownloadDir.Text = folder.Path;
                }
            }
            catch { }
        }

        private void OnAbout(object sender, RoutedEventArgs e)
        {
            var loc = LocalizationService.Instance;
            var dlg = new ContentDialog
            {
                Title = loc.Get("SettingsAbout"),
                Content = new ScrollViewer
                {
                    MaxHeight = 360,
                    Content = new TextBlock
                    {
                        Text = loc.Get("SettingsAboutText"),
                        TextWrapping = Microsoft.UI.Xaml.TextWrapping.Wrap,
                        FontFamily = (Microsoft.UI.Xaml.Media.FontFamily)Application.Current.Resources["AppFont"],
                        LineHeight = 20
                    }
                },
                CloseButtonText = loc.Get("CommonOK"),
                XamlRoot = XamlRoot
            };
            _ = dlg.ShowAsync();
        }

        private async void OnCheckUpdate(object sender, RoutedEventArgs e)
        {
            var loc = LocalizationService.Instance;
            if (AppPaths.IsStoreDistribution)
            {
                ShowInfo(loc.Get("SettingsStoreVersion"), loc.Get("SettingsStoreUpdateHint"));
                return;
            }
            var url = SettingsService.Instance.UpdateUrl;
            ShowInfo(loc.Get("SettingsCheckUpdate"), loc.Get("SettingsUpdateChecking"));
            try
            {
                var (info, err) = await Task.Run(() => FetchUpdate(url));
                if (err != null || info == null || !info.ContainsKey("version"))
                {
                    ShowInfo(loc.Get("SettingsUpdateFailed"), err ?? loc.Get("SettingsUpdateMissing"));
                    return;
                }
                var latest = (info["version"] ?? "").Trim();
                var notes = info.TryGetValue("notes", out var n) ? n ?? "" : "";
                var download = info.TryGetValue("url", out var d) ? d ?? "" : "";
                var cur = VersionString;
                if (!string.IsNullOrEmpty(latest) && string.CompareOrdinal(latest, cur) > 0)
                {
                    var msg = loc.Format("SettingsUpdateNewVersion", latest, cur);
                    if (!string.IsNullOrEmpty(notes)) msg += "\n\n" + loc.Get("SettingsUpdateNotes") + "\n" + notes;
                    var box = new ContentDialog
                    {
                        Title = loc.Get("SettingsUpdateAvailable"),
                        Content = new TextBlock { Text = msg, TextWrapping = Microsoft.UI.Xaml.TextWrapping.Wrap },
                        PrimaryButtonText = loc.Get("CommonOK"),
                        CloseButtonText = loc.Get("CommonCancel"),
                        DefaultButton = ContentDialogButton.Primary,
                        XamlRoot = XamlRoot
                    };
                    var r = await box.ShowAsync();
                    if (r == ContentDialogResult.Primary && !string.IsNullOrEmpty(download) && !AppPaths.IsStoreDistribution)
                    {
                        try { Process.Start(new ProcessStartInfo(download) { UseShellExecute = true }); } catch { }
                    }
                }
                else
                {
                    ShowInfo(loc.Get("SettingsUpdateLatest"), loc.Format("SettingsUpdateCurrent", cur));
                }
            }
            catch (Exception ex)
            {
                ShowInfo(loc.Get("SettingsUpdateFailed"), ex.Message);
            }
        }

        private static (Dictionary<string, string>? Info, string? Error) FetchUpdate(string url)
        {
            try
            {
                if (string.IsNullOrEmpty(url)) return (null, LocalizationService.Instance.Get("SettingsUpdateUnconfigured"));
                if (url.Contains("github.com") && url.Contains("/blob/"))
                {
                    var parts = url.Split(new[] { "github.com/" }, StringSplitOptions.None)[1];
                    var i = parts.IndexOf("/blob/", StringComparison.Ordinal);
                    url = "https://raw.githubusercontent.com/" + parts[..i] + parts[(i + 6)..];
                }
                else if (url.Contains("gitee.com") && url.Contains("/blob/"))
                {
                    var parts = url.Split(new[] { "gitee.com/" }, StringSplitOptions.None)[1];
                    var i = parts.IndexOf("/blob/", StringComparison.Ordinal);
                    url = "https://gitee.com/" + parts[..i] + "/raw/" + parts[(i + 6)..];
                }

                using var client = new HttpClient();
                client.Timeout = TimeSpan.FromSeconds(10);
                client.DefaultRequestHeaders.UserAgent.ParseAdd("Tobatools/1.0");
                var text = client.GetStringAsync(url).GetAwaiter().GetResult().Trim();

                Dictionary<string, string>? obj = null;
                try
                {
                    using var doc = System.Text.Json.JsonDocument.Parse(text);
                    if (doc.RootElement.ValueKind == System.Text.Json.JsonValueKind.Object)
                    {
                        obj = new Dictionary<string, string>();
                        foreach (var p in doc.RootElement.EnumerateObject())
                        {
                            obj[p.Name] = p.Value.ValueKind == System.Text.Json.JsonValueKind.String ? p.Value.GetString() ?? "" : p.Value.ToString();
                        }
                    }
                }
                catch { obj = null; }

                if (obj == null || !obj.ContainsKey("version"))
                {
                    var kv = new Dictionary<string, string>();
                    foreach (var line in text.Split('\n'))
                    {
                        var t = line.Trim();
                        if (string.IsNullOrEmpty(t) || t.StartsWith('#')) continue;
                        var eq = t.IndexOf('=');
                        if (eq > 0)
                        {
                            kv[t[..eq].Trim()] = t[(eq + 1)..].Trim();
                        }
                    }
                    if (kv.ContainsKey("version"))
                    {
                        obj = new Dictionary<string, string>();
                        obj["version"] = kv.TryGetValue("version", out var v) ? v : "";
                        obj["url"] = kv.TryGetValue("url", out var u) ? u : "";
                        obj["notes"] = kv.TryGetValue("notes", out var nn) ? nn : "";
                    }
                }

                if (obj == null || !obj.ContainsKey("version"))
                {
                    foreach (var line in text.Split('\n'))
                    {
                        var t = line.Trim();
                        if (!string.IsNullOrEmpty(t))
                        {
                            obj = new Dictionary<string, string> { ["version"] = t };
                            break;
                        }
                    }
                }

                if (obj == null || !obj.ContainsKey("version")) return (null, LocalizationService.Instance.Get("SettingsUpdateMissing"));
                return (obj, null);
            }
            catch (Exception ex)
            {
                return (null, ex.Message);
            }
        }

        private void OnWebsite(object sender, RoutedEventArgs e) => OpenUrl("https://tobatools.top");
        private void OnQQGroup(object sender, RoutedEventArgs e) => OpenUrl("https://qm.qq.com/q/iBPCO3Xrjy");
        private void OnTelegram(object sender, RoutedEventArgs e) => OpenUrl("https://t.me/tuoba1213141647");

        private static void OpenUrl(string url)
        {
            try
            {
                Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch { }
        }

        private void ShowInfo(string title, string message)
        {
            var loc = LocalizationService.Instance;
            var dlg = new ContentDialog
            {
                Title = title,
                Content = new TextBlock { Text = message, TextWrapping = Microsoft.UI.Xaml.TextWrapping.Wrap },
                CloseButtonText = loc.Get("CommonOK"),
                XamlRoot = XamlRoot
            };
            _ = dlg.ShowAsync();
        }

    }
}
