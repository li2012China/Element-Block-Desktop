# 构建与打包

> 本机（Windows）装有 .NET 11 SDK，NuGet 可还原 Windows App SDK 1.6 与 Windows SDK BuildTools，因此 **Windows 端已在本机真实编译、打包并自签名 MSIX**；Debian 端是纯 Python 的 `Architecture: all` 包，按 Debian 二进制包格式（`ar` + `control.tar.gz` + `data.tar.gz`）直接构造，无需本机 dpkg。两端安装包都在 `dist/`。GTK 运行时验证仍需在 Debian 机器上完成，MSIX 也未在本机安装运行（避免改动系统状态）。

## 0. 已构建的安装包（`dist/`）

| 文件 | 平台 / 架构 | 大小 | 说明 |
|---|---|---|---|
| `dist/ElementBlocksDesktop_1.0.1.3_x64.msix` | Windows x64 | 10.4 MB | **Windows 推荐安装**：在 1.0.1.2 两项 Bug 修复（点击「轮换时间」崩溃、有任意未最小化窗口就隐藏）基础上，实现**方块窗口置底**——位于所有窗口 Z 序最底层、点击/获得焦点不上浮、永不遮挡其他窗口（`HWND_BOTTOM` + `WM_WINDOWPOSCHANGING` 子类化拦截），详见 `docs/02` §3.7 |
| `dist/ElementBlocksDesktop_1.0.1.2_x64.msix` | Windows x64 | 10.4 MB | 上一版：修复「点击轮换时间崩溃」（`XamlParseException: Failed to assign to property RangeBase.Minimum`，`0xc000027b`）与「有任意未最小化窗口方块就隐藏」（后台挂起 UWP 整屏矩形被误判为全屏）；含不透明度、ComboBox 间隔 + 按钮右移、显示桌面保持可见 |
| `dist/ElementBlocksDesktop_1.0.0.5_x64.msix` | Windows x64 | 10.4 MB | 旧版（含上述两个 Bug），保留仅作对照，**不要安装** |
| `dist/element-blocks-desktop_1.0.0-5_all.deb` | Debian/Ubuntu `all` | 58 KB | **推荐安装**：在 1.0.0-4 基础上 —— 细化桌面层级（仅被最大化/全屏窗口覆盖时隐藏、正常桌面永不遮挡）、修复「显示桌面」误隐藏方块、新增不透明度设置（实时+持久）、间隔选择改 ComboBox 且「立即切换」按钮移至其右侧；`control` / `md5sums` / `triggers` 齐全 |
| `dist/element-blocks-desktop_1.0.0-4_all.deb` | Debian/Ubuntu `all` | 54 KB | 旧版（修单击后消失），保留仅作对照 |
| `dist/element-blocks-desktop_1.0.0-3_all.deb` | Debian/Ubuntu `all` | 45 KB | 旧版（修布局，未修单击消失），保留仅作对照 |
| `dist/element-blocks-desktop_1.0.0-2_all.deb` | Debian/Ubuntu `all` | 40 KB | 旧版（仅修依赖，未修布局），保留仅作对照 |
| `dist/element-blocks-desktop_1.0.0-1_all.deb` | Debian/Ubuntu `all` | 40 KB | 旧版（`python3 >= 3.9` 过严），保留仅作对照，**不要安装** |
| `dist/certs/ElementBlocksDesktop.cer` | Windows | 790 B | 安装前需导入的公钥证书（**私钥 `.pfx` 不要对外分发**） |
| `dist/dependencies/*.msix` | Windows x64 | 约 22 MB | Microsoft 签名的 Windows App SDK 1.6 运行时框架包，供离线机器先装 |
| `dist/SHA256SUMS.txt` | — | — | 全部安装包（含历史版本）的 SHA-256 校验和 |

### Windows 安装（x64，Windows 10 1809+）

以**管理员 PowerShell** 执行：

```powershell
cd "<仓库根>"
Import-Certificate -FilePath .\dist\certs\ElementBlocksDesktop.cer -CertStoreLocation Cert:\LocalMachine\Root
# 已装 Windows App SDK 1.6 运行时可跳过下一行
Add-AppxPackage -Path .\dist\dependencies\Microsoft.WindowsAppRuntime.1.6.msix
Add-AppxPackage -Path .\dist\ElementBlocksDesktop_1.0.1.3_x64.msix
```

也可以双击 `.msix` 交给「应用安装程序」。签名用的是开发用自签名证书（`CN=Element Blocks Desktop`，有效期至 2031-11-13），所以 `signtool verify /pa` 会提示"根证书不受信任"——导入 `.cer` 后即消失；正式分发请改用受信任 CA 的代码签名证书或走 Microsoft Store。包清单里声明了 `PackageDependency Name="Microsoft.WindowsAppRuntime.1.6"`，未装运行时会拒绝安装。

