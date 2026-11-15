"""X11 / Wayland 差异处理：常驻窗口的层级、任务栏隐藏、锚点定位与点击穿透。

X11   : GDK_WINDOW_TYPE_HINT_DESKTOP + KEEP_BELOW + SKIP_TASKBAR/PAGER +
        gtk_window_move 绝对定位 + 空 input shape（点击穿透）——全部可用。
Wayland: 协议不允许客户端指定绝对坐标，也不允许 DESKTOP 类型窗口；
        set_type_hint / move / input_shape 会被合成器忽略。
        因此 Wayland 下退化为"无边框 + 不抢焦点 + 保持置底"的普通窗口，
        位置由合成器记住。wlroots 合成器可改用 gtk-layer-shell 的
        LayerSurface（LAYER_BACKGROUND）获得与 X11 等价的效果，见 docs/01。

屏幕适配（v1.0.0-3 修复）：
  过去用配置里的名义尺寸 cfg.block_size 做 clamp，一旦窗口被 HiDPI 缩放或
  窗口管理器放大，实际 GDK 窗口更大，右/下边缘就会跑出屏幕。现在改为：
    · 尺寸：按工作区做 fit_size，并用 set_geometry_hints 锁定 min=max；
    · 定位：读取 GDK 窗口的**真实**宽高，在设备像素坐标系内 clamp；
    · 复核：move 之后延时读回窗口原点，越界就按实测比例校正（同时兼容
      gtk_window_move 在不同后端把参数解释为逻辑像素 / 设备像素的差异）。

可见性自愈（v1.0.0-4 修复）：
  ensure_visible() 在方块被桌面组件盖住、被 WM 撤回或重新映射后，重新声明
  DESKTOP / BELOW / STICKY 等 X property 并恢复显示；只动可见性与层级，
  不改元素、配置、位置、尺寸。_lock_size() 改为幂等：resize() 会触发
  configure-event 连锁重排，不能因为一次轮换 tick 就反复调用。
"""
from __future__ import annotations

import os
import struct
from functools import partial

import cairo
from gi.repository import Gdk, GLib, Gtk

from . import layout
from . import cover_policy

_TOLERANCE = 2          # 允许的定位误差（设备像素）
_MAX_CORRECTIONS = 3    # 防止与窗口管理器来回拉扯
_VERIFY_DELAYS = (120, 400)  # ms：WM 初始摆放与延迟重排各查一次
_VERIFY_STATE = {}
_SIZE_STATE = {}            # id(window) -> 已施加的尺寸，保证 resize 幂等


def _state_bit(name: str, default: int) -> int:
    """Gdk.WindowState 的位值：不同 PyGObject 版本枚举成员可能缺失。"""
    try:
        return int(getattr(Gdk.WindowState, name))
    except (AttributeError, TypeError, ValueError):
        return default


STATE_WITHDRAWN = _state_bit("WITHDRAWN", 1)
STATE_ICONIFIED = _state_bit("ICONIFIED", 2)
STATE_BELOW = _state_bit("BELOW", 64)


def is_wayland() -> bool:
    display = Gdk.Display.get_default()
    cls = type(display).__name__.lower() if display else ""
    return ("wayland" in cls
            or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            or bool(os.environ.get("WAYLAND_DISPLAY")))


def _scale(window: Gtk.Window) -> int:
    """窗口的缩放因子（逻辑像素 → 设备像素）。"""
    try:
        s = int(window.get_scale_factor())
    except (AttributeError, TypeError, ValueError):
        gdk = window.get_window()
        try:
            s = int(gdk.get_scale_factor()) if gdk else 1
        except (AttributeError, TypeError, ValueError):
            s = 1
    return max(1, s or 1)


def _monitor_count() -> int:
    display = Gdk.Display.get_default()
    if display is not None and hasattr(display, "get_n_monitors"):
        return display.get_n_monitors()
    screen = Gdk.Screen.get_default()
    return screen.get_n_monitors() if screen else 0


def workarea(cfg) -> tuple[int, int, int, int]:
    """返回 (x, y, width, height)，**应用（逻辑）像素**，已扣除 dock / 面板。"""
    count = _monitor_count()
    idx = min(max(0, cfg.position.monitor_index), max(0, count - 1))
    if count:
        display = Gdk.Display.get_default()
        if display is not None and hasattr(display, "get_monitor"):
            try:
                r = display.get_monitor(idx).get_workarea()
                if r.width > 0 and r.height > 0:
                    return r.x, r.y, r.width, r.height
            except (AttributeError, TypeError, ValueError):
                pass
        screen = Gdk.Screen.get_default()
        if screen is not None:
            try:
                r = screen.get_monitor_workarea(idx)
                if r.width > 0 and r.height > 0:
                    return r.x, r.y, r.width, r.height
            except (AttributeError, TypeError, ValueError):
                pass
    screen = Gdk.Screen.get_default()
    if screen:
        return 0, 0, screen.get_width(), screen.get_height()
    return 0, 0, 1920, 1080


