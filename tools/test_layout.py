#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 Python 布局回归测试：不需要 GTK / dpkg / Linux。

覆盖本次修复的两类越界：
  · 方块窗口：尺寸自适应、按真实窗口尺寸 clamp、高分屏坐标换算与位置校正收敛；
  · 方块文字：长英文名/底部原子量的字号收敛、文本框边界。

运行：python tools/test_layout.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "ebd_layout", ROOT / "linux" / "element_blocks_desktop" / "layout.py")
L = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(L)

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {detail}")


def rect_inside(x, y, w, h, b) -> bool:
    return (x >= b[0] - 0.01 and y >= b[1] - 0.01
            and x + w <= b[0] + b[2] + 0.01
            and y + h <= b[1] + b[3] + 0.01)


print("=== 1. fit_size：方块尺寸必须落进工作区 ===")
cases = [(132, 1920, 1080), (320, 1080, 768), (320, 640, 480),
         (132, 200, 150), (320, 120, 90), (132, 60, 40), (80, 300, 300)]
for req, aw, ah in cases:
    s = L.fit_size(req, aw, ah)
    ok = 1 <= s <= req or s >= L.ABSOLUTE_MIN
    ok = ok and (s + 2 * L.MARGIN <= max(aw, ah))
    ok = ok and s <= min(aw, ah) and (s + 2 * L.MARGIN <= min(aw, ah)
                                     or min(aw, ah) - 2 * L.MARGIN <= 0)
    check(f"fit_size(req={req}, area={aw}x{ah}) -> {s}", ok,
          f"size={s}, min_area={min(aw, ah)}")
check("fit_size 不放大配置尺寸", L.fit_size(132, 1920, 1080) == 132)
check("fit_size 收敛 320 到小屏", L.fit_size(320, 200, 150) <= 150 - 16)

print("\n=== 2. anchor_origin：按真实窗口尺寸 clamp（含高分屏与 WM 放大） ===")
bounds_cases = [
    ("scale=1", (0, 0, 1080, 768), 1, 132),
    ("scale=1.5", (0, 0, 1080, 720), 1.5, 198),
    ("scale=2", (0, 0, 2160, 1440), 2, 264),
    ("WM 放大 1.5x", (0, 0, 1080, 720), 1.5, 288),
    ("带左侧 dock", (100, 0, 980, 720), 1, 198),
    ("极小工作区", (0, 0, 160, 120), 1, 100),
]
anchors = ("TopLeft", "TopRight", "BottomLeft", "BottomRight", "Custom")
offsets = ((0, 0), (32, 32), (9999, 9999), (-500, -500))
for label, bounds, scale, win in bounds_cases:
    for anchor in anchors:
        for ox, oy in offsets:
            dx, dy = ox * scale, oy * scale
            x, y = L.anchor_origin(anchor, dx, dy, bounds, win, win)
            if not rect_inside(x, y, win, win, bounds):
                check(f"{label} / {anchor} / off=({ox},{oy})", False,
                      f"got ({x},{y}) win={win} bounds={bounds}")
                break
        else:
            continue
        break
    else:
        check(f"{label} 所有锚点与偏移均在屏内 (win={win})", True)

print("\n=== 3. 复现旧 bug：用名义尺寸 clamp 会越界，新逻辑不会 ===")
# 1080 设备像素宽、1.5x 缩放；实际窗口被放大到 288 设备像素
bounds = (0, 0, 1080, 720)
actual = 288
old_x = bounds[2] - 132 - 32          # 旧代码：cfg.block_size=132 名义尺寸
new_x, _ = L.anchor_origin("TopRight", 32 * 1.5, 0, bounds, actual, actual)
check("旧算法确实越界（回归基线）", old_x + actual > bounds[2],
      f"old right={old_x + actual} > {bounds[2]}")
check("新算法右边缘在屏内", rect_inside(new_x, 0, actual, actual, bounds),
      f"new x={new_x}, right={new_x + actual}")

