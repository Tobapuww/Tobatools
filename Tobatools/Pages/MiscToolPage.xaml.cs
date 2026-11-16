using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Tobatools.Dialogs;

namespace Tobatools.Pages;

/// <summary>杂项与镜像工厂共用设置式工具页面，不以对话框承载完整工具。</summary>
public sealed partial class MiscToolPage : Page
{
    private string _parentTag = "misc";
    public string ParentTag => _parentTag;

    public MiscToolPage()
    {
        InitializeComponent();
        Loaded += (_, _) => Dlg.Root = XamlRoot;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        var route = e.Parameter as string ?? "";
        bool image = route.StartsWith("imagefactory/", StringComparison.Ordinal);
        _parentTag = image ? "imagefactory" : "misc";
        var id = image ? route["imagefactory/".Length..] : route;
        var tool = image ? ImageToolContents.Get(id) : MiscToolContents.Get(id);
        // 固件源工具已存在页内版本，与杂项工具共用实现。
        if (image && id is "payload" or "ofp") tool = MiscToolContents.Get(id);
        ToolBreadcrumb.ItemsSource = new[] { image ? "镜像工厂" : "杂项工具箱", tool?.Title ?? "未知工具" };
        ToolSubtitle.Text = tool?.Subtitle ?? "未找到对应工具，请通过上方导航返回。";
        ToolNotice.IsOpen = false;
        try { Host.Content = tool?.Build(); }
        catch (Exception ex) { ShowNotice("页面加载失败", ex.Message, true); }
    }

    public void ShowNotice(string title, string message, bool error)
    {
        ToolNotice.Title = title;
        ToolNotice.Message = message;
        ToolNotice.Severity = error ? InfoBarSeverity.Error : InfoBarSeverity.Informational;
        ToolNotice.IsOpen = true;
    }

    private void OnBreadcrumbClicked(BreadcrumbBar sender, BreadcrumbBarItemClickedEventArgs args)
    {
        if (args.Index == 0) MainWindow.BackFromTool();
    }
}
