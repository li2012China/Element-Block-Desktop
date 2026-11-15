using Windows.ApplicationModel;

namespace ElementBlocks.Desktop.Services;

/// <summary>开机自启：MSIX 走 StartupTask（需用户确认），散包部署回退 HKCU Run 键。</summary>
public static class StartupService
{
    private const string TaskId = "ElementBlocksStartup";
    private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "ElementBlocksDesktop";

    public static async Task<bool> ApplyAsync(bool enable)
    {
        try
        {
            var task = await StartupTask.GetAsync(TaskId);
            if (!enable)
            {
                task.Disable();
                return false;
            }
            var state = await task.RequestEnableAsync();
            return state is StartupTaskState.Enabled or StartupTaskState.EnabledByPolicy;
        }
        catch
        {
            // 未打包（WindowsPackageType=None）时 StartupTask 不可用
            return SetRunKey(enable);
        }
    }

    private static bool SetRunKey(bool enable)
    {
        try
        {
            using var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: true);
            if (key is null) return false;
            if (enable) key.SetValue(ValueName, $"\"{Environment.ProcessPath}\"");
            else key.DeleteValue(ValueName, throwOnMissingValue: false);
            return true;
        }
        catch { return false; }
    }
}
