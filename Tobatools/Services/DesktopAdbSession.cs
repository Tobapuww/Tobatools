using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Tobatools.Models;

namespace Tobatools.Services;

/// <summary>
/// 桌面端 ADB 会话门面。
/// 将 Android 工程中的设备画像、命令执行、文件传输和无线连接职责统一到一个可取消的接口。
/// 这里使用官方 adb.exe，不实现 Binder、UID 伪造或漏洞绕过。
/// </summary>
public sealed class DesktopAdbSession
{
    public sealed record DeviceSnapshot(
        string Serial,
        string State,
        string Mode,
        DeviceInfo? Info,
        string ShellIdentity,
        string SuIdentity,
        string SelinuxState,
        bool HasSu,
        bool IsRoot)
    {
        public bool IsAuthorized => State.Equals("device", StringComparison.OrdinalIgnoreCase);
        public bool IsSystemMode => Mode.Equals("system", StringComparison.OrdinalIgnoreCase);
    }

    public sealed record CommandResult(int ExitCode, string Output, bool TimedOut, bool Cancelled)
    {
        public bool Success => ExitCode == 0 && !TimedOut && !Cancelled;
    }

    public sealed record TransferResult(bool Success, string Output, string LocalPath, string RemotePath);

    public async Task<IReadOnlyList<(string Serial, string State)>> ListDevicesAsync(CancellationToken cancellationToken = default)
    {
        return await Task.Run(() =>
        {
            cancellationToken.ThrowIfCancellationRequested();
            return (IReadOnlyList<(string Serial, string State)>)AdbService.ListDeviceStates();
        }, cancellationToken).ConfigureAwait(false);
    }

    public async Task<DeviceSnapshot> InspectAsync(string serial, CancellationToken cancellationToken = default)
    {
        ValidateSerial(serial);
        var infoTask = Task.Run(() => AdbService.GetDeviceInfo(serial), cancellationToken);
        var shellTask = ShellAsync(serial, new[] { "id" }, 30, cancellationToken);
        var suTask = ShellAsync(serial, new[] { "su", "-c", "id" }, 30, cancellationToken);
        var selinuxTask = ShellAsync(serial, new[] { "getenforce" }, 15, cancellationToken);
        await Task.WhenAll(infoTask, shellTask, suTask, selinuxTask).ConfigureAwait(false);

        var shell = shellTask.Result.Output.Trim();
        var su = suTask.Result.Output.Trim();
        var selinux = selinuxTask.Result.Output.Trim();
        var state = (await ListDevicesAsync(cancellationToken).ConfigureAwait(false))
            .FirstOrDefault(x => string.Equals(x.Serial, serial, StringComparison.Ordinal)).State ?? "unknown";
        var root = IsRootIdentity(su) || IsRootIdentity(shell);
        var hasSu = !string.IsNullOrWhiteSpace(su) && !LooksUnavailable(su);
        return new DeviceSnapshot(serial, state, "system", infoTask.Result, shell, su, selinux, hasSu, root);
    }

    public async Task<CommandResult> ShellAsync(
        string serial,
        IReadOnlyList<string> arguments,
        int timeoutSeconds = 30,
        CancellationToken cancellationToken = default)
    {
        ValidateSerial(serial);
        if (arguments == null || arguments.Count == 0)
            throw new ArgumentException("ADB shell 命令不能为空。", nameof(arguments));
        var result = await ProcessRunner.RunAsync(
            AdbService.AdbBin,
            new[] { "-s", serial, "shell" }.Concat(arguments),
            AppPaths.BinDir,
            timeoutMs: Math.Max(1, timeoutSeconds) * 1000,
            ct: cancellationToken).ConfigureAwait(false);
        return new CommandResult(result.ExitCode, result.Output.Trim(), result.TimedOut, result.Cancelled);
    }

    public async Task<TransferResult> PushAsync(
        string serial,
        string localPath,
        string remotePath,
        int timeoutSeconds = 600,
        CancellationToken cancellationToken = default)
    {
        ValidateSerial(serial);
        if (string.IsNullOrWhiteSpace(localPath) || !File.Exists(localPath))
            throw new FileNotFoundException("本地文件不存在。", localPath);
        if (string.IsNullOrWhiteSpace(remotePath))
            throw new ArgumentException("远程路径不能为空。", nameof(remotePath));
        var result = await ProcessRunner.RunAsync(
            AdbService.AdbBin,
            new[] { "-s", serial, "push", Path.GetFullPath(localPath), remotePath },
            AppPaths.BinDir,
            timeoutMs: Math.Max(1, timeoutSeconds) * 1000,
            ct: cancellationToken).ConfigureAwait(false);
        return new TransferResult(result.Success, result.Output.Trim(), localPath, remotePath);
    }

    public async Task<TransferResult> PullAsync(
        string serial,
        string remotePath,
        string localPath,
        int timeoutSeconds = 600,
        CancellationToken cancellationToken = default)
    {
        ValidateSerial(serial);
        if (string.IsNullOrWhiteSpace(remotePath))
            throw new ArgumentException("远程路径不能为空。", nameof(remotePath));
        var target = Path.GetFullPath(localPath);
        var parent = Path.GetDirectoryName(target);
        if (!string.IsNullOrWhiteSpace(parent)) Directory.CreateDirectory(parent);
        var result = await ProcessRunner.RunAsync(
            AdbService.AdbBin,
            new[] { "-s", serial, "pull", remotePath, target },
            AppPaths.BinDir,
            timeoutMs: Math.Max(1, timeoutSeconds) * 1000,
            ct: cancellationToken).ConfigureAwait(false);
        return new TransferResult(result.Success, result.Output.Trim(), target, remotePath);
    }

