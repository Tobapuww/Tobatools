// 方案参考自 TIK（GPL-3.0，另附非商业条款）: https://github.com/ColdWindScholar/TIK
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Tobatools.Services;

namespace Tobatools.Logic.ImageFactory
{
    public abstract class BaseTool
    {
        public Action<string>? Log { get; set; }
        public Action<string, string>? StepStart { get; set; }
        public Action<string, bool, string>? StepFinish { get; set; }
        public volatile bool Stop;
        public void StopRequest() => Stop = true;
        protected void Emit(string s) { try { Log?.Invoke(s); } catch { } }
        protected void CheckStop() { if (Stop) throw new OperationCanceledException("已取消"); }

        protected static long AlignUp(long n, long align)
        {
            if (align <= 0) return n;
            return ((n + align - 1) / align) * align;
        }

        protected static string MetaPath(string cfgDir, string name, string kind) =>
            Path.Combine(cfgDir, $"{name}_{kind}.json");

        /// <summary>
        /// 以 LF 换行写入文本行，且不追加末尾换行。
        /// 与原 Python 实现的 <c>newline="\n"</c> + <c>"\n".join(...)</c> 逐字节一致；
        /// 生成的 fs_config / file_contexts / transfer.list 会被外部工具按字节解析。
        /// </summary>
        internal static void WriteLfText(string path, IEnumerable<string> lines)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, string.Join("\n", lines), new UTF8Encoding(false));
        }

        protected static void WriteMeta(string cfgDir, string name, string kind, object meta)
        {
            try
            {
                Directory.CreateDirectory(cfgDir);
                File.WriteAllText(MetaPath(cfgDir, name, kind),
                    JsonSerializer.Serialize(meta, new JsonSerializerOptions { WriteIndented = true }));
            }
            catch { }
        }

        protected static Dictionary<string, object>? ReadMeta(string cfgDir, string name, string kind)
        {
            try
            {
                var p = MetaPath(cfgDir, name, kind);
                if (!File.Exists(p)) return null;
                return JsonSerializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(p));
            }
            catch { return null; }
        }

        protected static long DirSizeBytes(string root)
        {
            long total = 0;
            try
            {
                foreach (var f in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories))
                {
                    try { total += new FileInfo(f).Length; } catch { }
                }
            }
            catch { }
            return total;
        }
    }

    // ==================== ext4 ====================
    public sealed class Ext4ImageTool : BaseTool
    {
        public bool Extract(string image, string projectDir, bool generateConfigs = true)
        {
            if (!File.Exists(image)) throw new FileNotFoundException($"镜像文件不存在: {image}");
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            var stepId = "ext4_extract";
            StepStart?.Invoke(stepId, "提取 ext4 镜像");
            string? unsparsePath = null;
            try
            {
                Emit($"输入: {image}");
                Emit($"工程: {proj.Root}");
                Emit($"解包输出: {proj.ExtractedDir}");
                Emit($"配置输出: {proj.ConfigDir}");

                var src = image;
                using (var fd = File.OpenRead(image))
                {
                    if (CheckSparse(fd))
                    {
                        Emit("检测到 sparse 镜像，正在转换为 raw...");
                        unsparsePath = Unsparse(fd);
                        Emit($"转换完成: {unsparsePath}");
                    }
                }
                if (unsparsePath != null) src = unsparsePath;

                using var fs = File.OpenRead(src);
                var vol = new Ext4Volume(fs);
                var mount = vol.MountPoint.Trim();
                var name = mount.TrimStart('/').Split('/').LastOrDefault() ?? "";
                if (name.Any(c => c is '.' or '@' or '#')) name = "";
                var baseName = name.Length > 0 ? name : Path.GetFileNameWithoutExtension(image);
                foreach (var sep in new[] { "-", " ", "+", "{", "(" })
                {
                    var idx = baseName.IndexOf(sep, StringComparison.Ordinal);
                    if (idx > 0) baseName = baseName[..idx];
                }
                baseName = SafeName(baseName);
                var extractRoot = Path.Combine(proj.ExtractedDir, baseName);
                Directory.CreateDirectory(extractRoot);

                var imgSizeBytes = new FileInfo(src).Length;
                var fsConfigLines = new List<string>();
                var fcLines = new List<string>();

                void ScanDir(Ext4Volume.Ext4Inode rootInode, string rootPath = "")
                {
                    CheckStop();
                    foreach (var (entryName, inodeIdx, entryType) in rootInode.OpenDir())
                    {
                        if (entryName is "." or ".." || entryName.EndsWith(" (2)")) continue;
                        var entryInode = vol.GetInode(inodeIdx, entryType);
                        var entryPath = rootPath + "/" + entryName;
                        var targetRel = ("/" + baseName + entryPath).Replace("//", "/");
                        var targetFs = Path.Combine(extractRoot, entryPath.TrimStart('/').Replace('/', Path.DirectorySeparatorChar));
                        targetFs = SafeName(targetFs).Replace(' ', '_');

                        if (generateConfigs)
                        {
                            var mode = PermToOctal(entryInode.ModeStr);
                            var uid = entryInode.IUid;
                            var gid = entryInode.IGid;
                            var cap = "";
                            string linkTarget = "";
                            foreach (var (k, v) in entryInode.Xattrs())
                            {
                                if (k == "security.selinux")
                                {
                                    var t = targetRel;
                                    foreach (var fuk in @"\^$.|?*+(){}[]")
                                        t = t.Replace(fuk.ToString(), "\\" + fuk);
                                    // Python 用 v.decode('utf8')[:-1]，只去掉单个结尾 NUL；
                                    // TrimEnd 会把上下文里的多个 NUL 一起吞掉，必须只裁一个。
                                    var sctx = Encoding.UTF8.GetString(v);
                                    if (sctx.EndsWith('\0')) sctx = sctx[..^1];
                                    fcLines.Add($"{t} {sctx}");
                                }
                                else if (k == "security.capability" && v.Length >= 20)
                                {
                                    try
                                    {
                                        var r1 = BitConverter.ToUInt32(v, 0);
                                        var r2 = BitConverter.ToUInt32(v, 4);
                                        var r3 = BitConverter.ToUInt32(v, 8);
                                        var r4 = BitConverter.ToUInt32(v, 12);
                                        // 与 Python 版 hex() 一致：保留 0x 前缀。
                                        if (r2 > 65535)
                                            cap = $" capabilities=0x{uint.Parse($"{r4:x4}{r2:x4}", System.Globalization.NumberStyles.HexNumber):x}";
                                        else
                                            cap = $" capabilities=0x{uint.Parse($"{r4:x4}{r3:x4}{r2:x4}", System.Globalization.NumberStyles.HexNumber):x}";
                                    }
                                    catch { }
                                }
                            }
                            if (entryInode.IsSymlink)
                            {
                                try { linkTarget = Encoding.UTF8.GetString(entryInode.OpenRead()).TrimEnd('\0'); } catch { linkTarget = ""; }
                            }
                            fsConfigLines.Add($"{targetRel} {uid} {gid} {mode}{cap} {linkTarget}".TrimEnd());
                        }

                        if (entryInode.IsDir)
                        {
                            Directory.CreateDirectory(targetFs);
                            ScanDir(entryInode, entryPath);
                        }
                        else if (entryInode.IsFile)
                        {
                            Directory.CreateDirectory(Path.GetDirectoryName(targetFs)!);
                            var data = entryInode.OpenRead();
                            File.WriteAllBytes(targetFs, data);
                        }
                        else if (entryInode.IsSymlink)
                        {
                            Directory.CreateDirectory(Path.GetDirectoryName(targetFs)!);
                            var linkData = entryInode.OpenRead();
                            File.WriteAllBytes(targetFs, SymlinkMarker(linkData));
                        }
                        // 其它类型暂不落盘
                    }
                }

                ScanDir(vol.Root);

                if (generateConfigs)
                {
                    var cfgDir = proj.ConfigDir;
                    fsConfigLines = fsConfigLines.Distinct().ToList();
                    // Python 以 newline="\n" 写入且不追加行尾换行；生成的 fs_config / file_contexts
                    // 会被 e2fsdroid、make_ext4fs 等工具按字节读取，必须保持 LF。
                    WriteLfText(Path.Combine(cfgDir, $"{baseName}_fs_config"), fsConfigLines);
                    if (fcLines.Count > 0)
                    {
                        fcLines = fcLines.Distinct().OrderBy(x => x, StringComparer.Ordinal).ToList();
                        WriteLfText(Path.Combine(cfgDir, $"{baseName}_file_contexts"), fcLines);
                    }
                    WriteMeta(cfgDir, baseName, "image_meta", new
                    {
                        fs = "ext4", name = baseName, source_image = Path.GetFullPath(image),
                        source_raw_image = Path.GetFullPath(src), original_image_size_bytes = imgSizeBytes, mount_point = mount
                    });
                }

                StepFinish?.Invoke(stepId, true, "完成");
                return true;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
            // 与 Python ext4_image.py L335 一致：unsparse 文件放在源目录旁并保留给用户，
            // 避免同一镜像重复转换（Python 注释明确说明不自动清理）。
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

        private static byte[] SymlinkMarker(byte[] target)
        {
            // Windows 下写入 marker 文件，打包阶段可恢复
            var prefix = Encoding.ASCII.GetBytes("!<symlink>");
            var enc = Encoding.Unicode.GetBytes(Encoding.UTF8.GetString(target).TrimEnd('\0'));
            var buf = new byte[prefix.Length + enc.Length + 2];
            Array.Copy(prefix, buf, prefix.Length);
            Array.Copy(enc, 0, buf, prefix.Length, enc.Length);
            return buf;
        }

        public bool Pack(string projectDir, string folder, string outName = "", string label = "",
            string mountPoint = "", int blockSize = 4096, bool allowGrow = false, long? targetSizeBytes = null)
        {
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            if (!Directory.Exists(folder)) throw new FileNotFoundException($"folder 不存在: {folder}");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            var name = Path.GetFileName(folder.TrimEnd('/', '\\'));
            var outName2 = string.IsNullOrEmpty(outName) ? $"{name}.img" : outName;
            if (!outName2.ToLowerInvariant().EndsWith(".img")) outName2 += ".img";
            var outImg = Path.Combine(proj.OutDir, outName2);

            var cfgDir = proj.ConfigDir;
            var fsConfig = Path.Combine(cfgDir, $"{name}_fs_config");
            if (!File.Exists(fsConfig)) throw new FileNotFoundException($"未找到 fs_config: {fsConfig}（请先解包并生成 config）");

            var makeExt4fs = ExtTool.Resolve("make_ext4fs");
            var mke2fs = ExtTool.Resolve("mke2fs");
            var e2fsdroid = ExtTool.Resolve("e2fsdroid");

            var dirSize = DirSizeBytes(folder);
            var requiredMin = AlignUp(dirSize + 16 * 1024 * 1024, 1024 * 1024);
            long recordedSize = 0;
            var meta = ReadMeta(cfgDir, name, "image_meta");
            if (meta != null && meta.TryGetValue("original_image_size_bytes", out var v) && long.TryParse(v?.ToString(), out var rs) && rs > 0)
                recordedSize = rs;

            long imgSize;
            if (targetSizeBytes != null) imgSize = targetSizeBytes.Value;
            else if (recordedSize > 0) imgSize = recordedSize;
            else imgSize = AlignUp(dirSize + 64 * 1024 * 1024, 1024 * 1024);

            var label2 = string.IsNullOrEmpty(label) ? name : label;
            var mount2 = mountPoint;
            if (mount2.Length > 0 && !mount2.StartsWith("/")) mount2 = "/" + mount2;
            if (mount2.Length == 0) mount2 = "/" + name;

            var stepId = "ext4_pack";
            StepStart?.Invoke(stepId, "打包 ext4 镜像");
            try
            {
                CheckStop();
                Emit($"工程: {proj.Root}");
                Emit($"输入目录: {folder}");
                Emit($"输出: {outImg}");
                Emit($"fs_config: {fsConfig}");
                var fileContexts = Path.Combine(cfgDir, $"{name}_file_contexts");
                Emit($"file_contexts: {fileContexts}");
                if (recordedSize > 0) Emit($"原镜像大小(记录): {recordedSize}");
                Emit($"目录估算最小需求: {requiredMin}");
                Emit($"目标镜像大小: {imgSize}");

                if (recordedSize > 0 && !allowGrow && imgSize > recordedSize)
                    throw new InvalidOperationException($"目标镜像大小 {imgSize} 大于原镜像大小 {recordedSize}，为避免刷入失败已阻止。");
                if (recordedSize > 0 && requiredMin > recordedSize && !allowGrow)
                    throw new InvalidOperationException($"当前目录内容需要至少 {requiredMin}，已超过原镜像大小 {recordedSize}。为避免刷入失败已阻止：请删减内容或允许增长/调整分区大小。");
                if (requiredMin > imgSize)
                    throw new InvalidOperationException($"目标镜像大小 {imgSize} 过小，至少需要 {requiredMin}。");
                if (File.Exists(outImg)) { try { File.Delete(outImg); } catch { } }

                if (File.Exists(makeExt4fs))
                {
                    var cmd = new List<string>
                    {
                        makeExt4fs, "-J", "-l", imgSize.ToString(),
                        "-C", fsConfig, "-L", label2, "-a", mount2.TrimStart('/')
                    };
                    var haveFc = File.Exists(fileContexts);
                    if (haveFc) cmd.AddRange(new[] { "-S", fileContexts });
                    cmd.Add(outImg); cmd.Add(folder);
                    var lines = new List<string>();
                    var r = ExtProc.Run(cmd, null, s => { lock (lines) lines.Add(s); Emit(s); }, () => Stop, 900000);
                    if (r.ExitCode != 0)
                    {
                        var joined = string.Join("\n", lines.Skip(Math.Max(0, lines.Count - 200)));
                        if (haveFc && (joined.Contains("cannot lookup security context") || joined.Contains("security context")))
                        {
                            Emit("");
                            Emit("检测到 SELinux file_contexts 不完整导致 make_ext4fs 失败。");
                            Emit("将自动降级：忽略 file_contexts（不使用 -S）并重试打包。");
                            Emit("提示：如需完整 SELinux 标签，请补全 config 里的 *_file_contexts（至少包含挂载点根目录）。");
                            Emit("");
                            var cmd2 = cmd.Where(x => x != "-S" && x != fileContexts).ToList();
                            var r2 = ExtProc.Run(cmd2, null, s => Emit(s), () => Stop, 900000);
                            if (r2.ExitCode != 0) throw new InvalidOperationException($"make_ext4fs 失败，退出码: {r2.ExitCode}");
                        }
                        else
                        {
                            throw new InvalidOperationException($"make_ext4fs 失败，退出码: {r.ExitCode}");
                        }
                    }
                }
                else if (File.Exists(mke2fs) && File.Exists(e2fsdroid))
                {
                    var blocks = Math.Max(1, imgSize / blockSize);
                    Directory.CreateDirectory(Path.GetDirectoryName(outImg)!);
                    using (var f = new FileStream(outImg, FileMode.Create, FileAccess.Write)) f.SetLength(imgSize);
                    var r1 = ExtProc.Run(new[] { mke2fs, "-F", "-O", "^has_journal", "-L", label2, "-I", "256", "-M", mount2, "-m", "0", "-t", "ext4", "-b", blockSize.ToString(), outImg, blocks.ToString() }, null, s => Emit(s), () => Stop, 900000);
                    if (r1.ExitCode != 0) throw new InvalidOperationException($"mke2fs 失败，退出码: {r1.ExitCode}");
                    var cmd2 = new List<string> { e2fsdroid, "-e", "-C", fsConfig, "-a", mount2, "-f", folder };
                    if (File.Exists(fileContexts)) cmd2.AddRange(new[] { "-S", fileContexts });
                    cmd2.Add(outImg);
                    var r2 = ExtProc.Run(cmd2, null, s => Emit(s), () => Stop, 900000);
                    if (r2.ExitCode != 0) throw new InvalidOperationException($"e2fsdroid 失败，退出码: {r2.ExitCode}");
                }
                else
                {
                    throw new FileNotFoundException("未找到 ext4 打包工具（make_ext4fs 或 mke2fs+e2fsdroid）");
                }

                CheckStop();
                if (!File.Exists(outImg) || new FileInfo(outImg).Length == 0)
                    throw new InvalidOperationException("打包失败：未生成有效输出文件");
                StepFinish?.Invoke(stepId, true, "完成");
                return true;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
        }

        // ---- sparse helpers (shared with SuperImage) ----
        public static bool CheckSparse(Stream fd)
        {
            fd.Seek(0, SeekOrigin.Begin);
            var hdr = new byte[28];
            ReadExact(fd, hdr, 0, 28);
            return BitConverter.ToUInt32(hdr, 0) == 0xED26FF3A;
        }

        public static string Unsparse(Stream fd)
        {
            fd.Seek(0, SeekOrigin.Begin);
            var hdr = new byte[28];
            ReadExact(fd, hdr, 0, 28);
            ushort fileHdrSz = BitConverter.ToUInt16(hdr, 8);
            ushort chunkHdrSz = BitConverter.ToUInt16(hdr, 10);
            uint blkSz = BitConverter.ToUInt32(hdr, 12);
            long totalChunks = BitConverter.ToUInt32(hdr, 20);

            fd.Seek(fileHdrSz - 28, SeekOrigin.Current);
            var dir = Path.GetDirectoryName(((FileStream)fd).Name) ?? ".";
            var baseName = Path.GetFileNameWithoutExtension(((FileStream)fd).Name);
            var outFile = Path.Combine(dir, $"{baseName}.unsparse.img");
            using var os = File.Create(outFile);
            long chunks = totalChunks;
            while (chunks > 0)
            {
                var ch = new byte[12];
                ReadExact(fd, ch, 0, 12);
                ushort chunkType = BitConverter.ToUInt16(ch, 0);
                uint chunkSz = BitConverter.ToUInt32(ch, 4);
                uint totalSz = BitConverter.ToUInt32(ch, 8);
                long sectorSize = (long)(chunkSz * blkSz) >> 9;
                long chunkDataSize = totalSz - chunkHdrSz;
                if (chunkType == 0xCAC1)
                {
                    if (chunkHdrSz > 12) fd.Seek(chunkHdrSz - 12, SeekOrigin.Current);
                    CopyExact(fd, os, chunkDataSize);
                }
                else
                {
                    if (chunkType is 0xCAC2 or 0xCAC3)
                    {
                        if (chunkHdrSz > 12) fd.Seek(chunkHdrSz - 12, SeekOrigin.Current);
                        fd.Seek(chunkDataSize, SeekOrigin.Current);
                    }
                    os.SetLength(os.Position + (sectorSize << 9));
                    os.Seek(0, SeekOrigin.End);
                }
                chunks--;
            }
            return outFile;
        }

        private static void CopyExact(Stream src, Stream dst, long count)
        {
            var buf = new byte[1 << 20];
            long remaining = count;
            while (remaining > 0)
            {
                int n = src.Read(buf, 0, (int)Math.Min(buf.Length, remaining));
                if (n <= 0) break;
                dst.Write(buf, 0, n);
                remaining -= n;
            }
        }

        private static string SafeName(string name)
        {
            name = name.Trim();
            name = name.Replace("\"", "");
            if (name.EndsWith(".")) name = name[..^1];
            return name;
        }

        private static string PermToOctal(string modeStr)
        {
            if (string.IsNullOrEmpty(modeStr)) return "0755";
            if (modeStr.Length == 10) modeStr = modeStr[1..];
            int o = 0, s = 0, w = 0, g = 0;
            var perms = new Dictionary<char, int> { { 'r', 4 }, { 'w', 2 }, { 'x', 1 } };
            for (int n = 0; n < modeStr.Length && n < 9; n++)
            {
                var sym = modeStr[n];
                bool has = perms.TryGetValue(sym, out var pv);
                if (n == 0 && has) o = pv;
                else if (n == 1 && has) o += pv;
                else if (n == 2)
                {
                    if (sym == 'S') s = 4;
                    else if (has) o += pv;
                    else if (sym == 's') { s += 4; o += 1; }
                }
                else if (n == 3 && has) g = pv;
                else if (n == 4 && has) g += pv;
                else if (n == 5)
                {
                    if (has) g += pv;
                    else if (sym == 'S') s += 2;
                    else if (sym == 's') { s += 2; g += 1; }
                }
                else if (n == 6 && has) w = pv;
                else if (n == 7 && has) w += pv;
                else if (n == 8)
                {
                    if (has) w += pv;
                    else if (sym == 'T') s += 1;
                    else if (sym == 't') { s += 1; w += 1; }
                }
            }
            return $"{s}{o}{g}{w}";
        }
    }

    // ==================== erofs ====================
    public sealed class ErofsTool : BaseTool
    {
        public bool Unpack(string image, string projectDir, string name = "")
        {
            if (!File.Exists(image)) throw new FileNotFoundException($"image 不存在: {image}");
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            if (name.Length == 0) name = Path.GetFileNameWithoutExtension(image);
            var outDir = Path.Combine(proj.ExtractedDir, name);
            Directory.CreateDirectory(outDir);
            var extractErofs = ExtTool.Resolve("extract.erofs", out var src);
            if (!File.Exists(extractErofs)) throw new FileNotFoundException($"未找到 extract.erofs (source={src})");
            var stepId = "erofs_unpack";
            StepStart?.Invoke(stepId, "解包 EROFS 镜像");
            try
            {
                Emit($"工程: {proj.Root}");
                Emit($"输入: {image}");
                Emit($"输出目录: {outDir}");
                var r = ExtProc.Run(new[] { extractErofs, "-i", image, "-x", "-o", outDir }, null, s => Emit(s), () => Stop, 1800000);
                var ok = r.ExitCode == 0 && !Stop;
                if (ok)
                {
                    bool hasContent = false;
                    try { hasContent = Directory.EnumerateFileSystemEntries(outDir).Any(); } catch { }
                    if (!hasContent) throw new InvalidOperationException("extract.erofs 执行成功但未提取到文件，请检查镜像或工具兼容性");
                    long sizeBytes = 0;
                    try { sizeBytes = new FileInfo(image).Length; } catch { }
                    WriteMeta(proj.ConfigDir, name, "image_meta", new { fs = "erofs", name, source_image = Path.GetFullPath(image), original_image_size_bytes = sizeBytes });
                }
                StepFinish?.Invoke(stepId, ok, ok ? "完成" : $"失败({r.ExitCode})");
                return ok;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
        }

        public bool Pack(string projectDir, string folder, string outName = "", string compress = "lz4hc", bool allowGrow = false)
        {
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            if (!Directory.Exists(folder)) throw new FileNotFoundException($"folder 不存在: {folder}");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            var name = Path.GetFileName(folder.TrimEnd('/', '\\'));
            var outName2 = string.IsNullOrEmpty(outName) ? $"{name}.img" : outName;
            if (!outName2.ToLowerInvariant().EndsWith(".img")) outName2 += ".img";
            var outImg = Path.Combine(proj.OutDir, outName2);
            var mkfsErofs = ExtTool.Resolve("mkfs.erofs", out var src);
            if (!File.Exists(mkfsErofs)) throw new FileNotFoundException($"未找到 mkfs.erofs (source={src})");
            if (compress.Length == 0) compress = "lz4hc";
            var stepId = "erofs_pack";
            StepStart?.Invoke(stepId, "打包 EROFS 镜像");
            try
            {
                Emit($"工程: {proj.Root}");
                Emit($"输入目录: {folder}");
                Emit($"输出: {outImg}");
                long? maxSize = null;
                var meta = ReadMeta(proj.ConfigDir, name, "image_meta");
                if (meta != null && meta.TryGetValue("original_image_size_bytes", out var v) && long.TryParse(v?.ToString(), out var rs) && rs > 0)
                    maxSize = rs;
                if (maxSize != null) Emit($"原镜像大小(记录): {maxSize}");
                if (File.Exists(outImg)) { try { File.Delete(outImg); } catch { } }
                var r = ExtProc.Run(new[] { mkfsErofs, "-z", compress, outImg, folder }, null, s => Emit(s), () => Stop, 900000);
                var ok = r.ExitCode == 0 && !Stop && File.Exists(outImg) && new FileInfo(outImg).Length > 0;
                if (ok && maxSize != null)
                {
                    var outSz = new FileInfo(outImg).Length;
                    if (outSz > maxSize.Value) Emit($"警告：输出镜像大小 {outSz} 超过原镜像大小 {maxSize}（按当前设置保留输出，不自动删除）");
                }
                StepFinish?.Invoke(stepId, ok, ok ? "完成" : $"失败({r.ExitCode})");
                return ok;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
        }
    }

    // ==================== super ====================
    public sealed class SuperImageTool : BaseTool
    {
        public bool Unpack(string superImg, string projectDir)
        {
            if (!File.Exists(superImg)) throw new FileNotFoundException($"super.img 不存在: {superImg}");
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            var stepId = "super_unpack";
            StepStart?.Invoke(stepId, "解包 super.img");
            try
            {
                CheckStop();
                Emit($"输入: {superImg}");
                Emit($"工程: {proj.Root}");
                Emit($"解包输出: {proj.ExtractedDir}");
                LpUnpack.Unpack(superImg, proj.ExtractedDir);
                StepFinish?.Invoke(stepId, true, "完成");
                return true;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
        }

        public bool Pack(string projectDir, string imagesDir, string outName = "super.img",
            string superName = "super", string groupName = "qti_dynamic_partitions",
            int metadataSize = 65536, int blockSize = 4096, bool sparse = true, bool readonly_ = false, long? superSize = null)
        {
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            if (!Directory.Exists(imagesDir)) throw new FileNotFoundException($"images_dir 不存在: {imagesDir}");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            // 空输出名回退到 super.img，与 Python 的 `req.out_name or "super.img"` 一致。
            outName = (string.IsNullOrWhiteSpace(outName) ? "super.img" : outName.Trim());
            if (!outName.ToLowerInvariant().EndsWith(".img")) outName += ".img";
            var outFile = Path.Combine(proj.OutDir, outName);
            var lpmake = ExtTool.Resolve("lpmake", out var src);
            if (!File.Exists(lpmake)) throw new FileNotFoundException($"未找到 lpmake: {lpmake} (source={src})");
            var stepId = "super_pack";
            StepStart?.Invoke(stepId, "打包 super.img");
            try
            {
                CheckStop();
                var imgs = Directory.EnumerateFiles(imagesDir)
                    .Where(p => !Path.GetFileName(p).StartsWith(".") && Path.GetExtension(p).ToLowerInvariant() == ".img")
                    .OrderBy(p => p, StringComparer.Ordinal)
                    .ToList();
                if (imgs.Count == 0) throw new InvalidOperationException("images_dir 下未找到任何 .img 分区镜像");
                long total = imgs.Sum(p => new FileInfo(p).Length);
                var autoSize = AlignUp(total + 8 * 1024 * 1024, 1024 * 1024);
                var superSizeVal = superSize ?? autoSize;
                Emit($"工程: {proj.Root}");
                Emit($"输入目录: {imagesDir}");
                Emit($"输出: {outFile}");
                Emit($"lpmake: {lpmake} (source={src})");
                Emit($"分区数: {imgs.Count}");
                Emit($"super_size: {superSizeVal}");
                var attr = readonly_ ? "readonly" : "none";
                var cmd = new List<string>
                {
                    lpmake, "--metadata-size", metadataSize.ToString(), "--super-name", superName,
                    $"-block-size={blockSize}"
                };
                if (sparse) cmd.Add("--sparse");
                cmd.AddRange(new[] { "--metadata-slots", "2", "--device", $"{superName}:{superSizeVal}", "--group", $"{groupName}:{superSizeVal}" });
                foreach (var p in imgs)
                {
                    var nm = Path.GetFileNameWithoutExtension(p);
                    cmd.AddRange(new[] { "--partition", $"{nm}:{attr}:{new FileInfo(p).Length}:{groupName}", "--image", $"{nm}={p.Replace(Path.DirectorySeparatorChar, '/')}" });
                }
                cmd.AddRange(new[] { "--output", outFile });
                if (File.Exists(outFile)) { try { File.Delete(outFile); } catch { } }
                var r = ExtProc.Run(cmd, null, s => Emit(s), () => Stop, 3600000);
                if (Stop)
                {
                    if (File.Exists(outFile)) { try { File.Delete(outFile); } catch { } }
                    StepFinish?.Invoke(stepId, false, "已取消");
                    return false;
                }
                if (r.ExitCode != 0 || !File.Exists(outFile) || new FileInfo(outFile).Length <= 0)
                {
                    if (File.Exists(outFile)) { try { File.Delete(outFile); } catch { } }
                    throw new InvalidOperationException($"lpmake 失败，退出码: {r.ExitCode}");
                }
                StepFinish?.Invoke(stepId, true, "完成");
                return true;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
        }
    }

    // ==================== dtbo ====================
    public sealed class DtboTool : BaseTool
    {
        private string RequireDtc()
        {
            var dtc = ExtTool.Resolve("dtc", out var src);
            if (!File.Exists(dtc)) throw new FileNotFoundException($"未找到 dtc (source={src})");
            Emit($"dtc: {dtc} (source={src})");
            return dtc;
        }

        public bool Unpack(string dtboImg, string projectDir, bool decompress = true)
        {
            if (!File.Exists(dtboImg)) throw new FileNotFoundException($"dtbo.img 不存在: {dtboImg}");
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            var stepId = "dtbo_unpack";
            StepStart?.Invoke(stepId, "解包 + 反编译 dtbo.img");
            try
            {
                CheckStop();
                var name = Path.GetFileNameWithoutExtension(dtboImg);
                var outDir = Path.Combine(proj.ExtractedDir, name, "dtbo_files");
                Directory.CreateDirectory(outDir);
                var outPrefix = Path.Combine(outDir, "dtbo");
                Emit($"输入: {dtboImg}");
                Emit($"工程: {proj.Root}");
                Emit($"解包输出: {outDir}");
                Mkdtboimg.DumpDtbo(dtboImg, outPrefix, decompress);
                var dtc = RequireDtc();
                var entries = Directory.EnumerateFiles(outDir)
                    .Where(p => Path.GetFileName(p).StartsWith("dtbo.") && !p.EndsWith(".dts"))
                    .OrderBy(p => p, StringComparer.Ordinal)
                    .ToList();
                if (entries.Count == 0) throw new InvalidOperationException("解包后未发现 dtbo.* 条目");
                Emit($"待反编译条目数: {entries.Count}");
                foreach (var src in entries)
                {
                    CheckStop();
                    var outDts = src + ".dts";
                    Emit($"反编译: {Path.GetFileName(src)} -> {Path.GetFileName(outDts)}");
                    var r = ExtProc.Run(new[] { dtc, "-q", "-I", "dtb", "-O", "dts", "-o", outDts, src }, null, s => Emit(s), () => Stop, 300000);
                    if (r.ExitCode != 0) throw new InvalidOperationException($"dtc 反编译失败: {Path.GetFileName(src)}，退出码: {r.ExitCode}");
                    if (!File.Exists(outDts) || new FileInfo(outDts).Length <= 0)
                        throw new InvalidOperationException($"dtc 反编译失败: 未生成有效 dts 文件 {outDts}");
                }
                StepFinish?.Invoke(stepId, true, "完成");
                return true;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
        }

        public bool Pack(string projectDir, string dtsDir, string outName = "dtbo.img", int pageSize = 4096)
        {
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            if (!Directory.Exists(dtsDir)) throw new FileNotFoundException($"dts_dir 不存在: {dtsDir}");
            // 空输出名回退到 dtbo.img，与 Python 的 `req.out_name or "dtbo.img"` 一致。
            outName = (string.IsNullOrWhiteSpace(outName) ? "dtbo.img" : outName.Trim());
            if (!outName.ToLowerInvariant().EndsWith(".img")) outName += ".img";
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            var stepId = "dtbo_pack";
            StepStart?.Invoke(stepId, "从 dts 回编译并打包 dtbo.img");
            var buildDir = Path.Combine(proj.ConfigDir, ".dtbo_build");
            try
            {
                CheckStop();
                var dtc = RequireDtc();
                var dtsFiles = Directory.EnumerateFiles(dtsDir)
                    .Where(p => !Path.GetFileName(p).StartsWith(".") && p.ToLowerInvariant().EndsWith(".dts"))
                    .OrderBy(p => p, StringComparer.Ordinal)
                    .ToList();
                if (dtsFiles.Count == 0) throw new InvalidOperationException("dts_dir 下未找到 *.dts 文件（仅支持从 dts 回编译）");
                if (Directory.Exists(buildDir)) { try { Directory.Delete(buildDir, true); } catch { } }
                Directory.CreateDirectory(buildDir);
                var dtbFiles = new List<string>();
                Emit($"工程: {proj.Root}");
                Emit($"输入目录: {dtsDir}");
                Emit($"构建目录: {buildDir}");
                Emit($"page_size: {pageSize}");
                Emit($"dts 条目数: {dtsFiles.Count}");
                foreach (var srcDts in dtsFiles)
                {
                    CheckStop();
                    var baseName = Path.GetFileNameWithoutExtension(srcDts);
                    var outDtb = Path.Combine(buildDir, baseName + ".dtb");
                    Emit($"回编译: {Path.GetFileName(srcDts)} -> {Path.GetFileName(outDtb)}");
                    var r = ExtProc.Run(new[] { dtc, "-q", "-I", "dts", "-O", "dtb", "-o", outDtb, srcDts }, null, s => Emit(s), () => Stop, 300000);
                    if (r.ExitCode != 0) throw new InvalidOperationException($"dtc 回编译失败: {Path.GetFileName(srcDts)}，退出码: {r.ExitCode}");
                    if (!File.Exists(outDtb) || new FileInfo(outDtb).Length <= 0)
                        throw new InvalidOperationException($"dtc 回编译失败: 未生成有效 dtb 文件 {outDtb}");
                    dtbFiles.Add(outDtb);
                }
                var outFile = Path.Combine(proj.OutDir, outName);
                Emit($"输出: {outFile}");
                Emit($"打包条目数: {dtbFiles.Count}");
                Mkdtboimg.CreateDtbo(outFile, dtbFiles, pageSize);
                if (!File.Exists(outFile) || new FileInfo(outFile).Length <= 0)
                    throw new InvalidOperationException("打包失败：未生成有效 dtbo.img 输出文件");
                StepFinish?.Invoke(stepId, true, "完成");
                return true;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
        }
    }

    // ==================== boot ====================
    public sealed class BootTool : BaseTool
    {
        public bool Unpack(string image, string projectDir, string name = "")
        {
            if (!File.Exists(image)) throw new FileNotFoundException($"image 不存在: {image}");
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            if (name.Length == 0) name = Path.GetFileNameWithoutExtension(image);
            var outDir = Path.Combine(proj.ExtractedDir, name);
            Directory.CreateDirectory(outDir);
            var magiskboot = ExtTool.Resolve("magiskboot", out var src);
            if (!File.Exists(magiskboot)) throw new FileNotFoundException($"未找到 magiskboot (source={src})");
            var stepId = "boot_unpack";
            StepStart?.Invoke(stepId, "解包 Boot 镜像");
            try
            {
                Emit($"工程: {proj.Root}");
                Emit($"输入: {image}");
                Emit($"输出目录: {outDir}");
                var r = ExtProc.Run(new[] { magiskboot, "unpack", "-h", image }, outDir, s => Emit(s), () => Stop, 600000);
                if (r.ExitCode != 0) throw new InvalidOperationException($"magiskboot unpack 失败，退出码: {r.ExitCode} (source={src})");
                WriteMeta(proj.ConfigDir, name, "boot_meta", new { name, original_image = Path.GetFullPath(image), extracted_dir = Path.GetFullPath(outDir) });
                var ok = !Stop;
                StepFinish?.Invoke(stepId, ok, ok ? "完成" : "已取消");
                return ok;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
        }

        public bool Pack(string projectDir, string folder, string outName = "", string originalImage = "")
        {
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            if (!Directory.Exists(folder)) throw new FileNotFoundException($"folder 不存在: {folder}");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            var name = Path.GetFileName(folder.TrimEnd('/', '\\'));
            var outName2 = string.IsNullOrEmpty(outName) ? $"{name}.img" : outName;
            if (!outName2.ToLowerInvariant().EndsWith(".img")) outName2 += ".img";
            var outImg = Path.Combine(proj.OutDir, outName2);
            var magiskboot = ExtTool.Resolve("magiskboot", out var src);
            if (!File.Exists(magiskboot)) throw new FileNotFoundException($"未找到 magiskboot (source={src})");
            var stepId = "boot_pack";
            StepStart?.Invoke(stepId, "打包 Boot 镜像");
            try
            {
                Emit($"工程: {proj.Root}");
                Emit($"输入目录: {folder}");
                Emit($"输出: {outImg}");
                var orig = originalImage;
                if (orig.Length == 0)
                {
                    var meta = ReadMeta(proj.ConfigDir, name, "boot_meta");
                    if (meta != null && meta.TryGetValue("original_image", out var v)) orig = v?.ToString() ?? "";
                }
                if (orig.Length == 0 || !File.Exists(orig))
                    throw new FileNotFoundException("未提供或未找到原始 boot 镜像（用于 magiskboot repack）。请先解包，或在打包时选择 original_image。");
                var tmpOut = Path.Combine(folder, "new-boot.img");
                var r = ExtProc.Run(new[] { magiskboot, "repack", orig, tmpOut }, folder, s => Emit(s), () => Stop, 600000);
                if (r.ExitCode != 0) throw new InvalidOperationException($"magiskboot repack 失败，退出码: {r.ExitCode} (source={src})");
                string? cand = null;
                foreach (var c in new[] { Path.GetFileName(tmpOut), "new-boot.img", "repacked.img", "repack.img", "new.img" })
                {
                    var p = Path.Combine(folder, c);
                    if (File.Exists(p) && new FileInfo(p).Length > 0) { cand = p; break; }
                }
                if (cand == null) throw new InvalidOperationException("未找到 magiskboot 生成的输出镜像（new-boot.img 等）");
                Directory.CreateDirectory(Path.GetDirectoryName(outImg)!);
                if (File.Exists(outImg)) { try { File.Delete(outImg); } catch { } }
                File.Move(cand, outImg);
                var ok = !Stop && File.Exists(outImg) && new FileInfo(outImg).Length > 0;
                StepFinish?.Invoke(stepId, ok, ok ? "完成" : "已取消");
                return ok;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
        }

        public bool PatchWithMagisk(string projectDir, string bootImage, string magiskApk, string outName = "")
        {
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            if (!File.Exists(bootImage)) throw new FileNotFoundException($"boot_image 不存在: {bootImage}");
            if (!File.Exists(magiskApk)) throw new FileNotFoundException($"magisk_apk 不存在: {magiskApk}");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            var magiskboot = ExtTool.Resolve("magiskboot", out var src);
            if (!File.Exists(magiskboot)) throw new FileNotFoundException($"未找到 magiskboot (source={src})");
            var baseName = Path.GetFileNameWithoutExtension(bootImage);
            var outName2 = string.IsNullOrEmpty(outName) ? $"magisk_patched-{baseName}.img" : outName;
            if (!outName2.ToLowerInvariant().EndsWith(".img")) outName2 += ".img";
            var outImg = Path.Combine(proj.OutDir, outName2);
            var stepId = "boot_magisk_patch";
            StepStart?.Invoke(stepId, "Magisk 修补 Boot 镜像");
            var workDir = Path.Combine(proj.ConfigDir, "magisk_patch_" + Guid.NewGuid().ToString("N")[..8]);
            try
            {
                Emit($"工程: {proj.Root}");
                Emit($"boot: {bootImage}");
                Emit($"magisk.apk: {magiskApk}");
                Emit($"工作目录: {workDir}");
                Emit($"输出: {outImg}");
                var apkDir = Path.Combine(workDir, "magisk_apk");
                Directory.CreateDirectory(apkDir);
                System.IO.Compression.ZipFile.ExtractToDirectory(magiskApk, apkDir);
                var bootPatch = Path.Combine(apkDir, "assets", "boot_patch.sh");
                if (!File.Exists(bootPatch))
                    throw new FileNotFoundException("magisk.apk 中未找到 assets/boot_patch.sh，当前版本暂不支持该包结构");
                var patchDir = Path.Combine(workDir, "patch");
                Directory.CreateDirectory(patchDir);
                var bootCopy = Path.Combine(patchDir, Path.GetFileName(bootImage));
                File.Copy(bootImage, bootCopy, true);
                File.Copy(magiskboot, Path.Combine(patchDir, Path.GetFileName(magiskboot)), true);
                File.Copy(bootPatch, Path.Combine(patchDir, "boot_patch.sh"), true);
                foreach (var (rel0, rel1, rel2, rel3) in new[]
                {
                    ("lib","arm64-v8a","libmagisk32.so","magisk32"), ("lib","arm64-v8a","libmagisk64.so","magisk64"),
                    ("lib","arm64-v8a","libmagiskinit.so","magiskinit"), ("lib","arm64-v8a","libmagiskboot.so","magiskboot")
                })
                {
                    var srcLib = Path.Combine(apkDir, rel0, rel1, rel2);
                    if (File.Exists(srcLib)) File.Copy(srcLib, Path.Combine(patchDir, rel3), true);
                }
                var env = new Dictionary<string, string>
                {
                    ["KEEPVERITY"] = "false", ["KEEPFORCEENCRYPT"] = "false", ["PATCHVBMETAFLAG"] = "false"
                };
                var busybox = ExtTool.Resolve("busybox", out var bbSrc);
                ProcessResult r;
                if (File.Exists(busybox))
                {
                    Emit($"shell: {busybox} (source={bbSrc})");
                    r = ExtProc.RunAsync(new[] { busybox, "sh", "boot_patch.sh", bootCopy }, patchDir, env, s => Emit(s), () => Stop, 900000).GetAwaiter().GetResult();
                }
                else
                {
                    Emit("shell: sh (system)");
                    r = ExtProc.RunAsync(new[] { "sh", "boot_patch.sh", bootCopy }, patchDir, env, s => Emit(s), () => Stop, 900000).GetAwaiter().GetResult();
                }
                if (r.ExitCode != 0) throw new InvalidOperationException($"Magisk patch 失败，退出码: {r.ExitCode}");
                string? cand = null;
                foreach (var fn in Directory.EnumerateFiles(patchDir))
                {
                    var low = fn.ToLowerInvariant();
                    if (low.EndsWith(".img") && (low.Contains("patched") || low.Contains("new-")))
                    {
                        if (new FileInfo(fn).Length > 0) { cand = fn; break; }
                    }
                }
                if (cand == null)
                {
                    foreach (var fn in new[] { "new-boot.img", "magisk_patched.img" })
                    {
                        var p = Path.Combine(patchDir, fn);
                        if (File.Exists(p) && new FileInfo(p).Length > 0) { cand = p; break; }
                    }
                }
                if (cand == null) throw new InvalidOperationException("未找到 Magisk 修补输出镜像");
                Directory.CreateDirectory(Path.GetDirectoryName(outImg)!);
                if (File.Exists(outImg)) { try { File.Delete(outImg); } catch { } }
                File.Copy(cand, outImg, true);
                var ok = !Stop && File.Exists(outImg) && new FileInfo(outImg).Length > 0;
                StepFinish?.Invoke(stepId, ok, ok ? "完成" : "已取消");
                return ok;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
            finally
            {
                try { Directory.Delete(workDir, true); } catch { }
            }
        }
    }

    // ==================== dat/br ====================
    public sealed class DatBrTool : BaseTool
    {
        private static List<(long, long)> RangeSet(string src)
        {
            var parts = src.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            var nums = parts.Select(p => long.Parse(p.Trim())).ToList();
            if (nums.Count != nums[0] + 1) throw new InvalidOperationException($"transfer.list rangeset 格式错误: {src}");
            var list = new List<(long, long)>();
            for (int i = 1; i < nums.Count; i += 2) list.Add((nums[i], nums[i + 1]));
            return list;
        }

        public bool Unpack(string projectDir, string transferList, string newDatOrBr, string name = "")
        {
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            if (!File.Exists(transferList)) throw new FileNotFoundException($"transfer.list 不存在: {transferList}");
            if (!File.Exists(newDatOrBr)) throw new FileNotFoundException($"new.dat/new.dat.br 不存在: {newDatOrBr}");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            if (name.Length == 0)
            {
                var b = Path.GetFileName(newDatOrBr);
                name = b.Replace(".new.dat.br", "").Replace(".new.dat", "").Replace(".br", "");
                if (name.Length == 0) name = "partition";
            }
            var outImg = Path.Combine(proj.ExtractedDir, $"{name}.img");
            var stepId = "datbr_unpack";
            StepStart?.Invoke(stepId, "解包 DAT/BR -> IMG");
            try
            {
                Emit($"工程: {proj.Root}");
                Emit($"transfer.list: {transferList}");
                Emit($"new.dat(.br): {newDatOrBr}");
                Emit($"输出: {outImg}");
                var raw = File.ReadAllBytes(newDatOrBr);
                if (newDatOrBr.EndsWith(".br", StringComparison.OrdinalIgnoreCase))
                {
                    Emit("检测到 .br，进行 brotli 解压...");
                    raw = BrotliDecompress(raw);
                }
                var lines = File.ReadAllLines(transferList);
                if (lines.Length < 2) throw new InvalidOperationException("transfer.list 格式错误");
                int version = int.Parse(lines[0].Trim());
                int index = 2;
                if (version >= 2) index = 4;
                const int blockSize = 4096;
                Emit($"transfer.list 版本: {version}");
                using (var outF = new FileStream(outImg, FileMode.Create, FileAccess.Write))
                {
                    long pos = 0;
                    long maxFileSize = 0;
                    for (; index < lines.Length; index++)
                    {
                        var parts = lines[index].Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
                        if (parts.Length < 2) continue;
                        var cmd = parts[0];
                        if (cmd != "new") continue;
                        foreach (var (begin, end) in RangeSet(parts[1]))
                        {
                            long count = end - begin;
                            maxFileSize = Math.Max(maxFileSize, end * blockSize);
                            outF.Seek(begin * blockSize, SeekOrigin.Begin);
                            for (long i = 0; i < count; i++)
                            {
                                if (Stop) break;
                                if (pos + blockSize > raw.Length)
                                    throw new InvalidOperationException($"new.dat 数据不足：需要至少 {pos + blockSize} 字节，但仅有 {raw.Length} 字节。（transfer.list 与 new.dat 不匹配）");
                                outF.Write(raw, (int)pos, blockSize);
                                pos += blockSize;
                            }
                        }
                    }
                    if (outF.Position < maxFileSize) outF.SetLength(maxFileSize);
                }
                var ok = !Stop && File.Exists(outImg) && new FileInfo(outImg).Length > 0;
                StepFinish?.Invoke(stepId, ok, ok ? "完成" : "已取消");
                return ok;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
        }

        public bool Pack(string projectDir, string image, string name = "", int version = 4, bool compressBr = true)
        {
            if (string.IsNullOrEmpty(projectDir)) throw new ArgumentException("project_dir 不能为空");
            if (!File.Exists(image)) throw new FileNotFoundException($"image 不存在: {image}");
            var proj = new ImageFactoryProject(projectDir);
            proj.Ensure();
            if (name.Length == 0) name = Path.GetFileNameWithoutExtension(image);
            var outPrefix = Path.Combine(proj.OutDir, name);
            var outTl = outPrefix + ".transfer.list";
            var outNew = outPrefix + ".new.dat";
            var outNewBr = outNew + ".br";
            var stepId = "datbr_pack";
            StepStart?.Invoke(stepId, "打包 IMG -> DAT/BR");
            try
            {
                Emit($"工程: {proj.Root}");
                Emit($"输入: {image}");
                Emit($"输出前缀: {outPrefix}");
                var size = new FileInfo(image).Length;
                const int blockSize = 4096;
                long blocks = (size + blockSize - 1) / blockSize;
                var tl = new List<string> { version.ToString(), blocks.ToString() };
                if (version >= 2) { tl.Add("0"); tl.Add("0"); }
                tl.Add($"new 2,0,{blocks}");
                // 设备端读 transfer.list 时不接受 CRLF，与 Python 的 newline="\n" 保持一致。
                WriteLfText(outTl, tl);
                using (var src = File.OpenRead(image))
                using (var dst = File.Create(outNew))
                {
                    src.CopyTo(dst);
                    long pad = blocks * blockSize - size;
                    if (pad > 0) dst.Write(new byte[pad], 0, (int)pad);
                }
                CheckStop();
                if (compressBr)
                {
                    Emit("生成 .br（brotli 压缩）...");
                    var raw = File.ReadAllBytes(outNew);
                    var comp = BrotliCompress(raw);
                    File.WriteAllBytes(outNewBr, comp);
                }
                var ok = File.Exists(outTl) && File.Exists(outNew) && new FileInfo(outNew).Length > 0;
                StepFinish?.Invoke(stepId, ok, ok ? "完成" : "失败");
                return ok;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(stepId, false, e.Message);
                throw;
            }
        }

        public static byte[] BrotliDecompress(byte[] data)
        {
            using var ms = new MemoryStream(data);
            using var br = new System.IO.Compression.BrotliStream(ms, System.IO.Compression.CompressionMode.Decompress);
            using var outMs = new MemoryStream();
            br.CopyTo(outMs);
            return outMs.ToArray();
        }

        public static byte[] BrotliCompress(byte[] data)
        {
            using var ms = new MemoryStream();
            using (var br = new System.IO.Compression.BrotliStream(ms, System.IO.Compression.CompressionLevel.Optimal, true))
                br.Write(data, 0, data.Length);
            return ms.ToArray();
        }
    }
}