print("\n=== 4. rect_intersection / overflow_delta ===")
a = (0, 0, 1080, 720)
b = (100, 40, 700, 500)
r = L.rect_intersection(a, b)
check("交集仍是内部矩形", r == (100, 40, 700, 500), str(r))
check("交集不超出任一输入",
      r[0] >= a[0] and r[2] <= a[2] and r[0] + r[2] <= b[0] + b[2])
check("退化交集回退到较小矩形",
      L.rect_intersection((0, 0, 100, 100), (500, 500, 10, 10))
      == (500, 500, 10, 10))
check("右侧越界 delta 为负", L.overflow_delta(950, 0, 288, 288, a)[0] < 0)
check("已在内部 delta=0", L.overflow_delta(400, 100, 200, 200, a) == (0, 0))

print("\n=== 5. 位置校正循环收敛（设备像素 / 逻辑像素两种 move 语义） ===")
for semantics in (1.0, 1.5, 2.0):
    target_x, target_y = 834, 48     # 期望的设备像素位置
    req_x, req_y = float(target_x), float(target_y)
    ratio = None
    converged = False
    for _ in range(5):
        origin = (int(req_x * semantics), int(req_y * semantics))  # WM 实际摆放
        dx, dy = L.overflow_delta(origin[0], origin[1], 198, 198, a)
        if dx == 0 and dy == 0:
            converged = True
            break
        if ratio is None:
            ratio = origin[0] / req_x if abs(req_x) > 8 else 1.0
            if not 0.25 < ratio <= 4:
                ratio = 1.0
        req_x += dx / ratio
        req_y += dy / ratio
    check(f"move 语义 x{semantics} 时 5 步内收敛", converged,
          f"last origin={origin}, req=({req_x:.0f},{req_y:.0f})")

print("\n=== 6. fit_font_size / text_box_left：文字不越界 ===")
# 长英文名 Rutherfordium：14px 实测宽 140，盒宽 116、盒高 16
f = L.fit_font_size(14, 140, 17, 116, 16)
check("长英文名等比缩字号", f < 14 and f >= 5.0, f"size={f}")
check("缩后宽高都进盒", 140 * (f / 14) <= 116 + 1e-6 and 17 * (f / 14) <= 16 + 1e-6,
      f"w={140 * f / 14:.1f} h={17 * f / 14:.1f}")
# 底部 238.0：15px 实测高 19，可用高度仅 18
f2 = L.fit_font_size(15, 60, 19, 116, 18)
check("底部原子量不再越过下边缘", 19 * (f2 / 15) <= 18 + 1e-6, f"size={f2}")
check("正常字号不被误缩", L.fit_font_size(46, 60, 55, 118, 62) == 46)
for align, x in (("center", 66), ("right", 123), ("left", 9)):
    left = L.text_box_left(x, align, 124, 132, 4)
    check(f"文本框 {align} 在卡片内边距内", 4 <= left and left + 124 <= 128,
          f"left={left}, right={left + 124}")

print("\n=== 7. Python 3.7 语法兼容 ===")
import ast
for p in sorted((ROOT / "linux" / "element_blocks_desktop").glob("*.py")):
    src = p.read_text(encoding="utf-8")
    try:
        ast.parse(src, feature_version=(3, 7))
        ok = True
    except SyntaxError as e:
        ok = False
        print(f"    {p.name}: {e}")
    check(f"{p.name} 语法兼容 3.7", ok)
mods = [p for p in (ROOT / "linux" / "element_blocks_desktop").glob("*.py")
        if p.name != "__init__.py"]  # __init__ 只有 docstring，无类型注解
futures = [p.name for p in mods
           if "from __future__ import annotations" in p.read_text(encoding="utf-8")]
check("含类型注解的模块均启用延迟求值", len(futures) == len(mods), str(futures))

print()
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL LAYOUT TESTS PASS")
