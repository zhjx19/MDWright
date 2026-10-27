# macOS 移植设计（v3.5.0 候选）

日期：2026-10-27　状态：待评审

## 1. 目标与边界

**目标**：产出一个可在 Apple Silicon Mac 上双击运行的 `MDWright.app`，功能与 Windows 版对齐——写作、即时渲染、Word/PDF 导出、R/Python 会话、`.smd` 文档、LLM/RAG。

**不做**（见 §8）：Intel 构建、Mac App Store、Developer ID 签名公证、Sparkle 自动更新、托盘常驻。

**已知不可验证项**：WKWebView 实际渲染、原生对话框、菜单栏行为、Gatekeeper 首次放行。这四项在本机（Windows）与 CI 上都测不到，只能靠 Beta 用户反馈。设计的首要目标不是优雅，是**可预测**。

## 2. 现状事实（逐文件实测）

| 层 | 文件 | 行数 | Windows 绑定 | 后果 |
|---|---|---|---|---|
| 服务端 | `md_server.py` | 3061 | 托盘 `ctypes` 264 行（1668–1931）、字体枚举 `winreg`（603–646）、`explorer /select`（787）、`netstat/taskkill`（447–453）、文档目录 `winreg`（2536–2547） | 全部在函数内，**无模块级调用** → mac 上今天就能起服务 |
| 入口 | `md_launch.pyw` | 303 | `wmic`/PowerShell/`taskkill`/`FindWindowW`/WebView2 路径约 150 行 | 整份需要重写 |
| 内嵌窗口 | `md_app.pyw` | 315 | WebView2 环境变量、`.ico`、`creationflags` 约 40 行 | pywebview 本身跨平台 |
| 原生对话框 | `_pickfile`/`_savefile`/`_pickdir_modern` | 395 | 纯 Win32/COM | mac 换 `osascript` |
| 启动画面 | `_splash.py` | 308 | 纯 Win32 GDI | mac 不用 |
| 工具探测 | `md_tools.py` | 193 | 注册表约 70 行 | 改路径候选即可 |
| 打包安装 | `install/uninstall.cmd`、`MDWright.cs`、`_mklnk.ps1` | ~600 | 全 Windows | 换 `.app` + `Info.plist` |

- Windows 专属约 **1700 行 / 全部约 6000 行 Python**，其中 1100 行是桌面集成外壳。
- 第三方依赖只有 **Pillow**（`md_server.py:2017`、`md_runs.py:194`）。`python/Lib/site-packages/bottle.py` 无任何 import，是残留。
- 前端 `mdwright.html` 与平台无关，仅 3 处文案需要平台化：`MDWright.exe`（1327、2599）与 `pandoc.exe`（2684 附近，mac 上应显示为 `pandoc`）。

**结论**：这不是「移植」，是「把外壳换掉」。核心零改动。

## 3. 关键决策

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| D1 | 代码组织 | `_plat` 门面 + `_plat_win` / `_plat_mac`（strangler） | 行为隔离清楚，Windows 可回归；若就地 `if sys.platform`，逻辑散落 8 个文件，`md_server.py` 已 3061 行 |
| D2 | `.app` 形式 | 便携布局（sh 启动壳 + `Resources/python`） | 与 Windows 同构；PyInstaller 的 pyobjc/WKWebView hook 一旦出错，CI 日志里只能靠猜，而本机无法调试 |
| D3 | 数据目录 | mac → `~/Library/Application Support/MDWright` | `.app` 内不可写：改内容破坏签名，Gatekeeper 重定位后数据会消失 |
| D4 | 外部工具 | 只带 Python；pandoc / R / Chrome 由用户自装并自动探测 | 用户决定。代价：不装 pandoc 时 Word 导出不可用，Release 说明必须写明 |
| D5 | PDF 引擎 | 探测 Chrome/Edge 走 CDP，缺失退化为 `window.print` | 与 Windows 完全同构，不引入不可测的新路径。WKWebView 原生打印虽零依赖，但属新代码且本机无法验证 |
| D6 | 架构 | 仅 arm64 | 2026 年 Intel Mac 已停止大版本支持；universal2 要两套运行时逐个 lipo，风险大于收益 |
| D7 | 签名 | ad-hoc（`codesign -s -`） | Apple Silicon **强制要求**至少 ad-hoc，否则「无法打开」；正式签名留到 P5 |
| D8 | Finder 集成 | `odoc` Apple Event → inbox 文件 → 服务端轮询 | 单一消费者；inbox 路径可在 CI 无头测试，是本项目 mac 侧唯一可自动验证的 UI 相关逻辑 |
| D9 | 文件关联 | `LSHandlerRank = Alternate` | 不抢 Typora/MacDown 的默认，只出现在「打开方式」 |
| D10 | 发布 | mac 全自动；Windows 手工纪律不变 | mac 侧无既有设施，不照搬 digest 核对/手工上传那套仪式 |

