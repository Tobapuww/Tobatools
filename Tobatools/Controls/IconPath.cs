using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Tobatools.Controls;

/// <summary>
/// 用路径数据绘制图标的 PathIcon。
/// Python 原版导航图标取自 qfluentwidgets 的 FluentIcon SVG（Fluent UI System Icons），
/// 与 Segoe 字体字形不是同一套图形，因此这里统一按几何数据绘制，确保与原版一致。
/// 资源字典里存的是路径字符串，这里在 C# 侧显式转换，避免依赖隐式类型转换。
/// </summary>
public sealed partial class IconPath : PathIcon
{
    public static readonly DependencyProperty IconDataProperty = DependencyProperty.Register(
        nameof(IconData), typeof(string), typeof(IconPath),
        new PropertyMetadata(null, (d, _) => ((IconPath)d).Apply()));

    /// <summary>SVG 路径数据（M/L/C/Q/A/Z 语法，坐标按 16x16 归一化）。</summary>
    public string? IconData
    {
        get => (string?)GetValue(IconDataProperty);
        set => SetValue(IconDataProperty, value);
    }

    public IconPath()
    {
        Loaded += (_, _) => Apply();
    }

    private void Apply()
    {
        var geometry = IconGeometry.From(IconData);
        if (geometry != null) Data = geometry;
    }
}