### Debian 安装

```bash
sudo apt install ./dist/element-blocks-desktop_1.0.0-5_all.deb
element-blocks-desktop     # 任意目录均可启动
```

硬依赖 `python3`（**无版本下限**，实测 3.7+ 可运行）、`python3-gi`、`python3-gi-cairo`、`gir1.2-gtk-3.0`；GNOME 需 AppIndicator 扩展才能显示托盘图标。X11 下是真正的桌面层窗口，Wayland 按 `docs/01` 降级。可用 `dpkg-deb -I` / `dpkg-deb -c` 在目标机上复核包内容。若安装器提示 `python3:amd64 3.9` /「依赖关系不满足: python3」，见本文第 4 节。

### 从源码重新构建

```bash
python tools/gen_elements.py && python tools/sync_data.py      # 数据契约

# Windows：仅需 .NET SDK + NuGet，不需要 Visual Studio
dotnet restore windows/src/ElementBlocks.Desktop/ElementBlocks.Desktop.csproj -p:Platform=x64
dotnet build   windows/src/ElementBlocks.Desktop/ElementBlocks.Desktop.csproj -c Release -p:Platform=x64 --no-restore
powershell -NoProfile -ExecutionPolicy Bypass -File tools/make_cert.ps1
python tools/build_msix.py

# Debian 包：Windows 上也能构建，不需要 dpkg
python tools/test_layout.py            # 布局回归 46 项（无需 GTK）
python tools/test_click_guard.py       # 单击/可见性回归 78 项（无需 GTK）
python tools/test_visibility_opacity.py  # 不透明度/显示桌面/ComboBox 回归 48 项（无需 GTK）
python tools/build_deb.py
python tools/build_deb.py --verify
```

`tools/build_msix.py` 读取编译自动生成的 `.build.appxrecipe` 组装布局，调用 NuGet 缓存里的 `makeappx.exe` 打包、`signtool.exe` 签名；中间文件放在纯 ASCII 临时目录以规避中文路径问题。`tools/build_deb.py` 构造 `ar` 归档并计算 `md5sums` / `Installed-Size`，文件布局与 `debian/rules` 一一对应。

## 1. 数据契约同步（每次改 `shared/` 后）

```bash
python tools/gen_elements.py     # 重新生成 elements/theme/intervals/config.schema
python tools/sync_data.py        # 复制到 windows/.../Assets/Data、linux/data、preview/data
python tools/gen_assets.py       # 重新生成托盘图标与各尺寸应用图标
```

## 2. Windows：WinUI3 / MSIX

### 前置条件
- Windows 10 1809 (10.0.17763) 或更高，x64（本包为 x64）
- .NET 8 SDK 或更高（本机实测 11.0.100 可用）
- Windows App SDK 1.6、Windows SDK BuildTools 由 NuGet 自动还原，**无需安装 Visual Studio 或 Windows Kits**
- 目标机上需 Windows App SDK 1.6 运行时框架包（`dist/dependencies/` 已附带）
- 打包需要代码签名证书：`tools/make_cert.ps1` 生成开发自签名证书

### 构建（已实测成功，0 警告 0 错误）
```powershell
dotnet restore windows/src/ElementBlocks.Desktop/ElementBlocks.Desktop.csproj -p:Platform=x64
dotnet build   windows/src/ElementBlocks.Desktop/ElementBlocks.Desktop.csproj -c Release -p:Platform=x64 --no-restore
powershell -NoProfile -ExecutionPolicy Bypass -File tools/make_cert.ps1
python tools/build_msix.py
```

编译会自动产出 `AppxManifest.xml`（带 `ProcessorArchitecture="x64"` 与 `PackageDependency`）、`resources.pri`（6 个 XBF 以 `EmbeddedData` 形式嵌入）与 `ElementBlocks.Desktop.build.appxrecipe`，后者就是 `build_msix.py` 的打包清单。也可用 Visual Studio 2022 的 **发布 → 创建应用包** 走 GUI 路径。若想免安装直接运行散包，改用 `-p:WindowsPackageType=None` 重编译，开机自启会自动回退到注册表 Run 键。

**1.0.1.3（Windows 方块窗口置底，真机验证 13/13）**

