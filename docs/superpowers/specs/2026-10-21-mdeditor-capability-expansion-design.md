# MDEditor 能力扩展设计（语法 / 导出 / AI / R）

- 日期：2026-10-21
- 基线：MarkdownEditor v2.0.0（git `d7035eb`，接手时的原仓状态）
- 目标版本序列：v2.1.0（R1）→ v2.2.0（R2）→ v2.3.0（R3）→ v2.4.0（R4）

---

## 1. 背景与目标

本仓库是他人开发的本地 Markdown 编辑器（MDEditor）。本轮在其上做能力扩展，目标：

1. **语法**：补齐脚注、提示块、行内高亮/上下标、定义列表、YAML front matter，并加入代码语法高亮。
2. **导出**：新增 Word（`.docx`，走本地 pandoc）与 PDF 直出文件（走 headless Chromium，Typora 路线）两条出口。
3. **AI**：DeepSeek 从「顺带能用」升为一等后端。
4. **R**：检测式接入本机 R 运行时，使 R 代码块可执行并渲染图。

成功判据：

- 预览 / 独立 HTML 导出 / 分页导出 / PDF 直出 四处渲染**同源**，同一份文档不出现四种观感。
- Word 导出中 LaTeX 公式落为 Word 原生公式（OMML），非图片、非 LaTeX 源码。
- PDF 直出无需打印对话框，一次点击产出文件，纸张尺寸与分页设置一致。
- 任何外部依赖（pandoc / R / 浏览器）缺失时**优雅降级**：不崩溃、不静默产出坏文件、给出可执行的下一步指引。

不在本轮范围：图表引擎扩容（新增 ECharts 等）、编辑区内核改造（contenteditable 分支）、`.smd` 格式变更、AI 新业务能力（摘要/对话/翻译）。

---

## 2. 现状盘点（实测事实）

| 事实 | 值 | 来源 |
|---|---|---|
| 开发工作区 | `MarkdownEditor-app/`，v2.0.0，587 个文件入 git | 本轮 `git init` |
| 分发快照 | `MarkdownEditor/`，v1.5.0，缺图表引擎与 AI 模块 | 目录比对 |
| 总体积 | 57.1 MB（`python/` 38.6 MB 占 68%） | 目录测量 |
| 内嵌运行时 | Python 3.11.9 embeddable；site-packages = pywebview 6.2.1 (+pythonnet/cffi/clr_loader/bottle/proxy_tools)、Pillow 13.0.0 | `site-packages` 列举 |
| 后端 | `md_server.py` 109KB，纯标准库 HTTP 服务（ThreadingTCPServer） | 源码 |
| 前端 | `markdown-editor.html` 154KB，HTML/CSS/JS 全内联，单页 | 源码 |
| 解析器 | `parseMarkdown` / `parseInline` / `parseList` / `parseTable` / `parseFenceLang`；行内占位机制 `toks`/`escs`/`codes` | 源码 |
| 图表引擎 | mermaid 10.9.3 / viz-js 3.2.0 / WaveDrom 3.7.0 / Vega 6.4.0+Lite 6.5.0+Embed 7.3.0，懒加载 | `docs/分发清单.md` |
| 代码高亮 | **无**。仅输出 `class="lang-xxx"`，无着色规则、无 vendor | grep `highlight|hljs|prism` |
| pandoc | 本机无独立安装；命中 RStudio 自带 `D:\Program Files\RStudio\resources\app\bin\quarto\bin\tools\pandoc.exe`（3.10）与 Quarto 自带 `C:\Program Files\Quarto\bin\tools\pandoc.exe` | 探测 |
| R | `D:\R-4.6.1\bin\Rscript.exe`，R 4.6.1，1285 包（含 knitr / ggplot2 / rmarkdown / dplyr / jsonlite）；注册表 `HKLM\SOFTWARE\R-core\R\4.6.1 → d:\R-4.6.1` | 探测 |
| 浏览器 | Edge 155、Chrome 155、WebView2 运行时 155 均在 | 探测 |

### 2.1 本轮已完成的可行性验证（实测证据）

