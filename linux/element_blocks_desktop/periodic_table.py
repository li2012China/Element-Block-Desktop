"""第一页：GTK3 原生 Gtk.Grid 摆出 118 个元素卡片（Gtk.ToggleButton）。

网格坐标来自 shared/elements.json，与 WinUI3 端完全一致。
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

CELL_W = 60
CELL_H = 62


def esc(text: str) -> str:
    return GLib.markup_escape_text(text)


class PeriodicTablePage(Gtk.Box):
    def __init__(self, state) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.state = state
        self.set_border_width(16)
        self._buttons: dict[str, Gtk.ToggleButton] = {}
        self._refreshing = False

        title = Gtk.Label()
        title.set_markup('<span size="x-large" weight="bold">元素周期表</span>')
        title.set_xalign(0)
        self.pack_start(title, False, False, 0)
        sub = Gtk.Label(label="点按卡片启用或禁用该元素；只有已启用的元素会参与自动轮换。变淡的卡片表示已禁用。")
        sub.set_xalign(0)
        sub.set_line_wrap(True)
        self.pack_start(sub, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, cb in (("全选", self._all), ("全不选", self._none),
                          ("仅天然元素", self._natural), ("恢复默认", self._reset)):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            toolbar.pack_start(b, False, False, 0)
        self.count_label = Gtk.Label()
        toolbar.pack_end(self.count_label, False, False, 8)
        self.pack_start(toolbar, False, False, 0)

        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for key, style in state.assets.theme["categories"].items():
            name = next((e.category_label for e in state.assets.elements
                         if e.category == key), key)
            lab = Gtk.Label()
            lab.set_markup(
                f'<span background="{style["fill"]}" foreground="{style["text"]}">  ■  </span>'
                f' <span size="small">{esc(name)}</span>')
            legend.pack_start(lab, False, False, 0)
        self.pack_start(legend, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        self.grid = Gtk.Grid()
        self.grid.set_row_spacing(2)
        self.grid.set_column_spacing(2)
        self.grid.set_border_width(8)
        scroll.add(self.grid)
        self.pack_start(scroll, True, True, 0)

        self._install_css()
        self._build_grid()
        self.refresh()
        state.on("enabled", self.refresh)

    def _install_css(self) -> None:
        rules = [
            "button.el-tile { background-image: none; border-style: solid; "
            "border-width: 1px; border-radius: 2px; padding: 1px; }",
            "button.el-tile:checked, button.el-tile:active { background-image: none; }",
        ]
        for key, s in self.state.assets.theme["categories"].items():
            for state_name in ("", ":checked", ":active"):
                rules.append(
                    f"button.el-tile.cat-{key}{state_name} {{ background-color: {s['fill']}; "
                    f"border-color: {s['border']}; color: {s['text']}; }}")
        provider = Gtk.CssProvider()
        provider.load_from_data("\n".join(rules).encode("utf-8"))
        screen = Gdk.Screen.get_default()
        if screen:
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _build_grid(self) -> None:
        layout = self.state.assets.layout
        for c in range(1, layout["columns"] + 1):
            lab = Gtk.Label(label=layout["groupLabels"].get(str(c), str(c)))
            lab.set_size_request(CELL_W, 20)
            self.grid.attach(lab, c, 0, 1, 1)
        for r in range(1, 8):
            lab = Gtk.Label(label=str(r))
            lab.set_size_request(26, CELL_H)
            self.grid.attach(lab, 0, r, 1, 1)

        for row, text in ((9, "镧系"), (10, "锕系")):
            lab = Gtk.Label(label=text)
            self.grid.attach(lab, 1, row, 2, 1)

        for p in layout["placeholders"]:
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
            frame.set_size_request(CELL_W, CELL_H)
            lab = Gtk.Label()
            lab.set_markup(f'<span size="small">{esc(p["label"])}</span>\n'
                           f'<span size="small" weight="bold">{esc(p["subLabel"])}</span>')
            lab.set_justify(Gtk.Justification.CENTER)
            frame.add(lab)
            self.grid.attach(frame, p["column"], p["row"], 1, 1)

        for e in self.state.assets.elements:
            btn = self._make_button(e)
            self.grid.attach(btn, e.column, e.row, 1, 1)
            self._buttons[e.symbol] = btn

    def _make_button(self, e) -> Gtk.ToggleButton:
        tile = self.state.assets.theme["tile"]
        style = self.state.assets.style(e.category)
        accent = tile["accent"] if e.radioactive else style["text"]

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        num = Gtk.Label()
        num.set_markup(f'<span foreground="{accent}" size="x-small">{e.number}</span>')
        num.set_xalign(0)
        sym = Gtk.Label()
        sym.set_markup(f'<span foreground="{accent}" weight="bold">{esc(e.symbol)}</span>')
        sym.set_xalign(1)
        top.pack_start(num, True, True, 0)
        top.pack_start(sym, True, True, 0)

        zh = Gtk.Label()
        zh.set_markup(f'<span foreground="{style["text"]}" size="large">{esc(e.name_zh)}</span>')
        zh.set_justify(Gtk.Justification.CENTER)
        zh.set_vexpand(True)
        mass = Gtk.Label()
        mass.set_markup(f'<span foreground="{style["text"]}" size="x-small">{esc(e.mass)}</span>')

        box.pack_start(top, False, False, 0)
        box.pack_start(zh, True, True, 0)
        box.pack_start(mass, False, False, 0)

        btn = Gtk.ToggleButton()
        btn.add(box)
        btn.set_size_request(CELL_W, CELL_H)
        btn.set_tooltip_text(e.tooltip)
        ctx = btn.get_style_context()
        ctx.add_class("el-tile")
        ctx.add_class("cat-" + e.category)
        btn.connect("toggled", self._on_toggled, e.symbol)
        return btn

    def _on_toggled(self, btn, symbol) -> None:
        if self._refreshing:
            return
        self.state.set_enabled(symbol, btn.get_active())

    def refresh(self) -> None:
        self._refreshing = True
        opacity = self.state.assets.theme["tile"]["disabledOpacity"]
        for symbol, btn in self._buttons.items():
            on = self.state.is_enabled(symbol)
            btn.set_active(on)
            btn.set_opacity(1.0 if on else opacity)
        total = len(self.state.assets.elements)
        self.count_label.set_text(f"已启用 {len(self.state.cfg.enabled_symbols)} / {total}")
        self._refreshing = False

    # ---- toolbar ----------------------------------------------------------
    def _all(self, _b) -> None: self.state.set_all(True)
    def _none(self, _b) -> None: self.state.set_all(False)
    def _natural(self, _b) -> None: self.state.only_natural()
    def _reset(self, _b) -> None: self.state.reset_defaults()
