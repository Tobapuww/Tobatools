# 拖把工具箱 Pro · Tobatools Pro

> 只要一台 Android 设备解锁了 Bootloader，
> 它就不该再被任何厂商工具、任何机型白名单拦住。

基于 **C# + WinUI 3** 的原生 Windows 桌面工具集：固件处理、刷机、投屏、应用与文件管理、分区备份，以及一批按需进入的维护工具。

<p align="left">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL%20v3%20%2B%20Non--Commercial-%239E1E63?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/.NET-10-%23512BD4?style=flat-square&logo=dotnet&logoColor=white" alt=".NET 10">
  <img src="https://img.shields.io/badge/WinUI-3-%230078D4?style=flat-square&logo=windows&logoColor=white" alt="WinUI 3">
  <img src="https://img.shields.io/badge/Windows_app_SDK-1.8-%230078D4?style=flat-square" alt="Windows App SDK 1.8">
  <img src="https://img.shields.io/badge/Windows-10%201809%2B-%230078D4?style=flat-square&logo=windows&logoColor=white" alt="Windows 10 1809+">
  <img src="https://img.shields.io/badge/Version-2.0.1-%2326A5E4?style=flat-square" alt="Version 2.0.1">
</p>

<p align="left">
  <a href="https://tobatools.top"><img src="https://img.shields.io/badge/官网-tobatools.top-%2326A5E4?style=flat-square" alt="Website"></a>
  <a href="https://t.me/tuoba1213141647"><img src="https://img.shields.io/badge/TG-拖把工具箱-%2326A5E4?style=flat-square&logo=telegram&logoColor=white" alt="Telegram"></a>
  <a href="https://qm.qq.com/q/iBPCO3Xrjy"><img src="https://img.shields.io/badge/QQ群-294122499-%2312B7F5?style=flat-square&logo=tencent-qq&logoColor=white" alt="QQ Group"></a>
</p>

---

## 目录

