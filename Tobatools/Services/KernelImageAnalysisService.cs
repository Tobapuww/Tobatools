using System;
using System.Buffers.Binary;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Tobatools.Services;

/// <summary>
/// 内核镜像离线 ELF/kallsyms 只读分析能力。
/// 该服务只解析文件和符号文本，不修改镜像，也不生成或执行任何可执行程序。
/// </summary>
public sealed class KernelImageAnalysisService
{
    private const long MaxElfBytes = 4L * 1024 * 1024 * 1024;
    private const int MaxSections = 4096;

    public sealed record ElfSection(
        string Name,
        uint Type,
        ulong Flags,
        ulong Address,
        ulong Offset,
        ulong Size,
        uint Link,
        uint Info,
        ulong EntrySize)
    {
        public ulong EndOffset => Offset + Size;
        public bool IsExecutable => (Flags & 0x4) != 0;
        public bool IsAlloc => (Flags & 0x2) != 0;
    }

    public sealed record ElfReport(
        string Path,
        long Size,
        bool Is64Bit,
        bool IsLittleEndian,
        ushort Machine,
        string Architecture,
        ulong EntryPoint,
        IReadOnlyList<ElfSection> Sections)
    {
        public ElfSection? Section(string name) => Sections.FirstOrDefault(x => x.Name == name);
        public IReadOnlyList<ElfSection> ExecutableSections() => Sections.Where(x => x.IsExecutable).ToArray();
        public IReadOnlyList<ElfSection> AllocDataSections() => Sections.Where(x => x.IsAlloc && !x.IsExecutable).ToArray();
    }

    public sealed record KernelSymbol(ulong Address, char Type, string Name, string Module = "");

    public async Task<ElfReport> AnalyzeElfAsync(string path, CancellationToken cancellationToken = default)
    {
        var fullPath = ValidateFile(path, "ELF 文件");
        var info = new FileInfo(fullPath);
        if (info.Length > MaxElfBytes) throw new InvalidDataException("ELF 文件超过分析上限。");
        var header = new byte[64];
        await using var stream = new FileStream(fullPath, FileMode.Open, FileAccess.Read, FileShare.Read, 64, useAsync: true);
        await ReadExactAsync(stream, header, cancellationToken).ConfigureAwait(false);
        if (!header.AsSpan(0, 4).SequenceEqual(new byte[] { 0x7f, (byte)'E', (byte)'L', (byte)'F' }))
            throw new InvalidDataException("文件不是 ELF 格式。");
        if (header[4] != 2) throw new InvalidDataException("当前分析器只支持 ELF64。");
        var little = header[5] == 1;
        if (header[5] is not (1 or 2)) throw new InvalidDataException("ELF 字节序未知。");
        var machine = U16(header, 18, little);
        var entry = U64(header, 24, little);
        var sectionOffset = U64(header, 40, little);
        var sectionEntrySize = U16(header, 58, little);
        var sectionCount = U16(header, 60, little);
        var stringIndex = U16(header, 62, little);
        if (sectionEntrySize < 64 || sectionCount > MaxSections)
            throw new InvalidDataException("ELF section header 表无效。");
        if (sectionCount == 0)
            return new ElfReport(fullPath, info.Length, true, little, machine, Architecture(machine), entry, Array.Empty<ElfSection>());

        if (sectionOffset > (ulong)info.Length || sectionOffset + (ulong)sectionEntrySize * sectionCount > (ulong)info.Length)
            throw new InvalidDataException("ELF section header 表超出文件范围。");
        var rawSections = new byte[sectionEntrySize * sectionCount];
        stream.Position = (long)sectionOffset;
        await ReadExactAsync(stream, rawSections, cancellationToken).ConfigureAwait(false);
        var sectionNames = stringIndex < sectionCount
            ? await ReadSectionNamesAsync(stream, rawSections, stringIndex, sectionEntrySize, little, info.Length, cancellationToken).ConfigureAwait(false)
            : Array.Empty<byte>();

        var sections = new List<ElfSection>(sectionCount);
        for (var i = 0; i < sectionCount; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var offset = i * sectionEntrySize;
            var nameOffset = U32(rawSections, offset, little);
            var type = U32(rawSections, offset + 4, little);
            var flags = U64(rawSections, offset + 8, little);
            var address = U64(rawSections, offset + 16, little);
            var dataOffset = U64(rawSections, offset + 24, little);
            var dataSize = U64(rawSections, offset + 32, little);
            var link = U32(rawSections, offset + 40, little);
            var sectionInfo = U32(rawSections, offset + 44, little);
            var entrySize = U64(rawSections, offset + 56, little);
            if (dataOffset > (ulong)info.Length || dataSize > (ulong)info.Length - dataOffset)
                throw new InvalidDataException($"ELF section {i} 超出文件范围。");
            sections.Add(new ElfSection(ReadCString(sectionNames, nameOffset), type, flags, address, dataOffset, dataSize, link, sectionInfo, entrySize));
        }
        return new ElfReport(fullPath, info.Length, true, little, machine, Architecture(machine), entry, sections);
    }

