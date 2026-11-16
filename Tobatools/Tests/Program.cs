using System.Diagnostics;
using Microsoft.UI.Dispatching;
using Tobatools.Models;
using Tobatools.Services;

int checks = 0;
void Check(bool value, string name)
{
    if (!value) throw new Exception("FAIL: " + name);
    Console.WriteLine("PASS: " + name);
    checks++;
}

var parsed = AdbDeviceParser.Parse("* daemon not running; starting now at tcp:5037\n* daemon started successfully\nList of devices attached\nusbA\tunauthorized\r\n192.168.1.8:5555  device product:test model:Test\nusbB\toffline\nerror: transport unavailable\n");
Check(parsed.Count == 3, "daemon/header/error lines are not devices");
Check(AdbDeviceParser.SelectMode(parsed) == ("system", "192.168.1.8:5555"), "online device takes priority over unauthorized device");
Check(AdbDeviceParser.SelectMode(AdbDeviceParser.Parse("x\tunauthorized")) == ("unauthorized", "x"), "unauthorized remains distinct");
Check(AdbDeviceParser.SelectMode(AdbDeviceParser.Parse("x\toffline")) == ("offline", "x"), "offline remains distinct");
Check(AdbDeviceParser.SelectMode(AdbDeviceParser.Parse("x\trecovery")) == ("recovery", "x"), "recovery is recognized");
Check(AdbDeviceParser.SelectMode(AdbDeviceParser.Parse("x\tsideload")) == ("sideload", "x"), "sideload is recognized");
Check(AdbDeviceParser.Parse("x\tdevice\nx device model:x").Count == 1, "duplicate serials are removed");
Check(AdbDeviceParser.SelectMode(AdbDeviceParser.Parse(null)) == ("none", ""), "empty output is disconnected");
Check(AdbCommandResult.IsSuccessful(0, "package:com.example.error\npackage:com.example.failure\n"), "package names containing error/failure are not command failures");
Check(!AdbCommandResult.IsSuccessful(1, ""), "nonzero command exit codes fail");
Check(!AdbCommandResult.IsSuccessful(0, "Failure [DELETE_FAILED_INTERNAL_ERROR]"), "pm Failure output fails even with exit code zero");
Check(!AdbCommandResult.IsSuccessful(0, "Error: unknown package"), "Android Error diagnostics fail");
Check(!AdbCommandResult.IsSuccessful(0, "adb: error: device offline"), "ADB-prefixed diagnostics fail");
Check(AdbCommandResult.IsSuccessful(0, "Success\n"), "successful command output passes");

Check(WirelessAdb.TryEndpoint(" 127.0.0.1:5555 ", false, out var endpoint, out _) && endpoint == "127.0.0.1:5555", "wireless IPv4 endpoint is trimmed and preserved");
Check(WirelessAdb.TryEndpoint("phone.local", false, out endpoint, out _) && endpoint == "phone.local:5555", "legacy wireless connection defaults to port 5555");
Check(WirelessAdb.TryEndpoint("[::1]:5555", false, out endpoint, out _) && endpoint == "[::1]:5555", "bracketed IPv6 retains its port");
Check(!WirelessAdb.TryEndpoint("::1:5555", false, out _, out _), "ambiguous unbracketed IPv6 is rejected");
Check(!WirelessAdb.TryEndpoint("phone.local", true, out _, out _), "pairing requires the explicit pairing port");
Check(!WirelessAdb.TryEndpoint("127.0.0.1:", false, out _, out _), "explicit empty port is rejected");
Check(!WirelessAdb.TryEndpoint("127.0.0.1:0", false, out _, out _) && !WirelessAdb.TryEndpoint("127.0.0.1:65536", false, out _, out _), "out-of-range ports are rejected");
Check(!WirelessAdb.TryEndpoint("http://127.0.0.1:5555", false, out _, out _) && !WirelessAdb.TryEndpoint("127.0.0.1 --help", false, out _, out _), "schemes and extra command arguments are rejected");
Check(WirelessAdb.IsPairingCode("123456") && !WirelessAdb.IsPairingCode("12345") && !WirelessAdb.IsPairingCode("abcdef"), "pairing codes require six ASCII digits");
Check(WirelessAdb.Result(0, "connected to 127.0.0.1:5555", false).Code == 0, "explicit ADB connection success passes");
Check(WirelessAdb.Result(0, "already connected to 127.0.0.1:5555", false).Code == 0, "already-connected ADB result passes");
Check(WirelessAdb.Result(0, "cannot connect to 10.0.2.15:5555: error 10060", false).Code != 0, "zero exit code with a timeout message is a failure");
Check(WirelessAdb.Result(0, "failed to authenticate to 127.0.0.1:5555", false).Code != 0, "authentication failure is not connection success");
Check(WirelessAdb.Result(0, "", false).Code != 0 && WirelessAdb.Result(0, "unexpected output", false).Code != 0, "empty and unknown ADB replies are not success");
Check(WirelessAdb.Result(1, "connected to 127.0.0.1:5555", false).Code != 0, "nonzero exit code overrides positive text");
Check(WirelessAdb.Result(0, "Successfully paired to 192.168.2.5:37001 [guid=test]", true).Code == 0, "explicit pairing success passes");
Check(WirelessAdb.Result(0, "Failed: Wrong password or connection was dropped.", true).Code != 0, "pairing failure with zero exit code is rejected");
Check(WirelessAdb.Result(0, "Successfully paired to 192.168.2.5:37001", false).Code != 0, "pairing is not mistaken for a usable ADB connection");
Check(WirelessAdb.FailureHint("10.0.2.15:5555", "10060").Contains("127.0.0.1:5555"), "emulator NAT failure suggests checking a host mapping without rewriting it");

