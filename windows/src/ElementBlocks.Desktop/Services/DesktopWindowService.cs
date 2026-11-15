using System.Runtime.InteropServices;
using ElementBlocks.Desktop.Interop;
using ElementBlocks.Desktop.Models;

namespace ElementBlocks.Desktop.Services;

/// <summary>
/// 让 WinUI3 窗口变成"桌面常驻方块"：
///   - WS_EX_TOOLWINDOW + 去掉 WS_EX_APPWINDOW  → 任务栏、Alt+Tab、任务视图都不出现
///   - WS_EX_NOACTIVATE                          → 点击不抢焦点，不影响用户操作别的窗口
///   - HWND_BOTTOM + WM_WINDOWPOSCHANGING 改写    → 位于所有普通窗口之下、壁纸之上；
///     任何"上浮"（点击激活、SetForegroundWindow、他人 SetWindowPos 置顶）都会在
///     生效前被改写回 HWND_BOTTOM，保证方块永远不遮挡其他窗口
///   - 按工作区（_NET 等价物 SPI_GETWORKAREA / MONITORINFO.rcWork）计算锚点位置，
///     避免被任务栏盖住；多显示器按 monitorIndex 定位。
///   - 可选 WS_EX_TRANSPARENT|LAYERED           → 鼠标点击穿透
/// </summary>
public static class DesktopWindowService
{
    public static void Apply(IntPtr hwnd, AppConfig cfg)
    {
        long style = Win32.GetWindowLongPtr(hwnd, Win32.GWL_EXSTYLE).ToInt64();
        style &= ~Win32.WS_EX_APPWINDOW;
        style |= Win32.WS_EX_TOOLWINDOW | Win32.WS_EX_NOACTIVATE;

        // 不透明度 < 1 或点击穿透都需要 WS_EX_LAYERED（启用 alpha 通道）；
        // 仅点击穿透时 alpha 仍取 255（不透明，只是点击穿透）。
        bool layered = cfg.ClickThrough || cfg.Opacity < 1.0;
        if (layered) style |= Win32.WS_EX_LAYERED;
        else style &= ~Win32.WS_EX_LAYERED;

        if (cfg.ClickThrough) style |= Win32.WS_EX_TRANSPARENT;
        else style &= ~Win32.WS_EX_TRANSPARENT;

        Win32.SetWindowLongPtr(hwnd, Win32.GWL_EXSTYLE, new IntPtr(style));

        if (layered)
        {
            byte alpha = (byte)Math.Round(Math.Clamp(cfg.Opacity, 0.1, 1.0) * 255);
            Win32.SetLayeredWindowAttributes(hwnd, 0, alpha, Win32.LWA_ALPHA);
        }

        Reposition(hwnd, cfg);
    }

    public static void Reposition(IntPtr hwnd, AppConfig cfg)
    {
        uint dpi = Win32.GetDpiForWindow(hwnd);
        double scale = dpi == 0 ? 1.0 : dpi / 96.0;
        int size = (int)Math.Round(cfg.BlockSize * scale);   // 物理像素

        var area = GetWorkArea(cfg.Position.MonitorIndex);
        int x, y;
        if (cfg.Position.Anchor == "Custom")
        {
            x = cfg.Position.OffsetX;
            y = cfg.Position.OffsetY;
        }
        else
        {
            bool right = cfg.Position.Anchor.Contains("Right", StringComparison.Ordinal);
            bool bottom = cfg.Position.Anchor.Contains("Bottom", StringComparison.Ordinal);
            x = right ? area.Right - size - cfg.Position.OffsetX : area.Left + cfg.Position.OffsetX;
            y = bottom ? area.Bottom - size - cfg.Position.OffsetY : area.Top + cfg.Position.OffsetY;
        }

        // 防止配置里的极端值把方块推到屏幕外
        x = Math.Clamp(x, area.Left, Math.Max(area.Left, area.Right - size));
        y = Math.Clamp(y, area.Top, Math.Max(area.Top, area.Bottom - size));

        // 每次重定位都显式沉底（同时清除可能残留的 TOPMOST 状态）。
        // 配合 PinToBottom 的 WM_WINDOWPOSCHANGING 拦截，z 顺序在任何路径下都保持最底层。
        Win32.SetWindowPos(hwnd, Win32.HWND_BOTTOM, x, y, size, size,
            Win32.SWP_NOACTIVATE | Win32.SWP_FRAMECHANGED | Win32.SWP_SHOWWINDOW);
    }

    // ---- 置底（bottom-most）------------------------------------------------
    // 与托盘（TrayIconService）同款的 comctl32 子类化，但使用不同的 uIdSubclass。
    // 整个进程只有一个方块窗口，委托保活用静态字段即可。

    private const uint PinSubclassId = 0x5A424F54;   // "ZBOT"
    private static Win32.SubclassProc? _pinProc;
    private static IntPtr _pinHwnd;

