namespace ElementBlocks.Desktop.Services;

/// <summary>
/// 轻量诊断日志：仅当用户目录下存在 trace.flag 时写入 trace.log。
/// 用途：定位"事件在页面 Loaded 之前触发"这类只有真机交互才会出现的问题，
/// 默认关闭、零开销（标志在启动时读一次，正常使用不会产生任何文件）。
/// </summary>
internal static class Diag
{
    private static readonly string Dir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "ElementBlocksDesktop");

    public static readonly bool Enabled = File.Exists(Path.Combine(Dir, "trace.flag"));


    public static void Log(string message)
    {
        if (!Enabled) return;
        try
        {
            File.AppendAllText(Path.Combine(Dir, "trace.log"),
                $"[{DateTimeOffset.Now:HH:mm:ss.fff}] {message}{Environment.NewLine}");
        }
        catch { /* 诊断失败不影响主流程 */ }
    }
}
