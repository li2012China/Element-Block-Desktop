using System;
using ElementBlocks.Desktop.Services;
using Microsoft.UI.Windowing;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using WinRT.Interop;

namespace ElementBlocks.Desktop;

/// <summary>桌面常驻的元素方块窗口。整个进程生命周期内一直存在（不关闭）。</summary>
public sealed partial class MainWindow : Window
{
    public IntPtr Handle { get; }

    /// <summary>当前是否因为"被最大化/全屏窗口覆盖"而被主动隐藏；此时任何设置变更/重定位都不应强行显示它。</summary>
    private bool _hiddenByCover;
    private DispatcherQueueTimer? _coverTimer;

    public MainWindow()
    {
        InitializeComponent();
        Handle = WindowNative.GetWindowHandle(this);

        // 无边框、无标题栏、不可调整大小 —— 由 Win32 层而非 XAML 最终决定层级
        if (AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.SetBorderAndTitleBar(hasBorder: false, hasTitleBar: false);
            presenter.IsResizable = false;
            presenter.IsMaximizable = false;
            presenter.IsMinimizable = false;
            presenter.IsAlwaysOnTop = false;      // 层级由 Win32 层管理（钉入 Z 序底层）
        }

        // Windows App SDK 1.5+ 提供该属性；用反射兼容更早版本，失败时 WS_EX_TOOLWINDOW 已足够
        typeof(AppWindow).GetProperty("IsShownInSwitchers")?.SetValue(AppWindow, false);

        ResizeToConfig();
        Block.SetElement(App.State.Current, App.State.Assets.Theme.Tile);

        App.State.ElementChanged += OnElementChanged;
        App.State.SettingsChanged += OnSettingsChanged;
        Closed += (_, _) =>
        {
            _coverTimer?.Stop();
            DesktopWindowService.UnpinFromBottom(Handle);
            App.State.ElementChanged -= OnElementChanged;
            App.State.SettingsChanged -= OnSettingsChanged;
        };
    }

    public void ResizeToConfig() =>
        AppWindow.Resize(new Windows.Graphics.SizeInt32(
            App.State.Config.BlockSize, App.State.Config.BlockSize));

    /// <summary>首次激活后由 App 调用：此时 HWND 已就绪，可以施加桌面层样式、钉入 Z 序底层并启动覆盖轮询。</summary>
    public void AttachToDesktop()
    {
        DesktopWindowService.Apply(Handle, App.State.Config);
        DesktopWindowService.PinToBottom(Handle);   // Z 序最底层：不遮挡任何窗口，点击/激活也不上浮
        StartCoverWatch();
    }

    /// <summary>每秒评估一次可见性：被最大化/全屏窗口覆盖则隐藏，显示桌面则保持可见。</summary>
    private void StartCoverWatch()
    {
        var queue = DispatcherQueue.GetForCurrentThread();
        if (queue is null) return;
        _coverTimer = queue.CreateTimer();
        _coverTimer.Interval = TimeSpan.FromSeconds(1);
        _coverTimer.Tick += (_, _) =>
            DesktopWindowService.EvaluateVisibility(Handle, App.State.Config, ref _hiddenByCover);
        _coverTimer.Start();
    }

    private void OnElementChanged(Models.Element? element) =>
        Block.SetElement(element, App.State.Assets.Theme.Tile);

    private void OnSettingsChanged()
    {
        // 因覆盖而隐藏期间，不要被设置变更 / 重定位强行显示出来。
        if (_hiddenByCover) return;
        ResizeToConfig();
        DesktopWindowService.Apply(Handle, App.State.Config);
    }

    /// <summary>显示器插拔 / 缩放变化后重定位，但隐藏态下不动，避免破坏覆盖隐藏。</summary>
    public void RelocateIfVisible()
    {
        if (_hiddenByCover) return;
        DesktopWindowService.Reposition(Handle, App.State.Config);
    }
}
