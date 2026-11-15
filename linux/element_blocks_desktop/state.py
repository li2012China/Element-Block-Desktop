"""单一状态源：窗口、托盘、设置页、轮换控制器共享同一份配置对象。"""
from __future__ import annotations

from typing import Callable


class AppState:
    def __init__(self, assets, store) -> None:
        self.assets = assets
        self.store = store
        self.cfg = store.config
        self._enabled: set[str] = set(self.cfg.enabled_symbols)
        # schedule 与 settings 必须分开：轮换器每 15 秒的对时通知只是刷新
        # 倒计时，不能让常驻方块误以为「窗口设置变了」而重新 resize/move。
        self._listeners: dict[str, list[Callable]] = {
            "element": [], "enabled": [], "settings": [], "schedule": [],
            "appearance": []}
        self.current = self._initial_element()

    # ---- observers --------------------------------------------------------
    def on(self, event: str, callback: Callable) -> None:
        self._listeners[event].append(callback)

    def emit(self, event: str, *args) -> None:
        for cb in list(self._listeners[event]):
            cb(*args)

    # ---- elements ---------------------------------------------------------
    def _initial_element(self):
        last = self.cfg.last_symbol
        if last and last in self._enabled:
            return self.assets.by_symbol[last]
        return self.enabled_list()[0] if self.enabled_list() else None

    def enabled_list(self):
        return [e for e in self.assets.elements if e.symbol in self._enabled]

    def is_enabled(self, symbol: str) -> bool:
        return symbol in self._enabled

    def _sync_to_config(self) -> None:
        self.cfg.enabled_symbols = [e.symbol for e in self.assets.elements if e.symbol in self._enabled]
        self.store.request_save()

    def set_enabled(self, symbol: str, value: bool) -> None:
        if value:
            if symbol in self._enabled:
                return
            self._enabled.add(symbol)
        else:
            if symbol not in self._enabled:
                return
            self._enabled.remove(symbol)
        self._sync_to_config()
        if not value and self.current and self.current.symbol == symbol:
            lst = self.enabled_list()
            self.current = lst[0] if lst else None
        elif value and self.current is None:
            self.current = self.assets.by_symbol.get(symbol)
        self.cfg.last_symbol = self.current.symbol if self.current else None
        self.emit("enabled")
        self.emit("element", self.current)

    def set_all(self, value: bool) -> None:
        self._enabled = {e.symbol for e in self.assets.elements} if value else set()
        self._after_bulk()

    def only_natural(self) -> None:
        self._enabled = {e.symbol for e in self.assets.elements if not e.synthetic}
        self._after_bulk()

    def reset_defaults(self) -> None:
        from .config import AppConfig
        d = AppConfig.defaults([e.symbol for e in self.assets.elements])
        self._enabled = set(d.enabled_symbols)
        self.cfg.rotation = d.rotation
        self.cfg.position = d.position
        self.cfg.block_size = d.block_size
        self.cfg.click_through = d.click_through
        self.cfg.paused = d.paused
        self.cfg.opacity = d.opacity
        self.cfg.last_symbol = d.last_symbol
        self.cfg.next_fire_utc = None
        self.cfg.rotation_cursor = 0
        self._after_bulk()

    def _after_bulk(self) -> None:
        self._sync_to_config()
        self.current = self._initial_element()
        self.cfg.last_symbol = self.current.symbol if self.current else None
        self.cfg.next_fire_utc = None
        self.emit("enabled")
        self.emit("element", self.current)
        self.emit("settings")

    # ---- rotation ---------------------------------------------------------
    def rotate_next(self) -> None:
        lst = self.enabled_list()
        if not lst:
            return
        idx = next((i for i, e in enumerate(lst)
                    if self.current and e.symbol == self.current.symbol), -1)
        nxt = 0 if idx < 0 else (idx + 1) % len(lst)
        self.cfg.rotation_cursor = nxt
        self.show_element(lst[nxt])

    def show_element(self, element) -> None:
        self.current = element
        self.cfg.last_symbol = element.symbol if element else None
        self.store.request_save()
        self.emit("element", element)

    def set_rotation(self, id_: str) -> None:
        self.cfg.rotation = id_
        self.cfg.next_fire_utc = None
        self.store.request_save()
        self.emit("settings")

    def set_paused(self, value: bool) -> None:
        self.cfg.paused = value
        self.cfg.next_fire_utc = None
        self.store.request_save()
        self.emit("settings")

    def set_auto_start(self, value: bool) -> None:
        self.cfg.auto_start = value
        self.store.request_save()

    def set_click_through(self, value: bool) -> None:
        self.cfg.click_through = value
        self.store.request_save()
        self.emit("settings")

    def set_opacity(self, value: float) -> None:
        from .config import _clamp_opacity
        self.cfg.opacity = _clamp_opacity(value)
        self.store.request_save()
        # 只刷新外观，不触发窗口重排（geometry_signature 不含 opacity）
        self.emit("appearance")

    def set_anchor(self, anchor: str) -> None:
        self.cfg.position.anchor = anchor
        self.store.request_save()
        self.emit("settings")

    def set_block_size(self, size: int) -> None:
        self.cfg.block_size = max(80, min(320, int(size)))
        self.store.request_save()
        self.emit("settings")

    def notify_schedule_changed(self) -> None:
        """排程 / 倒计时刷新：只通知设置页，不触发窗口重排。"""
        self.emit("schedule")
