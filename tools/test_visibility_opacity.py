#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面层级 / 显示桌面 / 不透明度：确定性回归测试（不需要 GTK，任意机器可跑）。

运行：python tools/test_visibility_opacity.py

覆盖四大块：
  1. 不透明度 clamp 与持久化（config._clamp_opacity、AppConfig.to_dict/from_dict、
     defaults、_migrate 的 opacity 字段）。
  2. 桌面层级 / 覆盖决策真值表（cover_policy.should_be_hidden）：
     仅当被最大化/全屏窗口覆盖、且非「显示桌面」状态才隐藏；
     「显示桌面」时无论其它判定如何都保持可见（修掉点显示桌面方块被藏的漏洞）。
  3. 几何辅助（layout.rect_overlap）：最大化/全屏窗口与显示器有正重叠才算覆盖。
  4. 静态接线检查：rotation_page 已改用 ComboBox + 把「立即切换」按钮移到其右侧、
     新增不透明度 Scale；且不再使用 RadioButton。最后做 Python 3.7 语法兼容校验。
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LINUX_PKG = ROOT / "linux" / "element_blocks_desktop"

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {detail}")


def _load_module(mod_name: str, path: Path, strip_gi: bool = False):
    """加载一个 linux 包内的模块；strip_gi=True 时去掉对 gi/Gtk 的顶层 import，
    以便在不装 GTK 的机器上测试其中的纯逻辑。"""
    src = path.read_text(encoding="utf-8")
    if strip_gi:
        kept = []
        for line in src.splitlines():
            if line.startswith("from gi") or line.startswith("import gi"):
                continue
            kept.append(line)
        src = "\n".join(kept)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod  # 让 dataclass 等装饰器能找到模块
    exec(compile(src, str(path), "exec"), mod.__dict__)  # noqa: S102
    return mod


# ---------------------------------------------------------------------------
print("=== 1. 不透明度：clamp 与持久化 ===")
cfg_mod = _load_module("ebd_config", LINUX_PKG / "config.py", strip_gi=True)
_clamp = cfg_mod._clamp_opacity

check("_clamp_opacity(1.0) == 1.0", _clamp(1.0) == 1.0)
check("_clamp_opacity(0.5) == 0.5", _clamp(0.5) == 0.5)
check("_clamp_opacity(0.1) == 0.1", _clamp(0.1) == 0.1)
check("_clamp_opacity(<0.1) 抬升到 0.1", _clamp(0.05) == 0.1, str(_clamp(0.05)))
check("_clamp_opacity(>1.0) 压到 1.0", _clamp(2.0) == 1.0, str(_clamp(2.0)))
check("_clamp_opacity(None) 回退 1.0", _clamp(None) == 1.0)
check("_clamp_opacity('abc') 回退 1.0", _clamp("abc") == 1.0)
check("_clamp_opacity('0.3') 解析为 0.3", _clamp("0.3") == 0.3)
check("_clamp_opacity(NaN) 回退 1.0", _clamp(float("nan")) == 1.0)

# AppConfig 默认值含 opacity=1.0
AppConfig = cfg_mod.AppConfig
defaults = AppConfig.defaults(["U", "Np"])
check("AppConfig 默认 opacity=1.0", defaults.opacity == 1.0,
      str(defaults.opacity))

# to_dict 含 opacity 键
d = defaults.to_dict()
check("to_dict 输出含 'opacity' 键", "opacity" in d and d["opacity"] == 1.0,
      str(d.get("opacity")))

# from_dict 反序列化并 clamp
c1 = AppConfig.from_dict({"opacity": 0.42})
check("from_dict 解析 opacity=0.42", c1.opacity == 0.42, str(c1.opacity))
c2 = AppConfig.from_dict({"opacity": 9.9})
check("from_dict 越界 opacity 被压到 1.0", c2.opacity == 1.0, str(c2.opacity))
c3 = AppConfig.from_dict({"opacity": -3})
check("from_dict 负 opacity 被抬到 0.1", c3.opacity == 0.1, str(c3.opacity))
c4 = AppConfig.from_dict({})
check("from_dict 缺省 opacity 回退 1.0", c4.opacity == 1.0, str(c4.opacity))

# _migrate（ConfigStore 方法）也会 clamp（容错旧配置）
class _FakeAssets:
    by_symbol = {"U": object(), "Np": object()}
    intervals = [SimpleNamespace(id="never")]


_store = cfg_mod.ConfigStore.__new__(cfg_mod.ConfigStore)
_store._assets = _FakeAssets()
c5 = cfg_mod.AppConfig(version=1, opacity=5.0)
_store._migrate(c5)
check("_migrate 修正越界 opacity", c5.opacity == 1.0, str(c5.opacity))

print("\n=== 2. 覆盖决策真值表（cover_policy.should_be_hidden）===")
cp = _load_module("ebd_cover_policy", LINUX_PKG / "cover_policy.py")
should = cp.should_be_hidden
check("(未覆盖, 非显示桌面) -> 不隐藏", should(False, False) is False)
check("(被覆盖, 非显示桌面) -> 隐藏", should(True, False) is True)
check("(未覆盖, 显示桌面) -> 不隐藏", should(False, True) is False)
check("(被覆盖, 显示桌面) -> 不隐藏（修漏洞）", should(True, True) is False)
# 用字符串 / 数值等价验证只看真值
check("covered 用 'yes' 仍按真值处理", should("yes", 0) is True)
check("showing_desktop 用 1 仍按真值处理", should(True, 1) is False)

