# 托盘与常驻窗口行为

## 1. 启动流程与窗口生命周期

```
进程启动
  └─ 单实例判定
       ├─ 已有实例 → 通知它打开设置 → 本进程立即退出
       └─ 首个实例
            ├─ 加载 shared/*.json（只读数据契约）
            ├─ 读 config.json（不存在则写默认值）
            ├─ 创建【常驻方块窗口】并 Activate / show
            ├─ 施加"桌面层"窗口样式 + 按锚点定位
            ├─ 创建【系统托盘图标】+ 右键菜单
            ├─ 启动轮换调度器（15s 对时轮询）
            └─ 停在消息循环 —— 不创建设置窗口
托盘左键 / 菜单"打开设置"
  └─ 创建或 present【设置窗口】（侧边栏 + 两页）
       └─ 关闭时只 hide（Linux）/ 释放引用（WinUI3），进程继续运行
托盘菜单"退出"
  └─ 移除托盘图标 → 停调度器 → 强制落盘 → 关窗 → 退出进程
```

关键点：**常驻窗口在进程生命周期内从不关闭**。WinUI3 默认在最后一个窗口关闭时结束应用，GTK 的 `Gtk.Application` 同理；因为方块窗口一直存在，关闭设置窗口不会误退出。Windows 端退出走 `Environment.Exit(0)`，Linux 端走 `Gtk.Application.quit()`。

Linux 端在 1.0.0-4 又加了两道保险：`BlockWindow.delete-event` 恒返回 `True`（阻止 GTK 默认 destroy），`Gtk.Application.hold()` 让"最后一个窗口意外消失"也不再连带退出进程；退出时先 `begin_shutdown()` 关闭自愈，再 `release() + quit()`。详见 §3.4。

单实例也顺带解决了"托盘被点两次就出现两个方块"的问题：Windows 用命名 `Mutex` + `EventWaitHandle`，第二个进程只 Set 事件；Linux 用 `Gtk.Application` 的 D-Bus 唯一名称，第二个进程的 `activate` 被转发给首个进程，首个进程只 `present()` 设置窗口。

## 2. 不在任务栏显示

| Windows | Debian |
|---|---|
| `WS_EX_TOOLWINDOW`，并清除 `WS_EX_APPWINDOW`（否则后者会覆盖前者）；`AppWindow.IsShownInSwitchers=false`；`WS_EX_NOACTIVATE` 保证点击不抢焦点 | `set_skip_taskbar_hint(True)` / `set_skip_pager_hint(True)` → `_NET_WM_STATE_SKIP_TASKBAR` / `SKIP_PAGER`；`set_accept_focus(False)`、`set_focus_on_map(False)` |
| 无边框：`OverlappedPresenter.SetBorderAndTitleBar(false,false)` | `set_decorated(False)`、`set_resizable(False)` |

注意：WinUI3 的"隐藏任务栏"本质是 **Win32 样式**，不是 XAML 属性，所以必须在 `WindowNative.GetWindowHandle()` 之后调用 `SetWindowLongPtr`，并用 `SetWindowPos(..., SWP_FRAMECHANGED)` 让样式生效。

## 3. 常驻在桌面固定位置

### 3.1 位置计算
配置里的 `position` 是 `{anchor, offsetX, offsetY, monitorIndex}`，而不是裸坐标，这样换分辨率/换显示器也不会跑偏：

```
workArea = 指定显示器的工作区（已扣除任务栏 / dock）
size     = fit_size(blockSize, workArea)      # 先按工作区收敛，不放大配置值
winSize  = 窗口的真实宽高（不是名义 blockSize）
x = anchor 含 Right  ? workArea.right  - winSize.w - offsetX : workArea.left + offsetX
y = anchor 含 Bottom ? workArea.bottom - winSize.h - offsetY : workArea.top  + offsetY
最后 clamp 到「工作区 ∩ 整屏」内，保证方块四边不被推出屏幕
```

- Windows：`EnumDisplayMonitors` + `GetMonitorInfoW(...).rcWork`；`GetDpiForWindow` 把配置里的 CSS 像素换算成物理像素（PerMonitorV2）；`WM_DISPLAYCHANGE` 时 `DesktopWindowService.Reposition()`。
- Linux：`Gdk.Display.get_monitor(index).get_workarea()`（应用像素）→ 乘 `get_scale_factor()` 换算成设备像素；`monitors-changed` / `size-changed` / `monitor-added|removed` 触发重定位。Wayland 下 `window.move()` 被忽略，见 `01-platform-differences.md`。

