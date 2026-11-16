using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Foundation;

namespace Tobatools.Controls;

/// <summary>等宽卡片自动按可用宽度排列，窄窗口下降为两列或单列。</summary>
public sealed class AdaptiveCards : Panel
{
    public static readonly DependencyProperty MinItemWidthProperty = DependencyProperty.Register(
        nameof(MinItemWidth), typeof(double), typeof(AdaptiveCards), new PropertyMetadata(240d, OnChanged));
    public static readonly DependencyProperty SpacingProperty = DependencyProperty.Register(
        nameof(Spacing), typeof(double), typeof(AdaptiveCards), new PropertyMetadata(16d, OnChanged));
    public double MinItemWidth { get => (double)GetValue(MinItemWidthProperty); set => SetValue(MinItemWidthProperty, value); }
    public double Spacing { get => (double)GetValue(SpacingProperty); set => SetValue(SpacingProperty, value); }
    private static void OnChanged(DependencyObject d, DependencyPropertyChangedEventArgs e) => ((AdaptiveCards)d).InvalidateMeasure();
    protected override Size MeasureOverride(Size availableSize) => Layout(availableSize.Width, false);
    protected override Size ArrangeOverride(Size finalSize)
    {
        Layout(finalSize.Width, true);
        return finalSize;
    }
    private Size Layout(double width, bool arrange)
    {
        if (Children.Count == 0) return new Size();
        double gap = Math.Max(0, Spacing);
        if (double.IsInfinity(width)) width = Children.Count * (Math.Max(1, MinItemWidth) + gap) - gap;
        int columns = Math.Clamp((int)((width + gap) / (Math.Max(1, MinItemWidth) + gap)), 1, Children.Count);
        double itemWidth = Math.Max(0, (width - gap * (columns - 1)) / columns);
        double y = 0;
        for (int start = 0; start < Children.Count; start += columns)
        {
            double height = 0;
            int end = Math.Min(start + columns, Children.Count);
            for (int i = start; i < end; i++)
            {
                if (!arrange) Children[i].Measure(new Size(itemWidth, double.PositiveInfinity));
                height = Math.Max(height, Children[i].DesiredSize.Height);
            }
            if (arrange)
                for (int i = start; i < end; i++)
                    Children[i].Arrange(new Rect((i - start) * (itemWidth + gap), y, itemWidth, height));
            y += height + (end < Children.Count ? gap : 0);
        }
        return new Size(width, y);
    }
}
