# Element Blocks Desktop

在桌面固定位置常驻显示一个「元素方块」的桌面软件，支持 **Windows（WinUI3）** 与 **Linux / Debian（原生 GTK3，deb 包）**。

运行时**不在任务栏显示图标**，只在系统托盘；点击托盘图标打开带侧边栏的配置界面：

- **第一页 · 元素周期表**：18 列 × 7 周期 + 镧系/锕系两行，共 118 个元素，点按卡片即可启用 / 禁用（禁用时变淡）；提供全选、全不选、仅天然元素、恢复默认。
- **第二页 · 轮换时间**：从不 / 每 30 分钟 / 每小时 / 每 2、3、6、12 小时 / 每天，用下拉框（ComboBox）选择，按设定周期自动切换到**下一个已启用**的元素；「立即切换下一个元素」按钮就在下拉框右侧。另有暂停轮换、开机自启、点击穿透、固定位置、方块大小，以及**不透明度**滑块（10%~100%，拖动即时生效并自动保存）。

## 设计还原

方块样式取自参考图：米色底 (`#EFE3C0`)、深色细边框，左上角原子序数、右上角元素符号、**中央大号中文名**、英文名、底部相对原子质量；放射性元素的序号与符号用红色（参考图中 `92 U 铀 / Uranium / 238.0`）。元素分类配色沿用中文周期表的图例：金属米色、过渡元素红框、非金属绿色、稀有气体黄绿、镧系/锕系粉底红框。所有颜色与字号集中在 `shared/theme.json`，两端共用。

## 目录结构

```
README.md
docs/
  01-platform-differences.md   ★ 平台差异处理
  02-tray-and-widget.md        ★ 托盘与常驻窗口行为
  03-config-persistence.md     ★ 配置持久化方式
  04-build-and-package.md        MSIX / deb 构建与校验清单
shared/                         唯一数据源
  elements.json                 118 元素 + 周期表网格坐标 + 分类/放射/人造标记
  theme.json / intervals.json / config.schema.json
dist/                           ★ 已构建好的安装包
  ElementBlocksDesktop_1.0.1.3_x64.msix      Windows x64（已自签名，推荐）
  element-blocks-desktop_1.0.0-5_all.deb      Debian/Ubuntu all（推荐）
  certs/  dependencies/  SHA256SUMS.txt      公钥证书 / 运行时框架包 / 校验和
tools/                          数据生成、跨平台同步、图标生成、打包与回归测试
  build_deb.py / build_msix.py / make_cert.ps1
  test_layout.py / test_click_guard.py / test_visibility_opacity.py / repro_click_gtk.py
windows/                        WinUI3 工程（C# / XAML / Win32 互操作 / MSIX）
linux/                          GTK3 原生工程（PyGObject / Cairo / D-Bus / debian 打包）
preview/index.html              无需编译的交互预览（桌面 + 方块 + 托盘 + 设置界面）
```

## 三个核心问题的答案（摘要）

**平台差异**：共享 JSON 数据契约 + 两套原生 UI（WinUI3 的 `NavigationView` vs GTK3 的 `Gtk.StackSidebar`）。托盘在 Windows 用 `Shell_NotifyIconW`（WinUI3 无托盘 API，需窗口子类化收消息），Debian 用 Ayatana AppIndicator（SNI/D-Bus）并回退 `Gtk.StatusIcon`。窗口层级在 Windows 是 `WS_EX_TOOLWINDOW + HWND_BOTTOMMOST`，在 X11 是 `_NET_WM_WINDOW_TYPE_DESKTOP`；**Wayland 不支持绝对定位、桌面层窗口和输入区域穿透**，代码做了明确降级并预留 `gtk-layer-shell` 方案。详见 `docs/01`。

**托盘与常驻窗口**：单实例启动，只创建常驻方块窗口 + 托盘，不创建设置窗口；关闭设置窗口不退出进程，只有托盘「退出」结束。方块按工作区锚点定位、位于壁纸之上普通窗口之下；Windows 默认点击穿透，**Linux 1.0.0-4 起默认吞掉自身点击**（避免单击后桌面组件把方块盖住），并带可见性/层级自愈。托盘左键打开设置、右键菜单（立即切换 / 暂停 / 开机自启 / 退出）。轮换用持久化的 `nextFireUtc` + 15 秒对时轮询，休眠恢复最多补切一次。详见 `docs/02`。

**配置持久化**：单个 UTF-8 JSON，Windows 写 `ApplicationData.LocalFolder`（散包为 `%LOCALAPPDATA%\ElementBlocksDesktop`），Debian 写 `$XDG_CONFIG_HOME/element-blocks-desktop`。临时文件 + fsync + 原子替换，400ms 防抖，`version` 字段做迁移，损坏时备份 `.bak` 回退默认值；已启用元素用符号数组、时间用 UTC ISO-8601，两端结构完全一致。详见 `docs/03`。

## 安装包（已构建）

`dist/` 里是本机真实构建的两个安装包：Windows 为 **已编译 + 已自签名的 MSIX**（WinUI3 x64），Debian 为 **`Architecture: all` 的 .deb**（纯 Python，无需编译）。校验和见 `dist/SHA256SUMS.txt`。