| 验证项 | 结论 | 证据 |
|---|---|---|
| pandoc LaTeX → Word 公式 | 原生 OMML | `word/document.xml` 含 `<m:oMath>`×3、`<m:sSup>`、`<m:f>` |
| pandoc 脚注 | 原生 | `w:footnoteReference` + `word/footnotes.xml` 正文 |
| pandoc YAML front matter | 原生 | 写进 `docProps/core.xml` 的 `dc:title` |
| pandoc 上下标 | 原生 | `w:vertAlign val="superscript"/"subscript"` |
| pandoc `==高亮==` | **需显式 `-f markdown+mark`** | 默认输出字面 `==重点==`；`+mark` 后出现 `w:highlight` |
| pandoc 定义列表 | 原生 | 语法一致，无需转换 |
| headless `--print-to-pdf` 认 CSS 纸张 | 是 | `@page{size:100mm 200mm}` → MediaBox `99.82×200.07mm`（精确吻合） |
| headless `--dump-dom` | 可用 | 输出含 `pagedjs_page` ×3 与自定义标记 |
| highlight.js 含 R | 是 | `hljs.registerLanguage("r", …)` 独立语言文件存在 |
| R 注册表探测 | 可用（与盘符无关） | `HKLM\SOFTWARE\R-core\R\4.6.1 → d:\R-4.6.1` |

---

## 3. 范围与工作包

| 包 | 内容 | 依赖 | 版本 |
|---|---|---|---|
| **R1** 语法与渲染 | 脚注、Callout、`==高亮==`/`^上标^`/`~下标~`、定义列表、YAML front matter、代码高亮、代码复制按钮 | — | v2.1.0 |
| **R2** 导出新格式 | Word `.docx`（pandoc）、PDF 直出（headless Chromium） | R1 方言定稿 | v2.2.0 |
| **R3** DeepSeek | 一等后端：默认地址、模型预设、reasoner 参数差异 | — | v2.3.0 |
| **R4** 外部工具链与 R 代码块 | pandoc/R/quarto/浏览器 统一探测与配置；R 代码块执行 | — | v2.4.0 |

R3 与其余包零耦合，可并行。R2 必须等 R1 方言定稿后再实现预处理层。

### 3.1 一致性契约

1. **四出口同源**：预览、独立 HTML 导出、分页导出、PDF 直出全部消费前端 `parseMarkdown` 的产物。任何新语法只在前端实现一次。
2. **Word 是唯一异构通道**：Word 导出消费 **markdown 源**（非 HTML），故需后端方言→pandoc 转换层；该层只处理 pandoc 不认的部分，不得重复实现 pandoc 已支持的语法。
3. **fail-closed**：解析失败、工具缺失、渲染失败，一律显式报错或降级提示，不静默吞内容、不产出半成品文件。

---

## 4. R1 语法与渲染设计

### 4.1 脚注 `[^label]`

- **引用**：`这是脚注[^a]。` label 为任意非空白串。
- **定义**：`[^a]: 说明文字`。续行需缩进 4 空格并紧跟定义行；空行终止该定义。
- **编号**：按**引用首次出现顺序**。未被引用的定义不渲染、不占号。同一 label 多次引用共用一个编号，回链到首次引用处。
- **渲染**：正文 `<sup class="fn-ref"><a href="#fnref-1" id="fn-1">1</a></sup>`；文末 `<section class="footnotes"><hr><ol><li id="fn-1">… <a href="#fnref-1">↩</a></li></ol></section>`。
- **实现**：文档级占位，复用 `parseInline` 的 `toks` 机制；脚注区在 `parseMarkdown` 收尾时追加。
- **导出**：四出口同源；pandoc 原生。

### 4.2 提示块 Callout

- **类型**：`NOTE` / `TIP` / `IMPORTANT` / `WARNING` / `CAUTION`（GitHub 五型）。
- **写法**：
  ```
  > [!NOTE]
  > 正文首行
  > 正文续行
  ```
  可带标题：`> [!WARNING] 注意此操作不可逆`。
- **渲染**：`<div class="callout callout-note"><p class="callout-title">NOTE</p>…</div>`，CSS 左侧色条 + 淡底色；标题行用对应类型色。
- **pandoc 转换**：`> [!NOTE] 标题` → `> **NOTE** 标题`（引用块 + 粗体标签）。
- **导出**：四出口同源；pandoc 走转换层。

