using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Tobatools.Models;

namespace Tobatools.Services
{
    public class AdbServerError : Exception
    {
        public AdbServerError(string msg) : base(msg) { }
    }

    /// <summary>
    /// ADB 服务：优先通过 127.0.0.1:5037 的 ADB Server 协议通信，失败时回退到 adb.exe 子进程。
    /// 对应 Python 的 app/services/adb_service.py。
    /// </summary>
    public static class AdbService
    {
        public static string AdbBin => File.Exists(ExternalTools.Resolve("adb").Path)
            ? ExternalTools.Resolve("adb").Path
            : "adb";
        public static string FastbootBin => File.Exists(ExternalTools.Resolve("fastboot").Path)
            ? ExternalTools.Resolve("fastboot").Path
            : "fastboot";

        // ==================== ADB Server Socket 客户端 ====================
        private sealed class AdbServerClient
        {
            private readonly string _host;
            private readonly int _port;
            private readonly double _timeout;

            public AdbServerClient(string host = "127.0.0.1", int port = 5037, double timeout = 8.0)
            {
                _host = host;
                _port = port;
                _timeout = timeout;
            }

            private TcpClient Connect()
            {
                var c = new TcpClient();
                try
                {
                    using var deadline = new System.Threading.CancellationTokenSource(TimeSpan.FromSeconds(_timeout));
                    c.ConnectAsync(_host, _port, deadline.Token).AsTask().GetAwaiter().GetResult();
                    c.ReceiveTimeout = (int)(_timeout * 1000);
                    c.SendTimeout = (int)(_timeout * 1000);
                    return c;
                }
                catch
                {
                    c.Dispose();
                    throw;
                }
            }

            private static byte[] ConcatBytes(byte[] a, byte[] b)
            {
                var r = new byte[a.Length + b.Length];
                Buffer.BlockCopy(a, 0, r, 0, a.Length);
                Buffer.BlockCopy(b, 0, r, a.Length, b.Length);
                return r;
            }

            private static byte[] EncodeService(string service)
            {
                var b = Encoding.UTF8.GetBytes(service ?? "");
                var head = Encoding.ASCII.GetBytes(b.Length.ToString("x4"));
                return head.Concat(b).ToArray();
            }

            private static byte[] ReadExact(NetworkStream s, int n)
            {
                var buf = new byte[n];
                int off = 0;
                while (off < n)
                {
                    int r = s.Read(buf, off, n - off);
                    if (r <= 0) throw new AdbServerError("adb server closed connection");
                    off += r;
                }
                return buf;
            }

            private static string ReadString(NetworkStream s)
            {
                var lnHex = Encoding.ASCII.GetString(ReadExact(s, 4));
                if (!int.TryParse(lnHex, System.Globalization.NumberStyles.HexNumber, null, out var ln))
                    throw new AdbServerError("invalid length prefix: " + lnHex);
                if (ln <= 0) return "";
                return Encoding.UTF8.GetString(ReadExact(s, ln)).Replace("\ufffd", "");
            }

            private static void ReadStatus(NetworkStream s)
            {
                var st = Encoding.ASCII.GetString(ReadExact(s, 4));
                if (st == "OKAY") return;
                if (st == "FAIL")
                {
                    var msg = ReadString(s);
                    throw new AdbServerError(string.IsNullOrEmpty(msg) ? "adb server FAIL" : msg);
                }
                throw new AdbServerError("unexpected adb status: " + st);
            }

            public async Task<string> RequestAsync(string service, double timeout = -1, bool expectString = true)
            {
                using var c = Connect();
                using var s = c.GetStream();
                var data = EncodeService(service);
                await s.WriteAsync(data, 0, data.Length).ConfigureAwait(false);
                ReadStatus(s);
                if (!expectString) return "";
                return ReadString(s);
            }

            public async Task<string> ShellAsync(string serial, string cmd, double timeout = 20)
            {
                using var c = Connect();
                using var s = c.GetStream();
                var svc1 = EncodeService($"host:transport:{serial}");
                await s.WriteAsync(svc1, 0, svc1.Length).ConfigureAwait(false);
                ReadStatus(s);
                var svc2 = EncodeService($"shell:{cmd}");
                await s.WriteAsync(svc2, 0, svc2.Length).ConfigureAwait(false);
                ReadStatus(s);
                using var ms = new MemoryStream();
                var buf = new byte[65536];
                try
                {
                    while (true)
                    {
                        int r = s.Read(buf, 0, buf.Length);
                        if (r <= 0) break;
                        ms.Write(buf, 0, r);
                    }
                }
                catch (IOException) { /* timeout: treat as end */ }
                catch (ObjectDisposedException) { }
                return Encoding.UTF8.GetString(ms.ToArray()).Trim();
            }

            private TcpClient SyncOpen(string serial, double timeout = 30)
            {
                var c = Connect();
                var s = c.GetStream();
                var svc1 = EncodeService($"host:transport:{serial}");
                s.Write(svc1, 0, svc1.Length);
                ReadStatus(s);
                var svc2 = EncodeService("sync:");
                s.Write(svc2, 0, svc2.Length);
                ReadStatus(s);
                return c;
            }

            private static void SyncSendCmd(NetworkStream s, byte[] cmd4, byte[] payload = null!)
            {
                payload ??= Array.Empty<byte>();
                var hdr = cmd4.Concat(BitConverter.GetBytes((uint)payload.Length)).ToArray();
                s.Write(hdr, 0, hdr.Length);
                if (payload.Length > 0) s.Write(payload, 0, payload.Length);
            }

            private static (byte[] Cmd, int Len) SyncRecvHeader(NetworkStream s)
            {
                var hdr = ReadExact(s, 8);
                return (hdr.Take(4).ToArray(), (int)BitConverter.ToUInt32(hdr, 4));
            }

            public List<FsEntry> SyncList(string serial, string remoteDir)
            {
                using var c = SyncOpen(serial);
                using var s = c.GetStream();
                SyncSendCmd(s, Encoding.ASCII.GetBytes("LIST"), Encoding.UTF8.GetBytes(remoteDir ?? ""));
                var items = new List<FsEntry>();
                while (true)
                {
                    var (cmd4, ln) = SyncRecvHeader(s);
                    var cmd = Encoding.ASCII.GetString(cmd4);
                    if (cmd == "DONE") break;
                    if (cmd == "DENT")
                    {
                        var dent = ReadExact(s, 16 + ln);
                        uint mode = BitConverter.ToUInt32(dent, 0);
                        uint size = BitConverter.ToUInt32(dent, 4);
                        uint mtime = BitConverter.ToUInt32(dent, 8);
                        var name = Encoding.UTF8.GetString(dent, 16, dent.Length - 16);
                        items.Add(new FsEntry { Name = name, Mode = (int)mode, Size = (int)size, Mtime = (int)mtime });
                        continue;
                    }
                    if (cmd == "FAIL")
                    {
                        var msg = Encoding.UTF8.GetString(ReadExact(s, ln));
                        throw new AdbServerError(msg);
                    }
                    if (ln > 0) _ = ReadExact(s, ln);
                }
                return items;
            }

            public void SyncPullFile(string serial, string remote, string local)
            {
                using var c = SyncOpen(serial);
                using var s = c.GetStream();
                SyncSendCmd(s, Encoding.ASCII.GetBytes("RECV"), Encoding.UTF8.GetBytes(remote ?? ""));
                using var f = new FileStream(local, FileMode.Create, FileAccess.Write);
                while (true)
                {
                    var (cmd4, ln) = SyncRecvHeader(s);
                    var cmd = Encoding.ASCII.GetString(cmd4);
                    if (cmd == "DATA")
                    {
                        if (ln > 0)
                        {
                            var d = ReadExact(s, ln);
                            f.Write(d, 0, d.Length);
                        }
                        continue;
                    }
                    if (cmd == "DONE") break;
                    if (cmd == "FAIL")
                    {
                        var msg = Encoding.UTF8.GetString(ReadExact(s, ln));
                        throw new AdbServerError(msg);
                    }
                    if (ln > 0) _ = ReadExact(s, ln);
                }
            }

