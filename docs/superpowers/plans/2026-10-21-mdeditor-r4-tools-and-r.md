# MDEditor R4 外部工具配置 + R 代码块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (或 subagent-driven-development)。步骤用 `- [ ]` 勾选跟踪。

**Goal:** 补上 R2 推迟的「外部工具手工路径配置」，并让 ` ```r ` 代码块能在预览里**真执行**、把 stdout 与图（含 ggplot2）就地显示。

**Architecture:** 探测层 `md_tools.py`（R2 已建）扩展「显式路径优先」的写入与回读；执行层新增 `POST /api/run-r`（`Rscript` + 临时脚本包装：sink 捕获输出、png 设备捕获图、`par("page")` 判定是否真画了图）；前端在 R 围栏上挂「▶ 运行」按钮，输出与图渲染在代码块下方。

**Spec:** `docs/superpowers/specs/2026-10-21-mdeditor-capability-expansion-design.md` §7（外部工具链与 R 代码块）、§8 测试、§9 文档。

## Global Constraints

- 零新增依赖：后端仅标准库；R 是**外部运行时**（用户自备，本机 `d:\R-4.6.1`）。
- 执行的是**用户自己的代码**：UI 必须明示这一点（与 AI 润色同理，用户自负其责）。
- 超时 60s；临时文件与图落 `runtime/tmp/r-*`，不污染文档目录。
- 手工路径只影响探测，不改任何既有默认行为；填错回落自动探测。
- 服务版本 60→61（Task 3）。

## Review Focus

1. **R 缺失** → 明确指引，不产出半成品（`ok:false` + 文案）
2. **用户代码死循环/超长输出** → 60s 超时、输出截断，不拖死服务
3. **没画图时代码块不该出现空白图**（png 设备空跑也会生成文件）→ 用 `par("page")` 判定
4. **中文/多行/R 注释里的引号** 在 wrapper 中不被破坏（代码走独立文件，不做字符串插值）
5. **手工路径填错** → 回落自动探测（R2 已有语义，本轮加 UI 后必须仍然成立）

---

### Task 1: `PUT /api/tools` + `GET` 回读 configured

**Files:** `md_server.py`（路由）、`md_tools.py`（归一辅助）、`_test_tools.py`（扩）

**Interfaces:**
- `md_tools.norm_tools_config(cfg) -> dict`：只保留四个已知键、值 strip、非字符串归 ""
- `PUT /api/tools` body `{"config": {...}}` → `{ok, tools, configured}`
- `GET /api/tools` → `{ok, tools, configured}`（configured 供 UI 回填）

- [ ] 测试先行：PUT 往返、脏值归一（数字/Null/未知键）、GET 带回 configured
- [ ] 实现归一 + 两条路由
- [ ] 跑测试

### Task 2: `POST /api/run-r`

**Files:** `md_server.py`（路由 + helper）、`_test_run_r.py`（新）

**Interfaces:**
- `POST /api/run-r {"code": "...", "path": "<当前文档路径，可选>"}` → `{ok, stdout, stderr, image, error}`
- 图落 `runtime/tmp/r-<uuid>/plot.png`，前端走既有 `/img?path=` 显示

**wrapper 要点（写进 `_run_r_code`）：**
- 代码写独立 `code.R`，由 `run.R` 用 `readLines` 读入再 `eval(parse(text=))`——**不做字符串插值**，中文/引号/注释原样
- `sink()` 捕获 stdout、`sink(type="message")` 捕获 stderr 到文件
- `png()` 开设备 → `p0 <- par("page")` → eval → `p1 <- par("page")`；末值是 ggplot/函数则 `print()` 后再判
- `p1 == p0` 且末值不可打印 → 删掉 PNG、`image=""`（避免空白图）
- `tryCatch` 捕获 R 错误 → `ok:false`，错误原文进 `error`
- `subprocess.run(timeout=60)`

- [ ] 测试先行（cat / plot / ggplot / stop / 语法错 / 缺 R / 无图不产图）
- [ ] 实现 helper + 路由
- [ ] 跑测试

### Task 3: 前端「▶ 运行」+ 设置面板路径输入

**Files:** `markdown-editor.html`

- 设置 → 外部工具：只读 span 换成 `<input>` + 「保存」+「重新检测」；保存走 `PUT /api/tools`
- R 围栏：`mountRunners(div)` 在 `pre code[data-lang="r"]` 旁挂「▶ 运行」，输出容器在代码块下方
- UI 明示「执行的是你本机的 R 代码」
- 测试：`_test_menu_ui.py` 增浏览器级用例（R 围栏有按钮、点击后出现 stdout、设置页能保存路径并回读）

- [ ] 测试先行 → 实现 → 跑

### Task 4: 文档与版本

- `CHANGELOG.md` v2.5.0；`使用指南` 补「R 代码块」与「外部工具路径」；`README` 功能速览；`MD_SERVER_VERSION` 60→61
- 全量回归 + 重建安装包