- `Identity Version` = `1.0.1.3`；`tools/build_msix.py` 的 `NAME` 同步。
- **需求**：方块窗口位于所有窗口 Z 序最底层（仍在壁纸之上），点击、获得焦点也不上浮，不遮挡任何其他窗口，不影响其他窗口的正常显示与操作。
- **实现**：`DesktopWindowService.PinToBottom()`——① `SetWindowPos(HWND_BOTTOM)` 立即沉底（同时清除残留 TOPMOST）；② comctl32 `SetWindowSubclass` 拦截 `WM_WINDOWPOSCHANGING`，把一切 z 顺序变更（点击激活、`SetForegroundWindow`、外部 `SetWindowPos(HWND_TOP)`）在生效前改写为 `HWND_BOTTOM`；③ `Reposition` 显式带 `HWND_BOTTOM`（旧代码传 `IntPtr.Zero` 即 `HWND_TOP`，每次重定位实际会把窗口提到最上层）；④ 删除 1.0.1.2 的 `SetTopMost` 与"打开设置临时 `NOTOPMOST`"切换，设置窗口天然位于方块之上。`WS_EX_NOACTIVATE` 保证点击不抢焦点但 XAML 内容仍收到指针事件。
- **验证方式**：`python tools/verify_bottommost.py <PID>`（纯 ctypes：z 序断言、真实鼠标点击、强制上浮/前台攻击、最大化隐藏/还原恢复），本机 13/13 通过；覆盖隐藏逻辑与 1.0.1.2 行为无回归。

**1.0.1.2（Windows 两个 Bug 修复，真机复现+验证）**

- `Identity Version` = `1.0.1.2`；`tools/build_msix.py` 的 `NAME` 同步。
- **Bug 1 · 点击「轮换时间」崩溃**：根因是 WinUI3 编译型 XAML 在 `InitializeComponent()` 中先挂事件、后赋属性值，`Slider` 的 `Minimum`/`Value` 赋值同步触发 `ValueChanged`；旧代码此时 `_loading=false`，处理器写入状态并触发主窗口 `AppWindow.Resize()`，在 XAML 解析中重入窗口操作 → `XamlParseException: Failed to assign to property 'RangeBase.Minimum'` → `0xc000027b`。修复：`RotationPage` 增加 `_loaded` 闸门 + `SettingsWindow` 导航 try/catch + `App.UnhandledException` 写 `crash.log`；另加 `selftest.flag` 自检模式。
- **Bug 2 · 任意未最小化窗口就隐藏**：根因是覆盖检测枚举所有顶层窗口，把后台挂起 UWP（`ApplicationFrameWindow`/`CoreWindow`，可见+未最小化+整屏矩形）误判为全屏；叠加 `HWND_BOTTOMMOST` 使普通窗口也能压住方块。修复：改 `HWND_TOPMOST`（不抢焦点）、覆盖检测只看前台窗口及根窗口、跳过 DWM cloak、Win+D 后 `SW_RESTORE` 拉回。
- **验证方式**：`dotnet build`（0 警告 0 错误）→ `python tools/build_msix.py` → `Add-AppxPackage` 安装 → 打开设置点「轮换时间」不再崩溃；用 UIA 选中导航项并用受控窗口矩阵验证可见性（普通窗口可见 / 最大化隐藏 / 还原可见 / Win+D 可见）。诊断入口：`%LOCALAPPDATA%\ElementBlocksDesktop\crash.log`、`trace.flag`（事件时序）、`selftest.flag`（自动导航自检）。
- **真机验证已完成**（本机 Windows 11 2560×1440）：Bug 1 用 `crashrepro.flag` 复现出上述异常栈后修复；Bug 2 六种场景全部符合预期。

> **1.0.0.5（与 Linux 特性对齐）**：`Identity Version` 升到 `1.0.0.5`。移植了 Linux 端同款四项改动——不透明度（`AppConfig.Opacity` + `SetOpacity` + `RotationPage` 滑块，实时 `SetLayeredWindowAttributes` alpha）、间隔选择改 `ComboBox` 且「立即切换」按钮移至其右侧、桌面层级覆盖轮询、以及「显示桌面」不再隐藏方块的修复。该版本存在上述两个 Bug，**请使用 1.0.1.2**。