**缩放与 WM 兜底（1.0.0-3）**：早期版本用 `blockSize` 这个名义尺寸做 clamp，在 1.5x / 2x 缩放或窗口管理器放大窗口后会失效，方块右上角跑出屏幕。现在用 `gdk_window_get_width/height()` 的真实尺寸定位，尺寸用 `Gdk.Geometry + set_geometry_hints(min=max)` 锁定；`move()` 之后延时读回窗口原点，若仍越界就按「请求坐标 → 实测原点」的比例自动校正——这样既不假设 `gtk_window_move()` 的参数是逻辑像素还是设备像素，也能覆盖窗口管理器延迟重排。`configure-event` 里再做一次带冷却的收敛。纯计算部分在 `layout.py`，回归用例见 `tools/test_layout.py`。

**卡片文字不会越界**：整张卡片绘制前先 `cr.clip()` 到方块矩形；每行文字在独立文本框里按 Pango 实测宽高等比缩字号，超长英文名（`Rutherfordium` 等）用省略号收尾，底部相对原子质量按实测行高上移并留出 4px 内边距。窗口被拉成非正方形时卡片居中、按 `min(宽,高)` 等比缩放。字体、配色、内容与轮换逻辑不变。

### 3.2 层级：壁纸之上、普通窗口之下（桌面层；Windows 1.0.1.3 起钉死置底）
- Windows：**1.0.1.2 曾改用 `SetTopMost(true)`（置顶不抢焦点）；1.0.1.3 起改为真正的"桌面层"置底窗口**（与 Linux 的 BELOW/DESKTOP 哲学对齐），详见 §3.7。要点：`DesktopWindowService.PinToBottom(hwnd)` 用 `HWND_BOTTOM` + 子类化拦截 `WM_WINDOWPOSCHANGING` 把一切 z 变更改写为沉底——点击、激活、外部 `SetWindowPos(HWND_TOP)` 都不会让方块上浮；配合 `WS_EX_NOACTIVATE`（点击不抢焦点）方块永远不遮挡任何窗口。普通窗口与其重叠时只是被视觉覆盖、不隐藏；真正的"隐藏"仍只由 `EvaluateVisibility` 在**最大化/全屏**时触发。
- Windows 覆盖检测（**1.0.1.2 修正**）：`DesktopWindowService.IsCoveredByZoomedOrFullscreen(hwnd)` **只检查前台窗口**（及其 `GetAncestor(GA_ROOT)` 根窗口）：`IsZoomed` 为真、或窗口矩形完整覆盖其所在显示器 `rcMonitor`，且与方块矩形正重叠时才算覆盖。之所以不再枚举全部顶层窗口：Windows 上大量**后台挂起的 UWP 窗口**（「设置」「照片」的 `ApplicationFrameWindow`、`Windows 输入体验` 等）会保留**整屏矩形**且 `IsWindowVisible=true`，枚举法会把它们误判为"全屏窗口"，导致"有任意未最小化窗口，方块就隐藏"——这正是 1.0.0.5 的真实 Bug。此外仍跳过 DWM cloak 窗口（`DWMWA_CLOAKED`）与桌面壳层（`Progman`/`WorkerW`/`Shell_TrayWnd`）。
- Windows 「显示桌面」：`IsDesktopForeground()`（前景为 `Progman`/`WorkerW`）或本窗口被 Win+D 最小化（`IsIconic`）时，`EvaluateVisibility` 不仅不隐藏，还会 `SW_RESTORE` 把方块**拉回可见**，满足"显示桌面时方块保持正常显示"。
- Linux X11：`Gdk.WindowTypeHint.DESKTOP` → `_NET_WM_WINDOW_TYPE_DESKTOP` + `keep_below` + `stick()`（所有工作区可见）。Wayland 只能退化为普通置底窗口。

