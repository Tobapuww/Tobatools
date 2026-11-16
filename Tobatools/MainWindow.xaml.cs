using System;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Tobatools.Dialogs;
using Tobatools.Pages;
using Tobatools.Services;
using Windows.Graphics;

namespace Tobatools
{
    public sealed partial class MainWindow : Window
    {
        public Grid RootElement => RootGrid;
        public AppearanceService Appearance { get; }
        private bool _bannerCollapsed;
        private Storyboard? _bannerAnimation;
        private readonly DeviceBannerSummary _bannerSummary = new();
        private readonly Windows.UI.ViewManagement.UISettings _animationSettings = new();
        public MiscToolPage? ActiveToolPage => ContentFrame.Content as MiscToolPage;

        public MainWindow()
        {
            InitializeComponent();
            _bannerCollapsed = SettingsService.Instance.GetBool("appearance/device_banner_collapsed", false);

#if !ENABLE_FLASH
            // 公开构建不含刷机模块（源码不在公开库中），移除对应导航项。
            NavView.MenuItems.Remove(NavFlash);
#endif

            // 应用本地化文本
            ApplyLocalizedNavigation();
            UpdateBannerToggleText();

            ContentFrame.Navigated += (_, _) => UpdateBanner();
            RootGrid.Loaded += (s, e) => Dlg.Root = RootGrid.XamlRoot;

            // 全局云母与可选液态玻璃由统一材质服务管理。
            Appearance = new AppearanceService(this);

            // 窗口尺寸
            try
            {
                var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
                var id = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(hwnd);
                var appWindow = AppWindow.GetFromWindowId(id);
                appWindow.Resize(new SizeInt32(1280, 820));
                // 任务栏与窗口标题栏图标。可执行文件图标由 ApplicationIcon 写入，
                // 这里再显式设置一次，保证非打包运行时也使用工具箱图标。
                var icoPath = System.IO.Path.Combine(AppContext.BaseDirectory, "Assets", "app.ico");
                if (System.IO.File.Exists(icoPath))
                    appWindow.SetIcon(icoPath);
            }
            catch { }

            // 启动设备会话
            DeviceSession.Instance.StateChanged += UpdateCompactDeviceSummary;
            UpdateCompactDeviceSummary();
            DeviceSession.Instance.Start(DispatcherQueue);

            Closed += (s, e) =>
            {
                _bannerAnimation?.Stop();
                DeviceSession.Instance.StateChanged -= UpdateCompactDeviceSummary;
                Appearance.Dispose();
                DeviceSession.Instance.Stop();
            };

            // 初始导航
            NavView.SelectedItem = NavView.MenuItems[0] as NavigationViewItem;
            Navigate("dashboard");
        }

        private void OnSelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
        {
            if (args.SelectedItem is NavigationViewItem item && item.Tag is string tag)
            {
                Navigate(tag);
            }
        }

        private void Navigate(string tag)
        {
            Type pageType = tag switch
            {
                "dashboard" => typeof(DashboardPage),
                "imagefactory" => typeof(ImageFactoryPage),
#if ENABLE_FLASH
                "flash" => typeof(FlashPage),
#endif
                "scrcpy" => typeof(ScrcpyPage),
                "software" => typeof(SoftwareManagerPage),
                "files" => typeof(FileManagerPage),
                "backup" => typeof(BackupPage),
                "misc" => typeof(MiscPage),
                "settings" => typeof(SettingsPage),
                _ => typeof(DashboardPage),
            };

            if (ContentFrame.CurrentSourcePageType != pageType)
            {
                // 离开二级页时沿水平方向返回，避免默认的纵向进入动画。
                if (ActiveToolPage != null)
                    ContentFrame.Navigate(pageType, tag, new SlideNavigationTransitionInfo
                    {
                        Effect = SlideNavigationTransitionEffect.FromLeft
                    });
                else
                    ContentFrame.Navigate(pageType, tag);
            }
        }

        /// <summary>从杂项主页进入某个工具的二级页面。</summary>
        public static void OpenMiscTool(string toolId)
        {
            if (App.Instance?.MainWin is MainWindow w)
                w.ContentFrame.Navigate(typeof(MiscToolPage), toolId, new SlideNavigationTransitionInfo
                {
                    Effect = SlideNavigationTransitionEffect.FromRight
                });
        }

        public static void OpenImageTool(string toolId)
        {
            if (App.Instance?.MainWin is MainWindow w)
                w.ContentFrame.Navigate(typeof(MiscToolPage), "imagefactory/" + toolId, new SlideNavigationTransitionInfo
                {
                    Effect = SlideNavigationTransitionEffect.FromRight
                });
        }

        /// <summary>面包屑返回工具所属分类，不把镜像工具误导向杂项主页。</summary>
        public static void BackFromTool()
        {
            if (App.Instance?.MainWin is MainWindow w)
                w.Navigate(w.ActiveToolPage?.ParentTag ?? "misc");
        }

        private void OnBannerToggle(object sender, RoutedEventArgs e)
        {
            _bannerCollapsed = !_bannerCollapsed;
            SettingsService.Instance.Set("appearance/device_banner_collapsed", _bannerCollapsed ? "true" : "false");
            UpdateBannerToggleText();
            UpdateBanner(animate: true);
        }

