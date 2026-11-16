using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Tobatools.Controls;

public sealed partial class PageHeader : UserControl
{
    public static readonly DependencyProperty TitleProperty = DependencyProperty.Register(
        nameof(Title), typeof(string), typeof(PageHeader), new PropertyMetadata(""));
    public static readonly DependencyProperty SubtitleProperty = DependencyProperty.Register(
        nameof(Subtitle), typeof(string), typeof(PageHeader), new PropertyMetadata(""));
    // 图标改为路径数据：Python 原版用的是 FluentIcon SVG，与字体字形并非同一套图形。
    public static readonly DependencyProperty IconDataProperty = DependencyProperty.Register(
        nameof(IconData), typeof(string), typeof(PageHeader),
        new PropertyMetadata("", (d, _) => ((PageHeader)d).ApplyIcon()));

    public string Title { get => (string)GetValue(TitleProperty); set => SetValue(TitleProperty, value); }
    public string Subtitle { get => (string)GetValue(SubtitleProperty); set => SetValue(SubtitleProperty, value); }
    public string IconData { get => (string)GetValue(IconDataProperty); set => SetValue(IconDataProperty, value); }

    public PageHeader()
    {
        InitializeComponent();
        Loaded += (_, _) => ApplyIcon();
    }

    private void ApplyIcon()
    {
        if (GlyphIcon == null) return;
        GlyphIcon.Data = IconGeometry.From(IconData);
    }
}
