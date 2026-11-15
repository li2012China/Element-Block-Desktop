"""方块「是否应因窗口覆盖而隐藏」的纯决策（不依赖 GTK，可单测）。

决策只回答一个问题：给定「本显示器是否存在最大化/全屏窗口」与
「是否处于显示桌面状态」，方块该不该被隐藏。全部 X11 细节留在
``platform_window.cover_state()`` 里，那一层需要 GI 且只能在真机验证；
这里的真值表是确定性的、与后端无关的。
"""
from __future__ import annotations


def should_be_hidden(covered: bool, showing_desktop: bool) -> bool:
    """仅当被最大化/全屏窗口覆盖、且不在「显示桌面」状态下才隐藏。

    「显示桌面」(``_NET_SHOWING_DESKTOP == 1``) 意味桌面本就露出，
    方块必须保持可见——这条规则也直接修掉了「点显示桌面反而把方块藏起来」
    的漏洞：显示桌面时即使有其它覆盖判定也一律不隐藏。
    """
    return bool(covered) and not bool(showing_desktop)