```powershell
# Windows（管理员 PowerShell）
Import-Certificate -FilePath .\dist\certs\ElementBlocksDesktop.cer -CertStoreLocation Cert:\LocalMachine\Root
Add-AppxPackage -Path .\dist\dependencies\Microsoft.WindowsAppRuntime.1.6.msix   # 已装 1.6 运行时可跳过
Add-AppxPackage -Path .\dist\ElementBlocksDesktop_1.0.1.3_x64.msix
```
```bash
# Debian / Ubuntu
sudo apt install ./dist/element-blocks-desktop_1.0.0-5_all.deb
```

自签名证书仅供本地旁加载（导入 `.cer` 后被信任），正式分发需受信任 CA 的代码签名证书；`dist/certs/*.pfx` 含私钥，不要对外分发。Windows 端已在本机真机验证（MSIX 安装运行、置底行为 13/13 通过）；GTK 运行时尚未在真实 Linux 图形会话做真机验证。

> **版本说明**：`1.0.0-2` 把 `python3 (>= 3.9)` 放宽为无版本约束的 `python3`，解决 deepin / UOS / 麒麟等 Debian 10 系发行版上「仓库中缺失 python3:amd64 3.9 / 依赖关系不满足」的问题；`1.0.0-3` 修复了缩放桌面上**方块被屏幕裁掉**、**卡片文字溢出到方块外**两处布局问题；**`1.0.0-4` 修复了 Linux 上「单击元素方块后它意外消失」**——根因是空 input shape 把点击交给桌面组件、窗口缺少可见性/层级恢复入口、以及轮换 tick 每 15 秒误触发 `resize/move`。现在方块吞掉点击且零副作用，`delete-event` 不销毁窗口，`visibility / window-state / map / unmap` + 2 秒看门狗自动恢复，`clickThrough` 默认关闭并做一次性迁移。**`1.0.0-5`（两端同步）** 进一步细化了桌面层级显示逻辑：方块始终在桌面层、仅被最大化/全屏窗口覆盖时才隐藏、正常桌面永不遮挡；修复了「显示桌面」会误隐藏方块的漏洞；新增**不透明度**设置（实时生效 + 持久保存）；把"切换间隔"从单选按钮改为下拉框（ComboBox），并把「立即切换下一个元素」按钮移到其右侧。**Windows 请安装 `1.0.1.3`**——在 `1.0.1.2`（修复「点击轮换时间崩溃」与「任意未最小化窗口就隐藏」两个 Bug）的基础上，实现**方块窗口置底**：始终位于所有窗口 Z 序最底层（壁纸之上），点击、获得焦点也不上浮，永不遮挡任何其他窗口（真机验证 13/13 通过，详见 `docs/02` §3.7）；**Linux 请安装 `1.0.0-5`**，`1.0.0-1` ~ `1.0.0-4` 仅作对照。依赖排查见 `docs/04` 第 4 节，布局与点击修复细节见 `docs/04` 第 3 节和 `docs/02` §3.3/§3.4，桌面层级/显示桌面/不透明度/ComboBox 改动见 `docs/04` 第 3 节（1.0.0-5 小节）和 `docs/02` §3.2/§3.5，Windows 置底实现见 `docs/02` §3.7 与 `docs/04`（1.0.1.3 小节）。

## 快速开始

- **先看交互预览**：直接打开 `preview/index.html`（内嵌全部数据，无需服务器）。
- **从源码重建**：`dotnet build ... -c Release -p:Platform=x64` → `tools/make_cert.ps1` → `python tools/build_msix.py`；Debian 包用 `python tools/test_layout.py` + `python tools/test_click_guard.py` + `python tools/test_visibility_opacity.py`（三项纯 Python 回归，无需 GTK）+ `python tools/build_deb.py`（Windows 上也能跑，无需 dpkg）。真机复现用 `python3 tools/repro_click_gtk.py`。完整命令见 `docs/04`。
- **改数据后**：`python tools/gen_elements.py && python tools/sync_data.py`（图标用 `tools/gen_assets.py`），然后重建两个包。

> 本仓库在 Windows 工作区编写；WinUI3 已用本机 .NET 11 SDK + NuGet 还原的 Windows App SDK / BuildTools 编译打包，Debian 包按 deb 二进制格式直接构造。两端产物均为构建产物，运行验证需在各自目标系统上完成。

## 技术栈一览

| | Windows | Debian |
|---|---|---|
| 语言 / 框架 | C# 12 · WinUI3 · Windows App SDK 1.6 · net8.0-windows10.0.19041.0 | Python 3.7+（延迟注解）· GTK3 (PyGObject) · Cairo/Pango |
| 侧边栏 | `NavigationView` | `Gtk.StackSidebar` |
| 托盘 | `Shell_NotifyIconW` + `SetWindowSubclass` | `AyatanaAppIndicator3` / `Gtk.StatusIcon` |
| 打包 | MSIX（含 `startupTask`，已产出已签名 x64 包） | deb（`Architecture: all`，已产出；可免 dpkg 构建） |