            public void SyncPushFile(string serial, string local, string remote, int mode = 0x1A4 /*0644*/)
            {
                using var c = SyncOpen(serial);
                using var s = c.GetStream();
                var r = ConcatBytes(Encoding.UTF8.GetBytes(remote ?? ""), Encoding.UTF8.GetBytes("," + mode));
                SyncSendCmd(s, Encoding.ASCII.GetBytes("SEND"), r);
                using var f = new FileStream(local, FileMode.Open, FileAccess.Read);
                var buf = new byte[65536];
                int n;
                while ((n = f.Read(buf, 0, buf.Length)) > 0)
                {
                    var chunk = new byte[n];
                    Array.Copy(buf, chunk, n);
                    SyncSendCmd(s, Encoding.ASCII.GetBytes("DATA"), chunk);
                }
                SyncSendCmd(s, Encoding.ASCII.GetBytes("DONE"), BitConverter.GetBytes((uint)DateTimeOffset.UtcNow.ToUnixTimeSeconds()));
                var (cmd4, ln) = SyncRecvHeader(s);
                var cmd = Encoding.ASCII.GetString(cmd4);
                if (cmd == "OKAY") return;
                if (cmd == "FAIL")
                {
                    var msg = Encoding.UTF8.GetString(ReadExact(s, ln));
                    throw new AdbServerError(msg);
                }
                throw new AdbServerError("unexpected sync response");
            }
        }

        public class FsEntry
        {
            public string Name { get; set; } = "";
            public int Mode { get; set; }
            public int Size { get; set; }
            public int Mtime { get; set; }
            public bool IsDir => (Mode & 0x4000) != 0;
        }

        // ==================== 基础运行 ====================
        private static AdbServerClient _server(double timeout = 8.0) => new(timeout: timeout);

        public static bool EnsureAdbServerRunning()
        {
            try
            {
                _server(1.0).RequestAsync("host:devices", 1.0).GetAwaiter().GetResult();
                return true;
            }
            catch { }
            RunAdb(new[] { "start-server" }, 6);
            try
            {
                _server(2.0).RequestAsync("host:devices", 2.0).GetAwaiter().GetResult();
                return true;
            }
            catch { return false; }
        }

        public static (int Code, string Out) RunAdb(IEnumerable<string> args, int timeout = 10)
        {
            try
            {
                var r = ProcessRunner.Run(AdbBin, args, timeoutMs: timeout * 1000);
                return (r.ExitCode, r.Output.Trim());
            }
            catch (Exception e)
            {
                return (1, e.Message);
            }
        }

        private static string _run(IEnumerable<string> cmd, int timeout = 8)
        {
            try
            {
                var r = ProcessRunner.Run(cmd.First(), cmd.Skip(1), timeoutMs: timeout * 1000);
                return r.Output;
            }
            catch { return ""; }
        }

        private static string NormalizeHostPort(string host, object port)
        {
            var h = (host ?? "").Trim();
            var p = (port?.ToString() ?? "").Trim();
            if (string.IsNullOrEmpty(h)) return "";
            if (h.Contains(":")) return h;
            if (string.IsNullOrEmpty(p)) return h;
            return $"{h}:{p}";
        }

        // ==================== 无线连接 ====================
        public static (int, string) AdbPair(string host, object port, string pairingCode, int timeout = 15)
        {
            if (!WirelessAdb.TryEndpoint(NormalizeHostPort(host, port), true, out var hp, out var error)) return (2, error);
            var code = (pairingCode ?? "").Trim();
            if (!WirelessAdb.IsPairingCode(code)) return (2, "请输入设备配对窗口显示的 6 位数字配对码。");
            // 使用官方 CLI 的配对协议，避免手写 host:pair 的字段顺序和版本差异。
            return RunWirelessAdb(new[] { "pair", hp, code }, timeout, pairing: true);
        }

        public static (int, string) AdbConnect(string host, object port, int timeout = 10)
        {
            if (!WirelessAdb.TryEndpoint(NormalizeHostPort(host, port), false, out var hp, out var error)) return (2, error);
            return RunWirelessAdb(new[] { "connect", hp }, timeout, pairing: false);
        }

        private static (int, string) RunWirelessAdb(string[] args, int timeout, bool pairing)
        {
            try
            {
                // CLI 自行启动同一个 ADB server；只执行一次请求，避免 socket 超时后再等待一轮。
                var result = ProcessRunner.Run(AdbBin, args, timeoutMs: Math.Max(1, timeout) * 1000);
                if (result.TimedOut) return (124, (pairing
                    ? LocalizationService.Instance.Format("Logic/WirelessPairTimeout", timeout, result.Output)
                    : LocalizationService.Instance.Format("Logic/WirelessConnectTimeout", timeout, result.Output)).Trim());
                return WirelessAdb.Result(result.ExitCode, result.Output, pairing);
            }
            catch (Exception ex) { return (1, ex.Message); }
        }

        public static (int, string) AdbDisconnect(string host = null!, object port = null!, int timeout = 10)
        {
            try
            {
                EnsureAdbServerRunning();
                var svc = "host:disconnect:";
                if (!string.IsNullOrEmpty(host)) svc = $"host:disconnect:{NormalizeHostPort(host, port ?? "")}";
                var out_ = _server(timeout).RequestAsync(svc, timeout).GetAwaiter().GetResult();
                return (0, (out_ ?? "").Trim());
            }
            catch
            {
                if (!string.IsNullOrEmpty(host)) return RunAdb(new[] { "disconnect", NormalizeHostPort(host, port ?? "") }, timeout);
                return RunAdb(new[] { "disconnect" }, timeout);
            }
        }

        public static (int, string) AdbMdnsServices(int timeout = 5)
        {
            try
            {
                EnsureAdbServerRunning();
                var out_ = _server(timeout).RequestAsync("host:mdns:services", timeout).GetAwaiter().GetResult();
                return (0, (out_ ?? "").Trim());
            }
            catch
            {
                return RunAdb(new[] { "mdns", "services" }, timeout);
            }
        }

        public static (int, string) AdbKillServer() => RunAdb(new[] { "kill-server" }, 10);
        public static (int, string) AdbStartServer() => RunAdb(new[] { "start-server" }, 10);

        public static bool CheckAdbAvailable()
        {
            try { if (File.Exists(AdbBin)) return true; } catch { }
            try
            {
                var r = ProcessRunner.Run("where", new[] { "adb" }, timeoutMs: 3000);
                if (r.ExitCode == 0 && !string.IsNullOrWhiteSpace(r.Output)) return true;
            }
            catch { }
            return false;
        }

        public static List<(string Serial, string State)> ListDeviceStates()
        {
            try
            {
                if (EnsureAdbServerRunning())
                {
                    var output = _server(5.0).RequestAsync("host:devices", 5.0).GetAwaiter().GetResult();
                    return AdbDeviceParser.Parse(output);
                }
            }
            catch { }
            // Socket 不可用时仍尝试命令行，不能直接返回空列表。
            var fallback = RunAdb(new[] { "devices", "-l" }, 8);
            if (fallback.Code != 0)
                throw new AdbServerError("ADB 设备检测失败：" + fallback.Out);
            return AdbDeviceParser.Parse(fallback.Out);
        }

        public static List<string> ListDevices()
        {
            try { return ListDeviceStates().Where(d => d.State == "device").Select(d => d.Serial).ToList(); }
            catch { return new List<string>(); }
        }

        // ==================== shell / getprop ====================
        private static string GetProp(string serial, string key)
        {
            try
            {
                if (string.IsNullOrEmpty(serial)) return "";
                if (!EnsureAdbServerRunning()) throw new AdbServerError("ADB socket unavailable; using command-line fallback");
                return _server(3.0).ShellAsync(serial, $"getprop {key}", 3.0).GetAwaiter().GetResult();
            }
            catch
            {
                return _run(new[] { AdbBin, "-s", serial, "shell", "getprop", key }, 3);
            }
        }

        private static string Shell(string serial, string cmd)
        {
            try
            {
                if (string.IsNullOrEmpty(serial)) return "";
                if (!EnsureAdbServerRunning()) throw new AdbServerError("ADB socket unavailable; using command-line fallback");
                return _server(8.0).ShellAsync(serial, cmd, 8.0).GetAwaiter().GetResult();
            }
            catch
            {
                return _run(new[] { AdbBin, "-s", serial, "shell", cmd }, 8);
            }
        }

