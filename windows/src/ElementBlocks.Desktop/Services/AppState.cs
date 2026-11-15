using ElementBlocks.Desktop.Models;

namespace ElementBlocks.Desktop.Services;

/// <summary>
/// 单一状态源：常驻窗口、设置页、托盘菜单、轮换服务都读它，
/// 避免 WinUI3 多窗口之间各自持有过期配置。
/// </summary>
public sealed class AppState
{
    private readonly AppAssets _assets;
    private readonly ConfigService _config;
    private readonly HashSet<string> _enabled;

    public AppAssets Assets => _assets;
    public AppConfig Config => _config.Current;
    public ConfigService ConfigService => _config;

    public event Action<Element?>? ElementChanged;
    public event Action? EnabledChanged;
    public event Action? SettingsChanged;

    public Element? Current { get; private set; }

    public AppState(AppAssets assets, ConfigService config)
    {
        _assets = assets;
        _config = config;
        _enabled = new HashSet<string>(config.Current.EnabledSymbols, StringComparer.Ordinal);
        Current = ResolveInitialElement();
    }

    private Element? ResolveInitialElement()
    {
        var last = Config.LastSymbol;
        if (last is not null && _enabled.Contains(last) && _assets.BySymbol.TryGetValue(last, out var e))
            return e;
        return EnabledList().FirstOrDefault();
    }

    public List<Element> EnabledList() =>
        _assets.Elements.Elements.Where(e => _enabled.Contains(e.Symbol)).ToList();

    public bool IsEnabled(string symbol) => _enabled.Contains(symbol);

    public void SetEnabled(string symbol, bool value)
    {
        bool changed = value ? _enabled.Add(symbol) : _enabled.Remove(symbol);
        if (!changed) return;
        SyncEnabledToConfig();
        if (!value && Current?.Symbol == symbol)
            Current = EnabledList().FirstOrDefault();
        else if (value && Current is null)
            Current = _assets.BySymbol.TryGetValue(symbol, out var e) ? e : null;
        _config.RequestSave();
        EnabledChanged?.Invoke();
        ElementChanged?.Invoke(Current);
    }

    public void SetAll(bool enabled)
    {
        _enabled.Clear();
        if (enabled)
            foreach (var e in _assets.Elements.Elements) _enabled.Add(e.Symbol);
        AfterBulkEdit();
    }

    public void OnlyNatural()
    {
        _enabled.Clear();
        foreach (var e in _assets.Elements.Elements.Where(e => !e.Synthetic))
            _enabled.Add(e.Symbol);
        AfterBulkEdit();
    }

    public void ResetDefaults()
    {
        var d = AppConfig.CreateDefaults(_assets.Elements.Elements.Select(e => e.Symbol));
        _enabled.Clear();
        foreach (var s in d.EnabledSymbols) _enabled.Add(s);
        Config.Rotation = d.Rotation;
        Config.Position = d.Position;
        Config.BlockSize = d.BlockSize;
        Config.ClickThrough = d.ClickThrough;
        Config.Opacity = d.Opacity;
        Config.Paused = d.Paused;
        Config.LastSymbol = d.LastSymbol;
        Config.NextFireUtc = null;
        Config.RotationCursor = 0;
        AfterBulkEdit();
        SettingsChanged?.Invoke();
    }

    private void AfterBulkEdit()
    {
        SyncEnabledToConfig();
        Current = ResolveInitialElement();
        Config.LastSymbol = Current?.Symbol;
        Config.NextFireUtc = null;
        _config.RequestSave();
        EnabledChanged?.Invoke();
        ElementChanged?.Invoke(Current);
        SettingsChanged?.Invoke();
    }

    private void SyncEnabledToConfig()
    {
        Config.EnabledSymbols = _assets.Elements.Elements
            .Where(e => _enabled.Contains(e.Symbol)).Select(e => e.Symbol).ToList();
    }

    /// <summary>按顺序推进到下一个已启用元素；只有一个元素时保持不变。</summary>
    public void RotateNext()
    {
        var list = EnabledList();
        if (list.Count == 0) return;
        int start = list.FindIndex(e => Current is not null && e.Symbol == Current.Symbol);
        int next = start < 0 ? 0 : (start + 1) % list.Count;
        Config.RotationCursor = next;
        ShowElement(list[next]);
    }

    public void ShowElement(Element? element)
    {
        Current = element;
        Config.LastSymbol = element?.Symbol;
        _config.RequestSave();
        ElementChanged?.Invoke(element);
    }

    public void SetRotation(string id)
    {
        if (_assets.Intervals.All(i => i.Id != id)) return;
        Config.Rotation = id;
        Config.NextFireUtc = null;      // 让 RotationService 立即重新排程
        SettingsChanged?.Invoke();
        _config.RequestSave();
    }

    public void SetPaused(bool value)
    {
        Config.Paused = value;
        Config.NextFireUtc = null;
        SettingsChanged?.Invoke();
        _config.RequestSave();
    }

    public void SetAutoStart(bool value)
    {
        Config.AutoStart = value;
        _config.RequestSave();
    }

    public void SetClickThrough(bool value)
    {
        Config.ClickThrough = value;
        SettingsChanged?.Invoke();
        _config.RequestSave();
    }

    public void SetOpacity(double value)
    {
        Config.Opacity = double.IsFinite(value) ? Math.Clamp(value, 0.1, 1.0) : 1.0;
        SettingsChanged?.Invoke();
        _config.RequestSave();
    }

    public void SetAnchor(string anchor)
    {
        Config.Position.Anchor = anchor;
        SettingsChanged?.Invoke();
        _config.RequestSave();
    }

    public void SetBlockSize(int size)
    {
        Config.BlockSize = Math.Clamp(size, 80, 320);
        SettingsChanged?.Invoke();
        _config.RequestSave();
    }

    /// <summary>供 RotationService 在重新排程后通知 UI 刷新"下一次切换"。</summary>
    public void NotifyScheduleChanged() => SettingsChanged?.Invoke();
}
