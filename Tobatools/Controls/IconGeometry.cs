using Microsoft.UI.Xaml.Markup;
using Microsoft.UI.Xaml.Media;

namespace Tobatools.Controls;

/// <summary>
/// 把 SVG 路径数据字符串转成 WinUI 的 Geometry。
/// Python 原版图标来自 FluentIcon 的 SVG，与 Segoe 字体字形不同，
/// 因此这里统一用路径数据绘制，保证与原版图形一致。
/// </summary>
public static class IconGeometry
{
    public static Geometry? From(string? data)
    {
        if (string.IsNullOrWhiteSpace(data)) return null;
        try
        {
            return XamlBindingHelper.ConvertValue(typeof(Geometry), data) as Geometry;
        }
        catch
        {
            return null;
        }
    }
}