**显示逻辑（1.0.0-5 重新定义）**：方块**始终在桌面层级**（位于壁纸之上、普通窗口之下），并且在**正常桌面状态下永远不被遮挡**——只有「本显示器上存在最大化或全屏的普通窗口、且其边框与显示器有正重叠」时，方块才主动隐藏，让出视线给正在使用的全屏/最大化应用；一旦该覆盖窗口关闭、还原或最小化，方块立即恢复显示。这一隐藏决策由 `cover_policy.should_be_hidden(covered, showing_desktop)` 给出，X11 下的 `covered` / `showing_desktop` 通过 EWMH（`_NET_CLIENT_LIST_STACKING`、`_NET_WM_STATE_MAXIMIZED_*`、`_NET_WM_STATE_FULLSCREEN`、`_NET_SHOWING_DESKTOP`）在 `platform_window.cover_state()` 里读取；`block_window._cover_poll()` 每 1 秒轮询一次，仅在状态发生跳变时施加 `hide()` / `ensure_visible()`，稳定状态下不向窗口管理器重复发送重排消息。

**「显示桌面」不再隐藏方块（1.0.0-5 修复的漏洞）**：触发「显示桌面」时桌面环境会把 `_NET_SHOWING_DESKTOP` 置 1，`cover_state()` 据此把 `showing_desktop` 设为 True；`should_be_hidden()` 在 `showing_desktop` 为真时一律返回 False，因此方块**保持正常显示**，不会被藏起来。这条规则同时把"点显示桌面方块消失"的漏洞一并堵上（详见 §3.5）。Wayland 下协议不允许客户端探测别的窗口几何与状态，方块在 Wayland 下**永不隐藏**，即「桌面层 + 永不遮挡」的安全降级。

> 注意：主动因覆盖而隐藏（`_cover_hidden=True`）期间，方块的自愈逻辑（visibility / window-state / unmap / 看门狗）会被抑制，避免"隐藏 ↔ 恢复"来回拉扯；退出时 `begin_shutdown()` 会清除轮询定时器并复位该标志。

### 3.3 鼠标点击穿透
- Windows：默认开启，`WS_EX_TRANSPARENT | WS_EX_LAYERED` + `SetLayeredWindowAttributes(..., 255, LWA_ALPHA)`（保持完全不透明，但鼠标事件穿过）。方块为置底窗口（§3.7），Explorer 桌面不会因点击而盖住它，因此该平台保持原默认值。
- **Linux：1.0.0-4 起默认关闭**。X11 的"穿透"是给 GDK 窗口设置空的 `input shape`；Wayland 不支持，开关在 Wayland 下只记录配置、不改变行为。

默认关闭后，方块自己接收并吞掉 `button-press-event` / `button-release-event`（返回 `True`，不换元素、不隐藏、不移动、不改焦点），单击方块前后的状态完全一致。用户仍可在「轮换时间 → 常驻方块行为」里显式开启穿透；开启后由 §3.4 的自愈逻辑保证方块被桌面组件盖住后能自动回到原来的桌面层。升级到 1.0.0-4 时会用一次性标记文件把旧配置里的 `clickThrough: true` 重置为安全值，之后用户的选择不再被覆盖。

### 3.4 单击后方块消失：成因、复现与修复（1.0.0-4）

**现象**：在 X11 桌面（deepin / UOS / KDE / 带桌面图标的 GNOME）单击元素方块后，方块整块不见；托盘仍在，进程未退出，但不再显示，重启程序才回来。

**可能原因（按概率排序）**

| # | 机制 | 涉及代码 |
|---|---|---|
| 1 | **点击落到桌面组件，桌面 raise 自己把方块盖住**。方块设了空 `input shape`（`clickThrough` 默认 True），点击直接穿透到下面的 `dde-desktop` / 桌面图标窗口；这些组件收到点击会 `XRaiseWindow`。方块是 `_NET_WM_STATE_BELOW` 且**从不重新声明层级**，于是被压在桌面窗口之下 —— 窗口其实还在，只是被遮住 | `platform_window.apply_click_through()`、`apply_window_flags()`；`block_window.py` 旧版完全没有 `button-press-event` 处理 |
| 2 | **WM 撤回 / 最小化 / 重新映射后没人恢复**。DESKTOP 类型窗口被 WM 按"显示桌面"、工作区切换、`_NET_SHOWING_DESKTOP` 等规则 unmap 或 iconify；旧版没有 `visibility-notify-event` / `window-state-event` / `map-event` / `unmap-event` 处理，也没有定时兜底 | `BlockWindow` 旧版只连接 `draw` / `realize` / `configure-event` |
| 3 | **窗口被销毁导致进程退出**。无边框窗口仍可能收到 `WM_DELETE_WINDOW`；GTK 默认 `delete-event` 会 destroy，而方块是 `Gtk.Application` 唯一窗口且未 `hold()`，于是整个进程结束 | 旧版无 `delete-event` hook；`main.py` 旧版无 `hold()` |
| 4 | **每 15 秒被重排一次**。轮换器 `tick()` 结尾调用 `notify_schedule_changed()` → `emit("settings")` → `BlockWindow._on_settings()` → `apply_window_flags()` → `window.resize()` → `configure-event` → `enforce_bounds()` → `place()` → `window.move()`。某些 WM 会在桌面层窗口 resize/move 时重新堆叠，配合原因 1 的桌面 raise，方块被永久压下去 | `rotation.py::tick()`、`state.py::notify_schedule_changed()`、`platform_window._lock_size()`（旧版非幂等） |
| 5 | Wayland：协议不支持 input shape，点击其实到达方块；但合成器对 `accept_focus=False` 的 DESKTOP hint 窗口可能自行隐藏/撤回 | `platform_window.is_wayland()` 降级分支 |

