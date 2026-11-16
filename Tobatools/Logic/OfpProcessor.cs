// OFP 解密/提取方案参考自 TIK（GPL-3.0，另附非商业条款）: https://github.com/ColdWindScholar/TIK
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Xml.Linq;

namespace Tobatools.Logic
{
    /// <summary>OFP 固件包处理器（高通 QC / 联发科 MTK）纯 C# 移植。</summary>
    public class OfpProcessor
    {
        public Action<string>? Log { get; set; }
        public Action<string, string>? StepStart { get; set; }
        public Action<string, bool, string>? StepFinish { get; set; }
        private volatile bool _stop;

        public void Stop() => _stop = true;

        private void Emit(string s) { try { Log?.Invoke(s); } catch { } }
        private void CheckStop() { if (_stop) throw new InvalidOperationException("已取消"); }

        // ---------- 通用 ----------
        private static byte Swap(int ch) => (byte)(((ch & 0xF) << 4) + ((ch & 0xF0) >> 4));

        private static byte[] KeyShuffle(byte[] key, byte[] hkey)
        {
            var k = (byte[])key.Clone();
            for (int i = 0; i < 0x10; i += 4)
            {
                k[i] = Swap(hkey[i] ^ k[i]);
                k[i + 1] = Swap(hkey[i + 1] ^ k[i + 1]);
                k[i + 2] = Swap(hkey[i + 2] ^ k[i + 2]);
                k[i + 3] = Swap(hkey[i + 3] ^ k[i + 3]);
            }
            return k;
        }

        private static byte Rol(byte x, int n) // 8-bit rotate left; n=4 in usage
        {
            n %= 8;
            return (byte)((x << n) | (x >> (8 - n)));
        }

        private static byte[] Deobfuscate(byte[] data, byte[] mask)
        {
            var ret = new byte[data.Length];
            for (int i = 0; i < data.Length; i++)
                ret[i] = Rol((byte)(data[i] ^ mask[i % mask.Length]), 4);
            return ret;
        }

        private static byte[] AesCfb(byte[] data, byte[] key, byte[] iv)
        {
            using var aes = Aes.Create();
            aes.Mode = CipherMode.CFB;
            aes.FeedbackSize = 128;
            aes.Padding = PaddingMode.None;
            aes.Key = key;
            aes.IV = iv;
            using var dec = aes.CreateDecryptor();
            return dec.TransformFinalBlock(data, 0, data.Length);
        }

        private static byte[] HexBytes(string hex) => Convert.FromHexString(hex);

        private static string Md5Hex16(byte[] data)
        {
            using var md5 = MD5.Create();
            return Convert.ToHexString(md5.ComputeHash(data)).ToLowerInvariant()[..16];
        }

        // ---------- QC ----------
        private static readonly string[][] QcKeys =
        {
            new[] { "V1.4.17/1.4.27", "27827963787265EF89D126B69A495A21", "82C50203285A2CE7D8C3E198383CE94C", "422DD5399181E223813CD8ECDF2E4D72" },
            new[] { "V1.6.17", "E11AA7BB558A436A8375FD15DDD4651F", "77DDF6A0696841F6B74782C097835169", "A739742384A44E8BA45207AD5C3700EA" },
            new[] { "V1.5.13", "67657963787565E837D226B69A495D21", "F6C50203515A2CE7D8C3E1F938B7E94C", "42F2D5399137E2B2813CD8ECDF2F4D72" },
            new[] { "V1.6.6/1.6.9/1.6.17/1.6.24/1.6.26/1.7.6", "3C2D518D9BF2E4279DC758CD535147C3", "87C74A29709AC1BF2382276C4E8DF232", "598D92E967265E9BCABE2469FE4A915E" },
            new[] { "V1.7.2", "8FB8FB261930260BE945B841AEFA9FD4", "E529E82B28F5A2F8831D860AE39E425D", "8A09DA60ED36F125D64709973372C1CF" },
            new[] { "V2.0.3", "E8AE288C0192C54BF10C5707E9C4705B", "D64FC385DCD52A3C9B5FBA8650F92EDA", "79051FD8D8B6297E2E4559E997F63B7F" },
        };

