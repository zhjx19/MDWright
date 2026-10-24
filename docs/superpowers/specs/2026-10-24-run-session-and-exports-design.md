# 代码块运行会话与导出链路设计（v3.2.0）

日期：2026-10-24　状态：待评审

## 1. 目标

三件事，一起做，一起发：

1. **文件菜单拆分 + 关于窗口**：`最近文件 / 内置文档` 拆成两项，末尾加「关于」（版本号 3.2.0）。
2. **代码块运行结果可存活**：结果不再只活在预览 DOM 里——关程序、重开文档、导出 Word 都要在。
3. **代码块之间共享变量**：同一文档里前面的块定义的变量，后面的块能直接用。
4. **Word 表格三线化**：受「排版 → 三线表」开关控制，开关打开时 Word 里也是三线表。

## 2. 现状与缺口

| 事实 | 位置 | 后果 |
|---|---|---|
| 每次运行都是新进程（`subprocess.run` 一次） | `md_server._run_r_code` / `_run_py_code` | 变量不跨块 |
| 输出只写进预览 DOM 的 `.r-out` | `mdwright.html` `runCodeBlock()` | 重开文档即丢 |
| Word 导出吃 **markdown 源文** | `/api/export-docx` → `md_pandoc` | 输出必然不进 Word |
| R 出图落在 `runtime/tmp/` | `_run_r_code` | 重启后图失效 |
| pandoc 表格只写 `<w:tblStyle w:val="Table"/>`，无显式边框 | 实测 `document.xml` | Word 里只有表头下一条线 |

## 3. 决策（已与用户确认）

| 议题 | 决定 | 理由 |
|---|---|---|
| 变量复用 | **常驻会话**（每「文档 × 语言」一个进程） | 跑第二块秒回，符合迭代分析习惯 |
| 输出存档 | **侧车文件**（不写进 `.md` 源文） | 源文保持用户所写；重开可恢复；导出可注入 |
| 表格三线化 | **导出后改 XML**（不引 reference.docx、不加第三方依赖） | 精确、可按开关生效、无二进制资源 |
| 关于窗口 | 名称 / 版本 / 许可 / 上游说明 + 两个按钮 | 用户已确认不再加内容 |
| `.smd` 与未命名文档 | **纳入**（`.smd` 打进包；未命名存临时区） | 用户已确认 |

## 4. 架构

### 4.1 会话层（`md_server.py` 新增 `_RUN_SESSIONS`）

- 键：`(doc_key, lang)`。`doc_key` 为规范化绝对路径；未命名文档用前端传入的 `token`（`untitled:<token>`，`sessionStorage` 里按标签页生成一次，刷新不变、关标签页即失效）。
- 进程：
  - R：`<rscript> <workdir>/_driver.R <workdir>`
  - Python：`<exe> -u -X utf8 <workdir>/_driver.py <workdir>`
- 运行协议（避免 JSON 转义地狱，R 侧零第三方包）：
  1. 父进程写 `<id>.code`（UTF-8）到会话工作目录；
  2. 父进程向子进程 stdin 写一行 `<id>`；
  3. 子进程读 id → 从 `<id>.code` 取源码 → 执行 → 写 `<id>.out.txt` / `<id>.err.txt` / `<id>.png`（仅 R）/ `<id>.status`（`ok` 或 `err<TAB>消息`）→ 往 stdout 回一行 `DONE <id>`；
  4. 父进程读 stdout 直到 `DONE <id>`，超时（默认 60 秒，沿用现状）则杀掉会话并返回超时错误。
- 语义保持：R 仍是控制台语义（`withVisible` + 可见值自动 `print`、ggplot 出图、`library()` 静默）；Python 仍按脚本语义（不自动打印表达式）。
- 生命周期：首次运行创建；「重置会话」或空闲 30 分钟回收；服务退出时全部杀掉（`atexit`）。
- 并发：同一 `(doc, lang)` 串行，第二次运行返回 409「上一块还在运行」。
- 崩溃/超时：会话标记为死，下次运行自动重建，响应带 `restarted: true`，前端提示「会话已重启，变量已丢失」。

### 4.2 输出侧车

路径按文档形态分三种，**写盘只在服务端做**：

