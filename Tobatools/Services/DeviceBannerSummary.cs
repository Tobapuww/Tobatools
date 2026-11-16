using Tobatools.Models;

namespace Tobatools.Services;

/// <summary>仅缓存当前会话中同一序列号的名称，不借用其他设备的信息。</summary>
public sealed class DeviceBannerSummary
{
    private string _serial = "";
    private string _name = "";

    public string Update(string? serial, string? mode, DeviceInfo? info)
    {
        serial ??= "";
        if (serial != _serial || mode is "none" or "error")
        {
            _serial = serial;
            _name = "";
        }
        if (info != null && info.Serial == serial)
        {
            var model = info.Model.Trim();
            var brand = info.Brand.Trim();
            var preferZh = LocalizationService.Instance.EffectiveLanguageCode == LocalizationService.LangZhCN;
            var marketing = DeviceNameResolver.Instance.Resolve(model, info.Device.Trim(), preferZh);
            if (!string.IsNullOrEmpty(marketing))
                _name = marketing;
            else if (model.Length > 0 && model is not ("-" or "—"))
                _name = brand.Length == 0 || model.StartsWith(brand, System.StringComparison.OrdinalIgnoreCase)
                    ? model : $"{brand} {model}";
        }
        if (mode == null) return "正在检测设备…";
        if (mode == "none") return "未连接设备";
        if (mode == "error") return "设备检测失败";
        var name = _name.Length > 0 ? _name : serial.Length > 0 ? serial : "设备名称未提供";
        var state = mode switch
        {
            "system" => "已连接 · system",
            "recovery" => "已连接 · recovery",
            "sideload" => "已连接 · sideload",
            "bootloader" => "已连接 · bootloader",
            "fastbootd" => "已连接 · fastbootd",
            "edl" => "已连接 · EDL",
            "brom" => "已连接 · BROM",
            "unauthorized" => "等待授权",
            "offline" => "离线",
            _ => "状态未知"
        };
        return $"{name} - {state}";
    }
}
