"""轮换调度：GLib 定时器 + 持久化到配置的 nextFireUtc。

和 Windows 端逻辑一致：每 15 秒用 UTC 对时检查，休眠 / 关机期间不补跑，
恢复后最多补切一次。已启用元素少于 2 个时等同"从不"。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gi.repository import GLib

POLL_SECONDS = 15


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class RotationController:
    def __init__(self, state) -> None:
        self.state = state
        self._source_id = GLib.timeout_add_seconds(1, self._first_tick)
        self._poll_id: int | None = None

    def _first_tick(self) -> bool:
        self.tick()
        self._poll_id = GLib.timeout_add_seconds(POLL_SECONDS, self._poll)
        return False

    def _poll(self) -> bool:
        self.tick()
        return True

    def tick(self) -> None:
        cfg = self.state.cfg
        interval = self.state.assets.interval(cfg.rotation)
        inactive = interval.minutes <= 0 or cfg.paused or len(self.state.enabled_list()) < 2
        if inactive:
            if cfg.next_fire_utc:
                cfg.next_fire_utc = None
                self.state.store.request_save()
            return

        now = utcnow()
        scheduled = parse_utc(cfg.next_fire_utc)
        if scheduled is None or scheduled > now + timedelta(minutes=interval.minutes * 2):
            self._reschedule(now, interval.minutes)
            scheduled = parse_utc(cfg.next_fire_utc)

        if scheduled is not None and now >= scheduled:
            self.state.rotate_next()
            self._reschedule(now, interval.minutes)  # 从"现在"重新计算，不补跑
        self.state.notify_schedule_changed()

    def _reschedule(self, now: datetime, minutes: int) -> None:
        if minutes == 60:
            nxt = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        elif minutes == 1440:
            local_midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
            nxt = (local_midnight + timedelta(days=1)).astimezone(timezone.utc)
        else:
            nxt = now + timedelta(minutes=minutes)
        self.state.cfg.next_fire_utc = iso(nxt)
        self.state.store.request_save()

    def restart_after_manual_switch(self) -> None:
        interval = self.state.assets.interval(self.state.cfg.rotation)
        if interval.minutes > 0 and not self.state.cfg.paused:
            self._reschedule(utcnow(), interval.minutes)
            self.state.notify_schedule_changed()

    def stop(self) -> None:
        for sid in (self._source_id, self._poll_id):
            if sid is not None:
                GLib.source_remove(sid)
