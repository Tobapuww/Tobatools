// 方案参考自 TIK（GPL-3.0，另附非商业条款）: https://github.com/ColdWindScholar/TIK
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace Tobatools.Logic.ImageFactory
{
    /// <summary>最小 lpunpack 实现（纯 C# 移植自 TIK）。支持 sparse super.img 检测与解包。</summary>
    public static class LpUnpack
    {
        private const uint SparseHeaderMagic = 0xED26FF3A;
        private const int SparseHeaderSize = 28;
        private const int SparseChunkHeaderSize = 12;
        private const int LpPartitionReservedBytes = 4096;
        private const uint LpMetadataGeometryMagic = 0x616C4467;
        private const int LpMetadataGeometrySize = 4096;
        private const uint LpMetadataHeaderMagic = 0x414C5030;
        private const int LpSectorSize = 512;
        private const int LpTargetTypeLinear = 0;

        public static void Unpack(string superImg, string outDir)
        {
            if (!File.Exists(superImg)) throw new FileNotFoundException(superImg);
            if (string.IsNullOrEmpty(outDir)) throw new ArgumentException("out_dir is empty");
            Directory.CreateDirectory(outDir);

            var stream = File.OpenRead(superImg);
            try
            {
                var src = stream;
                string? unsparse = null;
                if (CheckSparse(stream))
                {
                    unsparse = Unsparse(stream);
                    stream.Dispose();
                    stream = File.OpenRead(unsparse);
                    src = stream;
                }
                try
                {
                    var metadata = ReadMetadata(src);
                    foreach (var part in metadata.Partitions)
                    {
                        var parts = new List<(long offset, long size)>();
                        for (int en = 0; en < part.NumExtents; en++)
                        {
                            var extent = metadata.Extents[(int)(part.FirstExtentIndex + en)];
                            if (extent.TargetType != LpTargetTypeLinear)
                                throw new InvalidOperationException($"Unsupported extent target type: {extent.TargetType}");
                            parts.Add(((long)extent.TargetData * LpSectorSize, (long)extent.NumSectors * LpSectorSize));
                        }
                        ExtractPartition(src, Path.Combine(outDir, part.Name + ".img"), parts, (int)metadata.Geometry.LogicalBlockSize);
                    }
                }
                finally
                {
                    stream.Dispose();
                    if (unsparse != null)
                    {
                        try { File.Delete(unsparse); } catch { }
                    }
                }
            }
            catch { stream.Dispose(); throw; }
        }

        private static void ExtractPartition(Stream fd, string outFile, List<(long, long)> parts, int blockSize)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(outFile)!);
            using var os = File.Create(outFile);
            foreach (var (offset, size) in parts)
            {
                fd.Seek(offset, SeekOrigin.Begin);
                long remaining = size;
                var buf = new byte[Math.Min(blockSize, 1 << 20)];
                while (remaining > 0)
                {
                    int chunk = Math.Min(buf.Length, (int)Math.Min(remaining, int.MaxValue));
                    int n = fd.Read(buf, 0, chunk);
                    if (n <= 0) break;
                    os.Write(buf, 0, n);
                    remaining -= n;
                }
            }
        }

        private static bool CheckSparse(Stream fd)
        {
            fd.Seek(0, SeekOrigin.Begin);
            var hdr = ReadBytes(fd, SparseHeaderSize);
            return BitConverter.ToUInt32(hdr, 0) == SparseHeaderMagic;
        }

        private static string Unsparse(Stream fd)
        {
            fd.Seek(0, SeekOrigin.Begin);
            var hdrBytes = ReadBytes(fd, SparseHeaderSize);
            var fileHdrSz = BitConverter.ToUInt16(hdrBytes, 8);
            var chunkHdrSz = BitConverter.ToUInt16(hdrBytes, 10);
            var blkSz = BitConverter.ToUInt32(hdrBytes, 12);
            var totalChunks = BitConverter.ToUInt32(hdrBytes, 20);

            fd.Seek(fileHdrSz - SparseHeaderSize, SeekOrigin.Current);

            var dir = Path.GetDirectoryName(fd is FileStream fs ? fs.Name : "");
            var name = Path.GetFileNameWithoutExtension(fd is FileStream fs2 ? fs2.Name : "super");
            var outFile = Path.Combine(dir ?? ".", $"{name}.unsparse.img");

            using var os = File.Create(outFile);
            long chunks = totalChunks;
            while (chunks > 0)
            {
                var ch = ReadBytes(fd, SparseChunkHeaderSize);
                var chunkType = BitConverter.ToUInt16(ch, 0);
                var chunkSz = BitConverter.ToUInt32(ch, 4);
                var totalSz = BitConverter.ToUInt32(ch, 8);
                long sectorSize = (long)(chunkSz * blkSz) >> 9;
                long chunkDataSize = totalSz - chunkHdrSz;

                if (chunkType == 0xCAC1) // RAW
                {
                    if (chunkHdrSz > SparseChunkHeaderSize) fd.Seek(chunkHdrSz - SparseChunkHeaderSize, SeekOrigin.Current);
                    CopyBytes(fd, os, chunkDataSize);
                }
                else
                {
                    if (chunkType is 0xCAC2 or 0xCAC3)
                    {
                        if (chunkHdrSz > SparseChunkHeaderSize) fd.Seek(chunkHdrSz - SparseChunkHeaderSize, SeekOrigin.Current);
                        fd.Seek(chunkDataSize, SeekOrigin.Current);
                    }
                    os.SetLength(os.Position + (sectorSize << 9));
                    os.Seek(0, SeekOrigin.End);
                }
                chunks--;
            }
            return outFile;
        }

        private static Metadata ReadMetadata(Stream fd)
        {
            fd.Seek(LpPartitionReservedBytes, SeekOrigin.Begin);
            var geoBytes = ReadBytes(fd, LpMetadataGeometrySize);
            var geometry = new LpMetadataGeometry(geoBytes);
            if (geometry.Magic != LpMetadataGeometryMagic) throw new InvalidOperationException("Invalid geometry magic");
            if (geometry.MetadataSlotCount <= 0) throw new InvalidOperationException("Invalid metadata slot count");

            var metadata = new Metadata { Geometry = geometry };
            var offsets = new List<long>
            {
                LpPartitionReservedBytes + LpMetadataGeometrySize * 2 + geometry.MetadataMaxSize * 0,
                LpPartitionReservedBytes + LpMetadataGeometrySize * 2 + geometry.MetadataMaxSize * geometry.MetadataSlotCount + 0
            };
            LpMetadataHeader? header = null;
            long headerOffset = 0;
            foreach (var off in offsets)
            {
                fd.Seek(off, SeekOrigin.Begin);
                var h = ReadHeader(fd);
                if (h.Magic == LpMetadataHeaderMagic) { header = h; headerOffset = off; break; }
            }
            if (header == null) throw new InvalidOperationException("Invalid metadata header magic");
            metadata.Header = header;
            // 四张表在 header 之后连续排布：partitions → extents → groups → block_devices。
            fd.Seek(headerOffset + header.HeaderSize, SeekOrigin.Begin);
            metadata.Partitions = ReadTable(fd, header.Partitions, b => new LpMetadataPartition(b));
            metadata.Extents = ReadTable(fd, header.Extents, b => new LpMetadataExtent(b));
            metadata.Groups = ReadTable(fd, header.Groups, b => new LpMetadataPartitionGroup(b));
            metadata.BlockDevices = ReadTable(fd, header.BlockDevices, b => new LpMetadataBlockDevice(b));
            if (metadata.BlockDevices.Count == 0) throw new InvalidOperationException("No block devices in metadata");
            return metadata;
        }

        private static LpMetadataHeader ReadHeader(Stream fd)
        {
            var b = ReadBytes(fd, 80);
            var h = new LpMetadataHeader
            {
                Magic = BitConverter.ToUInt32(b, 0),
                MajorVersion = BitConverter.ToInt16(b, 4),
                MinorVersion = BitConverter.ToInt16(b, 6),
                HeaderSize = BitConverter.ToUInt32(b, 8),
                HeaderChecksum = BitConverter.ToUInt32(b, 12),
                TablesSize = BitConverter.ToUInt32(b, 16),
                TablesChecksum = BitConverter.ToUInt32(b, 20)
            };
            h.Partitions = new LpMetadataTableDescriptor(ReadBytes(fd, 12));
            h.Extents = new LpMetadataTableDescriptor(ReadBytes(fd, 12));
            h.Groups = new LpMetadataTableDescriptor(ReadBytes(fd, 12));
            h.BlockDevices = new LpMetadataTableDescriptor(ReadBytes(fd, 12));
            return h;
        }

        private static List<T> ReadTable<T>(Stream fd, LpMetadataTableDescriptor desc, Func<byte[], T> ctor)
        {
            var list = new List<T>();
            for (int i = 0; i < desc.NumEntries; i++)
                list.Add(ctor(ReadBytes(fd, (int)desc.EntrySize)));
            return list;
        }

        private static byte[] ReadBytes(Stream fd, int count)
        {
            var buf = new byte[count];
            int off = 0;
            while (off < count)
            {
                int n = fd.Read(buf, off, count - off);
                if (n <= 0) break;
                off += n;
            }
            return buf;
        }

        private static void CopyBytes(Stream src, Stream dst, long count)
        {
            var buf = new byte[Math.Min(count, 1 << 20)];
            long remaining = count;
            while (remaining > 0)
            {
                int n = src.Read(buf, 0, (int)Math.Min(buf.Length, remaining));
                if (n <= 0) break;
                dst.Write(buf, 0, n);
                remaining -= n;
            }
        }

        public sealed class LpMetadataGeometry
        {
            public uint Magic; public uint StructSize; public byte[] Checksum = new byte[32];
            public uint MetadataMaxSize; public uint MetadataSlotCount; public uint LogicalBlockSize;
            public LpMetadataGeometry(byte[] b)
            {
                // checksum 是 32 字节 SHA256，后面各字段从 0x28 开始。
                Magic = BitConverter.ToUInt32(b, 0); StructSize = BitConverter.ToUInt32(b, 4);
                Array.Copy(b, 8, Checksum, 0, 32);
                MetadataMaxSize = BitConverter.ToUInt32(b, 40);
                MetadataSlotCount = BitConverter.ToUInt32(b, 44);
                LogicalBlockSize = BitConverter.ToUInt32(b, 48);
            }
        }
        public sealed class LpMetadataTableDescriptor
        {
            public uint Offset; public uint NumEntries; public uint EntrySize;
            public LpMetadataTableDescriptor(byte[] b)
            {
                Offset = BitConverter.ToUInt32(b, 0); NumEntries = BitConverter.ToUInt32(b, 4); EntrySize = BitConverter.ToUInt32(b, 8);
            }
        }
        public sealed class LpMetadataPartition
        {
            public string Name; public uint Attributes; public uint FirstExtentIndex; public uint NumExtents; public uint GroupIndex;
            public LpMetadataPartition(byte[] b)
            {
                Name = Encoding.UTF8.GetString(b, 0, 36).TrimEnd('\0');
                Attributes = BitConverter.ToUInt32(b, 36); FirstExtentIndex = BitConverter.ToUInt32(b, 40);
                NumExtents = BitConverter.ToUInt32(b, 44); GroupIndex = BitConverter.ToUInt32(b, 48);
            }
        }
        public sealed class LpMetadataExtent
        {
            public ulong NumSectors; public uint TargetType; public ulong TargetData; public ulong TargetSource;
            public LpMetadataExtent(byte[] b)
            {
                NumSectors = BitConverter.ToUInt64(b, 0); TargetType = BitConverter.ToUInt32(b, 8);
                TargetData = BitConverter.ToUInt64(b, 12); TargetSource = BitConverter.ToUInt32(b, 20);
            }
        }
        public sealed class LpMetadataPartitionGroup
        {
            public string Name; public uint Flags; public ulong MaximumSize;
            public LpMetadataPartitionGroup(byte[] b)
            {
                Name = Encoding.UTF8.GetString(b, 0, 36).TrimEnd('\0');
                Flags = BitConverter.ToUInt32(b, 36);
                MaximumSize = BitConverter.ToUInt64(b, 40);
            }
        }
        public sealed class LpMetadataBlockDevice
        {
            public ulong FirstLogicalSector; public uint Alignment; public uint AlignmentOffset;
            public ulong BlockDeviceSize; public string PartitionName; public uint Flags;
            public LpMetadataBlockDevice(byte[] b)
            {
                FirstLogicalSector = BitConverter.ToUInt64(b, 0); Alignment = BitConverter.ToUInt32(b, 8);
                AlignmentOffset = BitConverter.ToUInt32(b, 12); BlockDeviceSize = BitConverter.ToUInt64(b, 16);
                PartitionName = Encoding.UTF8.GetString(b, 24, 36).TrimEnd('\0'); Flags = BitConverter.ToUInt32(b, 60);
            }
        }
        public sealed class Metadata
        {
            public LpMetadataGeometry Geometry = null!;
            public LpMetadataHeader? Header;
            public List<LpMetadataPartition> Partitions = new();
            public List<LpMetadataExtent> Extents = new();
            public List<LpMetadataPartitionGroup> Groups = new();
            public List<LpMetadataBlockDevice> BlockDevices = new();
        }
        public sealed class LpMetadataHeader
        {
            public uint Magic; public short MajorVersion; public short MinorVersion; public uint HeaderSize;
            public uint HeaderChecksum; public uint TablesSize; public uint TablesChecksum;
            public LpMetadataTableDescriptor Partitions = null!;
            public LpMetadataTableDescriptor Extents = null!;
            public LpMetadataTableDescriptor Groups = null!;
            public LpMetadataTableDescriptor BlockDevices = null!;
        }
    }
}
