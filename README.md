# 🔥 拖把工具箱 - 全机型通用的安卓刷机工具

> **如果一个 Android 设备已经解锁 Bootloader，  
> 那它就不应该再被任何厂商工具限制。**

---

<p align="center">
  <img src="android-chrome-512x512.png" width="200"/>
</p>

<p align="center">
  <strong>全机型 · 全厂商 · 第三方固件 · 配置文件刷机</strong>
</p>

<p align="center">
  <em>Tobatools 不是"某品牌工具"，而是一个只尊重 Android 底层规则的刷机工具。</em>
</p>

[![License](https://img.shields.io/badge/License-GPL%20v3%20%2B%20Non--Commercial-%239E1E63?style=for-the-badge&logo=gnu&logoColor=white)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13%2B-%233776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Qt/PySide6](https://img.shields.io/badge/Qt%2FPySide6-%2341CD52?style=for-the-badge&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![Fluent Design](https://img.shields.io/badge/Fluent%20Design-%230078D4?style=for-the-badge&logo=windows&logoColor=white)](https://learn.microsoft.com/zh-cn/windows/apps/design/style/fluent-design-system)

---

## 📋 目录

- [✨ 核心特性](#-核心特性)
- [🚀 快速开始](#-快速开始)
- [📖 使用指南](#-使用指南)
- [⚙️ 配置文件](#️-配置文件)
- [🛠️ 功能模块](#️-功能模块)
- [⚠️ 注意事项](#️-注意事项)
- [🤝 贡献指南](#-贡献指南)

---

## ✨ 核心特性

### 🎯 无差别全机型通刷
- **不限品牌**：华为、小米、一加、OPPO、vivo 等支持fastboot的所有安卓品牌
- **不限芯片**：高通、联发科、展锐、三星等绝大多 SoC 平台
- **不限设备**：手机、平板、手表、电视盒子等所有安卓设备
- **不限固件**：官方 ROM、第三方 ROM、移植 ROM、救砖固件

### 🛡️ 安全可靠
- **实时模式检测**：自动识别 ADB/fastboot/fastbootd 模式
- **模式锁定机制**：不同模式对应不同权限，防止误操作
- **分区智能适配**：自动处理 A/B 分区、槽位切换
- **操作日志记录**：所有操作均可追溯，便于问题排查

### 🖥️ 现代化界面
- **Fluent Design**：微软原生设计语言，界面简洁美观
- **多线程异步**：所有操作在后台执行，UI 永不卡顿
- **Win11 特效**：完美支持 Mica 云母质感和 Acrylic 毛玻璃效果
- **实时状态显示**：设备信息、刷机进度实时更新

### 🔧 功能齐全
- **分区刷写**：支持单分区/多分区批量刷写
- **基带管理**：一键备份/还原基带分区
- **文件传输**：双向文件管理，无需 ADB 命令
- **投屏功能**：集成 Scrcpy，USB 投屏无延迟
- **日志查看**：实时日志显示，支持导出分析

---
## 🖥 软件截图
### 一张漂亮的截图胜过千言万语

<p align="center">
  <img src="https://github.com/user-attachments/assets/41299908-050c-45cc-a0ae-1afb4ebc2d8f" width="88%" />
</p>

<p align="center">
  <i>设备信息主界面</i>
</p>

---

<p align="center">
  <img src="https://github.com/user-attachments/assets/ed8ec755-6a68-4a4b-bb71-89a40e85d249" width="88%" />
</p>

<p align="center">
  <i>刷机页界面</i>
</p>

---

<p align="center">
  <img src="https://github.com/user-attachments/assets/238af5c7-31d5-4fdd-8624-24395903ed9b" width="88%" />
</p>

<p align="center">
  <i>投屏页界面</i>
</p>

---

<p align="center">
  <img src="https://github.com/user-attachments/assets/45950074-aefa-4f6f-9642-4916744412a5" width="88%" />
</p>

<p align="center">
  <i>基带备份操作界面</i>
</p>

---

<p align="center">
  <img src="https://github.com/user-attachments/assets/f3e7ddc9-5873-4925-89f2-2ba92945efa3" width="88%" />
</p>

<p align="center">
  <i>杂项工具页界面</i>
</p>





## 🚀 快速开始

### 环境要求
- Python 3.13+
- Windows 10/11
- 已解锁 Bootloader 的安卓设备

### 安装步骤

1. **克隆项目**
```bash
git clone https://github.com/Tobapuww/Tobatools.git
cd Tobatools
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **启动工具**
```bash
python -m app.main
```

### 首次使用
1. 确保设备已解锁 Bootloader
2. 开启 USB 调试模式
3. 用数据线连接电脑并授权
4. 工具会自动识别设备并显示当前状态

---

## 📖 使用指南

### 基础刷机流程

1. **选择刷机模式**
   - 散包刷机：适用于解压后的固件文件夹
   - 压缩包刷机：适用于 zip 格式的固件包
   - ADB Sideload：适用于 sideload 模式刷机
   - 小米线刷：适用于小米线刷脚本

2. **选择固件/配置文件**
   - 点击"选择文件"按钮
   - 选择对应的固件文件或配置脚本
   - 工具会自动解析并显示刷机计划

3. **开始刷机**
   - 点击"开始刷机"按钮
   - 确认设备模式正确
   - 等待刷机完成

### 高级功能

#### 配置文件刷机
- 编写配置文件定义刷机步骤
- 支持模式切换、分区刷写、槽位设置
- 可重复使用，适配无限机型

#### 基带管理
- 备份当前基带分区
- 还原备份的基带
- 自动校验基带完整性

---

## ⚙️ 配置文件

- 有关配置文件的编写方法、下载、拉取请求，请参阅：https://github.com/Tobapuww/Tobatools-config-file
---

## 🛠️ 功能模块

### 设备信息
- 实时显示设备型号、序列号、系统版本
- 显示 SoC 类型、分区信息、AB 槽位状态
- 自动检测设备连接模式

### 刷机功能
- 支持多种刷机模式
- 实时进度显示
- 错误容错处理
- 操作日志记录

### 文件管理
- 双向文件传输
- 分区文件浏览
- 批量上传/下载
- 无需 ADB 命令

### 投屏功能
- 集成 Scrcpy 投屏
- USB 连接无延迟
- 支持设备操作
- 刷机调试两不误

---

## ⚠️ 注意事项

### 重要提醒
- **刷机有风险**：操作前请务必备份重要数据
- **解锁是前提**：设备必须已解锁 Bootloader
- **模式要正确**：确保设备处于正确的连接模式
- **固件要匹配**：使用与设备型号匹配的固件

### 免责声明
本工具为开源免费软件，仅供学习、研究、个人使用。使用本工具产生的任何设备故障、数据丢失等问题，均由使用者自行承担。

---

## 🤝 贡献指南

### 开发原则
- 保持全机型通用的设计理念
- 拒绝硬编码的机型判断
- 通过配置文件实现适配
- 保证代码清晰易维护

### 贡献方式
1. Fork 本项目
2. 创建功能分支
3. 提交代码更改
4. 发起 Pull Request

### Bug 反馈
提交 Issue 时请提供：
- 详细的问题描述
- 设备型号和系统版本
- 操作步骤和错误日志
- 相关的配置文件（如有）

---

## 📄 许可证条款

**Tobatools 基于 GNU General Public License v3.0 发布，并附加以下额外条款：**

### ✅ 你可以：
1. 自由地查看、下载、使用本工具
2. 修改源代码，创建衍生版本
3. 分享给朋友、发布修改后的版本
4. 用于个人学习、研究、非商业项目
5. ROM作者用本工具适配自己的ROM并发布
6. 开发者贡献代码、配置文件

### ❌ 你不可以：
1. 将本工具或其修改版本用于**任何商业用途**
2. 将本工具**集成到商业软件**中销售
3. 倒卖、变卖本工具源代码
4. 基于本工具开发**闭源的商业工具**
5. 在**商业服务**中使用本工具（如收费刷机服务）
6. 未经明确授权，在公司内部商业环境中部署

### 💰 商业授权：
如需商业使用，请联系作者获取商业许可证。

### ⚖️ 开源义务：
基于GPL v3，所有修改版本必须保持开源，并明确标注基于Tobatools。

---
## 🌟 致谢

本项目的 UI 界面基于开源项目 [QFluentWidgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) 开发，感谢 QFluentWidgets的作者@zhiyiYo及贡献者提供的优秀开源控件库。
感谢所有为 Android 开源社区做出贡献的开发者、刷机爱好者，正是因为有你们，安卓的开源精神才得以延续。

---

**Tobatools - 真·全机型通刷，无界刷机，无限可能 ✨**

