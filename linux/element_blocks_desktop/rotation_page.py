"""第二页：轮换间隔 + 常驻方块行为（GTK3 原生控件）。"""
from __future__ import annotations

from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .config import set_auto_start  # noqa: E402
from .rotation import parse_utc  # noqa: E402

ANCHORS = [("TopLeft", "左上角"), ("TopRight", "右上角"),
           ("BottomLeft", "左下角"), ("BottomRight", "右下角")]


class RotationPage(Gtk.Box):
    def __init__(self, state, rotation) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.state = state
        self.rotation = rotation
        self._loading = True   # 构造期间抑制所有控件回调，直到 refresh() 末尾解除
        self.set_border_width(16)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        vbox.set_border_width(8)
        scroll.add(vbox)
        self.pack_start(scroll, True, True, 0)

        title = Gtk.Label()
        title.set_markup('<span size="x-large" weight="bold">轮换时间</span>')
        title.set_xalign(0)
        vbox.pack_start(title, False, False, 0)
        sub = Gtk.Label(label="按设定的周期自动切换到下一个已启用的元素；顺序按原子序数推进，不会连续重复。")
        sub.set_xalign(0)
        sub.set_line_wrap(True)
        vbox.pack_start(sub, False, False, 0)

        # --- 状态卡 ---
        frame = Gtk.Frame()
        grid = Gtk.Grid()
        grid.set_column_spacing(28)
        grid.set_row_spacing(6)
        grid.set_border_width(12)
        self.current_label = self._stat(grid, 0, "当前元素")
        self.next_label = self._stat(grid, 1, "下一次切换")
        self.enabled_label = self._stat(grid, 2, "已启用元素")
        frame.add(grid)
        vbox.pack_start(frame, False, False, 0)

        # --- 间隔（ComboBox）+ 立即切换按钮 ---
        lbl = Gtk.Label()
        lbl.set_markup('<span weight="bold">切换间隔</span>')
        lbl.set_xalign(0)
        vbox.pack_start(lbl, False, False, 0)

        self._interval_desc_by_id = {
            opt.id: opt.description for opt in state.assets.intervals}
        combo = Gtk.ComboBoxText()
        combo.set_size_request(220, -1)
        for opt in state.assets.intervals:
            combo.append(opt.id, opt.label)
        combo.connect("changed", self._on_interval_combo)
        self.interval_combo = combo

        btn = Gtk.Button(label="立即切换下一个元素")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", self._on_next)

        # 按钮放在 ComboBox 右侧同一行，保持布局整齐
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.pack_start(combo, False, False, 0)
        row.pack_start(btn, False, False, 0)
        vbox.pack_start(row, False, False, 0)

        self.interval_desc = Gtk.Label(label="")
        self.interval_desc.set_xalign(0)
        self.interval_desc.set_line_wrap(True)
        self.interval_desc.set_margin_start(2)
        vbox.pack_start(self.interval_desc, False, False, 0)

        self.hint = Gtk.Label(label="")
        self.hint.set_xalign(0)
        self.hint.set_line_wrap(True)
        vbox.pack_start(self.hint, False, False, 0)

        # --- 其它行为 ---
        lbl = Gtk.Label()
        lbl.set_markup('<span weight="bold">常驻方块行为</span>')
        lbl.set_xalign(0)
        lbl.set_margin_top(8)
        vbox.pack_start(lbl, False, False, 0)

        self.pause_switch = self._switch(vbox, "暂停轮换", "开启后计时停止，但保留下次切换时刻", self.state.cfg.paused,
                                         self._on_pause)
        self.auto_switch = self._switch(vbox, "开机自启", "写入 ~/.config/autostart/element-blocks-desktop.desktop",
                                        self.state.cfg.auto_start, self._on_auto)
        self.click_switch = self._switch(
            vbox, "鼠标点击穿透",
            "默认关闭：方块吞掉自身点击，单击不会改变状态；开启后点击落到桌面，"
            "部分桌面环境会短暂盖住方块",
            self.state.cfg.click_through, self._on_click)

        # --- 外观：不透明度 ---
        lbl = Gtk.Label()
        lbl.set_markup('<span weight="bold">外观</span>')
        lbl.set_xalign(0)
        lbl.set_margin_top(8)
        vbox.pack_start(lbl, False, False, 0)
        self.opacity_label = Gtk.Label(label="不透明度：100%")
        self.opacity_label.set_xalign(0)
        self.opacity_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.1, 1.0, 0.05)
        self.opacity_scale.set_draw_value(False)
        self.opacity_scale.set_hexpand(True)
        self.opacity_scale.connect("value-changed", self._on_opacity)
        vbox.pack_start(self.opacity_label, False, False, 0)
        vbox.pack_start(self.opacity_scale, False, True, 0)

        # --- 位置与尺寸 ---
        form = Gtk.Grid()
        form.set_column_spacing(24)
        form.set_row_spacing(8)
        form.set_margin_top(8)
        anchor_label = Gtk.Label(label="桌面固定位置")
        anchor_label.set_xalign(0)
        self.anchor_box = Gtk.ComboBoxText()
        for key, text in ANCHORS:
            self.anchor_box.append(key, text)
        self.anchor_box.connect("changed", self._on_anchor)
        form.attach(anchor_label, 0, 0, 1, 1)
        form.attach(self.anchor_box, 0, 1, 1, 1)

        self.size_label = Gtk.Label(label="方块大小：132 px")
        self.size_label.set_xalign(0)
        self.size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 80, 320, 4)
        self.size_scale.set_draw_value(False)
        self.size_scale.connect("value-changed", self._on_size)
        form.attach(self.size_label, 1, 0, 1, 1)
        form.attach(self.size_scale, 1, 1, 1, 1)
        form.set_hexpand(True)
        self.size_scale.set_hexpand(True)
        vbox.pack_start(form, False, True, 0)

        note = Gtk.Label(label="设置自动保存到 XDG 配置目录；休眠或关机期间不会补跑切换。")
        note.set_xalign(0)
        note.set_line_wrap(True)
        vbox.pack_start(note, False, False, 0)

        state.on("element", lambda _e: self.refresh())
        state.on("enabled", lambda: self.refresh())
        state.on("settings", lambda: self.refresh())
        state.on("schedule", lambda: self.refresh())   # 15 秒倒计时刷新
        self.refresh()

    # ---- builders ---------------------------------------------------------
    @staticmethod
    def _stat(grid, column, caption):
        cap = Gtk.Label(label=caption)
        cap.set_xalign(0)
        val = Gtk.Label()
        val.set_xalign(0)
        val.set_markup("<b>—</b>")
        grid.attach(cap, column, 0, 1, 1)
        grid.attach(val, column, 1, 1, 1)
        return val

    @staticmethod
    def _switch(parent, label, subtitle, active, callback):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_bottom(4)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        name = Gtk.Label(label=label)
        name.set_xalign(0)
        desc = Gtk.Label(label=subtitle)
        desc.set_xalign(0)
        texts.pack_start(name, False, False, 0)
        texts.pack_start(desc, False, False, 0)
        sw = Gtk.Switch()
        sw.set_active(active)
        sw.set_valign(Gtk.Align.CENTER)
        sw.connect("notify::active", callback)
        box.pack_start(texts, True, True, 0)
        box.pack_start(sw, False, False, 0)
        parent.pack_start(box, False, False, 0)
        return sw

    # ---- refresh ----------------------------------------------------------
    def refresh(self) -> None:
        self._loading = True
        cfg = self.state.cfg
        e = self.state.current
        self.current_label.set_text("未启用任何元素" if e is None
                                    else f"{e.number} {e.name_zh} {e.symbol}")
        self.enabled_label.set_text(f"{len(cfg.enabled_symbols)} / {len(self.state.assets.elements)}")

        interval = self.state.assets.interval(cfg.rotation)
        inactive = interval.minutes <= 0 or cfg.paused or len(cfg.enabled_symbols) < 2
        if inactive:
            self.next_label.set_text("已暂停" if cfg.paused else
                                     ("已启用元素不足 2 个" if len(cfg.enabled_symbols) < 2 else "从不"))
            self.hint.set_text("")
        else:
            t = parse_utc(cfg.next_fire_utc)
            if t is None:
                self.next_label.set_text("排程中…")
            else:
                local = t.astimezone()
                remain = (t - datetime.now(timezone.utc)).total_seconds()
                tail = "即将" if remain <= 0 else (f"{int(remain // 3600)} 小时 {int(remain % 3600 // 60)} 分后"
                                                  if remain >= 3600 else f"{max(0, int(remain // 60))} 分钟后")
                self.next_label.set_text(f"{local:%m-%d %H:%M}（{tail}）")
            self.hint.set_text("下一次切换时刻会写入配置，重启 / 休眠恢复后继续按该时刻执行。")

        self.interval_combo.set_active_id(cfg.rotation)
        self.interval_desc.set_text(self._interval_desc_by_id.get(cfg.rotation, ""))
        self.pause_switch.set_active(cfg.paused)
        self.auto_switch.set_active(cfg.auto_start)
        self.click_switch.set_active(cfg.click_through)
        self.anchor_box.set_active_id(cfg.position.anchor)
        self.size_scale.set_value(cfg.block_size)
        self.size_label.set_text(f"方块大小：{cfg.block_size} px")
        self.opacity_scale.set_value(cfg.opacity)
        self.opacity_label.set_text(f"不透明度：{round(cfg.opacity * 100)}%")
        self._loading = False

    # ---- handlers ---------------------------------------------------------
    def _on_interval_combo(self, combo) -> None:
        if self._loading:
            return
        id_ = combo.get_active_id()
        if not id_:
            return
        self.state.set_rotation(id_)
        self.interval_desc.set_text(self._interval_desc_by_id.get(id_, ""))
        self.refresh()

    def _on_next(self, _btn) -> None:
        self.state.rotate_next()
        self.rotation.restart_after_manual_switch()
        self.refresh()

    def _on_pause(self, sw, _param) -> None:
        if not self._loading:
            self.state.set_paused(sw.get_active())

    def _on_auto(self, sw, _param) -> None:
        if self._loading:
            return
        applied = set_auto_start(sw.get_active()) and sw.get_active()
        self.state.set_auto_start(applied)
        self._loading = True
        sw.set_active(applied)
        self._loading = False

    def _on_click(self, sw, _param) -> None:
        if not self._loading:
            self.state.set_click_through(sw.get_active())

    def _on_opacity(self, scale) -> None:
        if self._loading:
            return
        value = scale.get_value()
        self.state.set_opacity(value)
        self.opacity_label.set_text(f"不透明度：{round(value * 100)}%")

    def _on_anchor(self, combo) -> None:
        if self._loading:
            return
        id_ = combo.get_active_id()
        if id_:
            self.state.set_anchor(id_)

    def _on_size(self, scale) -> None:
        if not self._loading:
            self.state.set_block_size(int(scale.get_value()))