    public async Task<IReadOnlyList<KernelSymbol>> ParseKallsymsAsync(string path, CancellationToken cancellationToken = default)
    {
        var fullPath = ValidateFile(path, "kallsyms 文件");
        var symbols = new List<KernelSymbol>();
        using var reader = new StreamReader(new FileStream(fullPath, FileMode.Open, FileAccess.Read, FileShare.Read, 64 * 1024, useAsync: true), Encoding.UTF8, true);
        while (await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false) is { } line)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var parts = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 3 || !ulong.TryParse(parts[0], System.Globalization.NumberStyles.HexNumber, null, out var address)) continue;
            var module = parts.Length >= 4 ? parts[3].Trim('[', ']') : string.Empty;
            symbols.Add(new KernelSymbol(address, parts[1][0], parts[2], module));
        }
        return symbols;
    }

    public static IReadOnlyList<KernelSymbol> FindSymbols(IEnumerable<KernelSymbol> symbols, string name)
    {
        var needle = name?.Trim() ?? string.Empty;
        return symbols.Where(x => string.Equals(x.Name, needle, StringComparison.Ordinal)).ToArray();
    }

    public static ulong? InferBaseAddress(IEnumerable<KernelSymbol> symbols, ulong? knownOffset = null, ulong? knownAddress = null)
    {
        if (knownOffset is not ulong offset || knownAddress is not ulong address || address < offset) return null;
        return address - offset;
    }

    public static string ExportSymbolsJson(IEnumerable<KernelSymbol> symbols, bool indented = true)
    {
        return JsonSerializer.Serialize(symbols.OrderBy(x => x.Address), new JsonSerializerOptions { WriteIndented = indented });
    }

    private static async Task<byte[]> ReadSectionNamesAsync(Stream stream, byte[] sections, int index, int entrySize, bool little, long fileSize, CancellationToken cancellationToken)
    {
        var offset = (ulong)index * (ulong)entrySize;
        var dataOffset = U64(sections, (int)offset + 24, little);
        var dataSize = U64(sections, (int)offset + 32, little);
        if (dataOffset > (ulong)fileSize || dataSize > (ulong)fileSize - dataOffset || dataSize > 64 * 1024 * 1024)
            throw new InvalidDataException("ELF section name 表无效。");
        var data = new byte[(int)dataSize];
        stream.Position = (long)dataOffset;
        await ReadExactAsync(stream, data, cancellationToken).ConfigureAwait(false);
        return data;
    }

    private static async Task ReadExactAsync(Stream stream, byte[] buffer, CancellationToken cancellationToken)
    {
        var offset = 0;
        while (offset < buffer.Length)
        {
            var read = await stream.ReadAsync(buffer.AsMemory(offset), cancellationToken).ConfigureAwait(false);
            if (read <= 0) throw new EndOfStreamException("文件内容不完整。");
            offset += read;
        }
    }

    private static string ValidateFile(string path, string label)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path)) throw new FileNotFoundException(label + "不存在。", path);
        return Path.GetFullPath(path);
    }

    private static string ReadCString(byte[] data, uint offset)
    {
        if (offset >= data.Length) return string.Empty;
        var end = Array.IndexOf(data, (byte)0, (int)offset);
        if (end < 0) end = data.Length;
        return Encoding.UTF8.GetString(data, (int)offset, end - (int)offset);
    }

    private static string Architecture(ushort machine) => machine switch
    {
        183 => "AArch64",
        62 => "x86-64",
        40 => "ARM",
        3 => "x86",
        _ => $"ELF machine {machine}"
    };

    private static ushort U16(byte[] data, int offset, bool little) => little
        ? BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(offset, 2))
        : BinaryPrimitives.ReadUInt16BigEndian(data.AsSpan(offset, 2));

    private static uint U32(byte[] data, int offset, bool little) => little
        ? BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset, 4))
        : BinaryPrimitives.ReadUInt32BigEndian(data.AsSpan(offset, 4));

    private static ulong U64(byte[] data, int offset, bool little) => little
        ? BinaryPrimitives.ReadUInt64LittleEndian(data.AsSpan(offset, 8))
        : BinaryPrimitives.ReadUInt64BigEndian(data.AsSpan(offset, 8));
}