## 4. 架构

### 4.1 `_plat` 门面

只收**存在真实平台差异**的能力，不做万能抽象：

```python
data_dir()                       -> str          # 运行期可写目录
pick_file(start, types)          -> str          # 原生「打开文件」
pick_dir(start)                  -> str          # 原生「选择目录」
pick_save(name, start)           -> str          # 原生「另存为」
reveal(path)                     -> bool         # 在 Finder / 资源管理器中显示
font_names()                     -> list[str]    # 导出 Word 的字体下拉
tool_candidates(kind)            -> list[str]    # pandoc/browser/rscript/quarto/python
spawn_kwargs()                   -> dict         # subprocess 启动参数（无窗口等）
register_open_events(callback)   -> None         # mac: odoc；win: no-op
tray(server)                     -> object|None  # mac 返回 None
```

- `_plat_win.py`：把现有实现**原样搬进去**，行为逐字节不变。
- `_plat_mac.py`：`osascript` 对话框、`open -R` 显示、`fc-list` 或内置字体清单、mac 路径候选。
- 对话框保留现有「子进程 + 临时文件」惯例（`_run_picker(...)`）：`_plat.pick_file/pick_dir/pick_save` 内部按平台选脚本——Windows 用现有 `_pickfile.py` / `_pickdir_modern.py` / `_savefile.py`，mac 用新增 `_pick_mac.py`（内部调 `osascript`），不引入 pyobjc 依赖。

### 4.2 数据目录迁移

| 位置 | 迁移后 |
|---|---|
| `runtime/settings.json`、`window.json` | `data_dir()/…` |
| `runtime/userdata/`（WKWebView 数据） | `data_dir()/userdata/` |
| `runtime/tmp/runs/`、`runtime/tmp/` | `data_dir()/tmp/…` |
| `runtime/lifecycle.log`、`hang.log`、`*.err` | `data_dir()/…` |
| `_slice/`（导出切图缓存，`md_server.py:2068`） | `data_dir()/slice/` |

- `MDWRIGHT_HOME` 环境变量覆盖 `data_dir()`，供 CI / 便携 / 排障使用。
- **只读资源留在 bundle 内**：`mdwright.html`、`docs/`、`katex/`、`mermaid/`、`highlight/`、`pagedjs/`、`viz/`、`vega/`、`wavedrom/`、图标。
- 约 20 处调用点，机械替换；Windows 下 `data_dir()` 仍返回 `HERE/runtime`，**行为零变化**。

### 4.3 进程与窗口模型

与 Windows 同构：每个 `.md` 一个新窗口，共享 18766 单实例服务；最后一个窗口关闭 → 服务退出。

差异仅三处：无托盘、无 splash、关窗即退出（不学 mac 文档型 App 的「关窗不退出」，否则服务变孤岛）。

### 4.4 Finder 集成链路

```
Finder 双击 .md
  └─ Apple Event (odoc) ──写──▶ data_dir()/inbox/<uuid>.json
                                      │
      open MDWright.app file.md ──────┤   （同一入口）
                                      ▼
                          服务端 0.5s 轮询 inbox → 开新窗口
```

