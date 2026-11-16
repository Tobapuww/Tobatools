using System;
using System.IO;
using Microsoft.Win32;

namespace Tobatools.Services
{
    /// <summary>
    /// 设置服务：使用注册表 HKCU 持久化（对应 Python QSettings）。
    /// 键名与 Python 版保持一致：update/url、theme/mode、download/dir 等。
    /// </summary>
    public class SettingsService
    {
        public static SettingsService Instance { get; } = new SettingsService();

        // 界面测试使用一次性隔离设置，避免影响用户正在运行的工具实例。
        private static readonly string RegPath = Guid.TryParseExact(
            Environment.GetEnvironmentVariable("TOBATOOLS_TEST_SETTINGS_ID"), "N", out var testId)
                ? @"Software\Tobatools\UiTests\" + testId.ToString("N")
                : @"Software\Tobatools\Settings";

        public string Get(string key, string def = "")
        {
            try
            {
                using var k = Registry.CurrentUser.OpenSubKey(RegPath, false);
                var v = k?.GetValue(key)?.ToString();
                return string.IsNullOrEmpty(v) ? def : v!;
            }
            catch { return def; }
        }

        public void Set(string key, string value)
        {
            try
            {
                using var k = Registry.CurrentUser.CreateSubKey(RegPath, true);
                k?.SetValue(key, value, RegistryValueKind.String);
            }
            catch { }
        }

        public int GetInt(string key, int def = 0)
        {
            var s = Get(key, "");
            return int.TryParse(s, out var v) ? v : def;
        }

        public bool GetBool(string key, bool def = false)
        {
            var s = Get(key, "").Trim().ToLowerInvariant();
            if (s == "1" || s == "true" || s == "yes") return true;
            if (s == "0" || s == "false" || s == "no") return false;
            return def;
        }

        /// <summary>更新源（含旧 URL 迁移逻辑，保持与 Python 版一致）。</summary>
        public string UpdateUrl
        {
            get
            {
                var cur = Get("update/url", "");
                if (cur.Contains("Resilience") && cur.Contains("/.github/workflows/boxver"))
                {
                    cur = "https://gitee.com/AQ16/Resilience/raw/Mellifluous/.github/workflows/boxver";
                    Set("update/url", cur);
                }
                if (string.IsNullOrEmpty(cur))
                {
                    cur = "https://gitee.com/AQ16/Resilience/raw/Mellifluous/.github/workflows/boxver";
                    Set("update/url", cur);
                }
                return cur;
            }
        }
    }
}
