using Microsoft.UI.Xaml;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Tobatools.Services;
using Windows.UI.ViewManagement;

namespace Tobatools
{
    public partial class App : Application
    {
        private Window? _window;
        public static App? Instance { get; private set; }
        public MainWindow? MainWin { get; private set; }

        public App()
        {
            Instance = this;
            LocalizationService.Instance.ApplySavedLanguage();
            InitializeComponent();
            UnhandledException += (s, e) =>
            {
                try
                {
                    System.Diagnostics.Debug.WriteLine("Unhandled: " + e.Exception);
                }
                catch { }
            };
        }

        protected override void OnLaunched(LaunchActivatedEventArgs args)
        {
            // 初始化路径服务
            AppPaths.Initialize();

            _window = new MainWindow();
            MainWin = _window as MainWindow;
            _window.Activate();

            // 应用保存的主题
            ApplySavedTheme();
        }

        public static void ApplyTheme(string mode)
        {
            var win = Instance?.MainWin;
            var root = win?.RootElement;
            if (root == null) return;

            switch (mode)
            {
                case "light":
                    root.RequestedTheme = ElementTheme.Light;
                    break;
                case "dark":
                    root.RequestedTheme = ElementTheme.Dark;
                    break;
                default:
                    root.RequestedTheme = ElementTheme.Default;
                    break;
            }
        }

        private void ApplySavedTheme()
        {
            try
            {
                var mode = SettingsService.Instance.Get("theme/mode", "system");
                ApplyTheme(mode);
            }
            catch { }
        }
    }
}