        public bool Extract(string ofpPath, string outDir, string mode = "auto")
        {
            var p = ofpPath.Trim();
            if (!File.Exists(p)) throw new FileNotFoundException(p);
            Directory.CreateDirectory(outDir);
            var m = mode.Trim().ToLowerInvariant();
            if (m is not ("auto" or "qc" or "mtk")) throw new ArgumentException($"unknown mode: {mode}");
            var sid = Guid.NewGuid().ToString("N");
            StepStart?.Invoke(sid, $"处理 OFP ({m})");
            try
            {
                if (m == "qc") { var r = ExtractQc(p, outDir); StepFinish?.Invoke(sid, r, ""); return r; }
                if (m == "mtk") { var r = ExtractMtk(p, outDir); StepFinish?.Invoke(sid, r, ""); return r; }
                try
                {
                    if (ExtractQc(p, outDir)) { StepFinish?.Invoke(sid, true, "QC模式"); return true; }
                }
                catch { }
                var r2 = ExtractMtk(p, outDir);
                StepFinish?.Invoke(sid, r2, "MTK模式");
                return r2;
            }
            catch (Exception e)
            {
                StepFinish?.Invoke(sid, false, e.Message);
                throw;
            }
        }

        private (int pageSize, byte[] key, byte[] iv, byte[] xml) QcGenerateKey(string filename)
        {
            foreach (var dkey in QcKeys)
            {
                CheckStop();
                var mc = HexBytes(dkey[1]);
                var userkey = HexBytes(dkey[2]);
                var ivec = HexBytes(dkey[3]);
                var key = Encoding.ASCII.GetBytes(Md5Hex16(Deobfuscate(userkey, mc)));
                var iv = Encoding.ASCII.GetBytes(Md5Hex16(Deobfuscate(ivec, mc)));
                var (pageSize, dec) = QcExtractXml(filename, key, iv);
                if (pageSize != 0) return (pageSize, key, iv, dec);
            }
            return (0, Array.Empty<byte>(), Array.Empty<byte>(), Array.Empty<byte>());
        }

        /// <summary>
        /// 读取恰好 count 个字节。Stream.Read 允许短读（返回少于请求的字节数），
        /// OFP 解析依赖固定长度字段，短读会静默产出错误数据。
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

        private static (int, byte[]) QcExtractXml(string filename, byte[] key, byte[] iv)
        {
            var filesize = new FileInfo(filename).Length;
            int pagesize = 0;
            byte[] data;
            using (var rf = File.OpenRead(filename))
            {
                foreach (var x in new[] { 0x200L, 0x1000L })
                {
                    rf.Seek(filesize - x + 0x10, SeekOrigin.Begin);
                    var b4 = new byte[4];
                    ReadExact(rf, b4, 0, 4);
                    if (BitConverter.ToUInt32(b4, 0) == 0x7CEF) { pagesize = (int)x; break; }
                }
                if (pagesize == 0) throw new InvalidOperationException("unknown pagesize");
                long xmloffset = filesize - pagesize;
                rf.Seek(xmloffset + 0x14, SeekOrigin.Begin);
                var b4a = new byte[4];
                ReadExact(rf, b4a, 0, 4);
                var offset = BitConverter.ToUInt32(b4a, 0) * pagesize;
                ReadExact(rf, b4a, 0, 4);
                long length = BitConverter.ToUInt32(b4a, 0);
                if (length < 200) length = xmloffset - offset - 0x57;
                rf.Seek(offset, SeekOrigin.Begin);
                data = new byte[length];
                ReadExact(rf, data, 0, (int)length);
            }
            var dec = AesCfb(data, key, iv);
            if (!ContainsAscii(dec, "<?xml")) return (0, Array.Empty<byte>());
            return (pagesize, dec);
        }

        private static bool ContainsAscii(byte[] data, string ascii)
        {
            var s = Encoding.ASCII.GetString(data);
            return s.Contains(ascii);
        }

