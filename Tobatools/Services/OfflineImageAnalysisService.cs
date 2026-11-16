using System;
using System.Buffers.Binary;
using System.IO;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;

namespace Tobatools.Services;

/// <summary>
/// 本地 Android 镜像分析器。
/// 只读取用户明确选择的文件，不修改设备、不执行镜像中的代码，也不实现漏洞利用。
/// </summary>
public sealed class OfflineImageAnalysisService
{
    private const int ProbeSize = 4096;
    private const long MaxAnalysisBytes = 8L * 1024 * 1024 * 1024;

    public enum ImageKind
    {
        Unknown,
        AndroidBoot,
        RawArm64Image,
        Gzip,
        Lz4,
        Elf64,
        Zip,
    }

    public sealed record ImageReport(
        string Path,
        long Size,
        string Sha256,
        ImageKind Kind,
        string Magic,
        bool IsArm64,
        int? BootHeaderVersion,
        uint? PageSize,
        ulong? KernelOffset,
        ulong? KernelSize,
        string Architecture,
        string Notes);

    public async Task<ImageReport> AnalyzeAsync(string path, CancellationToken cancellationToken = default)
    {
        var fullPath = ValidatePath(path);
        var info = new FileInfo(fullPath);
        if (info.Length > MaxAnalysisBytes)
            throw new InvalidDataException($"镜像文件超过分析上限（{MaxAnalysisBytes / 1024 / 1024 / 1024} GiB）。");

        var probe = await ReadProbeAsync(fullPath, cancellationToken).ConfigureAwait(false);
        var hash = await ComputeSha256Async(fullPath, cancellationToken).ConfigureAwait(false);
        return ParseReport(fullPath, info.Length, hash, probe);
    }

