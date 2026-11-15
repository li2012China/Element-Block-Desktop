"""配置持久化（XDG Base Directory + 原子写 + 防抖 + 容错迁移）。

路径：$XDG_CONFIG_HOME/element-blocks-desktop/config.json
      未设置 XDG_CONFIG_HOME 时为 ~/.config/element-blocks-desktop/config.json
安装包只往 /usr/share 写只读数据，用户配置永远在 home 下，
因此升级 / 重装 deb 不会丢设置。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from gi.repository import GLib


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return Path(base).expanduser() if base else Path.home() / ".config"


def _clamp_opacity(value) -> float:
    """不透明度必须落在 0.1~1.0；非法值（None / 负数 / 字符串）回退到 1.0。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 1.0
    if v != v:  # NaN
        return 1.0
    return max(0.1, min(1.0, v))


APP_DIR = config_dir() / "element-blocks-desktop"
CONFIG_FILE = APP_DIR / "config.json"
INSTANCE_LOCK = APP_DIR / "instance.lock"
AUTOSTART_DIR = config_dir() / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "element-blocks-desktop.desktop"
SYSTEM_AUTOSTART = Path("/usr/share/element-blocks-desktop/element-blocks-desktop-autostart.desktop")


@dataclass
class Position:
    anchor: str = "TopRight"
    offset_x: int = 32
    offset_y: int = 32
    monitor_index: int = 0

    def to_dict(self) -> dict:
        return {"anchor": self.anchor, "offsetX": self.offset_x,
                "offsetY": self.offset_y, "monitorIndex": self.monitor_index}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Position":
        d = d or {}
        return cls(anchor=d.get("anchor", "TopRight"),
                   offset_x=int(d.get("offsetX", 32)),
                   offset_y=int(d.get("offsetY", 32)),
                   monitor_index=max(0, int(d.get("monitorIndex", 0))))


@dataclass
class AppConfig:
    version: int = 1
    enabled_symbols: list[str] = field(default_factory=list)
    rotation: str = "never"
    position: Position = field(default_factory=Position)
    block_size: int = 132
    # 1.0.0-4：默认由 True 改为 False。空 input shape 会把单击交给桌面组件，
    # 桌面组件 raise 自己后会把 keep_below 的方块盖住 —— 即「单击后消失」。
    # 现在方块默认吞掉自身点击；用户仍可在设置页显式开启穿透。
    click_through: bool = False
    auto_start: bool = False
    paused: bool = False
    opacity: float = 1.0   # 方块不透明度 0.1~1.0（1.0 完全不透明）
    last_symbol: str | None = "U"
    next_fire_utc: str | None = None
    rotation_cursor: int = 0

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "enabledSymbols": self.enabled_symbols,
            "rotation": self.rotation,
            "position": self.position.to_dict(),
            "blockSize": self.block_size,
            "clickThrough": self.click_through,
            "autoStart": self.auto_start,
            "paused": self.paused,
            "opacity": self.opacity,
            "lastSymbol": self.last_symbol,
            "nextFireUtc": self.next_fire_utc,
            "rotationCursor": self.rotation_cursor,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AppConfig":
        return cls(
            version=int(d.get("version", 1)),
            enabled_symbols=list(d.get("enabledSymbols") or []),
            rotation=str(d.get("rotation", "never")),
            position=Position.from_dict(d.get("position")),
            block_size=int(d.get("blockSize", 132)),
            click_through=bool(d.get("clickThrough", False)),
            auto_start=bool(d.get("autoStart", False)),
            paused=bool(d.get("paused", False)),
            opacity=_clamp_opacity(d.get("opacity", 1.0)),
            last_symbol=d.get("lastSymbol", "U"),
            next_fire_utc=d.get("nextFireUtc"),
            rotation_cursor=max(0, int(d.get("rotationCursor", 0))),
        )

    @classmethod
    def defaults(cls, symbols: list[str]) -> "AppConfig":
        return cls(enabled_symbols=list(symbols))


