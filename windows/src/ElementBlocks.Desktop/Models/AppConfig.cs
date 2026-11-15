namespace ElementBlocks.Desktop.Models;

/// <summary>
/// config.json 的内存模型。字段名与 shared/config.schema.json 完全一致，
/// 两端（WinUI3 / GTK）读写同一份结构，便于交叉迁移与人工编辑。
/// </summary>
public sealed class AppConfig
{
    public int Version { get; set; } = 1;

    /// <summary>允许参与轮换的元素符号。用符号而不是序号，方便核对与人工编辑。</summary>
    public List<string> EnabledSymbols { get; set; } = [];

    /// <summary>轮换间隔 id，见 intervals.json。默认 never = 从不。</summary>
    public string Rotation { get; set; } = "never";

    public PositionConfig Position { get; set; } = new();

    /// <summary>方块边长（与设备无关像素 / CSS 像素）。</summary>
    public int BlockSize { get; set; } = 132;

    /// <summary>鼠标点击穿透，方块不拦截桌面点击。</summary>
    public bool ClickThrough { get; set; } = true;

    /// <summary>方块整体不透明度，0.1–1.0；实时生效并持久保存。</summary>
    public double Opacity { get; set; } = 1.0;

    public bool AutoStart { get; set; }

    /// <summary>托盘菜单里的"暂停轮换"。</summary>
    public bool Paused { get; set; }

    /// <summary>当前显示的元素。重启后直接恢复，不跳变。</summary>
    public string? LastSymbol { get; set; } = "U";

    /// <summary>下一次轮换的 UTC 时刻；休眠/关机期间不补跑，恢复时最多补一次。</summary>
    public DateTimeOffset? NextFireUtc { get; set; }

    /// <summary>轮换游标：按原子序在已启用集合里顺序推进，避免连续重复。</summary>
    public int RotationCursor { get; set; }

    public static AppConfig CreateDefaults(IEnumerable<string> allSymbols) => new()
    {
        Version = 1,
        EnabledSymbols = allSymbols.ToList(),
        Rotation = "never",
        Position = new PositionConfig { Anchor = "TopRight", OffsetX = 32, OffsetY = 32, MonitorIndex = 0 },
        BlockSize = 132,
        ClickThrough = true,
        Opacity = 1.0,
        AutoStart = false,
        Paused = false,
        LastSymbol = "U",
        NextFireUtc = null,
        RotationCursor = 0,
    };
}

public sealed class PositionConfig
{
    public string Anchor { get; set; } = "TopRight";
    public int OffsetX { get; set; } = 32;
    public int OffsetY { get; set; } = 32;
    public int MonitorIndex { get; set; }
}