### 4.3 行内高亮 / 上标 / 下标

| 语法 | 渲染 | pandoc |
|---|---|---|
| `==高亮==` | `<mark>` | 需 `-f markdown+mark` |
| `^上标^` | `<sup>` | 原生 |
| `~下标~` | `<sub>` | 原生 |

- **优先级**：`~~删除线~~` 必须先于 `~下标~` 匹配，否则 `~~a~~` 会被拆成两个下标。
- **约束**：下标/上标内容不含空白与 `~`/`^`（`~([^\s~]+)~`、`\^([^\s^]+)\^`）。
- 与既有 `~~删除线~~`、`**加粗**`、`` `代码` `` 共存，顺序：代码 → 转义 → 图片/链接占位 → 删除线 → 高亮 → 上下标 → 加粗/斜体。

### 4.4 定义列表

```
术语
: 定义说明
: 第二条定义
```

- 渲染 `<dl><dt>术语</dt><dd>定义说明</dd><dd>第二条定义</dd></dl>`。
- 连续 `: ` 行归入上一术语；空行或非 `: ` 行终止。

### 4.5 YAML front matter

- **位置**：仅文档第一行是 `---` 时生效，到下一个 `---`（或 `...`）为止。
- **支持深度（极简子集）**：嵌套 map（缩进）、列表（`- item`）、标量（字符串去引号 / 数字 / 布尔 / null）。
- **解析失败**：整块当作普通段落（fail-closed），不吞内容。
- **用途**：
  - Word 导出 → pandoc 原生读作 metadata → 写入 docx 核心属性（title/author/date）。
  - HTML / 分页导出 → 注入 `<meta>` 与文档标题。
  - 分页导出的文档标题与文件名默认值。

### 4.6 代码语法高亮

- **vendor**：`highlight/highlight.min.js`（highlight.js 11.11.1 common 集，约 37 种语言，含 **R**、Python、JS/TS、SQL、Bash、Go、Rust、Java、C/C++/C#、JSON、YAML、Markdown）+ `highlight/styles/github.css`、`highlight/styles/github-dark.css`。
- **许可**：BSD-3-Clause（非 MIT，需在 `LICENSES/` 与 `docs/版权与开源组件声明.md` 准确登记为 BSD-3-Clause）。
- **加载**：懒加载，首次遇到**非图表**代码围栏时载入（与 mermaid/vega 同一 `loadVendor` 机制）；文档无代码则零加载。
- **着色时机**：前端着色完成后 DOM 已是带 `hljs-*` class 的 span，**服务端导出只需注入主题 CSS**，无需内联 120KB JS，独立 HTML 仍是可分发的单文件。
- **主题**：跟随编辑器明暗（两套 CSS 切换）。
- **图表围栏不参与高亮**：mermaid / dot / graphviz / viz / wavedrom / wavejson / vega / vega-lite / vegalite 是图表容器，走 `mountDiagrams`。

### 4.7 代码块复制按钮

- 每个 `pre` 右上角「复制」按钮，复制纯代码文本（去语言标注），成功后 toast「已复制」。
- **导出时移除**：服务端在 `build_standalone_html` / `build_paged_html` 中剥离 `.copy-btn` 节点（独立 HTML 内 clipboard 在 `file://` 下不可靠，且按钮对读者无意义）。

---

## 5. R2 导出新格式设计

### 5.1 Word `.docx`（pandoc 通道）

```
前端「导出 Word」→ POST /api/export-docx {path, markdown}
  1. 探测 pandoc（§7.2）→ 未命中 → 400 {ok:false, error:"未检测到 pandoc.exe，可手动指定路径或安装"}
  2. 方言预处理（md_pandoc.py）
       Callout      →  > **NOTE**
       图片 {N}     →  {width=N%}
       图表围栏     →  保持代码块
       其余原样透传
  3. 工作目录：普通 .md → 文档所在目录；.smd → 已解包目录 runtime/tmp/<hash>/（包内图片 pandoc 可解析）
  4. 执行：pandoc -f markdown+mark -t docx --resource-path=<workdir> -o <名>.docx <tmp.md>
  5. 落盘：文档同目录 <文档名>.docx
  6. 返回 {ok:true, path} → 前端 toast + 「打开所在目录」
```