    /// <summary>
    /// 把窗口钉在 Z 序最底层：
    ///   1. 立即 SetWindowPos(HWND_BOTTOM) 沉底（若此前是 TOPMOST 会同时降级）；
    ///   2. 子类化拦截 WM_WINDOWPOSCHANGING——所有 z 顺序变更在生效前都会携带
    ///      WINDOWPOS 结构路过该消息，把 hwndInsertAfter 改写为 HWND_BOTTOM，
    ///      即便系统/他人尝试把窗口提到上层（激活、SetForegroundWindow 等），
    ///      实际效果也永远落在最底层。
    /// </summary>
    public static void PinToBottom(IntPtr hwnd)
    {
        if (_pinProc is not null) return;   // 已安装（单窗口应用）
        _pinHwnd = hwnd;
        _pinProc = PinWndProc;
        Win32.SetWindowSubclass(hwnd, _pinProc, new UIntPtr(PinSubclassId), IntPtr.Zero);
        Win32.SetWindowPos(hwnd, Win32.HWND_BOTTOM, 0, 0, 0, 0,
            Win32.SWP_NOMOVE | Win32.SWP_NOSIZE | Win32.SWP_NOACTIVATE);
    }

    /// <summary>窗口销毁前移除子类化，避免回调落到悬空 HWND。</summary>
    public static void UnpinFromBottom(IntPtr hwnd)
    {
        if (_pinProc is null) return;
        Win32.RemoveWindowSubclass(hwnd, _pinProc, new UIntPtr(PinSubclassId));
        _pinProc = null;
        _pinHwnd = IntPtr.Zero;
        GC.KeepAlive(_pinProc);
    }

    private static IntPtr PinWndProc(IntPtr hWnd, uint uMsg, IntPtr wParam, IntPtr lParam,
                                     UIntPtr uIdSubclass, IntPtr dwRefData)
    {
        // 纯移动/尺寸类操作（带 SWP_NOZORDER）本来就不改 z 序，不掺和；
        // 真正要改 z 序的操作一律改写为"沉底"。
        if (uMsg == Win32.WM_WINDOWPOSCHANGING && lParam != IntPtr.Zero)
        {
            var pos = Marshal.PtrToStructure<Win32.WINDOWPOS>(lParam);
            if ((pos.flags & Win32.SWP_NOZORDER) == 0)
            {
                pos.hwndInsertAfter = Win32.HWND_BOTTOM;
                Marshal.StructureToPtr(pos, lParam, fDeleteOld: false);
            }
        }
        return Win32.DefSubclassProc(hWnd, uMsg, wParam, lParam);
    }

    /// <summary>枚举显示器取 rcWork（工作区，已扣除任务栏）。</summary>
    private static Win32.RECT GetWorkArea(int monitorIndex)
    {
        var areas = new List<Win32.RECT>();
        Win32.MonitorEnumProc cb = (hMonitor, _, _, _) =>
        {
            var mi = new Win32.MONITORINFO { cbSize = Marshal.SizeOf<Win32.MONITORINFO>() };
            if (Win32.GetMonitorInfoW(hMonitor, ref mi)) areas.Add(mi.rcWork);
            return true;
        };
        Win32.EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, cb, IntPtr.Zero);
        GC.KeepAlive(cb);

        if (areas.Count > 0) return areas[Math.Clamp(monitorIndex, 0, areas.Count - 1)];

