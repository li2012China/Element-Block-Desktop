using System.Text.Json;
using ElementBlocks.Desktop.Models;

namespace ElementBlocks.Desktop.Services;

/// <summary>加载随包发布的 shared/*.json（只读数据契约）。</summary>
public sealed class AssetsService
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    public AppAssets Assets { get; }

    public AssetsService()
    {
        string dir = LocateDataDirectory();
        var elements = Read<ElementsDocument>(Path.Combine(dir, "elements.json"));
        var theme = Read<ThemeDocument>(Path.Combine(dir, "theme.json"));
        var intervals = Read<List<IntervalOption>>(Path.Combine(dir, "intervals.json"));

        if (elements.Elements.Count != 118)
            throw new InvalidDataException($"elements.json 应包含 118 个元素，实际 {elements.Elements.Count}");

        Assets = new AppAssets
        {
            Elements = elements,
            Theme = theme,
            Intervals = intervals,
            BySymbol = elements.Elements.ToDictionary(e => e.Symbol, StringComparer.Ordinal),
        };
    }

    private static T Read<T>(string path) where T : class
    {
        if (!File.Exists(path))
            throw new FileNotFoundException($"缺少随包资源：{path}（请先运行 tools/sync_data.py）", path);
        return JsonSerializer.Deserialize<T>(File.ReadAllText(path, System.Text.Encoding.UTF8), Json)
               ?? throw new InvalidDataException($"无法解析 {path}");
    }

    /// <summary>
    /// MSIX 打包与散包部署都把资源放在可执行文件旁的 Assets/Data。
    /// 开发期如果尚未拷贝，则允许回退到仓库 shared/ 目录。
    /// </summary>
    private static string LocateDataDirectory()
    {
        var candidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "Assets", "Data"),
            Path.Combine(Directory.GetCurrentDirectory(), "Assets", "Data"),
        };
        foreach (var c in candidates)
            if (File.Exists(Path.Combine(c, "elements.json")))
                return c;

        // dev fallback: walk up looking for shared/elements.json
        var probe = new DirectoryInfo(AppContext.BaseDirectory);
        while (probe is not null)
        {
            var shared = Path.Combine(probe.FullName, "shared");
            if (File.Exists(Path.Combine(shared, "elements.json"))) return shared;
            probe = probe.Parent;
        }
        throw new DirectoryNotFoundException("找不到 Assets/Data 或 shared/ 数据目录");
    }
}