**可复现的测试步骤**

1. 无 GUI 的确定性回归（任意机器，含 Windows 开发机）：
   ```bash
   python tools/test_click_guard.py     # 78 项：含旧行为复现模型、单击零副作用、自愈防抖/熔断、接线检查
   python tools/test_layout.py          # 46 项：上一版布局回归，确保没有回退
   ```
   `test_click_guard.py` 第 1 节用「1.0.0-3 的事件表模型」直接复现：空 input shape → 点击落到桌面 → 桌面 raise → `below` 层方块被盖住且无恢复入口 → 一直不可见。
2. 目标 Linux 图形会话里的真机验证（需 GTK3 + PyGObject + Cairo）：
   ```bash
   python3 tools/repro_click_gtk.py          # 验收修复：A 单击 / B delete / C 隐藏自愈 / D 遮挡与 WITHDRAWN
   python3 tools/repro_click_gtk.py --old    # 关闭自愈，复现 1.0.0-3 的「保持消失」
   ```
3. 人工鼠标复核（装 1.0.0-3 与 1.0.0-4 各测一次）：
   ```bash
   WID=$(xdotool search --name 'Element Blocks Desktop' | head -1)
   xwininfo -id "$WID" | grep -E 'Map State|Absolute upper-left|Width|Height'
   xprop -id "$WID" _NET_WM_WINDOW_TYPE _NET_WM_STATE
   xdotool mousemove <方块的 X> <方块的 Y> click --repeat 10 --delay 80 1
   # 再跑一次 xwininfo / xprop：Map State 应仍是 IsViewable，位置尺寸不变
   ```
   旧版在 10 次连点后 `Map State` 常变成 `IsUnMapped` 或窗口虽在却被桌面盖住；新版应始终 `IsViewable` 且 `_NET_WM_STATE` 保持 `BELOW / STICKY / SKIP_TASKBAR`。

**修复（全部集中在 Linux 端，Windows 不受影响）**

- `widget_guard.py`（新增，纯计算、无 GI 依赖）：把「事件 → 动作」抽成状态机，动作只有 `ignore / restore / reapply`；单击策略恒为「只吞事件、零副作用」，并带 400ms 防抖 + 5 秒内最多 3 次熔断 + 退出抑制。
- `block_window.py`：订阅 `BUTTON_PRESS / BUTTON_RELEASE / STRUCTURE / VISIBILITY_NOTIFY` 掩码；吞掉点击；`delete-event` 返回 `True`；`visibility-notify` / `window-state` / `map` / `unmap` + 2 秒看门狗触发延后 40ms 的自愈；`settings` 事件只在 `geometry_signature`（尺寸 / 锚点 / 偏移 / 显示器 / 点击穿透）变化时才重排窗口。
- `platform_window.py`：新增 `ensure_visible()` —— 恢复可见性、强制重新声明 `DESKTOP / BELOW / STICKY / SKIP_TASKBAR / NO_FOCUS`、在 BELOW 层内 `raise_()`、重建 input shape、重绘；**不动元素、配置、位置、尺寸**。`_lock_size()` 改为幂等，只在尺寸真变化时才 `resize()`。
- `state.py` / `rotation.py` / `rotation_page.py`：拆出独立的 `schedule` 事件用于 15 秒倒计时刷新，`settings` 只留给真正的配置变化。
- `config.py`：`clickThrough` 默认改 `False`；一次性迁移标记 `~/.config/element-blocks-desktop/click-guard-v4` 重置旧配置。
- `main.py`：`do_startup()` 里 `hold()`；退出前 `begin_shutdown()` → `release()` → `quit()`。