    public async Task<CommandResult> InstallAsync(
        string serial,
        string apkPath,
        bool replace = false,
        bool downgrade = false,
        int timeoutSeconds = 600,
        CancellationToken cancellationToken = default)
    {
        ValidateSerial(serial);
        if (string.IsNullOrWhiteSpace(apkPath) || !File.Exists(apkPath))
            throw new FileNotFoundException("APK 文件不存在。", apkPath);
        var args = new List<string> { "-s", serial, "install" };
        if (replace) args.Add("-r");
        if (downgrade) args.Add("-d");
        args.Add(Path.GetFullPath(apkPath));
        var result = await ProcessRunner.RunAsync(
            AdbService.AdbBin,
            args,
            AppPaths.BinDir,
            timeoutMs: Math.Max(1, timeoutSeconds) * 1000,
            ct: cancellationToken).ConfigureAwait(false);
        return new CommandResult(result.ExitCode, result.Output.Trim(), result.TimedOut, result.Cancelled);
    }

    public async Task<CommandResult> RebootAsync(
        string serial,
        string target = "",
        int timeoutSeconds = 60,
        CancellationToken cancellationToken = default)
    {
        ValidateSerial(serial);
        var allowed = new[] { "", "recovery", "bootloader", "edl" };
        if (!allowed.Contains(target, StringComparer.OrdinalIgnoreCase))
            throw new ArgumentException("不支持的重启目标。", nameof(target));
        var args = new List<string> { "-s", serial, "reboot" };
        if (!string.IsNullOrWhiteSpace(target)) args.Add(target);
        var result = await ProcessRunner.RunAsync(
            AdbService.AdbBin,
            args,
            AppPaths.BinDir,
            timeoutMs: Math.Max(1, timeoutSeconds) * 1000,
            ct: cancellationToken).ConfigureAwait(false);
        return new CommandResult(result.ExitCode, result.Output.Trim(), result.TimedOut, result.Cancelled);
    }

    public async Task<(int Code, string Output)> PairAsync(
        string endpoint,
        string pairingCode,
        int timeoutSeconds = 20,
        CancellationToken cancellationToken = default)
    {
        if (!WirelessAdb.TryEndpoint(endpoint, true, out var normalized, out var error))
            throw new ArgumentException(error, nameof(endpoint));
        var code = pairingCode?.Trim() ?? string.Empty;
        if (!WirelessAdb.IsPairingCode(code))
            throw new ArgumentException("配对码必须是 6 位数字。", nameof(pairingCode));
        var result = await ProcessRunner.RunAsync(
            AdbService.AdbBin,
            new[] { "pair", normalized, code },
            AppPaths.BinDir,
            timeoutMs: Math.Max(1, timeoutSeconds) * 1000,
            ct: cancellationToken).ConfigureAwait(false);
        return (result.ExitCode, result.Output.Trim());
    }

    public async Task<(int Code, string Output)> ConnectAsync(
        string endpoint,
        int timeoutSeconds = 20,
        CancellationToken cancellationToken = default)
    {
        if (!WirelessAdb.TryEndpoint(endpoint, false, out var normalized, out var error))
            throw new ArgumentException(error, nameof(endpoint));
        var result = await ProcessRunner.RunAsync(
            AdbService.AdbBin,
            new[] { "connect", normalized },
            AppPaths.BinDir,
            timeoutMs: Math.Max(1, timeoutSeconds) * 1000,
            ct: cancellationToken).ConfigureAwait(false);
        return (result.ExitCode, result.Output.Trim());
    }

    public async Task<(int Code, string Output)> DisconnectAsync(
        string? endpoint = null,
        int timeoutSeconds = 20,
        CancellationToken cancellationToken = default)
    {
        var args = new List<string> { "disconnect" };
        if (!string.IsNullOrWhiteSpace(endpoint))
        {
            if (!WirelessAdb.TryEndpoint(endpoint, false, out var normalized, out var error))
                throw new ArgumentException(error, nameof(endpoint));
            args.Add(normalized);
        }
        var result = await ProcessRunner.RunAsync(
            AdbService.AdbBin,
            args,
            AppPaths.BinDir,
            timeoutMs: Math.Max(1, timeoutSeconds) * 1000,
            ct: cancellationToken).ConfigureAwait(false);
        return (result.ExitCode, result.Output.Trim());
    }

    public static bool IsRootIdentity(string? value) =>
        !string.IsNullOrWhiteSpace(value) && value.Split(new[] { ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
            .Any(token => token.StartsWith("uid=0", StringComparison.OrdinalIgnoreCase));

    private static bool LooksUnavailable(string value) =>
        value.Contains("not found", StringComparison.OrdinalIgnoreCase) ||
        value.Contains("inaccessible", StringComparison.OrdinalIgnoreCase) ||
        value.Contains("denied", StringComparison.OrdinalIgnoreCase) ||
        value.Contains("unknown", StringComparison.OrdinalIgnoreCase);

    private static void ValidateSerial(string serial)
    {
        if (string.IsNullOrWhiteSpace(serial))
            throw new InvalidOperationException("未选择 ADB 设备。");
        var states = AdbService.ListDeviceStates();
        if (!states.Any(x => string.Equals(x.Serial, serial, StringComparison.Ordinal) &&
                             string.Equals(x.State, "device", StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException("目标设备未授权或当前不处于 ADB device 状态。");
    }
}
