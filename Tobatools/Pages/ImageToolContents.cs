using System.Collections.Generic;
using System.Linq;
using Tobatools.Dialogs;

namespace Tobatools.Pages
{
    /// <summary>镜像工厂二级工具注册表；页面布局由工具导航宿主提供。</summary>
    public static class ImageToolContents
    {
        public static readonly IReadOnlyList<ToolDef> All = new List<ToolDef>
        {
            new ToolDef("super", "Super 动态分区工具", "解包 super.img 或从分区镜像打包 super.img", "\uE8B7", SuperToolDialog.Build),
            new ToolDef("dtbo", "DTBO 工具", "解包 + 反编译 dtbo.img，或从 dts 回编译并打包", "\uE8B7", DtboToolDialog.Build),
            new ToolDef("partitionfs", "分区镜像工具", "解包 / 打包 ext4 与 erofs 分区镜像", "\uE8B7", PartitionFsToolDialog.Build),
            new ToolDef("boot", "Boot 镜像工具", "解包 boot 镜像，或打包（magiskboot repack）", "\uE8B7", BootToolDialog.Build),
            new ToolDef("datbr", "OTA 增量包工具", "旧版 DAT/BR 与 IMG 之间互相转换", "\uE8B7", DatBrToolDialog.Build),
        }.AsReadOnly();

        public static ToolDef? Get(string id) => All.FirstOrDefault(tool => tool.Id == id);
    }
}