var banner = new DeviceBannerSummary();
Check(banner.Update(null, null, null) == "正在检测设备…", "compact banner distinguishes detection from disconnected");
Check(banner.Update("phone1", "system", new DeviceInfo { Serial = "phone1", Brand = "Redmi", Model = "Redmi K20 Pro" }).StartsWith("Redmi K20 Pro -"), "compact banner avoids duplicate device brand");
Check(banner.Update("phone1", "recovery", null).Contains("Redmi K20 Pro - 已连接 · recovery"), "same-serial recovery retains known device name with current mode");
Check(banner.Update("phone2", "recovery", null).StartsWith("phone2 -"), "different device never inherits previous model");
Check(banner.Update("phone2", "unauthorized", null).Contains("等待授权"), "compact banner distinguishes authorization");
Check(banner.Update("phone2", "offline", null).Contains("离线"), "compact banner distinguishes offline");
Check(banner.Update("", "none", null) == "未连接设备", "disconnect clears compact device identity");
Check(banner.Update("phone1", "recovery", null).StartsWith("phone1 -"), "reconnection does not reuse disconnected device identity");
Check(banner.Update("", "error", null) == "设备检测失败", "compact banner preserves detection errors");

var dispatcher = new DispatcherQueue();
var session = DeviceSession.Instance;
using var releaseDetails = new ManualResetEventSlim(false);
int calls = 0, active = 0, maxActive = 0, notices = 0;
int state = 0;
bool wrongThread = false;
AdbService.ReadSummary = () =>
{
    Interlocked.Increment(ref calls);
    return Volatile.Read(ref state) switch
    {
        0 => new() { Connected = true, Mode = "system", Serial = "phoneA" },
        1 => new() { Connected = false, Mode = "none" },
        2 => throw new IOException("test detection failure"),
        _ => new() { Connected = true, Mode = "sideload", Serial = "phoneB" }
    };
};
AdbService.ReadInfo = serial =>
{
    int count = Interlocked.Increment(ref active);
    maxActive = Math.Max(maxActive, count);
    try
    {
        if (!releaseDetails.Wait(TimeSpan.FromSeconds(5))) throw new TimeoutException("Test details gate timed out");
        return new DeviceInfo { Serial = serial, Model = "Test phone" };
    }
    finally { Interlocked.Decrement(ref active); }
};
Action brokenSubscriber = () => throw new Exception("test subscriber failure");
Action subscriber = () =>
{
    notices++;
    wrongThread |= Environment.CurrentManagedThreadId != dispatcher.OwnerThread;
};
session.StateChanged += brokenSubscriber;
session.StateChanged += subscriber;
void PumpUntil(Func<bool> condition)
{
    var time = Stopwatch.StartNew();
    while (time.Elapsed < TimeSpan.FromSeconds(5))
    {
        dispatcher.Drain();
        if (condition()) return;
        Thread.Sleep(10);
    }
    throw new TimeoutException("Timed out waiting for session state");
}
try
{
    session.Start(dispatcher);
    PumpUntil(() => session.IsConnected);
    Check(session.Info == null && !releaseDetails.IsSet, "connection is published before slow device details");
    Check(notices > 0 && !wrongThread, "UI thread delivery survives another subscriber failure");
    for (int i = 0; i < 20; i++) session.RefreshNow();
    Thread.Sleep(100);
    Check(calls == 1 && maxActive == 1, "manual refresh cannot overlap in-flight device collection");
    releaseDetails.Set();
    PumpUntil(() => session.Info?.Model == "Test phone");
    Check(session.Info?.Serial == "phoneA", "details update is delivered to UI");
    Volatile.Write(ref state, 1);
    session.RefreshNow();
    PumpUntil(() => session.Summary?.Mode == "none");
    Check(session.Info == null, "disconnect clears previous device information");
    Volatile.Write(ref state, 2);
    session.RefreshNow();
    PumpUntil(() => session.Summary?.Mode == "error");
    Check(session.Summary!.StatusLine.Contains("test detection failure"), "detection errors are not reported as disconnected");
    Volatile.Write(ref state, 3);
    session.RefreshNow();
    PumpUntil(() => session.Summary?.Mode == "sideload");
    Check(session.IsConnected && session.Info == null, "sideload connects without unsupported shell collection");
    int beforeStop = notices;
    session.Stop();
    dispatcher.Drain();
    Check(notices == beforeStop, "stopped session does not publish queued notifications");

    releaseDetails.Reset();
    Volatile.Write(ref state, 0);
    session.Start(dispatcher);
    PumpUntil(() => Volatile.Read(ref active) == 1);
    session.Stop();
    session.Start(dispatcher);
    Thread.Sleep(100);
    Check(Volatile.Read(ref active) == 1 && maxActive == 1, "stop/restart cannot overlap old and new collectors");
    releaseDetails.Set();
    PumpUntil(() => session.Info?.Model == "Test phone");
    Check(session.IsConnected, "a restarted session can publish new device information");
}
finally
{
    releaseDetails.Set();
    session.Stop();
    session.StateChanged -= brokenSubscriber;
    session.StateChanged -= subscriber;
}
Console.WriteLine($"All {checks} regression checks passed. These tests use fake ADB and a queued UI dispatcher; no device was modified.");