        private static (string file, long start, long length, long rlength, string sha, string md5, int decryptsize) QcParseItem(XElement item, int pagesize)
        {
            var sha = (string?)item.Attribute("sha256") ?? "";
            var md5 = (string?)item.Attribute("md5") ?? "";
            var wfile = (string?)item.Attribute("Path") ?? (string?)item.Attribute("filename") ?? "";
            long start = -1;
            var fos = (string?)item.Attribute("FileOffsetInSrc");
            var siz = (string?)item.Attribute("SizeInSectorInSrc");
            if (fos != null && long.TryParse(fos, out var fv)) start = fv * pagesize;
            else if (siz != null && long.TryParse(siz, out var sv)) start = sv * pagesize;
            long rlength = 0;
            var sib = (string?)item.Attribute("SizeInByteInSrc");
            if (sib != null && long.TryParse(sib, out var rv)) rlength = rv;
            long length = rlength;
            if (siz != null && long.TryParse(siz, out var lv)) length = lv * pagesize;
            return (wfile, start, length, rlength, sha, md5, 0x40000);
        }

        private static string HashStatusCn(string s)
        {
            var v = (s ?? "").Trim().ToLowerInvariant();
            if (v == "verified") return "已校验";
            if (v == "bad") return "不匹配";
            if (v == "empty") return "无";
            return s ?? "";
        }

        private static string OpPrefixCn(bool iscopy) => iscopy ? "拷贝: " : "解密: ";

        private void QcCheckHash(string path, string sha256sum, string md5sum, bool iscopy)
        {
            var prefix = OpPrefixCn(iscopy);
            try
            {
                long size = new FileInfo(path).Length;
                byte[] md5;
                string? sha256status = "empty";
                string md5status = "empty";
                bool sha256bad = false, md5bad = false;
                using (var rf = File.OpenRead(path))
                {
                    var head = new byte[0x40000];
                    int n = rf.Read(head, 0, head.Length);
                    using (var m = MD5.Create())
                        md5 = m.ComputeHash(head, 0, n);
                    if (!string.IsNullOrEmpty(sha256sum))
                    {
                        foreach (var x in new[] { 0x40000L, size })
                        {
                            CheckStop();
                            using var sha = SHA256.Create();
                            rf.Seek(0, SeekOrigin.Begin);
                            if (x == 0x40000)
                            {
                                var buf = new byte[Math.Min(x, 0x100000)];
                                int rn = rf.Read(buf, 0, buf.Length);
                                sha.TransformBlock(buf, 0, rn, null, 0);
                            }
                            else
                            {
                                var buf = new byte[0x20000];
                                int rn;
                                while ((rn = rf.Read(buf, 0, buf.Length)) > 0)
                                {
                                    CheckStop();
                                    sha.TransformBlock(buf, 0, rn, null, 0);
                                }
                            }
                            sha.TransformFinalBlock(Array.Empty<byte>(), 0, 0);
                            var hx = Convert.ToHexString(sha.Hash!).ToLowerInvariant();
                            if (!string.Equals(sha256sum.ToLowerInvariant(), hx))
                            {
                                sha256bad = true;
                                sha256status = "bad";
                            }
                            else
                            {
                                sha256status = "verified";
                                sha256bad = false;
                                break;
                            }
                        }
                    }
                    if (!string.IsNullOrEmpty(md5sum))
                    {
                        var hx = Convert.ToHexString(md5).ToLowerInvariant();
                        if (!string.Equals(md5sum.ToLowerInvariant(), hx)) { md5bad = true; md5status = "bad"; }
                        else { md5status = "verified"; md5bad = false; }
                    }
                }
                if ((sha256bad && md5bad) || (sha256bad && string.IsNullOrEmpty(md5sum)) || (md5bad && string.IsNullOrEmpty(sha256sum)))
                    Emit(prefix + "校验失败（hash 不匹配），文件可能损坏");
                else
                    Emit(prefix + $"成功 (md5: {HashStatusCn(md5status)} | sha256: {HashStatusCn(sha256status)})");
            }
            catch { }
        }

        private void QcCopy(string filename, string outDir, string wfile, long start, long length, string sha, string md5)
        {
            Emit($"正在提取 {wfile}");
            var outPath = Path.Combine(outDir, wfile);
            Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
            using (var rf = File.OpenRead(filename))
            {
                rf.Seek(start, SeekOrigin.Begin);
                var data = new byte[length];
                ReadExact(rf, data, 0, (int)length);
                File.WriteAllBytes(outPath, data);
            }
            QcCheckHash(outPath, sha, md5, true);
        }