def fit_block_size(cfg) -> int:
    """按当前工作区把配置尺寸收敛到屏幕内。"""
    _x, _y, w, h = workarea(cfg)
    return layout.fit_size(cfg.block_size, w, h)


def _lock_size(window: Gtk.Window, size: int, force: bool = False) -> None:
    """把窗口尺寸锁在 size：既防止 WM 放大，也保证重定位时尺寸稳定。

    幂等很关键：resize() 会触发 configure-event → enforce_bounds → place →
    move 的连锁重排。若轮换器每 15 秒的排程通知也走到这里，某些窗口管理器
    会趁机把 DESKTOP 层方块压到桌面组件下面（1.0.0-4 单击消失的诱因之一）。
    """
    key = id(window)
    if not force and _SIZE_STATE.get(key) == size:
        return
    window.set_default_size(size, size)
    try:
        window.set_size_request(size, size)
    except (AttributeError, TypeError):
        pass
    try:
        geom = Gdk.Geometry()
        geom.min_width = geom.max_width = size
        geom.min_height = geom.max_height = size
        window.set_geometry_hints(
            window, geom, Gdk.WindowHints.MIN_SIZE | Gdk.WindowHints.MAX_SIZE)
    except (AttributeError, TypeError, ValueError):
        pass  # 个别合成器不支持 hints，仍有 fit_size + 复核兜底
    window.resize(size, size)
    _SIZE_STATE[key] = size


def apply_window_flags(window: Gtk.Window, cfg, force: bool = False) -> None:
    """force=True 用于重新映射后（X property 与 geometry hints 已丢失）。"""
    window.set_decorated(False)
    window.set_resizable(False)
    window.set_skip_taskbar_hint(True)      # 任务栏不出现图标
    window.set_skip_pager_hint(True)        # 不在工作区切换器中出现
    window.set_keep_below(True)             # 位于普通窗口之下
    window.set_accept_focus(False)          # 不抢焦点
    window.set_focus_on_map(False)
    window.stick()                          # 所有虚拟桌面都显示
    window.set_type_hint(Gdk.WindowTypeHint.DESKTOP)  # X11: _NET_WM_WINDOW_TYPE_DESKTOP
    _lock_size(window, fit_block_size(cfg), force=force)


def device_bounds(cfg, scale: int) -> tuple[int, int, int, int]:
    """工作区在设备像素下的边界，并与整屏取交集（无论后端怎么报告都不会越界）。"""
    x0, y0, w, h = workarea(cfg)
    wa = (x0 * scale, y0 * scale, w * scale, h * scale)
    screen = Gdk.Screen.get_default()
    if screen:
        full = (0, 0, screen.get_width() * scale, screen.get_height() * scale)
        r = layout.rect_intersection(wa, full)
        return int(r[0]), int(r[1]), int(r[2]), int(r[3])
    return int(wa[0]), int(wa[1]), int(wa[2]), int(wa[3])


def _actual_size(window: Gtk.Window, fallback: int) -> tuple[int, int]:
    gdk = window.get_window()
    if gdk is not None:
        return max(1, gdk.get_width()), max(1, gdk.get_height())
    return fallback, fallback


def _verify(window: Gtk.Window, token: int, attempt: int) -> bool:
    """move 之后读回真实原点，越界就校正；GLib.SOURCE_REMOVE。"""
    st = _VERIFY_STATE.get(id(window))
    if st is None or st["token"] != token or is_wayland():
        return False
    gdk = window.get_window()
    if gdk is None:
        return False
    try:
        ox, oy = gdk.get_origin()
    except (TypeError, ValueError):
        return False
    w, h = max(1, gdk.get_width()), max(1, gdk.get_height())
    dx, dy = layout.overflow_delta(ox, oy, w, h, st["bounds"])
    if abs(dx) <= _TOLERANCE and abs(dy) <= _TOLERANCE:
        return False

    if not st.get("calibrated"):
        # 校准：gtk_window_move 的参数究竟按设备像素还是逻辑像素解释，
        # 由「请求值 → 实测原点」的比值决定，不再依赖后端假设。
        req_x, req_y = st["request"]
        ratio = 1.0
        if abs(req_x) > 8:
            ratio = ox / req_x
        elif abs(req_y) > 8:
            ratio = oy / req_y
        st["ratio"] = ratio if 0.25 < ratio <= 4 else 1.0
        st["calibrated"] = True

    ratio = st["ratio"]
    new_x = st["request"][0] + dx / ratio
    new_y = st["request"][1] + dy / ratio
    st["request"] = (new_x, new_y)
    window.move(int(round(new_x)), int(round(new_y)))
    if attempt + 1 < _MAX_CORRECTIONS:
        GLib.timeout_add(150, partial(_verify, window, token, attempt + 1))
    return False


