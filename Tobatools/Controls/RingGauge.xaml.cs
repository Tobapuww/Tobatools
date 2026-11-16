using System;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace Tobatools.Controls
{
    /// <summary>
    /// 环形仪表：用于显示电池/存储/内存等百分比。
    /// </summary>
    public sealed partial class RingGauge : UserControl
    {
        private double _value = 0;
        private string _accent = "#2BC3A8";

        public static readonly DependencyProperty AccentColorProperty =
            DependencyProperty.Register(nameof(AccentColor), typeof(string), typeof(RingGauge),
                new PropertyMetadata("#2BC3A8", (d, e) => ((RingGauge)d).SetAccent((string)e.NewValue)));

        public static readonly DependencyProperty RingSizeProperty =
            DependencyProperty.Register(nameof(RingSize), typeof(double), typeof(RingGauge),
                new PropertyMetadata(120.0, (d, e) => ((RingGauge)d).ApplySize((double)e.NewValue)));

        public string AccentColor
        {
            get => (string)GetValue(AccentColorProperty);
            set => SetValue(AccentColorProperty, value);
        }

        /// <summary>环体外径（px），用于 KPI 紧凑块与默认大尺寸两种场景。</summary>
        public double RingSize
        {
            get => (double)GetValue(RingSizeProperty);
            set => SetValue(RingSizeProperty, value);
        }

        public RingGauge()
        {
            InitializeComponent();
            ApplySize(RingSize);
        }

        private void ApplySize(double size)
        {
            size = Math.Max(60, size);
            Root.Width = size;
            Root.Height = size;
            TrackPath.Width = size;
            TrackPath.Height = size;
            ValuePath.Width = size;
            ValuePath.Height = size;
            TxtValue.FontSize = size >= 110 ? 22 : size >= 80 ? 17 : 15;
            TxtCaption.FontSize = size >= 80 ? 11 : 10;
            DrawTrack();
            DrawArc();
        }

        public double Radius
        {
            get => Root.Width / 2.0;
        }

        public void SetValue(double value, string? display = null, string? caption = null)
        {
            _value = Math.Max(0, Math.Min(100, value));
            if (display != null) TxtValue.Text = display;
            if (caption != null) TxtCaption.Text = caption;
            DrawArc();
        }

        public void SetValueOnly(double value)
        {
            _value = Math.Max(0, Math.Min(100, value));
            TxtValue.Text = $"{(int)_value}%";
            DrawArc();
        }

        public void SetAccent(string hex)
        {
            _accent = hex ?? _accent;
            DrawArc();
        }

        private static double DegToRad(double d) => d * Math.PI / 180.0;

        private void DrawTrack()
        {
            var cx = Radius;
            var cy = Radius;
            var r = Radius - 10;
            TrackPath.Data = new EllipseGeometry
            {
                Center = new Windows.Foundation.Point(cx, cy),
                RadiusX = r,
                RadiusY = r
            };
        }

        private void DrawArc()
        {
            var cx = Radius;
            var cy = Radius;
            var r = Radius - 10;
            var start = -90.0;
            var sweep = _value / 100.0 * 360.0;
            if (sweep <= 0)
            {
                ValuePath.Data = null;
                ValuePath.Stroke = new SolidColorBrush(ParseColor(_accent));
                return;
            }

            if (_value >= 100)
            {
                ValuePath.Data = new EllipseGeometry
                {
                    Center = new Windows.Foundation.Point(cx, cy), RadiusX = r, RadiusY = r
                };
                ValuePath.Stroke = new SolidColorBrush(ParseColor(_accent));
                return;
            }
            var end = start + sweep;
            var startRad = DegToRad(start);
            var endRad = DegToRad(end);
            var p1 = new Windows.Foundation.Point(cx + r * Math.Cos(startRad), cy + r * Math.Sin(startRad));
            var p2 = new Windows.Foundation.Point(cx + r * Math.Cos(endRad), cy + r * Math.Sin(endRad));

            ValuePath.Data = new PathGeometry
            {
                Figures =
                {
                    new PathFigure
                    {
                        StartPoint = p1,
                        IsClosed = false,
                        IsFilled = false,
                        Segments =
                        {
                            new ArcSegment
                            {
                                Point = p2,
                                Size = new Windows.Foundation.Size(r, r),
                                SweepDirection = SweepDirection.Clockwise,
                                IsLargeArc = sweep > 180
                            }
                        }
                    }
                }
            };
            ValuePath.Stroke = new SolidColorBrush(ParseColor(_accent));
        }

        private static Color ParseColor(string hex)
        {
            hex = hex.TrimStart('#');
            if (hex.Length == 6)
                return Color.FromArgb(255, Convert.ToByte(hex.Substring(0, 2), 16), Convert.ToByte(hex.Substring(2, 2), 16), Convert.ToByte(hex.Substring(4, 2), 16));
            if (hex.Length == 8)
                return Color.FromArgb(Convert.ToByte(hex.Substring(0, 2), 16), Convert.ToByte(hex.Substring(2, 2), 16), Convert.ToByte(hex.Substring(4, 2), 16), Convert.ToByte(hex.Substring(6, 2), 16));
            return Colors.Teal;
        }
    }
}
