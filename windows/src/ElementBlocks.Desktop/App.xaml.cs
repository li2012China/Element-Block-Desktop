using ElementBlocks.Desktop.Services;
using ElementBlocks.Desktop.Views;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;

namespace ElementBlocks.Desktop;

/// <summary>
/// 进程入口。整个应用只有一个常驻窗口（Widget）+ 一个按需创建的设置窗口，
/// 退出只能从托盘菜单发起；关闭设置窗口不会结束进程。
/// </summary>
public partial class App : Application
{
    private const string MutexName = @"Local\ElementBlocksDesktop.SingleInstance";
    private const string OpenEventName = @"Local\ElementBlocksDesktop.OpenSettings";

    private static Mutex? _mutex;
    private static EventWaitHandle? _openEvent;
    private static CancellationTokenSource? _listenerCts;
    private static DispatcherQueue? _dispatcher;
    private static SettingsWindow? _settings;

    public static AppState State { get; private set; } = null!;
    public static ConfigService Config { get; private set; } = null!;
    public static RotationService? Rotation { get; private set; }
    public static TrayIconService? Tray { get; private set; }
    public static MainWindow? Widget { get; private set; }

    public App()
    {
        InitializeComponent();
        // 桌面小组件不应因单次未处理异常直接退出；记录完整异常栈到本地文件，便于定位崩溃根因。
        UnhandledException += OnUnhandledException;
    }

    private void OnUnhandledException(object sender, Microsoft.UI.Xaml.UnhandledExceptionEventArgs e)
    {
        try
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ElementBlocksDesktop");
            Directory.CreateDirectory(dir);
            var sb = new System.Text.StringBuilder();
            sb.AppendLine($"[{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss}] " +
                          $"{e.Exception.GetType().FullName}: {e.Message}");
            sb.AppendLine(e.Exception.StackTrace ?? "(no stack)");
            if (e.Exception.InnerException is not null)
                sb.AppendLine("Inner: " + e.Exception.InnerException);
            File.AppendAllText(Path.Combine(dir, "crash.log"), sb.ToString());
        }
        catch { /* 记录失败不影响主流程 */ }
        e.Handled = true;   // 不让小组件崩溃退出，记录后继续运行
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _dispatcher = DispatcherQueue.GetForCurrentThread();

        // 单实例：第二次启动只把已有进程的设置窗口叫出来，避免出现第二个方块
        _mutex = new Mutex(initiallyOwned: true, MutexName, out bool createdNew);
        if (!createdNew)
        {
            try
            {
                using var ev = EventWaitHandle.OpenExisting(OpenEventName);
                ev.Set();
            }
            catch { /* 首个进程已退出，直接结束 */ }
            Environment.Exit(0);
            return;
        }

        _openEvent = new EventWaitHandle(false, EventResetMode.AutoReset, OpenEventName);
        _listenerCts = new CancellationTokenSource();
        _ = Task.Run(() => ListenForSecondInstance(_listenerCts.Token));

        var assets = new AssetsService().Assets;
        Config = new ConfigService(assets);
        State = new AppState(assets, Config);
        Rotation = new RotationService(State);

