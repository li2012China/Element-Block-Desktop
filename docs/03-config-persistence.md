# 配置持久化方式

## 1. 存储选型

用**单个 UTF-8 JSON 文件**保存全部用户设置，而不是 Windows 注册表 / `ApplicationDataContainer` / GSettings / ini。理由：

1. 两个平台读写**完全相同的结构**，便于人工检查、备份、脚本修改和交叉迁移；
2. 数据里有数组（已启用元素）、嵌套对象（位置）、时间戳，JSON 表达最自然；
3. 与随包只读数据（`elements.json`）解耦：升级程序只替换只读数据，用户设置在 home 下原地保留；
4. 便于加 `version` 字段做 schema 迁移。

只有"开机自启"这类**必须调用系统 API** 的开关，才额外写系统位置（MSIX `StartupTask` / HKCU Run / XDG autostart）；配置文件里仍保留 `autoStart` 作为 UI 状态的镜像。

## 2. 文件路径

| 平台 | 路径 | 说明 |
|---|---|---|
| Windows（MSIX） | `ApplicationData.Current.LocalFolder.Path\config.json` | Windows 自动重定向到包容器 `%LOCALAPPDATA%\Packages\<PackageFamilyName>\LocalCache\Local\...`；卸载/升级由系统处理迁移 |
| Windows（散包） | `%LOCALAPPDATA%\ElementBlocksDesktop\config.json` | `Environment.SpecialFolder.LocalApplicationData` |
| Debian | `$XDG_CONFIG_HOME/element-blocks-desktop/config.json` | 未设置 `XDG_CONFIG_HOME` 时为 `~/.config/element-blocks-desktop/config.json`，遵循 XDG Base Directory |

只读数据契约的位置：Windows `AppContext.BaseDirectory/Assets/Data/*.json`（打进 MSIX），Debian `/usr/share/element-blocks-desktop/data/*.json`。开发期两端都允许回退到仓库 `shared/` 目录。

**配置是机器本地的**，不漫游、不上云、不含任何隐私数据；deb 卸载（非 purge）或 MSIX 升级都不会删除用户 home 下的配置。

## 3. 文件结构（v1）

```json
{
  "version": 1,
  "enabledSymbols": ["H", "He", "Li", "...", "U", "..."],
  "rotation": "h1",
  "position": { "anchor": "TopRight", "offsetX": 32, "offsetY": 32, "monitorIndex": 0 },
  "blockSize": 132,
  "clickThrough": false,
  "autoStart": false,
  "paused": false,
  "lastSymbol": "U",
  "nextFireUtc": "2026-11-13T14:00:00Z",
  "rotationCursor": 91
}
```

字段约定（完整约束见 `shared/config.schema.json`）：

| 字段 | 含义 |
|---|---|
| `version` | schema 版本，当前 1；读到更高版本按已知字段降级处理 |
| `enabledSymbols` | 允许参与轮换的**元素符号**数组。用符号而不是原子序数或数组下标：可读、可 diff、数据文件增删元素时不会错位 |
| `rotation` | 间隔 id，枚举来自 `intervals.json`（`never` / `m30` / `h1` … `d1`） |
| `position` | 锚点 + 偏移 + 显示器索引，避免记录随分辨率变化的裸坐标 |
| `blockSize` | 方块边长（CSS/逻辑像素），80–320 |
| `clickThrough` / `autoStart` / `paused` | 行为开关。Linux 1.0.0-4 起 `clickThrough` 默认 `false`（方块吞掉自身点击，避免单击后消失）；Windows 仍默认 `true`。升级时用同目录的一次性标记 `click-guard-v4` 把旧配置里的 `true` 重置为 `false`，之后用户的显式选择不再被覆盖 |
| `lastSymbol` | 当前显示的元素。**重启后立即恢复，不跳变** |
| `nextFireUtc` | 下一次轮换的 UTC 时刻（ISO-8601），跨时区/休眠/重启的唯一真相 |
| `rotationCursor` | 轮换游标，用于人工编辑配置后仍能顺序推进 |