        private void UpdateBanner(bool animate = false)
        {
            bool dashboard = ContentFrame.CurrentSourcePageType == typeof(DashboardPage);
            DeviceBanner.Visibility = dashboard ? Visibility.Collapsed : Visibility.Visible;
            CompactDeviceSummary.Visibility = _bannerCollapsed ? Visibility.Visible : Visibility.Collapsed;
            UpdateBannerToggleText();
            BannerToggleIcon.Glyph = _bannerCollapsed ? "\uE70D" : "\uE70E";

            // 先捕获正在呈现的高度，再停止旧动画，使快速反向点击也能连续过渡。
            double from = DeviceBarViewport.ActualHeight;
            _bannerAnimation?.Stop();
            _bannerAnimation = null;
            if (!animate || dashboard || !_animationSettings.AnimationsEnabled)
            {
                FinishBannerTransition();
                return;
            }

            DeviceBar.Visibility = Visibility.Visible;
            DeviceBar.IsEnabled = !_bannerCollapsed;
            DeviceBar.Measure(new Windows.Foundation.Size(Math.Max(1, DeviceBarViewport.ActualWidth), double.PositiveInfinity));
            double to = _bannerCollapsed ? 0 : DeviceBar.DesiredSize.Height;
            DeviceBarViewport.Height = from;
            var animation = new DoubleAnimation
            {
                From = from, To = to,
                Duration = new Duration(TimeSpan.FromMilliseconds(220)),
                EnableDependentAnimation = true,
                EasingFunction = new CubicEase { EasingMode = EasingMode.EaseInOut }
            };
            Storyboard.SetTarget(animation, DeviceBarViewport);
            Storyboard.SetTargetProperty(animation, "Height");
            var storyboard = new Storyboard();
            storyboard.Children.Add(animation);
            _bannerAnimation = storyboard;
            storyboard.Completed += (_, _) =>
            {
                if (!ReferenceEquals(_bannerAnimation, storyboard)) return;
                storyboard.Stop();
                _bannerAnimation = null;
                FinishBannerTransition();
            };
            storyboard.Begin();
        }

        private void FinishBannerTransition()
        {
            DeviceBarViewport.Height = _bannerCollapsed ? 0 : double.NaN;
            DeviceBar.Visibility = _bannerCollapsed ? Visibility.Collapsed : Visibility.Visible;
            DeviceBar.IsEnabled = !_bannerCollapsed;
        }

        private void OnDeviceBarViewportSizeChanged(object sender, SizeChangedEventArgs e)
        {
            DeviceBarClip.Rect = new Windows.Foundation.Rect(0, 0, e.NewSize.Width, e.NewSize.Height);
        }

        private void UpdateCompactDeviceSummary()
        {
            var session = DeviceSession.Instance;
            var summary = session.Summary;
            CompactDeviceSummary.Text = _bannerSummary.Update(summary?.Serial, summary?.Mode, session.Info);
            ToolTipService.SetToolTip(CompactDeviceSummary, CompactDeviceSummary.Text);
        }

        /// <summary>按当前语言填充导航项文本和 ToolTip。
        /// 语言切换需要重启应用，因此只需在构造时调用一次。</summary>
        private void ApplyLocalizedNavigation()
        {
            var loc = LocalizationService.Instance;
            AppTitle = loc.Get("AppTitle");
            Title = AppTitle;
            RootGrid.Language = loc.EffectiveLanguageCode;
            AppTitleTextBlock.Text = AppTitle;
            AppSubtitleTextBlock.Text = loc.Get("AppSubtitle");

            SetNavItem(NavDashboard, "NavDashboard", "NavDashboardTooltip");
            SetNavItem(NavImageFactory, "NavImageFactory", "NavImageFactoryTooltip");
#if ENABLE_FLASH
            SetNavItem(NavFlash, "NavFlash", "NavFlashTooltip");
#endif
            SetNavItem(NavScrcpy, "NavScrcpy", "NavScrcpyTooltip");
            SetNavItem(NavSoftware, "NavSoftware", "NavSoftwareTooltip");
            SetNavItem(NavFiles, "NavFiles", "NavFilesTooltip");
            SetNavItem(NavBackup, "NavBackup", "NavBackupTooltip");
            SetNavItem(NavMisc, "NavMisc", "NavMiscTooltip");
            SetNavItem(NavSettingsItem, "NavSettings", "NavSettingsTooltip");
        }

        private void SetNavItem(NavigationViewItem item, string contentKey, string tooltipKey)
        {
            var loc = LocalizationService.Instance;
            item.Content = loc.Get(contentKey);
            ToolTipService.SetToolTip(item, loc.Get(tooltipKey));
        }

        private void UpdateBannerToggleText()
        {
            var loc = LocalizationService.Instance;
            string text = _bannerCollapsed ? loc.Get("DeviceBarExpand") : loc.Get("DeviceBarCollapse");
            BannerToggleText.Text = text;
            Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(BannerToggle, text);
        }

        public string AppTitle { get; private set; } = "Tobatools";
    }
}
