using Microsoft.UI.Dispatching;

namespace ElementBlocks.Desktop.Services;

/// <summary>
/// 轮换调度。设计要点：
///  * 不做"计时器到点就切换"，而是把 nextFireUtc 写进配置；每 15 秒用 UTC 对时检查。
///    这样休眠、时钟调整、进程重启都不会漏掉或重复触发，也天然支持跨天间隔。
///  * 恢复运行时如果已过期，只补切一次（不把休眠的 8 小时一次性补 8 次）。
///  * 已启用元素少于 2 个时，nextFireUtc 清空，等同"从不"。
/// </summary>
public sealed class RotationService : IDisposable
{
    private const int PollSeconds = 15;

    private readonly AppState _state;
    private readonly DispatcherQueue _dispatcher;
    private readonly Timer _poll;
    private bool _disposed;

    public event Action? Polled;

    public RotationService(AppState state)
    {
        _state = state;
        _dispatcher = DispatcherQueue.GetForCurrentThread();
        _poll = new Timer(_ => _dispatcher.TryEnqueue(Tick), null,
                          TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(PollSeconds));
    }

    private void Tick()
    {
        if (_disposed) return;
        var cfg = _state.Config;
        var interval = _state.Assets.Interval(cfg.Rotation);
        var now = DateTimeOffset.UtcNow;

        bool inactive = interval.Minutes <= 0 || cfg.Paused || _state.EnabledList().Count < 2;
        if (inactive)
        {
            if (cfg.NextFireUtc is not null)
            {
                cfg.NextFireUtc = null;
                _state.ConfigService.RequestSave();
            }
            Polled?.Invoke();
            return;
        }

        // 间隔被改动 / 首次启动 / 配置损坏 → 立刻排一次
        if (cfg.NextFireUtc is null || cfg.NextFireUtc > now.AddMinutes(interval.Minutes * 2))
            Reschedule(now, interval.Minutes);

        if (now >= cfg.NextFireUtc)
        {
            _state.RotateNext();
            Reschedule(now, interval.Minutes);  // 从"现在"重新计算，不补跑历史次数
        }
        Polled?.Invoke();
    }

    private void Reschedule(DateTimeOffset now, int minutes)
    {
        DateTimeOffset next = minutes switch
        {
            60 => new DateTimeOffset(now.Year, now.Month, now.Day, now.Hour, 0, 0, TimeSpan.Zero)
                    .AddHours(1),
            1440 => new DateTimeOffset(now.ToLocalTime().Date.AddDays(1),
                                       TimeZoneInfo.Local.GetUtcOffset(now.ToLocalTime().Date.AddDays(1)))
                    .ToUniversalTime(),
            _ => now.AddMinutes(minutes),
        };
        _state.Config.NextFireUtc = next;
        _state.ConfigService.RequestSave();
        _state.NotifyScheduleChanged();
    }

    /// <summary>托盘"立即切换"后重置排程，避免刚手动切完又立刻自动切。</summary>
    public void RestartCycleAfterManualSwitch()
    {
        var interval = _state.Assets.Interval(_state.Config.Rotation);
        if (interval.Minutes > 0 && !_state.Config.Paused)
            Reschedule(DateTimeOffset.UtcNow, interval.Minutes);
    }

    public void Dispose()
    {
        _disposed = true;
        _poll.Dispose();
    }
}