- **公式**：`$...$` / `$$...$$` 原样交给 pandoc，落为 OMML 原生公式。
- **图片**：pandoc 按 `--resource-path` 解析相对路径并嵌入 `word/media/`；`.smd` 走解包目录故包内图片同样可嵌入。
- **失败**：捕获 pandoc stderr 原样回报（如图片缺失），不吞错。
- **不做**：reference.docx 样式模板定制（YAGNI，pandoc 默认样式已可用）。

### 5.2 PDF 直出（headless Chromium 通道，Typora 路线）

```
前端「导出 PDF」→ POST /api/export-pdf {path}
  1. 复用 build_paged_html → document.paged.html（纸张/页边距/页码/目录/排版全部沿用现有设置）
  2. 探测浏览器（§7.2）→ 未命中 → 400 + 前端按钮置灰（现有「打印」按钮照常可用）
  3. 两趟法：
       趟1  --dump-dom --virtual-time-budget=N   → 统计 .pagedjs_page 数 = P
       趟2  --print-to-pdf                        → 统计 PDF 页数      = Q
       Q == P → 成功
       Q != P → 加大预算重试（预算序列 30000 → 60000 → 120000 ms，最多 2 次重试）
       仍不等 → 报错「分页未稳定，请改用「打印」对话框」
  4. 落盘：文档同目录 <文档名>.pdf
```

- **命令行**：
  ```
  <browser> --headless=new --disable-gpu --no-sandbox --no-pdf-header-footer
             --user-data-dir=<临时目录> --virtual-time-budget=30000
             --print-to-pdf=<out.pdf> "http://127.0.0.1:18766/static/document.paged.html"
  ```
- **纸张**：CSS `@page` 尺寸被 headless 认（已实测），故 A4/B5/自定义全部正确。
- **页数校验**：`--dump-dom` 的 DOM 统计 `.pagedjs_page`；PDF 页数由服务端解析 `/Type /Page` 计数。
- **降级**：参数不被当前浏览器版本支持（--no-pdf-header-footer 等）→ 捕获非零退出码 → 明确报错并引导用「打印」。

### 5.3 前端按钮与既有入口的关系

| 按钮 | 行为 | 状态 |
|---|---|---|
| 打印（既有） | 浏览器打印对话框 | 保留 |
| 导出 PDF（新增） | headless 直出文件 | 无浏览器时置灰 |
| 导出 Word（新增） | pandoc → docx | 无 pandoc 时置灰 |

---

## 6. R3 DeepSeek 设计

| 项 | 设计 |
|---|---|
| 后端枚举 | `llm_client.py` 增加 `deepseek`，协议族同 `openai`（`_chat_url` → `<base>/chat/completions`，`_models_url` → `<base>/models`，`Authorization: Bearer`） |
| 默认地址 | `https://api.deepseek.com/v1`；用户填 `https://api.deepseek.com` 时沿用既有 `/v1` 补全逻辑 |
| 模型预设 | `deepseek-chat`（通用）、`deepseek-reasoner`（推理）；前端下拉直接给出，后端 `/models` 仍可拉取 |
| **reasoner 差异** | DeepSeek 官方说明 reasoner 不支持采样参数 → 模型名含 `reasoner` 时**请求体不带 `temperature`**（也不带 top_p），避免 400 |
| API Key | 复用既有 `api_key` 字段；前端选 `deepseek` 时显示 Key 行（与 `openai` 同一行） |
| 兼容 | 既有 `openai` 后端行为一行不改；`md_server._norm_llm_config` 白名单加 `deepseek`；旧的 `openai` 配置继续按原逻辑工作 |

---

## 7. R4 外部工具链与 R 代码块

### 7.1 统一探测

新增模块 `md_tools.py`，单一探测顺序：

```
settings.json 显式路径  →  PATH  →  常见安装目录 / 注册表
```

