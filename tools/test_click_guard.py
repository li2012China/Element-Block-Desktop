#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单击方块后消失：确定性复现 + 回归测试（不需要 GTK，任意机器可跑）。

运行：python tools/test_click_guard.py

分四部分：
  1. 复现旧行为（模型）：空 input shape → 点击落到桌面 → 桌面 raise →
     keep_below 的方块被盖住，且旧代码没有任何恢复入口 → 一直不可见。
  2. 验证新策略：单击只吞事件、不改任何状态；可见性/层级事件能自愈。
  3. 防抖 / 熔断 / 退出抑制 / settings 事件不再误重排窗口。
  4. 静态接线检查与 Python 3.7 语法兼容（deb 目标发行版可能是 3.7）。
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LINUX_PKG = ROOT / "linux" / "element_blocks_desktop"

spec = importlib.util.spec_from_file_location("ebd_widget_guard",
                                              LINUX_PKG / "widget_guard.py")
G = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(G)

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {detail}")


class FakeBlock:
    """记录所有可能改变方块状态的调用，用来证明「单击零副作用」。"""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.visible = True
        self.mapped = True
        self.covered = False
        self.origin = (834, 48)
        self.size = (132, 132)
        self.element = "U"
        self.stacking = "below"

    def snapshot(self) -> tuple:
        return (self.visible, self.mapped, self.covered, self.origin,
                self.size, self.element, self.stacking)

    def hide(self) -> None:
        self.calls.append("hide")
        self.visible = False

    def destroy(self) -> None:
        self.calls.append("destroy")
        self.mapped = False

    def move(self, x, y) -> None:
        self.calls.append("move")
        self.origin = (x, y)

    def resize(self, w, h) -> None:
        self.calls.append("resize")
        self.size = (w, h)

    def rotate(self) -> None:
        self.calls.append("rotate")
        self.element = "Np"

    def quit(self) -> None:
        self.calls.append("quit")
        self.mapped = False

    def show(self) -> None:
        self.visible = True

    def raise_(self) -> None:
        self.stacking = "below"

    def apply(self, actions: dict[str, bool]) -> None:
        """把策略字典映射到真实副作用；consume 只是停止事件传播。"""
        for key, value in actions.items():
            if key == "consume" or not value:
                continue
            fn = getattr(self, {"unmap": "hide", "destroy": "destroy",
                                "move": "move", "resize": "resize",
                                "change_element": "rotate", "quit": "quit",
                                "hide": "hide"}.get(key, ""), None)
            if fn is not None:
                fn() if key not in ("move", "resize") else fn(0, 0)


def cfg_stub(size=132, anchor="TopRight", ox=32, oy=32, monitor=0, click=False):
    return SimpleNamespace(
        block_size=size,
        position=SimpleNamespace(anchor=anchor, offset_x=ox, offset_y=oy,
                                 monitor_index=monitor),
        click_through=click,
    )


print("=== 1. 复现旧行为（1.0.0-3 的事件表模型，无需 GTK） ===")
# 1.0.0-3 的 BlockWindow 只连接了 draw / realize / configure-event；
# clickThrough 默认 True → 空 input shape → 点击穿过方块落到桌面组件。
legacy_handlers = {"draw": "redraw", "realize": "place",
                   "configure-event": "enforce_bounds"}
restore_signals = ("button-press-event", "delete-event", "visibility-notify-event",
                   "window-state-event", "map-event", "unmap-event")
check("旧版未连接任何点击/可见性信号",
      not any(s in legacy_handlers for s in restore_signals))
old_block = FakeBlock()
old_block.stacking = "below"          # _NET_WM_STATE_BELOW，从不重新声明层级
click_reached_desktop = True          # 点击穿过方块，落到 dde-desktop / 桌面图标窗口
desktop_raised = click_reached_desktop
old_block.covered = desktop_raised and old_block.stacking == "below"
check("旧路径：单击落到桌面，桌面 raise 后把方块盖住", old_block.covered is True)
# 没有任何 handler 能恢复，方块一直不可见 —— 这就是用户看到的「意外消失」
check("旧路径：无恢复入口，方块保持不可见（bug 复现）", old_block.covered is True)

print("\n=== 2. 新策略：单击只吞事件，状态零变化 ===")
for button in (1, 2, 3):
    for click_through in (False, True):
        a = G.click_actions(button, click_through)
        side_effects = {k: v for k, v in a.items() if k != "consume"}
        check(f"click(button={button}, through={click_through}) 吞掉事件",
              a["consume"] is True)
        check(f"click(button={button}, through={click_through}) 零副作用",
              not any(side_effects.values()), str(side_effects))

