using System;
using Microsoft.Graphics.Canvas.Effects;
using Microsoft.UI.Composition;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Hosting;
using Microsoft.UI.Xaml.Media;
using Tobatools.Services;
using Windows.UI;

namespace Tobatools.Controls;

/// <summary>共享全局材质：普通云母承载表面 / 可调实时背景模糊 / 系统纯色回退。</summary>
public sealed class AppMaterialBrush : XamlCompositionBrushBase
{
    public static readonly DependencyProperty NormalColorProperty = DependencyProperty.Register(
        nameof(NormalColor), typeof(Color), typeof(AppMaterialBrush),
        new PropertyMetadata(Microsoft.UI.Colors.Transparent, OnMaterialChanged));
    public static readonly DependencyProperty KindProperty = DependencyProperty.Register(
        nameof(Kind), typeof(string), typeof(AppMaterialBrush), new PropertyMetadata("Surface", OnMaterialChanged));

    public Color NormalColor { get => (Color)GetValue(NormalColorProperty); set => SetValue(NormalColorProperty, value); }
    public string Kind { get => (string)GetValue(KindProperty); set => SetValue(KindProperty, value); }
    private AppearanceService? _appearance;
    private CompositionEffectFactory? _factory;
    private CompositionEffectBrush? _effect;
    private CompositionBackdropBrush? _backdrop;
    private bool _connected;

    protected override void OnConnected()
    {
        _connected = true;
        _appearance = AppearanceService.Current;
        if (_appearance != null) _appearance.Changed += OnAppearanceChanged;
        UpdateMaterial();
    }

    protected override void OnDisconnected()
    {
        _connected = false;
        if (_appearance != null) _appearance.Changed -= OnAppearanceChanged;
        _appearance = null;
        ReleaseComposition();
    }

    private static void OnMaterialChanged(DependencyObject sender, DependencyPropertyChangedEventArgs args)
    {
        var brush = (AppMaterialBrush)sender;
        if (brush._connected) brush.UpdateMaterial();
    }
    private void OnAppearanceChanged(object? sender, EventArgs args) => UpdateMaterial();

    private void UpdateMaterial()
    {
        var normal = NormalColor;
        if (_appearance?.UseOpaqueFallback == true) normal.A = 255;
        FallbackColor = normal;
        var window = App.Instance?.MainWin;
        if (!_connected || window == null) return;
        var compositor = ElementCompositionPreview.GetElementVisual(window.RootElement).Compositor;
        if (_appearance?.IsGlassActive != true)
        {
            ReleaseComposition();
            CompositionBrush = compositor.CreateColorBrush(normal);
            return;
        }

        try
        {
            if (Kind == "Border")
            {
                ReleaseComposition();
                var rim = compositor.CreateLinearGradientBrush();
                rim.StartPoint = new System.Numerics.Vector2(0, 0);
                rim.EndPoint = new System.Numerics.Vector2(1, 1);
                var dark = _appearance.IsDark;
                rim.ColorStops.Add(compositor.CreateColorGradientStop(0, Color.FromArgb(dark ? (byte)110 : (byte)235, 255, 255, 255)));
                rim.ColorStops.Add(compositor.CreateColorGradientStop(0.5f, Color.FromArgb(dark ? (byte)24 : (byte)40, 120, 130, 150)));
                rim.ColorStops.Add(compositor.CreateColorGradientStop(1, Color.FromArgb(dark ? (byte)55 : (byte)180, 255, 255, 255)));
                CompositionBrush = rim;
                return;
            }

            var (tint, opacity) = _appearance.GlassMaterial(Kind);
            tint.A = (byte)Math.Round(255 * opacity);
            if (_effect == null)
            {
                ReleaseComposition();
                var blur = new GaussianBlurEffect
                {
                    Name = "Blur",
                    BlurAmount = _appearance.BlurAmount,
                    BorderMode = EffectBorderMode.Hard,
                    Optimization = EffectOptimization.Balanced,
                    Source = new CompositionEffectSourceParameter("Backdrop")
                };
                var material = new CompositeEffect
                {
                    Mode = Microsoft.Graphics.Canvas.CanvasComposite.SourceOver,
                    Sources = { blur, new ColorSourceEffect { Name = "Tint", Color = tint } }
                };
                _factory = compositor.CreateEffectFactory(material, new[] { "Blur.BlurAmount", "Tint.Color" });
                _effect = _factory.CreateBrush();
                _backdrop = compositor.CreateBackdropBrush();
                _effect.SetSourceParameter("Backdrop", _backdrop);
                CompositionBrush = _effect;
            }
            // 拖动滑块只更新 GPU 参数，不重建画刷、截图、导航或工具页面。
            _effect.Properties.InsertScalar("Blur.BlurAmount", _appearance.BlurAmount);
            _effect.Properties.InsertColor("Tint.Color", tint);
        }
        catch (Exception ex)
        {
            ReleaseComposition();
            normal.A = 255;
            FallbackColor = normal;
            CompositionBrush = compositor.CreateColorBrush(normal);
            _appearance.ReportRenderFailure(ex);
        }
    }

    private void ReleaseComposition()
    {
        var old = CompositionBrush;
        CompositionBrush = null;
        old?.Dispose();
        _effect = null;
        _backdrop?.Dispose();
        _backdrop = null;
        _factory?.Dispose();
        _factory = null;
    }
}