- pyobjc 只做一件事：包一层 `NSApp.delegate` 代理以接收 `application:openFiles:`，并转发原有回调（保住 pywebview 的关闭/退出行为）。
- 代理若在某个 pywebview 版本上失效，inbox 通路照常工作——这是设计上的兜底，不是额外保险。

### 4.5 `.app` 结构

```
MDWright.app/Contents/
  MacOS/MDWright               ← ~10 行 sh，exec Resources/python/bin/python3 md_launch.py "$@"
  Resources/python/            ← python-build-standalone 3.11 aarch64 + pillow + pywebview + pyobjc
  Resources/*.py *.html        ← 源码与前端
  Resources/{katex,mermaid,highlight,pagedjs,viz,vega,wavedrom,docs}/
  Info.plist
  Resources/MDWright.icns      ← 由 mdwright.ico 经 iconutil 生成
```

`Info.plist` 关键键：`CFBundleIdentifier=io.github.zhjx19.mdwright`、`CFBundleName=MDWright`、`CFBundleDisplayName=墨匠 MDWright`、`CFBundleShortVersionString=<APP_VERSION>`、`LSMinimumSystemVersion=12.0`、`NSPrincipalClass=NSApplication`、`NSHighResolutionCapable=true`、`CFBundleDocumentTypes`（`md/markdown/smd`，`LSHandlerRank=Alternate`）、`UTExportedTypeDeclarations`（`.smd`）。

### 4.6 打包与签名

`installer/_build_macos.py`（新增）：

1. 组装 bundle 目录树
2. **由内向外**逐个 ad-hoc 签所有 Mach-O（`.dylib` / `.so` / 可执行），再签 `.app`；`--deep` 已废弃，不可用
3. `codesign --verify --strict` 断言，失败即中止
4. `ditto -c -k --sequesterRsrc --keepParent` 出 zip

### 4.7 CI

仓库为公开仓库，标准 runner 不计量，macOS 构建零成本。

```yaml
# .github/workflows/ci.yml（P1，双平台跑现有代码）
on: [push, pull_request]
jobs:
  test:
    strategy: matrix: { os: [windows-latest, macos-14] }
    steps: checkout → setup-python 3.11 → pip install pillow
           → 跑 tests/run_all.py（需先去掉对 python\ 目录布局的依赖）

# .github/workflows/release-mac.yml（P5）
on: push: tags: ['v*', 'mac-v*']
  → 校验 tag 与 APP_VERSION 一致（不一致 fail）
  → pip install pillow pywebview pyobjc-* → 下载 python-build-standalone
  → python installer/_build_macos.py
  → 无头 smoke：起服务 → /api/version、/ → brew install pandoc → 导出 docx
  → codesign --verify --strict
  → v*   → 上传到 draft release（Windows 包随后手工补挂，再由人点发布）
  → mac-v* → 直接创建并发布（mac 单独修复路径，零人工）
```

### 4.8 版本

平台层改动属于服务端改动 → `MD_SERVER_VERSION` +1；`APP_VERSION` 与 `CHANGELOG.md` 首段同步（沿 `AGENTS.md` 的三处规则）。mac 包版本号跟 `APP_VERSION` 走，不另立版本线。

## 5. 分期

| 期 | 内容 | 验收标准 | 工期 |
|---|---|---|---|
| **P1** | 双平台 CI，跑**现有未改代码** | 拿到 windows-latest 与 macos-14 的真实失败清单；Windows 本机测试仍全绿 | 0.5–1 天 |
| **P2** | `_plat` 层 + 数据目录 + 工具探测 + 字体 + reveal | Windows 侧行为零变化（70 测试全绿）；mac 上服务可启动、工具探测与 reveal 可用 | 2–3 天 |
| **P3** | mac 外壳：`_pick_mac.py` 三对话框、odoc/inbox、砍托盘/splash、pywebview 配置 | 对话框可用；inbox 通路有单测 | 2–3 天 |
| **P4** | `_build_macos.py` + ad-hoc 签名 + 结构校验 | CI 产出首个 `.zip` artifact，`--verify --strict` 通过 | 2–3 天 |
| **P5** | `release-mac.yml` + draft 发布 + 前端文案去 `.exe` + README/Release 说明 | Beta 用户可下载安装并反馈 | 1 天 |