        private static string AdbGetState(string serial)
        {
            try
            {
                if (string.IsNullOrEmpty(serial)) return "";
                if (!EnsureAdbServerRunning()) throw new AdbServerError("ADB socket unavailable; using command-line fallback");
                return _server(2.0).RequestAsync($"host-serial:{serial}:get-state", 2.0).GetAwaiter().GetResult()?.Trim() ?? "";
            }
            catch
            {
                return _run(new[] { AdbBin, "-s", serial, "get-state" }, 2);
            }
        }

        private static string Fastboot(IEnumerable<string> cmds, int timeout = 5)
            => _run(new[] { FastbootBin }.Concat(cmds), timeout);

        private static int ReadSysValue(string serial, IEnumerable<string> paths)
        {
            foreach (var path in paths)
            {
                var cmd = $"if [ -f {path} ]; then cat {path}; fi";
                var out_ = Shell(serial, cmd);
                var val = (out_ ?? "").Trim();
                if (string.IsNullOrEmpty(val) || val.Contains("No such file") || val.Contains("Permission denied")) continue;
                if (double.TryParse(val, out var d)) return (int)d;
            }
            return 0;
        }

        /// <summary>已知芯片代号 → 营销名；未命中回退显示代号本身。一对多型号用 "/" 分隔；键不区分大小写。</summary>
        private static readonly Dictionary<string, string> SocMarketingNames = new(StringComparer.OrdinalIgnoreCase)
        {
            // ---------- 高通 骁龙 8 系 ----------
            ["SDM845"] = "骁龙 845",
            ["SM8150"] = "骁龙 855",
            ["SM8250"] = "骁龙 865/865 Plus/870",
            ["SM8350"] = "骁龙 888/888+",
            ["SM8450"] = "骁龙 8 Gen 1",
            ["SM8475"] = "骁龙 8+ Gen 1",
            ["SM8550"] = "骁龙 8 Gen 2",
            ["SM8635"] = "骁龙 8s Gen 3",
            ["SM8650"] = "骁龙 8 Gen 3",
            ["SM8750"] = "骁龙 8 Elite",
            ["SM8845"] = "骁龙 8 Gen 5",
            ["SM8850"] = "骁龙 8 Elite Gen 5",
            ["SM8850-1-AB"] = "骁龙 8 Elite Gen 5 V",
            ["SM8850-1-AD"] = "骁龙 8 Elite Gen 5 Galaxy",
            ["SM8950"] = "骁龙 8 Elite Gen 6",
            ["SM8975"] = "骁龙 8 Elite Extreme Gen 6",
            // ---------- 高通 骁龙 7 系 ----------
            ["SDM710"] = "骁龙 710",
            ["SDM712"] = "骁龙 712",
            ["SM6250"] = "骁龙 720G",
            ["SM7125"] = "骁龙 720G",
            ["SM7150"] = "骁龙 730/730G/732G",
            ["SM7225"] = "骁龙 750G",
            ["SM7250"] = "骁龙 765/765G/768G",
            ["SM7325"] = "骁龙 778G/778G+/782G",
            ["SM7350"] = "骁龙 780G",
            ["SM7435"] = "骁龙 7s Gen 2",
            ["SM7450"] = "骁龙 7 Gen 1",
            ["SM7475"] = "骁龙 7+ Gen 2",
            ["SM7550"] = "骁龙 7 Gen 3",
            ["SM7635"] = "骁龙 7s Gen 3/7s Gen 4",
            ["SM7675"] = "骁龙 7+ Gen 3",
            ["SM7750"] = "骁龙 7 Gen 4",
            // ---------- 高通 骁龙 6 系 ----------
            ["SDM630"] = "骁龙 630",
            ["SDM632"] = "骁龙 632",
            ["SDM636"] = "骁龙 636",
            ["SDM660"] = "骁龙 660",
            ["SDM670"] = "骁龙 670",
            ["SDM678"] = "骁龙 678",
            ["SM6115"] = "骁龙 662/6s 4G Gen 1",
            ["SM6125"] = "骁龙 665",
            ["SM6150"] = "骁龙 675",
            ["SM6225"] = "骁龙 680/685",
            ["SM6350"] = "骁龙 690",
            ["SM6375"] = "骁龙 695/6s Gen 3",
            ["SM6435"] = "骁龙 6s Gen 4",
            ["SM6450"] = "骁龙 6 Gen 1",
            ["SM6475"] = "骁龙 6 Gen 3",
            ["SM6850"] = "骁龙 6 Gen 5",
            ["MSM8939"] = "骁龙 615/616",
            ["MSM8952"] = "骁龙 617",
            ["MSM8976"] = "骁龙 652/653",
            // ---------- 高通 骁龙 4 系 ----------
            ["MSM8917"] = "骁龙 425",
            ["MSM8920"] = "骁龙 427",
            ["MSM8937"] = "骁龙 430",
            ["MSM8940"] = "骁龙 435",
            ["SDM429"] = "骁龙 429",
            ["SDM439"] = "骁龙 439",
            ["SDM450"] = "骁龙 450",
            ["SM4250"] = "骁龙 460",
            ["SM4350"] = "骁龙 480/480+",
            ["SM4375"] = "骁龙 4 Gen 1",
            ["SM4450"] = "骁龙 4 Gen 2/4+ Gen 2",
            ["SM4635"] = "骁龙 4s Gen 2",
            // ---------- 高通 骁龙 老旗舰（MSM，刷机常见） ----------
            ["MSM8998"] = "骁龙 835",
            ["MSM8996"] = "骁龙 820/821",
            ["MSM8953"] = "骁龙 625/626",
            // ---------- 联发科 天玑 9000 系 ----------
            ["MT6983"] = "天玑 9000/9000+",
            ["MT6985"] = "天玑 9200/9200+",
            ["MT6989"] = "天玑 9300/9300+",
            ["MT6991"] = "天玑 9400/9400+",
            ["MT6993"] = "天玑 9500",
            // ---------- 联发科 天玑 8000 / 1000 系 ----------
            ["MT6899"] = "天玑 8400/8400 Ultra",
            ["MT6897"] = "天玑 8300",
            ["MT6896"] = "天玑 8200",
            ["MT6895"] = "天玑 8000/8100",
            ["MT6893"] = "天玑 1200/1300",
            ["MT6891"] = "天玑 1100",
            ["MT6889"] = "天玑 1000/1000+",
            ["MT6885"] = "天玑 1000L",
            ["MT6883"] = "天玑 1000C",
            // ---------- 联发科 天玑 7000 / 入门 5G ----------
            ["MT6881"] = "天玑 7500",
            ["MT6886"] = "天玑 7350",
            ["MT6878"] = "天玑 7300",
            ["MT6877"] = "天玑 900/920",
            ["MT6875"] = "天玑 820",
            ["MT6873"] = "天玑 800",
            ["MT6853"] = "天玑 720/800U",
            ["MT6853V/TNZA"] = "天玑 800U",
            ["MT6853V/ZA"] = "天玑 720",
            ["MT6833"] = "天玑 700/810",
            // ---------- 联发科 Helio ----------
            ["MT6789"] = "Helio G99",
            ["MT6785"] = "Helio G90/G90T/G95",
            ["MT6769"] = "Helio G70/G80/G85",
            ["MT6765"] = "Helio G35/P35",
            ["MT6762"] = "Helio G25/P22",
            ["MT6768"] = "Helio P65",
            ["MT6779"] = "Helio P95",
            // ---------- 紫光展锐 Unisoc ----------
            ["SC9863A"] = "紫光展锐 SC9863A",
            ["SC9832E"] = "紫光展锐 SC9832E",
            ["T310"] = "紫光展锐 T310",
            ["T610"] = "紫光展锐 T610",
            ["T618"] = "紫光展锐 T618",
            ["T7200"] = "紫光展锐 T7200",
            ["T7300"] = "紫光展锐 T7300",
            ["T8100"] = "紫光展锐 T8100",
            ["T8200"] = "紫光展锐 T8200",
            ["T8300"] = "紫光展锐 T8300",
            ["T9100"] = "紫光展锐 T9100",
            ["UMS512"] = "紫光展锐 UMS512",
            ["S512"] = "紫光展锐 S512",
            // ---------- 海思麒麟 Kirin ----------
            ["Kirin9000"] = "麒麟 9000",
            ["Kirin9000S"] = "麒麟 9000S",
            ["Kirin9010"] = "麒麟 9010",
            ["Kirin9010S"] = "麒麟 9010S",
            ["Kirin9020"] = "麒麟 9020",
            ["Kirin9030"] = "麒麟 9030/9030 Pro",
            ["Kirin9050"] = "麒麟 9050/9050 Pro",
            ["Kirin990"] = "麒麟 990",
            ["Kirin980"] = "麒麟 980",
            ["Kirin970"] = "麒麟 970",
            ["Kirin820"] = "麒麟 820",
            ["Kirin810"] = "麒麟 810",
            ["Kirin710"] = "麒麟 710",
            // ---------- 瑞芯微 Rockchip ----------
            ["RK3588"] = "瑞芯微 RK3588",
            ["RK3588J"] = "瑞芯微 RK3588J",
            ["RK3576"] = "瑞芯微 RK3576",
            ["RK3568"] = "瑞芯微 RK3568/RK3568J",
            ["RK3566"] = "瑞芯微 RK3566",
            ["RK3562"] = "瑞芯微 RK3562",
            ["RK3506"] = "瑞芯微 RK3506",
            ["RK3399"] = "瑞芯微 RK3399",
            ["RK3326"] = "瑞芯微 RK3326",
            // ---------- 小米玄戒 XRING ----------
            ["XRINGO1"] = "玄戒 O1",
            ["XRINGO3"] = "玄戒 O3",
            ["XRINGT1"] = "玄戒 T1",
        };

