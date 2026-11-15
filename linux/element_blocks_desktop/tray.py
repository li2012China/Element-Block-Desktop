"""系统托盘：优先 Ayatana AppIndicator（StatusNotifierItem / D-Bus），
缺失时回退到 X11 的 Gtk.StatusIcon（XEMBED 旧式 systray）。

平台差异：SNI 规范下"左键"由合成器决定，通常弹出菜单；
因此把"打开设置…"放在菜单第一项，并用 set_secondary_activate_target
（中键 / 部分桌面环境的激活动作）直接打开配置界面。
Gtk.StatusIcon 路径则严格实现"左键打开设置、右键弹出菜单"。
"""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except (ValueError, ImportError):
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator
    except (ValueError, ImportError):
        AppIndicator = None


def icon_path() -> str:
    candidates = [
        Path("/usr/share/icons/hicolor/32x32/apps/element-blocks-desktop.png"),
        Path(__file__).resolve().parent.parent / "data" / "icons" / "hicolor"
        / "32x32" / "apps" / "element-blocks-desktop.png",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return "element-blocks-desktop"   # 交给图标主题查找


class TrayIcon:
    def __init__(self, state, on_open, on_next, on_quit, on_pause, on_auto_start) -> None:
        self.state = state
        self._on_open = on_open
        self._on_next = on_next
        self._on_quit = on_quit
        self._on_pause = on_pause
        self._on_auto_start = on_auto_start
        self._syncing = False

        self.menu = Gtk.Menu()

        open_item = Gtk.MenuItem(label="打开设置…")
        open_item.connect("activate", lambda _w: on_open())
        self.menu.append(open_item)

        next_item = Gtk.MenuItem(label="立即切换下一个元素")
        next_item.connect("activate", lambda _w: on_next())
        self.menu.append(next_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        self.pause_item = Gtk.CheckMenuItem(label="暂停轮换")
        self.pause_item.connect("toggled", self._on_pause_toggled)
        self.menu.append(self.pause_item)

        self.auto_item = Gtk.CheckMenuItem(label="开机自启")
        self.auto_item.connect("toggled", self._on_auto_toggled)
        self.menu.append(self.auto_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="退出")
        quit_item.connect("activate", lambda _w: on_quit())
        self.menu.append(quit_item)
        self.menu.show_all()

        self.indicator = None
        self.status_icon = None
        if AppIndicator is not None:
            try:
                self.indicator = AppIndicator.Indicator.new(
                    "element-blocks-desktop", icon_path(),
                    AppIndicator.IndicatorCategory.APPLICATION_STATUS)
                self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
                self.indicator.set_menu(self.menu)
                if hasattr(self.indicator, "set_secondary_activate_target"):
                    self.indicator.set_secondary_activate_target(open_item)
            except Exception:
                self.indicator = None

        if self.indicator is None:
            # X11 回退：左键 = 打开设置，右键 = 菜单
            self.status_icon = Gtk.StatusIcon.new_from_file(icon_path())
            self.status_icon.connect("activate", lambda _w: on_open())
            self.status_icon.connect("popup-menu", self._popup)

        state.on("element", lambda _e: self.update_tooltip())
        state.on("settings", lambda: self.sync_checks())
        self.update_tooltip()
        self.sync_checks()

    def _popup(self, _icon, button, time):
        self.menu.popup(None, None, None, None, button, time)

    def sync_checks(self) -> None:
        self._syncing = True
        self.pause_item.set_active(self.state.cfg.paused)
        self.auto_item.set_active(self.state.cfg.auto_start)
        self._syncing = False

    def _on_pause_toggled(self, item) -> None:
        if not self._syncing:
            self._on_pause(item.get_active())

    def _on_auto_toggled(self, item) -> None:
        if not self._syncing:
            self._on_auto_start(item.get_active())

    def update_tooltip(self) -> None:
        e = self.state.current
        text = ("Element Blocks Desktop · 未启用任何元素" if e is None
                else f"Element Blocks Desktop · {e.number} {e.name_zh} {e.symbol}")
        if self.indicator is not None and hasattr(self.indicator, "set_title"):
            self.indicator.set_title(text)
        if self.status_icon is not None:
            self.status_icon.set_tooltip_text(text)

    def dispose(self) -> None:
        if self.indicator is not None:
            self.indicator.set_status(AppIndicator.IndicatorStatus.PASSIVE)
        self.status_icon = None