合计约 8–11 个工作日。P1 必须**先于任何代码改动**，用真实失败清单替代静态分析的猜测。

## 6. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 无真机，UI 全盲 | WKWebView 不渲染 / 对话框不弹 / 菜单缺失 | P4 出包即交 Beta 用户；每次往返修一类问题 |
| pyobjc delegate 代理与 pywebview 冲突 | Finder 双击无反应 | inbox 轮询兜底；必要时牺牲关联，改「先开 App 再拖文件」 |
| WKWebView 首次加载白屏（缺 `NSPrincipalClass` 等） | 打开一片空白，最难远程诊断 | CI 加 `plutil -lint` 与 plist 键断言；Release 说明附「白屏请回报 `data_dir()/lifecycle.log`」 |
| 便携 Python 缺 `_tkinter` / `libffi` | 崩溃或 PDF/字体功能异常 | 构建脚本固定 python-build-standalone 版本并跑 import 自检 |
| Gatekeeper 拦截（未公证） | 用户以为文件损坏 | Release 说明写「右键 → 打开」并附 `xattr -dr com.apple.quarantine` 一行命令 |
| 现有测试依赖 `python\` 布局与 `md_stop.cmd` | CI 红灯与代码无关 | P1 只改测试脚手架，不动产品代码 |
| PyPI 上的 pywebview/pyobjc 版本漂移 | 明天能构建、后天不能 | 构建脚本锁死版本号，不写 `>=` |

## 7. 测试

| 层 | 覆盖 | 手段 |
|---|---|---|
| 现有 70 个测试 | 双平台 | `tests/run_all.py`，端口 18777/18790 已隔离 |
| `_plat` 契约 | 双平台 | 新增 `tests/_test_platform.py`：`data_dir()` 可写、`tool_candidates()` 非空、`reveal()` 返回 bool |
| inbox / odoc | ✅ 可测 | 写 inbox 文件 → 断言新窗口被请求 |
| 服务端 + 导出 | ✅ 可测 | CI 无头：`/api/version`、首页 200、docx 导出 |
| WKWebView / 对话框 / Gatekeeper | ❌ 不可测 | Beta 用户人工验收（见 §9） |

## 8. 不做的事（YAGNI）

- universal2 / Intel 构建
- 托盘常驻、启动画面
- Mac App Store 分发
- Sparkle 自动更新
- 把 Windows 打包搬进 CI（Windows 手工纪律不变，`_setup_out/` 与 exe 上传照旧）
- WKWebView 原生打印 PDF（见 D5）

## 9. 验收清单（Beta 用户手册）

装好后逐项打勾，任一项失败请回报对应日志：

1. 双击 `MDWright.app` 能打开，出现「墨匠 MDWright」窗口（白屏 → `lifecycle.log`）
2. 「打开文件」能弹出原生对话框（失效 → `pickdir.log`）
3. 编辑区实时渲染：标题、表格、代码块高亮（失效 → 截图 + Web Inspector）
4. `Cmd+S` 保存回原文件；「另存为」落在 `~/Documents`
5. 双击 `.md` 文件 → 新窗口打开该文件（失效 → 先开 App 再拖入）
6. 导出 PDF（无 Chrome 时走打印对话框）
7. 导出 Word（未装 pandoc 时应给出明确安装提示，而非静默失败）
8. 运行一段 R / Python 代码块（未装 R 时应提示指定 Rscript 路径）
9. 关闭所有窗口后，`lsof -i :18766` 无残留