def _schedule_verify(window: Gtk.Window,
                     bounds: tuple[int, int, int, int],
                     request: tuple[int, int]) -> None:
    st = _VERIFY_STATE.setdefault(id(window), {"token": 0})
    st["token"] += 1
    token = st["token"]
    st.update(bounds=bounds, request=request, ratio=1.0, calibrated=False)
    # 第一次：WM 完成初始摆放后校正；第二次：兜底检查延迟重排，且不再派生新链
    GLib.timeout_add(_VERIFY_DELAYS[0], partial(_verify, window, token, 0))
    GLib.timeout_add(_VERIFY_DELAYS[1],
                     partial(_verify, window, token, _MAX_CORRECTIONS - 1))


def place(window: Gtk.Window, cfg) -> tuple[int, int]:
    """按锚点定位，并保证方块整体落在屏幕内。返回 (x, y)（设备像素）。"""
    scale = _scale(window)
    size = fit_block_size(cfg)
    bounds = device_bounds(cfg, scale)
    win_w, win_h = _actual_size(window, size * scale)

    if win_w > bounds[2] or win_h > bounds[3]:
        # WM 忽略过 resize / 旧配置块尺寸过大：按实际可用区域再缩一次
        smaller = max(layout.ABSOLUTE_MIN,
                      int(min(bounds[2], bounds[3]) / scale) - 2 * layout.MARGIN)
        _lock_size(window, smaller)
        win_w = win_h = smaller * scale

    off_x = cfg.position.offset_x * scale
    off_y = cfg.position.offset_y * scale
    x, y = layout.anchor_origin(cfg.position.anchor, off_x, off_y,
                                bounds, win_w, win_h)
    if not is_wayland():
        window.move(x, y)   # Wayland 会忽略；由合成器记住上次位置
        _schedule_verify(window, bounds, (x, y))
    return x, y


def enforce_bounds(window: Gtk.Window, cfg) -> None:
    """窗口被 WM 重新摆放 / 缩放后按需重定位；带冷却，避免 configure-event 自激。"""
    if is_wayland():
        return
    st = _VERIFY_STATE.get(id(window))
    if not st or "bounds" not in st:
        return
    now = GLib.get_monotonic_time()
    if now - st.get("last_enforce", 0) < 250_000:  # 250 ms
        return
    gdk = window.get_window()
    if gdk is None:
        return
    try:
        ox, oy = gdk.get_origin()
    except (TypeError, ValueError):
        return
    dx, dy = layout.overflow_delta(ox, oy, gdk.get_width(), gdk.get_height(),
                                   st["bounds"])
    if abs(dx) > _TOLERANCE or abs(dy) > _TOLERANCE:
        st["last_enforce"] = now
        place(window, cfg)


def apply_click_through(window: Gtk.Window, enabled: bool) -> bool:
    """X11 用空 input shape 让鼠标事件直接落到桌面；Wayland 不支持，返回 False。"""
    gdk = window.get_window()
    if gdk is None or is_wayland():
        return False
    try:
        if enabled:
            gdk.input_shape_combine_region(cairo.Region(), 0, 0)
        else:
            w, h = gdk.get_width(), gdk.get_height()
            gdk.input_shape_combine_region(
                cairo.Region(cairo.RectangleInt(0, 0, w, h)), 0, 0)
        return True
    except (AttributeError, TypeError):
        return False