| 工具 | 探测点 |
|---|---|
| pandoc | `settings.tools.pandoc_path` → PATH → `%ProgramFiles%\Pandoc\pandoc.exe` → `%LOCALAPPDATA%\Pandoc\pandoc.exe` → `%ProgramFiles%\Quarto\bin\tools\pandoc.exe` → `%ProgramFiles(x86)%\RStudio\resources\app\bin\quarto\bin\tools\pandoc.exe` → `%ProgramFiles%\RStudio\resources\app\bin\quarto\bin\tools\pandoc.exe` |
| R | `settings.tools.rscript_path` → PATH → 注册表 `HKLM\SOFTWARE\R-core\R\*\InstallPath` → `<InstallPath>\bin\x64\Rscript.exe` → `<InstallPath>\bin\Rscript.exe` → `C:\Program Files\R\R-*\bin\x64\Rscript.exe` |
| quarto | `settings.tools.quarto_path` → PATH → `%ProgramFiles%\Quarto\bin\quarto.exe` |
| 浏览器 | `settings.tools.browser_path` → `%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe` → `%ProgramFiles%\Microsoft\Edge\Application\msedge.exe` → `%ProgramFiles%\Google\Chrome\Application\chrome.exe` → `%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe` |

- 注册表探测用 `winreg`（标准库），读 `HKLM\SOFTWARE\R-core\R` 各子键的 `InstallPath`。
- 版本获取：各自 `--version` 首行。

### 7.2 接口

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/tools` | GET | 探测结果 + 当前生效配置：`{pandoc:{found,path,version}, r:{...}, quarto:{...}, browser:{...}, configured:{...}}` |
| `/api/tools` | PUT | 保存手填路径到 `runtime/settings.json` 的 `tools` 段（`pandoc_path`/`rscript_path`/`quarto_path`/`browser_path`），保存后立即重探并返回新结果 |
| `/api/export-docx` | POST | §5.1 |
| `/api/export-pdf` | POST | §5.2 |
| `/api/run-r` | POST | §7.3 |

前端：设置面板新增「外部工具」区（状态灯 + 手填路径 + 「重新检测」）。设置面板现有分段（llm / rag / web_search）结构不变。

### 7.3 R 代码块执行

```
```r 围栏右上角出现「▶ 运行」按钮（仅 r / R 语言）
前端 POST /api/run-r {code}
  1. 探测 Rscript（§7.1）→ 未命中 → 400 {ok:false, error:"未检测到 R 运行时，可指定 Rscript 路径"}
  2. 生成临时脚本：
       options(warn = 1)
       sink(stdout_txt); sink(stderr_txt, type = "message")
       png(png_file, width = 1600, height = 1000, res = 150)
       result <- tryCatch(withVisible(eval(parse(text = CODE))),
                          error = function(e) list(value = NULL, error = conditionMessage(e)))
       invisible(dev.off())
       sink(type = "message"); sink()
  3. 执行 Rscript --vanilla -f tmp.R，60s 超时
  4. 返回 {ok, stdout, stderr, image:"<png 路径>", error}
  5. 前端在代码块下方渲染：文本输出（等宽块）+ 图形（经既有 /img 代理）；错误红框显示
```

- 末值是 `ggplot` 或函数时 `print()` 一次；代码内部已 `print()` 的图直接被 png 设备捕获。
- 图落在 `runtime/tmp/r-plot-<hash>.png`，经既有 `/img?path=` 代理显示。
- **UI 必须明示**：执行的是用户自己的 R 代码，行为与用户本地执行等同。

### 7.4 降级矩阵

| 缺失 | 表现 |
|---|---|
| pandoc | 「导出 Word」置灰 + 提示可指定路径或安装 |
| R | 「▶ 运行」置灰 + 提示未检测到 R 运行时 |
| 浏览器 | 「导出 PDF」置灰；「打印」照常可用 |
| quarto | 不影响任何功能（本轮不依赖 quarto 执行） |

---

## 8. 测试策略

沿用现有 `_test_*.py` 体例：抽真实源码跑 node（仿 `_test_list_parse.py`）、真服务 HTTP（仿 `_test_paged_e2e.py`）、必要时 playwright。