自愈不依赖具体 WM 是否发送 `VisibilityNotify`（另有 2 秒看门狗兜底），也不会与普通应用窗口抢层级：只在 `fully_obscured` / `WITHDRAWN` / `ICONIFIED` 时动作，且 `Gdk.WindowState.BELOW` 未上报这类不可靠信号一律忽略，避免周期性 `resize/move`。

### 3.5 桌面层级 / 显示桌面 / 不透明度 / 间隔 ComboBox（1.0.0-5）

**① 显示逻辑与不遮挡**：见 §3.2——方块始终在桌面层级，仅在被最大化/全屏窗口覆盖时隐藏，正常桌面状态不得被遮挡。「显示桌面」不再隐藏方块（见 §3.2 与下方说明）。

> **Windows 端（1.0.0.5 同步移植）**：上述四项改动在本轮同时移植到了 WinUI3 工程，功能与 Linux 对齐：不透明度（`AppConfig.Opacity` + `AppState.SetOpacity` + `RotationPage` 滑块，实时经 `SetLayeredWindowAttributes` 的 alpha 通道生效）；间隔选择由 `RadioButton` 组改为 `ComboBox` 且「立即切换下一个元素」按钮移到其右侧；桌面层级覆盖隐藏与「显示桌面」不隐藏由 `DesktopWindowService.EvaluateVisibility` 的 1 秒轮询实现（§3.2 已详述）。Windows 端的覆盖隐藏 / Win+D 不隐藏 / 不透明度实时生效尚未在真实桌面会话做真机验证。

**② 修复「点显示桌面方块消失」**：旧实现把"显示桌面"与"普通窗口覆盖"混为一谈，桌面环境在 `_NET_SHOWING_DESKTOP=1` 时 unmap / 盖住桌面层方块，方块于是消失。1.0.0-5 在 `cover_policy.should_be_hidden()` 中把 `showing_desktop` 作为**否决条件**：只要处于显示桌面状态，无论是否有其它覆盖判定都返回 False（不隐藏）；`platform_window.cover_state()` 把 `_NET_SHOWING_DESKTOP` 一并读回，`block_window` 在显示桌面期间即便被 WM 一并最小化也会把它拉回。这是纯逻辑修复，不依赖具体窗口管理器。

**③ 新增「不透明度」设置项**：
- 配置新增 `opacity`（浮点 0.1~1.0，默认 1.0），写进 `config.json` 的 `opacity` 键，随其它字段一起 400ms 防抖、原子落盘；`config._clamp_opacity()` 把越界/NaN/空值收敛回 [0.1, 1.0]。
- **实时生效**：拖动设置页的 `Gtk.Scale`（10%~100%）即调用 `state.set_opacity()` → 发射独立的 `appearance` 事件 → `BlockWindow._on_appearance()` 调 `platform_window.apply_opacity()`（`window.set_opacity()`）并重绘。`appearance` 事件刻意与 `settings`（几何重排）分离，因此改不透明度**绝不会触发窗口 resize/move**，避免与 §3.4 的自愈逻辑互相干扰。
- **持久保存**：`state.set_opacity()` 经由 `ConfigStore.request_save()` 落盘，重启后 `config.from_dict()` 读回并 clamp。

**④ 间隔选择控件改为 ComboBox + 按钮右移**：
- 旧版"切换间隔"用一组 `Gtk.RadioButton`（每个间隔一个单选按钮），新版改为单个 `Gtk.ComboBoxText`（`interval_combo`），下拉项来自 `shared/intervals.json`，当前选择用 `set_active_id(cfg.rotation)` 同步、用 `get_active_id()` 读取。
- 「立即切换下一个元素」按钮（`Gtk.Button`，连到 `_on_next`）移到 ComboBox 右侧，二者放在同一个水平 `Gtk.Box` 行里，布局更紧凑整齐。
- 相关代码：`rotation_page.py`（`_on_interval_combo` 替代 `_on_interval`、新增 `_on_opacity`、移除 `self._radios`）；`state.set_rotation()` / `state.set_opacity()` 不变。

