using System.Collections.Concurrent;
using Tobatools.Models;

// 仅供回归测试的替身；主项目明确排除了 Tests/**/*.cs。
namespace Microsoft.UI.Dispatching
{
    public sealed class DispatcherQueue
    {
        private readonly ConcurrentQueue<Action> _queue = new();
        public bool Accepting { get; set; } = true;
        public int OwnerThread { get; } = Environment.CurrentManagedThreadId;
        public bool TryEnqueue(Action callback)
        {
            if (!Accepting) return false;
            _queue.Enqueue(callback);
            return true;
        }
        public void Drain()
        {
            if (OwnerThread != Environment.CurrentManagedThreadId) throw new Exception("Wrong UI thread");
            while (_queue.TryDequeue(out var callback)) callback();
        }
    }
}

namespace Tobatools.Services
{
    public static class AdbService
    {
        public sealed class ConnectionSummary
        {
            public string Mode { get; set; } = "none";
            public string Serial { get; set; } = "";
            public bool Connected { get; set; }
            public string StatusLine { get; set; } = "";
            public string StatusConn { get; set; } = "";
            public string StatusColor { get; set; } = "";
        }
        public static Func<ConnectionSummary> ReadSummary { get; set; } = () => new();
        public static Func<string, DeviceInfo> ReadInfo { get; set; } = s => new() { Serial = s };
        public static ConnectionSummary GetConnectionSummary() => ReadSummary();
        public static DeviceInfo GetDeviceInfo(string serial) => ReadInfo(serial);
        public static DeviceInfo CollectOverallInfo() => new();
    }
}