| 文件 | 覆盖 |
|---|---|
| `_test_syntax.py` | 脚注编号按引用序 / 未引用定义不占号 / Callout 五型与标题 / `==高亮==` / `^上标^`、`~下标~` / `~~删除线~~` 优先级 / 定义列表多定义 / YAML 极简子集与解析失败降级 / 复制按钮存在性 |
| `_test_highlight.py` | vendor 存在性与许可登记 / 语言集含 r / 懒加载链路 / 图表围栏不参与高亮 / 导出注入主题 CSS 且剥离 `.copy-btn` |
| `_test_pandoc.py` | pandoc 探测路径优先级 / 方言预处理三则转换 / md→docx 产出 / **OMML 断言**（`word/document.xml` 含 `m:oMath`）/ 脚注与定义列表往返 / 图片嵌入 `word/media/` |
| `_test_pdf_export.py` | 浏览器探测 / 两趟法页数一致性 / PDF `%PDF` 头 / MediaBox 尺寸与 `@page` 一致 / 缺浏览器降级 |
| `_test_r_run.py` | R 探测（注册表路径）/ stdout 捕获 / 图产出 / 错误路径 / 无 R 降级 |
| `_test_llm_deepseek.py` | 默认地址 / 模型预设 / **reasoner 请求体不含 temperature** / 旧 `openai` 行为回归 |

回归要求：既有 22 个 `_test_*.py` 全绿。每个发布包单独提交测试，`MD_SERVER_VERSION` 随包递增以触发旧页面自愈刷新。

---

## 9. 文档与分发

- `CHANGELOG.md`：按仓库体例（现象 / 根因 / 修法 / 验证）逐包写条目；版本号 v2.1.0 → v2.2.0 → v2.3.0 → v2.4.0。
- `README.md`：功能速览补新语法、两条导出、DeepSeek；核心文件清单补 `highlight/` vendor。
- `docs/MDEditor 使用指南.md`：新增「语法速查」条目（脚注 / Callout / 高亮 / 上下标 / 定义列表 / front matter / 代码高亮与 R 执行）。
- `docs/分发清单.md`：补 highlight.js 行与最小分发集更新。
- `LICENSES/`：补 highlight.js（BSD-3-Clause）全文；`docs/版权与开源组件声明.md` 同步。
- 体积影响：highlight.js common + 2 套主题 ≈ +130 KB。

---

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| pandoc / R / 浏览器均为外部依赖，用户未必有 | 检测 + 手填路径 + 明确安装指引 + 优雅降级；不自动安装（用户已确认自备） |
| headless 参数在旧版浏览器行为不同 | 非零退出码即捕获 → 明确报错并引导「打印」 |
| Paged.js 分页未完成导致半截 PDF | 两趟法 + 页数校验 + 预算递增重试；仍失败则报错不产出文件 |
| 引入 `==`/`^`/`~` 与既有语法冲突 | 固定匹配优先级（§4.3）；`~~` 先于 `~`；回归测试锁定 |
| YAML 极简子集覆盖不足 | 解析失败即整块当普通段落，用户内容不丢；后续可扩 |
| R 执行用户代码 | UI 明示；仅本地执行，不外发；60s 超时 |
| highlight.js 许可与 AGPL-3.0 并存 | BSD-3 无传染性，`LICENSES/` 与版权声明准确登记 |
| 单文件前端已达 154KB，继续膨胀 | 本轮不做内核拆分（不在范围）；新增逻辑集中于独立后端模块与少量前端函数 |

---

## 11. 落地顺序

```
R1 语法与渲染（v2.1.0）   ← 地基，四出口同源的前提
R2 导出新格式（v2.2.0）   ← 依赖 R1 方言定稿
R3 DeepSeek（v2.3.0）     ← 零耦合
R4 工具链与 R 代码块（v2.4.0）
```

每包独立可发布：独立测试、独立 CHANGELOG 条目、独立 `MD_SERVER_VERSION` 递增、独立提交。

本文件是**项目级规格**，覆盖四个子项目。实施阶段按 §11 顺序推进，**每个子项目单独产出实现计划并单独走一轮实现**（R1 的计划先行，R2/R3/R4 在各自包开始前再写），避免一份巨型计划失控。
