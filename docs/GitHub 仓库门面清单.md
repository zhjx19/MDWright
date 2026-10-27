# GitHub 仓库门面清单

> 标准很简单：**一个从没听过这个工具的人，只有四个入口能判断它是什么、值不值得下载**——仓库 About、Topics、Releases、README 首屏。四处写死在这份清单里，发版前后照着勾；issues / wiki / discussions 在项目没到那一步之前不铺。
> 版本：v3.2.4（2026-10-25，首个 Release 已发布）。

---

## 一、About：先能被搜到

仓库首页右侧 **About → ⚙**。

| 字段 | 现值 | 规则 |
|---|---|---|
| Description | **空**（待填） | ≤ 350 字符，建议 ≤ 120 字；不写版本号 |
| Website | **空** | 留空，或填 Releases 页；不要填尚不存在的官网 |
| Topics | **空**（待填） | 最多 20 个，小写字母 / 数字 / 连字符 |

### Description（直接粘）

```text
墨匠 MDWright — Windows 单机 Markdown 写作台：分页 / Word / PDF 导出、三线表、可运行代码块、图表离线渲染。本地运行、断网可用；不做公众号排版，也不是 Markdown linter。
```

三句话的分工，改之前先读：

- 前半句全是**检索词**：Windows、Markdown、写作台、导出、三线表、离线——没人会搜「墨匠」；
- 「不做公众号排版，也不是 Markdown linter」是**排除项**：中文「墨匠」在公众号排版领域另有项目（微信「一键排版」的 AI 代号就叫墨匠），不写清会有一半误访；同理「linter」挡掉把它当检查工具的人；
- 不写版本号与下载量：About 里会过期的东西一律不放，版本看 Releases。

### Topics（一个个加，回车确认）

```text
markdown  markdown-editor  windows  desktop-app  pandoc  docx  pdf-export
typesetting  chinese  offline  python  webview2  code-runner  agpl
```

排序原则：GitHub 搜索按 topic 聚合，**前五个是主战场**（markdown / markdown-editor / windows / desktop-app / pandoc），后面的负责长尾（typesetting、chinese、offline 是它区别于海外同类的地方）。

---

## 二、Release：一次发版的固定动作

### tag 与版本号，三处必须一致

见 `AGENTS.md`「发布必改三处」：

| 位置 | 形态 |
|---|---|
| `CHANGELOG.md` 首段 | `## vX.Y.Z（YYYY-MM-DD）` |
| `md_server.APP_VERSION` | `"X.Y.Z"` |
| `md_server.MD_SERVER_VERSION` | 整数，服务端路由/能力变更时 +1（`md_launch` 依此自愈换代） |

`mdwright.html` 关于窗口里的版本号取自 `/api/version` 的 `app` 字段，**不要另写一处**。

### 顺序

1. 改代码 → `MD_SERVER_VERSION` +1、`APP_VERSION` 改、CHANGELOG 加段（现象 / 根因 / 修法 / 验证四件事）；
2. `md_stop.cmd` 停实例 → `python\python.exe tests\run_all.py`（全套串行，单文件 300s 超时；先停实例，否则 18766 被占着会出与代码无关的 FAIL）；
3. `python\python.exe installer\_build_installer.py --smoke` → 通过后去掉 `--smoke` 正式构建；
4. 记下 `(Get-FileHash "_setup_out\MDWright-Setup-vX.Y.Z.exe" -Algorithm SHA256).Hash`；
5. `git push origin main`；
6. 网页发 Release（见下）。

### 为什么 exe 只能手动上传

`_setup_out/` 在 `.gitignore` 里（安装包不入库，避免仓库体积膨胀），所以资产只能从本机上载。本机没装 `gh`、也没有可用 token，网页是唯一通道——不要为了省这一步去改 `.gitignore`。

### 网页端六步

1. <https://github.com/zhjx19/MDWright/releases/new>
2. **Choose a tag** 输 `vX.Y.Z` → 点「Create new tag: vX.Y.Z on publish」（不用先手动建 tag）
3. **Target** 选 `main`（确认它就是刚推的那个 commit）
4. **Title**：`墨匠 MDWright vX.Y.Z`
5. **Describe**：按下节骨架；**Attach binaries** 拖入 `_setup_out\MDWright-Setup-vX.Y.Z.exe`
6. 不勾 prerelease、不存草稿 → **Publish release**

### 正文骨架

```markdown
## 墨匠 MDWright vX.Y.Z

<一句话：这一版解决什么>

### 本版（vX.Y.Z）

- **新增**：…
- **修**：现象 → 根因 → 修法，一行说清
- **文档**：…

### 安装

下载 `MDWright-Setup-vX.Y.Z.exe`，双击安装，**不需要管理员权限**。装完自动注册右键菜单、`.md` / `.smd` 关联、桌面与开始菜单快捷方式。

SHA256：`<完整值>`
```

三条硬规矩：

1. **只写现象、根因、修法、验证**；不写自评、不写路线图、不写「欢迎反馈」；
2. **不要把外部清单贴进来**：v3.2.4 的正文末尾就误粘了一段「发布后顺手核对三件事」（那是自检清单），发布完才发现要回去编辑——正文只放用户需要知道的；
3. **首次 release 要把此前没单独发过版本的修复一起列出**：用户看不到 3.2.1 / 3.2.2 的条目，只发 3.2.4 时若只写 3.2.4，等于告诉他们那三个修复不存在。

