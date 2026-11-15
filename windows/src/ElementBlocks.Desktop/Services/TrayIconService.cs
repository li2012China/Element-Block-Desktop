using System.Runtime.InteropServices;
using ElementBlocks.Desktop.Interop;

namespace ElementBlocks.Desktop.Services;

/// <summary>
/// Windows 托盘：WinUI3 / Windows App SDK 至今没有官方 TrayIcon 控件，
/// 所以这里用 Shell_NotifyIconW + comctl32 的窗口子类化接收回调消息。
/// ICON 消息投递到常驻窗口的 HWND，不额外创建隐藏窗口（该窗口本来就是 TOOLWINDOW）。
/// Explorer 重启时会广播 "TaskbarCreated"，收到后必须重新添加图标。
/// </summary>
public sealed class TrayIconService : IDisposable
{
    private const int IconId = 1;
    private const int WM_DISPLAYCHANGE = 0x007E;
    private const uint SubclassId = 0x454C424B; // "ELBK"

    private readonly IntPtr _hWnd;
    private readonly string _iconPath;
    private readonly Win32.SubclassProc _subclass;   // 必须保活，否则 GC 后回调崩溃
    private readonly uint _taskbarCreated;
    private readonly Func<bool> _isPaused;
    private readonly Func<bool> _isAutoStart;

    private IntPtr _hIcon;
    private bool _added;
    private bool _disposed;

    public event Action? LeftClick;
    public event Action? OpenSettings;
    public event Action? NextElement;
    public event Action<bool>? SetPaused;
    public event Action<bool>? SetAutoStart;
    public event Action? Exit;
    public event Action? DisplayChanged;

    public TrayIconService(IntPtr hWnd, string iconPath, Func<bool> isPaused, Func<bool> isAutoStart)
    {
        _hWnd = hWnd;
        _iconPath = iconPath;
        _isPaused = isPaused;
        _isAutoStart = isAutoStart;
        _subclass = SubclassWndProc;
        _taskbarCreated = Win32.RegisterWindowMessageW("TaskbarCreated");

        Win32.SetWindowSubclass(hWnd, _subclass, new UIntPtr(SubclassId), IntPtr.Zero);
        AddIcon();
    }

    private void AddIcon()
    {
        if (_hIcon == IntPtr.Zero && File.Exists(_iconPath))
            _hIcon = Win32.LoadImageW(IntPtr.Zero, _iconPath, Win32.IMAGE_ICON,
                                      0, 0, Win32.LR_LOADFROMFILE | Win32.LR_DEFAULTSIZE);

        var data = new Win32.NOTIFYICONDATAW
        {
            cbSize = Marshal.SizeOf<Win32.NOTIFYICONDATAW>(),
            hWnd = _hWnd,
            uID = IconId,
            uFlags = Win32.NIF_MESSAGE | Win32.NIF_ICON | Win32.NIF_TIP,
            uCallbackMessage = Win32.WM_TRAY,
            hIcon = _hIcon,
            szTip = "Element Blocks Desktop",
        };
        _added = Win32.Shell_NotifyIconW(_added ? Win32.NIM_MODIFY : Win32.NIM_ADD, ref data);
    }

    public void SetTooltip(string text)
    {
        if (!_added) return;
        var data = new Win32.NOTIFYICONDATAW
        {
            cbSize = Marshal.SizeOf<Win32.NOTIFYICONDATAW>(),
            hWnd = _hWnd,
            uID = IconId,
            uFlags = Win32.NIF_TIP,
            szTip = text.Length > 127 ? text[..127] : text,
        };
        Win32.Shell_NotifyIconW(Win32.NIM_MODIFY, ref data);
    }

    private IntPtr SubclassWndProc(IntPtr hWnd, uint uMsg, IntPtr wParam, IntPtr lParam,
                                   UIntPtr uIdSubclass, IntPtr dwRefData)
    {
        if (uMsg == _taskbarCreated)
        {
            _added = false;
            AddIcon();
        }
        else if (uMsg == Win32.WM_TRAY)
        {
            int mouse = Win32.LowWord(lParam);
            if (mouse == Win32.WM_LBUTTONUP) LeftClick?.Invoke();
            else if (mouse == Win32.WM_RBUTTONUP) ShowContextMenu(hWnd);
        }
        else if (uMsg == WM_DISPLAYCHANGE)
        {
            DisplayChanged?.Invoke();
        }
        return Win32.DefSubclassProc(hWnd, uMsg, wParam, lParam);
    }

    private void ShowContextMenu(IntPtr hWnd)
    {
        IntPtr menu = Win32.CreatePopupMenu();
        if (menu == IntPtr.Zero) return;
        try
        {
            Append(menu, 1, "打开设置…", false);
            Append(menu, 2, "立即切换下一个元素", false);
            Win32.AppendMenuW(menu, Win32.MF_SEPARATOR, UIntPtr.Zero, null);
            Append(menu, 3, "暂停轮换", _isPaused());
            Append(menu, 4, "开机自启", _isAutoStart());
            Win32.AppendMenuW(menu, Win32.MF_SEPARATOR, UIntPtr.Zero, null);
            Append(menu, 5, "退出", false);

            Win32.GetCursorPos(out var pt);
            Win32.SetForegroundWindow(hWnd);
            int cmd = Win32.TrackPopupMenu(menu,
                Win32.TPM_RETURNCMD | Win32.TPM_RIGHTBUTTON | Win32.TPM_NONOTIFY,
                pt.X, pt.Y, 0, hWnd, IntPtr.Zero);

            switch (cmd)
            {
                case 1: OpenSettings?.Invoke(); break;
                case 2: NextElement?.Invoke(); break;
                case 3: SetPaused?.Invoke(!_isPaused()); break;
                case 4: SetAutoStart?.Invoke(!_isAutoStart()); break;
                case 5: Exit?.Invoke(); break;
            }
        }
        finally
        {
            Win32.DestroyMenu(menu);
        }
    }

    private static void Append(IntPtr menu, int id, string text, bool checkedState)
    {
        uint flags = Win32.MF_STRING | (checkedState ? Win32.MF_CHECKED : Win32.MF_UNCHECKED);
        Win32.AppendMenuW(menu, flags, new UIntPtr((uint)id), text);
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        if (_added)
        {
            var data = new Win32.NOTIFYICONDATAW
            {
                cbSize = Marshal.SizeOf<Win32.NOTIFYICONDATAW>(),
                hWnd = _hWnd,
                uID = IconId,
            };
            Win32.Shell_NotifyIconW(Win32.NIM_DELETE, ref data);
        }
        Win32.RemoveWindowSubclass(_hWnd, _subclass, new UIntPtr(SubclassId));
        if (_hIcon != IntPtr.Zero) Win32.DestroyIcon(_hIcon);
        _hIcon = IntPtr.Zero;
        GC.KeepAlive(_subclass);
    }
}