def ensure_visible(window: Gtk.Window, cfg,
                   reapply_geometry: bool = False) -> bool:
    """方块被桌面组件盖住 / 被 WM 撤回后，恢复到原来的桌面层状态。

    只恢复「可见性与层级」：不改元素、不改配置、不重排位置尺寸，因此单击
    方块前后的窗口状态完全一致。``reapply_geometry=True`` 只在 map-event
    时使用（重新映射后 geometry hints 与锚点位置可能已丢失）。
    """
    gdk = window.get_window()
    if gdk is None:
        return False
    try:
        bits = int(gdk.get_state())
    except (AttributeError, TypeError, ValueError):
        bits = 0
    withdrawn = bool(bits & STATE_WITHDRAWN)
    iconified = bool(bits & STATE_ICONIFIED)
    try:
        if withdrawn or iconified:
            window.deiconify()
        if not window.get_visible():
            window.show()          # 不用 present()：不抢焦点、不置顶

        # GTK 对「值没变」的 setter 是 no-op。重新映射 / WM 重启后 X property
        # 已丢失，必须先置反再置回，才会重新发送 _NET_WM_STATE client message。
        window.set_keep_below(False)
        window.set_keep_below(True)
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        window.set_accept_focus(False)
        window.set_focus_on_map(False)
        window.stick()
        window.set_type_hint(Gdk.WindowTypeHint.DESKTOP)

        if reapply_geometry:
            apply_window_flags(window, cfg, force=True)
            place(window, cfg)
        elif not is_wayland():
            # 桌面组件 raise 自己盖住方块时，在 BELOW 层内部上移；
            # EWMH 下普通窗口仍在我们之上，不会弹出到应用窗口前面。
            try:
                gdk.raise_()
            except (AttributeError, TypeError, ValueError):
                pass

        apply_click_through(window, cfg.click_through)
        apply_opacity(window, cfg.opacity)
        window.queue_draw()
        return True
    except (AttributeError, TypeError, ValueError):
        return False


def on_screen_changed(screen, callback) -> None:
    """显示器插拔 / 分辨率变化后重新按工作区锚点定位。"""
    screen.connect("monitors-changed", lambda _s: callback())
    screen.connect("size-changed", lambda _s: callback())
    display = Gdk.Display.get_default()
    if display is not None:
        for sig in ("monitor-added", "monitor-removed"):
            try:
                display.connect(sig, lambda *_a: callback())
            except (TypeError, AttributeError):
                pass


# ---------------------------------------------------------------------------
# 不透明度（实时生效、持久化）
# ---------------------------------------------------------------------------
def apply_opacity(window: Gtk.Window, opacity: float) -> None:
    """设置窗口不透明度；GDK 在 X11 / Wayland 都支持 set_opacity。"""
    try:
        window.set_opacity(max(0.1, min(1.0, float(opacity))))
    except (AttributeError, TypeError, ValueError):
        pass


# ---------------------------------------------------------------------------
# 桌面层级 / 最大化·全屏隐藏 / 显示桌面（X11 EWMH）
# ---------------------------------------------------------------------------
# 这些名称在 Wayland 下用不到：Wayland 协议不允许客户端探测其它窗口的几何
# 与状态，方块在 Wayland 下始终可见（即「桌面层 + 永不隐藏」的安全降级）。
_MAX_H = "_NET_WM_STATE_MAXIMIZED_HORZ"
_MAX_V = "_NET_WM_STATE_MAXIMIZED_VERT"
_FULL = "_NET_WM_STATE_FULLSCREEN"
_CLIENTS_STACKING = "_NET_CLIENT_LIST_STACKING"
_CLIENTS = "_NET_CLIENT_LIST"
_SHOWING_DESKTOP = "_NET_SHOWING_DESKTOP"


def _x11_atom(display, name: str):
    try:
        from gi.repository import GdkX11
        return GdkX11.x11_get_xatom_by_name_for_display(display, name)
    except (ImportError, AttributeError, ValueError, TypeError):
        return None


def _x11_root() -> "Gdk.Window | None":
    screen = Gdk.Screen.get_default()
    return screen.get_root_window() if screen else None


def _x11_prop_int(window, display, name: str):
    atom = _x11_atom(display, name)
    if atom is None or window is None:
        return None
    try:
        res = window.property_get(name, "CARDINAL", 0, 4)
        if not res:
            return None
        _type, _fmt, data = res
        if not data or len(data) < 4:
            return None
        raw = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        return struct.unpack("<I", raw[:4])[0]
    except (AttributeError, TypeError, ValueError, struct.error):
        return None


def _x11_prop_window_ids(window, display, name: str):
    atom = _x11_atom(display, name)
    if atom is None or window is None:
        return []
    try:
        res = window.property_get(name, "WINDOW", 0, 1024 * 16)
        if not res:
            return []
        _type, _fmt, data = res
        raw = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        n = len(raw) // 4
        return list(struct.unpack("<%dI" % n, raw[:n * 4]))
    except (AttributeError, TypeError, ValueError, struct.error):
        return []