class ConfigStore:
    def __init__(self, assets) -> None:
        self._assets = assets
        self._timer_id: int | None = None
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.config = self._load()

    # ---- load / migrate ---------------------------------------------------
    def _load(self) -> AppConfig:
        if not CONFIG_FILE.exists():
            cfg = AppConfig.defaults([e.symbol for e in self._assets.elements])
            self._write(cfg)
            return self._migrate_click_guard(cfg)
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return self._migrate_click_guard(self._migrate(AppConfig.from_dict(raw)))
        except Exception:
            # 不静默丢弃：保留损坏文件供人工排查
            try:
                shutil.copy2(CONFIG_FILE, CONFIG_FILE.with_suffix(".json.bak"))
            except OSError:
                pass
            cfg = AppConfig.defaults([e.symbol for e in self._assets.elements])
            self._write(cfg)
            return self._migrate_click_guard(cfg)

    def _migrate_click_guard(self, cfg: AppConfig) -> AppConfig:
        """1.0.0-4 一次性迁移：把旧版默认的「点击穿透」重置为安全值。

        1.0.0-1..3 的 clickThrough 默认 True，会在旧配置里留下 true。升级时
        只做一次重置（用同目录标记文件记录），之后用户在设置页的显式选择
        不再被覆盖。标记文件不是 config.json 的一部分，不影响 schema。
        """
        marker = APP_DIR / "click-guard-v4"
        if marker.exists():
            return cfg
        changed = cfg.click_through
        if changed:
            cfg.click_through = False
        try:
            marker.write_text("Element Blocks Desktop 1.0.0-4 click guard\n",
                              encoding="utf-8")
            if changed:
                self._write(cfg)
        except OSError:
            pass
        return cfg

    def _migrate(self, cfg: AppConfig) -> AppConfig:
        known = set(self._assets.by_symbol)
        seen: set[str] = set()
        cfg.enabled_symbols = [s for s in cfg.enabled_symbols
                              if s in known and not (s in seen or seen.add(s))]
        if cfg.rotation not in {i.id for i in self._assets.intervals}:
            cfg.rotation = "never"
        if cfg.position.anchor not in ("TopLeft", "TopRight", "BottomLeft", "BottomRight", "Custom"):
            cfg.position.anchor = "TopRight"
        cfg.block_size = max(80, min(320, cfg.block_size))
        cfg.opacity = _clamp_opacity(cfg.opacity)
        if cfg.last_symbol and cfg.last_symbol not in known:
            cfg.last_symbol = None
        if cfg.next_fire_utc:
            try:
                t = datetime.fromisoformat(cfg.next_fire_utc.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - t).days > 730:
                    cfg.next_fire_utc = None
            except (ValueError, TypeError):
                cfg.next_fire_utc = None
        cfg.version = 1  # v1 → v2 的迁移分支以后加在这里
        return cfg

    # ---- save -------------------------------------------------------------
    def request_save(self) -> None:
        """防抖 400ms；UI 上连续点按元素不会反复落盘。"""
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
        self._timer_id = GLib.timeout_add(400, self._flush)

    def _flush(self) -> bool:
        self._timer_id = None
        self._write(self.config)
        return False  # GLib.SOURCE_REMOVE

    def flush(self) -> None:
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        self._write(self.config)

    def _write(self, cfg: AppConfig) -> None:
        """同目录临时文件 + fsync + os.replace：避免半写文件。"""
        APP_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=str(APP_DIR))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, CONFIG_FILE)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def set_auto_start(enable: bool) -> bool:
    """Debian 的开机自启用 XDG autostart .desktop（无需 systemd 用户服务）。"""
    try:
        if enable:
            AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            src = SYSTEM_AUTOSTART if SYSTEM_AUTOSTART.exists() else (
                Path(__file__).resolve().parent.parent / "data" / "element-blocks-desktop-autostart.desktop")
            shutil.copy2(src, AUTOSTART_FILE)
        elif AUTOSTART_FILE.exists():
            AUTOSTART_FILE.unlink()
        return True
    except OSError:
        return False
