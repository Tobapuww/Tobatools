using System;
using System.Collections.Generic;
using System.Linq;

namespace Tobatools.Services;

/// <summary>ADB socket 与 adb devices -l 共用解析，忽略 daemon 启动提示和诊断输出。</summary>
public static class AdbDeviceParser
{
    public static List<(string Serial, string State)> Parse(string? output)
    {
        var devices = new List<(string Serial, string State)>();
        foreach (var raw in (output ?? "").Split('\n'))
        {
            var line = raw.Trim();
            if (line.StartsWith("List of devices", StringComparison.OrdinalIgnoreCase) || line.StartsWith('*')) continue;
            var parts = line.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 2) continue;
            if (parts[1] is not ("device" or "offline" or "unauthorized" or "sideload" or "recovery")) continue;
            if (!devices.Any(d => d.Serial == parts[0])) devices.Add((parts[0], parts[1]));
        }
        return devices;
    }

    public static (string Mode, string Serial) SelectMode(IEnumerable<(string Serial, string State)> devices)
    {
        // 未授权设备不能遮蔽列表中后面的在线设备。
        var selected = devices.OrderBy(d => d.State switch
        {
            "device" => 0, "recovery" => 1, "sideload" => 2, "unauthorized" => 3, _ => 4
        }).FirstOrDefault();
        return (selected.State == "device" ? "system" : selected.State ?? "none", selected.Serial ?? "");
    }
}