**可复现的测试步骤**
```bash
# ① 任意机器（含 Windows 开发机），确定性回归（无需 GTK）
python tools/test_visibility_opacity.py   # 48 项：不透明度 clamp/持久化、显示桌面真值表、
                                           # rect_overlap、ComboBox/opacity 接线、3.7 语法
python tools/test_click_guard.py          # 78 项：单击零副作用、自愈、接线（确认没回退）
python tools/test_layout.py               # 46 项：布局回归（确认没回退）

# ② 目标 Linux 图形会话（GTK3 + PyGObject + Cairo），真实窗口验证
python3 tools/repro_click_gtk.py          # 确认单击/隐藏/遮挡自愈仍正常
# 手动验证「显示桌面」与「不透明度」：
WID=$(xdotool search --name 'Element Blocks Desktop' | head -1)
xprop -id "$WID" _NET_WM_STATE _NET_WM_WINDOW_TYPE
wmctrl -k on          # 显示桌面：方块仍应可见（Map State 仍 IsViewable）
# 在设置页拖动「不透明度」到 50%，立即生效；重启程序后仍是 50%
```

### 3.6 Windows 1.0.1.2：两个 Bug 的根因与修复（真机复现并验证）

**Bug 1 · 点击「轮换时间」即崩溃（`0xc000027b`，`Microsoft.UI.Xaml.dll`）**

- **根因**（已在真机复现，异常栈见下）：WinUI3 的编译型 XAML 在 `InitializeComponent()` 里**先挂事件处理器、再赋属性值**。`RotationPage` 的 `Slider` 声明为 `Minimum="0.1" … Value="1.0"` / `Minimum="80" … Value="132"`，于是赋值瞬间同步触发 `ValueChanged`。1.0.0.5 的处理器只有 `if (_loading) return;`（此时 `_loading=false`），于是真的执行了 `App.State.SetOpacity(...)` / `SetBlockSize(...)` → `SettingsChanged` → **主窗口在 XAML 解析过程中执行 `AppWindow.Resize()` + `DesktopWindowService.Apply()`** → 重入窗口操作抛异常，被 XAML 包装成属性赋值失败：
  ```
  Microsoft.UI.Xaml.Markup.XamlParseException:
  Failed to assign to property 'Microsoft.UI.Xaml.Controls.Primitives.RangeBase.Minimum'.
     at ElementBlocks.Desktop.Views.RotationPage.InitializeComponent()
     at ElementBlocks.Desktop.Views.RotationPage..ctor()
     at Microsoft.UI.Xaml.Controls.Frame.Navigate(Type sourcePageType)
  ```
  该异常无人捕获 → `0xc000027b` 直接终止进程。因为 `Slider` 只有这一页有，所以只有「轮换时间」崩，且每次都崩。
- **修复**：`RotationPage` 增加 `_loaded` 标志（`Loaded` 事件置真、`Unloaded` 复位），所有交互处理器改为 `if (!_loaded) { 记录并 return; } if (_loading) return;`——页面加载完成前一律不写状态；`SettingsWindow.Nav_SelectionChanged` 外层加 `try/catch`（导航失败只记日志、保留上一页，绝不终止进程）；`App` 挂 `UnhandledException` 把完整栈写 `%LOCALAPPDATA%\ElementBlocksDesktop\crash.log` 并 `e.Handled=true`；另提供 `selftest.flag` 自检模式（启动即自动导航各页并记录结果后退出），便于后续无交互复现。

**Bug 2 · 只要有未最小化的窗口，方块就隐藏**

- **根因**：1.0.0.5 的 `IsCoveredByZoomedOrFullscreen` 枚举**所有**顶层可见窗口，把"矩形覆盖整块 `rcMonitor`"当作全屏。Windows 上「设置」「照片」等**后台挂起的 UWP**（`ApplicationFrameWindow`）和「Windows 输入体验」（`Windows.UI.Core.CoreWindow`）恰恰是"可见 + 未最小化 + 整屏矩形"，于是被误判为全屏覆盖 → 方块隐藏。叠加 `HWND_BOTTOMMOST`，普通窗口也会把方块压住，视觉上就是"开任何窗口方块都没了"。
- **修复**：① `Reposition` 不再设 BOTTOMMOST，改由 `SetTopMost(true)` 置顶（`WS_EX_NOACTIVATE` 保证不抢焦点，打开设置时临时 `NOTOPMOST`）——**1.0.1.3 起①被 §3.7 的置底方案取代**（应用户需求改为"始终位于 Z 序最底层、不遮挡任何窗口"），②③保持不变；② `IsCoveredByZoomedOrFullscreen` 改为**只看前台窗口及其根窗口**，并跳过 DWM cloak 窗口与桌面壳层；③ `EvaluateVisibility` 在"显示桌面/被 Win+D 最小化"时 `SW_RESTORE` 把方块拉回。
- **真机验证矩阵**（本机 2560×1440 单显示器，1.0.1.2 实测）：正常桌面 可见 ✓；普通（非最大化）窗口在前台且覆盖方块 可见 ✓；前台窗口最大化 隐藏 ✓；还原 可见 ✓；关闭窗口 可见 ✓；Win+D 显示桌面 可见 ✓。