        private static string ResolveCpuModel(string cpuinfo, string socModel, string family, string machine, string board)
        {
            // 依次用各候选代号查字典；命中则返回 营销名（原始码）。
            foreach (var candidate in new[] { socModel, cpuinfo, board, machine, family })
            {
                if (string.IsNullOrWhiteSpace(candidate) || IsGenericPlatform(candidate)) continue;
                if (TryMapSoc(candidate.Trim(), out var mapped, out var raw))
                    return $"{mapped}（{raw}）";
            }

            // 未命中字典：按平台信息兜底。
            if (!IsGenericPlatform(cpuinfo)) return cpuinfo;
            if (!IsGenericPlatform(machine)) return machine;
            if (!IsGenericPlatform(family))
                return IsGenericPlatform(board) ? family : $"{family} {board}";
            if (!IsGenericPlatform(board)) return board;
            return cpuinfo ?? "";
        }

        // 逐级尝试把芯片代号映射为营销名；raw 为保留展示的原始代号。
        private static bool TryMapSoc(string code, out string name, out string raw)
        {
            raw = code;
            var firstSegment = code.Split('-', '/', '_')[0];
            string[] variants =
            {
                code,
                NormalizeSocCode(code),
                firstSegment,
                NormalizeSocCode(firstSegment),
                ExtractSocStem(code),
            };
            foreach (var v in variants.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                if (string.IsNullOrEmpty(v)) continue;
                if (SocMarketingNames.TryGetValue(v, out var mapped)) { name = mapped; return true; }
            }
            name = "";
            return false;
        }

        // 取“字母前缀 + 连续数字”的粗主干，剥离封装/频率变体尾字母（如 MT6853V/TNZA → MT6853）。
        private static string ExtractSocStem(string code)
        {
            var m = Regex.Match(code, @"^[A-Za-z]+\d+");
            return m.Success ? m.Value : "";
        }

        private static bool IsGenericPlatform(string? s)
        {
            if (string.IsNullOrWhiteSpace(s)) return true;
            var t = s.Trim().ToLowerInvariant();
            if (t is "qcom" or "msm" or "generic" or "unknown" or "0") return true;
            // 纯数字（如 /proc/cpuinfo 里的处理器编号）不是平台型号。
            return t.All(char.IsDigit);
        }

        // 归一化芯片代号：去除所有空白，兼容 "Kirin 9000S" 这类带空格的返回值。
        private static string NormalizeSocCode(string code) =>
            new string(code.Where(static c => !char.IsWhiteSpace(c)).ToArray());

        private static int MeminfoValue(string meminfo, string key)
        {
            var m = Regex.Match(meminfo ?? "", $@"^{Regex.Escape(key)}\s*:\s*(\d+)", RegexOptions.Multiline);
            if (!m.Success) return 0;
            return int.TryParse(m.Groups[1].Value, out var v) ? v : 0;
        }

        private static string FormatMemSize(int kb)
        {
            if (kb <= 0) return "0 MB";
            double gb = kb / (1024.0 * 1024.0);
            if (gb >= 1) return $"{gb:0.0} GB";
            return $"{kb / 1024.0:0} MB";
        }

        private static (int Rated, int Full) HarmonizeCapacityPair(int rated, int full)
        {
            if (rated <= 0 || full <= 0) return (rated, full);
            int smaller, larger;
            bool swap;
            if (rated <= full) { smaller = rated; larger = full; swap = false; }
            else { smaller = full; larger = rated; swap = true; }
            while (larger / Math.Max(1, smaller) >= 8 && smaller < 1_000_000_000) smaller *= 10;
            if (swap) return (larger, smaller);
            return (smaller, larger);
        }

        private static string FormatCapacity(int uah)
        {
            if (uah <= 0) return "";
            double mah = uah / 1000.0;
            if (mah >= 1000) return $"{mah:N0} mAh";
            if (mah >= 100) return $"{mah:0} mAh";
            return $"{mah:0.0} mAh";
        }

        // ==================== 连接模式检测 ====================
        public static (string Mode, string Serial) DetectConnectionMode(bool throwOnError = false)
        {
            Exception? adbError = null;
            try
            {
                var detected = AdbDeviceParser.SelectMode(ListDeviceStates());
                if (detected.Mode != "none") return detected;
            }
            catch (Exception ex) { adbError = ex; }

            var fbOut = _run(new[] { FastbootBin, "devices" }, 2);
            if (!string.IsNullOrEmpty(fbOut))
            {
                foreach (var line in fbOut.Split('\n').Select(x => x.Trim()).Where(x => x.Length > 0))
                {
                    var parts = line.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length < 2 || parts[1] != "fastboot") continue;
                    var serial = parts[0];
                    if (serial.ToLowerInvariant().StartsWith("(bootloader)")) continue;
                    var isUserspace = _run(new[] { FastbootBin, "-s", serial, "getvar", "is-userspace" }, 2);
                    if ((isUserspace ?? "").ToLowerInvariant().Contains("yes")) return ("fastbootd", serial);
                    return ("bootloader", serial);
                }
            }

            try
            {
                var (portMode, portId) = DetectSpecialPortMode();
                if (portMode != "none") return (portMode, portId);
            }
            catch { }

            if (adbError != null && throwOnError) throw new AdbServerError(adbError.Message);
            return ("none", "");
        }

        private static (string Mode, string Id) DetectSpecialPortMode()
        {
            var ps = @"
$ErrorActionPreference = 'SilentlyContinue'
$items = @()
$items += Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Name, PNPDeviceID
$items += Get-CimInstance Win32_PnPEntity | Where-Object {
    $_.Name -match '\(COM\d+\)' -or $_.Caption -match '\(COM\d+\)'
} | Select-Object @{Name='DeviceID';Expression={ if ($_.Name -match '\((COM\d+)\)') { $matches[1] } elseif ($_.Caption -match '\((COM\d+)\)') { $matches[1] } else { '' } }}, @{Name='Name';Expression={ if ($_.Name) { $_.Name } elseif ($_.Caption) { $_.Caption } else { '' } }}, PNPDeviceID
$items | ForEach-Object {
    $dev = [string]$_.DeviceID
    $name = [string]$_.Name
    $pnp = [string]$_.PNPDeviceID
    if ($dev) { Write-Output ($dev + '|' + $name + '|' + $pnp) }
}
";
            var out_ = _run(new[] { "powershell", "-NoProfile", "-Command", ps }, 4);
            if (string.IsNullOrEmpty(out_)) return ("none", "");
            var seen = new HashSet<string>();
            foreach (var raw in out_.Split('\n'))
            {
                var line = (raw ?? "").Trim();
                if (string.IsNullOrEmpty(line)) continue;
                var parts = line.Split('|');
                var com = parts.Length > 0 ? parts[0].Trim() : "";
                var name = parts.Length > 1 ? parts[1].Trim() : "";
                var pnp = parts.Length > 2 ? parts[2].Trim() : "";
                if (!Regex.IsMatch(com, @"^COM\d+$", RegexOptions.IgnoreCase)) continue;
                var key = com.ToUpperInvariant() + name;
                if (!seen.Add(key)) continue;
                var text = (name + " " + pnp).ToLowerInvariant().Replace("_", "-");
                if (text.Contains("9008") || text.Contains("qdloader") || text.Contains("qualcomm hs-usb")
                    || text.Contains("qualcomm usb") || text.Contains("emergency download")
                    || (text.Contains("qualcomm") && text.Contains("edl")))
                    return ("edl", com);
                if ((text.Contains("mediatek") || text.Contains("mtk")) &&
                    (text.Contains("preloader") || text.Contains("brom") || text.Contains("vcom")
                     || text.Contains("usb port") || text.Contains("download port")))
                    return ("brom", com);
            }
            return ("none", "");
        }