**运行时状态不落盘**：窗口句柄、托盘句柄、菜单对象、定时器 id、当前 UI 线程状态都只在内存里。

## 4. 写入策略

### 4.1 原子写（两端一致）
```
1. 在同目录创建 config-<随机>.tmp（Windows 用 config.json.tmp）
2. 写 UTF-8 JSON → StreamWriter.Flush → FileStream.Flush(true)   /  f.flush() → os.fsync()
3. File.Move(tmp, config.json, overwrite:true)                  /  os.replace(tmp, config.json)
4. finally 清理残留 tmp
```
临时文件必须与目标**同一目录、同一文件系统**，否则 `os.replace` / `File.Move` 不是原子操作。先 fsync 再替换，保证掉电时要么是旧配置，要么是完整新配置，绝不会出现半截 JSON。

### 4.2 防抖
用户在周期表上连续点按 118 个元素，若每次点击都落盘会有上百次 IO。两端都实现 400ms 防抖：

- Windows：`System.Threading.Timer`，`RequestSave()` 只 `Change(400, Infinite)`；进程退出时 `Flush()` 强制立即写。
- Linux：`GLib.timeout_add(400, ...)`，重复调用先 `GLib.source_remove`；退出时 `flush()`。

`RequestSave()` 会**立即广播内存状态变更**给所有窗口，所以 UI 反馈是即时的，落盘稍后才发生。

### 4.3 读取、校验与迁移
`Load()` 顺序：

1. 文件不存在 → 写默认值（118 个元素全启用、`rotation="never"`、`lastSymbol="U"`、右上角锚点）；
2. 解析失败 / IO 异常 → 把损坏文件复制成 `config.json.bak` 保留现场，再回退默认值；
3. 解析成功 → `Migrate()` 逐字段校验：
   - `enabledSymbols` 过滤掉数据契约里不存在的符号并去重；
   - `rotation` 不是合法 id → 回退 `never`；
   - `anchor` 不是合法枚举 → 回退 `TopRight`；
   - `blockSize` clamp 到 80–320，`monitorIndex` / `rotationCursor` 取非负；
   - `lastSymbol` 不在 118 个元素里 → 置 null；
   - `nextFireUtc` 解析失败或早于两年前 → 置 null（由调度器重新排程）；
   - 设置 `version = 1`。将来做 v2 时在这里按版本加分支即可。

### 4.4 并发
应用是单实例（命名 Mutex / Gtk.Application D-Bus），所以**只有一个进程会写这个文件**，不需要文件锁。UI 修改都发生在主线程（Windows 轮换定时器经 `DispatcherQueue` 切回 UI 线程，Linux GLib 回调本来就在主循环），因此内存状态也没有竞态。若用户在应用运行时手工改文件，改动不会自动生效——重启应用即可（文档中已说明）。

## 5. 升级与重装行为

| 场景 | 结果 |
|---|---|
| 安装新版本 deb / MSIX | `/usr/share`（或包内 Assets）里的只读数据被替换；`config.json` 在用户目录原地保留，字段按 `Migrate()` 补齐 |
| 卸载后重装（未清理 home） | 设置完整恢复，包括上次显示的元素与下次切换时刻 |
| 配置文件损坏 | 自动备份 `.bak` + 默认值，用户可手工从备份恢复 |
| 系统休眠 / 关机 | `nextFireUtc` 仍在；恢复后若已过期只补切一次，并从"现在"重新排程 |

## 6. 与只读数据的关系

```
shared/elements.json      ← 随包发布，不可写；决定 118 个元素与周期表坐标
shared/intervals.json     ← 随包发布，不可写；决定可选间隔
shared/theme.json         ← 随包发布，不可写；决定方块配色/字号
config.json               ← 用户可写；只存"选择"，不存"数据"
```

这是刻意的分工：**用户偏好与领域数据分离**。以后要更新原子量或加入新元素，只需换数据文件，不会弄脏用户的启用列表；反过来，用户怎么点也不会破坏随包资源。
