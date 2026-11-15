using System.Text.Json.Serialization;

namespace ElementBlocks.Desktop.Models;

public sealed class CategoryStyle
{
    [JsonPropertyName("fill")] public string Fill { get; set; } = "#EFE3C0";
    [JsonPropertyName("text")] public string Text { get; set; } = "#2B2A28";
    [JsonPropertyName("border")] public string Border { get; set; } = "#C9B98F";
}

public sealed class TileTheme
{
    [JsonPropertyName("background")] public string Background { get; set; } = "#EFE3C0";
    [JsonPropertyName("foreground")] public string Foreground { get; set; } = "#2B2A28";
    [JsonPropertyName("accent")] public string Accent { get; set; } = "#B23A2E";
    [JsonPropertyName("border")] public string Border { get; set; } = "#8C7B55";
    [JsonPropertyName("borderWidth")] public double BorderWidth { get; set; } = 1;
    [JsonPropertyName("cornerRadius")] public double CornerRadius { get; set; } = 2;
    [JsonPropertyName("disabledOpacity")] public double DisabledOpacity { get; set; } = 0.32;
    [JsonPropertyName("fontNumber")] public double FontNumber { get; set; } = 15;
    [JsonPropertyName("fontSymbol")] public double FontSymbol { get; set; } = 17;
    [JsonPropertyName("fontNameZh")] public double FontNameZh { get; set; } = 46;
    [JsonPropertyName("fontNameEn")] public double FontNameEn { get; set; } = 14;
    [JsonPropertyName("fontMass")] public double FontMass { get; set; } = 15;
}

public sealed class ThemeDocument
{
    [JsonPropertyName("tile")] public TileTheme Tile { get; set; } = new();
    [JsonPropertyName("categories")] public Dictionary<string, CategoryStyle> Categories { get; set; } = [];
}

public sealed class IntervalOption
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("label")] public string Label { get; set; } = "";
    [JsonPropertyName("minutes")] public int Minutes { get; set; }
    [JsonPropertyName("description")] public string Description { get; set; } = "";
}

/// <summary>内存中的只读资源集合：元素数据 + 主题 + 轮换间隔。</summary>
public sealed class AppAssets
{
    public required ElementsDocument Elements { get; init; }
    public required ThemeDocument Theme { get; init; }
    public required List<IntervalOption> Intervals { get; init; }

    public Dictionary<string, Element> BySymbol { get; init; } = new(StringComparer.Ordinal);

    public IntervalOption Interval(string id) =>
        Intervals.FirstOrDefault(i => i.Id == id) ?? Intervals[0];

    public CategoryStyle Style(string category) =>
        Theme.Categories.TryGetValue(category, out var s) ? s : new CategoryStyle();
}
