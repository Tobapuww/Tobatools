# 新增标签页

本项目使用 WinUI 3。新增页面需复用公共主题，不独立定义另一套字体、配色、按钮模板。

## 页面模板

将下面模板中的类名、标题、说明和内容替换为实际工具。通过 `MainWindow.xaml` 菜单及 `MainWindow.xaml.cs` 的导航映射注册入口。

```xml
<Page
    x:Class="Tobatools.Pages.ExamplePage"
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    xmlns:controls="using:Tobatools.Controls">
    <Grid Background="{ThemeResource AppCanvasBrush}">
        <ScrollViewer VerticalScrollBarVisibility="Auto"
                      HorizontalScrollBarVisibility="Disabled">
            <StackPanel Style="{StaticResource PageContentStyle}">
                <controls:PageHeader Title="工具名称" Subtitle="说明工具用途与使用前提。" Glyph="&#xE713;"/>
                <controls:ResponsiveColumns Breakpoint="900">
                    <Border Style="{StaticResource CardBorderStyle}">
                        <StackPanel Spacing="16">
                            <TextBlock Text="配置" Style="{StaticResource CardTitleStyle}"/>
                            <TextBox Header="输入文件" Style="{StaticResource RoundedTextBoxStyle}"/>
                            <!-- 主操作按钮必须绑定真实事件，示例不提供无效入口。 -->
                        </StackPanel>
                    </Border>
                    <Border Style="{StaticResource CardBorderSubtleStyle}">
                        <TextBlock Text="操作说明" Style="{StaticResource BodyTextStyle}"/>
                    </Border>
                </controls:ResponsiveColumns>
            </StackPanel>
        </ScrollViewer>
    </Grid>
</Page>
```

## 选择布局控件

- `ResponsiveColumns`：恰好两个直接子元素。`Breakpoint` 按自身可用宽度判断，宽时左右排列、窄时上下排列。`FirstColumnWeight` / `SecondColumnWeight` 设置列宽比例。
- `AdaptiveCards`：多个等宽指标或操作卡，使用 `MinItemWidth` 设置最小目标宽度，列数自动调整。
- `WrapPanel`：自动换行的按钮和选项，使用 `Spacing`，不为每个子元素额外重复设置右边距。
- `LogView`：设置有限高度，让日志独立滚动。

## 二级工具页

二级页采用 Windows 设置式“分类 › 工具名”面包屑，复用 `Pages/MiscToolPage.xaml` 宿主；标题使用 `PageTitleStyle`，内容继续沿用公共卡片主题。

- 杂项工具在 `MiscToolContents` 注册 `ToolDef`，入口调用 `MainWindow.OpenMiscTool(id)`。
- 镜像工厂工具在 `ImageToolContents` 注册，入口调用 `MainWindow.OpenImageTool(id)`；Payload / OFP 复用杂项的内容构建器。
- 工具的 `Build()` 仅返回内容，不重复创建页头、外层卡片与页面边距，不以 `ContentDialog` 承载完整工具。
- 父级面包屑返回所属分类；窄窗口由原生 `BreadcrumbBar` 处理折叠。二级导航显式使用横向 `SlideNavigationTransitionInfo`：进入为 `FromRight`，离开为 `FromLeft`，不使用默认纵向动画。
- 一般提示使用宿主 `ShowNotice()` / 页内 `InfoBar`。危险操作确认与系统文件选择器仍需保留。
- 工具离页应请求取消后台任务；取消按钮不能立即重新启用开始按钮，必须等待任务实际结束。任务运行时禁用输入应使用 `Control.IsEnabled`，`StackPanel` 不支持该属性。

顶部设备栏统一由 `MainWindow` 管理。仪表盘始终隐藏整个 Banner；其他页保留展开/收起入口，偏好保存为 `appearance/device_banner_collapsed`，不在每个页面重复实现。展开/收起使用 220ms 高度缓动及裁剪，支持连续反向点击；系统关闭动画时立即切换。收起后显示设备名称、连接状态和模式摘要，长文本省略并提供完整提示。摘要来自统一设备会话，名称缺失时使用序列号；仅在连续会话且序列号相同时保留已知名称，断开或换设备清除，不能伪造 Recovery 设备名称。

## 全局材质与框架

主项目目标为 `net10.0-windows10.0.26100.0`，使用 .NET 10 SDK 构建，Windows App SDK 为 `1.8.260209005`。

- `AppearanceService` 统一管理默认启用的云母、液态玻璃开关、模糊值及系统回退。页面的 `AppCanvasBrush` 在普通主题下透明，让窗口云母真正可见；根窗口负责不支持云母时的主题底色。
- 液态玻璃默认关闭。设置项为 `appearance/liquid_glass_enabled`（默认 false）、`appearance/liquid_glass_blur`（默认 24，范围 0–64 DIP）。DIP 是不随屏幕缩放改变逻辑尺寸的单位；此参数控制玻璃背景模糊，不改变云母自身由系统决定的模糊。
- `AppMaterialBrush` 为公共卡片、辅助表面、导航侧栏、设备栏、普通按钮、输入框及标准弹出表面提供材质。新页面继续使用公共样式即可接入，无需单独创建合成效果。
- `DevWinUI.LiquidGlass 1.0.8` 依赖的 `LiquidGlass.Uno` 提供浅/深色玻璃着色资源；`Microsoft.Graphics.Win2D 1.4.0` 和原生 Composition 实现可调 `GaussianBlurEffect`、着色叠加和渐变边缘。这是该 Windows 包的亚克力式玻璃材质，不是额外的折射着色器。
- 包的资源字典按需载入供材质解析，不全局应用其隐式控件模板。这样能保留公共按钮层级、危险操作确认、键盘焦点及运行中的页面状态。拖动模糊滑块仅更新合成参数，不截图、不重建页面。
- 高对比度、系统关闭透明效果或合成能力不可用时禁用实际玻璃，保留用户偏好并使用纯色回退；设置页显示原因。云母不受支持时使用普通主题背景。主窗口关闭时释放事件订阅，画刷断开时释放合成资源。

材质自动化测试见 `Tests/AppearanceSmoke.ps1`。它使用一次性设置作用域，允许用户已有实例继续运行，不修改生产设置。不同 Windows 版本、远程桌面和低端显卡仍需单独验收。

## 状态与行为

页面应在 `Loaded` 时订阅 `DeviceSession.Instance.StateChanged`，在 `Unloaded` 时退订。统一会话事件在 UI 线程触发；读取慢速 shell 或传输操作仍需后台执行。后台任务开始前捕获输入值，不能从后台线程直接读取 TextBox 等控件。

数据缺失显示“—”，加载、未授权、离线、检测失败分别提示。等待设备列表完成后再判断无设备。设备变更后清除旧数据，并丢弃旧异步请求的结果。危险操作必须等待确认对话框结果，再执行并检查命令退出状态。

验证方式见 `Tests/README.md`。项目规则 `.cursor/rules/toolbox-ui.mdc` 同步记录上述要求。
