"""常驻方块的「单击不改状态」与「可见性自愈」策略（纯计算，不依赖 GTK）。

背景（1.0.0-4）：Linux 端单击元素方块后方块会意外消失。旧实现有三处缺口：

  1. ``BlockWindow`` 没有任何 button-press-event 处理。默认 ``clickThrough=True``
     给 GDK 窗口设了空 input shape，单击直接落到下面的桌面组件；deepin / UOS
     的 dde-desktop、GNOME 的桌面图标窗口、Plasma 桌面等收到点击会 raise 自己，
     而方块是 ``_NET_WM_STATE_BELOW`` 且从不重新声明层级，于是被盖住 → 看起来消失。
  2. 窗口没有 delete-event / window-state-event / map-event / unmap-event /
     visibility-notify-event 处理，一旦被 WM 撤回、最小化、随工作区切换隐藏，
     甚至收到 WM_DELETE_WINDOW 被 GTK 默认销毁，就再也不会恢复；方块是
     ``Gtk.Application`` 的唯一窗口，销毁还会连带退出进程（未调用 hold()）。
  3. 轮换器每 15 秒 ``emit("settings")``，导致 ``apply_window_flags()`` →
     ``window.resize()`` → ``configure-event`` → ``place()`` → ``window.move()``，
     桌面层窗口被反复重排，某些 WM 会趁机把它压到桌面组件下面。

本模块把「收到事件 → 该做什么」抽成纯函数 / 小状态机，不 import gi，
因此可以在没有 GTK 的机器上用 ``tools/test_click_guard.py`` 做确定性回归。

不变量：**单击方块不得改变窗口的可见性、层级、位置、尺寸或当前元素，
也不得改变配置。**
"""
from __future__ import annotations

COOLDOWN_MS = 400        # 两次自愈之间的最小间隔，避免与窗口管理器抢栈
MAX_RESTORES = 3         # 每个观察窗口内最多自愈次数（熔断）
RESET_WINDOW_MS = 5000   # 静默 5 秒后重置熔断计数

IGNORE = "ignore"        # 什么也不做
RESTORE = "restore"      # 恢复可见性 / 层级（不改几何与元素）
REAPPLY = "reapply"      # 重新声明窗口属性 / 位置 / 输入形状


def geometry_signature(cfg) -> tuple:
    """只取会真正影响窗口几何或命中区域的字段。

    轮换排程（nextFireUtc）、暂停、开机自启、当前元素等变化**不应**触发
    resize / move，否则 15 秒一次的 tick 会重排桌面层窗口。
    """
    p = cfg.position
    return (int(cfg.block_size), str(p.anchor), int(p.offset_x),
            int(p.offset_y), int(p.monitor_index), bool(cfg.click_through))


def click_actions(button: int, click_through: bool) -> dict[str, bool]:
    """单击策略：吞掉事件即可，绝不产生任何副作用。

    ``consume=True`` 表示 button-press-event 返回 True（GDK_EVENT_STOP），
    GTK 的默认处理与向下的传播都被截断。button / click_through 只作记录，
    不改变策略——设置里开启穿透时事件根本到不了本窗口，由自愈逻辑兜底。
    """
    return {
        "consume": True,
        "change_element": False,
        "hide": False,
        "unmap": False,
        "destroy": False,
        "move": False,
        "resize": False,
        "quit": False,
        "change_focus": False,
    }


def keep_window_on_delete(quitting: bool) -> bool:
    """delete-event 一律返回 True，阻止 GTK 的默认 destroy。

    即使进程正在退出也返回 True：退出统一由托盘菜单的 ``Gtk.Application.quit()``
    负责，窗口不该被 WM 的关闭请求单独拆掉。
    """
    return True


class WidgetGuard:
    """把 GTK 信号归一成有限个动作，并负责防抖与熔断。

    ``now_ms`` 由调用方传入（GLib.get_monotonic_time() // 1000），
    这样本类不读时钟、不做 IO，测试里可以精确构造时间序列。
    """

    def __init__(self, now_ms: int = 0) -> None:
        self.quitting = False
        self.click_count = 0
        self._last_restore = -10 ** 9
        self._restores = 0
        self._window_start = int(now_ms)

    def mark_quitting(self) -> None:
        """进程退出前调用：退出过程中 GTK 会 unmap 所有窗口，此时不要复活方块。"""
        self.quitting = True

    # ---- 单击 -------------------------------------------------------------
    def click(self, button: int, click_through: bool) -> dict[str, bool]:
        self.click_count += 1
        return click_actions(button, click_through)

    def on_delete(self, _event=None) -> bool:
        return keep_window_on_delete(self.quitting)

    # ---- 配置变化 ---------------------------------------------------------
    def settings_action(self, old_sig: tuple, new_sig: tuple) -> str:
        return REAPPLY if old_sig != new_sig else IGNORE

    # ---- 可见性与层级 -----------------------------------------------------
    def on_visibility(self, state_name: str, now_ms: int) -> str:
        """只在「完全被遮挡」时恢复，普通窗口盖住方块属于正常桌面层行为。"""
        if self.quitting or state_name != "fully_obscured":
            return IGNORE
        return self._throttled(RESTORE, now_ms)

    def on_window_state(self, withdrawn: bool, iconified: bool,
                        below: bool | None, now_ms: int) -> str:
        if self.quitting:
            return IGNORE
        if withdrawn or iconified:
            return self._throttled(RESTORE, now_ms)
        # 不能依据 below 缺失就 REAPPLY：DESKTOP 类型窗口的 BELOW 常由 WM
        # 按 type hint 隐式处理，GDK 不一定上报，据此反复重排会造成周期性
        # resize/move。层级重新声明统一放在 ensure_visible() 里做。
        return IGNORE

    def on_map(self, now_ms: int) -> str:
        """重新映射后 X property / input shape 会丢，必须重新声明一次。"""
        if self.quitting:
            return IGNORE
        return REAPPLY

    def on_unmap(self, now_ms: int) -> str:
        if self.quitting:
            return IGNORE
        return self._throttled(RESTORE, now_ms)

    def on_watchdog(self, visible: bool, withdrawn: bool,
                    iconified: bool, now_ms: int) -> str:
        """兜底：某些 WM 不发 VisibilityNotify，用 2 秒轮询补上。"""
        if self.quitting:
            return IGNORE
        if not visible or withdrawn or iconified:
            return self._throttled(RESTORE, now_ms)
        return IGNORE

    # ---- 内部 -------------------------------------------------------------
    def _throttled(self, action: str, now_ms: int) -> str:
        now_ms = int(now_ms)
        if now_ms - self._window_start >= RESET_WINDOW_MS:
            self._restores = 0
            self._window_start = now_ms
        if self._restores >= MAX_RESTORES:
            return IGNORE
        if now_ms - self._last_restore < COOLDOWN_MS:
            return IGNORE
        self._last_restore = now_ms
        self._restores += 1
        return action