### 3.7 Windows 1.0.1.3：方块窗口置底（bottom-most，不遮挡任何窗口）

**需求**：方块窗口位于所有窗口 Z 序最底层（仍在壁纸之上），点击、获得焦点都不上浮，永不遮挡任何其他窗口，也不影响其他窗口的正常显示与操作。

**实现**（`DesktopWindowService` + `Win32`）：

1. **`PinToBottom(hwnd)`**（由 `MainWindow.AttachToDesktop()` 调用，替代 1.0.1.2 的 `SetTopMost(true)`）：
   - 先 `SetWindowPos(HWND_BOTTOM, NOMOVE|NOSIZE|NOACTIVATE)` 立即沉底——`HWND_BOTTOM` 会同时把 TOPMOST 窗口降为普通层再沉底；
   - 再用与托盘同款的 comctl32 `SetWindowSubclass`（同一个 HWND，独立的 `uIdSubclass=0x5A424F54`）拦截 `WM_WINDOWPOSCHANGING`：**所有 z 顺序变更在生效前都会携带 `WINDOWPOS` 结构路过该消息**，把 `hwndInsertAfter` 改写为 `HWND_BOTTOM`。于是点击激活、`SetForegroundWindow`、外部 `SetWindowPos(HWND_TOP)` 等一切"上浮"路径最终都落在最底层。纯移动/尺寸类操作（带 `SWP_NOZORDER`）不干预。
   - `MainWindow.Closed` 调 `UnpinFromBottom` 移除子类化，避免回调落到悬空 HWND。
2. **`Reposition` 每次显式带 `HWND_BOTTOM`**：旧代码传 `IntPtr.Zero`（即 `HWND_TOP`），每次重定位其实会把窗口提到最上层；这是置底方案必须堵住的路径。
3. **交互保证**：`WS_EX_NOACTIVATE` 让鼠标点击不激活、不抢焦点（XAML 内容仍收到指针事件，设置/轮换功能不受影响）；`WS_EX_TOOLWINDOW` 不进任务栏/Alt+Tab。设置窗口天然位于方块之上，1.0.1.2 的"打开设置临时 `NOTOPMOST`"切换逻辑（`App.ShowSettings`）已删除。
4. **可见性**（与 §3.2 一致）：普通窗口重叠仅视觉覆盖、不隐藏；最大化/全屏才由 `EvaluateVisibility` 触发 `SW_HIDE`，还原后 `Apply`（内含 `Reposition`）把方块放回底层。

**真机验证**（本机 2560×1440 单显示器，1.0.1.3 实测，`python tools/verify_bottommost.py <PID>`，13/13 通过）：

| 场景 | 结果 |
|---|---|
| 初始 z 序：其下仅桌面壳层（Progman / WorkerW） | ✓ |
| 扩展样式：无 `WS_EX_TOPMOST`，有 `NOACTIVATE` / `TOOLWINDOW` | ✓ |
| 真实鼠标点击方块中心：z 序不变、不成为前台 | ✓ |
| 外部 `SetWindowPos(HWND_TOP)` 强制上浮：被 `WM_WINDOWPOSCHANGING` 拦截 | ✓ |
| `SetForegroundWindow` 获得焦点后仍置底 | ✓ |
| 普通窗口重叠：方块位于其下但保持可见（不被隐藏） | ✓ |
| 前台窗口最大化：覆盖轮询 `SW_HIDE`；还原后恢复可见且仍在底层 | ✓ |

> 脚本说明：`tools/verify_bottommost.py` 用纯 ctypes 驱动（EnumWindows 读 z 序、CreateWindowExW 构造测试窗口、mouse_event 合成真实点击、ALT 键解锁前台锁后 SetForegroundWindow），可重复使用；传方块进程 PID 即可。


