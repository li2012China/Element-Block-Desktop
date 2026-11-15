using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using WinRT.Interop;

namespace ElementBlocks.Desktop.Views;

/// <summary>托盘左键打开的配置窗口；侧边栏用 WinUI3 NavigationView。</summary>
public sealed partial class SettingsWindow : Window
{
    public SettingsWindow()
    {
        InitializeComponent();

        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        SystemBackdrop = new MicaBackdrop();

        AppWindow.Resize(new Windows.Graphics.SizeInt32(1160, 780));
        if (AppWindow.Presenter is OverlappedPresenter p)
        {
            p.IsMaximizable = false;
            p.IsResizable = true;
        }

        RefreshStatus();
        VersionText.Text = "v" + AppVersion();
        App.State.EnabledChanged += RefreshStatus;
        ContentFrame.Navigate(typeof(PeriodicTablePage));
        Closed += (_, _) => App.State.EnabledChanged -= RefreshStatus;
    }

    private void RefreshStatus() =>
        StatusText.Text = $"已启用 {App.State.Config.EnabledSymbols.Count} / {App.State.Assets.Elements.Elements.Count}";

    /// <summary>从 MSIX 包清单读取真实版本（散包/开发期回退到程序集版本）。</summary>
    private static string AppVersion()
    {
        try
        {
            var v = Windows.ApplicationModel.Package.Current.Id.Version;
            return $"{v.Major}.{v.Minor}.{v.Build}";
        }
        catch
        {
            var a = typeof(SettingsWindow).Assembly.GetName().Version;
            return a is null ? "1.0" : $"{a.Major}.{a.Minor}.{a.Build}";
        }
    }

    private void Nav_SelectionChanged(NavigationView sender,
                                      NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItem is not NavigationViewItem item) return;
        try
        {
            switch (item.Tag as string)
            {
                case "Rotation": ContentFrame.Navigate(typeof(RotationPage)); break;
                default: ContentFrame.Navigate(typeof(PeriodicTablePage)); break;
            }
        }
        catch (Exception ex)
        {
            // 导航失败不应让整个程序崩溃；记录后保留在上一页。
            try
            {
                var dir = System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "ElementBlocksDesktop");
                System.IO.Directory.CreateDirectory(dir);
                var sb = new System.Text.StringBuilder();
                sb.AppendLine($"[{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss}] [Navigation] " +
                              $"{ex.GetType().FullName}: {ex.Message}");
                sb.AppendLine(ex.StackTrace ?? "(no stack)");
                System.IO.File.AppendAllText(System.IO.Path.Combine(dir, "crash.log"), sb.ToString());
            }
            catch { /* ignore */ }
        }
    }

    public IntPtr Handle => WindowNative.GetWindowHandle(this);

    /// <summary>
    /// 自检用：导航到指定页面并返回结果（"OK" 或异常的完整描述）。
    /// 供 App 的诊断模式在无 GUI 交互的情况下复现导航期崩溃。
    /// </summary>
    public string SelfTestNavigate(Type page)
    {
        try
        {
            ContentFrame.Navigate(page);
            return "OK (" + page.Name + ")";
        }
        catch (Exception ex)
        {
            var sb = new System.Text.StringBuilder();
            for (Exception? e = ex; e is not null; e = e.InnerException)
                sb.AppendLine($"{e.GetType().FullName}: {e.Message}");
            sb.AppendLine(ex.StackTrace);
            return "EXCEPTION\n" + sb;
        }
    }
}
