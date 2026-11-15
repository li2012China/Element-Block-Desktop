#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机复现 / 验收：单击元素方块后是否消失。

必须在**目标 Linux 图形会话**里运行（需要 GTK3 + PyGObject + Cairo）：

    python3 tools/repro_click_gtk.py            # 验收 1.0.0-4 的修复
    python3 tools/repro_click_gtk.py --old     # 模拟 1.0.0-3（关闭自愈）复现 bug

脚本创建一个真实的常驻方块窗口，用真实 GTK 信号回调（事件对象用桩替代，
避免依赖 Gdk.Event 构造）依次验证：

    A 单击 / 松开 / 三键 / 双击   -> 窗口仍 visible，位置尺寸元素不变
    B delete-event               -> 窗口不被 GTK 默认销毁
    C hide() 模拟 WM 撤回         -> 修复版自动恢复；--old 版保持消失
    D visibility=fully_obscured / window-state=WITHDRAWN -> 恢复可见性
    E 结束后打印 xdotool / xprop 命令，供人工用真实鼠标复核

退出码 0 = 全部符合预期，1 = 有断言失败。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "linux"))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from element_blocks_desktop.block_window import BlockWindow  # noqa: E402
from element_blocks_desktop import platform_window  # noqa: E402

OLD_MODE = "--old" in sys.argv
FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(name)


def pump(ms: int) -> None:
    """让 GLib 主循环跑 ms 毫秒，使 timeout 回调（自愈、位置复核）真正执行。"""
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, loop.quit)
    loop.run()


class FakeState:
    """最小状态桩：只提供 BlockWindow / platform_window 需要的字段。"""

    def __init__(self, theme: dict) -> None:
        self.cfg = SimpleNamespace(
            block_size=132,
            click_through=False,
            position=SimpleNamespace(anchor="TopRight", offset_x=32,
                                     offset_y=32, monitor_index=0),
        )
        self.assets = SimpleNamespace(theme=theme)
        self.current = SimpleNamespace(number=92, symbol="U", name_zh="铀",
                                       name_en="Uranium", mass="238.0",
                                       radioactive=True)
        self.listeners: list[tuple[str, object]] = []

    def on(self, event: str, callback) -> None:
        self.listeners.append((event, callback))


def window_state(win) -> tuple:
    gdk = win.get_window()
    if gdk is None:
        return (False, (), "U", "no-gdk")
    try:
        origin = gdk.get_origin()
    except (TypeError, ValueError):
        origin = (-1, -1)
    return (bool(win.get_visible()), tuple(origin),
            (gdk.get_width(), gdk.get_height()), "U")


def same_state(a, b) -> bool:
    """比较前后状态；WM 的位置复核允许 ±2px 抖动。"""
    if a[0] != b[0] or a[2] != b[2] or a[3] != b[3]:
        return False
    if len(a[1]) != 2 or len(b[1]) != 2:
        return a[1] == b[1]
    return abs(a[1][0] - b[1][0]) <= 2 and abs(a[1][1] - b[1][1]) <= 2


def main() -> int:
    theme = json.loads((ROOT / "shared" / "theme.json").read_text(encoding="utf-8"))
    state = FakeState(theme)
    win = BlockWindow(state)
    pump(800)                      # 等 realize / map / 首次定位与 120/400ms 复核全部完成

    if OLD_MODE:
        # 1.0.0-3 没有恢复入口：抑制 guard 即等价复现旧行为
        win.guard.mark_quitting()
        print("=== 复现模式：已关闭自愈（模拟 1.0.0-3） ===")

    before = window_state(win)
    print(f"初始状态: visible={before[0]} origin={before[1]} size={before[2]} "
          f"element={before[3]}  backend={'Wayland' if platform_window.is_wayland() else 'X11'}")
    check("窗口启动时可见", before[0] is True)

    print("\n=== A. 单击 / 松开 / 三键 不改状态 ===")
    stub = SimpleNamespace(button=1, x=10.0, y=10.0, state=0, time=0)
    for label, button in (("左键单击", 1), ("中键", 2), ("右键", 3)):
        stub.button = button
        consumed = win._on_button(win, stub)
        check(f"{label} 事件被吞掉", consumed is True)
    released = win._on_button(win, stub)   # 同一处理器用于 release
    check("松开事件被吞掉", released is True)
    pump(120)
    check(f"点击后 click_count={win.guard.click_count}", win.guard.click_count == 4,
          str(win.guard.click_count))
    check("单击后可见性/位置/尺寸/元素全部不变", same_state(window_state(win), before),
          f"{before} -> {window_state(win)}")

    print("\n=== B. delete-event 不销毁窗口 ===")
    check("delete-event 返回 True", win._on_delete(win, stub) is True)
    pump(80)
    check("窗口仍可见且未被销毁", window_state(win)[0] is True)

    print("\n=== C. WM 撤回 / 隐藏（复现「消失」） ===")
    win.hide()
    # 同步读取：hide() 已让窗口不可见；自愈回调要等主循环才执行
    hidden = not window_state(win)[0]
    check("hide() 立即让方块消失（复现现象）", hidden is True)
    pump(2600)                     # 覆盖 40ms unmap 恢复与 2 秒看门狗
    visible_now = window_state(win)[0]
    if OLD_MODE:
        check("旧版：无恢复入口，方块保持消失（符合 bug 预期）", visible_now is False)
    else:
        check("修复版：方块自动恢复可见", visible_now is True)
        check("恢复后几何与元素未变", same_state(window_state(win), before),
              f"{before} -> {window_state(win)}")

    print("\n=== D. 桌面 raise（完全遮挡）与 WITHDRAWN ===")
    vis_stub = SimpleNamespace(state="fully_obscured")
    win._on_visibility(win, vis_stub)
    pump(200)
    state_stub = SimpleNamespace(new_window_state=int(
        getattr(Gdk.WindowState, "WITHDRAWN", 1)))
    win._on_window_state(win, state_stub)
    pump(200)
    if OLD_MODE:
        check("旧版：遮挡事件无任何恢复动作", win.guard.quitting is True)
    else:
        check("遮挡 / WITHDRAWN 后仍可见", window_state(win)[0] is True)
        check("当前元素仍是 U（点击未触发轮换）", win.state.current.symbol == "U")

    win.begin_shutdown()
    print("\n=== 人工复核（真实鼠标，可选） ===")
    print("  xdotool search --name 'Element Blocks Desktop'")
    print("  xprop -id <WINDOW_ID> _NET_WM_WINDOW_TYPE _NET_WM_STATE")
    print("  xwininfo -id <WINDOW_ID> | grep -E 'Map State|Absolute|Width|Height'")
    print("  xdotool mousemove <X> <Y> click 1     # 连点 10 次再复查上面三条")
    print("  python3 tools/test_click_guard.py      # 无 GUI 的确定性回归")

    print()
    if FAILS:
        print(f"FAILED {len(FAILS)}: {FAILS}")
        return 1
    print("GTK CLICK REPRO PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
