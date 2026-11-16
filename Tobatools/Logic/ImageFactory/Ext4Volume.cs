// 方案参考自 TIK（GPL-3.0，另附非商业条款）: https://github.com/ColdWindScholar/TIK
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace Tobatools.Logic.ImageFactory
{
    /// <summary>ext4 文件系统只读解析器（纯 C# 移植自 vendor/ext4.py）。</summary>
    public sealed class Ext4Volume : IDisposable
    {
        public const int RootInode = 2;
        public Stream Stream { get; }
        public bool IgnoreFlags { get; }
        public bool IgnoreMagic { get; }
        public bool Platform64 { get; private set; }
        public Superblock Sb { get; }
        public List<GroupDescriptor> GroupDescriptors { get; } = new();
        public int BlockSize => 1 << (int)(10 + Sb.SLogBlockSize);
        public uint BlockCount => Sb.SBlocksCount;
        public string MountPoint => Encoding.UTF8.GetString(Sb.SLastMounted).TrimEnd('\0');

        public Ext4Volume(Stream stream, bool ignoreFlags = false, bool ignoreMagic = false)
        {
            Stream = stream;
            IgnoreFlags = ignoreFlags;
            IgnoreMagic = ignoreMagic;
            var sbBytes = Read(0x400, 0x1000);
            Sb = new Superblock(sbBytes);
            Platform64 = (Sb.SFeatureIncompat & Superblock.Incompat64bit) != 0;
            if (!ignoreMagic && Sb.SMagic != 0xEF53)
                throw new InvalidOperationException($"Invalid magic value in superblock: 0x{Sb.SMagic:X4} (expected 0xEF53)");

            int groupCount = (int)(Sb.SInodesCount / Sb.SInodesPerGroup);
            long groupDescTableOffset = (0x400L / BlockSize + 1) * BlockSize;
            for (int i = 0; i < groupCount; i++)
            {
                long off = groupDescTableOffset + i * Sb.SDescSize;
                GroupDescriptors.Add(new GroupDescriptor(Read(off, 0x40), Platform64));
            }
        }

        public Ext4Inode GetInode(uint inodeIdx, uint fileType = 0)
        {
            if (inodeIdx == 0 || inodeIdx > Sb.SInodesCount)
                throw new InvalidOperationException($"无效的 inode 编号: {inodeIdx}");
            uint groupIdx = (inodeIdx - 1) / Sb.SInodesPerGroup;
            uint entryIdx = (inodeIdx - 1) % Sb.SInodesPerGroup;
            if ((int)groupIdx >= GroupDescriptors.Count)
                throw new InvalidOperationException($"inode {inodeIdx} 对应的块组 {groupIdx} 超出范围");
            long inodeTableOffset = (long)GroupDescriptors[(int)groupIdx].BgInodeTable * BlockSize;
            long inodeOffset = inodeTableOffset + entryIdx * Sb.SInodeSize;
            return new Ext4Inode(this, inodeOffset, inodeIdx, fileType);
        }

        public byte[] Read(long offset, int byteLen)
        {
            if (Stream.Position != offset) Stream.Seek(offset, SeekOrigin.Begin);
            var buf = new byte[byteLen];
            int off = 0;
            while (off < byteLen)
            {
                int n = Stream.Read(buf, off, byteLen - off);
                if (n <= 0) break;
                off += n;
            }
            return buf;
        }

        public Ext4Inode Root => GetInode(RootInode, 2);

        public void Dispose() => Stream.Dispose();

        // ---------- structs ----------
        public sealed class Superblock
        {
            public const uint Incompat64bit = 0x80;
            public const uint IncompatFiletype = 0x2;
            public uint SInodesCount; public uint SBlocksCount; public uint SRBlocksCount;
            public uint SFreeBlocksCount; public uint SFreeInodesCount; public uint SFirstDataBlock;
            public uint SLogBlockSize; public uint SLogClusterSize; public uint SBlocksPerGroup;
            public uint SClustersPerGroup; public uint SInodesPerGroup; public uint SMtime; public uint SWtime;
            public ushort SMntCount; public ushort SMaxMntCount; public ushort SMagic; public ushort SState;
            public ushort SErrors; public ushort SMinorRevLevel; public uint SLastcheck; public uint SCheckinterval;
            public uint SCreatorOs; public uint SRevLevel; public ushort SDefResuid; public ushort SDefResgid;
            public uint SFirstIno; public ushort SInodeSize; public ushort SBlockGroupNr;
            public uint SFeatureCompat; public uint SFeatureIncompat; public uint SFeatureRoCompat;
            public byte[] SUuid = new byte[16]; public byte[] SVolumeName = new byte[16];
            public byte[] SLastMounted = new byte[64]; public uint SAlgorithmUsageBitmap;
            public byte SPreallocBlocks; public byte SPreallocDirBlocks; public ushort SReservedGdtBlocks;
            public byte[] SJournalUuid = new byte[16]; public uint SJournalInum; public uint SJournalDev;
            public uint SLastOrphan; public uint[] SHashSeed = new uint[4]; public byte SDefHashVersion;
            public byte SJnlBackupType; public ushort SDescSize; public uint SDefaultMountOpts;
            public uint SFirstMetaBg; public uint SMkfsTime; public uint[] SJnlBlocks = new uint[17];
            public uint SBlocksCountHi; public uint SRBlocksCountHi; public uint SFreeBlocksCountHi;

            public Superblock(byte[] b)
            {
                SInodesCount = LE32(b, 0); SBlocksCount = LE32(b, 4); SRBlocksCount = LE32(b, 8);
                SFreeBlocksCount = LE32(b, 12); SFreeInodesCount = LE32(b, 16); SFirstDataBlock = LE32(b, 20);
                SLogBlockSize = LE32(b, 24); SLogClusterSize = LE32(b, 28); SBlocksPerGroup = LE32(b, 32);
                SClustersPerGroup = LE32(b, 36); SInodesPerGroup = LE32(b, 40); SMtime = LE32(b, 44); SWtime = LE32(b, 48);
                SMntCount = LE16(b, 52); SMaxMntCount = LE16(b, 54); SMagic = LE16(b, 56); SState = LE16(b, 58);
                SErrors = LE16(b, 60); SMinorRevLevel = LE16(b, 62); SLastcheck = LE32(b, 64); SCheckinterval = LE32(b, 68);
                SCreatorOs = LE32(b, 72); SRevLevel = LE32(b, 76); SDefResuid = LE16(b, 80); SDefResgid = LE16(b, 82);
                SFirstIno = LE32(b, 84); SInodeSize = LE16(b, 88); SBlockGroupNr = LE16(b, 90);
                SFeatureCompat = LE32(b, 92); SFeatureIncompat = LE32(b, 96); SFeatureRoCompat = LE32(b, 100);
                Array.Copy(b, 104, SUuid, 0, 16); Array.Copy(b, 120, SVolumeName, 0, 16); Array.Copy(b, 136, SLastMounted, 0, 64);
                SAlgorithmUsageBitmap = LE32(b, 200); SPreallocBlocks = b[204]; SPreallocDirBlocks = b[205];
                SReservedGdtBlocks = LE16(b, 206); Array.Copy(b, 208, SJournalUuid, 0, 16);
                SJournalInum = LE32(b, 224); SJournalDev = LE32(b, 228); SLastOrphan = LE32(b, 232);
                for (int i = 0; i < 4; i++) SHashSeed[i] = LE32(b, 236 + i * 4);
                SDefHashVersion = b[252]; SJnlBackupType = b[253]; SDescSize = LE16(b, 254);
                SDefaultMountOpts = LE32(b, 256); SFirstMetaBg = LE32(b, 260); SMkfsTime = LE32(b, 264);
                for (int i = 0; i < 17; i++) SJnlBlocks[i] = LE32(b, 268 + i * 4);
                SBlocksCountHi = LE32(b, 336); SRBlocksCountHi = LE32(b, 340); SFreeBlocksCountHi = LE32(b, 344);
                if (SDescSize == 0)
                    SDescSize = (SFeatureIncompat & Incompat64bit) != 0 ? (ushort)0x40 : (ushort)0x20;
            }
        }

        public sealed class GroupDescriptor
        {
            public uint BgBlockBitmap; public uint BgInodeBitmap; public uint BgInodeTable;
            public GroupDescriptor(byte[] b, bool platform64 = false)
            {
                BgBlockBitmap = LE32(b, 0); BgInodeBitmap = LE32(b, 4); BgInodeTable = LE32(b, 8);
                // 只有 64bit 特性开启时，inode 表高位才在 0x28；否则那里属于下一个组描述符，
                // 盲目合并会让 inode 表指针错位，读到完全无关的数据。
                if (platform64 && b.Length >= 0x30)
                    BgInodeTable |= (LE32(b, 0x28) << 32);
            }
        }

        public sealed class Ext4Inode
        {
            public const int S_IFDIR = 0x4000; public const int S_IFREG = 0x8000; public const int S_IFLNK = 0xA000;
            public const int S_IRUSR = 0x100; public const int S_IWUSR = 0x80; public const int S_IXUSR = 0x40;
            public const int S_IRGRP = 0x20; public const int S_IWGRP = 0x10; public const int S_IXGRP = 0x8;
            public const int S_IROTH = 0x4; public const int S_IWOTH = 0x2; public const int S_IXOTH = 0x1;
            public const int S_ISUID = 0x800; public const int S_ISGID = 0x400; public const int S_ISVTX = 0x200;
            public const uint EXT4_INDEX_FL = 0x1000; public const uint EXT4_EXTENTS_FL = 0x80000;
            public const int GoodOldInodeSize = 128;

            public Ext4Volume Volume { get; }
            public uint InodeIdx { get; }
            public uint FileType { get; }
            public long Offset { get; }
            public ushort IMode; public ushort IUidLo; public uint ISizeLo; public uint IAtime; public uint ICtime;
            public uint IMtime; public uint IDtime; public ushort IGidLo; public ushort ILinksCount; public uint IBlocksLo;
            public uint IFlags; public uint IGeneration; public uint IFileAclLo; public uint ISizeHi; public uint IOsd2BlocksHigh;
            public ushort IFileAclHi; public ushort IUidHi; public ushort IGidHi; public ushort IOsd2ChecksumLo;
            public ushort IOsd2Reserved; public ushort IExtraIsize; public ushort IChecksumHi;
            public byte[] IBlock = new byte[15 * 4];
            public uint IUid => (uint)((IUidHi << 16) | IUidLo);
            public uint IGid => (uint)((IGidHi << 16) | IGidLo);
            public ulong ISize => ((ulong)ISizeHi << 32) | ISizeLo;
            public ulong IFileAcl => ((ulong)IFileAclHi << 32) | IFileAclLo;

            public Ext4Inode(Ext4Volume volume, long offset, uint inodeIdx, uint fileType)
            {
                Volume = volume; Offset = offset; InodeIdx = inodeIdx; FileType = fileType;
                var b = volume.Read(offset, 128);
                IMode = LE16(b, 0); IUidLo = LE16(b, 2); ISizeLo = LE32(b, 4); IAtime = LE32(b, 8);
                ICtime = LE32(b, 12); IMtime = LE32(b, 16); IDtime = LE32(b, 20); IGidLo = LE16(b, 24);
                ILinksCount = LE16(b, 26); IBlocksLo = LE32(b, 28); IFlags = LE32(b, 32);
                // i_block 位于 0x28（40），15 个块指针。
                Array.Copy(b, 40, IBlock, 0, 60);
                IGeneration = LE32(b, 100); IFileAclLo = LE32(b, 104); ISizeHi = LE32(b, 108);
                // 0x70（112）是 i_obso_faddr，必须跳过；此前漏读导致后续字段整体前移 4 字节，
                // 使 i_extra_isize 读错、内联 security.selinux 等 xattr 解析失败。
                IOsd2BlocksHigh = LE16(b, 116); IFileAclHi = LE16(b, 118); IUidHi = LE16(b, 120);
                IGidHi = LE16(b, 122); IOsd2ChecksumLo = LE16(b, 124); IOsd2Reserved = LE16(b, 126);
                // i_extra_isize / i_checksum_hi 位于 128 之后，属于 i_extra 区，128 字节读不到。
                if (volume.Sb.SInodeSize > GoodOldInodeSize)
                {
                    var extra = volume.Read(offset + GoodOldInodeSize, 4);
                    IExtraIsize = LE16(extra, 0); IChecksumHi = LE16(extra, 2);
                }
            }

            public bool IsDir =>
                (Volume.Sb.SFeatureIncompat & Superblock.IncompatFiletype) == 0 ? (IMode & S_IFDIR) != 0 : FileType == 2;
            public bool IsFile =>
                (Volume.Sb.SFeatureIncompat & Superblock.IncompatFiletype) == 0 ? (IMode & S_IFREG) != 0 : FileType == 1;
            public bool IsSymlink =>
                (Volume.Sb.SFeatureIncompat & Superblock.IncompatFiletype) == 0 ? (IMode & S_IFLNK) != 0 : FileType == 7;

            public string ModeStr
            {
                get
                {
                    char deviceType = '?';
                    bool useFileType = (Volume.Sb.SFeatureIncompat & Superblock.IncompatFiletype) != 0;
                    if (!useFileType)
                    {
                        switch (IMode & 0xF000)
                        {
                            case 0x1000: deviceType = 'p'; break;
                            case 0x2000: deviceType = 'c'; break;
                            case S_IFDIR: deviceType = 'd'; break;
                            case 0x6000: deviceType = 'b'; break;
                            case S_IFREG: deviceType = '-'; break;
                            case S_IFLNK: deviceType = 'l'; break;
                            case 0xC000: deviceType = 's'; break;
                        }
                    }
                    else
                    {
                        deviceType = FileType switch
                        {
                            1 => '-', 2 => 'd', 3 => 'c', 4 => 'b', 5 => 'p', 6 => 's', 7 => 'l', _ => '?'
                        };
                    }
                    var sb = new StringBuilder();
                    sb.Append(deviceType);
                    sb.Append((IMode & S_IRUSR) != 0 ? 'r' : '-');
                    sb.Append((IMode & S_IWUSR) != 0 ? 'w' : '-');
                    sb.Append(SpecialFlag('s', (IMode & S_IXUSR) != 0, (IMode & S_ISUID) != 0));
                    sb.Append((IMode & S_IRGRP) != 0 ? 'r' : '-');
                    sb.Append((IMode & S_IWGRP) != 0 ? 'w' : '-');
                    sb.Append(SpecialFlag('s', (IMode & S_IXGRP) != 0, (IMode & S_ISGID) != 0));
                    sb.Append((IMode & S_IROTH) != 0 ? 'r' : '-');
                    sb.Append((IMode & S_IWOTH) != 0 ? 'w' : '-');
                    sb.Append(SpecialFlag('t', (IMode & S_IXOTH) != 0, (IMode & S_ISVTX) != 0));
                    return sb.ToString();
                }
            }

            private static char SpecialFlag(char letter, bool execute, bool special)
            {
                if (!execute && !special) return '-';
                if (!execute && special) return char.ToUpper(letter);
                if (execute && !special) return 'x';
                return letter;
            }

            public IEnumerable<(string name, uint inode, uint fileType)> OpenDir()
            {
                if (!Volume.IgnoreFlags && !IsDir)
                    throw new InvalidOperationException($"Inode ({InodeIdx}) is not a directory.");
                var raw = OpenRead();
                int offset = 0;
                while (offset < raw.Length)
                {
                    if (offset + 8 > raw.Length) break;
                    uint inode = LE32(raw, offset);
                    ushort recLen = LE16(raw, offset + 4);
                    byte nameLen = raw[offset + 6];
                    byte fileType = raw[offset + 7];
                    if (recLen == 0) break;
                    // 目录尾部的未使用槽位 inode 为 0，不能交给 GetInode 解析。
                    if (inode == 0) { offset += recLen; continue; }
                    if (offset + 8 + nameLen > raw.Length) break;
                    var name = Encoding.UTF8.GetString(raw, offset + 8, nameLen);
                    if (fileType != 0xDE)
                        yield return (name, inode, fileType);
                    offset += recLen;
                }
            }

            public byte[] OpenRead()
            {
                if ((IFlags & EXT4_EXTENTS_FL) != 0)
                {
                    var mapping = new List<(uint fileBlock, ulong diskBlock, uint count)>();
                    var queue = new Queue<long>();
                    queue.Enqueue(Offset + 40); // i_block offset in inode
                    while (queue.Count > 0)
                    {
                        var headerOffset = queue.Dequeue();
                        var hb = Volume.Read(headerOffset, 12);
                        ushort magic = LE16(hb, 0); ushort entries = LE16(hb, 2); ushort depth = LE16(hb, 6);
                        if (!Volume.IgnoreMagic && magic != 0xF30A)
                            throw new InvalidOperationException($"Invalid magic value in extent header of inode {InodeIdx}");
                        if (depth != 0)
                        {
                            for (int i = 0; i < entries; i++)
                            {
                                var ib = Volume.Read(headerOffset + 12 + i * 12, 12);
                                uint leafLo = LE32(ib, 4); ushort leafHi = LE16(ib, 8);
                                ulong leaf = ((ulong)leafHi << 32) | leafLo;
                                queue.Enqueue((long)(leaf * (ulong)Volume.BlockSize));
                            }
                        }
                        else
                        {
                            for (int i = 0; i < entries; i++)
                            {
                                var eb = Volume.Read(headerOffset + 12 + i * 12, 12);
                                uint eeBlock = LE32(eb, 0); ushort eeLen = LE16(eb, 4);
                                ushort startHi = LE16(eb, 6); uint startLo = LE32(eb, 8);
                                ulong start = ((ulong)startHi << 32) | startLo;
                                mapping.Add((eeBlock, start, eeLen));
                            }
                        }
                    }
                    // optimize mapping
                    mapping = mapping.OrderBy(x => x.fileBlock).ToList();
                    var merged = new List<(uint fileBlock, ulong diskBlock, uint count)>();
                    foreach (var m in mapping)
                    {
                        if (merged.Count > 0)
                        {
                            var last = merged[^1];
                            if (last.fileBlock + last.count == m.fileBlock && last.diskBlock + last.count == m.diskBlock)
                            {
                                merged[^1] = (last.fileBlock, last.diskBlock, last.count + m.count);
                                continue;
                            }
                        }
                        merged.Add(m);
                    }
                    var reader = new BlockReader(Volume, (long)ISize, merged);
                    return reader.ReadAll();
                }
                // inline data
                var inline = new byte[Math.Min((long)ISize, IBlock.Length)];
                Array.Copy(IBlock, inline, inline.Length);
                return inline;
            }

            public IEnumerable<(string name, byte[] value)> Xattrs()
            {
                var prefixes = new Dictionary<uint, string>
                {
                    {0,""},{1,"user."},{2,"system.posix_acl_access"},{3,"system.posix_acl_default"},
                    {4,"trusted."},{6,"security."},{7,"system."},{8,"system.richacl"}
                };
                // inline xattrs
                long inlineDataOffset = Offset + GoodOldInodeSize + IExtraIsize;
                long inlineDataLength = Offset + Volume.Sb.SInodeSize - inlineDataOffset;
                if (inlineDataLength > 4)
                {
                    var inline = Volume.Read(inlineDataOffset, (int)inlineDataLength);
                    uint hMagic = LE32(inline, 0);
                    if (hMagic == 0xEA020000)
                    {
                        int offset = 4;
                        // Python 先做 inline_data[offset:] 切片再解析，值偏移因此相对切片起点。
                        // 这里不切片，所以要把切片起点补进基准，否则每个值都会前移 4 字节。
                        foreach (var (n, v) in ParseXattrs(inline, offset, offset, prefixes))
                            yield return (n, v);
                    }
                }
                if (IFileAcl != 0)
                {
                    long start = (long)(IFileAcl * (ulong)Volume.BlockSize);
                    var block = Volume.Read(start, Volume.BlockSize);
                    if (block.Length > 0)
                    {
                        uint hMagic = LE32(block, 0);
                        if (!Volume.IgnoreMagic && hMagic != 0xEA020000) yield break;
                        uint hBlocks = LE32(block, 4);
                        if (hBlocks != 1) yield break;
                        int offset = 4 * ((32 + 3) / 4);
                        // 块内 xattr 的值偏移相对块内切片起点（即 offset 处），同样需要补基准。
                        foreach (var (n, v) in ParseXattrs(block, offset, offset, prefixes))
                            yield return (n, v);
                    }
                }
            }

            private static readonly Encoding? Latin2 = CreateLatin2();

            private static Encoding? CreateLatin2()
            {
                try
                {
                    Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
                    return Encoding.GetEncoding(28592); // iso-8859-2
                }
                catch
                {
                    return null;
                }
            }

            /// <summary>解码 xattr 名字。Python 用 iso-8859-2；.NET 默认不带该代码页，
            /// 取不到时退回 latin1（单字节一一映射，不会因为字符集缺失而中断解包）。</summary>
            private static string DecodeXattrName(byte[] raw, int index, int count)
            {
                if (count <= 0 || index + count > raw.Length) return "";
                var enc = Latin2;
                return enc != null ? enc.GetString(raw, index, count) : Encoding.Latin1.GetString(raw, index, count);
            }

            private IEnumerable<(string, byte[])> ParseXattrs(byte[] raw, int start, int offset, Dictionary<uint, string> prefixes)
            {
                int i = start;
                while (i < raw.Length)
                {
                    if (i + 16 > raw.Length) break;
                    byte nameLen = raw[i]; byte nameIndex = raw[i + 1];
                    ushort valueOffs = LE16(raw, i + 2); uint valueInum = LE32(raw, i + 4);
                    uint valueSize = LE32(raw, i + 8);
                    if (nameLen == 0 && nameIndex == 0 && valueOffs == 0 && valueInum == 0) break;
                    if (!prefixes.ContainsKey(nameIndex))
                        throw new InvalidOperationException($"Unknown attribute prefix {nameIndex} in inode {InodeIdx}");
                    string xname = prefixes[nameIndex];
                    xname += DecodeXattrName(raw, i + 16, nameLen);
                    byte[] value;
                    if (valueInum != 0)
                    {
                        var xinode = Volume.GetInode(valueInum, 1);
                        value = xinode.OpenRead();
                    }
                    else
                    {
                        int vpos = valueOffs + offset;
                        if (vpos < 0) vpos = 0;
                        value = new byte[Math.Min(valueSize, Math.Max(0, raw.Length - vpos))];
                        if (value.Length > 0) Array.Copy(raw, vpos, value, 0, value.Length);
                    }
                    yield return (xname, value);
                    i += 4 * ((16 + nameLen + 3) / 4);
                }
            }
        }

        private sealed class BlockReader
        {
            private readonly Ext4Volume _volume;
            private readonly long _byteSize;
            private readonly List<(uint fileBlock, ulong diskBlock, uint count)> _map;
            private long _cursor;

            public BlockReader(Ext4Volume volume, long byteSize, List<(uint, ulong, uint)> map)
            {
                _volume = volume; _byteSize = byteSize; _map = map;
            }

            private ulong? GetBlockMapping(uint fileBlock)
            {
                foreach (var e in _map)
                    if (e.fileBlock <= fileBlock && fileBlock < e.fileBlock + e.count)
                        return e.diskBlock + (fileBlock - e.fileBlock);
                return null;
            }

            public byte[] ReadAll()
            {
                using var ms = new MemoryStream();
                long remaining = _byteSize;
                while (remaining > 0)
                {
                    long pos = _cursor;
                    uint startBlock = (uint)(pos / _volume.BlockSize);
                    var disk = GetBlockMapping(startBlock);
                    long inBlock = pos % _volume.BlockSize;
                    long want = Math.Min(_volume.BlockSize - inBlock, remaining);
                    if (disk == null)
                    {
                        var zeros = new byte[want];
                        ms.Write(zeros, 0, zeros.Length);
                    }
                    else
                    {
                        var block = _volume.Read((long)(disk.Value * (ulong)_volume.BlockSize), _volume.BlockSize);
                        int from = (int)inBlock;
                        int cnt = (int)Math.Min(want, block.Length - from);
                        if (cnt > 0) ms.Write(block, from, cnt);
                        if (cnt < want) ms.Write(new byte[want - cnt], 0, (int)(want - cnt));
                    }
                    _cursor += want;
                    remaining -= want;
                }
                return ms.ToArray();
            }
        }

        private static ushort LE16(byte[] b, int off) => (ushort)(b[off] | (b[off + 1] << 8));
        private static uint LE32(byte[] b, int off) =>
            (uint)(b[off] | (b[off + 1] << 8) | (b[off + 2] << 16) | (b[off + 3] << 24));
        private static ulong LE64(byte[] b, int off) => LE32(b, off) | ((ulong)LE32(b, off + 4) << 32);
    }
}
