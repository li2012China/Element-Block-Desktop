using System.Text;
using System.Text.Json;
using ElementBlocks.Desktop.Models;

namespace ElementBlocks.Desktop.Services;

/// <summary>
/// 配置持久化。要点：
///  1) 路径：MSIX 用 ApplicationData.LocalFolder（自动重定向到包容器），
///     散包用 %LOCALAPPDATA%\ElementBlocksDesktop。
///  2) 原子写：同目录临时文件 + Flush(true) + File.Move(overwrite)，避免掉电写坏。
///  3) 防抖：UI 上连续点击元素不会反复落盘。
///  4) 迁移/容错：按 version 补齐缺失字段，坏文件自动备份为 .bak 后回退默认值。
/// </summary>
public sealed class ConfigService : IDisposable
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
    };

    private readonly AppAssets _assets;
    private readonly object _gate = new();
    private readonly Timer _debounce;
    private readonly string _path;
    private bool _disposed;

    public AppConfig Current { get; private set; }

    public event Action<AppConfig>? Changed;

    public string ConfigPath => _path;

    public ConfigService(AppAssets assets)
    {
        _assets = assets;
        var dir = ResolveConfigDirectory();
        Directory.CreateDirectory(dir);
        _path = Path.Combine(dir, "config.json");
        _debounce = new Timer(_ => Flush(), null, Timeout.Infinite, Timeout.Infinite);
        Current = Load();
    }

    private static string ResolveConfigDirectory()
    {
        try
        {
            // MSIX 包：写入 Windows 管理的容器目录，卸载/升级时可迁移。
            return Windows.Storage.ApplicationData.Current.LocalFolder.Path;
        }
        catch
        {
            // 散包 / 开发期：遵循 Windows 惯例写 LocalAppData。
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ElementBlocksDesktop");
        }
    }

    private AppConfig Load()
    {
        if (!File.Exists(_path))
        {
            var fresh = AppConfig.CreateDefaults(_assets.Elements.Elements.Select(e => e.Symbol));
            WriteImmediate(fresh);
            return fresh;
        }

        try
        {
            var text = File.ReadAllText(_path, Encoding.UTF8);
            var cfg = JsonSerializer.Deserialize<AppConfig>(text, Json) ?? throw new JsonException("null");
            return Migrate(cfg);
        }
        catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
        {
            // 损坏时保留现场，不静默丢弃用户数据。
            try { File.Copy(_path, _path + ".bak", overwrite: true); } catch { /* best effort */ }
            var fallback = AppConfig.CreateDefaults(_assets.Elements.Elements.Select(e => e.Symbol));
            WriteImmediate(fallback);
            return fallback;
        }
    }

    /// <summary>按 schema version 做字段补齐与非法值裁剪；以后升级时在此加分支。</summary>
    private AppConfig Migrate(AppConfig cfg)
    {
        var known = new HashSet<string>(_assets.BySymbol.Keys, StringComparer.Ordinal);
        cfg.EnabledSymbols = (cfg.EnabledSymbols ?? [])
            .Where(known.Contains).Distinct(StringComparer.Ordinal).ToList();

        if (_assets.Intervals.All(i => i.Id != cfg.Rotation)) cfg.Rotation = "never";
        cfg.Position ??= new PositionConfig();
        if (cfg.Position.Anchor is not ("TopLeft" or "TopRight" or "BottomLeft" or "BottomRight" or "Custom"))
            cfg.Position.Anchor = "TopRight";
        cfg.Position.MonitorIndex = Math.Max(0, cfg.Position.MonitorIndex);
        cfg.BlockSize = Math.Clamp(cfg.BlockSize, 80, 320);
        cfg.Opacity = double.IsFinite(cfg.Opacity) ? Math.Clamp(cfg.Opacity, 0.1, 1.0) : 1.0;
        cfg.RotationCursor = Math.Max(0, cfg.RotationCursor);
        if (cfg.LastSymbol is not null && !known.Contains(cfg.LastSymbol)) cfg.LastSymbol = null;
        if (cfg.NextFireUtc is { } t && t < DateTimeOffset.UtcNow.AddYears(-2)) cfg.NextFireUtc = null;

        cfg.Version = 1; // v1 → v2 的迁移逻辑以后写在这里
        return cfg;
    }

    /// <summary>UI 修改配置后调用：防抖 400ms 后落盘，并立即广播变更。</summary>
    public void RequestSave()
    {
        lock (_gate) _debounce.Change(400, Timeout.Infinite);
        Changed?.Invoke(Current);
    }

    public void Flush()
    {
        if (_disposed) return;
        lock (_gate)
        {
            _debounce.Change(Timeout.Infinite, Timeout.Infinite);
            WriteImmediate(Current);
        }
    }

    private void WriteImmediate(AppConfig cfg)
    {
        var tmp = _path + ".tmp";
        try
        {
            using (var fs = new FileStream(tmp, FileMode.Create, FileAccess.Write, FileShare.None))
            using (var sw = new StreamWriter(fs, new UTF8Encoding(false)))
            {
                sw.Write(JsonSerializer.Serialize(cfg, Json));
                sw.Flush();
                fs.Flush(flushToDisk: true);
            }
            File.Move(tmp, _path, overwrite: true);
        }
        finally
        {
            if (File.Exists(tmp)) try { File.Delete(tmp); } catch { /* ignore */ }
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        Flush();
        _disposed = true;
        _debounce.Dispose();
    }
}
