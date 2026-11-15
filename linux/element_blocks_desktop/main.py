"""进程入口。

单实例：Gtk.Application 带 application_id 时通过会话 D-Bus 自动保证单实例——
第二次运行会把 activate 转发给首个进程，首个进程只做 "打开设置窗口"。
常驻方块窗口始终存在，因此 Gtk.Application 不会因为窗口关闭而退出；
只有托盘菜单的"退出"会结束进程。
"""
from __future__ import annotations

import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from .assets import Assets  # noqa: E402
from .block_window import BlockWindow  # noqa: E402
from .config import ConfigStore, set_auto_start  # noqa: E402
from .rotation import RotationController  # noqa: E402
from .settings_window import SettingsWindow  # noqa: E402
from .state import AppState  # noqa: E402
from .tray import TrayIcon  # noqa: E402

APPLICATION_ID = "org.elementblocks.Desktop"


class ElementBlocksApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APPLICATION_ID,
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        GLib.set_application_name("Element Blocks Desktop")
        self._started = False
        self._settings: SettingsWindow | None = None
        self.tray: TrayIcon | None = None

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        # 方块是唯一窗口。即使 WM 意外发来关闭请求、或某个窗口被销毁，
        # 也不允许 Gtk.Application 因「最后一个窗口没了」而自行退出。
        # 退出统一由托盘菜单的 quit_app() 负责（release + quit）。
        self.hold()

    def do_activate(self) -> None:
        if self._started:
            self.show_settings()
            return
        self._started = True

        self.assets = Assets()
        self.store = ConfigStore(self.assets)
        self.state = AppState(self.assets, self.store)
        self.rotation = RotationController(self.state)

        self.block = BlockWindow(self.state)
        self.add_window(self.block)

        self.tray = TrayIcon(
            self.state,
            on_open=self.show_settings,
            on_next=self.next_element,
            on_quit=self.quit_app,
            on_pause=lambda v: self.state.set_paused(v),
            on_auto_start=self._on_auto_start,
        )

        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig,
                                 lambda s=sig: self.quit_app() or False)

    def _on_auto_start(self, want: bool) -> None:
        applied = set_auto_start(want) and want
        self.state.set_auto_start(applied)
        if self.tray:
            self.tray.sync_checks()

    def show_settings(self) -> None:
        if self._settings is None:
            self._settings = SettingsWindow(self, self.state, self.rotation)
        self._settings.present()

    def next_element(self) -> None:
        self.state.rotate_next()
        self.rotation.restart_after_manual_switch()

    def quit_app(self) -> None:
        if self.tray:
            self.tray.dispose()
        self.rotation.stop()
        self.store.flush()
        block = getattr(self, "block", None)
        if block is not None and hasattr(block, "begin_shutdown"):
            # 退出时 GTK 会 unmap 所有窗口；先关掉自愈，避免把窗口又拉回来
            block.begin_shutdown()
        self.release()
        Gtk.Application.quit(self)


def main(argv=None) -> int:
    return ElementBlocksApp().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
