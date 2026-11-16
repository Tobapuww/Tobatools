# 本地回归检查

## 设备状态回归

在项目目录运行：

```powershell
dotnet run --project Tests/Regression.csproj
```

该检查链接实际的 `DeviceSession`、`AdbDeviceParser`、`AdbCommandResult` 和 `WirelessAdb` 源码，使用模拟的 ADB 服务及可排队的 UI 调度器。
覆盖 52 项检查：设备输出解析、未授权/离线区分、在线设备优先、命令退出状态与错误诊断、无线地址/端口/配对码校验、ADB 失败文本不得按退出码 0 误判成功、配对与连接区分、收起设备栏名称/连接模式及断开换机清理、先发布连接再发布详情、重复刷新合并、断开清理、订阅者异常隔离和停止/重新启动会话。
不连接或修改手机，不代替真实硬件测试。

## 本机 ADB 只读核验

```powershell
dotnet run --project Tests/AdbReadOnly.csproj
```

此项链接实际 ADB 服务，比较命令行与程序的设备列表，并输出实际使用的 ADB 路径、当前模式。会查询本机 ADB 服务，必要时启动它；不执行设备修改命令。设备在测试中途接入或拔出可能导致两次采样不同，应保持连接状态稳定后重试。

## 页面运行时检查

主项目需要 .NET 10 SDK。先还原依赖，再构建独立验证输出（避免混用旧 .NET 8 文件）：

```powershell
dotnet restore Tobatools.csproj
dotnet build Tobatools.csproj --no-restore -p:Platform=x64 -p:OutputPath=bin\glass-verification\
powershell -NoProfile -ExecutionPolicy Bypass -File Tests/UiSmoke.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File Tests/ToolNavigationSmoke.ps1
```

`UiSmoke.ps1` 启动独立验证目录内的程序，使用 Windows UI Automation 在 1440 / 900 像素宽度下切换九个导航页面，并检查主要页面控件已加载。
它也切换浅色、深色和跟随系统主题，随后恢复测试前的主题，最后关闭这个测试实例。

`ToolNavigationSmoke.ps1` 检查仪表盘隐藏 Banner、其他页展开/收起、收起摘要可见、连续快速点击后的状态一致性、跨导航与应用重启记忆；在 1440 / 900 像素宽度下验证镜像工厂全部 7 个工具，以及杂项的 Payload / OFP / 配置检测子页。验证页内输入、无整工具弹窗、面包屑返回正确分类，结束恢复原设备栏偏好并关闭实例。

两个脚本均接受 `-ExePath` 指定其他构建目录，不点击安装、刷写、删除、重启、备份或实际镜像处理按钮。测试时请避免同时修改应用主题或设备栏偏好。
这只能验证启动、导航、设备栏偏好及主题切换，不是截图对比或完整功能测试。

测试项目使用 `Tests/Directory.Build.props` 隔离各自 `obj` / `bin`，避免多个项目在同一目录覆盖 NuGet 资产或应用入口。纯逻辑和 ADB 只读测试仍使用 .NET 8，与主项目的 WinUI 框架升级解耦。

## 全局材质检查

```powershell
dotnet build Tobatools.csproj --no-restore -p:Platform=x64 -p:OutputPath=bin\material-verification\
powershell -NoProfile -ExecutionPolicy Bypass -File Tests/AppearanceSmoke.ps1
```

`AppearanceSmoke.ps1` 默认运行 `bin/material-verification/Tobatools.exe`，接受 `-ExePath`。它为测试进程设置随机 GUID 格式的 `TOBATOOLS_TEST_SETTINGS_ID`，使 `SettingsService` 使用 `HKCU\Software\Tobatools\UiTests\{id}`；结束关闭自己的实例并删除自己的设置。生产环境不设置该变量，继续使用原注册表位置。允许用户旧实例运行，不会改动它们的主题、模糊或设备栏设置。

检查首次默认玻璃关闭/模糊 24，0/24/64 模糊值，开关即时切换，浅深色、1440/900 宽度、九个标签页往返，六种开关/模糊组合重启记忆，最后在玻璃开启状态运行二级页与 Banner 回归。系统不支持效果时测试明确报覆盖未完成，不把纯色回退当成真实玻璃验证通过。

可选 `-CaptureDirectory "绝对路径"` 保存本测试窗口的屏幕截图，用于人工核验；这是实际屏幕捕获，会短暂将测试窗口置前。截图可能受窗口遮挡及动画时机影响，不是像素级模糊正确性或性能测试。

## 无线连接实测

```powershell
dotnet build Tobatools.csproj --no-restore -p:Platform=x64 -p:OutputPath=bin\wireless-verification\
powershell -NoProfile -ExecutionPolicy Bypass -File Tests/WirelessSmoke.ps1 -ConnectEndpoint 127.0.0.1:5555 -UnreachableEndpoint 10.0.2.15:5555
```

此脚本会实际发起 ADB 连接，只应对明确获准调试的设备使用。默认地址是本次已确认的 MuMu 本机端口；其他环境必须修改参数，且失败地址必须确实无法连接。脚本不自动断开其他设备，也不替用户修改网络、开启 TCP 调试或授权。

使用隔离设置验证输入错误、配对缺端口（不发送真实配对请求）、连接期间窗口保持打开且禁用重复提交、超时后保留错误、真实连接成功关闭并刷新设备栏、记忆成功地址、仪表盘型号和软件管理应用列表。最后关闭自己的窗口，保留已建立的 ADB 连接并清理测试设置。应用枚举可能只读提取图标，不安装、刷写、重启或修改设备文件。Android 11+ 真机配对仍需有配对码的设备单独验证。

## 人工验收

- 云母模式下页面底色应透出系统背景色，开启玻璃后卡片/导航/设备栏及输入表面材质一致，正文仍清晰。
- 关闭 Windows 透明效果、切换高对比度或使用不支持合成的环境，检查纯色回退及设置页状态；恢复系统条件后用户偏好仍保留。
- 模糊滑块拖动时检查交互流畅性；切换外观不得重建工具页面或重置输入。0 表示关闭高斯模糊，但保留玻璃着色与边缘。
- 在浅色、深色、跟随系统主题下切换全部页面，检查文字、卡片边框和禁用态。
- 在常用桌面宽度和窄窗口下检查多栏折叠、按钮换行、长路径和包名；键盘可访问主要操作。
- 无设备时仪表盘显示等待连接、指标显示“—”，软件管理显示页内提示而非初始化弹窗。
- 单台已授权设备接入后，设备栏/仪表盘/镜像辅助状态一致，软件管理能加载应用列表。
- 拔出、更换设备、设备离线或进入 Recovery/Sideload 时，旧信息应清理，软件管理只允许系统模式设备。
- 多设备时软件管理明确提示，不擅自对某一台执行操作。
- 取消卸载/清除数据/冻结确认应不执行命令；确认后的实际设备操作应仅在可丢弃测试应用上进行。
