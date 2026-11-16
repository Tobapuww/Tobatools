using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace Tobatools.Services
{
    /// <summary>
    /// 离线机型字典：以型号编号(ro.product.model)为主键、codename(ro.product.device)为兜底键，
    /// 把连接设备的编号补全为传播名(营销名)。字典来自内嵌资源 Data/device_models.json，
    /// 不依赖网络；中文界面取中文名，英文/俄文界面取英文名，缺失时互相回退。
    /// </summary>
    public sealed class DeviceNameResolver
    {
        public static DeviceNameResolver Instance { get; } = new();

        private readonly object _loadLock = new();
        private Dictionary<string, Entry> _byModel = new(StringComparer.OrdinalIgnoreCase);
        private Dictionary<string, string> _codeToModel = new(StringComparer.OrdinalIgnoreCase);
        private bool _loaded;

        private DeviceNameResolver() { }

        private sealed class Entry
        {
            public string Model { get; set; } = "";
            public string Zh { get; set; } = "";
            public string En { get; set; } = "";
            public string Brand { get; set; } = "";
            public string Type { get; set; } = "";
        }

        private void EnsureLoaded()
        {
            if (_loaded) return;
            lock (_loadLock)
            {
                if (_loaded) return;
                var assembly = typeof(DeviceNameResolver).Assembly;
                var resource = assembly.GetManifestResourceNames()
                    .FirstOrDefault(name => name.EndsWith("device_models.json", StringComparison.OrdinalIgnoreCase));
                if (resource == null)
                {
                    _loaded = true;
                    return;
                }

                using var stream = assembly.GetManifestResourceStream(resource)!;
                using var doc = JsonDocument.Parse(stream);

                var byModel = new Dictionary<string, Entry>(StringComparer.OrdinalIgnoreCase);
                var codeToModel = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

                if (doc.RootElement.TryGetProperty("models", out var models))
                {
                    foreach (var el in models.EnumerateArray())
                    {
                        var entry = new Entry
                        {
                            Model = el.TryGetProperty("m", out var m) ? m.GetString() ?? "" : "",
                            Zh = el.TryGetProperty("zh", out var zh) ? zh.GetString() ?? "" : "",
                            En = el.TryGetProperty("en", out var en) ? en.GetString() ?? "" : "",
                            Brand = el.TryGetProperty("b", out var b) ? b.GetString() ?? "" : "",
                            Type = el.TryGetProperty("t", out var t) ? t.GetString() ?? "" : "",
                        };
                        if (!string.IsNullOrEmpty(entry.Model))
                            byModel[entry.Model] = entry;
                    }
                }

                if (doc.RootElement.TryGetProperty("codes", out var codes))
                {
                    foreach (var el in codes.EnumerateArray())
                    {
                        var code = el.TryGetProperty("c", out var c) ? c.GetString() ?? "" : "";
                        var model = el.TryGetProperty("m", out var m) ? m.GetString() ?? "" : "";
                        if (!string.IsNullOrEmpty(code) && !string.IsNullOrEmpty(model))
                            codeToModel.TryAdd(code, model);
                    }
                }

                _byModel = byModel;
                _codeToModel = codeToModel;
                _loaded = true;
            }
        }

        /// <summary>
        /// 按型号编号查询，未命中再用 codename 兜底。返回营销名；字典无记录时返回 null。
        /// </summary>
        /// <param name="model">ro.product.model（编号，如 PYB110）。</param>
        /// <param name="device">ro.product.device（codename，如 OP60EBL1）。</param>
        /// <param name="preferChinese">true 取中文名（缺失回退英文）；false 取英文名（缺失回退中文）。</param>
        public string? Resolve(string? model, string? device, bool preferChinese)
        {
            EnsureLoaded();

            var modelKey = (model ?? "").Trim();
            if (!string.IsNullOrEmpty(modelKey) && _byModel.TryGetValue(modelKey, out var entry))
                return Pick(entry, preferChinese);

            var codeKey = (device ?? "").Trim();
            if (!string.IsNullOrEmpty(codeKey) &&
                _codeToModel.TryGetValue(codeKey, out var linkedModel) &&
                _byModel.TryGetValue(linkedModel, out entry))
                return Pick(entry, preferChinese);

            return null;
        }

        private static string Pick(Entry entry, bool preferChinese)
        {
            if (preferChinese)
                return !string.IsNullOrEmpty(entry.Zh) ? entry.Zh : entry.En;
            return !string.IsNullOrEmpty(entry.En) ? entry.En : entry.Zh;
        }
    }
}
