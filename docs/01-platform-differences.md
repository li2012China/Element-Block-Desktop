# 平台差异处理

## 1. 总体取舍：共享数据契约 + 两套原生 UI

需求明确要求 **Windows 用 WinUI3、Debian 用原生 UI**，因此没有采用 Electron / Qt / Flutter / MAUI 这类"一套 UI 跨端"的方案。项目被切成三层：

```
shared/     ← 唯一数据源（elements.json / theme.json / intervals.json / config.schema.json）
   │           纯 JSON，无平台类型、无二进制格式，两端都直接读
   ├── windows/  WinUI3 + Windows App SDK (C#)，XAML + Win32 互操作
   └── linux/    GTK3 原生控件 (Python/PyGObject)，Cairo + GDK + D-Bus
```

逻辑层（配置模型、轮换算法、周期表坐标）在两端各写一份薄实现，**行为由同一份 JSON 契约约束**：
- 周期表的 18 列 × 7 周期 + 镧系/锕系两行，坐标由 `elements.json` 的 `row`/`column` 给出，两端都不硬编码元素位置；
- 轮换间隔、配色、方块字号全部来自 `intervals.json` / `theme.json`；
- 配置文件字段名、类型、取值范围由 `config.schema.json` 定义，两端读写结构完全一致（便于人工编辑和交叉迁移）。

这样既满足"原生 UI"的要求，又不会出现"Windows 上启用 118 个元素、Linux 上只显示 92 个"这类数据漂移。`tools/gen_elements.py` 生成数据，`tools/sync_data.py` 把它复制进各平台的资源目录（MSIX 与 deb 必须自包含，不能引用源码树之外的路径）。

## 2. 逐项差异对照

| 关注点 | Windows（WinUI3） | Debian（原生 GTK3） |
|---|---|---|
| UI 框架 | WinUI3 / Windows App SDK 1.6，XAML | GTK3 原生控件：`Gtk.Window` / `Gtk.StackSidebar` / `Gtk.Grid` / `Gtk.ToggleButton` / `Gtk.Switch`；**无 WebView、无 Electron、无 Qt** |
| 侧边栏 | `NavigationView`（`PaneDisplayMode=Left`） | `Gtk.StackSidebar` + `Gtk.Stack`，GNOME 原生侧栏 |
| 元素方块绘制 | `UserControl` + `Viewbox`，XAML 文本块 | `Gtk.DrawingArea` + Cairo/Pango 绘制 |
| 托盘 | WinUI3 **没有**托盘 API → P/Invoke `Shell_NotifyIconW`，`SetWindowSubclass` 收消息 | `AyatanaAppIndicator3`（StatusNotifierItem / D-Bus），缺失时回退 `Gtk.StatusIcon` |
| 隐藏任务栏 | `WS_EX_TOOLWINDOW` + 去掉 `WS_EX_APPWINDOW`；`AppWindow.IsShownInSwitchers=false` | `set_skip_taskbar_hint` / `set_skip_pager_hint`（写入 `_NET_WM_STATE_SKIP_TASKBAR`） |
| 桌面层级 | `HWND_BOTTOMMOST` + `WS_EX_NOACTIVATE`；可选 `SetParent` 到 `WorkerW` | X11：`Gdk.WindowTypeHint.DESKTOP`（`_NET_WM_WINDOW_TYPE_DESKTOP`）+ `keep_below` |
| 绝对定位 | `SetWindowPos` + `MONITORINFO.rcWork` | X11：`gtk_window_move` + `Gdk.Monitor.get_workarea`（回退 `Gdk.Screen.get_monitor_workarea`）；**Wayland 不支持** |
| 点击穿透 | `WS_EX_TRANSPARENT \| WS_EX_LAYERED` + `SetLayeredWindowAttributes`（默认开启） | X11：空 `input shape`（`gdk_window_input_shape_combine_region`）；**Wayland 不支持**。1.0.0-4 起 Linux 默认**关闭**：空 input shape 会让点击落到桌面组件、组件 raise 后盖住 `keep_below` 的方块（详见 `docs/02` §3.4） |
| DPI / 多显示器 | `app.manifest` 声明 PerMonitorV2；`GetDpiForWindow` 把 CSS 像素换算成物理像素；`WM_DISPLAYCHANGE` 触发重定位 | GTK 用逻辑像素自动缩放；定位时显式乘 `get_scale_factor()` 换算成设备像素，并用真实 GDK 窗口尺寸 clamp + 延时读回原点校正（1.0.0-3）；`monitors-changed` / `size-changed` / `monitor-added|removed` 触发重定位 |
| 定时器 | `System.Threading.Timer`（15 秒轮询）经 `DispatcherQueue` 切回 UI 线程 | `GLib.timeout_add_seconds`（15 秒），本身跑在主循环线程 |
| 单实例 | 命名 `Mutex` + `EventWaitHandle`（第二个进程 Set 事件后退出） | `Gtk.Application` 带 `application_id`，由会话 D-Bus 自动单实例并转发 `activate` |
| 开机自启 | MSIX `StartupTask.RequestEnableAsync()`；散包回退 `HKCU\...\Run` | 复制 `.desktop` 到 `$XDG_CONFIG_HOME/autostart` |
| 资源配置目录 | `AppContext.BaseDirectory/Assets/Data`（MSIX 内） | `/usr/share/element-blocks-desktop/data` |
| 配置文件目录 | `ApplicationData.Current.LocalFolder`（MSIX 重定向）或 `%LOCALAPPDATA%\ElementBlocksDesktop` | `$XDG_CONFIG_HOME/element-blocks-desktop`，缺省 `~/.config/...` |
| 打包 | MSIX 单项目（`WindowsPackageType=MSIX`），`net8.0-windows10.0.19041.0`，最低 17763 | `debhelper-compat 13`，`Architecture: all`，产出 `.deb` |

