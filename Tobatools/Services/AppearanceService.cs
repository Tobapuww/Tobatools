using System;
using System.Globalization;
using Microsoft.UI.Composition;
using Microsoft.UI.Composition.SystemBackdrops;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Windows.UI;
using Windows.UI.ViewManagement;

namespace Tobatools.Services;

/// <summary>窗口统一材质策略。仅更新画刷，不重建页面或中断工具任务。</summary>
public sealed class AppearanceService : IDisposable
{
    internal static AppearanceService? Current { get; private set; }
    private readonly MainWindow _window;
    private readonly UISettings _ui = new();
    private readonly AccessibilitySettings _accessibility = new();
    private readonly CompositionCapabilities _capabilities;
    private bool _disposed;
    private bool _rendererFailed;
    private bool _micaSupported;

    public bool GlassEnabled { get; private set; }
    public int BlurAmount { get; private set; }
    public bool EffectsAvailable => !_accessibility.HighContrast && _ui.AdvancedEffectsEnabled
        && _capabilities.AreEffectsSupported() && !_rendererFailed;
    public bool IsGlassActive => GlassEnabled && EffectsAvailable;
    internal bool IsDark => _window.RootElement.ActualTheme == ElementTheme.Dark;
    internal bool UseOpaqueFallback => !EffectsAvailable;
    public event EventHandler? Changed;

    public string StatusText
    {
        get
        {
            if (_accessibility.HighContrast) return "高对比度模式：已使用系统纯色，保留液态玻璃偏好。";
            if (!_ui.AdvancedEffectsEnabled) return "系统透明效果已关闭：当前使用纯色，保留液态玻璃偏好。";
            if (_rendererFailed || !_capabilities.AreEffectsSupported()) return "当前图形环境不支持玻璃合成，已回退普通材质。";
            var backdrop = _micaSupported ? "全局云母已启用" : "系统不支持云母，使用主题背景";
            return IsGlassActive ? $"{backdrop} · 液态玻璃已启用 · 模糊 {BlurAmount} DIP"
                : $"{backdrop} · 液态玻璃未启用";
        }
    }

    public AppearanceService(MainWindow window)
    {
        _window = window;
        _capabilities = new CompositionCapabilities();
        Current = this;
        GlassEnabled = SettingsService.Instance.GetBool("appearance/liquid_glass_enabled", false);
        BlurAmount = Math.Clamp(SettingsService.Instance.GetInt("appearance/liquid_glass_blur", 24), 0, 64);
        try
        {
            _micaSupported = MicaController.IsSupported();
            if (_micaSupported) _window.SystemBackdrop = new MicaBackdrop { Kind = MicaKind.Base };
        }
        catch { _micaSupported = false; }
        _window.RootElement.ActualThemeChanged += OnThemeChanged;
        _window.RootElement.Loaded += OnLoaded;
        // AccessibilitySettings.HighContrastChanged 依赖 UWP CoreWindow，非打包 WinUI 窗口不能订阅。
        // 桌面窗口通过 UISettings 颜色变化及激活事件重新读取高对比度状态。
        _window.Activated += OnWindowActivated;
        _ui.AdvancedEffectsEnabledChanged += OnAdvancedEffectsChanged;
        _ui.ColorValuesChanged += OnColorsChanged;
        _capabilities.Changed += OnCapabilitiesChanged;
        Refresh();
    }

    public void SetGlassEnabled(bool enabled)
    {
        if (GlassEnabled == enabled) return;
        GlassEnabled = enabled;
        // 显式切换允许重试暂时故障；关闭玻璃也应恢复独立的云母背景。
        _rendererFailed = false;
        SettingsService.Instance.Set("appearance/liquid_glass_enabled", enabled ? "true" : "false");
        Refresh();
    }

    public void SetBlurAmount(int amount)
    {
        amount = Math.Clamp(amount, 0, 64);
        if (BlurAmount == amount) return;
        BlurAmount = amount;
        SettingsService.Instance.Set("appearance/liquid_glass_blur", amount.ToString(CultureInfo.InvariantCulture));
        Changed?.Invoke(this, EventArgs.Empty);
    }

    private void Refresh()
    {
        if (_disposed) return;
        var background = _accessibility.HighContrast ? _ui.GetColorValue(UIColorType.Background)
            : IsDark ? Color.FromArgb(255, 25, 28, 35) : Color.FromArgb(255, 244, 246, 250);
        _window.RootElement.Background = new SolidColorBrush(_micaSupported && EffectsAvailable
            ? Microsoft.UI.Colors.Transparent : background);
        Changed?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>
    /// 玻璃材质配色。原先取自 LiquidGlass 包的资源字典，
    /// 移除该依赖后改为内置配色，保持相同观感并省去 Uno/SkiaSharp 运行时。
    /// </summary>
    internal (Color tint, float opacity) GlassMaterial(string kind)
    {
        var dark = IsDark;
        return kind switch
        {
            "Pane" => (dark ? Color.FromArgb(255, 30, 34, 42) : Color.FromArgb(255, 250, 251, 253), 0.72f),
            "Control" => (dark ? Color.FromArgb(255, 42, 47, 58) : Color.FromArgb(255, 255, 255, 255), 0.62f),
            _ => (dark ? Color.FromArgb(255, 36, 40, 49) : Color.FromArgb(255, 252, 253, 255), 0.66f),
        };
    }

    internal void ReportRenderFailure(Exception error)
    {
        if (_rendererFailed || _disposed) return;
        _rendererFailed = true;
        System.Diagnostics.Debug.WriteLine("Glass composition fallback: " + error);
        QueueRefresh();
    }

    private void QueueRefresh() => _window.DispatcherQueue.TryEnqueue(Refresh);
    private void OnLoaded(object sender, RoutedEventArgs e) => Refresh();
    private void OnThemeChanged(FrameworkElement sender, object args) => Refresh();
    private void OnWindowActivated(object sender, WindowActivatedEventArgs args) => Refresh();
    private void OnAdvancedEffectsChanged(UISettings sender, object args) => QueueRefresh();
    private void OnColorsChanged(UISettings sender, object args) => QueueRefresh();
    private void OnCapabilitiesChanged(CompositionCapabilities sender, object args) => QueueRefresh();

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _window.RootElement.ActualThemeChanged -= OnThemeChanged;
        _window.RootElement.Loaded -= OnLoaded;
        _window.Activated -= OnWindowActivated;
        _ui.AdvancedEffectsEnabledChanged -= OnAdvancedEffectsChanged;
        _ui.ColorValuesChanged -= OnColorsChanged;
        _capabilities.Changed -= OnCapabilitiesChanged;
        Changed = null;
        if (ReferenceEquals(Current, this)) Current = null;
    }
}