        var rc = new Win32.RECT();
        Win32.SystemParametersInfoW(Win32.SPI_GETWORKAREA, 0, ref rc, 0);
        return rc;
    }

    /// <summary>
    /// 可选：把窗口挂到 Progman / WorkerW 下，成为真正的"桌面层"子窗口
    /// （Win+X 显示桌面时依然可见，不会被"显示桌面"隐藏）。
    /// 这依赖 Explorer 内部窗口结构，属于 best-effort；失败时窗口仍以 BOTTOMMOST
    /// 形态工作。WinUI3 使用 DirectComposition，某些系统上 SetParent 后可能不绘制，
    /// 因此默认不调用，详见 docs/02-tray-and-widget.md。
    /// </summary>
    public static bool TryPinToDesktop(IntPtr hwnd)
    {
        IntPtr progman = Win32.FindWindowW("Progman", null);
        if (progman == IntPtr.Zero) return false;

        // 0x052C 让 Explorer 生成承载桌面图标的 WorkerW
        Win32.SendMessageTimeoutW(progman, 0x052C, IntPtr.Zero, IntPtr.Zero, 0, 1000, out _);

        IntPtr workerW = IntPtr.Zero;
        Win32.EnumWindowsProc cb = (top, _) =>
        {
            IntPtr defView = Win32.FindWindowExW(top, IntPtr.Zero, "SHELLDLL_DefView", null);
            if (defView != IntPtr.Zero)
            {
                workerW = Win32.FindWindowExW(IntPtr.Zero, top, "WorkerW", null);
                return false;
            }
            return true;
        };
        Win32.EnumWindows(cb, IntPtr.Zero);
        GC.KeepAlive(cb);

        if (workerW == IntPtr.Zero) return false;
        return Win32.SetParent(hwnd, workerW) != IntPtr.Zero;
    }

    private static bool RectsOverlap(Win32.RECT a, Win32.RECT b) =>
        a.Left < b.Right && b.Left < a.Right && a.Top < b.Bottom && b.Top < a.Bottom;

    /// <summary>
    /// 前台窗口（或其根窗口）是否处于最大化 / 全屏，并与本方块矩形重叠。
    /// 只检查**前台**窗口：后台挂起的 UWP（设置、照片等）与「Windows 输入体验」等
    /// 系统窗口会保留整屏矩形且 IsWindowVisible=true，若枚举全部窗口会被误判为全屏覆盖，
    /// 表现为"只要有任意未最小化的窗口，方块就隐藏"（1.0.0.5 的真实 Bug）。
    /// </summary>
    public static bool IsCoveredByZoomedOrFullscreen(IntPtr hwnd)
    {
        if (!Win32.GetWindowRect(hwnd, out Win32.RECT self)) return false;
        IntPtr fg = Win32.GetForegroundWindow();
        if (fg == IntPtr.Zero) return false;

        if (Covers(hwnd, fg, self)) return true;
        // 前台可能是 UWP 框架内的子窗口，取根窗口再判一次
        IntPtr root = Win32.GetAncestor(fg, Win32.GA_ROOT);
        return root != IntPtr.Zero && root != fg && Covers(hwnd, root, self);
    }

    private static bool Covers(IntPtr selfHwnd, IntPtr h, Win32.RECT self)
    {
        if (h == selfHwnd) return false;
        if (!Win32.IsWindowVisible(h) || Win32.IsIconic(h)) return false;

        var sb = new System.Text.StringBuilder(256);
        Win32.GetClassNameW(h, sb, sb.Capacity);
        string cls = sb.ToString();
        if (cls is "Progman" or "WorkerW" or "Shell_TrayWnd") return false;
        if (Win32.DwmGetWindowAttribute(h, Win32.DWMWA_CLOAKED, out int cloaked, sizeof(int)) == 0
            && cloaked != 0) return false;

        bool zoomed = Win32.IsZoomed(h);
        Win32.GetWindowRect(h, out Win32.RECT r);
        bool fullscreen = false;
        if (!zoomed)
        {
            IntPtr mon = Win32.MonitorFromWindow(h, 0);
            if (mon != IntPtr.Zero)
            {
                var mi = new Win32.MONITORINFO { cbSize = Marshal.SizeOf<Win32.MONITORINFO>() };
                if (Win32.GetMonitorInfoW(mon, ref mi))
                {
                    var mr = mi.rcMonitor;
                    fullscreen = r.Left <= mr.Left && r.Top <= mr.Top
                                && r.Right >= mr.Right && r.Bottom >= mr.Bottom
                                && (r.Right - r.Left) > 0 && (r.Bottom - r.Top) > 0;
                }
            }
        }

        return (zoomed || fullscreen) && RectsOverlap(self, r);
    }

    /// <summary>"显示桌面"（Win+D）状态：前景窗口是 Progman / WorkerW 即视为桌面可见。</summary>
    public static bool IsDesktopForeground()
    {
        IntPtr fg = Win32.GetForegroundWindow();
        if (fg == IntPtr.Zero) return false;
        var sb = new System.Text.StringBuilder(256);
        Win32.GetClassNameW(fg, sb, sb.Capacity);
        string cls = sb.ToString();
        return cls is "Progman" or "WorkerW";
    }

    /// <summary>
    /// 周期性评估方块可见性（每秒一次），对应 Linux 的 cover_policy.should_be_hidden：
    ///   - 显示桌面（桌面为前台 或 本窗口被最小化）时始终可见；
    ///   - 否则，被最大化/全屏窗口覆盖时隐藏，否则确保可见。
    /// 仅在状态跳变时动手，稳定状态不重复发窗口消息。
    /// hiddenByCover 跨调用记忆"当前是否因覆盖而隐藏"，避免与设置变更 / 重定位互相打架。
    /// </summary>
    public static void EvaluateVisibility(IntPtr hwnd, AppConfig cfg, ref bool hiddenByCover)
    {
        bool desktopShown = IsDesktopForeground() || Win32.IsIconic(hwnd);
        bool covered = !desktopShown && IsCoveredByZoomedOrFullscreen(hwnd);
        bool shouldHide = covered;

        // "显示桌面"（Win+D）会把方块一并最小化：立即恢复，保持桌面小组件常驻可见。
        if (!shouldHide && Win32.IsIconic(hwnd))
        {
            Win32.ShowWindow(hwnd, Win32.SW_RESTORE);
            Apply(hwnd, cfg);
            hiddenByCover = false;
            return;
        }

        if (shouldHide && !hiddenByCover)
        {
            Win32.ShowWindow(hwnd, Win32.SW_HIDE);
            hiddenByCover = true;
        }
        else if (!shouldHide && hiddenByCover)
        {
            // SW_RESTORE 同时应对 SW_HIDE（我们主动隐藏）与 Win+D 的图标化；
            // 本窗口带 WS_EX_NOACTIVATE，恢复时不会抢焦点。
            Win32.ShowWindow(hwnd, Win32.SW_RESTORE);
            Apply(hwnd, cfg);   // 重新套用样式（含不透明度）+ 定位并显示
            hiddenByCover = false;
        }
    }
}
