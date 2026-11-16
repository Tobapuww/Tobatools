using System;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text.RegularExpressions;

namespace Tobatools.Services;

/// <summary>无线 ADB 地址与结果校验，独立于 UI 和实际设备，便于回归测试。</summary>
public static class WirelessAdb
{
    public static bool TryEndpoint(string? input, bool pairing, out string endpoint, out string error)
    {
        endpoint = "";
        error = "请输入有效的 IP:端口或主机名:端口；IPv6 请使用 [地址]:端口。";
        var value = input?.Trim() ?? "";
        if (value.Length == 0 || value.Any(char.IsWhiteSpace)) return false;
        string host;
        string port = "";
        bool explicitPort;
        if (value.StartsWith('['))
        {
            int end = value.IndexOf(']');
            if (end <= 1) return false;
            var ipText = value[1..end];
            if (!IPAddress.TryParse(ipText, out var ip) || ip.AddressFamily != AddressFamily.InterNetworkV6) return false;
            host = "[" + ipText + "]";
            explicitPort = end + 1 < value.Length;
            if (explicitPort)
            {
                if (value[end + 1] != ':') return false;
                port = value[(end + 2)..];
            }
        }
        else
        {
            var parts = value.Split(':');
            if (parts.Length > 2) return false;
            host = parts[0];
            explicitPort = parts.Length == 2;
            if (explicitPort) port = parts[1];
            if (Uri.CheckHostName(host) == UriHostNameType.Unknown) return false;
            if (host.All(c => char.IsDigit(c) || c == '.') && !IPAddress.TryParse(host, out _)) return false;
        }
        if (!explicitPort)
        {
            if (pairing)
            {
                error = "配对地址必须包含手机配对窗口中显示的端口；它与连接端口不同。";
                return false;
            }
            port = "5555";
        }
        if (!Regex.IsMatch(port, "^[0-9]{1,5}$") || !int.TryParse(port, out var number) || number is < 1 or > 65535)
        {
            error = "端口必须是 1–65535 的整数。";
            return false;
        }
        endpoint = $"{host}:{number}";
        error = "";
        return true;
    }

    public static bool IsPairingCode(string? code) => Regex.IsMatch(code?.Trim() ?? "", "^[0-9]{6}$");

    public static (int Code, string Message) Result(int exitCode, string? output, bool pairing)
    {
        var message = output?.Trim() ?? "";
        var lines = message.Split('\n').Select(line => line.Trim()).ToArray();
        // ADB 的 host 服务及部分 CLI 版本会在失败文本下仍返回 0，必须确认明确成功标记。
        var successPattern = pairing ? "^Successfully paired to \\S+" : "^(already connected to|connected to) \\S+";
        bool success = lines.Any(line => Regex.IsMatch(line, successPattern, RegexOptions.IgnoreCase));
        bool failed = lines.Any(line => Regex.IsMatch(line, "^(?:adb: )?(?:error|failed|cannot|unable)\\b", RegexOptions.IgnoreCase));
        if (exitCode == 0 && success && !failed) return (0, message);
        if (message.Length == 0) message = "ADB 未返回明确的成功信息，请检查地址、端口和设备授权。";
        return (exitCode == 0 ? 1 : exitCode, message);
    }

    public static string FailureHint(string endpoint, string message)
    {
        if (endpoint.StartsWith("10.0.2.15:", StringComparison.Ordinal))
            return "10.0.2.15 常是模拟器内部 NAT 地址。请查看模拟器公布的本机 ADB 映射地址（例如 127.0.0.1:5555），不要直接使用虚拟机内部地址。";
        if (Regex.IsMatch(message, "10060|timed? ?out|timeout|超时", RegexOptions.IgnoreCase))
            return "目标端口未响应。请核对设备当前连接地址、两端网络可达性，以及无线调试是否开启。";
        if (Regex.IsMatch(message, "10061|refused|拒绝", RegexOptions.IgnoreCase))
            return "目标拒绝连接。请核对 ADB 是否监听此端口；Android 无线调试的连接端口不一定是 5555。";
        if (Regex.IsMatch(message, "auth|unauthorized|授权", RegexOptions.IgnoreCase))
            return "请在设备上允许调试授权；Android 11 及以上的无线调试可能需要先配对，再使用无线调试主页的连接端口。";
        return "手机请使用无线调试主页的连接 IP 和端口；配对窗口中的端口只用于配对。模拟器请使用它公布的本机映射端口。";
    }
}
