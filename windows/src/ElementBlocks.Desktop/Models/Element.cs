using System.Text.Json.Serialization;

namespace ElementBlocks.Desktop.Models;

/// <summary>一个元素。字段与 shared/elements.json 一一对应。</summary>
public sealed class Element
{
    [JsonPropertyName("number")] public int Number { get; set; }
    [JsonPropertyName("symbol")] public string Symbol { get; set; } = "";
    [JsonPropertyName("nameEn")] public string NameEn { get; set; } = "";
    [JsonPropertyName("nameZh")] public string NameZh { get; set; } = "";
    [JsonPropertyName("pinyin")] public string? Pinyin { get; set; }
    [JsonPropertyName("mass")] public string Mass { get; set; } = "";
    [JsonPropertyName("massBracketed")] public bool MassBracketed { get; set; }
    [JsonPropertyName("category")] public string Category { get; set; } = "";
    [JsonPropertyName("categoryLabel")] public string CategoryLabel { get; set; } = "";
    [JsonPropertyName("radioactive")] public bool Radioactive { get; set; }
    [JsonPropertyName("synthetic")] public bool Synthetic { get; set; }
    [JsonPropertyName("row")] public int Row { get; set; }
    [JsonPropertyName("column")] public int Column { get; set; }
    [JsonPropertyName("period")] public int Period { get; set; }
    [JsonPropertyName("group")] public int? Group { get; set; }

    public string Tooltip =>
        $"{Number}  {Symbol}  {NameZh}{(Synthetic ? "*" : "")} / {NameEn}\n" +
        $"相对原子质量 {Mass}" + (MassBracketed ? "（最长半衰期同位素质量数）" : "") +
        $"\n{categoryName()} · 第 {Period} 周期" + (Group is int g ? $" · 第 {g} 族" : " · f 区") +
        (Radioactive ? "\n放射性元素（红色序号）" : "");

    private string categoryName() => CategoryLabel;
}

public sealed class Placeholder
{
    [JsonPropertyName("row")] public int Row { get; set; }
    [JsonPropertyName("column")] public int Column { get; set; }
    [JsonPropertyName("label")] public string Label { get; set; } = "";
    [JsonPropertyName("subLabel")] public string SubLabel { get; set; } = "";
}

public sealed class PeriodicTableLayout
{
    [JsonPropertyName("columns")] public int Columns { get; set; } = 18;
    [JsonPropertyName("rows")] public int Rows { get; set; } = 10;
    [JsonPropertyName("spacerRow")] public int SpacerRow { get; set; } = 8;
    [JsonPropertyName("placeholders")] public List<Placeholder> Placeholders { get; set; } = [];
    [JsonPropertyName("groupLabels")] public Dictionary<string, string> GroupLabels { get; set; } = [];
    [JsonPropertyName("periodLabels")] public Dictionary<string, string> PeriodLabels { get; set; } = [];
}

public sealed class ElementsDocument
{
    [JsonPropertyName("$schemaVersion")] public int SchemaVersion { get; set; }
    [JsonPropertyName("layout")] public PeriodicTableLayout Layout { get; set; } = new();
    [JsonPropertyName("elements")] public List<Element> Elements { get; set; } = [];
}
