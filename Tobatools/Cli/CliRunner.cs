using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;

namespace Tobatools.Cli
{
    /// <summary>
    /// 开发调试命令行的公共基础设施：参数解析、输出、进度与确认。
    /// 仅在带 --cli 参数启动时使用，不参与正式图形界面的任何路径。
    /// </summary>
    public static class CliRunner
    {
        public static readonly string[] HelpTokens = { "--cli", "-cli", "/cli", "--headless" };

        /// <summary>检测启动参数是否要求进入命令行模式。</summary>
        public static bool IsCliInvocation(string[]? args)
        {
            if (args == null) return false;
            foreach (var a in args)
            {
                var t = (a ?? "").Trim();
                foreach (var token in HelpTokens)
                {
                    if (string.Equals(t, token, StringComparison.OrdinalIgnoreCase)) return true;
                }
            }
            return false;
        }

        /// <summary>去掉 CLI 开关后返回剩余参数。</summary>
        public static string[] StripTokens(string[]? args)
        {
            if (args == null) return Array.Empty<string>();
            var result = new List<string>();
            foreach (var a in args)
            {
                var t = (a ?? "").Trim();
                var drop = false;
                foreach (var token in HelpTokens)
                {
                    if (string.Equals(t, token, StringComparison.OrdinalIgnoreCase)) { drop = true; break; }
                }
                if (!drop) result.Add(t);
            }
            return result.ToArray();
        }

        private static void Color(ConsoleColor color, string text)
        {
            var prev = Console.ForegroundColor;
            try { Console.ForegroundColor = color; } catch { }
            Console.WriteLine(text);
            try { Console.ForegroundColor = prev; } catch { }
        }

        public static void Info(string message) => Console.WriteLine(message);
        public static void Step(string message) => Color(ConsoleColor.Cyan, "==> " + message);
        public static void Ok(string message) => Color(ConsoleColor.Green, "[OK] " + message);
        public static void Warn(string message) => Color(ConsoleColor.Yellow, "[WARN] " + message);
        public static void Fail(string message) => Color(ConsoleColor.Red, "[FAIL] " + message);
        public static void Detail(string message) => Color(ConsoleColor.DarkGray, "    " + message);

        /// <summary>打印一行缩进的“键: 值”，空值显示为 —。</summary>
        public static void Field(string key, string? value)
        {
            var v = string.IsNullOrWhiteSpace(value) ? "—" : value!.Trim();
            Console.WriteLine($"    {key,-22} {v}");
        }

        public static void Section(string title)
        {
            Console.WriteLine();
            Color(ConsoleColor.White, "--- " + title + " ---");
        }
    }

    /// <summary>简单的子命令注册表：名称 → 说明与处理函数。</summary>
    public sealed class CliCommand
    {
        public string Name { get; }
        public string Usage { get; }
        public string Summary { get; }
        public Func<string[], int> Handler { get; }

        public CliCommand(string name, string usage, string summary, Func<string[], int> handler)
        {
            Name = name;
            Usage = usage;
            Summary = summary;
            Handler = handler;
        }
    }

    /// <summary>命令行参数集合：支持 --key value 与 --flag。</summary>
    public sealed class CliArgs
    {
        private readonly Dictionary<string, string> _values = new(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> _flags = new(StringComparer.OrdinalIgnoreCase);
        private readonly List<string> _positional = new();

        public IReadOnlyList<string> Positional => _positional;

        public static CliArgs Parse(string[] args)
        {
            var result = new CliArgs();
            for (var i = 0; i < args.Length; i++)
            {
                var token = args[i] ?? "";
                if (token.StartsWith("--", StringComparison.Ordinal))
                {
                    var body = token[2..];
                    var eq = body.IndexOf('=');
                    if (eq > 0)
                    {
                        result._values[body[..eq]] = body[(eq + 1)..];
                        continue;
                    }
                    // 下一个参数存在且不是开关时作为取值，否则视为布尔开关。
                    if (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
                    {
                        result._values[body] = args[i + 1];
                        i++;
                    }
                    else
                    {
                        result._flags.Add(body);
                    }
                    continue;
                }
                result._positional.Add(token);
            }
            return result;
        }

        public bool Has(string name) => _values.ContainsKey(name) || _flags.Contains(name);

        public string? Get(string name)
            => _values.TryGetValue(name, out var v) ? v : null;

        public string Get(string name, string def)
            => _values.TryGetValue(name, out var v) && !string.IsNullOrWhiteSpace(v) ? v : def;

        public int GetInt(string name, int def)
            => int.TryParse(Get(name, ""), out var v) ? v : def;

        public long GetLong(string name, long def)
            => long.TryParse(Get(name, ""), out var v) ? v : def;

        public bool GetBool(string name, bool def = false)
        {
            if (_flags.Contains(name)) return true;
            if (!_values.TryGetValue(name, out var v)) return def;
            var t = (v ?? "").Trim().ToLowerInvariant();
            if (t is "1" or "true" or "yes" or "on") return true;
            if (t is "0" or "false" or "no" or "off") return false;
            return def;
        }

        /// <summary>必填项：缺失时抛出带用法提示的异常。</summary>
        public string Require(string name, string hint)
        {
            var v = Get(name, "");
            if (string.IsNullOrWhiteSpace(v))
                throw new CliUsageException($"缺少参数 --{name}（{hint}）");
            return v;
        }

        public string Pos(int index, string def = "")
            => index < _positional.Count ? _positional[index] : def;
    }

    public sealed class CliUsageException : Exception
    {
        public CliUsageException(string message) : base(message) { }
    }
}