def _x11_window_states(display, xid: int):
    try:
        from gi.repository import GdkX11
        win = GdkX11.X11Window.foreign_new_for_display(display, xid)
        res = win.property_get(_FULL, "ATOM", 0, 1024 * 4)
        if not res:
            return set()
        _type, _fmt, data = res
        raw = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        n = len(raw) // 4
        return set(struct.unpack("<%dI" % n, raw[:n * 4]))
    except (ImportError, AttributeError, TypeError, ValueError, struct.error):
        return set()


def _x11_window_frame(display, xid: int):
    try:
        from gi.repository import GdkX11
        win = GdkX11.X11Window.foreign_new_for_display(display, xid)
        rect = win.get_frame_extents()
        return (rect.x, rect.y, rect.width, rect.height)
    except (ImportError, AttributeError, TypeError, ValueError):
        return None


def cover_state(cfg) -> tuple[bool, bool]:
    """返回 (covered, showing_desktop)。

    covered  = 本显示器上存在最大化或全屏的普通窗口（其边框与显示器有正重叠）；
    showing_desktop = 桌面环境正处于「显示桌面」状态（_NET_SHOWING_DESKTOP=1）。

    任何异常（无 X11、GdkX11 缺失、属性读不到）都按 (False, False) 处理——
    即「无法确定覆盖 -> 方块保持可见」，这是保守且安全的默认。Wayland 直接返回
    (False, False)，因为协议不允许探测别的窗口，方块在 Wayland 下永不隐藏。
    """
    if is_wayland():
        return (False, False)
    try:
        display = Gdk.Display.get_default()
        screen = Gdk.Screen.get_default()
        root = _x11_root()
        if display is None or screen is None or root is None:
            return (False, False)

        showing = _x11_prop_int(root, display, _SHOWING_DESKTOP)
        showing_desktop = bool(showing)

        clients = (_x11_prop_window_ids(root, display, _CLIENTS_STACKING)
                   or _x11_prop_window_ids(root, display, _CLIENTS))
        if not clients:
            return (False, showing_desktop)

        max_h = _x11_atom(display, _MAX_H)
        max_v = _x11_atom(display, _MAX_V)
        full = _x11_atom(display, _FULL)
        if None in (max_h, max_v, full):
            return (False, showing_desktop)

        idx = min(max(0, cfg.position.monitor_index), max(0, _monitor_count() - 1))
        mg = screen.get_monitor_geometry(idx)
        monitor = (mg.x, mg.y, mg.width, mg.height)

        for xid in clients:
            states = _x11_window_states(display, xid)
            if full in states or ({max_h, max_v} <= states):
                fr = _x11_window_frame(display, xid)
                if fr and layout.rect_overlap(fr, monitor):
                    return (True, showing_desktop)
        return (False, showing_desktop)
    except Exception:
        return (False, False)


def evaluate_cover(window: Gtk.Window, cfg) -> bool:
    """根据当前 EWMH 状态，让方块在「被最大化/全屏窗口覆盖」时隐藏、否则显示。

    返回当前是否处于「因覆盖而隐藏」的状态。显示桌面（showing_desktop）时一律
    显示——既满足需求，也顺带修掉「点显示桌面方块被藏起来」的漏洞。

    只在状态发生跳变时施加动作（hide / ensure_visible），稳定状态下不重复调用
    GTK 接口，避免每秒向窗口管理器发送多余的重排消息。
    """
    covered, showing_desktop = cover_state(cfg)
    hidden = cover_policy.should_be_hidden(covered, showing_desktop)
    gdk = window.get_window()
    if gdk is None:
        return hidden
    try:
        bits = int(gdk.get_state())
    except (AttributeError, TypeError, ValueError):
        bits = 0
    withdrawn = bool(bits & STATE_WITHDRAWN)
    iconified = bool(bits & STATE_ICONIFIED)
    visible = bool(window.get_visible()) and not withdrawn and not iconified
    if hidden:
        if visible:
            window.hide()
    else:
        # 仅在「不可见 / 被撤回 / 被最小化」时恢复。显示桌面时若 WM 把方块
        # 一并最小化，这里会把它拉回来；若 WM 没动方块则保持原状、不重复施加。
        if (not window.get_visible()) or withdrawn or iconified:
            ensure_visible(window, cfg)
    return hidden