        // ==================== 设备信息 ====================
        public static DeviceInfo GetDeviceInfo(string serial)
        {
            var info = new DeviceInfo { Serial = serial };

            info.Brand = GetProp(serial, "ro.product.brand");
            info.Model = GetProp(serial, "ro.product.model");
            info.Device = GetProp(serial, "ro.product.device");
            info.Product = GetProp(serial, "ro.product.name");
            info.AndroidVersion = GetProp(serial, "ro.build.version.release");
            info.Sdk = GetProp(serial, "ro.build.version.sdk");
            info.Vndk = GetProp(serial, "ro.build.version.vndk");
            info.BuildDisplay = GetProp(serial, "ro.build.display.id");
            info.Fingerprint = GetProp(serial, "ro.build.fingerprint");

            var batteryDump = Shell(serial, "dumpsys battery");
            foreach (var line in batteryDump.Split('\n'))
            {
                var t = line.Trim();
                if (t.ToLowerInvariant().StartsWith("level:"))
                {
                    info.Battery = t.Split(':').LastOrDefault()?.Trim() ?? "";
                    break;
                }
            }
            info.Bootloader = GetProp(serial, "ro.bootloader");
            info.Baseband = GetProp(serial, "gsm.version.baseband");

            // CPU：ARM 的 /proc/cpuinfo 通常只有 implementer/part，不含营销名，
            // 优先 ro.soc.model 芯片代号并映射营销名；ro.hardware(qcom) 这类平台名只作最后兜底。
            var cpuModel = "";
            var cpuinfo = Shell(serial, "cat /proc/cpuinfo");
            foreach (var line in cpuinfo.Split('\n'))
            {
                var t = line.Trim();
                if (t.StartsWith("Hardware")) { cpuModel = t.Split(':').LastOrDefault()?.Trim() ?? ""; break; }
                else if (t.StartsWith("Processor") && string.IsNullOrEmpty(cpuModel)) cpuModel = t.Split(':').LastOrDefault()?.Trim() ?? "";
            }

            var socModel = GetProp(serial, "ro.soc.model").Trim();
            var socFamily = Shell(serial, "cat /sys/devices/soc0/family").Trim();
            var socMachine = Shell(serial, "cat /sys/devices/soc0/machine").Trim();
            var boardPlatform = GetProp(serial, "ro.board.platform").Trim();
            cpuModel = ResolveCpuModel(cpuModel, socModel, socFamily, socMachine, boardPlatform);

            if (string.IsNullOrEmpty(cpuModel))
            {
                var dmesg = Shell(serial, "dmesg | grep -i 'cpu\\|processor\\|soc' | head -5");
                foreach (var line in dmesg.Split('\n'))
                {
                    if (line.ToLowerInvariant().Contains("mt") || line.ToLowerInvariant().Contains("snapdragon")
                        || line.ToLowerInvariant().Contains("qualcomm") || line.ToLowerInvariant().Contains("mediatek")
                        || line.ToLowerInvariant().Contains("dimensity"))
                    {
                        var m = Regex.Match(line, @"(MT\d+\w*|SDM\d+\w*|SM\d+\w*|Snapdragon\s+\w+|Dimensity\s+\d+\w*)", RegexOptions.IgnoreCase);
                        if (m.Success) { cpuModel = m.Groups[1].Value; break; }
                    }
                }
            }
            if (string.IsNullOrEmpty(cpuModel))
            {
                var abi = GetProp(serial, "ro.product.cpu.abi");
                var abi2 = GetProp(serial, "ro.product.cpu.abi2");
                cpuModel = abi;
                if (!string.IsNullOrEmpty(abi2) && abi2 != abi) cpuModel = $"{abi} ({abi2})";
            }
            info.CpuInfo = string.IsNullOrEmpty(cpuModel) ? "Unknown" : cpuModel;

            // battery health
            var rated = ReadSysValue(serial, new[] {
                "/sys/class/power_supply/battery/charge_full_design",
                "/sys/class/power_supply/BAT0/charge_full_design" });
            var full = ReadSysValue(serial, new[] {
                "/sys/class/power_supply/battery/charge_full",
                "/sys/class/power_supply/BAT0/charge_full" });
            if (rated > 0 && full > 0)
            {
                var (r2, f2) = HarmonizeCapacityPair(rated, full);
                rated = r2; full = f2;
                info.BatteryHealthPercent = Math.Max(0, Math.Min(100, (int)((double)full / rated * 100))).ToString();
            }
            if (rated > 0) info.BatteryRatedCapacity = FormatCapacity(rated);
            if (full > 0) info.BatteryFullCapacity = FormatCapacity(full);

            // storage
            info.StorageData = Shell(serial, "df -h /data | tail -n 1");

            // memory
            var meminfo = Shell(serial, "cat /proc/meminfo");
            var memTotal = MeminfoValue(meminfo, "MemTotal");
            var memAvail = MeminfoValue(meminfo, "MemAvailable");
            if (memAvail == 0) memAvail = MeminfoValue(meminfo, "MemFree");
            if (memTotal > 0)
            {
                var used = Math.Max(0, memTotal - (memAvail > 0 ? memAvail : 0));
                var pct = memTotal > 0 ? (int)((double)used / memTotal * 100) : 0;
                pct = Math.Max(0, Math.Min(100, pct));
                info.MemoryPercent = pct.ToString();
                info.MemorySummary = $"已用 {FormatMemSize(used)} / 总 {FormatMemSize(memTotal)}";
            }

            // kernel
            var kern = Shell(serial, "uname -r");
            if (string.IsNullOrEmpty(kern)) kern = Shell(serial, "cat /proc/version");
            info.Kernel = kern;

            // slot
            var slotSuffix = GetProp(serial, "ro.boot.slot_suffix");
            var slot = GetProp(serial, "ro.boot.slot");
            info.CurrentSlot = !string.IsNullOrEmpty(slot) ? slot : slotSuffix.Replace("_", "");

            // bootloader unlock
            var vbState = GetProp(serial, "ro.boot.vbmeta.device_state");
            var flashLocked = GetProp(serial, "ro.boot.flash.locked");
            var verifiedBoot = GetProp(serial, "ro.boot.verifiedbootstate");
            var unlocked = "unknown";
            if (!string.IsNullOrEmpty(vbState)) unlocked = vbState.ToLowerInvariant() == "unlocked" ? "unlocked" : "locked";
            else if (!string.IsNullOrEmpty(flashLocked)) unlocked = flashLocked.Trim() == "0" ? "unlocked" : "locked";
            else if (!string.IsNullOrEmpty(verifiedBoot))
            {
                var vb = verifiedBoot.Trim().ToLowerInvariant();
                if (vb == "orange") unlocked = "unlocked";
                else if (vb == "green") unlocked = "locked";
            }
            info.BootloaderUnlock = unlocked;

            info.Codename = GetProp(serial, "ro.product.device");
            var deviceSerial = Shell(serial, "getprop ro.serialno");
            if (string.IsNullOrEmpty(deviceSerial))
                deviceSerial = Shell(serial, "cat /proc/cmdline | tr ' ' '\\n' | grep androidboot.serialno | cut -d'=' -f2");
            info.DeviceSerial = (deviceSerial ?? "").Trim();

            var uptime = Shell(serial, "cat /proc/uptime");
            if (!string.IsNullOrEmpty(uptime))
            {
                var parts = uptime.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length > 0 && double.TryParse(parts[0], out var sec))
                {
                    int days = (int)(sec / 86400);
                    int hours = (int)((sec % 86400) / 3600);
                    int mins = (int)((sec % 3600) / 60);
                    if (days > 0) info.Uptime = $"{days}天 {hours}小时 {mins}分钟";
                    else if (hours > 0) info.Uptime = $"{hours}小时 {mins}分钟";
                    else info.Uptime = $"{mins}分钟";
                }
            }