`Package.appxmanifest` 里声明了 `windows.startupTask`（`TaskId=ElementBlocksStartup`），设置页的「开机自启」调用 `StartupTask.RequestEnableAsync()`，由用户确认，符合 Store 规范；若以散包方式运行（`WindowsPackageType=None`），`StartupService` 会自动回退到 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`。

### 关键文件
| 文件 | 作用 |
|---|---|
| `windows/src/ElementBlocks.Desktop/ElementBlocks.Desktop.csproj` | net8.0-windows10.0.19041.0、`UseWinUI`、Windows App SDK 包引用、`Assets/Data/*.json` 随包复制 |
| `Package.appxmanifest` | MSIX 身份、图标、StartupTask、`runFullTrust` |
| `app.manifest` | PerMonitorV2 DPI、comctl32 v6（托盘子类化）、asInvoker |
| `Interop/Win32.cs` | user32 / shell32 / comctl32 的 P/Invoke 声明 |
| `Services/TrayIconService.cs` | `Shell_NotifyIconW` + 窗口子类化 + 右键菜单 |
| `Services/DesktopWindowService.cs` | TOOLWINDOW / NOACTIVATE / 置底（PinToBottom 子类化）/ 锚点定位 / 覆盖轮询 / 可选 WorkerW 嵌入 |

### 校验清单
- [ ] 启动后任务栏、Alt+Tab、任务视图都**没有**图标，托盘出现米色「E」图标
- [ ] 桌面右上角出现 92 U 铀 方块，鼠标点击可穿透到桌面
- [ ] 左键托盘打开设置窗口；侧边栏两页可切换
- [ ] 点击元素卡片变灰、再次点击恢复；设置文件 400ms 后更新
- [ ] 选「每小时」后 `nextFireUtc` 对齐整点；托盘「立即切换」后重新排程
- [ ] 改分辨率 / 换缩放后方块仍贴住工作区右上角
- [ ] 重启进程仍显示上次的 `lastSymbol`

## 3. Debian：原生 GTK3 → .deb

### 前置条件
```bash
sudo apt update
sudo apt install -y build-essential debhelper dpkg-dev fakeroot \
                    python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
                    gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1 \
                    fonts-noto-cjk
# GNOME Shell 用户另需 AppIndicator 扩展（SNI 托盘显示）
```

### 开发期直接运行（不用打包）
```bash
cd linux
python3 -m element_blocks_desktop.main
# 或：PYTHONPATH=. /usr/bin/python3 element-blocks-desktop-launcher
```

### 构建 .deb

在 Debian 上用官方工具链：

```bash
cd linux
chmod +x debian/rules element-blocks-desktop-launcher
dpkg-buildpackage -us -uc -b
# 产物：../element-blocks-desktop_1.0.0-5_all.deb
sudo apt install ../element-blocks-desktop_1.0.0-5_all.deb
```

在 Windows（或任何没有 dpkg 的机器）上用等价脚本，直接产出 `dist/element-blocks-desktop_1.0.0-5_all.deb`：

```bash
python tools/build_deb.py            # 构建 + 自检
python tools/build_deb.py --verify   # 重新读取 .deb 校验
```

脚本按 Debian 二进制包规范写 `ar` 头与 `debian-binary` / `control.tar.gz` / `data.tar.gz`，生成 `control`（展开 `${misc:Depends}`、计算 `Installed-Size`）、`md5sums`、`triggers`（`update-icon-caches`），所有条目 `root:root` 且 launcher 为 0755；并附 `/usr/share/doc/` 下的 copyright 与压缩 changelog。因为包是纯 Python 的 `Architecture: all`，不需要编译器，两条构建路径产物等价。

`debian/rules` 是手工安装（禁用了 `dh_auto_*` 自动步骤），布局如下：

```
/usr/bin/element-blocks-desktop                        启动脚本（把 /usr/lib/... 加入 sys.path）
/usr/lib/element-blocks-desktop/element_blocks_desktop/  Python 包
/usr/share/element-blocks-desktop/data/*.json           共享数据契约
/usr/share/element-blocks-desktop/element-blocks-desktop-autostart.desktop
/usr/share/applications/element-blocks-desktop.desktop
/usr/share/icons/hicolor/{16..256}/apps/*.png + scalable/*.svg
```

依赖写在 `debian/control`：`python3`（无版本约束）、`python3-gi`、`python3-gi-cairo`、`gir1.2-gtk-3.0` 为硬依赖；AppIndicator 的 GI typelib、`fonts-noto-cjk`、GNOME AppIndicator 扩展为推荐/建议——缺失时程序会回退到 `Gtk.StatusIcon`（X11）或由合成器显示菜单。源码全部带 `from __future__ import annotations`、语法兼容 3.7、未使用 3.8+ 运行时 API，因此不应对 `python3` 加版本下限（1.0.0-1 的 `>= 3.9` 是过严的，已在 1.0.0-2 移除）。

### 布局修复（1.0.0-3）：方块越界与文字溢出

统信 UOS / deepin 等开了显示缩放的桌面上，1.0.0-2 会出现「方块右上角被屏幕裁掉、卡片里的 `Uranium` / `238.0` 跑到方块外」。原因与修复：

| 问题 | 根因 | 修复 |
|---|---|---|
| 方块整体超出屏幕 | `place()` 用配置里的**名义尺寸** `blockSize` 做 clamp，而 HiDPI（`get_scale_factor()` 1.5 / 2）或窗口管理器让 GDK 窗口真实尺寸更大；工作区是应用像素、GDK 窗口是设备像素，混用后右/下边缘越界 | ① `fit_size()` 按工作区收敛尺寸并用 `set_geometry_hints(min=max)` 锁定；② `place()` 读取 `gdk.get_width/height()` 的**真实尺寸**，在设备像素坐标系内对锚点 clamp；③ `move()` 后 120/400ms 读回窗口原点，越界按实测比例校正（自动兼容 `gtk_window_move` 参数为逻辑像素或设备像素的后端差异）；④ `configure-event` 与 `monitors-changed` 触发二次收敛 |
| 文字溢出卡片 | 绘制时没有裁剪；`238.0` 在 y=113 配 15px 字体，实测行高越过 BASE=132 下边缘；13 字符的 `Rutherfordium` 只按 8px 下限缩字号，仍可能宽于卡片 | ① 全部绘制先 `cr.clip()` 到 `BASE×BASE` 矩形（硬边界，任何文字都不可能画到卡片外）；② 每行文字有独立文本框，按 Pango 实测宽高等比缩字号，仍超长由 `set_ellipsize(END)` 省略；③ 底部行按实测行高上移并留出 `PAD=4` 内边距；④ 窗口被拉成非正方形时卡片居中、按 `min(宽,高)` 等比缩放 |

新增 `linux/element_blocks_desktop/layout.py`（纯函数、无 GI 依赖）与 `tools/test_layout.py`（46 项回归）：覆盖 1/1.5/2 缩放、WM 放大窗口、四种锚点 ± 超大偏移、极小工作区、位置校正收敛、长英文名与底部原子量的字号收敛、Python 3.7 语法兼容。**字体、配色、层级、托盘、轮换、点击穿透、配置格式在该版本均未改动**；1.0.0-3 的 `config.json` 无需迁移、不丢设置（1.0.0-4 起 `clickThrough` 默认值改变并有一次性迁移，见下一节）。

在源码树 / 目标机上复核布局（`tools/` 不随 deb 安装，回归测试需在源码仓库里跑）：

```bash
python3 tools/test_layout.py            # 无需 GTK，任意机器可跑
xrandr | head -3                        # 看实际分辨率
gsettings get org.gnome.desktop.interface scaling-factor   # GNOME 缩放
xwininfo -id "$(xdotool search --name 'Element Blocks Desktop' | head -1)"  # 窗口实际几何
```

### 单击消失修复（1.0.0-4）

**现象**：X11 桌面单击方块后整块消失，托盘仍在、进程未退出，重启程序才回来。成因与代码定位详见 `docs/02-tray-and-widget.md` §3.4，摘要：

1. `clickThrough` 旧默认 `True` → X11 空 `input shape` → 点击穿透到 `dde-desktop` / 桌面图标窗口 → 桌面组件 raise 自己，把 `_NET_WM_STATE_BELOW` 且从不重新声明层级的方块盖住；
2. `BlockWindow` 旧版只连了 `draw` / `realize` / `configure-event`，没有 `button-press` / `delete-event` / `visibility-notify` / `window-state` / `map` / `unmap`，窗口被 WM 撤回或收到 `WM_DELETE_WINDOW` 后无人恢复；方块是唯一窗口，被 destroy 还会让 `Gtk.Application` 退出；
3. 轮换器每 15 秒 `emit("settings")` 触发 `resize()` → `configure-event` → `place()` → `move()`，桌面层窗口被反复重排。

**修复**：`widget_guard.py`（纯计算策略）+ `BlockWindow` 吞掉点击、`delete-event` 返回 `True`、可见性/层级自愈（防抖 400ms、5 秒最多 3 次、退出抑制、2 秒看门狗）+ `platform_window.ensure_visible()` + `settings` 事件改用几何签名 + `schedule` 独立事件 + `Gtk.Application.hold()` + `clickThrough` 默认 `False`（一次性迁移标记 `~/.config/element-blocks-desktop/click-guard-v4`）。视觉样式、托盘、轮换、配置格式不变；升级后用户配置不丢失。

**可复现的测试步骤**：

```bash
# ① 任意机器（含 Windows 开发机），确定性回归 + 旧行为复现模型
python tools/test_click_guard.py        # 78 项 PASS
python tools/test_layout.py             # 46 项 PASS，确认布局没有回退

# ② 目标 Linux 图形会话（GTK3 + PyGObject + Cairo），真实窗口验证
python3 tools/repro_click_gtk.py        # 验收修复：单击零副作用、hide 后自动恢复
python3 tools/repro_click_gtk.py --old  # 关闭自愈，复现 1.0.0-3「保持消失」

# ③ 真实鼠标复核（1.0.0-3 与 1.0.0-4 各测一次）
WID=$(xdotool search --name 'Element Blocks Desktop' | head -1)
xwininfo -id "$WID" | grep -E 'Map State|Absolute upper-left|Width|Height'
xprop -id "$WID" _NET_WM_WINDOW_TYPE _NET_WM_STATE
xdotool mousemove <X> <Y> click --repeat 10 --delay 80 1
# 再跑一次 xwininfo / xprop：新版 Map State 仍是 IsViewable，几何与元素不变
```

`tools/` 不随 deb 安装，①②③ 都必须在源码仓库里执行；本机是 Windows 且没有 GTK，②/③ 尚未在真机执行。

### 桌面层级 / 显示桌面 / 不透明度 / 间隔 ComboBox（1.0.0-5）

**改动摘要**（成因与代码定位详见 `docs/02-tray-and-widget.md` §3.2 与 §3.5）：

1. **显示逻辑**：方块始终在桌面层级（壁纸之上、普通窗口之下），**仅当本显示器被最大化/全屏窗口覆盖时**才主动隐藏，正常桌面状态永不遮挡。`cover_policy.should_be_hidden(covered, showing_desktop)` 是唯一的隐藏裁决；X11 下 `covered` / `showing_desktop` 由 `platform_window.cover_state()` 读 EWMH（`_NET_CLIENT_LIST_STACKING`、`_NET_WM_STATE_MAXIMIZED_*`、`_NET_WM_STATE_FULLSCREEN`、`_NET_SHOWING_DESKTOP`）得到，`block_window._cover_poll()` 每 1 秒轮询、仅在状态跳变时动作。
2. **修复「显示桌面」误隐藏**：`_NET_SHOWING_DESKTOP=1` 时 `should_be_hidden()` 返回 False，方块保持正常显示；同时堵上"点显示桌面方块消失"的漏洞。Wayland 下协议不允许探测别的窗口，方块永不隐藏。
3. **新增不透明度**：`config.opacity`（0.1~1.0，默认 1.0）随配置原子落盘；设置页 `Gtk.Scale`（10%~100%）拖动即 `state.set_opacity()` → 独立 `appearance` 事件 → `platform_window.apply_opacity()`（`window.set_opacity()`）实时生效，**不触发窗口重排**；`config._clamp_opacity()` 处理越界/NaN/空值。
4. **间隔选择改 ComboBox**："切换间隔"由一组 `Gtk.RadioButton` 改为单个 `Gtk.ComboBoxText`；「立即切换下一个元素」按钮移到 ComboBox 右侧同一行；`rotation_page.py` 新增 `_on_interval_combo` / `_on_opacity`，移除 `self._radios`。

新增 `linux/element_blocks_desktop/cover_policy.py`（纯决策，无 GI）与 `tools/test_visibility_opacity.py`（48 项纯 Python 回归，无需 GTK）。视觉样式、托盘、轮换、配置格式（除新增 `opacity` 键外）均未改动；升级到 1.0.0-5 时若旧 `config.json` 无 `opacity` 键，`from_dict()` 回退到 1.0（完全不透明），不丢其它设置。

**可复现的测试步骤**：

```bash
# ① 任意机器（含 Windows 开发机），确定性回归（无需 GTK）
python tools/test_visibility_opacity.py   # 48 项 PASS：不透明度 clamp/持久化、显示桌面真值表、
                                           # rect_overlap、ComboBox/opacity 接线、3.7 语法
python tools/test_click_guard.py          # 78 项 PASS，确认单击/可见性逻辑没回退
python tools/test_layout.py               # 46 项 PASS，确认布局没回退

# ② 目标 Linux 图形会话（GTK3 + PyGObject + Cairo），真实窗口验证
python3 tools/repro_click_gtk.py          # 确认单击/遮挡自愈仍正常
WID=$(xdotool search --name 'Element Blocks Desktop' | head -1)
wmctrl -k on                              # 显示桌面：方块仍 IsViewable（1.0.0-5 修复）
# 在设置页拖动「不透明度」到 50% → 立即半透明；重启程序后仍是 50%
```

`tools/` 不随 deb 安装，①② 都必须在源码仓库里执行；本机是 Windows 且没有 GTK，② 尚未在真机执行。

### 校验清单
- [ ] `python3 tools/test_layout.py` 与 `python3 tools/test_click_guard.py` 全部 PASS
- [ ] `python3 tools/repro_click_gtk.py` 全部 PASS；`--old` 能复现「保持消失」
- [ ] 连点方块 10 次后仍 `IsViewable`，位置 / 尺寸 / 当前元素 / `lastSymbol` 均不变
- [ ] 手动 `win.hide()` / 切工作区 / 「显示桌面」后方块在 2 秒内自动恢复
- [ ] 1x / 1.5x / 2x 缩放下方块四边都在屏幕内，改分辨率后仍贴住锚点
- [ ] `Rf`（Rutherfordium）、`U`（238.0）等最长文案完整落在卡片内，不越界、不被下边缘截断
- [ ] `dpkg -L element-blocks-desktop` 路径齐全；`element-blocks-desktop` 可从任意目录启动
- [ ] X11 下 `xprop` 看到 `_NET_WM_WINDOW_TYPE(DESKTOP)`、`_NET_WM_STATE_SKIP_TASKBAR`
- [ ] Wayland 下不报错（只是位置/穿透降级），日志明确提示
- [ ] 托盘菜单第一项打开设置；中键也可打开
- [ ] `~/.config/element-blocks-desktop/config.json` 生成且为 UTF-8 缩进 JSON
- [ ] 「开机自启」在 `~/.config/autostart/` 生成 `.desktop`
- [ ] 升级 deb 后用户配置不丢失

## 4. 依赖问题排查：安装器报 `python3:amd64 3.9`

### 现象与成因

图形安装器提示「仓库中缺失的依赖包 `python3:amd64 3.9`」+「依赖关系不满足: python3」，成因分三层：

1. **版本下限过严（首要原因，已修复）**：1.0.0-1 的 `debian/control` 写了 `Depends: python3 (>= 3.9)`。Debian 10 系（deepin 20 / 统信 UOS / 银河麒麟 V10 等）仓库默认 `python3` 是 3.7.x，Ubuntu 20.04 是 3.8.x，都够不到 3.9；安装器把「找不到 >=3.9 的 python3」显示成「仓库中缺失」。而源码只用到 3.7 语法——所有带注解的模块都有 `from __future__ import annotations`，`ast.parse(..., feature_version=(3,7))` 全部通过，且未使用任何 3.8+ 运行时 API——这个下限是多余的。
2. **图形安装器只走 dpkg / 商店源**：双击 deb 调起的安装器通常等价于 `dpkg -i`，它**不会**去 apt 源里补依赖；部分国产桌面还只检索应用商店仓库而非系统 apt 源，于是即便系统里 `python3 -V` 是 3.7 也会报「仓库中缺失」。
3. **架构与源配置**：`python3:amd64` 是安装器把 `Architecture: all` 包的依赖解析成本机架构元包；若机器是 arm64 / 飞腾 / 鲲鹏 / 龙芯，或 `/etc/apt/sources.list` 未启用 `main`/`universe`、长期未 `apt update`，同样查不到。

**已修复**：`linux/debian/control` 改为无版本约束的 `python3`（`pyproject.toml` 同步 `>=3.7`），从 1.0.0-2 起生效。**请直接安装最新的 1.0.0-5**（同时包含依赖修正、布局修复、单击消失修复，以及 1.0.0-5 的桌面层级/显示桌面/不透明度/ComboBox 修复）；`1.0.0-1` ~ `1.0.0-4` 仅作对照，不要再装。

### 方案 A：安装对应的 python3 依赖包（最稳妥）

```bash
cat /etc/os-release; uname -m
python3 -V || true                     # 先看系统里到底有没有、是几版本
apt-cache policy python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0
sudo apt update
sudo apt install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0
sudo dpkg -i ./dist/element-blocks-desktop_1.0.0-5_all.deb
element-blocks-desktop                 # 任意目录均可启动
```

> 不要为凑 3.9 去下载其它发行版的 `python3_3.9*.deb` 强装，也不要源码编译覆盖 `/usr/bin/python3`：Debian 系大量系统工具（apt、更新管理器等）依赖发行版自带解释器，替换会导致系统级破损。

### 方案 B：让包管理器自动解决依赖（最省事，优先试）

```bash
sudo apt install ./dist/element-blocks-desktop_1.0.0-5_all.deb
# 必须带 ./ 或绝对路径，apt 才会把它当本地包、读取 control 并从已配置源补依赖
# 若之前用 dpkg -i 留下了半安装状态：
sudo apt --fix-broken install
```

`apt install ./pkg.deb` 与 `dpkg -i` 的关键差别就是前者会自动解析 `Depends`，截图里的图形安装器走的是后者。离线机器可先在**同架构联网机器**上 `apt download python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0`，把下载到的 `.deb` 拷过去 `sudo dpkg -i *.deb`，再装本包。

### 方案 C：改用不依赖 python3 的替代包

Linux 端是 PyGObject / GTK3 实现，**运行时本质上需要 Python 解释器**；只要沿用这套实现，就不可能真正零 Python。可选路径：

| 做法 | deb 依赖 | 代价 / 注意 |
|---|---|---|
| PyInstaller / Nuitka 把解释器打进包（`--onedir`），deb 的 `Depends` 去掉 `python3*` | 不依赖 python3 | 体积增至数十 MB；**必须在目标发行版或更低 glibc 版本上构建**，否则老系统跑不起来；GI typelib 与 GTK 共享库仍取自系统 |
| AppImage / Flatpak（`org.gnome.Platform`）自带运行时 | 不经 deb 依赖 | 目标机需允许运行 AppImage 或已装 flatpak；分发形态改变 |
| C / Vala / Rust + GTK3 重写 | 仅 GTK 系统库 | 真正零 Python，但要重写约 1400 行 GTK 逻辑，工作量最大 |
| 换用本仓库的 Windows MSIX | 与 Linux 无关 | 仅适用于可用 Windows 的机器 |

PyInstaller 路线示例（须在目标发行版上执行，本机 Windows 无 GTK，故**未构建验证**）：

```bash
sudo apt install -y python3-pip python3-gi python3-gi-cairo gir1.2-gtk-3.0 libgtk-3-0
pip3 install pyinstaller
pyinstaller --onedir --name element-blocks-desktop \
  --add-data "linux/data:data" --hidden-import gi \
  linux/element-blocks-desktop-launcher
# 再把产出的目录作为 payload 重打 deb，Depends 只写 libgtk-3-0, gir1.2-gtk-3.0
```

注意：需要同步调整 `assets.py` 的数据查找路径与 launcher 的 `INSTALLED_LIB`；`python3-gi` 的 C 扩展、GI typelib 与系统 GTK/GObject 版本强绑定，跨发行版直接拷贝二进制不可靠。

### 注意事项速查

- ❌ 不要 `dpkg -i --force-depends`：会留下「装上了但跑不起来」的包，之后每次 apt 操作都报依赖破损；误用后 `sudo apt --fix-broken install` 修复。
- ❌ 不要用 `python3.9` 替换系统 `python3`，不要 `ln -sf` 改 `/usr/bin/python3` 指向。
- ✅ 先确认架构与源：`dpkg --print-architecture`、`grep -rhv '^#' /etc/apt/sources.list*`、`sudo apt update`。
- ✅ 用 `dpkg-deb -f xxx.deb Depends` 复核依赖声明；`apt-cache policy <包名>` 看仓库里可用的版本。
- ✅ 还有三个硬依赖 `python3-gi` / `python3-gi-cairo` / `gir1.2-gtk-3.0`，若仓库里也缺，同样按方案 A/B 补齐。
- ✅ GNOME 需 AppIndicator 扩展才看得到托盘图标；X11 是完整效果，Wayland 会降级（见 `docs/01`）。
- ✅ 升级到 1.0.0-5 不会丢配置：用户设置在 `$XDG_CONFIG_HOME/element-blocks-desktop/config.json`，与 `/usr/share` 下的只读数据分离；1.0.0-4 只会一次性把旧配置里的 `clickThrough: true` 重置为 `false`（标记文件 `click-guard-v4`），1.0.0-5 在此基础上新增 `opacity` 键（旧配置缺省时回退 1.0，不覆盖其它字段）。

## 5. 无编译交互预览

直接打开 `preview/index.html`（或由 `present_files` 预览面板打开）。它是自包含的 HTML，内嵌了 118 个元素数据、主题与间隔定义，模拟：

- 桌面壁纸 + 固定位置的常驻元素方块（与参考图一致的米色卡片）
- 右下角系统托盘图标与右键菜单
- WinUI3/GTK 风格的侧边栏设置窗口：周期表页（点击启用/禁用）、轮换时间页
- 轮换倒计时与「预览加速」开关、localStorage 持久化

它用于确认交互与设计，**不是**发布产物；真实窗口层级、托盘、单实例、开机自启只能由上面的原生工程提供。

## 6. 目录速查

```
ElementBlocksDesktop/
├── README.md
├── docs/                        架构 / 托盘窗口 / 持久化 / 构建（本文）
├── shared/                      唯一数据源（4 个 JSON）
├── dist/                        ★ 已构建的安装包、证书、运行时依赖、校验和
├── tools/                       数据生成 / 同步 / 图标 / 打包
│   ├── gen_elements.py  sync_data.py  gen_assets.py
│   ├── build_deb.py            免 dpkg 构造 .deb
│   ├── test_layout.py          布局越界回归 46 项（纯 Python）
│   ├── test_click_guard.py     单击/可见性回归 78 项（纯 Python）
│   ├── test_visibility_opacity.py  桌面层级/显示桌面/不透明度/ComboBox 回归 48 项（纯 Python）
│   ├── repro_click_gtk.py      目标机 GTK 真机复现脚本
│   ├── make_cert.ps1           自签名证书
│   └── build_msix.py           appxrecipe → makeappx → signtool
├── windows/                     WinUI3 工程 + MSIX 清单
├── linux/                       GTK3 工程 + debian/ 打包（含 widget_guard.py、cover_policy.py）
└── preview/index.html           无编译交互预览
```