    public async Task<string> ExtractKernelAsync(
        string imagePath,
        string outputPath,
        CancellationToken cancellationToken = default)
    {
        var report = await AnalyzeAsync(imagePath, cancellationToken).ConfigureAwait(false);
        if (report.KernelOffset is not ulong offset || report.KernelSize is not ulong size)
            throw new InvalidDataException("该文件不是包含可直接提取内核段的 Android boot 镜像。");
        if (size == 0 || size > int.MaxValue * 4L)
            throw new InvalidDataException("内核段大小无效。");
        if (offset > long.MaxValue || offset + size > (ulong)new FileInfo(report.Path).Length)
            throw new InvalidDataException("内核段超出镜像文件范围。");

        var target = Path.GetFullPath(outputPath);
        var parent = Path.GetDirectoryName(target);
        if (!string.IsNullOrWhiteSpace(parent)) Directory.CreateDirectory(parent);
        await using var source = new FileStream(report.Path, FileMode.Open, FileAccess.Read, FileShare.Read, 1024 * 1024, useAsync: true);
        await using var destination = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None, 1024 * 1024, useAsync: true);
        source.Position = (long)offset;
        var remaining = size;
        var buffer = new byte[1024 * 1024];
        while (remaining > 0)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var requested = (int)Math.Min((ulong)buffer.Length, remaining);
            var read = await source.ReadAsync(buffer.AsMemory(0, requested), cancellationToken).ConfigureAwait(false);
            if (read <= 0) throw new EndOfStreamException("读取内核段时提前到达文件末尾。");
            await destination.WriteAsync(buffer.AsMemory(0, read), cancellationToken).ConfigureAwait(false);
            remaining -= (ulong)read;
        }
        return target;
    }

    public static string FormatSummary(ImageReport report)
    {
        var kernel = report.KernelSize is ulong size ? $"，内核段 {size:N0} 字节" : string.Empty;
        var version = report.BootHeaderVersion is int v ? $"，Boot v{v}" : string.Empty;
        return $"{report.Kind}，{report.Size:N0} 字节，SHA-256={report.Sha256}{version}{kernel}";
    }

    private static ImageReport ParseReport(string path, long size, string sha256, byte[] probe)
    {
        var magic = GetMagic(probe);
        if (StartsWith(probe, "ANDROID!"u8))
        {
            var pageSize = ReadUInt32(probe, 36);
            var kernelSize = ReadUInt32(probe, 8);
            var version = DetectBootHeaderVersion(probe, size, pageSize);
            var kernelOffset = pageSize;
            return new ImageReport(path, size, sha256, ImageKind.AndroidBoot, magic, false, version,
                pageSize == 0 ? null : pageSize, kernelSize == 0 ? null : kernelOffset,
                kernelSize == 0 ? null : kernelSize, "Android boot image", "仅解析容器头，未执行镜像内容。");
        }

        if (IsArm64Image(probe))
        {
            var imageSize = ReadUInt64(probe, 0x10);
            return new ImageReport(path, size, sha256, ImageKind.RawArm64Image, magic, true, null, null, 0,
                imageSize == 0 || imageSize > (ulong)size ? (ulong)size : imageSize,
                "AArch64", "检测到 Linux ARM64 Image 头。");
        }

        if (StartsWith(probe, new byte[] { 0x1f, 0x8b }))
            return new ImageReport(path, size, sha256, ImageKind.Gzip, magic, false, null, null, null, null, "未知", "检测到 gzip 压缩流，需要离线解压后继续分析。");
        if (StartsWith(probe, new byte[] { 0x02, 0x21, 0x4c, 0x18 }))
            return new ImageReport(path, size, sha256, ImageKind.Lz4, magic, false, null, null, null, null, "未知", "检测到 LZ4 压缩流，需要离线解压后继续分析。");
        if (StartsWith(probe, new byte[] { 0x7f, (byte)'E', (byte)'L', (byte)'F' }))
        {
            var is64 = probe.Length > 5 && probe[4] == 2;
            var machine = probe.Length >= 20 ? BinaryPrimitives.ReadUInt16LittleEndian(probe.AsSpan(18, 2)) : 0;
            var arch = machine == 183 ? "AArch64" : $"ELF machine {machine}";
            return new ImageReport(path, size, sha256, is64 ? ImageKind.Elf64 : ImageKind.Unknown, magic, machine == 183, null, null, null, null, arch, "检测到 ELF 文件头。");
        }
        if (StartsWith(probe, new byte[] { (byte)'P', (byte)'K', 0x03, 0x04 }))
            return new ImageReport(path, size, sha256, ImageKind.Zip, magic, false, null, null, null, null, "未知", "检测到 ZIP 容器，可继续识别 OTA 分区文件。");

        return new ImageReport(path, size, sha256, ImageKind.Unknown, magic, false, null, null, null, null, "未知", "未识别的镜像容器格式。");
    }

    private static int? DetectBootHeaderVersion(byte[] probe, long fileSize, uint pageSize)
    {
        if (pageSize == 0) return null;
        // v1 在传统 boot header 后增加 recovery_dtbo_size；v2 继续增加 dtb_size。
        // 这里仅依据字段是否落在文件范围内做保守识别，不把猜测当成确定版本。
        var v1Field = ReadUInt32(probe, 1632);
        var v2Field = ReadUInt32(probe, 1648);
        if (v2Field > 0 && v2Field < fileSize) return 2;
        if (v1Field > 0 && v1Field < fileSize) return 1;
        return 0;
    }

    private static bool IsArm64Image(byte[] data) =>
        data.Length >= 0x3c && data[0x38] == (byte)'A' && data[0x39] == (byte)'R' &&
        data[0x3a] == (byte)'M' && data[0x3b] == (byte)'d';

    private static uint ReadUInt32(byte[] data, int offset) =>
        data.Length >= offset + 4 ? BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset, 4)) : 0;

    private static ulong ReadUInt64(byte[] data, int offset) =>
        data.Length >= offset + 8 ? BinaryPrimitives.ReadUInt64LittleEndian(data.AsSpan(offset, 8)) : 0;

    private static bool StartsWith(byte[] data, ReadOnlySpan<byte> prefix) =>
        data.AsSpan().StartsWith(prefix);

    private static string GetMagic(byte[] data)
    {
        var length = Math.Min(16, data.Length);
        return Convert.ToHexString(data, 0, length).ToLowerInvariant();
    }

    private static string ValidatePath(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            throw new FileNotFoundException("镜像文件不存在。", path);
        return Path.GetFullPath(path);
    }

    private static async Task<byte[]> ReadProbeAsync(string path, CancellationToken cancellationToken)
    {
        var buffer = new byte[ProbeSize];
        await using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, ProbeSize, useAsync: true);
        var read = await stream.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false);
        if (read == buffer.Length) return buffer;
        Array.Resize(ref buffer, read);
        return buffer;
    }

    private static async Task<string> ComputeSha256Async(string path, CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 1024 * 1024, useAsync: true);
        using var sha = SHA256.Create();
        var buffer = new byte[1024 * 1024];
        int read;
        while ((read = await stream.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false)) > 0)
            sha.TransformBlock(buffer, 0, read, null, 0);
        sha.TransformFinalBlock(Array.Empty<byte>(), 0, 0);
        return Convert.ToHexString(sha.Hash!).ToLowerInvariant();
    }
}