            var wm = Shell(serial, "wm size");
            if (!string.IsNullOrEmpty(wm) && wm.Contains("Physical size:"))
                info.Resolution = wm.Split(new[] { "Physical size:" }, StringSplitOptions.None)[1].Trim();
            var density = GetProp(serial, "ro.sf.lcd_density");
            if (string.IsNullOrEmpty(density))
            {
                var wmDensity = Shell(serial, "wm density");
                if (!string.IsNullOrEmpty(wmDensity) && wmDensity.Contains("Physical density:"))
                    density = wmDensity.Split(new[] { "Physical density:" }, StringSplitOptions.None)[1].Trim();
            }
            info.DisplayDensity = density;

            var emmc = ReadSysValue(serial, new[] { "/sys/block/mmcblk0/device/type", "/sys/block/mmcblk1/device/type" });
            var ufs = ReadSysValue(serial, new[] { "/sys/block/sda/device/type", "/sys/block/sdb/device/type" });
            string storageType = "";
            if (emmc > 0) storageType = "eMMC";
            else if (ufs > 0) storageType = "UFS";
            else
            {
                if (ReadSysValue(serial, new[] { "/sys/block/sda" }) > 0) storageType = "UFS";
                else if (ReadSysValue(serial, new[] { "/sys/block/mmcblk0" }) > 0) storageType = "eMMC";
            }
            info.StorageType = storageType;

            // root status
            var rootStatus = "未检测";
            var suCheck = Shell(serial, "which su");
            if (!string.IsNullOrEmpty(suCheck?.Trim())) rootStatus = "已Root";
            else
            {
                var magisk = Shell(serial, "which magisk");
                if (!string.IsNullOrEmpty(magisk?.Trim())) rootStatus = "已Root (Magisk)";
                else
                {
                    var systemRw = Shell(serial, "mount | grep ' /system ' | grep rw");
                    if (!string.IsNullOrEmpty(systemRw?.Trim())) rootStatus = "已Root";
                }
            }
            info.RootStatus = rootStatus;

