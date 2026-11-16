using Microsoft.UI.Xaml.Media;

namespace Tobatools.Models
{
    public class AppItem
    {
        public string Pkg { get; set; } = "";
        public string Label { get; set; } = "";
        public ImageSource? Icon { get; set; }
        public bool IsSystem { get; set; }
    }
}