## 4. 托盘交互

| 动作 | Windows | Debian（AppIndicator / SNI） | Debian（StatusIcon 回退） |
|---|---|---|---|
| 左键 | **打开设置窗口** | 弹出菜单（合成器决定），菜单第一项即「打开设置…」 | **打开设置窗口** |
| 中键 | — | `set_secondary_activate_target` → 打开设置 | — |
| 右键 | 弹出菜单 | 弹出菜单 | 弹出菜单 |

菜单项两端一致：

1. 打开设置…
2. 立即切换下一个元素
3. ─────
4. 暂停轮换（勾选态）
5. 开机自启（勾选态）
6. ─────
7. 退出

托盘提示文本（tooltip）随当前元素更新，例如 `Element Blocks Desktop · 92 铀 U`；Windows 用 `NIM_MODIFY` 改 `szTip`，Linux 用 `set_title` / `set_tooltip_text`。Windows 端还需监听 `TaskbarCreated` 广播，在 Explorer 重启后重新添加图标。

## 5. 自动轮换行为

间隔选项（`shared/intervals.json`）：**从不 / 每 30 分钟 / 每小时 / 每 2 小时 / 每 3 小时 / 每 6 小时 / 每 12 小时 / 每天**。

调度不是"到点计时器触发"，而是：

1. 把下一次切换的 UTC 时刻 `nextFireUtc` 写进配置；
2. 每 15 秒用 `DateTimeOffset.UtcNow` / `datetime.now(timezone.utc)` 对时检查；
3. `now >= nextFireUtc` → 切到下一个已启用元素，然后**从"现在"重新排程**。

这样带来的性质：
- 进程重启、系统休眠、用户改系统时钟都不会漏掉或重复触发；
- 休眠 8 小时后恢复只补切一次，不会连切 8 次；
- 「每小时」对齐到整点，「每天」对齐到本地次日零点，其余按 `now + N 分钟`；
- 在「从不」、暂停、或已启用元素少于 2 个时清空 `nextFireUtc`，等同不轮换；
- 托盘/设置页的「立即切换」会重置排程，避免手动切完马上又自动切。

轮换顺序按原子序数在已启用集合里顺序推进（`RotationCursor` 记录位置），因此不会出现连续两次同一个元素；如果启用的元素只有一个，就一直显示它。一个都没启用时，方块显示「未启用任何元素 / 请在设置中启用」占位文案，而不是空白。

## 6. 边界与降级

| 场景 | 处理 |
|---|---|
| Explorer / Shell 重启 | Windows 监听 `TaskbarCreated` 重新加图标；Linux 的 SNI 由 D-Bus 自动重连 |
| 分辨率、缩放、插拔显示器 | 两端都重新读取工作区并重定位；Linux 端额外按真实窗口尺寸重新收敛并延时复核原点（1.0.0-3） |
| 配置文件被外部编辑器改动 | 应用只在启动时读取；运行时以内存状态为准（单实例，避免并发写） |
| 设置窗口关闭 | 只隐藏/释放引用，方块与托盘继续存在 |
| 单击方块 | Windows：点击穿透（默认）；Linux 1.0.0-4：吞掉点击、零副作用；被桌面盖住 / WM 撤回时自愈恢复（§3.4） |
| 最大化 / 全屏普通窗口（覆盖当前显示器） | 方块主动隐藏，让出视线；窗口还原 / 最小化后立即恢复。正常桌面（无最大化/全屏覆盖）方块始终可见、不被遮挡（§3.2 / §3.5） |
| 显示桌面 | 方块**保持可见**（1.0.0-5 修复：旧版会被隐藏）。`_NET_SHOWING_DESKTOP=1` 时一律不隐藏（§3.5） |
| 不透明度设置 | 设置页 10%~100% 滑块实时生效（`window.set_opacity`）并持久保存到 `config.json`，且**不触发窗口重排**（独立 `appearance` 事件，与几何 `settings` 分离）（§3.5） |
| 全屏游戏 / 锁屏 | 桌面层窗口不抢焦点、不置顶，不会打断全屏应用 |
| Wayland | 见 `01-platform-differences.md` 第 3.2 节，绝对定位与点击穿透降级；且协议不允许探测别的窗口，方块在 Wayland 下永不隐藏（§3.2） |
