"""纯计算布局工具：不依赖 GTK / Pango，可在任意平台做单元测试。

约定：所有函数都在**同一个坐标系**里工作。调用方（platform_window.py）负责把
工作区、偏移、窗口尺寸统一换算到设备像素后再传进来；本模块不猜测逻辑/设备像素。

这里集中处理两类越界：
  1. 方块窗口整体超出屏幕 —— fit_size / anchor_origin / overflow_delta；
  2. 方块内文字超出方块 —— fit_font_size / text_box_left。
"""
from __future__ import annotations

MARGIN = 8          # 方块与工作区边缘至少保留的空白（逻辑像素）
ABSOLUTE_MIN = 40   # 极小工作区下的可见底线尺寸


def clamp(value: float, low: float, high: float) -> float:
    """把 value 限制在 [low, high]；high < low 时返回 low（窗口比屏幕还大的退化情况）。"""
    if high < low:
        return low
    return max(low, min(value, high))


def fit_size(requested: int, area_w: int, area_h: int,
            margin: int = MARGIN) -> int:
    """把方块尺寸收敛到可用工作区内：size + 2*margin <= min(area_w, area_h)。"""
    room = min(int(area_w), int(area_h)) - 2 * margin
    if room <= 0:
        # 极端情况（工作区比留白还小）：宁可贴边也不能越界
        return max(1, min(int(area_w), int(area_h)))
    size = min(max(1, int(requested)), room)
    if size < ABSOLUTE_MIN:
        size = min(room, ABSOLUTE_MIN)
    return max(1, size)


def rect_intersection(a: tuple[float, float, float, float],
                      b: tuple[float, float, float, float]
                      ) -> tuple[float, float, float, float]:
    """求两个 (x, y, w, h) 矩形的交集；退化时返回面积更小的那个（保证不放大边界）。"""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    if x1 <= x0 or y1 <= y0:
        return a if a[2] * a[3] <= b[2] * b[3] else b
    return (x0, y0, x1 - x0, y1 - y0)


def anchor_origin(anchor: str, off_x: float, off_y: float,
                  bounds: tuple[float, float, float, float],
                  win_w: float, win_h: float) -> tuple[int, int]:
    """按锚点算左上角，并 clamp 到 bounds 内，使窗口四边都不越界。

    win_w / win_h 必须是**实际**窗口尺寸，不能用配置里的名义值。
    """
    x0, y0, bw, bh = bounds
    max_x = x0 + max(0.0, bw - win_w)
    max_y = y0 + max(0.0, bh - win_h)
    if anchor == "Custom":
        x, y = off_x, off_y
    else:
        x = (x0 + bw - win_w - off_x) if "Right" in anchor else (x0 + off_x)
        y = (y0 + bh - win_h - off_y) if "Bottom" in anchor else (y0 + off_y)
    return int(round(clamp(x, x0, max_x))), int(round(clamp(y, y0, max_y)))


def overflow_delta(x: float, y: float, w: float, h: float,
                   bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    """返回把窗口拉回 bounds 内所需的位移（设备像素）；已在内部则为 (0, 0)。"""
    x0, y0, bw, bh = bounds
    dx = dy = 0.0
    if x < x0:
        dx = x0 - x
    elif x + w > x0 + bw:
        dx = (x0 + bw) - (x + w)
    if y < y0:
        dy = y0 - y
    elif y + h > y0 + bh:
        dy = (y0 + bh) - (y + h)
    return dx, dy


def fit_font_size(size: float, width: float, height: float,
                  max_width: float, max_height: float,
                  min_size: float = 5.0) -> float:
    """按实测排版宽高等比缩小字号，让文字落进给定盒内（宽度/高度谁超缩谁）。"""
    ratio = 1.0
    if width > max_width > 0:
        ratio = min(ratio, max_width / width)
    if height > max_height > 0:
        ratio = min(ratio, max_height / height)
    return max(min_size, size * ratio)


def text_box_left(x: float, align: str, box_width: float,
                  tile_size: float = 132.0, pad: float = 4.0) -> float:
    """由锚点 x + 对齐方式算出文本框左边界，并夹在方块内边距之内。"""
    if align == "center":
        left = x - box_width / 2
    elif align == "right":
        left = x - box_width
    else:
        left = x
    return clamp(left, pad, tile_size - pad - box_width)


def rect_overlap(a: tuple[float, float, float, float],
                b: tuple[float, float, float, float]) -> bool:
    """两个 (x, y, w, h) 矩形是否有正的重叠面积（边碰边不算）。"""
    return not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0]
                or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])

