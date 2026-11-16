using System.Collections.Generic;

namespace Tobatools.Models
{
    /// <summary>设备信息（对应 Python get_device_info / collect_overall_info 的 dict）。</summary>
    public class DeviceInfo
    {
        public string Serial { get; set; } = "";
        public string Brand { get; set; } = "";
        public string Model { get; set; } = "";
        public string Device { get; set; } = "";
        public string Product { get; set; } = "";
        public string AndroidVersion { get; set; } = "";
        public string Sdk { get; set; } = "";
        public string Vndk { get; set; } = "";
        public string BuildDisplay { get; set; } = "";
        public string Fingerprint { get; set; } = "";
        public string Battery { get; set; } = "";
        public string Bootloader { get; set; } = "";
        public string Baseband { get; set; } = "";
        public string CpuInfo { get; set; } = "";
        public string BatteryHealthPercent { get; set; } = "";
        public string BatteryRatedCapacity { get; set; } = "";
        public string BatteryFullCapacity { get; set; } = "";
        public string StorageData { get; set; } = "";
        public string MemoryPercent { get; set; } = "";
        public string MemorySummary { get; set; } = "";
        public string Kernel { get; set; } = "";
        public string CurrentSlot { get; set; } = "";
        public string BootloaderUnlock { get; set; } = "";
        public string Codename { get; set; } = "";
        public string DeviceSerial { get; set; } = "";
        public string Uptime { get; set; } = "";
        public string Resolution { get; set; } = "";
        public string DisplayDensity { get; set; } = "";
        public string StorageType { get; set; } = "";
        public string RootStatus { get; set; } = "";

        /// <summary>连接状态：system/sideload/fastbootd/bootloader/edl/brom/offline/none</summary>
        public string ConnectionStatus { get; set; } = "none";

        public string DisplayName
        {
            get
            {
                var parts = new List<string>();
                if (!string.IsNullOrEmpty(Brand)) parts.Add(Brand);
                if (!string.IsNullOrEmpty(Model)) parts.Add(Model);
                if (!string.IsNullOrEmpty(Device)) parts.Add(Device);
                return parts.Count > 0 ? string.Join(" ", parts) : Serial;
            }
        }
    }
}