- [这个工具是什么](#这个工具是什么)
- [能力一览](#能力一览)
- [普通用户：安装与使用](#普通用户安装与使用)
- [功能详解](#功能详解)
- [刷机指南](#刷机指南)
- [常见问题](#常见问题)
- [开发者：项目结构](#开发者项目结构)
- [开发者：构建与运行](#开发者构建与运行)
- [开发者：命令行调试模式](#开发者命令行调试模式)
- [开发者：添加新页面](#开发者添加新页面)
- [开发者：测试](#开发者测试)
- [致谢与许可证](#致谢与许可证)

---

## 这个工具是什么

Tobatools 不是"某品牌的专用刷机助手"，它的设计前提是：**设备解锁之后，控制权应当回到使用者手上**。

所以它：

- **不限品牌、不限芯片**。判断依据是设备自身反馈的 fastboot 变量、分区表与配置文件，而不是一份不断过期的机型白名单。
- **面向文件而不是面向机型**。拿到一份固件、一个 `payload.bin`、一个 `super.img`、一个 `boot.img`，工具负责把它拆开、处理、再装回去。
- **不做隐藏动作**。所有设备命令的原始输出都保留在日志里，出错时你看到的是真实回显，不是一句"操作失败"。

实现上，它是一套**原生 Windows 应用**（C# + WinUI 3 + Windows App SDK 1.8），不是 Electron、不是 Python 打包壳，启动与内存占用按普通桌面软件的标准来。所有外部依赖（adb、fastboot、7z、scrcpy 等）随包下发，解压即用，不需要另装 SDK。

---

## 能力一览

| 模块 | 做什么 |
|---|---|
| **仪表盘** | 设备连接模式与状态、电池 / 存储 / 内存实时读数、硬件参数与系统信息、快捷操作 |
| **镜像工厂** | 7 类镜像处理（方案参考 [TIK](https://github.com/ColdWindScholar/TIK)）：`payload.bin`、`.ofp` 固件、`super.img` 动态分区、`dtbo.img` 设备树、ext4 / erofs 分区镜像、`boot` 镜像、OTA 增量包 DAT/BR |
| **刷机中心** | 智能一键刷机：镜像目录或固件包作为来源，自动生成刷机计划并执行；带刷机环境前置检查 |
| **投屏中心** | 内置 scrcpy，可调分辨率 / 帧率 / 码率 / 缓冲与窗口行为，在独立窗口操作设备 |
| **软件管理** | 浏览已安装应用、安装 APK、导出 APK、卸载与组件管理 |
| **文件管理** | 浏览设备存储，在电脑与设备之间双向传输文件 |
| **基带备份** | 扫描并选择分区备份，可选打包 ZIP、生成本地恢复脚本 |
| **杂项工具箱** | 16 个维护工具，分「常用 / 高级 / 模拟控制」三类，按需进入独立操作页 |
| **设置** | 主题与液态玻璃外观、界面语言（简体中文 / English / Русский）、下载目录、版本与社区入口 |

> **关于"刷机中心"**：该模块的实现（分区刷写顺序、机型判定表、固件解包密钥、远程控制软件检测规则）不随公开仓库发布。克隆公开仓库自行构建时，刷机导航项会自动隐藏；官方发行版包含该功能。

---

## 普通用户：安装与使用

### 系统要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10 1809（17763）及以上，Windows 11 推荐 |
| 架构 | x64（发行包为 `win-x64`；源码可编译 x86 / ARM64） |
| 运行时 | .NET 10 桌面运行时 + Windows App Runtime 1.8（**启动器会自动检查并安装**） |
| 设备 | 已解锁 Bootloader 的 Android 设备，开启 USB 调试 |

### 首次运行

1. 下载并 **完整解压** 发行包（不要在压缩包内直接双击运行）。
2. 双击 `TobatoolsLauncher.exe`。
   - 启动器会先检查 .NET 10 桌面运行时与 Windows App Runtime 1.8；
   - 缺失时弹窗询问，可用 winget 或官方直链自动安装（需要管理员权限）；
   - 安装过程写入同目录 `launcher.log`，出问题先看这个文件。
3. 依赖齐全后启动器自动拉起 `Tobatools.exe`。之后也可以直接运行主程序。

### 连接设备

1. 手机进入 **开发者选项 → USB 调试**，用数据线连接电脑并在手机上点「允许调试」。
2. 打开应用，仪表盘会自动识别设备，显示模式（`adb` / `fastboot` / `fastbootd`）、序列号与硬件信息。
3. 需要无线调试时，在仪表盘点「无线连接」，填入配对地址与配对码，或使用 USB 首次配对后转为无线。

> 除仪表盘外的其他页面顶部有一条设备栏，显示当前设备概览；可在页内「收起设备栏」，收起状态会记忆。

---

## 功能详解

### 仪表盘

连接状态与设备信息的集中视图。电池 / 存储 / 内存三个环形读数，硬件参数（品牌、型号、CPU、分辨率、DPI、存储类型、电池健康与容量）与系统信息（Android 版本、SDK、内核、VNDK、Bootloader 锁状态、Root 状态、当前 A/B 槽位、本次开机时间）。

快捷操作区提供：电源菜单（按目标模式重启设备）、重启 ADB 服务、无线调试、打开设备管理器，以及常用工具的直接执行入口。

### 镜像工厂

> 镜像解打包方案参考自 [TIK](https://github.com/ColdWindScholar/TIK)（GPL-3.0，另附非商业条款）。

按文件类型选择工具，每个工具都是独立操作页——进入、处理、返回，不再弹一堆对话框：

| 分组 | 工具 | 说明 |
|---|---|---|
| 固件源处理 | Payload.bin 解包 | 在线或本地提取 `payload.bin`，支持全量与指定分区 |
| 固件源处理 | OFP 解包 | 解密并提取 `.ofp` 固件内容 |
| 动态分区 / Super | Super 解 / 打包 | 拆分 `super.img` 或从分区目录重新打包，可设组名 / 元数据 / 块大小 / 稀疏 |
| 设备树 / DTBO | DTBO 解 / 打包 | 解包 + 反编译 `dtbo.img`，或从 `.dts` 目录回编译打包 |
| 文件系统 / 分区镜像 | ext4 与 erofs 解 / 打包 | 自动识别文件系统类型；打包可设标签、挂载点、块大小与目标大小 |
| Boot 镜像 | Boot 解 / 打包 | 解包启动镜像，或用 `magiskboot` 重新打包 |
| OTA 增量包（DAT/BR） | DAT/BR 转换 | 旧版 `new.dat` / `.br` 与 `img` 之间互相转换 |

### 刷机中心

两种来源：**镜像目录**（已解压的散包）与 **固件包**（压缩包，分 OTA zip、NewPort 7z、ColorOS 17 7z、旧版四类解包模式）。选定后工具扫描镜像、生成刷机计划并展示，勾选「清除数据」「保留 Root」后执行。

执行前会做**刷机环境检查**：若本机存在会抢占 USB 设备的远程控制类软件，会直接拦下，避免刷到一半连接被截走。

刷写过程中的全部原始输出进入日志面板，可另存为文件或直接打开日志目录。

### 投屏中心

基于内置 scrcpy，可调：分辨率、帧率、码率、视频缓冲、音频缓冲与音频开关；窗口行为可选项包括全屏启动、无边框、置顶、禁用屏保、保持唤醒、息屏投屏、显示触摸、剪贴板同步、兼容粘贴、转发所有点击、打印 FPS。点「开始投屏」后设备画面出现在独立窗口。

### 软件管理

浏览设备已安装应用（可按名称或包名搜索，可选是否包含系统应用），支持把电脑上的 APK 安装到设备（含「覆盖安装」「允许降级」选项）、导出已安装应用为 APK、卸载，以及查看与应用/组件相关的信息。右侧面板可实时显示当前前台应用包名与 Activity。

### 文件管理

浏览设备存储，右键菜单提供打开、导出、复制、剪切、粘贴、重命名、删除、属性、导入文件、导入文件夹；双击进入目录，支持把选中项拉取到本地。右侧实时显示传输进度，并附使用提示（Android 11+ 的 `Android/data` 等目录受系统权限限制，可能无法访问）。

### 基带备份

扫描设备分区列表并勾选目标分区（基带、EFS 等维护类分区），可选项：

- 将备份分区打包成一个 ZIP；
- 生成本地恢复脚本（`flash_all.bat` / `.sh`）。

恢复脚本建议自己核对后再执行，**不要跨设备恢复基带分区**。

### 杂项工具箱

16 个工具分三组，全部是独立二级页面（Win11 设置式导航，带面包屑返回）：

- **常用工具**：单分区刷入、Payload.bin 处理、OFP 处理
- **高级操作**：启动异常修复（移除异常模块）、Magisk 模块管理（列表 / 启用 / 禁用 / 备份 / 移除 / 安装 / 批量安装）、ADB 开发终端、运行开发维护脚本、刷机配置文件检测
- **模拟控制**：显示属性修改（分辨率 / DPI / 最小宽度）、电池状态模拟、锁屏时间修改、隐藏状态栏图标、字体缩放、动画速度、一键关闭辅助功能、模拟按键

### 设置

- **外观**：浅色 / 深色 / 跟随系统；可开启液态玻璃（模糊半径 0–64 可调）
- **界面语言**：简体中文 / English / Русский（切换后需重启应用）
- **下载目录**：下载类操作的默认落盘位置
- **关于**：版本信息、检查更新、官网、QQ 群、Telegram

---

## 刷机指南

### 刷机前必须确认

1. **固件与机型匹配**。刷错固件是变砖最常见的原因，工具不会拦你，也不会替你判断。
2. **设备已进入 Bootloader / fastbootd**，且数据线连接稳定（直连主板 USB 口优于前置面板与 Hub）。
3. **电量充足**（建议 50% 以上）。
4. **数据已备份**。勾选「清除数据」后，用户数据不可恢复。

### 推荐流程

```
确认机型与固件 → 备份重要分区（基带备份页）→ 进入 fastboot → 选择来源
→ 核对刷机计划 → 执行 → 观察日志至结束 → 首次开机会较慢，耐心等待
```

### 出问题怎么办

- **改过 Magisk 模块导致开不了机**：用「启动异常修复」移除模块配置，或进 Recovery 处理后重试。
- **刷完卡在启动动画**：多数是固件不匹配或漏刷分区，回退到完整固件包重刷。
- **设备无法进入 fastboot**：本工具走的是 ADB 与 fastboot 通道，EDL / 9008 模式下的恢复需要厂商线刷工具。

---

## 常见问题

**Q：为什么不直接双击 Tobatools.exe？**
A：可以，前提是机器已装 .NET 10 桌面运行时与 Windows App Runtime 1.8。用启动器是为了在缺依赖的干净系统上自动补齐，并留下 `launcher.log` 便于排查。

**Q：启动器提示缺组件，自动安装失败怎么办？**
A：手动执行 `winget install Microsoft.DotNet.DesktopRuntime.10` 与 `winget install Microsoft.WindowsAppRuntime.1.8`，或按弹窗提示到官网下载安装包。

**Q：我的源码构建里没有"刷机"这一页？**
A：正常。刷机模块不随公开仓库发布，构建时检测不到对应目录会自动跳过，其余功能不受影响。

**Q：设备连上了但页面显示"未连接"？**
A：确认 USB 调试已授权、`adb devices` 能看到设备且状态为 `device` 而非 `unauthorized`。模式不对时先在仪表盘执行「重启 ADB 服务」。

**Q：杀毒软件报警？**
A：工具会调用 adb / fastboot 并对分区写入，行为与刷机工具一致，可能触发启发式告警。若来源可信可加白名单；不建议关闭实时防护。

---

## 开发者：项目结构

仓库根即 `Tobatools/` 目录，单一 WinUI 3 工程（`Tobatools.csproj`），外围另有 `Launcher/`（依赖引导启动器）。

```
Tobatools/
├─ Tobatools.csproj           # .NET 10 / WinUI 3 / 条件编译 ENABLE_FLASH
├─ Program.cs                 # 自定义入口：--cli 走命令行，否则走 WinUI
├─ App.xaml(.cs) / MainWindow.xaml(.cs)   # 应用外壳与导航
├─ Styles.xaml                # 全局视觉语言（颜色、字体、卡片、按钮、间距）
│
├─ Pages/                     # 顶层页面
│   ├─ DashboardPage / ImageFactoryPage / ScrcpyPage / SoftwareManagerPage
│   ├─ FileManagerPage / BackupPage / MiscPage / SettingsPage
│   ├─ MiscToolPage.xaml(.cs)         # 二级工具页通用宿主（面包屑 + 内容区）
│   ├─ MiscToolContents.cs            # 杂项 16 个工具的内容工厂
│   └─ ImageToolContents.cs           # 镜像工厂 7 个工具的内容工厂
├─ Controls/                  # 可复用控件：DeviceBar / LogView / RingGauge /
│                             # PageHeader / ResponsiveColumns / AdaptiveCards / IconPath
├─ Dialogs/                   # 仍需弹窗的场景：无线连接、模块安装窗口、公共对话框设施
├─ Logic/                     # 与 UI 无关的纯处理逻辑
│   ├─ PayloadExtractor / OfpProcessor / ModuleManager
│   └─ ImageFactory/          # Ext4Volume / LpUnpack / Mkdtboimg / ImageTools / Basics
├─ Services/                  # 设备与应用服务层
│   ├─ DeviceSession / AdbService / WirelessAdb / DesktopAdbSession / InteractiveShell
│   ├─ ProcessRunner / ExternalTools / AppPaths          # 外部命令与路径
│   ├─ SettingsService / LocalizationService / AppearanceService
│   └─ KernelImageAnalysisService / OfflineImageAnalysisService
├─ Cli/                       # 命令行调试模式（CliHost / CliCommands / CliRunner）
├─ Private/Flash/             # 【闭源】刷机模块：FastbootService / FlashPlanBuilder /
│                             # FlashSession / ArchiveExtractor / FlashEnvironmentGuard
├─ Strings/{zh-CN,en-US,ru-RU}/   # Pages.resw / Resources.resw 翻译目录（编译内嵌）
├─ Data/device_models.json    # 机型基础数据
├─ Assets/                    # icon.png / app.ico
├─ tools/                     # 随包下发的外部工具（见下）
├─ Docs/                      # 设计说明：NewPage / WirelessConnection
└─ Tests/                     # 回归与 UI 冒烟测试（不参与主工程编译）
```

**外部工具链**（`tools/`）：`adb`、`fastboot`、`7z`、`scrcpy`（含 `scrcpy-server`）、`payload-dumper-go`、`lpmake`、`mke2fs`、`zstd`、`sqlite3`、`aapt`、`etc1tool` 等第三方二进制。**源码仓库不附带这些二进制**，仅在官方发行版中打包；基于源码自行构建时需按 `AppPaths` 定位自备工具，各组件许可证汇总见 `tools/NOTICE.txt`。

### 分层约定

- **Logic/** 只依赖 BCL，不引用 XAML，可被 CLI 与测试直接调用；
- **Services/** 负责设备状态、进程、配置、本地化等有状态的东西；
- **Pages/** 只做界面与交互编排，复杂业务下沉到 Logic/Services；
- **Controls/** 是无业务含义的可复用控件。

这条边界的实际好处是：每个页面背后的逻辑都能用 `--cli` 在真机上单独验证，不需要点界面。

---

## 开发者：构建与运行

### 环境

- .NET SDK **10.0**（`dotnet --version` 应输出 10.x）
- Visual Studio 2022（可选，用于 XAML 设计器）或任意编辑器
- Windows 10 1809+

### 构建

```powershell
cd Tobatools
dotnet build Tobatools.csproj -c Debug -p:Platform=x64
```

产物位于 `bin\x64\Debug\net10.0-windows10.0.26100.0\Tobatools.exe`。

> 编译前请关闭正在运行的 `Tobatools.exe`，否则会因文件占用失败（MSB3027）。若遇到 `XamlCompiler` 抛 `MSB3073` 且看不到具体报错，先清理 `obj\x64` 再重试，这类错误多数是 C# 编译错误被掩盖。

### 发布

```powershell
dotnet publish Tobatools.csproj -c Release -p:Platform=x64 -r win-x64
```

几个与体积相关的工程决策，改动前请理解原因：

- `WindowsAppSDKSelfContained=false`：依赖系统已安装的 Windows App Runtime，避免把 SDK 运行时塞进包内（体积从约 180 MB 降到约 100 MB）；
- `ExcludeAiRuntimeFromPublish`：WindowsAppSDK 元包会把 onnxruntime / DirectML 作为传递依赖带入（约 38 MB），本项目不做任何 AI 推理，发布时排除；
- `SatelliteResourceLanguages=zh-CN;en-US;ru-RU`：剔除其余 70 多种语言的资源。

### 刷机模块的条件编译

`Private/Flash/` 不在公开仓库中（`.gitignore` 已排除，其中包含分区刷写顺序、机型判定表与固件解包密钥）。`Tobatools.csproj` 通过目录是否存在自动开关：

```xml
<HasFlashModule Condition="Exists('$(FlashPrivateDir)\Pages\FlashPage.xaml')">true</HasFlashModule>
```

存在则定义 `ENABLE_FLASH` 并编译；不存在则从编译项中移除 `Private\**`，代码中所有相关引用用 `#if ENABLE_FLASH` 包裹，`MainWindow` 会移除对应导航项。**克隆公开仓库后缺少该目录属正常现象，构建不会报错。**

---

## 开发者：命令行调试模式

任何需要对着真机验证的逻辑，都可以不打开界面直接跑：

```powershell
Tobatools.exe --cli help
```

主要子命令（完整列表见 `--cli help`）：

```powershell
# 设备
Tobatools.exe --cli devices
Tobatools.exe --cli info
Tobatools.exe --cli shell --cmd "getprop ro.product.model"
Tobatools.exe --cli setting --get global airplane_mode_on

# 杂项工具的逻辑（工具 ID 与界面注册表一致）
Tobatools.exe --cli misc animscale
Tobatools.exe --cli misc display

# 模块与救砖
Tobatools.exe --cli modules --list
Tobatools.exe --cli modules --disable <模块ID>
Tobatools.exe --cli unbrick --yes

# 镜像处理
Tobatools.exe --cli payload --in payload.bin --out out
Tobatools.exe --cli ofp --in firmware.ofp --out out
Tobatools.exe --cli image super unpack --in super.img --project work
Tobatools.exe --cli ext4dump --in system.img

# 刷机模块（仅含 Private/Flash 的构建）
Tobatools.exe --cli flashplan --dir images --wipe --json plan.json
Tobatools.exe --cli flashguard
Tobatools.exe --cli flashprobe
```

设计原则：**命令行不引入界面之外的新功能**，它只是同一套 Logic/Services 的另一个入口，因此用它验证的结果与界面行为一致。`flashplan` 这类命令只导出计划、不执行刷写，适合在没有设备时做计划比对。

---

## 开发者：添加新页面

约定与约束见 `Docs/NewPage.md`，要点：

1. **顶层页面**：在 `Pages/` 新建 `XxxPage.xaml(.cs)`，`MainWindow.xaml` 增加 `NavigationViewItem`（`Tag` 与 `Navigate()` 的 `switch` 分支对应），并在 `Resources.resw` 补 `NavXxx` / `NavXxxTooltip` 键。
2. **工具类子页面**：无需新建页面。在 `MiscToolContents.cs`（或 `ImageToolContents.cs`）的注册表里加一条 `ToolDef`，再实现一个 `Build()` 内容工厂即可——`MiscToolPage` 会自动处理面包屑、标题、返回导航。
3. **文案一律走资源**：XAML 用 `{loc:Loc Key=Pages/Xxx_001}`，不要硬编码中文字符串，否则切换语言后仍显示中文。
4. **颜色与样式取自 `Styles.xaml` 的语义资源**（`AppCanvasBrush` / `CardBorderStyle` / `IconBadgeStyle` / `PageHeader` 等），不要在各页面自造色值，否则深浅主题切换会错色。
5. **响应式**：多栏布局用 `ResponsiveColumns`，不要在固定宽度里硬排两列。

---

## 开发者：测试

`Tests/` 下的工程与脚本不参与主程序编译，全部为本地验证手段。

```powershell
# 逻辑回归（52 项，使用模拟 ADB，不接触真机）
dotnet run --project Tests/Regression.csproj

# 本机 ADB 只读核验（只查询，不修改设备）
dotnet run --project Tests/AdbReadOnly.csproj

# 界面冒烟（UI Automation：九个导航页、主题切换、窄宽布局）
powershell -NoProfile -ExecutionPolicy Bypass -File Tests/UiSmoke.ps1

# 工具导航冒烟（镜像工厂全部工具、杂项子页、面包屑返回、设备栏记忆）
powershell -NoProfile -ExecutionPolicy Bypass -File Tests/ToolNavigationSmoke.ps1

# 语言与外观专项
powershell -NoProfile -ExecutionPolicy Bypass -File Tests/LanguageSmoke.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File Tests/AppearanceSmoke.ps1

# 无线连接实测（仅对接入获准调试的设备）
powershell -NoProfile -ExecutionPolicy Bypass -File Tests/WirelessSmoke.ps1 -ConnectEndpoint 127.0.0.1:5555
```

这些脚本只做启动、导航与控件存在性检查，**不点击安装、刷写、删除、重启、备份等实际动作**，也不能替代真实设备测试。

---

## 贡献

- 保持"按文件、按规范处理，而不是按机型白名单"的设计理念；
- 不硬编码机型判断，适配逻辑走配置文件与数据表；
- 提交前确保 `dotnet build` 零警告零错误，新增文案补齐三种语言的 resw；
- 界面改动请同时检查浅色 / 深色主题与 900 / 1440 两种窗口宽度。

反馈问题时请附上：设备型号与系统版本、操作步骤、`launcher.log`（启动问题）或日志面板导出的文件（刷机问题）。

---

## 致谢与许可证

感谢所有为 Android 开源社区贡献过的开发者与刷机爱好者——安卓的开源精神正因此才得以延续。界面遵循 Microsoft Fluent Design / WinUI 3 的设计规范。

镜像处理（`super.img` / `dtbo.img` / `boot` / ext4 / erofs 分区镜像、`payload.bin`、`.ofp` 的解打包）方案参考自 [TIK](https://github.com/ColdWindScholar/TIK)（GPL-3.0，另附非商业条款）；其余部分参考 AOSP 与社区开源工具的实现思路。

**许可证：GNU General Public License v3.0 + 附加非商业条款**（完整条款见仓库根 `LICENSE`）。

- ✅ 可查看、使用、修改、分发，可用于个人学习、研究与非商业项目；ROM 作者可用其适配并发布自己的 ROM。
- ❌ 不得用于任何商业用途，不得集成进商业软件销售，不得倒卖源码，不得基于本项目开发闭源商业工具，不得在收费刷机等商业服务中使用。
- 💰 商业使用请联系作者获取商业授权。
- ⚖️ 依 GPL v3，修改版本必须保持开源并注明基于 Tobatools。

**免责声明**：本工具为开源免费软件，仅供学习、研究与个人使用。刷机涉及分区写入，存在变砖与数据丢失风险；请先备份并确认固件匹配。因使用本工具造成的任何设备故障与数据损失，由使用者自行承担。

---

<p align="left"><strong>Tobatools Pro · 真·全机型通刷，无界刷机，无限可能。</strong></p>
