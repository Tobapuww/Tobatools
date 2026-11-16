// DTBO 格式参照 AOSP mkdtboimg；解打包流程参考 TIK（GPL-3.0，另附非商业条款）:
// https://github.com/ColdWindScholar/TIK
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace Tobatools.Logic.ImageFactory
{
    /// <summary>DTBO 镜像打包/解包（纯 C# 移植自 AOSP mkdtboimg）。</summary>
    public static class Mkdtboimg
    {
        public const uint DtboMagic = 0xD7B7AB1E;
        public const uint AcpioMagic = 0x41435049;
        public const int DtTableHeaderSize = 32;
        public const int DtEntryHeaderSize = 32;
        private const int GzipWbits = 31;
        private const int ZlibDecompWbits = 47;

        public static void DumpDtbo(string dtboImg, string outPrefix, bool decompress)
        {
            using var f = File.OpenRead(dtboImg);
            var entries = ReadEntries(f);
            for (int idx = 0; idx < entries.Count; idx++)
            {
                var e = entries[idx];
                var size = e.Size;
                f.Seek(e.DtOffset, SeekOrigin.Begin);
                var data = new byte[size];
                ReadExact(f, data, 0, (int)size);
                var compression = e.Compression;
                byte[] outData;
                if (decompress && compression != 0)
                {
                    if (compression is 1 or 2)
                    {
                        outData = DecompressZlib(data, ZlibDecompWbits);
                    }
                    else
                    {
                        throw new InvalidOperationException($"Unknown compression format detected: {compression}");
                    }
                }
                else
                {
                    outData = data;
                }
                File.WriteAllBytes($"{outPrefix}.{idx}", outData);
            }
        }

        public static void CreateDtbo(string outFile, List<string> dtbFiles, int pageSize)
        {
            var entries = new List<DtEntry>();
            foreach (var p in dtbFiles)
            {
                entries.Add(new DtEntry
                {
                    DtFile = File.ReadAllBytes(p),
                    Size = new FileInfo(p).Length,
                    Id = 0, Rev = 0, Flags = 0, Custom0 = 0, Custom1 = 0, Custom2 = 0, Custom3 = 0
                });
            }
            CreateDtbo(outFile, entries, pageSize);
        }

        /// <summary>
        /// 读取恰好 count 个字节。Stream.Read 允许短读，镜像结构字段长度固定，
        /// 短读会静默产出错位数据。
        /// </summary>
        private static void ReadExact(Stream s, byte[] buffer, int offset, int count)
        {
            int done = 0;
            while (done < count)
            {
                int got = s.Read(buffer, offset + done, count - done);
                if (got <= 0) throw new EndOfStreamException($"需要 {count} 字节，只读到 {done} 字节。");
                done += got;
            }
        }

        private static void CreateDtbo(string outFile, List<DtEntry> dtEntries, int pageSize)
        {
            int dtEntryCount = dtEntries.Count;
            long dtOffset = DtTableHeaderSize + dtEntryCount * DtEntryHeaderSize;
            var entryBuf = new MemoryStream();
            foreach (var dtEntry in dtEntries)
            {
                var data = dtEntry.DtFile;
                dtEntry.DtOffset = dtOffset;
                dtEntry.Size = data.Length;
                entryBuf.Write(data, 0, data.Length);
                dtOffset += data.Length;
            }

            // metadata header
            var totalSize = DtTableHeaderSize + dtEntryCount * DtEntryHeaderSize + (int)entryBuf.Length;
            var header = new byte[8 * 4];
            WriteU32BE(header, 0, DtboMagic);
            WriteU32BE(header, 4, (uint)totalSize);
            WriteU32BE(header, 8, DtTableHeaderSize);
            WriteU32BE(header, 12, DtEntryHeaderSize);
            WriteU32BE(header, 16, (uint)dtEntryCount);
            WriteU32BE(header, 20, DtTableHeaderSize);
            WriteU32BE(header, 24, (uint)pageSize);
            WriteU32BE(header, 28, 0); // version

            using var os = File.Create(outFile);
            os.Write(header, 0, header.Length);
            foreach (var dtEntry in dtEntries)
            {
                var e = new byte[8 * 4];
                WriteU32BE(e, 0, (uint)dtEntry.Size);
                WriteU32BE(e, 4, (uint)dtEntry.DtOffset);
                WriteU32BE(e, 8, (uint)dtEntry.Id);
                WriteU32BE(e, 12, (uint)dtEntry.Rev);
                WriteU32BE(e, 16, (uint)dtEntry.Flags);
                WriteU32BE(e, 20, (uint)dtEntry.Custom0);
                WriteU32BE(e, 24, (uint)dtEntry.Custom1);
                WriteU32BE(e, 28, (uint)dtEntry.Custom2);
                os.Write(e, 0, e.Length);
            }
            entryBuf.Position = 0;
            entryBuf.CopyTo(os);
        }

        private static List<DtEntry> ReadEntries(Stream f)
        {
            var hdr = new byte[32];
            ReadExact(f, hdr, 0, 32);
            var magic = ReadU32BE(hdr, 0);
            if (magic != DtboMagic && magic != AcpioMagic)
                throw new InvalidOperationException($"Invalid magic number 0x{magic:X} in DTBO/ACPIO file");
            var totalSize = ReadU32BE(hdr, 4);
            var headerSize = ReadU32BE(hdr, 8);
            var dtEntrySize = ReadU32BE(hdr, 12);
            var dtEntryCount = ReadU32BE(hdr, 16);
            var dtEntriesOffset = ReadU32BE(hdr, 20);
            var pageSize = ReadU32BE(hdr, 24);
            var version = ReadU32BE(hdr, 28);
            if (headerSize != DtTableHeaderSize) throw new InvalidOperationException($"Invalid header size ({headerSize}) in DTBO/ACPIO file");
            if (dtEntrySize != DtEntryHeaderSize) throw new InvalidOperationException($"Invalid DT entry header size ({dtEntrySize}) in DTBO/ACPIO file");

            var entries = new List<DtEntry>();
            f.Seek(dtEntriesOffset, SeekOrigin.Begin);
            for (int i = 0; i < dtEntryCount; i++)
            {
                var e = new byte[32];
                ReadExact(f, e, 0, 32);
                var flags = version == 1 ? ReadU32BE(e, 16) : 0u;
                entries.Add(new DtEntry
                {
                    Size = ReadU32BE(e, 0),
                    DtOffset = ReadU32BE(e, 4),
                    Id = ReadU32BE(e, 8),
                    Rev = ReadU32BE(e, 12),
                    Flags = flags,
                    Custom0 = ReadU32BE(e, version == 1 ? 20 : 16),
                    Custom1 = ReadU32BE(e, version == 1 ? 24 : 20),
                    Custom2 = ReadU32BE(e, version == 1 ? 28 : 24),
                    Custom3 = version == 0 ? ReadU32BE(e, 28) : 0
                });
            }
            _ = totalSize; _ = pageSize;
            return entries;
        }

        private static uint ReadU32BE(byte[] b, int off) =>
            (uint)((b[off] << 24) | (b[off + 1] << 16) | (b[off + 2] << 8) | b[off + 3]);

        private static void WriteU32BE(byte[] b, int off, uint v)
        {
            b[off] = (byte)(v >> 24); b[off + 1] = (byte)(v >> 16);
            b[off + 2] = (byte)(v >> 8); b[off + 3] = (byte)v;
        }

        private static byte[] DecompressZlib(byte[] data, int wbits)
        {
            // zlib/gzip 解压（使用带头检测的 ZLibStream 或 GZipStream）
            try
            {
                using var ms = new MemoryStream(data);
                using var z = new ZLibStream(ms, CompressionMode.Decompress);
                using var outMs = new MemoryStream();
                z.CopyTo(outMs);
                return outMs.ToArray();
            }
            catch
            {
                using var ms = new MemoryStream(data);
                using var gz = new GZipStream(ms, CompressionMode.Decompress);
                using var outMs = new MemoryStream();
                gz.CopyTo(outMs);
                return outMs.ToArray();
            }
        }

        private sealed class DtEntry
        {
            public byte[] DtFile = Array.Empty<byte>();
            public long Size; public long DtOffset;
            public long Id; public long Rev; public long Flags;
            public long Custom0; public long Custom1; public long Custom2; public long Custom3;
            public long Compression => Flags & 0x0F;
        }
    }
}