        // 诊断模式：存在 selftest.flag 时，不做正常启动，而是逐个导航设置页并记录结果后退出。
        // 用途：在用户机器上无交互复现"点击某页崩溃"，把真实托管异常栈落到日志。
        string diagDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "ElementBlocksDesktop");
        if (File.Exists(Path.Combine(diagDir, "selftest.flag")))
        {
            RunSelfTestAndExit(diagDir);
            return;
        }

        Widget = new MainWindow();
        Widget.Activate();
        Widget.AttachToDesktop();

        string iconPath = Path.Combine(AppContext.BaseDirectory, "Assets", "ElementBlocks.ico");
        Tray = new TrayIconService(Widget.Handle, iconPath,
                                   () => State.Config.Paused,
                                   () => State.Config.AutoStart);
        WireTray();
        UpdateTooltip();
        State.ElementChanged += _ => UpdateTooltip();
    }

    /// <summary>
    /// 诊断模式主流程：创建设置窗口 → 依次导航每页 → 等布局/渲染跑完 → 写日志退出。
    /// 崩溃若发生在导航期（构造/事件回调）会被 SelfTestNavigate 捕获；
    /// 若发生在随后的布局期，则由 UnhandledException 记入 crash.log（e.Handled 保证进程不退出）。
    /// </summary>
    private static void RunSelfTestAndExit(string dir)
    {
        var log = new System.Text.StringBuilder();
        void W(string s) => log.AppendLine($"[{DateTimeOffset.Now:HH:mm:ss.fff}] {s}");

        try
        {
            W("selftest start");
            var w = new SettingsWindow();
            W("SettingsWindow ctor: OK (PeriodicTablePage)");
            w.Activate();

            var queue = DispatcherQueue.GetForCurrentThread();
            var timer = queue!.CreateTimer();
            timer.Interval = TimeSpan.FromSeconds(2.5);
            timer.Tick += (_, _) =>
            {
                timer.Stop();
                try
                {
                    W("RotationPage: " + w.SelfTestNavigate(typeof(Views.RotationPage)));
                    W("waiting one more layout pass…");
                    var t2 = queue.CreateTimer();
                    t2.Interval = TimeSpan.FromSeconds(1.5);
                    t2.Tick += (_, _) =>
                    {
                        t2.Stop();
                        W("selftest done (若崩溃发生在布局期，crash.log 里会有记录)");
                        try { File.WriteAllText(Path.Combine(dir, "selftest.log"), log.ToString()); }
                        catch { }
                        Environment.Exit(0);
                    };
                    t2.Start();
                }
                catch (Exception ex)
                {
                    W("selftest fatal: " + ex);
                    try { File.WriteAllText(Path.Combine(dir, "selftest.log"), log.ToString()); } catch { }
                    Environment.Exit(1);
                }
            };
            timer.Start();
        }
        catch (Exception ex)
        {
            W("selftest startup failed: " + ex);
            try { File.WriteAllText(Path.Combine(dir, "selftest.log"), log.ToString()); } catch { }
            Environment.Exit(1);
        }
    }

    private static void WireTray()
    {
        var tray = Tray!;
        tray.LeftClick += ShowSettings;
        tray.OpenSettings += ShowSettings;
        tray.NextElement += () =>
        {
            State.RotateNext();
            Rotation?.RestartCycleAfterManualSwitch();
        };
        tray.SetPaused += paused => State.SetPaused(paused);
        tray.SetAutoStart += async want =>
        {
            bool applied = await StartupService.ApplyAsync(want);
            State.SetAutoStart(applied);
        };
        tray.Exit += Quit;
        tray.DisplayChanged += () =>
        {
            // 分辨率 / 缩放 / 显示器插拔后重新按工作区锚点定位（隐藏态下不动）
            Widget?.RelocateIfVisible();
        };
    }

    private static void ListenForSecondInstance(CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            if (_openEvent!.WaitOne(500))
                _dispatcher?.TryEnqueue(ShowSettings);
        }
    }

    public static void ShowSettings()
    {
        // 方块窗口常驻 Z 序底层（PinToBottom），设置对话框天然在其上方，无需任何临时层级切换。
        if (_settings is null)
        {
            _settings = new SettingsWindow();
            _settings.Closed += (_, _) => { _settings = null; };
        }
        _settings.Activate();
    }

    private static void UpdateTooltip()
    {
        var e = State.Current;
        Tray?.SetTooltip(e is null
            ? "Element Blocks Desktop · 未启用任何元素"
            : $"Element Blocks Desktop · {e.Number} {e.NameZh} {e.Symbol}");
    }

    public static void Quit()
    {
        Rotation?.Dispose();
        Tray?.Dispose();
        Config?.Flush();
        _listenerCts?.Cancel();
        _openEvent?.Dispose();
        try { _mutex?.ReleaseMutex(); } catch { /* ignore */ }
        _mutex?.Dispose();
        _settings?.Close();
        Widget?.Close();
        Environment.Exit(0);
    }
}
