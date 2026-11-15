"""配置窗口：Gtk.Stack + Gtk.StackSidebar，GNOME 原生的侧边栏导航。"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .periodic_table import PeriodicTablePage  # noqa: E402
from .rotation_page import RotationPage  # noqa: E402


class SettingsWindow(Gtk.Window):
    def __init__(self, app, state, rotation) -> None:
        super().__init__(title="Element Blocks Desktop · 设置")
        self.set_default_size(1160, 780)
        self.set_position(Gtk.WindowPosition.CENTER)

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("Element Blocks Desktop")
        header.set_subtitle("设置")
        self.set_titlebar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        stack.set_transition_duration(180)

        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(stack)
        sidebar.set_size_request(220, -1)

        stack.add_titled(PeriodicTablePage(state), "elements", "元素周期表")
        stack.add_titled(RotationPage(state, rotation), "rotation", "轮换时间")

        box.pack_start(sidebar, False, False, 0)
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        box.pack_start(stack, True, True, 0)
        self.add(box)

        # 关闭只隐藏：窗口常驻内存，托盘左键再次点开时状态不丢
        self.connect("delete-event", self._on_delete)
        app.add_window(self)
        self.show_all()
        stack.set_visible_child_name("elements")

    def _on_delete(self, _window, _event) -> bool:
        self.hide()
        return True
