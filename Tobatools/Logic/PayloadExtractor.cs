// payload.bin 解包方案参考自 TIK（GPL-3.0，另附非商业条款）: https://github.com/ColdWindScholar/TIK
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Threading.Tasks;
using Tobatools.Logic.ImageFactory;
using Tobatools.Services;

namespace Tobatools.Logic
{
    /// <summary>payload.bin 解包器：本地或在线 payload.bin，支持全量/指定分区。</summary>
    public sealed class PayloadExtractor
    {
        public Action<string>? Log { get; set; }
        public Action<string, string>? StepStart { get; set; }
        public Action<string, bool, string>? StepFinish { get; set; }
        private volatile bool _stop;
        public void Stop() => _stop = true;

        private void Emit(string s) { try { Log?.Invoke(s); } catch { } }

        private static bool IsUrl(string s)
        {
            return Uri.TryCreate(s, UriKind.Absolute, out var u) && (u.Scheme == "http" || u.Scheme == "https");
        }

        public bool Extract(string source, string outputDir, string partitions = "")
        {
            source = (source ?? "").Trim();
            outputDir = (outputDir ?? "").Trim();
            partitions = (partitions ?? "").Trim();

            if (string.IsNullOrEmpty(source)) throw new ArgumentException("请输入 payload.bin 路径或在线 URL");
            if (string.IsNullOrEmpty(outputDir)) throw new ArgumentException("请输入输出目录");

            var stepId = "payload";
            StepStart?.Invoke(stepId, "解包 payload.bin");
            try
            {
                Directory.CreateDirectory(outputDir);
                if (_stop) { StepFinish?.Invoke(stepId, false, "已取消"); return false; }

                string payloadFile = source;
                if (IsUrl(source))
                {
                    Emit("检测到在线 URL，开始下载 payload.bin...");
                    var tmpDir = AppPaths.TempDir;
                    payloadFile = Path.Combine(tmpDir, "payload_download.bin");
                    using var http = new HttpClient { Timeout = TimeSpan.FromHours(12) };
                    http.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0");
                    var resp = http.GetAsync(source, HttpCompletionOption.ResponseHeadersRead).GetAwaiter().GetResult();
                    resp.EnsureSuccessStatusCode();
                    long? total = resp.Content.Headers.ContentLength;
                    using (var src = resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult())
                    using (var dst = new FileStream(payloadFile, FileMode.Create, FileAccess.Write))
                    {
                        var buf = new byte[1 << 20];
                        long done = 0;
                        int n;
                        while ((n = src.Read(buf, 0, buf.Length)) > 0)
                        {
                            dst.Write(buf, 0, n);
                            done += n;
                            if (total != null && total > 0)
                                Emit($"下载进度: {done / 1024 / 1024} MB / {total.Value / 1024 / 1024} MB");
                        }
                    }
                    Emit($"下载完成: {payloadFile}");
                }

                var tool = ExtTool.Resolve("payload-dumper-go", out var toolSource);
                if (!File.Exists(tool))
                    throw new FileNotFoundException($"未找到 payload-dumper-go (source={toolSource})，请在 bin 目录放置该工具");

                var args = new List<string> { "-o", outputDir };
                if (partitions.Length > 0) args.AddRange(new[] { "-partitions", partitions });
                args.Add(payloadFile);

                Emit($"工具: {tool} (source={toolSource})");
                Emit($"输出目录: {outputDir}");
                if (partitions.Length > 0) Emit($"指定分区: {partitions}");
                else Emit("分区: 全部");

                var result = ProcessRunner.RunAsync(tool, args, null, s => Emit(s), () => _stop, 0).GetAwaiter().GetResult();
                if (_stop) { StepFinish?.Invoke(stepId, false, "已取消"); return false; }
                if (result.ExitCode != 0)
                    throw new InvalidOperationException($"解包失败，退出码: {result.ExitCode}");

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
}
