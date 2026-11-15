"""桌面常驻元素方块：GTK3 窗口 + Cairo 绘制（与参考图一致的元素卡片）。

v1.0.0-3 布局修复（保留）：
  · 整张卡片先 clip 到 BASE×BASE 的矩形 —— 任何文字都不可能画到方块外；
  · 每行文字有自己的文本框：Pango 实测宽高 → 等比缩字号 → 仍超长则省略号，
    底部行按实测行高上移，杜绝 "238.0" / 长英文名被方块下边缘截断；
  · 窗口被 WM 拉成非正方形时把卡片居中，并按 min(宽,高) 等比缩放。

v1.0.0-4 单击消失修复（详见 widget_guard.py 与 docs/02 §3.4）：
  · 接收并吞掉 button-press / button-release —— 单击不再落到桌面，
    不再触发焦点、堆叠或状态变化；默认也关闭了点击穿透；
  · delete-event 返回 True，窗口永不因 WM 关闭请求被 GTK 默认销毁；
  · visibility / window-state / map / unmap 事件 + 2 秒看门狗：被桌面组件
    盖住、被 WM 撤回或最小化时自动恢复到原来的桌面层，几何与元素不变；
  · settings 事件只在「几何签名」变化时才重排窗口，轮换器 15 秒的排程
    通知改走 schedule 事件，不再每 15 秒 resize/move 一次桌面层窗口。

视觉样式、字体层级、托盘、轮换、配置格式全部保持不变。
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import layout, platform_window, widget_guard  # noqa: E402
from .assets import hex_to_rgb  # noqa: E402

BASE = 132.0   # 设计基准尺寸，所有坐标按此比例缩放
PAD = 4.0      # 卡片内边距（基准坐标）


def _now_ms() -> int:
    return GLib.get_monotonic_time() // 1000


def _event_mask():
    """点击与可见性事件必须显式订阅，否则 GDK 不会投递给本窗口。"""
    return (Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.STRUCTURE_MASK
            | Gdk.EventMask.VISIBILITY_NOTIFY_MASK)


def _state_bits(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _visibility_name(state) -> str:
    """把 Gdk.VisibilityState 归一成 fully_obscured / partial / other。

    GDK3 各版本枚举命名不一致（FULLY_OBSCURED / PARTIALLY_VISIBLE / …），
    这里只认字符串特征，避免依赖具体枚举成员；测试桩可直接传字符串。
    """
    if state is None:
        return "other"
    if isinstance(state, str):
        name = state.upper()
    else:
        try:
            name = (state.value_name or "").upper()
        except (AttributeError, TypeError, ValueError):
            name = str(state).upper()
    if "FULLY" in name and "OBSCUR" in name:
        return "fully_obscured"
    if "PART" in name:
        return "partial"
    return "other"


def _set_font(pl, font: str, size: float) -> None:
    pl.set_font_description(Pango.FontDescription(f"{font} {size}"))


def _text(cr, text: str, font: str, size: float, x: float, y: float,
          color, align: str = "left", max_width: float | None = None,
          bottom: float | None = None) -> None:
    """在「卡片内的文本框」里绘制单行文字：自动字体回退 + 缩放 + 省略 + 裁剪。"""
    if not text:
        return
    box_w = min(float(max_width) if max_width else BASE - 2 * PAD,
                BASE - 2 * PAD)
    bottom = min(float(bottom) if bottom is not None else BASE - PAD, BASE - PAD)

    pl = PangoCairo.create_layout(cr)   # 中英文/扩展汉字交给 fontconfig 回退
    pl.set_text(text, -1)
    pl.set_single_paragraph_mode(True)  # 不折成多行，超长用省略号收尾
    _set_font(pl, font, size)
    _ink, logical = pl.get_extents()
    w = logical.width / Pango.SCALE
    h = logical.height / Pango.SCALE

    fitted = layout.fit_font_size(size, w, h, box_w, max(1.0, bottom - y))
    if fitted < size:
        _set_font(pl, font, fitted)
        _ink, logical = pl.get_extents()
        w = logical.width / Pango.SCALE
        h = logical.height / Pango.SCALE

    # 限定文本框宽度后交给 Pango 对齐；超长时自动省略，绝不会画到框外
    pl.set_width(int(box_w * Pango.SCALE))
    pl.set_ellipsize(Pango.EllipsizeMode.END)
    pl.set_alignment(Pango.Alignment.CENTER if align == "center" else
                     Pango.Alignment.RIGHT if align == "right" else
                     Pango.Alignment.LEFT)
    left = layout.text_box_left(x, align, box_w, BASE, PAD)
    top = max(PAD, min(y, bottom - h))

    cr.set_source_rgb(*color)
    cr.move_to(left, top)
    PangoCairo.show_layout(cr, pl)


class BlockWindow(Gtk.Window):
    def __init__(self, state) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.state = state
        self.guard = widget_guard.WidgetGuard(now_ms=_now_ms())
        self._geom_sig = widget_guard.geometry_signature(state.cfg)
        self._restore_pending = False
        self._cover_hidden = False   # 因被最大化/全屏窗口覆盖而主动隐藏（区别于自愈）
        self._watchdog_id = None
        self._cover_id = None
        self.set_title("Element Blocks Desktop")
        self.set_role("element-blocks-widget")

        self._area = Gtk.DrawingArea()
        self._area.connect("draw", self._on_draw)

        # 事件掩码必须在 realize（GdkWindow 创建）之前设置；
        # DrawingArea 是无窗口控件，也要订阅，点击才能落到本窗口而非桌面。
        mask = _event_mask()
        for widget in (self, self._area):
            widget.add_events(mask)
            widget.connect("button-press-event", self._on_button)
            widget.connect("button-release-event", self._on_button)
        self.add(self._area)

        self.connect("delete-event", self._on_delete)
        self.connect("visibility-notify-event", self._on_visibility)
        self.connect("window-state-event", self._on_window_state)
        self.connect("map-event", self._on_map)
        self.connect("unmap-event", self._on_unmap)
        self.connect("configure-event", self._on_configure)
        self.connect("realize", self._on_realize)

        platform_window.apply_window_flags(self, state.cfg)
        platform_window.apply_opacity(self, state.cfg.opacity)
        state.on("element", lambda _e: self._area.queue_draw())
        state.on("settings", self._on_settings)
        state.on("appearance", self._on_appearance)
        self.show_all()
        # 某些 WM 不投递 VisibilityNotify，用低频轮询兜底（2 秒，开销可忽略）
        self._watchdog_id = GLib.timeout_add_seconds(2, self._watchdog)
        # 覆盖轮询：检查本显示器是否被最大化/全屏窗口覆盖，决定是否隐藏；
        # 显示桌面状态下保持可见。1 秒一次，开销可忽略。
        self._cover_id = GLib.timeout_add_seconds(1, self._cover_poll)

    # ---- 点击：只吞事件，零副作用 ----------------------------------------
    def _on_button(self, _widget, _event) -> bool:
        self.guard.click(1, self.state.cfg.click_through)
        return True   # GDK_EVENT_STOP：GTK 默认处理与向下传播都被截断

    def _on_delete(self, _window, _event) -> bool:
        # 无边框窗口没有关闭按钮，但 WM 仍可能发 WM_DELETE_WINDOW；
        # GTK 默认会 destroy，而本窗口是 Application 的唯一窗口 → 进程退出。
        return self.guard.on_delete()

    # ---- 可见性 / 层级自愈 ------------------------------------------------
    def _on_visibility(self, _window, event) -> bool:
        if self._cover_hidden:
            return False   # 主动隐藏期间，忽略遮挡事件
        name = _visibility_name(getattr(event, "state", None))
        if self.guard.on_visibility(name, _now_ms()) == widget_guard.RESTORE:
            self._schedule_restore(False)
        return False

    def _on_window_state(self, _window, event) -> bool:
        if self._cover_hidden:
            return False   # 主动隐藏期间，不与被覆盖的窗口抢层级
        bits = _state_bits(getattr(event, "new_window_state", 0))
        withdrawn = bool(bits & platform_window.STATE_WITHDRAWN)
        iconified = bool(bits & platform_window.STATE_ICONIFIED)
        # Wayland 后端不保证上报 BELOW，语义未知时不据此重排层级
        below = None if platform_window.is_wayland() else bool(
            bits & platform_window.STATE_BELOW)
        action = self.guard.on_window_state(withdrawn, iconified, below,
                                            _now_ms())
        if action == widget_guard.RESTORE:
            self._schedule_restore(False)
        elif action == widget_guard.REAPPLY:
            self._schedule_restore(True)
        return False

    def _on_map(self, _window, _event) -> bool:
        if self.guard.on_map(_now_ms()) == widget_guard.REAPPLY:
            self._schedule_restore(True)
        return False

    def _on_unmap(self, _window, _event) -> bool:
        if self._cover_hidden:
            return False   # 主动隐藏触发的 unmap，不要复活
        if self.guard.on_unmap(_now_ms()) == widget_guard.RESTORE:
            self._schedule_restore(False)
        return False

    def _watchdog(self) -> bool:
        if self.guard.quitting:
            return False       # 移除定时器
        if self._cover_hidden:
            return True        # 主动隐藏中，不要复活
        gdk = self.get_window()
        if gdk is None:
            return True
        try:
            bits = _state_bits(gdk.get_state())
        except (AttributeError, TypeError, ValueError):
            bits = 0
        withdrawn = bool(bits & platform_window.STATE_WITHDRAWN)
        iconified = bool(bits & platform_window.STATE_ICONIFIED)
        visible = bool(self.get_visible()) and not withdrawn and not iconified
        if self.guard.on_watchdog(visible, withdrawn, iconified,
                                  _now_ms()) == widget_guard.RESTORE:
            self._schedule_restore(False)
        return True

    def _schedule_restore(self, geometry: bool) -> None:
        if self._restore_pending or self.guard.quitting:
            return
        self._restore_pending = True
        # 延后一帧：不要在信号回调里和窗口管理器抢 X 堆叠顺序
        GLib.timeout_add(40, self._do_restore, bool(geometry))

    def _do_restore(self, geometry: bool = False) -> bool:
        self._restore_pending = False
        if not self.guard.quitting:
            platform_window.ensure_visible(self, self.state.cfg,
                                           reapply_geometry=bool(geometry))
        return False

    def begin_shutdown(self) -> None:
        """托盘「退出」时调用：退出过程中不要复活窗口。"""
        self.guard.mark_quitting()
        self._restore_pending = False
        self._cover_hidden = False
        for tid in (self._watchdog_id, self._cover_id):
            if tid is not None:
                try:
                    GLib.source_remove(tid)
                except (TypeError, ValueError):
                    pass
        self._watchdog_id = None
        self._cover_id = None

    # ---- 外观变化：只改不透明度，不重排窗口 --------------------------------
    def _on_appearance(self) -> None:
        platform_window.apply_opacity(self, self.state.cfg.opacity)
        self._area.queue_draw()

    # ---- 覆盖轮询：最大化/全屏窗口或显示桌面 -------------------------------
    def _cover_poll(self) -> bool:
        if self.guard.quitting:
            return False       # 移除定时器
        self._cover_hidden = platform_window.evaluate_cover(self, self.state.cfg)
        return True

    # ---- 配置变化：只有几何相关字段变了才重排 ------------------------------
    def _on_settings(self) -> None:
        sig = widget_guard.geometry_signature(self.state.cfg)
        if self.guard.settings_action(self._geom_sig, sig) == widget_guard.REAPPLY:
            platform_window.apply_window_flags(self, self.state.cfg)
            platform_window.place(self, self.state.cfg)
            platform_window.apply_click_through(self, self.state.cfg.click_through)
            platform_window.apply_opacity(self, self.state.cfg.opacity)
            self._geom_sig = sig
        self._area.queue_draw()

    def _on_realize(self, _window) -> None:
        platform_window.place(self, self.state.cfg)
        platform_window.apply_click_through(self, self.state.cfg.click_through)
        screen = Gdk.Screen.get_default()
        if screen:
            platform_window.on_screen_changed(screen, self._on_settings)

    def _on_configure(self, _window, _event) -> bool:
        # WM 有可能在 map 之后重新摆放 DESKTOP 窗口，发现越界就重新收敛
        platform_window.enforce_bounds(self, self.state.cfg)
        return False

    # ---- 绘制（v1.0.0-3 逻辑，未改动） ------------------------------------
    def _on_draw(self, _area, cr) -> bool:
        w = self._area.get_allocated_width()
        h = self._area.get_allocated_height()
        if w <= 0 or h <= 0:
            return False

        tile = self.state.assets.theme["tile"]
        k = min(w, h) / BASE
        cr.save()
        cr.scale(k, k)
        # 非正方形分配时让卡片居中，避免贴边后被屏幕裁掉
        cr.translate((w / k - BASE) / 2.0, (h / k - BASE) / 2.0)
        cr.save()
        cr.rectangle(0, 0, BASE, BASE)
        cr.clip()   # ★ 硬边界：所有绘制都限制在卡片矩形内

        cr.set_source_rgb(*hex_to_rgb(tile["background"]))
        cr.rectangle(0, 0, BASE, BASE)
        cr.fill()
        cr.set_source_rgb(*hex_to_rgb(tile["border"]))
        cr.set_line_width(max(1.0, tile["borderWidth"]))
        cr.rectangle(0.5, 0.5, BASE - 1, BASE - 1)
        cr.stroke()

        fg = hex_to_rgb(tile["foreground"])
        accent = hex_to_rgb(tile["accent"])
        e = self.state.current

        if e is None:
            _text(cr, "--", "Sans", tile["fontNumber"], 9, 7, fg,
                  max_width=40, bottom=30)
            _text(cr, "—", "Serif", 40, BASE / 2, 34, fg, "center", bottom=92)
            _text(cr, "未启用任何元素", "Sans", 12, BASE / 2, 95, fg,
                  "center", 118, 111)
            _text(cr, "请在设置中启用", "Sans", 12, BASE / 2, 112, fg,
                  "center", 118, BASE - PAD)
            cr.restore()
            cr.restore()
            return False

        num_color = accent if e.radioactive else fg
        _text(cr, str(e.number), "Sans", tile["fontNumber"], 9, 7,
              num_color, max_width=40, bottom=30)
        _text(cr, e.symbol, "Sans Bold", tile["fontSymbol"], 123, 7,
              num_color, "right", 40, 30)
        _text(cr, e.name_zh, "Serif", tile["fontNameZh"], BASE / 2, 30,
              fg, "center", 118, 92)
        _text(cr, e.name_en, "Sans", tile["fontNameEn"], BASE / 2, 94,
              fg, "center", 116, 110)
        _text(cr, e.mass, "Sans Bold", tile["fontMass"], BASE / 2, 110,
              fg, "center", 116, BASE - PAD)

        cr.restore()   # 解除 clip
        cr.restore()   # 解除 scale / translate
        return False
