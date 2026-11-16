using Microsoft.UI.Xaml;

namespace Tobatools.Models
{
    public class FileItem
    {
        public string Name { get; set; } = "";
        public string Size { get; set; } = "-";
        public string Type { get; set; } = "file"; // dir | file
        public string FullPath { get; set; } = "";
        public string TypeText => Tobatools.Services.LocalizationService.Instance.Get(Type == "dir" ? "FilesFolder" : "FilesFile");
        public bool IsDir => Type == "dir";
        public Visibility DirVisibility => IsDir ? Visibility.Visible : Visibility.Collapsed;
        public Visibility FileVisibility => IsDir ? Visibility.Collapsed : Visibility.Visible;
    }
}