        private void QcDecryptFile(byte[] key, byte[] iv, string filename, string outDir, string wfile,
            long start, long length, long rlength, string sha, string md5, int decryptsize = 0x40000)
        {
            Emit($"正在提取 {wfile}");
            var outPath = Path.Combine(outDir, wfile);
            Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
            if (rlength == length)
            {
                long tlen = length;
                length = (length / 0x4 * 0x4);
                if (tlen % 0x4 != 0) length += 0x4;
            }
            using (var rf = File.OpenRead(filename))
            {
                rf.Seek(start, SeekOrigin.Begin);
                long size = decryptsize;
                if (rlength < decryptsize) size = rlength;
                var data = new byte[size];
                ReadExact(rf, data, 0, (int)size);
                if (size % 4 != 0)
                {
                    var padded = new byte[size + (4 - size % 4)];
                    Array.Copy(data, padded, size);
                    data = padded;
                }
                var outp = AesCfb(data, key, iv);
                using var wf = new FileStream(outPath, FileMode.Create, FileAccess.Write);
                wf.Write(outp, 0, (int)size);
                if (rlength > decryptsize)
                {
                    long remain = rlength - size;
                    var buf = new byte[0x100000];
                    while (remain > 0)
                    {
                        CheckStop();
                        int chunk = rf.Read(buf, 0, (int)Math.Min(0x100000, remain));
                        if (chunk <= 0) break;
                        wf.Write(buf, 0, chunk);
                        remain -= chunk;
                    }
                }
            }
            QcCheckHash(outPath, sha, md5, false);
        }

        private bool ExtractQc(string ofpPath, string outDir)
        {
            Emit("模式: 高通 (QC)");
            CheckStop();
            byte[] head;
            using (var rf = File.OpenRead(ofpPath))
            {
                head = new byte[2];
                ReadExact(rf, head, 0, 2);
            }
            if (head[0] == 'P' && head[1] == 'K')
            {
                Emit("检测到 ZIP 格式 OFP，尝试解密/解压");
                var zippw = Encoding.ASCII.GetBytes("flash@realme$50E7F7D847732396F1582CD62DD385ED7ABB0897");
                using var zf = System.IO.Compression.ZipFile.OpenRead(ofpPath);
                foreach (var entry in zf.Entries)
                {
                    CheckStop();
                    Emit("正在提取 " + entry.FullName);
                    var dest = Path.Combine(outDir, entry.FullName.Replace('/', Path.DirectorySeparatorChar));
                    Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
                    using var es = entry.Open();
                    using var os = new FileStream(dest, FileMode.Create, FileAccess.Write);
                    // 带密码的 zip：使用 AES? Python zipfile 用 PKZIP 传统加密；此处先尝试明文读取
                    es.CopyTo(os);
                }
                return true;
            }

            var (pagesize, key, iv, data) = QcGenerateKey(ofpPath);
            if (pagesize == 0) throw new InvalidOperationException("无法识别此 OFP 的密钥");
            int xmlEnd = data.Length;
            for (int i = data.Length - 1; i >= 0; i--) { if (data[i] == (byte)'>') { xmlEnd = i + 1; break; } }
            var xmlBytes = data[..xmlEnd];
            var xml = Encoding.UTF8.GetString(xmlBytes);
            try { File.WriteAllText(Path.Combine(outDir, "ProFile.xml"), xml, new UTF8Encoding(false)); } catch { }
            var root = XElement.Parse(xml, LoadOptions.None);
            foreach (var child in root.Elements())
            {
                CheckStop();
                foreach (var item in child.Elements())
                {
                    CheckStop();
                    if (item.Attribute("Path") == null && item.Attribute("filename") == null)
                    {
                        foreach (var subitem in item.Elements())
                        {
                            var (wfile, start, length, rlength, sha, md5, ds) = QcParseItem(subitem, pagesize);
                            if (wfile.Length == 0 || start == -1) continue;
                            QcDecryptFile(key, iv, ofpPath, outDir, wfile, start, length, rlength, sha, md5, ds);
                        }
                    }
                    var (wfile2, start2, length2, rlength2, sha2, md5_2, ds2) = QcParseItem(item, pagesize);
                    if (wfile2.Length == 0 || start2 == -1) continue;
                    if (child.Name.LocalName == "Sahara") ds2 = (int)rlength2;
                    if (child.Name.LocalName is "Config" or "Provision" or "ChainedTableOfDigests" or "DigestsToSign" or "Firmware")
                        length2 = rlength2;
                    if (child.Name.LocalName is "DigestsToSign" or "ChainedTableOfDigests" or "Firmware")
                        QcCopy(ofpPath, outDir, wfile2, start2, length2, sha2, md5_2);
                    else
                        QcDecryptFile(key, iv, ofpPath, outDir, wfile2, start2, length2, rlength2, sha2, md5_2, ds2);
                }
            }
            return true;
        }

