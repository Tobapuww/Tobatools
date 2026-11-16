using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Foundation;

namespace Tobatools.Controls;

/// <summary>两个内容区在可用宽度不足时纵向排列；断点按内容宽度而非窗口宽度判断。</summary>
public sealed class ResponsiveColumns : Grid
{
    public static readonly DependencyProperty BreakpointProperty = Register(nameof(Breakpoint), 900);
    public static readonly DependencyProperty SpacingProperty = Register(nameof(Spacing), 16);
    public static readonly DependencyProperty FirstColumnWeightProperty = Register(nameof(FirstColumnWeight), 1);
    public static readonly DependencyProperty SecondColumnWeightProperty = Register(nameof(SecondColumnWeight), 1);
    private bool? _wide;
    private int _childCount = -1;

    public double Breakpoint { get => (double)GetValue(BreakpointProperty); set => SetValue(BreakpointProperty, value); }
    public double Spacing { get => (double)GetValue(SpacingProperty); set => SetValue(SpacingProperty, value); }
    public double FirstColumnWeight { get => (double)GetValue(FirstColumnWeightProperty); set => SetValue(FirstColumnWeightProperty, value); }
    public double SecondColumnWeight { get => (double)GetValue(SecondColumnWeightProperty); set => SetValue(SecondColumnWeightProperty, value); }

    private static DependencyProperty Register(string name, double value) => DependencyProperty.Register(
        name, typeof(double), typeof(ResponsiveColumns), new PropertyMetadata(value, OnLayoutChanged));

    private static void OnLayoutChanged(DependencyObject sender, DependencyPropertyChangedEventArgs args)
    {
        var panel = (ResponsiveColumns)sender;
        panel._wide = null;
        panel.InvalidateMeasure();
    }

    protected override Size MeasureOverride(Size availableSize)
    {
        bool wide = availableSize.Width >= Breakpoint;
        if (_wide != wide || _childCount != Children.Count)
        {
            _wide = wide;
            _childCount = Children.Count;
            RowDefinitions.Clear();
            ColumnDefinitions.Clear();
            ColumnSpacing = wide ? Math.Max(0, Spacing) : 0;
            RowSpacing = wide ? 0 : Math.Max(0, Spacing);
            ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(Math.Max(0.1, FirstColumnWeight), GridUnitType.Star) });
            if (wide)
                ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(Math.Max(0.1, SecondColumnWeight), GridUnitType.Star) });
            for (int i = 0; i < Children.Count; i++)
            {
                if (!wide) RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                Children[i].SetValue(RowProperty, wide ? 0 : i);
                Children[i].SetValue(ColumnProperty, wide ? Math.Min(i, 1) : 0);
            }
        }
        return base.MeasureOverride(availableSize);
    }
}

/// <summary>操作按钮、选项和指标卡按可用宽度换行，不产生水平溢出。</summary>
public sealed class WrapPanel : Panel
{
    public static readonly DependencyProperty SpacingProperty = DependencyProperty.Register(
        nameof(Spacing), typeof(double), typeof(WrapPanel),
        new PropertyMetadata(8d, (sender, _) => ((WrapPanel)sender).InvalidateMeasure()));
    public double Spacing { get => (double)GetValue(SpacingProperty); set => SetValue(SpacingProperty, value); }

    protected override Size MeasureOverride(Size availableSize) => Layout(availableSize.Width, false);
    protected override Size ArrangeOverride(Size finalSize)
    {
        Layout(finalSize.Width, true);
        return finalSize;
    }

    private Size Layout(double width, bool arrange)
    {
        double x = 0, y = 0, rowHeight = 0, usedWidth = 0;
        double gap = Math.Max(0, Spacing);
        foreach (var child in Children)
        {
            if (child.Visibility == Visibility.Collapsed) continue;
            if (!arrange) child.Measure(new Size(width, double.PositiveInfinity));
            var size = child.DesiredSize;
            if (x > 0 && x + size.Width > width)
            {
                x = 0;
                y += rowHeight + gap;
                rowHeight = 0;
            }
            if (arrange) child.Arrange(new Rect(x, y, size.Width, size.Height));
            usedWidth = Math.Max(usedWidth, x + size.Width);
            x += size.Width + gap;
            rowHeight = Math.Max(rowHeight, size.Height);
        }
        return new Size(usedWidth, y + rowHeight);
    }
}
