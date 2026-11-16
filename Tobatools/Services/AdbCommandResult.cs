using System.Text.RegularExpressions;

namespace Tobatools.Services;

/// <summary>命令退出状态及常见诊断；不把包名中的 error / failure 当成执行失败。</summary>
public static class AdbCommandResult
{
    public static bool IsSuccessful(int exitCode, string? output) => exitCode == 0 &&
        !Regex.IsMatch(output ?? "",
            @"^\s*(?:(?:adb|pm|am):\s*)?(?:Failure\b|Error(?:\s|:|$)|Exception(?:\s|:|$)|(?:java\.\w+\.)?\w*Exception:)|permission denied|not allowed|unknown (command|package)|can't find|cannot find",
            RegexOptions.IgnoreCase | RegexOptions.Multiline);
}
