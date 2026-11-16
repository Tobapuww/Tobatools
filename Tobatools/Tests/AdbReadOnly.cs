using Tobatools.Services;

// 仅检查工具路径、设备列表和当前模式，不调用任何修改设备状态的操作。
Console.WriteLine("Resolved ADB: " + AdbService.AdbBin);
if (!AdbService.CheckAdbAvailable()) throw new Exception("ADB executable was not resolved.");
var cli = AdbService.RunAdb(new[] { "devices", "-l" });
if (cli.Code != 0) throw new Exception("ADB CLI failed: " + cli.Out);
var expected = AdbDeviceParser.Parse(cli.Out).OrderBy(d => d.Serial).ToList();
var actual = AdbService.ListDeviceStates().OrderBy(d => d.Serial).ToList();
if (!expected.SequenceEqual(actual)) throw new Exception("CLI and application device states differ (or device changed during test).");
Console.WriteLine($"PASS: CLI and application enumerate the same {actual.Count} device(s).");
var online = actual.Where(d => d.State == "device").Select(d => d.Serial).OrderBy(s => s);
if (!online.SequenceEqual(AdbService.ListDevices().OrderBy(s => s)))
    throw new Exception("Online-device filtering differs (or device changed during test).");
Console.WriteLine("PASS: online-device filtering matches the shared enumeration.");
var summary = AdbService.GetConnectionSummary();
Console.WriteLine($"Connection summary: mode={summary.Mode}, connected={summary.Connected}");
Console.WriteLine("No install, reboot, flash, push, delete or other device modification was performed.");