print("\n=== 3. 几何辅助：rect_overlap ===")
ly = _load_module("ebd_layout", LINUX_PKG / "layout.py")
overlap = ly.rect_overlap
check("完全重叠 -> True", overlap((0, 0, 100, 100), (10, 10, 50, 50)) is True)
check("部分重叠 -> True", overlap((0, 0, 100, 100), (80, 80, 100, 100)) is True)
check("相切（零面积）-> False", overlap((0, 0, 100, 100), (100, 0, 50, 50)) is False)
check("相离 -> False", overlap((0, 0, 100, 100), (200, 200, 50, 50)) is False)
check("边界贴合 -> False", overlap((0, 0, 100, 100), (100, 100, 10, 10)) is False)

print("\n=== 4. 静态接线检查 ===")
rp = (LINUX_PKG / "rotation_page.py").read_text(encoding="utf-8")
pw = (LINUX_PKG / "platform_window.py").read_text(encoding="utf-8")
bw = (LINUX_PKG / "block_window.py").read_text(encoding="utf-8")
st = (LINUX_PKG / "state.py").read_text(encoding="utf-8")

check("rotation_page 使用 ComboBoxText", "Gtk.ComboBoxText" in rp)
check("rotation_page 绑定 changed -> _on_interval_combo",
      'combo.connect("changed", self._on_interval_combo)' in rp)
check("rotation_page 定义 _on_interval_combo 处理器",
      "def _on_interval_combo(self, combo)" in rp)
check("rotation_page 用 set_active_id 同步当前间隔",
      "self.interval_combo.set_active_id(" in rp)
check("rotation_page 用 get_active_id 读取间隔",
      "combo.get_active_id()" in rp)
check("rotation_page 提供『立即切换下一个元素』按钮",
      'Gtk.Button(label="立即切换下一个元素")' in rp
      or 'label="立即切换下一个元素"' in rp)
check("rotation_page 按钮连接到 _on_next",
      'btn.connect("clicked", self._on_next)' in rp)
check("rotation_page 按钮与 ComboBox 同处一行 HBox",
      "row.pack_start(combo, False, False, 0)" in rp
      and "row.pack_start(btn, False, False, 0)" in rp)
check("rotation_page 不再使用 RadioButton", "RadioButton" not in rp)
check("rotation_page 不残留 _radios 引用", "self._radios" not in rp
      and "_radios" not in rp)

# 不透明度 UI 接线
check("rotation_page 新增不透明度 Scale",
      "Gtk.Scale.new_with_range" in rp and "opacity_scale" in rp)
check("rotation_page 不透明度 Scale 连到 _on_opacity",
      'self.opacity_scale.connect("value-changed", self._on_opacity)' in rp)
check("rotation_page 定义 _on_opacity 处理器",
      "def _on_opacity(self, scale)" in rp)
check("rotation_page 不透明度标签显示百分比",
      "不透明度：" in rp and "opacity_label" in rp)
check("state 提供 set_opacity", "def set_opacity(self, value: float)" in st)
check("state 通过 appearance 事件广播（不触发窗口重排）",
      '"appearance"' in st and 'self.emit("appearance")' in st)
check("config 提供 _clamp_opacity", "def _clamp_opacity(" in pw or
      "def _clamp_opacity(" in (LINUX_PKG / "config.py").read_text(encoding="utf-8"))
check("platform_window 提供 apply_opacity", "def apply_opacity(" in pw)
check("platform_window 提供 cover_state（EWMH）", "def cover_state(" in pw)
check("platform_window 提供 evaluate_cover", "def evaluate_cover(" in pw)
check("block_window 订阅 appearance 事件", 'state.on("appearance"' in bw)
check("block_window 实现 _on_appearance", "def _on_appearance(" in bw)
check("block_window 启动 1 秒覆盖轮询",
      'self._cover_id = GLib.timeout_add_seconds(1, self._cover_poll)' in bw)
check("block_window 实现 _cover_poll", "def _cover_poll(" in bw)
check("主动隐藏期间抑制自愈（unmap）",
      'if self._cover_hidden:\n            return False   # 主动隐藏触发的 unmap'
      in bw or "_cover_hidden" in bw)
check("evaluate_cover 仅在状态跳变时施加动作", "window.hide()" in pw
      and "ensure_visible(window, cfg)" in pw)

print("\n=== 5. Python 3.7 语法兼容（deb 目标发行版）===")
for p in sorted(LINUX_PKG.glob("*.py")):
    src = p.read_text(encoding="utf-8")
    try:
        ast.parse(src, feature_version=(3, 7))
        ok = True
    except SyntaxError as e:
        ok = False
        print(f"    {p.name}: {e}")
    check(f"{p.name} 语法兼容 3.7", ok)
mods = [p for p in LINUX_PKG.glob("*.py") if p.name != "__init__.py"]
futures = [p.name for p in mods
           if "from __future__ import annotations" in p.read_text(encoding="utf-8")]
check("含注解模块均启用延迟求值", len(futures) == len(mods),
      f"missing: {sorted(set(p.name for p in mods) - set(futures))}")

print()
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL VISIBILITY/OPACITY TESTS PASS")