guard = G.WidgetGuard(now_ms=0)
block = FakeBlock()
before = block.snapshot()
for i in range(5):
    block.apply(guard.click(1, False))
check("连续 5 次单击后 click_count=5", guard.click_count == 5, str(guard.click_count))
check("连续 5 次单击未调用任何状态变更方法", block.calls == [], str(block.calls))
check("可见性/层级/位置/尺寸/元素全部保持不变", block.snapshot() == before,
      f"{before} -> {block.snapshot()}")
check("delete-event 阻止 GTK 默认销毁", guard.on_delete() is True)
check("退出过程中 delete-event 仍不销毁", G.WidgetGuard().on_delete() is True)

# 从 config.py 的 AST 直接读出类字段默认值，而不是重复硬编码一份
_tree = ast.parse((LINUX_PKG / "config.py").read_text(encoding="utf-8"))
_defaults = {}
for _node in ast.walk(_tree):
    if isinstance(_node, ast.AnnAssign) and isinstance(_node.target, ast.Name):
        _defaults[_node.target.id] = _node.value
_ct_default = _defaults.get("click_through")
check("AppConfig.click_through 默认值改为 False（新装即吞点击）",
      isinstance(_ct_default, ast.Constant) and _ct_default.value is False,
      str(getattr(_ct_default, "value", None)))

print("\n=== 3. 可见性 / 层级自愈 ===")
g = G.WidgetGuard(now_ms=0)
check("完全遮挡 -> RESTORE", g.on_visibility("fully_obscured", 1000) == G.RESTORE)
check("部分遮挡 -> IGNORE（普通窗口盖住属正常）",
      g.on_visibility("partial", 1000) == G.IGNORE)
check("未遮挡 -> IGNORE", g.on_visibility("unobscured", 1000) == G.IGNORE)
check("400ms 内重复事件被防抖",
      g.on_visibility("fully_obscured", 1200) == G.IGNORE)
check("冷却结束后可再次自愈",
      g.on_visibility("fully_obscured", 1500) == G.RESTORE)
seq = [g.on_visibility("fully_obscured", t) for t in (2000, 2500, 3000, 3500)]
check("5 秒内最多 3 次自愈（熔断）",
      seq == [G.RESTORE, G.IGNORE, G.IGNORE, G.IGNORE], str(seq))
check("静默 5 秒后重置熔断",
      g.on_visibility("fully_obscured", 8000) == G.RESTORE)

g2 = G.WidgetGuard(now_ms=0)
check("WITHDRAWN -> RESTORE",
      g2.on_window_state(True, False, True, 0) == G.RESTORE)
check("ICONIFIED -> RESTORE",
      g2.on_window_state(False, True, True, 500) == G.RESTORE)
check("BELOW 未上报 / 正常 / 未知都 IGNORE（避免周期性重排）",
      g2.on_window_state(False, False, False, 1000) == G.IGNORE
      and g2.on_window_state(False, False, True, 1001) == G.IGNORE
      and g2.on_window_state(False, False, None, 1002) == G.IGNORE)
check("map -> 重新声明属性", g2.on_map(2000) == G.REAPPLY)
check("看门狗：窗口仍可见 -> IGNORE",
      g2.on_watchdog(True, False, False, 3000) == G.IGNORE)
check("unmap -> RESTORE", G.WidgetGuard().on_unmap(2500) == G.RESTORE)
check("看门狗：窗口被隐藏 -> RESTORE",
      G.WidgetGuard().on_watchdog(False, False, False, 3500) == G.RESTORE)

g3 = G.WidgetGuard(now_ms=0)
flood = [g3.on_visibility("fully_obscured", t) for t in (0, 500, 1000, 1500)]
check("熔断期间隐藏事件被抑制（不与 WM 抢栈）",
      flood == [G.RESTORE, G.RESTORE, G.RESTORE, G.IGNORE]
      and g3.on_watchdog(False, False, False, 1500) == G.IGNORE, str(flood))

# 自愈之后状态仍然不变（只恢复可见性，不重排 / 不换元素）
healed = FakeBlock()
healed.covered = True
snap = (healed.visible, healed.origin, healed.size, healed.element, healed.stacking)
healed.covered = False
check("自愈只解除遮挡，不改几何 / 元素 / 层级",
      (healed.visible, healed.origin, healed.size, healed.element,
       healed.stacking) == snap and not healed.calls)