        // ---------- MTK ----------
        private static byte[] MtkShuffle(byte[] key, byte[] data)
        {
            var d = (byte[])data.Clone();
            for (int i = 0; i < d.Length; i++)
            {
                var k = key[i % key.Length];
                var h = (byte)((((d[i]) & 0xF0) >> 4) | (16 * ((d[i]) & 0xF)));
                d[i] = (byte)(k ^ h);
            }
            return d;
        }

        private static byte[] MtkShuffle2(byte[] key, byte[] data)
        {
            var d = (byte[])data.Clone();
            for (int i = 0; i < d.Length; i++)
            {
                var tmp = key[i % key.Length] ^ d[i];
                d[i] = (byte)(((tmp & 0xF0) >> 4) | (16 * (tmp & 0xF)));
            }
            return d;
        }

        private static readonly string[][] MtkKeyTables =
        {
            new[] { "67657963787565E837D226B69A495D21", "F6C50203515A2CE7D8C3E1F938B7E94C", "42F2D5399137E2B2813CD8ECDF2F4D72" },
            new[] { "9E4F32639D21357D37D226B69A495D21", "A3D8D358E42F5A9E931DD3917D9A3218", "386935399137416B67416BECF22F519A" },
            new[] { "892D57E92A4D8A975E3C216B7C9DE189", "D26DF2D9913785B145D18C7219B89F26", "516989E4A1BFC78B365C6BC57D944391" },
            new[] { "27827963787265EF89D126B69A495A21", "82C50203285A2CE7D8C3E198383CE94C", "422DD5399181E223813CD8ECDF2E4D72" },
            new[] { "3C4A618D9BF2E4279DC758CD535147C3", "87B13D29709AC1BF2382276C4E8DF232", "59B7A8E967265E9BCABE2469FE4A915E" },
            new[] { "1C3288822BF824259DC852C1733127D3", "E7918D22799181CF2312176C9E2DF298", "3247F889A7B6DECBCA3E28693E4AAAFE" },
            new[] { "1E4F32239D65A57D37D2266D9A775D43", "A332D3C3E42F5A3E931DD991729A321D", "3F2A35399A373377674155ECF28FD19A" },
            new[] { "122D57E92A518AFF5E3C786B7C34E189", "DD6DF2D9543785674522717219989FB0", "12698965A132C76136CC88C5DD94EE91" },
            new[] { "ab3f76d7989207f2", "2bf515b3a9737835" },
        };

        private static (string key, string iv, int count) MtkGetKey(int index)
        {
            var kt = MtkKeyTables[index];
            if (kt.Length == 3)
            {
                var obskey = HexBytes(kt[0]);
                var encaeskey = HexBytes(kt[1]);
                var encaesiv = HexBytes(kt[2]);
                var aeskey = Md5Hex16(MtkShuffle2(obskey, encaeskey));
                var aesiv = Md5Hex16(MtkShuffle2(obskey, encaesiv));
                return (aeskey, aesiv, MtkKeyTables.Length);
            }
            return (kt[0], kt[1], MtkKeyTables.Length);
        }

        private static (byte[], byte[]) MtkBruteKey(Stream rf)
        {
            rf.Seek(0, SeekOrigin.Begin);
            var encdata = new byte[16];
            ReadExact(rf, encdata, 0, 16);
            var (_, _, count) = MtkGetKey(0);
            for (int keyid = 0; keyid < count; keyid++)
            {
                var (ks, vs, _) = MtkGetKey(keyid);
                var key = Encoding.ASCII.GetBytes(ks);
                var iv = Encoding.ASCII.GetBytes(vs);
                var data = AesCfb(encdata, key, iv);
                if (data.Length >= 3 && data[0] == (byte)'M' && data[1] == (byte)'M' && data[2] == (byte)'M')
                    return (key, iv);
            }
            throw new InvalidOperationException("unknown key");
        }