## 3. 三个最需要小心的差异

### 3.1 WinUI3 没有托盘，也没有"桌面层窗口"控件
`Shell_NotifyIconW` 需要一个 HWND 接收回调，WinUI3 的 `Window` 不暴露 `WndProc`。本项目用 `comctl32.SetWindowSubclass` 给常驻窗口挂一个子类过程（`Interop/Win32.cs`、`Services/TrayIconService.cs`），省掉一个隐藏窗口。注意：
- `SUBCLASSPROC` 委托必须作为字段保活，否则 GC 后回调会崩；
- Explorer 崩溃重启会广播 `TaskbarCreated`（`RegisterWindowMessageW`），收到后必须重新 `NIM_ADD`；
- `app.manifest` 里声明了 comctl32 v6，否则 `SetWindowSubclass` 可能不可用。

Linux 侧不存在这个问题，但多了 **SNI 语义差异**：StatusNotifierItem 规范下"左键"由合成器决定，GNOME/KDE 通常弹出菜单而不是触发 `Activate`。因此 Linux 端把「打开设置…」放在菜单第一项，并用 `set_secondary_activate_target` 把中键/激活映射到它；`Gtk.StatusIcon` 回退路径则严格实现"左键打开设置、右键菜单"。GNOME Shell 需要 AppIndicator 扩展才能显示 SNI 图标（已写进 `Recommends` / `Suggests`）。

### 3.2 Wayland 的能力缺口
X11 允许客户端声明 `_NET_WM_WINDOW_TYPE_DESKTOP`、指定绝对坐标、设置空输入区域；Wayland 协议**三者都不允许**（`wlr-layer-shell` 除外）。因此 `platform_window.py` 做了明确降级：

| 能力 | X11 | Wayland |
|---|---|---|
| 桌面层窗口 | ✅ `DESKTOP` hint | ❌ 退化为无边框 + 不抢焦点 + `keep_below` 的普通窗口 |
| 固定位置 | ✅ `window.move()` | ❌ 由合成器记住上次位置；配置里的锚点不生效 |
| 点击穿透 | ✅ 空 input shape | ❌ 方块可接收鼠标事件（但仍 `accept_focus=False`） |

在 wlroots 合成器（Sway/Hyprland 等）上，要把 `platform_window.apply_window_flags` 换成 `gtk-layer-shell` 的 `LayerSurface`，设置 `layer=BACKGROUND`、`anchor` 对应配置锚点、并给 `LayerSurface` 设置空输入区域，即可获得与 X11 等价的效果。GNOME Wayland 目前没有等价接口，这是协议限制而非实现遗漏。

### 3.3 字体与扩展汉字
参考图中「铀」这类汉字用宋体（SimSun / Noto Serif CJK）；104–118 号元素的中文名位于 CJK 扩展 B–F 区（`𬬻`、`鿫` 等），很多系统字体缺字。`elements.json` 为这些元素额外提供 `pinyin` 字段，UI 可据此显示拼音或退回元素符号；Debian 包把 `fonts-noto-cjk` 放进 `Recommends`，Windows 端在 `App.xaml` 全局设置 `Microsoft YaHei`。两端都用 Pango/WinUI 的字体回退机制，不会因缺字崩溃。

## 4. 行为一致性保证

尽管 UI 与窗口机制不同，下面这些行为两端完全一致：

- 默认显示 `92 U 铀`，默认「从不」轮换、118 个元素全部启用；
- 启用/禁用状态用**元素符号**数组保存，与语言、UI 无关；
- 轮换按原子序数顺序推进、不连续重复，只有一个已启用元素时保持不变；
- `nextFireUtc` 用 UTC ISO-8601 保存，两端解析同一字符串；
- 休眠/关机恢复后最多补切一次，不补跑历史次数；
- 配置损坏时备份 `.bak` 并回退默认值；写入都是临时文件 + fsync + 原子替换。
