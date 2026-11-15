#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机验证方块窗口"置底（bottom-most）"行为（Windows 1.0.1.3+）。

用法：
    python tools/verify_bottommost.py <方块进程PID>
    （PID 由 Get-Process -Name "ElementBlocks.Desktop" 查得）

验证项：
  1. 初始 z 序：方块位于所有可见应用窗口之下（其下仅剩桌面壳层）
  2. 扩展样式：无 WS_EX_TOPMOST，有 WS_EX_NOACTIVATE / WS_EX_TOOLWINDOW
  3. 真实鼠标点击方块中心 → z 序不变、方块不成为前台
  4. 外部强制上浮（SetWindowPos HWND_TOP / SetForegroundWindow）→ 仍被钉回底层
  5. 普通窗口与其重叠 → 方块仍可见（只是被视觉覆盖，不被隐藏）
  6. 最大化该窗口 → 覆盖轮询 SW_HIDE；还原 → 方块恢复可见且仍在底层
  7. 清理测试窗口
"""
import ctypes
import sys
import time
from ctypes import c_ssize_t, wintypes

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_OVERLAPPEDWINDOW = 0x00CF0000
SW_HIDE, SW_SHOWNORMAL, SW_MAXIMIZE, SW_RESTORE = 0, 1, 3, 9
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
DWMWA_CLOAKED = 13
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                 "SHELLDLL_DefView", "Button", "Xaml_Window", "Windows.UI.Composition.DesktopWindowContentBridge"}

user32.SetProcessDPIAware()
user32.SetProcessDPIAware.restype = ctypes.c_bool

WNDPROC = ctypes.WINFUNCTYPE(c_ssize_t, wintypes.HWND, ctypes.c_uint,
                             wintypes.WPARAM, wintypes.LPARAM)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.DefWindowProcW.restype = c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.DestroyWindow.argtypes = [wintypes.HWND]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("style", ctypes.c_uint),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HANDLE),
                ("hIcon", wintypes.HANDLE), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HANDLE)]


def z_list():
    """EnumWindows 自顶向下给出 Z 序。"""
    order = []

    @EnumWindowsProc
    def cb(h, _):
        order.append(h)
        return True

    user32.EnumWindows(cb, 0)
    return order


def hwnd_pid(h):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value


def class_name(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, buf, 256)
    return buf.value


def rect(h):
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def visible(h):
    return bool(user32.IsWindowVisible(h))


def cloaked(h):
    v = ctypes.c_int()
    if dwmapi.DwmGetWindowAttribute(h, DWMWA_CLOAKED, ctypes.byref(v), 4) == 0:
        return v.value != 0
    return False


def exstyle(h):
    return user32.GetWindowLongW(h, GWL_EXSTYLE) & 0xFFFFFFFF


def widget_hwnd(pid):
    cands = [h for h in z_list()
             if hwnd_pid(h) == pid and visible(h) and user32.GetAncestor(h, 3) == h]
    return cands[0] if cands else None


def z_index(target, order):
    for i, h in enumerate(order):
        if h == target:
            return i
    return -1


def visible_app_windows_below(widget, order, skip):
    """可见、未 cloak、非壳层、非测试窗口的应用窗口若出现在方块之下，列出。"""
    below = []
    seen_widget = False
    for h in order:
        if h == widget:
            seen_widget = True
            continue
        if not seen_widget or h in skip:
            continue
        if visible(h) and not cloaked(h) and class_name(h) not in SHELL_CLASSES:
            below.append((h, class_name(h)))
    return below


def bring_foreground(h):
    """ALT 键解锁系统前台锁后把窗口带前台。"""
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(h)


def make_test_window(x, y, w, h, title, cls="EBDTestWin", hinst=None):
    hinst = hinst or ctypes.windll.kernel32.GetModuleHandleW(None)
    proc = WNDPROC(lambda hh, m, wp, lp:
                   user32.DefWindowProcW(hh, m, wp, lp))
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = proc
    wc.hInstance = hinst
    wc.lpszClassName = cls
    ctypes.windll.user32.RegisterClassExW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(0, cls, title, WS_OVERLAPPEDWINDOW,
                                  x, y, w, h, None, None, hinst, None)
    user32.ShowWindow(hwnd, SW_SHOWNORMAL)
    user32.UpdateWindow(hwnd)
    return hwnd, proc, wc


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    pid = int(sys.argv[1])
    results = []

    def check(name, ok, detail=""):
        results.append((name, ok))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))

    widget = widget_hwnd(pid)
    if not widget:
        print(f"!! 找不到 PID {pid} 的可见顶层窗口")
        return 2
    print(f"widget hwnd = {widget:#x}, class = {class_name(widget)}")

    # 1) 初始 z 序
    order = z_list()
    below = visible_app_windows_below(widget, order, skip=set())
    check("初始 z 序最底层（其下仅桌面壳层）",
          len(below) == 0,
          f"之下可见应用窗口: {below}" if below else "")

    # 2) 扩展样式
    es = exstyle(widget)
    check("无 TOPMOST 扩展样式", (es & WS_EX_TOPMOST) == 0, f"exstyle={es:#x}")
    check("有 NOACTIVATE（点击不抢焦点）", (es & WS_EX_NOACTIVATE) != 0)
    check("有 TOOLWINDOW（不进任务栏/Alt+Tab）", (es & WS_EX_TOOLWINDOW) != 0)

    # 3) 真实鼠标点击方块中心 → 不上浮、不进前台
    l, t, r, b = rect(widget)
    cx, cy = (l + r) // 2, (t + b) // 2
    idx_before = z_index(widget, z_list())
    fg_before = user32.GetForegroundWindow()
    user32.SetCursorPos(cx, cy)
    time.sleep(0.2)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.6)
    idx_after = z_index(widget, z_list())
    check("点击方块后 z 序不变（不上浮）", idx_before == idx_after,
          f"z index {idx_before} -> {idx_after}")
    fg_after = user32.GetForegroundWindow()
    check("点击方块后不成为前台窗口", fg_after != widget,
          f"foreground {fg_before:#x} -> {fg_after:#x}")

    # 4) 外部强制上浮 → 被钉回底层
    user32.SetWindowPos(widget, 0, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)  # HWND_TOP
    time.sleep(0.3)
    below = visible_app_windows_below(widget, z_list(), skip=set())
    check("SetWindowPos(HWND_TOP) 强制上浮被拦截", len(below) == 0)

    bring_foreground(widget)
    time.sleep(0.5)
    below = visible_app_windows_below(widget, z_list(), skip=set())
    got_focus = user32.GetForegroundWindow() == widget
    check("获得焦点（SetForegroundWindow）后仍在底层",
          len(below) == 0, f"已获得前台={got_focus}")

    # 5/6) 测试窗口：普通重叠不隐藏；最大化才隐藏
    l, t, r, b = rect(widget)
    tw, proc, wc = make_test_window(l + 20, t + 20, (r - l), (b - t), "EBD 置底验证窗口")
    time.sleep(0.5)
    bring_foreground(tw)
    time.sleep(0.5)
    order = z_list()
    iw, it = z_index(widget, order), z_index(tw, order)
    check("普通窗口重叠时位于其下方", iw > it, f"z index widget={iw} test={it}")
    check("普通窗口重叠时方块仍可见（仅视觉覆盖）", visible(widget))

    user32.ShowWindow(tw, SW_MAXIMIZE)
    time.sleep(2.6)   # 覆盖轮询周期 1s
    check("最大化窗口出现后方块被隐藏（SW_HIDE）", not visible(widget))

    user32.ShowWindow(tw, SW_RESTORE)
    time.sleep(2.6)
    check("还原后方块恢复可见", visible(widget))
    below = visible_app_windows_below(widget, z_list(), skip={tw})
    check("还原后方块仍在 z 序底层", len(below) == 0)

    # 7) 清理
    user32.DestroyWindow(tw)
    ctypes.windll.user32.UnregisterClassW(wc.lpszClassName, wc.hInstance)

    failed = [n for n, ok in results if not ok]
    print(f"\n{'全部通过' if not failed else '失败项: ' + '; '.join(failed)}"
          f"（{sum(1 for _, ok in results if ok)}/{len(results)}）")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