---

## 三、发布后核对（四条，一条都不能省）

| # | 检查 | 判据 |
|---|---|---|
| 1 | Releases 计数 +1、该条带 **Latest** | 仓库首页右侧与 Releases 页 |
| 2 | **`digest` 与本地 SHA256 逐字一致** | 比大小可靠：这是 GitHub 自己算的哈希，唯一能证明「上传的包没坏」 |
| 3 | README「安装」段的资产名与实际文件名一致 | `MDWright-Setup-vX.Y.Z.exe`，改名就同步改 README |
| 4 | 装一次**下载回来的**包 | 「关于」显示版本号、标题栏是「墨匠 MDWright」——别只信本地构建 |

```powershell
# 本地哈希（小写，与 GitHub 的 digest 同格式）
(Get-FileHash "_setup_out\MDWright-Setup-v3.2.4.exe" -Algorithm SHA256).Hash.ToLower()

# 远端：看 assets[].digest 与 size（代理端口先确认：git config --get http.proxy）
curl.exe -s --proxy http://127.0.0.1:9567 https://api.github.com/repos/zhjx19/MDWright/releases/latest
```

> 代理是本机 `127.0.0.1:9567`，代理没起时 `git push` 与 `curl` 都会连不上，表现为 `Failed to connect to github.com port 443 via 127.0.0.1`。这不是仓库问题。

---

## 四、README 首屏

| 位置 | 要求 |
|---|---|
| 第 1 行 | `# 墨匠 MDWright`（中文名在前，英文名是技术标识） |
| 第 3 行 | 一句话说清「是什么 + 给谁」：Windows 上的单机 Markdown 写作台 |
| 第 5 行 | 中英文名的关系（墨 = Markdown 的 M，匠 = -wright）+ 排除项（不做公众号排版、不是 linter） |
| 截图 | 必须来自真实界面：`python\python.exe docs\screenshots\_make_screenshots.py` 重录；改界面就重录，旧截图比没截图更糟 |
| 视频 | 播放走 **GitHub Pages**：`docs/video/index.html`（`<video>` + 下载兜底）→ `https://zhjx19.github.io/MDWright/video/`，`docs/` 作站点根，视频以 `video/mp4` 直供、支持 Range。**另外两条路都不可用**：① README 内联只认 `user-attachments` 地址，仓库内 mp4 与 raw 链接会被清洗；② blob 预览页不渲染超过约 1 MB 的文件（社区实测 4.73 MB 的 mp4 也是「Sorry about that, but we can't show files that are this big right now」）。<br>踩过的坑：Pages 默认跑 Jekyll，`docs/` 里 `superpowers/plans/*.md` 含 Python 源码 `return "{%s}%s" % (…)` 被 Liquid 当标签解析 → 构建失败；**`docs/.nojekyll` 关掉 Jekyll 后即通过**（静态托管不需要它，也避免其它代码块被静默改写）。<br>若要走 `user-attachments`：拖拽上传后**先在地址栏打开该 URL 确认能播再提交**——上传中断会得到 404 的空壳地址（2026-10-26 连踩两次） |
| 首屏禁止 | 路线图、待办清单、Star 数、「本项目由 AI 生成」的自我辩解（这句放在致谢里，不占首屏） |

---

## 五、为什么元数据比名字更要紧

名字只影响「搜到之后的辨识」，`description` 与 `topics` 决定「能不能被搜到」。

v3.2.4 发布时的实际状态：Release 挂得很好（tag、Latest、资产、digest 全对），但仓库 `description` 与 `topics` 都是空的——GitHub 站内搜「markdown 编辑器 windows 离线」时，这个仓库没有任何字段能匹配上。**先补元数据，再谈名字的传播**；改名解决不了冷启动，元数据能。

---

## 六、当前状态（2026-10-27）

| 项 | 状态 |
|---|---|
| About · Description | 已填（按第一节文案） |
| About · Topics | 已填 14 个（按第一节列表） |
| Releases | 三条：`v3.4.1`（Latest，资产 26,161,152 字节，`digest` 与本地 SHA256 逐字一致）、`v3.3.4`（26,156,032 字节）、`v3.2.4`（26,133,504 字节） |
| Release 正文 | `v3.4.1` 只写用户需要知道的（本版 + 同批未单独发布的 3.4.0），无自检清单；`v3.3.4` 同理（本版 + 3.3.0–3.3.3） |
| tag | `v3.3.0`–`v3.3.4` 均已推送；**`v3.4.1` 的 tag 建成了不带 `v` 的 `3.4.1`**（2026-10-27 发布时漏写），与既有 `v*` 命名不一致，下次改版前按第四节改回 `v3.4.1` 并删掉裸 `3.4.1` |
| 下载回来的包 | `v3.4.1` 的 `digest` 与本地哈希逐字一致（`sha256:56968902…be3`）；装一次下载回来的包待核（「关于」应为 3.4.1） |