| 文档形态 | 侧车 | R 出图 |
|---|---|---|
| `.md` | `<doc>.md.assets/runs/run-outputs.json` | `<doc>.md.assets/runs/run-<hash>.png` |
| `.smd` | 包内条目 `runs/run-outputs.json` | 包内 `runs/run-<hash>.png` |
| 未命名 | `runtime/tmp/runs/<token>/run-outputs.json` | 同目录 |

> 为什么单开 `runs/` 而不是塞进 `assets/`：`.smd` 的 `save_from_dir()` 会**删除 `assets/` 里没被正文引用的孤儿资产**（`PROTECTED` 只保 `annotations.json`）。运行图的引用写在侧车里、不在正文里，放进 `assets/` 会被下一次保存静默清掉。独立 `runs/` 目录不参与该清理，也不会污染用户的图片目录。

格式（数组而非字典：**按代码原文匹配**，前端无需实现哈希）：

```json
{
  "version": 1,
  "blocks": [
    {
      "lang": "r",
      "code": "x <- 1:10\nmean(x)",
      "stdout": "[1] 5.5\n",
      "stderr": "",
      "error": "",
      "image": "run-3f2a1b.png",
      "runtime": "builtin",
      "python": "",
      "ranAt": "2026-10-24T20:30:00"
    }
  ]
}
```

- 匹配口径：`(lang, code)` 完全相等。**代码一改就对不上，旧输出不再显示**（不展示过期结果，也不做「已过期」的灰色提示——宁可空着，也不让人误读）。
- `.smd` 与预览的对接：包内图按现有约定解包到 `base_dir_for(smd)`，前端拿到的仍是可渲染的绝对路径；写回时按 ZIP 追加模式只加变化条目（沿用 `_smd.py` 的既有契约）。
- 损坏/超限（> 2 MB）→ 当空处理，不阻塞打开文档。

### 4.3 HTTP 契约

| 端点 | 入参 | 出参 |
|---|---|---|
| `POST /api/run-r`、`/api/run-py` | `{code, doc, token}` | `{ok, stdout, stderr, error, image, runtime, python, restarted}`；成功后**顺带写侧车** |

> 兼容口径：请求里**没有** `doc` 也没有 `token` 时按一次性执行（不建会话、不写侧车），保持既有调用方与 `_test_run_r` / `_test_run_py` 的行为不变。真实界面永远带 `token` 或 `doc`。
| `GET /api/run-outputs` | `?doc=&token=` | `{ok, blocks:[...]}` |
| `POST /api/run-reset` | `{doc, token, lang?}` | `{ok, killed:[...]}` |
| `POST /api/export-docx` | 新增 `threeLine: bool` | 原有出参 |

`image` 字段返回可直接给 `<img src>` 的相对引用（`.md` 为 `<stem>.assets/run-x.png`，`.smd` 为 `assets/run-x.png`）。

### 4.4 前端

- `mountRunners()` 之后新增 `restoreRunOutputs()`：拉 `GET /api/run-outputs`，按 `(lang, code)` 把 `.r-out` 填回去（样式与运行时标记完全复用现在的渲染函数）。
- 每次重渲（render）后都重试恢复——编辑器刷新会重建 DOM。
- 工具栏「跟随」右侧加 `⟳ 会话` 按钮：hover 显示已连的解释器；点击调 `/api/run-reset`，Toast 提示「会话已重置」。
- 未命名文档的输出块底部加一行说明：「当前文档未保存为 .md，运行结果只在本次使用期间保留」。

### 4.5 导出

| 出口 | 现状 | 本轮 |
|---|---|---|
| 独立 HTML | bodyHtml 已含 `.r-out`；`/img?path=` 改写成 `file:///` | 只需图落到 assets（4.2 已解决） |
| 分页 / PDF | 同上，图由服务端提供 | 同上 |
| Word | 吃源文，输出全丢 | 新增注入 + 三线表 |

**Word 注入**（`md_pandoc.inject_run_outputs`）：扫源文的围栏块，取每块的 `(lang, code)` 去侧车匹配，命中则在闭合围栏后插入：