            return info;
        }

        // ==================== 重启 ====================
        public static (bool, string) RebootTo(string target)
        {
            target = (target ?? "").Trim().ToLowerInvariant();
            if (target is not ("bootloader" or "recovery" or "fastbootd" or "system" or "edl"))
                return (false, $"不支持的目标: {target}");

            string mode, serial;
            try { (mode, serial) = DetectConnectionMode(); }
            catch (Exception ex) { return (false, ex.Message); }
            if (mode == "none" || (string.IsNullOrEmpty(serial) && mode is not ("fastbootd" or "bootloader")))
                return (false, "未检测到已连接设备");

            if (mode is "system" or "sideload")
            {
                if (target == "system") return (true, _run(new[] { AdbBin, "reboot" }) ?? "已重启到系统");
                if (target == "bootloader") return (true, _run(new[] { AdbBin, "reboot", "bootloader" }) ?? "正在重启到 Bootloader");
                if (target == "fastbootd") return (true, _run(new[] { AdbBin, "reboot", "fastboot" }) ?? "正在重启到 FastbootD");
                if (target == "recovery") return (true, _run(new[] { AdbBin, "reboot", "recovery" }) ?? "正在重启到 Recovery");
                if (target == "edl")
                {
                    var o = _run(new[] { AdbBin, "reboot", "edl" });
                    return (true, !string.IsNullOrEmpty(o) ? o : "已尝试通过 ADB 进入 EDL（是否成功取决于设备支持）");
                }
            }

            if (mode is "fastbootd" or "bootloader")
            {
                if (target == "system") return (true, _run(new[] { FastbootBin, "reboot" }) ?? "正在重启到系统");
                if (target == "bootloader")
                {
                    if (mode != "bootloader") _run(new[] { FastbootBin, "reboot-bootloader" });
                    return (true, "已在 Bootloader 或正在进入 Bootloader");
                }
                if (target == "fastbootd") return (true, _run(new[] { FastbootBin, "reboot", "fastboot" }) ?? "正在重启到 FastbootD");
                if (target == "recovery")
                {
                    var o = _run(new[] { FastbootBin, "reboot", "recovery" });
                    if (!string.IsNullOrEmpty(o)) return (true, o);
                    var o2 = _run(new[] { FastbootBin, "oem", "reboot-recovery" });
                    return (true, o2 ?? "已尝试进入 Recovery（是否成功取决于设备支持）");
                }
                if (target == "edl")
                {
                    var o = _run(new[] { FastbootBin, "oem", "edl" });
                    if (!string.IsNullOrEmpty(o)) return (true, o);
                    var o2 = _run(new[] { FastbootBin, "edl" });
                    return (true, o2 ?? "已尝试进入 EDL（是否成功取决于设备支持）");
                }
            }

            return (false, "未能执行重启命令");
        }

        // ==================== 文件操作 ====================
        public class DirItem
        {
            public string Name { get; set; } = "";
            public string Size { get; set; } = "-";
            public string Type { get; set; } = "file";
            public bool IsDir => Type == "dir";
        }

        public static (List<DirItem>, string) ListDir(string path)
        {
            var p = string.IsNullOrEmpty(path) ? "/" : path;
            try
            {
                var serials = ListDevices();
                var serial = serials.Count > 0 ? serials[0] : "";
                if (!string.IsNullOrEmpty(serial) && EnsureAdbServerRunning())
                {
                    try
                    {
                        var out_ = _server(6.0).ShellAsync(serial, $"sh -c \"ls -1p '{p}' 2>/dev/null || toybox ls -1p '{p}' 2>/dev/null\"", 6.0).GetAwaiter().GetResult();
                        if (!string.IsNullOrEmpty(out_) && !out_.Contains("No such file") && !out_.Contains("Permission denied"))
                        {
                            var items = new List<DirItem>();
                            foreach (var line in out_.Split('\n'))
                            {
                                var name = (line ?? "").Trim();
                                if (string.IsNullOrEmpty(name)) continue;
                                bool isDir = name.EndsWith("/");
                                if (isDir) name = name[..^1];
                                items.Add(new DirItem { Name = name, Size = "-", Type = isDir ? "dir" : "file" });
                            }
                            return (items, "");
                        }
                    }
                    catch { }
                    try
                    {
                        var entries = _server(10.0).SyncList(serial, p);
                        var items2 = new List<DirItem>();
                        foreach (var e in entries)
                        {
                            var name = (e.Name ?? "").Trim();
                            if (string.IsNullOrEmpty(name) || name is "." or "..") continue;
                            items2.Add(new DirItem { Name = name, Size = e.Size.ToString(), Type = e.IsDir ? "dir" : "file" });
                        }
                        return (items2, "");
                    }
                    catch { }
                }
            }
            catch { }

            var outAdb = _run(new[] { AdbBin, "shell", "ls", "-l", p }, 10);
            if (string.IsNullOrEmpty(outAdb?.Trim()))
            {
                var out2 = _run(new[] { AdbBin, "shell", "ls", p }, 10);
                if (string.IsNullOrEmpty(out2?.Trim())) return (new List<DirItem>(), $"无法列出目录：{p}（设备未连接或权限不足）");
                var items3 = new List<DirItem>();
                foreach (var w in out2.Split(new[] { ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
                    items3.Add(new DirItem { Name = w.Trim(), Size = "-", Type = "file" });
                return (items3, "");
            }
            var result = new List<DirItem>();
            foreach (var line in outAdb.Split('\n'))
            {
                var s = line.Trim();
                if (string.IsNullOrEmpty(s) || s.StartsWith("total ")) continue;
                var parts = s.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                try
                {
                    var perm = parts[0];
                    bool isDir = perm.StartsWith("d");
                    var size = "-";
                    foreach (var tok in parts.Skip(1).Take(5))
                    {
                        if (tok.All(char.IsDigit)) { size = tok; break; }
                    }
                    result.Add(new DirItem { Name = parts[^1], Size = size, Type = isDir ? "dir" : "file" });
                }
                catch { result.Add(new DirItem { Name = s, Size = "-", Type = "file" }); }
            }
            return (result, "");
        }

        public static (bool, string) PullFile(string remote, string local)
        {
            try
            {
                var serials = ListDevices();
                var serial = serials.Count > 0 ? serials[0] : "";
                if (!string.IsNullOrEmpty(serial) && EnsureAdbServerRunning())
                {
                    _server(600.0).SyncPullFile(serial, remote, local);
                    return (true, "完成");
                }
                throw new Exception("no device");
            }
            catch (Exception e)
            {
                try
                {
                    var out_ = _run(new[] { AdbBin, "pull", remote, local }, 600);
                    return (true, string.IsNullOrEmpty(out_) ? "完成" : out_);
                }
                catch { return (false, e.Message); }
            }
        }

        private static string ShQuote(string s)
        {
            var t = s ?? "";
            if (t.Length == 0) return "''";
            if (!t.Contains("'")) return $"'{t}'";
            return "'" + t.Replace("'", "'\"'\"'") + "'";
        }

        public static string AdbShellSerial(string serial, object args, int timeout = 20)
        {
            try
            {
                if (string.IsNullOrEmpty(serial)) return "";
                if (!EnsureAdbServerRunning()) throw new AdbServerError("ADB socket unavailable; using command-line fallback");
                string cmd;
                if (args is string str) cmd = str;
                else
                {
                    var list = ((IEnumerable<object>)args).Select(x => x?.ToString() ?? "").ToList();
                    cmd = string.Join(" ", list.Select(ShQuote));
                }
                return _server(timeout).ShellAsync(serial, cmd, timeout).GetAwaiter().GetResult();
            }
            catch
            {
                if (args is string s2) return _run(new[] { AdbBin, "-s", serial, "shell", s2 }, timeout);
                var l2 = ((IEnumerable<object>)args).Select(x => x?.ToString() ?? "").ToList();
                return _run(new[] { AdbBin, "-s", serial, "shell" }.Concat(l2), timeout);
            }
        }

        public static string AdbPmPath(string serial, string pkg, int timeout = 6)
        {
            var out_ = AdbShellSerial(serial, new object[] { "pm", "path", (pkg ?? "").Trim() }, timeout);
            foreach (var line in (out_ ?? "").Split('\n'))
            {
                var s = line.Trim();
                if (s.StartsWith("package:")) return s.Split(':').LastOrDefault()?.Trim() ?? "";
            }
            return "";
        }

        public static (bool, string) AdbPullFileSerial(string serial, string remote, string local, int timeout = 600)
        {
            try
            {
                if (string.IsNullOrEmpty(serial)) return (false, "未检测到设备");
                if (!EnsureAdbServerRunning()) return (false, "ADB server 未就绪");
                _server(timeout).SyncPullFile(serial, remote, local);
                return (true, "完成");
            }
            catch (Exception e)
            {
                try
                {
                    var out_ = _run(new[] { AdbBin, "-s", serial, "pull", remote, local }, timeout);
                    return (true, string.IsNullOrEmpty(out_) ? "完成" : out_);
                }
                catch { return (false, e.Message); }
            }
        }

        public static (bool, string) AdbInstallApk(string serial, string apkPath, bool reinstall = false, bool downgrade = false, int timeout = 600)
        {
            var p = (apkPath ?? "").Trim();
            if (string.IsNullOrEmpty(p)) return (false, "APK 路径为空");
            try
            {
                if (string.IsNullOrEmpty(serial)) return (false, "未检测到设备");
                if (!EnsureAdbServerRunning()) return (false, "ADB server 未就绪");
                var remote = $"/data/local/tmp/{Guid.NewGuid():N}.apk";
                _server(timeout).SyncPushFile(serial, p, remote);
                var flags = new List<string> { "pm", "install" };
                if (reinstall) flags.Add("-r");
                if (downgrade) flags.Add("-d");
                flags.Add(remote);
                var out_ = AdbShellSerial(serial, flags.Cast<object>().ToList(), timeout);
                var ok = (out_ ?? "").Contains("Success") && !(out_ ?? "").Contains("Failure");
                try { AdbShellSerial(serial, new object[] { "rm", "-f", remote }, 10); } catch { }
                return (ok, (out_ ?? "").Trim());
            }
            catch (Exception e)
            {
                return (false, e.Message);
            }
        }

        // ==================== 路径操作 ====================
        private static string _adbShell(IEnumerable<string> args, int timeout = 20)
        {
            try
            {
                var serials = ListDevices();
                var serial = serials.Count > 0 ? serials[0] : "";
                if (!string.IsNullOrEmpty(serial) && EnsureAdbServerRunning())
                {
                    var cmd = string.Join(" ", args.Select(x => x ?? ""));
                    return _server(timeout).ShellAsync(serial, cmd, timeout).GetAwaiter().GetResult();
                }
            }
            catch { }
            return _run(new[] { AdbBin, "shell" }.Concat(args), timeout);
        }

        public static bool PathExists(string path)
        {
            var out_ = _adbShell(new[] { "ls", path }, 6);
            return !string.IsNullOrEmpty(out_?.Trim()) && !out_.Contains("No such file");
        }

        public static bool IsDir(string path)
        {
            var out_ = _adbShell(new[] { "sh", "-c", $"[ -d '{path}' ] && echo d || echo f" }, 6);
            return (out_ ?? "").Trim().StartsWith("d");
        }

        public static (bool, string) MkdirP(string path)
        {
            var out_ = _adbShell(new[] { "mkdir", "-p", path }, 8);
            return (true, out_ ?? "");
        }

        public static (bool, string) DeletePath(string path)
        {
            var out_ = _adbShell(new[] { "rm", "-rf", path }, 20);
            return (true, out_ ?? "");
        }

        public static (bool, string) MovePath(string src, string dstDir)
        {
            MkdirP(dstDir);
            var out_ = _adbShell(new[] { "sh", "-c", $"mv '{src}' '{dstDir}/'" }, 30);
            return (true, out_ ?? "");
        }

        public static (bool, string) CopyPath(string src, string dstDir)
        {
            MkdirP(dstDir);
            var out_ = _adbShell(new[] { "sh", "-c", $"cp -r '{src}' '{dstDir}/' || toybox cp -r '{src}' '{dstDir}/'" }, 120);
            return (true, out_ ?? "");
        }

        public static (bool, string) RenamePath(string src, string newName)
        {
            var parent = src.Contains('/') ? src[..src.LastIndexOf('/')] : "/";
            var out_ = _adbShell(new[] { "sh", "-c", $"mv '{src}' '{parent}/{newName}'" }, 15);
            return (true, out_ ?? "");
        }

        public static (bool, string) PullPath(string remote, string localDest)
        {
            try
            {
                var serials = ListDevices();
                var serial = serials.Count > 0 ? serials[0] : "";
                if (string.IsNullOrEmpty(serial) || !EnsureAdbServerRunning()) throw new Exception("未检测到设备");

                List<FsEntry> entries;
                try { entries = _server(20.0).SyncList(serial, remote); }
                catch { entries = new List<FsEntry>(); }

                if (entries.Count > 0)
                {
                    Directory.CreateDirectory(localDest);
                    foreach (var e in entries)
                    {
                        var name = (e.Name ?? "").Trim();
                        if (string.IsNullOrEmpty(name) || name is "." or "..") continue;
                        var rpath = remote is "/" or "" ? "/" + name : remote.TrimEnd('/') + "/" + name;
                        var lpath = Path.Combine(localDest, name);
                        if (e.IsDir)
                        {
                            var (ok, msg) = PullPath(rpath, lpath);
                            if (!ok) return (false, msg);
                        }
                        else _server(3600.0).SyncPullFile(serial, rpath, lpath);
                    }
                    return (true, "完成");
                }

                _server(3600.0).SyncPullFile(serial, remote, localDest);
                return (true, "完成");
            }
            catch (Exception e)
            {
                try
                {
                    var out_ = _run(new[] { AdbBin, "pull", remote, localDest }, 3600);
                    return (true, string.IsNullOrEmpty(out_) ? "完成" : out_);
                }
                catch { return (false, e.Message); }
            }
        }

        public static (bool, string) PushPath(string localPath, string remoteDir)
        {
            try
            {
                var serials = ListDevices();
                var serial = serials.Count > 0 ? serials[0] : "";
                if (string.IsNullOrEmpty(serial) || !EnsureAdbServerRunning()) throw new Exception("未检测到设备");

                var lp = localPath;
                if (!File.Exists(lp) && !Directory.Exists(lp)) return (false, "本地文件不存在");

                if (Directory.Exists(lp))
                {
                    MkdirP(remoteDir);
                    foreach (var child in Directory.GetFileSystemEntries(lp))
                    {
                        var name = Path.GetFileName(child);
                        var dst = remoteDir is "/" or "" ? "/" + name : remoteDir.TrimEnd('/') + "/" + name;
                        var (ok, msg) = PushPath(child, dst);
                        if (!ok) return (false, msg);
                    }
                    return (true, "完成");
                }

                var r = remoteDir;
                if (r.EndsWith("/") || r is "/" or "")
                    r = r is "/" or "" ? "/" + Path.GetFileName(lp) : r.TrimEnd('/') + "/" + Path.GetFileName(lp);

                _server(3600.0).SyncPushFile(serial, lp, r);
                return (true, "完成");
            }
            catch (Exception e)
            {
                try
                {
                    var out_ = _run(new[] { AdbBin, "push", localPath, remoteDir }, 3600);
                    return (true, string.IsNullOrEmpty(out_) ? "完成" : out_);
                }
                catch { return (false, e.Message); }
            }
        }

        public static string GetBoardId(string serial)
        {
            try { var cmdline = Shell(serial, "cat /proc/cmdline"); return ExtractBoardId(cmdline); }
            catch { return ""; }
        }

        public static string ExtractBoardId(string cmdline)
        {
            if (string.IsNullOrEmpty(cmdline)) return "";
            const string token = "oplusboot.serialno=";
            var idx = cmdline.IndexOf(token, StringComparison.Ordinal);
            if (idx == -1) return "";
            var rest = cmdline[(idx + token.Length)..];
            return rest.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries).FirstOrDefault()?.Trim() ?? "";
        }

        public static string ModeCn(string mode)
        {
            return mode switch
            {
                "system" => "系统",
                "sideload" => "Sideload",
                "fastbootd" => "FastbootD",
                "bootloader" => "Bootloader",
                "edl" => "9008 (EDL)",
                "brom" => "BROM",
                "offline" => "离线",
                "unauthorized" => "未授权",
                "recovery" => "Recovery",
                "none" => "未连接",
                _ => string.IsNullOrEmpty(mode) ? "未知" : mode,
            };
        }

        public class ConnectionSummary
        {
            public string Mode { get; set; } = "none";
            public string Serial { get; set; } = "";
            public bool Connected { get; set; }
            public string StatusConn { get; set; } = "";
            public string StatusMode { get; set; } = "";
            public string StatusLine { get; set; } = "";
            public string StatusColor { get; set; } = "#86909c";
            public string BannerState { get; set; } = "disconnected";
        }

        public static ConnectionSummary GetConnectionSummary()
        {
            var (mode, serial) = DetectConnectionMode(throwOnError: true);
            var cn = ModeCn(mode);
            serial ??= "";
            var s = new ConnectionSummary
            {
                Mode = mode,
                Serial = serial,
                Connected = mode is "system" or "recovery" or "sideload" or "fastbootd" or "bootloader" or "edl" or "brom",
            };
            if (mode is "system" or "recovery" or "sideload" or "fastbootd" or "bootloader")
            {
                s.StatusConn = $"设备：已连接（{cn}）";
                s.StatusMode = $"模式：{cn}";
                s.StatusLine = $"已连接：{cn}";
                s.StatusColor = "#00b42a";
                s.BannerState = "connected";
            }
            else if (mode is "edl" or "brom")
            {
                var port = string.IsNullOrEmpty(serial) ? "" : $"（{serial}）";
                s.StatusConn = $"设备：已连接（端口{port}）";
                s.StatusMode = $"模式：{cn}";
                s.StatusLine = $"已连接：{cn}{port}";
                s.StatusColor = "#fa8c16";
                s.BannerState = "connected";
            }
            else if (mode is "offline" or "unauthorized")
            {
                s.StatusConn = mode == "unauthorized" ? "设备：等待授权" : "设备：离线";
                s.StatusMode = "模式：" + cn;
                s.StatusLine = mode == "unauthorized"
                    ? "设备等待授权，请在手机上允许 USB 调试"
                    : "设备离线，请检查 USB 连接或重新连接设备";
                s.StatusColor = "#ff4d4f";
                s.BannerState = "disconnected";
            }
            else
            {
                s.StatusConn = "设备：未连接";
                s.StatusMode = "模式：未知";
                s.StatusLine = "未发现已连接设备";
                s.StatusColor = "#86909c";
                s.BannerState = "disconnected";
            }
            return s;
        }

        public static DeviceInfo CollectOverallInfo()
        {
            var summary = GetConnectionSummary();
            var info = new DeviceInfo { ConnectionStatus = summary.Mode, Serial = summary.Serial };
            if (summary.Mode is "system" or "sideload" && !string.IsNullOrEmpty(summary.Serial))
            {
                var dev = GetDeviceInfo(summary.Serial);
                CopyProps(dev, info);
            }
            else if (summary.Mode is "fastbootd" or "bootloader")
            {
                string CleanFastbootOutput(string output)
                {
                    if (string.IsNullOrEmpty(output)) return output;
                    var lines = output.Trim().Split('\n');
                    var first = lines[0].Trim();
                    var clean = first.Replace("(bootloader) ", "");
                    var fi = clean.ToLowerInvariant().IndexOf("finish");
                    if (fi >= 0) clean = clean[..fi].Trim();
                    return clean;
                }
                var prod = CleanFastbootOutput(Fastboot(new[] { "getvar", "product" }, 2));
                info.Product = prod.Contains("product:") ? prod.Split(new[] { "product:" }, StringSplitOptions.None)[1].Trim() : prod;
                var curSlot = CleanFastbootOutput(Fastboot(new[] { "getvar", "current-slot" }, 2));
                if (curSlot.Contains("current-slot:")) info.CurrentSlot = curSlot.Split(new[] { "current-slot:" }, StringSplitOptions.None)[1].Trim();
                else if (curSlot.Contains("SLOT:")) info.CurrentSlot = curSlot.Split(new[] { "SLOT:" }, StringSplitOptions.None)[1].Trim();
                else info.CurrentSlot = curSlot;
                var status = "unknown";
                var unlockState = CleanFastbootOutput(Fastboot(new[] { "getvar", "unlocked" }, 2));
                if (unlockState.ToLowerInvariant().Contains("yes")) status = "unlocked";
                else if (unlockState.ToLowerInvariant().Contains("no")) status = "locked";
                if (status == "unknown")
                {
                    var bootState = CleanFastbootOutput(Fastboot(new[] { "getvar", "secure" }, 2));
                    if (bootState.ToLowerInvariant().Contains("no")) status = "unlocked";
                    else if (bootState.ToLowerInvariant().Contains("yes")) status = "locked";
                }
                info.BootloaderUnlock = status;
                info.Battery = "-";
                info.StorageData = "-";
                info.Kernel = "-";
                info.AndroidVersion = "-";
            }
            info.ConnectionStatus = summary.Mode;
            info.Serial = summary.Serial;
            return info;
        }

        private static void CopyProps(DeviceInfo src, DeviceInfo dst)
        {
            dst.Brand = src.Brand; dst.Model = src.Model; dst.Device = src.Device; dst.Product = src.Product;
            dst.AndroidVersion = src.AndroidVersion; dst.Sdk = src.Sdk; dst.Vndk = src.Vndk;
            dst.BuildDisplay = src.BuildDisplay; dst.Fingerprint = src.Fingerprint; dst.Battery = src.Battery;
            dst.Bootloader = src.Bootloader; dst.Baseband = src.Baseband; dst.CpuInfo = src.CpuInfo;
            dst.BatteryHealthPercent = src.BatteryHealthPercent; dst.BatteryRatedCapacity = src.BatteryRatedCapacity;
            dst.BatteryFullCapacity = src.BatteryFullCapacity; dst.StorageData = src.StorageData;
            dst.MemoryPercent = src.MemoryPercent; dst.MemorySummary = src.MemorySummary; dst.Kernel = src.Kernel;
            dst.CurrentSlot = src.CurrentSlot; dst.BootloaderUnlock = src.BootloaderUnlock; dst.Codename = src.Codename;
            dst.DeviceSerial = src.DeviceSerial; dst.Uptime = src.Uptime; dst.Resolution = src.Resolution;
            dst.DisplayDensity = src.DisplayDensity; dst.StorageType = src.StorageType; dst.RootStatus = src.RootStatus;
        }
    }
}