        private static string CleanCString(byte[] b)
        {
            var list = b.TakeWhile(x => x != 0).ToArray();
            return Encoding.UTF8.GetString(list);
        }

        private bool ExtractMtk(string ofpPath, string outDir)
        {
            Emit("模式: 联发科 (MTK)");
            var hdrkey = Encoding.ASCII.GetBytes("geyixue");
            var filesize = new FileInfo(ofpPath).Length;
            const int hdrlength = 0x6C;
            using (var rf = File.OpenRead(ofpPath))
            {
                var (aeskey, aesiv) = MtkBruteKey(rf);
                rf.Seek(filesize - hdrlength, SeekOrigin.Begin);
                var hdrRaw = new byte[hdrlength];
                ReadExact(rf, hdrRaw, 0, hdrlength);
                var hdr = MtkShuffle(hdrkey, hdrRaw);
                // 46s Q 4s 7s 5s H 32s H
                var prjname = CleanCString(hdr[0..46]);
                var hdr2entries = BitConverter.ToUInt16(hdr, 46 + 8 + 4 + 7 + 5);
                var prjinfo = CleanCString(hdr[(46 + 8 + 4 + 7 + 5 + 2)..(46 + 8 + 4 + 7 + 5 + 2 + 32)]);
                var cpu = CleanCString(hdr[(46 + 8)..(46 + 8 + 4)]);
                var flashtype = CleanCString(hdr[(46 + 8 + 4)..(46 + 8 + 4 + 7)]);
                if (prjname.Length > 0) Emit("检测到项目: " + prjname);
                if (prjinfo.Length > 0) Emit("检测到信息: " + prjinfo);
                if (cpu.Length > 0) Emit("检测到 CPU: " + cpu);
                if (flashtype.Length > 0) Emit("检测到存储类型: " + flashtype);

                var hdr2length = hdr2entries * 0x60;
                rf.Seek(filesize - hdr2length - hdrlength, SeekOrigin.Begin);
                var hdr2Raw = new byte[hdr2length];
                ReadExact(rf, hdr2Raw, 0, hdr2Raw.Length);
                var hdr2 = MtkShuffle(hdrkey, hdr2Raw);

                for (int i = 0; i < hdr2.Length / 0x60; i++)
                {
                    CheckStop();
                    var entry = hdr2[(i * 0x60)..(i * 0x60 + 0x60)];
                    // <32s Q Q Q 32s Q
                    var name = CleanCString(entry[0..32]);
                    var start = BitConverter.ToInt64(entry, 32);
                    var length = BitConverter.ToInt64(entry, 40);
                    var enclength = BitConverter.ToInt64(entry, 48);
                    var filename = CleanCString(entry[56..88]);
                    if (filename.Length == 0) continue;
                    Emit($"正在写出 \"{name}\" -> \"{filename}\"");
                    var outPath = Path.Combine(outDir, filename);
                    Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
                    using (var wb = new FileStream(outPath, FileMode.Create, FileAccess.Write))
                    {
                        if (enclength > 0)
                        {
                            rf.Seek(start, SeekOrigin.Begin);
                            var encdata = new byte[enclength];
                            ReadExact(rf, encdata, 0, (int)enclength);
                            if (enclength % 16 != 0)
                            {
                                var padded = new byte[enclength + (16 - enclength % 16)];
                                Array.Copy(encdata, padded, enclength);
                                encdata = padded;
                            }
                            var data = AesCfb(encdata, aeskey, aesiv);
                            wb.Write(data, 0, (int)enclength);
                            length -= enclength;
                        }
                        var buf = new byte[0x200000];
                        while (length > 0)
                        {
                            CheckStop();
                            int size = (int)Math.Min(0x200000, length);
                            int rn = rf.Read(buf, 0, size);
                            if (rn <= 0) break;
                            length -= rn;
                            wb.Write(buf, 0, rn);
                        }
                    }
                }
            }
            return true;
        }
    }
}