- 文字输出 → ```` ```output ```` 代码块（等宽呈现）
- 有错误 → 同块内先写 `[错误] <error>`，再写已有的 stdout
- 有图 → 下行插入 `![运行输出](<绝对路径>){80}`
- 未命中 → 什么都不插

**Word 三线表**（`md_pandoc.three_line_tables`）：pandoc 出包后改写 `word/document.xml`：

- 每个 `<w:tbl>` 的 `<w:tblPr>` 内插入 `<w:tblBorders>`：上/下 `single` 1.5 磅、左右无、内部横线无、竖线无
- 表头行每个 `<w:tc>` 的 `<w:tcPr>` 内插入 `<w:tcBorders><w:bottom single 1pt/>`
- **元素顺序按 OOXML schema 插入**（`tblBorders` 在 `tblInd/shd` 之后、`tblLayout/tblLook` 之前；`tcBorders` 在 `tcW/gridSpan/vMerge` 之后、`shd/tcMar/vAlign` 之前）——项目踩过 OMML 顺序导致 Word 报文件损坏的坑
- 结构自检：改完用 `pandoc -f docx -t markdown` 回读一次，读不出即判失败（绝不落一个 Word 打不开的文件）

### 4.6 文件菜单与关于

```
文件 ▾
  新建        打开…      保存      另存为…
  ────
  最近文件…
  内置文档（帮助）…
  ────
  关于
```

- `#fmOverlay` 增加 `data-mode`：`recent` 只显示最近列表，`builtin` 只显示两篇内置文档；共用现有渲染与点击逻辑
- `#aboutOverlay`：图标、`MDWright`、版本号、一行定位、`AGPL-3.0-or-later` + 「衍生自 MDEditor v2.0」、按钮「打开使用指南」「打开许可声明」「确定」；Esc 与点遮罩关闭
- 版本号单一来源：`md_server.APP_VERSION = "3.2.0"`，由 `/api/version` 带出；前端取不到时回退「—」

## 5. 错误处理与边界

| 情形 | 行为 |
|---|---|
| 运行超时（>60s） | 杀掉会话，返回「执行超时」，下次运行自动重建 |
| 会话进程崩溃 / stdin 关闭 | 下次运行重建，响应 `restarted: true` |
| 侧车损坏 / 过大 | 当空处理并重写，不影响打开文档 |
| 代码改动 | 旧输出不再显示（匹配不上），需重跑 |
| 未安装 Rscript / Python 路径无效 | 维持现有报错文案与回退逻辑 |
| 同一文档两块同时点运行 | 第二块收到 409 与明确提示 |
| 服务退出 | `atexit` 杀掉全部会话进程，避免僵尸 |

## 6. 测试

| 文件 | 覆盖 | 关键断言 |
|---|---|---|
| `_test_run_session.py` | 会话层 | R 两块共享变量；Python 两块共享变量；超时杀会话；崩溃后重建且 `restarted`；重置后变量消失；并发第二个 409 |
| `_test_run_outputs.py` | 侧车 | `.md`/`.smd`/未命名三种落点；代码改动后匹配不到；PNG 落到 assets；损坏文件当空 |
| `_test_run_export.py` | 导出 | 真导出 docx 解包：输出文本在、R 图是 `<w:drawing>`；三线表开关开 → `tblBorders` 存在且竖线为 none；关 → 不注入；pandoc 回读通过 |
| `_test_run_ui.py` | 浏览器 | 跑 A 块 → 跑 B 块引用 A 的变量成功；刷新页面输出恢复；「⟳ 会话」按钮可用 |
| `_test_about.py` | ① | 菜单三项齐全；关于窗口出现、版本 3.2.0；Esc / 点遮罩关闭 |
| `_test_menu_ui.py`（扩展） | 菜单 | 文件菜单 9 项、最近文件与内置文档分别只显示对应内容 |

## 7. 明确不做

- 不做输出的富文本化（表格/HTML 渲染），一律等宽文本 + 图片
- 不做输出可编辑（只读展示）
- 不做跨文档共享会话
- 不引入任何第三方依赖（R 侧只用 Base R，Python 侧只用标准库）
- 不重做 `.smd` 打包格式（只在现有 ZIP 结构里加两个条目）

## 8. 发布口径

- 版本号三处同步：`CHANGELOG.md` 首段、`md_server.APP_VERSION`、`md_server.MD_SERVER_VERSION`（66 → 67）
- `docs/MDWright 使用指南.md` 需补：会话与变量的行为、运行结果的保存位置、Word 三线表开关
- `AGENTS.md` 的「发布必改两处」改为三处