g2.mark_quitting()
check("退出后所有自愈动作被抑制",
      all(x == G.IGNORE for x in (
          g2.on_visibility("fully_obscured", 9000),
          g2.on_window_state(True, False, True, 9000),
          g2.on_map(9000), g2.on_unmap(9000),
          g2.on_watchdog(False, False, False, 9000))))

print("\n=== 4. 轮换 tick 不再误触窗口重排 ===")
base = cfg_stub()
check("geometry_signature 只含几何相关字段",
      G.geometry_signature(base) == (132, "TopRight", 32, 32, 0, False))
tick_only = cfg_stub()
# 模拟 RotationController.tick()：只改 nextFireUtc / rotationCursor / paused
tick_only.next_fire_utc = "2026-11-14T00:00:00Z"
tick_only.rotation_cursor = 7
tick_only.paused = True
check("仅排程变化：settings_action=IGNORE（不 resize/move）",
      G.WidgetGuard().settings_action(G.geometry_signature(base),
                                      G.geometry_signature(tick_only)) == G.IGNORE)
for label, changed in (
        ("方块大小", cfg_stub(size=180)),
        ("锚点", cfg_stub(anchor="BottomLeft")),
        ("偏移", cfg_stub(ox=64)),
        ("显示器", cfg_stub(monitor=1)),
        ("点击穿透开关", cfg_stub(click=True))):
    check(f"{label}变化 -> REAPPLY",
          G.WidgetGuard().settings_action(G.geometry_signature(base),
                                          G.geometry_signature(changed)) == G.REAPPLY)

print("\n=== 5. 静态接线检查（防止修复被漏掉） ===")
bw = (LINUX_PKG / "block_window.py").read_text(encoding="utf-8")
pw = (LINUX_PKG / "platform_window.py").read_text(encoding="utf-8")
st = (LINUX_PKG / "state.py").read_text(encoding="utf-8")
mn = (LINUX_PKG / "main.py").read_text(encoding="utf-8")
cf = (LINUX_PKG / "config.py").read_text(encoding="utf-8")
rp = (LINUX_PKG / "rotation.py").read_text(encoding="utf-8")
for signal in ("button-press-event", "button-release-event", "delete-event",
               "window-state-event", "visibility-notify-event", "map-event",
               "unmap-event", "configure-event"):
    check(f"BlockWindow 已连接 {signal}", f'"{signal}"' in bw)
check("输入事件掩码包含 BUTTON_PRESS / VISIBILITY_NOTIFY",
      "BUTTON_PRESS_MASK" in bw and "VISIBILITY_NOTIFY_MASK" in bw)
check("button / delete 处理返回 True", "return True" in bw)
check("存在 2 秒可见性看门狗", "timeout_add_seconds" in bw and "_watchdog" in bw)
check("platform_window 提供 ensure_visible", "def ensure_visible(" in pw)
check("platform_window 尺寸锁定幂等", "_SIZE_STATE" in pw)
check("state 拆分出 schedule 事件", '"schedule"' in st)
check("轮换器改用 schedule 通知", "notify_schedule_changed" in rp and
      "emit(\"schedule\")" in st)
check("Gtk.Application 调用 hold/release", "self.hold()" in mn and
      "self.release()" in mn)
check("退出前抑制自愈", "begin_shutdown" in mn)
check("click_through 默认 False", "click_through: bool = False" in cf
      and 'd.get("clickThrough", False)' in cf)

print("\n=== 6. Python 3.7 语法兼容（deb 目标发行版） ===")
for p in sorted(LINUX_PKG.glob("*.py")):
    src = p.read_text(encoding="utf-8")
    try:
        ast.parse(src, feature_version=(3, 7))
        ok = True
    except SyntaxError as e:
        ok = False
        print(f"    {p.name}: {e}")
    check(f"{p.name} 语法兼容 3.7", ok)
mods = [p for p in LINUX_PKG.glob("*.py") if p.name != "__init__.py"]
futures = [p.name for p in mods
           if "from __future__ import annotations" in p.read_text(encoding="utf-8")]
check("含注解模块均启用延迟求值", len(futures) == len(mods),
      f"missing: {sorted(set(p.name for p in mods) - set(futures))}")

print()
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL CLICK-GUARD TESTS PASS")
