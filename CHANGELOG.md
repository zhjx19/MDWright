# MarkdownEditor 更新日志

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。  
版本号遵循语义版本控制。

体例：只有版本号是标题（`## vX.Y.Z`）；段内分组与要点一律用加粗（`**修复**`／`**变更**`／  
`**新增**`／`**测试**`／`**说明**`），条目写成 `- **短语**：说明`；段与段之间用 `---` 分隔。

文风：每段只写**现象、根因、修法、验证**四件事。不出现第一／二人称叙事，不写与代码行为  
无关的产品定位论证，不用口语化措辞。技术结论直接陈述，不带情绪与元评价。

---

## v2.5.0（2026-10-21）

**本次改动：外部工具手工路径配置 + R 代码块可执行（就地出图）**

**新增**

- **R 代码块执行**：` ```r ` 围栏右上角出现「**▶ 运行**」，点一下就在本机跑这段 R，**stdout 与图形直接显示在代码块下方**（base plot 与 ggplot2 都支持；ggplot 对象即使没手动 `print()` 也会画出来）。执行的是用户自己的代码，UI 已明示。后端新增 `POST /api/run-r`：代码写独立 `.R` 文件、wrapper 用 `readLines + eval(parse(text=))`（**不做字符串插值**，中文/引号/注释原样），`sink()` 捕获 stdout、`sink(connection, type="message")` 捕获 stderr（stderr 的 sink 必须先开连接，传文件名会报错），png 设备出图，60s 超时。图落 `runtime/tmp/r/`，经既有 `/img` 代理显示，只保留最近 50 张。
- **外部工具手工路径**：设置 →「外部工具」页不再是只读状态，四个工具（pandoc / 浏览器 / Rscript / quarto）各有输入框 +「保存路径」+「重新检测」。留空=自动探测；填了就用指定路径；**填错自动回落到自动探测**（不会把功能锁死）。新增 `PUT /api/tools`（归一后写入 `runtime/settings.json` 的 `tools` 段，存完立刻重探），`GET /api/tools` 增返 `configured` 供 UI 回填。为此 `Handler` 补了 `do_PUT`（转发给 `do_POST`；`BaseHTTPRequestHandler` 默认不给 PUT，会 501）。

**变更**

- **空白图判定**：png 设备即使一行图都没画也会生成文件（纯白），原先按「有没有文件」判断会渲染出一个空白图块。改为**按暗像素计数**判定（实测空白图 0 个暗像素、真图数千以上；PIL 缺失时退化为体积阈值）。设计上原打算用 R 的 `par("page")` 页计数，实测**不递增**，已弃用。
- 服务版本 60→61：`MD_SERVER_VERSION` 自愈换代。

**测试**

- 新增 `_test_run_r.py`（11 项，真 Rscript）：stdout 中文捕获、base plot 出合法 PNG、ggplot 末值未 print 也出图、R 错误与语法错的原文回传、空代码拒绝、缺 R 明确报错、中间文件不残留。
- `_test_tools.py` 扩至 21 项：配置归一（strip/非字符串/只留四键）、`PUT` 往返、`GET` 带回 `configured`、假路径回落。
- `_test_menu_ui.py` 增 4 项浏览器级：R 围栏有运行按钮、输出区挂在代码块下方、点击后回显 stdout、按钮恢复可用。

---

## v2.4.0（2026-10-21）

**本次改动：DeepSeek 从「OpenAI 兼容里顺带能跑」升级为一等后端**

**新增**

- **DeepSeek 后端**：AI 设置的后端下拉新增「DeepSeek API（api.deepseek.com）」，选中即自动填地址 `https://api.deepseek.com/v1`、显示 API Key 行、模型下拉直接给出 `deepseek-chat` / `deepseek-reasoner` 两个预设（也可点「刷新」走 `/models` 实拉）。此前要走「OpenAI 兼容」自己手填地址与模型名，填错 `/v1` 或模型名就只报一个含义不明的 HTTP 错误。
- **reasoner 不传采样参数**：`deepseek-reasoner` 不支持 `temperature` / `top_p`（官方口径，带上可能 400），调用时按模型名（不区分大小写）识别并**从请求体里省掉 temperature**；`deepseek-chat` 照常发送。这是接 DeepSeek 最容易踩的坑，单独做了回归。

**变更**

- `llm_client.py` 抽出 `OPENAI_LIKE = ("openai", "deepseek")`：端点、Bearer 鉴权、`/models` 列表三处共用同一套逻辑，`openai` 后端行为**一行未改**（回归覆盖）。
- 缺 Key 的报错按后端点名：`DeepSeek 后端需先在 LLM 设置中填写 API Key`（原先是统一的「OpenAI 兼容」）。
- `md_server._norm_llm_config` 的后端白名单加入 `deepseek`（脏配置仍归一回默认）。
- 服务版本 59→60：`MD_SERVER_VERSION` 自愈换代。

**测试**

- 新增 `_test_llm_deepseek.py`（16 项）：默认地址与 `/v1` 自动补全、chat/models 端点、Bearer 鉴权、**reasoner 不含 temperature/top_p**（含大小写变体）、deepseek-chat 照常带、缺 Key 明确报错、openai 三处回归、配置白名单、前端选项与预设存在。
- `_test_menu_ui.py` 增 4 项浏览器级：选 DeepSeek 后 Key 行显隐、地址自动填、模型预设就位且默认选中 `deepseek-chat`。
- 回归：`_test_llm_websearch.py`、`_test_routes.py`、全量 `_test_*.py` 通过。

---

## v2.3.1（2026-10-21）

**修复**

- **导出 Word / PDF 一点就提示「已取消导出」，保存框根本不出现**：现象——v2.3.0 里点「导出 → Word…/PDF…」，界面上直接冒出「已取消导出」，Windows 的「另存为」对话框从未出现。根因——保存框的**文件类型过滤器**被当成命令行参数传给 `_savefile.py`，而 Win32 的 filter 格式必须是 `描述\0通配\0…\0\0`（内嵌 NUL）；命令行参数不允许 NUL，`subprocess.run` 在启动子进程前就抛 `ValueError: embedded null character`，异常被 `except Exception: pass` 吞掉、路径回传文件未生成 → 上层读到空串即判定「用户取消」。修法——过滤器改由 `_savefile.py` **内部按扩展名构造**，argv 只传 `docx`/`pdf`；`_save_dialog_subprocess` 增加扩展名白名单。验证——`_test_outpath.py` 新增三项：保存框被真的调起、**argv 中无 NUL 字符**（这条就是复发守卫）、`_savefile.py --selftest` 断言过滤器以双 NUL 结尾且含对应通配（不弹框）。
- **`_test_startup_perf.py` 在 IDE 终端里误报**：Positron/VSCode 给子进程注入 `PYTHONPYCACHEPREFIX`，`.pyc` 被写到 IDE 的全局缓存目录而不是 `./__pycache__`，测试因此报「pyc generated after first run」失败。修法——测试启动子进程时剥掉 `PYTHONPYCACHEPREFIX`/`PYTHONDONTWRITEBYTECODE`/`PYTHONHOME`/`PYTHONPATH`，还原「用户双击启动」的环境。验证——12/12 通过。

**变更**

- 服务版本 58→59：`MD_SERVER_VERSION` 自愈换代。

---

## v2.3.0（2026-10-21）

**本次改动：工具栏改为菜单栏（5 个下拉 + 设置）、统一设置面板、Word/PDF 导出可选保存路径**

**新增**

- **菜单栏**：原来二十多个按钮平铺在一条工具栏上，找东西靠扫。改为 **5 个一级菜单 + 1 个设置按钮**：`文件`（新建/打开/保存/另存为/最近文件与内置文档）、`编辑`（标题/加粗/斜体/删除线/行内代码/引用/无序·有序·任务列表/链接/表格，12 项按语义分四组）、`视图`（分屏/预览跟随/主题）、`导出`（HTML/打印分页/Word/PDF）、`AI`（润色选中文字/RAG 润色/AI 设置）。点击开合、展开时悬停切换、Esc 与点击外部关闭；菜单的 `mousedown` 一律 `preventDefault`，**不抢编辑区焦点与选区**（否则「润色选中文字」拿到的是空选区）。所有旧按钮的 id 与处理器保持原样，只换了容器，行为零变化。
- **统一设置面板**（工具栏「设置」）：把原先散在「排版」面板里的选项按页签收拢——`外观`（主题/预览跟随）、`保存`（自动落盘间隔）、`排版`（9 类元素的字体·字号·对齐、段落缩进、表格样式）、`分页`（纸张/页边距/页码/目录）、`外部工具`（pandoc / 浏览器 / Rscript / quarto 的探测结果 + 重新检测）。设置与「视图」菜单共用同一状态源，任一处改动两边同步。原「排版」按钮已并入此处。
- **Word / PDF 导出可选保存位置**：点「导出 → Word/PDF…」先弹 **Windows 原生「另存为」框**（`_savefile.py`，`comdlg32.GetSaveFileNameW`，纯 ctypes、零依赖）：可改目录与文件名、按 `.docx`/`.pdf` 过滤、覆盖已存在文件由系统确认；**取消则完全不发导出请求**，不会悄悄写到别处。服务端新增 `/api/save-dialog` 与 `outPath` 校验（必须绝对路径、扩展名匹配、父目录存在、不得指向安装目录 docs/），非法路径返回明确原因而不是写到奇怪位置。

**变更**

- 导出入口收进「导出」菜单；工具缺失时仍按探测结果置灰并给出安装指引。
- 服务版本 57→58：`MD_SERVER_VERSION` 自愈换代，旧页面自动刷新到菜单栏版本。

**测试**

- 新增 `_test_menu_ui.py`（15 项，浏览器级）：菜单数量与名称、展开/收起（含 Esc）、12 个格式项、选中文字加粗包裹、设置面板 5 页签与切页、外部工具页显示真实探测结果、Word 导出「先保存框后导出」的调用顺序与成功提示。
- 新增 `_test_outpath.py`（9 项）：`_norm_out_path` 的六种路径情形（默认/绝对/相对/扩展名不符/父目录不存在/安装目录）+ 带 `outPath` 的端到端导出。
- 回归：`_test_export_ui.py` 4/4（按钮存在、置灰、未保存提示）、全量 `_test_*.py` 通过。

---

## v2.2.1（2026-10-21）

**修复**

- **导出报 `[WinError 17] 系统无法将文件移到不同的磁盘驱动器`**：现象——v2.2.0 导出的 Word/PDF 一点就失败，错误形如
  `'C:\Users\...\AppData\Local\Temp\mdeditor-pandoc-xxxx\out.docx' -> 'D:\...\文档.docx'`；文档在 D 盘、系统临时目录在 C 盘时必现，文档在 C 盘时正常。根因——v2.2.0 的「原子落位」把待落位的 docx 暂存在系统临时目录，而 Windows 的 `os.replace` **不允许跨卷**（EXDEV）。修法——暂存文件改建在**目标同目录**（`.mdeditor-<随机串>.docx.part`，成功后 `os.replace`、失败即删）；源码 md 与浏览器 profile 仍放系统临时目录（那两样不需要跨卷移动）。PDF 侧暂存本来就在目标目录，未受影响。验证——`_test_docx.py` 新增断言「`-o` 目标目录 == 待导出文档目录」（把跨卷复发挡在测试里）；D 盘文档 + C 盘 `%TEMP%` 真机实测：Word、PDF 均成功落盘。
- **内置文档导出会往安装目录里写产物**：现象——打开「使用指南」（位于安装目录 `docs/`）直接导出，产物落在安装目录里，既污染安装（升级被覆盖、卸载残留），装在 `Program Files` 时还会因权限失败。修法——服务端两条导出路由识别「文档位于应用目录 `docs/` 下」并拒绝，前端在 `currentBuiltin >= 0` 时直接提示，文案统一为「内置文档请先「另存为」到你自己的目录，再导出」。验证——`_test_docx.py` / `_test_pdf.py` 各加一条：请求内置文档返回 `ok:false` 且错误含「另存为」。
- **目标目录不可写时说人话**：`PermissionError` 不再原样抛出，改为「目标目录不可写：<目录>（多因位于 Program Files，需管理员权限或以普通目录另存）」。

**变更**

- 服务版本 56→57：`MD_SERVER_VERSION` 自愈换代，旧页面自动刷新。

---

## v2.2.0（2026-10-21）

**本次改动：两条新导出出口——Word（.docx，pandoc）与 PDF 直出（headless Chromium）**

**新增**

- **Word 导出（`.docx`）**：工具栏「Word」按钮 → `POST /api/export-docx` → 交 **markdown 源文**给本机 pandoc（不是 bodyHtml：pandoc 吃源文才能把结构落成 Word 结构）。**LaTeX 公式落为 Word 原生公式（OMML）**——实测 `word/document.xml` 含 `<m:oMath>`、`<m:sSup>`（上标）、`<m:f>`（分数），不是图片、不是 LaTeX 源码。方言 → pandoc 的转换只做 pandoc 不认的三件事（`md_pandoc.prepare_markdown`）：Callout `> [!NOTE]` → `> **NOTE**` 引用块、图片 `{N}` → pandoc `{width=N%}`、图表围栏剥掉 `{N}`；脚注 / 定义列表 / front matter / 行内高亮 / 上下标 / 公式全部原样透传（pandoc 原生支持）。资源路径——普通文档以所在目录为基准，`.smd` 以**解包目录**为基准（`_smd.base_dir_for`），否则包内图片全丢且不报错。验证——`_test_pandoc_prep.py` 10/10；`_test_docx.py` 13/13（OMML、脚注进 footnotes.xml、图片嵌入 word/media、front matter 进 docProps、Callout 无字面残留、中文/空格/`#` 文件名、未保存文档明确报错且不产文件）。
- **PDF 直出文件**：工具栏「PDF」按钮 → `POST /api/export-pdf` → 复用分页 HTML，用 headless Chromium 出 PDF 文件，**不开打印对话框**。实现走 **CDP 单会话**：`Page.navigate` → 轮询页面上的 `data-paged-done` 标记（由页码填充脚本在「页数连续稳定」后写入）→ `Page.printToPDF(preferCSSPageSize)`。纸张尺寸跟随 `@page`（A4 实测 MediaBox 594.96×841.92pt）。页数校验：DOM 页数必须等于 PDF 页数，不一致**删掉文件并报错**，绝不留下半截 PDF。验证——`_test_pdf.py` 9/9，连跑 3 次全 PASS。
- **外部工具探测（`md_tools.py`）**：pandoc / 浏览器 / Rscript / quarto 统一探测，顺序为「settings.json 显式路径 → PATH → 常见安装目录 / 注册表」。R 走注册表 `HKLM\SOFTWARE\R-core\R\<ver>\InstallPath`（唯一与盘符无关的探测法，本机实测 d:\R-4.6.1 能命中）。显式路径填错**回落**到自动探测，不因一次笔误永久判缺失。路由 `GET /api/tools` 供前端决定按钮是否置灰。验证——`_test_tools.py` 11/11。
- **打开所在目录**：导出成功的 toast 带「打开所在目录」按钮 → `GET /api/reveal`（资源管理器 `/select,` 定位，只接受已存在路径）。

**变更**

- **PDF 直出弃用 CLI 两趟法，改 CDP 单会话**：原设计是「`--dump-dom` 数页数 + `--print-to-pdf` 出文件，两者页数相等才算成功」。实测证伪——两个命令是**两次独立加载**，同一文档、同一 profile 连跑 6 次 dump，`.pagedjs_page` 数量依次为 2/0/1/0/3/1，`data-paged-done` 还会在只有 1 页时被提前写下；这种口径下「页数一致」既会误判完成（截断文档）也会误判未完成（白等重试）。改为 CDP 在同一会话里等待标记后再打印，中间没有二次加载：实测 3 次全部 DOM=PDF=3 页、A4 尺寸正确、单次约 2.5s。规格 §5.2 的目的（页数校验、不出半截文件）不变且真正达成。
- **分页填充脚本新增完成标记**：页码脚本判定「页数连续 3 次稳定」后写 `document.documentElement[data-paged-done=1]`，供 CDP 判断可打印。既有打印链路行为不变（`_test_paged_e2e.py` 47/47 回归通过）。
- **两个按钮按工具可用性置灰**：页面启动即 `GET /api/tools`；缺 pandoc → 「Word」置灰并提示「装 pandoc 或用自带 pandoc 的 Quarto/RStudio」；缺浏览器 → 「PDF」置灰并提示「可改用「打印」」。探测失败一律保持置灰（不假装可用）。
- **服务版本 55→56**：`MD_SERVER_VERSION` 自愈换代，旧页面自动刷新到带导出按钮的版本。

**测试**

- 新增 `_test_tools.py`（11）、`_test_pandoc_prep.py`（10）、`_test_docx.py`（13）、`_test_pdf.py`（9）、`_test_export_ui.py`（4）。
- 新增 `_cdp.py`（最小 CDP 客户端，纯标准库 WebSocket）与 `md_tools.py`、`md_pandoc.py` 两个模块。
- 回归：`_test_paged_e2e.py` 47/47、`_test_smd_ann.py`、`_test_syntax_ui.py` 全 PASS。

**说明**

- pandoc 与 Chromium 内核浏览器是**外部工具**，随本工具不分发。缺失时只是对应导出不可用，其余功能不受影响。
- 内置「外部工具路径」手工配置 UI 属下一版（R4）；本轮只做自动探测。
- 「打印」按钮保留原样：需要页码/目录页码等书册级排版时用它（Paged.js 在真实浏览器里跑），「PDF」是「一键出文件」的快捷通道。

---

## v2.1.0（2026-10-21）

**本次改动：五类 Markdown 语法扩展 + 代码语法高亮 + 代码块复制按钮**

**新增**

- **脚注（文档级）**：正文 `[^label]` 引用、文档任意处 `[^label]: 说明` 定义；编号按**引用首次出现顺序**重排（与定义先后无关），同一标签多次引用共用编号；未定义的引用保持字面原文（fail-closed，不渲染成坏链接）；定义行剥离出正文，文末自动生成脚注区（带回跳锚点）。根因约束——编辑器按 H1/H2 分块增量渲染，脚注天然是文档级语义，故 `render()` 入口先全文提取 `fx`（定义表 + 引用序编号表）再分块渲染，脚注区独立于 `.pblk` 块序列追加在预览末尾，编号签名变化时含引用的块整批重渲。验证——`_test_footnote.py` 9/9 PASS（编号序、未定义字面、定义剥离、多行定义、代码块内不生效、重复引用共用编号、无脚注不生成空区）；`_test_syntax_ui.py` 7/7 浏览器级断言真实 DOM。
- **Callout 提示块**：`> [!NOTE]` / `[!TIP]` / `[!IMPORTANT]` / `[!WARNING]` / `[!CAUTION]` 五型（可带标题 `> [!NOTE] 标题`），渲染为带类型色条的容器；普通引用块行为不变。修法——引用块分支识别首行 `[!TYPE]` 后改渲染 `.callout` 容器，正文仍走递归 `parseMarkdown`（列表/代码块等照常）。验证——`_test_callout.py` 10/10 PASS。
- **行内高亮与上下标**：`==高亮==`→`<mark>`、`^上标^`→`<sup>`、`~下标~`→`<sub>`。顺序敏感——删除线 `~~x~~` 必须先于下标匹配，否则会被拆成两个下标；行内代码段与链接 URL 内的同名字符不生效（代码段优先、链接先占位）。验证——`_test_inline_ext.py` 11/11 PASS。
- **定义列表**：`术语` + 后续 `: 定义` 行渲染为 `<dl><dt><dd>`，一条术语可带多条定义，定义续行缩进 4 空格。修法——段落分支之前先判定义列表，并给段落续行加 `: ` 终止条件；同时把段落分支改为「首行无条件吃下」，否则以 `: ` 开头的行会一行都吃不到、`i` 不推进导致死循环（实现期实测踩中）。验证——`_test_deflist.py` 7/7 PASS。
- **YAML front matter**：文档首行 `---` 起的元数据块剥离出正文（不进预览），支持极简子集（嵌套 map / 列表 / 标量，含去引号、数字、布尔、null）。解析失败（未闭合 / 非法 / 不在首行 / 重复键）一律**原样返回整篇**按普通段落渲染，一字不丢（fail-closed）；导出的 HTML 标题优先取 `title`。验证——`_test_frontmatter.py` 12/12 PASS；`_test_syntax_ui.py` 断言 YAML 与分隔线不出现在预览。
- **代码语法高亮**：highlight.js 11.11.1 common 构建（36 语言，**含 R**）就地 vendor 分发，懒加载（文档无代码则零加载），主题跟随编辑器明暗。**只按围栏声明的语言着色，不做自动探测**——实测 `highlightAuto` 会把 `plain text no lang` 判成 css 并着色，写作工具里 ASCII 图/日志/配置被乱涂是负体验。着色结果留在 DOM，导出只注入主题 CSS，独立 HTML 仍是可分发的单文件。验证——`_test_highlight.py` 11/11（vendor/语言集/许可/文档登记）；`_test_syntax_ui.py` 断言 `hljs-keyword` span 真实生成、无语言围栏不着色。
- **代码块复制按钮**：代码块右上角「复制」（悬停出现），点击把该块代码写入剪贴板（clipboard API 失败回退 `execCommand`）。导出时由**服务端**统一剥离（`_strip_export_artifacts`，两条导出出口共用），独立 HTML 里 clipboard 在 file:// 下不可靠且按钮对读者无意义。验证——`_test_copy_btn.py` 6/6 PASS（按钮数、逐块复制内容、按钮文本不污染代码、两条导出产物均无按钮）。

**变更**

- **导出与预览样式同源**：新语法样式在预览（CSS 变量跟随主题）、独立 HTML 导出、分页导出（固定色值，导出文档无 CSS 变量）三处同步；分页导出的注入序为 katex → 目录 → 新语法 → 用户排版样式，保证用户 `!important` 规则仍覆盖。验证——`_test_export_css.py` 11/11 PASS；`_test_paged_e2e.py` 47/47 回归 PASS。
- **新增 CDP 浏览器测试通道**：本机未安装 playwright，既有 `_test_list_ui.py` / `_test_outline_jump.py` 无法运行。新增 `_cdp.js`（Node 24 内置 `fetch`/`WebSocket` 直连本机 Chrome/Edge 调试端口，零安装）+ `_test_browser.py`（起服务 + headless 浏览器 + 页面内求值取 JSON），调试端口运行时探测空闲口，避免残留进程冲突。R2/R4 的浏览器级验证可复用。
- **服务版本 54→55**：`MD_SERVER_VERSION` 自愈换代，旧页面自动刷新至带新语法的版本。

**测试**

- 新增 `_test_footnote.py` / `_test_callout.py` / `_test_inline_ext.py` / `_test_deflist.py` / `_test_frontmatter.py` / `_test_highlight.py` / `_test_export_css.py` / `_test_copy_btn.py` / `_test_syntax_ui.py`，以及测试基建 `_cdp.js` / `_test_browser.py`。
- 回归：`_test_list_parse.py` 20/20、`_test_escape.py` 11/11、`_test_img_width.py` 6/6、`_test_table_split.py` 8/8、`_test_routes.py`、`_test_smd.py` 33/33、`_test_keepalive.py`、`_test_smd_ann.py`、`_test_paged_e2e.py` 47/47 全 PASS。
- **未覆盖**：`_test_list_ui.py` / `_test_outline_jump.py` 依赖 playwright（本机未装），本轮未运行；R1 只改解析器与渲染管线，不触列表 UI 与大纲跳转逻辑。

**说明**

- 图表引擎本轮不扩容（mermaid / dot / wavedrom / vega 四套维持现状）。
- highlight.js 许可为 **BSD-3-Clause**（非 MIT），无传染性，与本工具 AGPL-3.0-or-later 并存无冲突；已登记 `LICENSES/highlight.js-BSD-3-Clause.txt` 与分发清单、版权声明。
- 分发体积 +约 132KB（`highlight.min.js` 127KB + 两套主题 CSS 共 4.3KB）。

---

## v2.0.0（2026-10-20）

**本次改动：四种本地图表引擎 + 预览滚动跟随开关 + 打开/另存为扩展名过滤 + 图表 vendor 两处缺陷修复**

**新增**

- **无序列表标记方言**：`+` 渲染实心圆点（disc）、`-` 渲染空心圆圈（circle），样式跟标记符走、与缩进无关（缩进只决定嵌套层级），逐 `<li>` 显式 `list-style-type` 覆盖浏览器按嵌套深度换 marker 的默认行为；**星号退出列表标记**（`*星号*` 斜体 / `**双星**` 加粗专属，行首 `* 内容` 按普通段落处理）；有序列表编号接力语义不变。`_test_list_parse.py` 断言更新至新输出并扩至 20 例（20/20 PASS）。
- **使用指南示例图片不渲染（指南误用转义 + 解析器无转义双重根因）**：现象——指南「图片」章三处 `\!\[内嵌示例图\](...)` 预览中反斜杠原样漏出，且 `\[...\](..)` 仍被链接正则吃成真 `<a>`，示例图片全部不渲染。根因——① 指南示例写成了 `\!\[...\]` 转义形态（本意内嵌真图，写法错误）；② 解析器无反斜杠转义处理，转义与非转义之间的行为不可预期。修法——指南三处示例改回真图片写法（`![内嵌示例图](路径)`、40% 例带 `{40}`）；`parseInline` 按 CommonMark 口径补 `\X`（X 为 ASCII 标点）转义：占位符隔离后行内语法全部失效、末尾还原为字面 X（逐字符 HTML 转义不产生真标签），代码段内反斜杠保持字面（代码段优先），LaTeX 公式在 `extractMath` 文档级占位不受影响。新增 `_test_escape.py` 11 例全 PASS；`_test_img_width.py` 6/6、`_test_list_parse.py` 20/20 回归 PASS。使用指南「约定」补转义条目。
- **语法速查文档**：使用指南新增「语法速查与本工具的特殊写法」章（与标准 Markdown 差异表 + 特有写法表：`{N}` / 图表围栏 / 任务列表 / 删除线 / 公式 + 钳制与只读约定）；「列表与任务」章改用 `+/-` 双语义活示例；「排版」章补列表首行缩进行为说明；README 功能速览补方言条目与指南指引。

- **四种图表围栏本地渲染（全程离线）**：` ```mermaid `（mermaid 10.9.3 UMD 全量 3.34MB，无 ESM 分包断链）、` ```dot `／` ```graphviz `／` ```viz `（viz-js 3.2.0 standalone 1.36MB，内嵌 Graphviz 9.0.0 WASM）、` ```wavedrom `／` ```wavejson `（WaveDrom 3.7.0 55KB + default/dark 双皮肤 87KB）、` ```vega `／` ```vega-lite `／` ```vegalite `（Vega 6.4.0 + Vega-Lite 6.5.0 + Vega-Embed 7.3.0 共 840KB）。按需懒加载：文档无图零加载，首遇对应围栏才加载引擎；渲染失败容器内原样显示源码与错误；暗/亮主题切换重渲（mermaid 换 theme、wavedrom 换皮肤）；`wavedrom`／`vega` 源码仅 `JSON.parse`（fail-closed，不 eval）。后端零改动（复用 `/static/` 通用路由）。
- **预览滚动跟随开关**：工具栏「跟随」按钮（分屏切换旁），`localStorage` 键 `md-editor-follow` 持久化，默认开；`syncPreviewToEditor` 入口守卫，联动管线零侵入。
- **使用指南「图表作图」章**：mermaid 流程图（判定分支+样式）、mermaid 时序图（autonumber+alt）、dot 模块依赖拓扑、wavedrom 请求握手波形、vega 柱状图共 5 个真实示例 + 围栏对照表；wavedrom/vega 示例过严格 JSON 校验。
- **图片与图表宽度参数 `{N}`**：`![说明](路径){30}` 与 ` ```mermaid {30} `（四引擎围栏通用）→ 宽度 = 版面宽度的 30%、等比缩放；基准为版面而非原图，不同原图同参数等宽，**原始文件只读不写**（切片产生的条带存缓存目录）。预览 / 导出 HTML / 分页三处一致（内联 `style="width:N%"` 随 bodyHtml 流转）；`{150}` 钳到 100，`{0}`/非数字不生效且后缀字面保留（fail-closed）；围栏与图片的 `{N}` 规矩对称（空白可选均生效）；vega 渲染器切 `svg`（矢量缩放无损，打印同益）。分页超长图切片决策基于调整后落地宽度（`eff_w_mm = 版心 × pct`），条带继承同一宽度样式（实测 400×2400 图：满宽切 23 条、50% 切 12 条，条带几何随 eff 宽换算）；资源路径改写只动括号内路径，`){N}` 后缀原样保留。测试 `_test_img_width.py` 6/6 PASS（前端解析 21 例含围栏 13 例 + 改写保留 + 切片 4 断言）；`_test_list_parse.py` 18/18、`_test_list_ui.py`、`_test_outline_jump.py` 回归全 PASS。

**修复**

- **排版列表档「首行缩进」错位**：现象——列表设首行缩进 N 字符后渲染成「编号顶格 + 文本右移 + 中间大空隙」（`1.   xxxx`）。根因——CSS 用 `text-indent`，而它只缩进文本行、不缩进 outside 定位的编号/圆点 marker。修法——列表档首行缩进改用 `padding-left`（整项含 marker 一起右移 N em），正文段落与引用档维持 `text-indent`；排版 CSS 经 `#ts-style` 整体随导出/分页传递，预览与导出自动一致。
- **viz vendor 不内嵌 WASM**：现象——3.31.0 `viz-global.js` 无 WASM 魔数（`AGFzbQ` 计 0）、无 base64 块，运行时外部 fetch，离线 dot 渲染必挂；3.21–3.31 各版本 dist 均为同形态。根因——vendor 选型只验了路由 200，未做真实渲染验证。修法——回退 3.2.0 `lib/viz-standalone.js`（内嵌 WASM）；node 实测 `graphvizVersion 9.0.0`、11 引擎（dot/neato/fdp/circo/twopi 等）加载；五处引用同步改名（编辑器加载链、`_test_dist_verify.py`、`_setup_win.cs` 冒烟、分发清单、LICENSES）。
- **WaveDrom 渲染 childNodes null（两层叠加）**：现象——指南波形块报 `Cannot read properties of null (reading 'childNodes')`。根因——① WaveDrom 皮肤为独立必需文件（`skins/*.js` 定义 `window.WaveSkin`），未随包分发；② `RenderWaveForm(index, source, output)` 第三参为 id 前缀字符串（内部 `getElementById(output + index)`），调用误传 DOM 元素。修法——落地 `skins/default.js`+`skins/dark.js`（各 43KB）；加载链补双皮肤；渲染改自建 `#wd-{seq}` 容器并传 `'wd-'` 前缀；暗色 UI 自动注入 `obj.skin='dark'`（源码显式声明时尊重源码）。验证——真实浏览器同代码路径 E2E：`svg=YES | svgChildren=3 | width=400 | RESULT=PASS`。
- **打开/另存为对话框扩展名过滤**：现象——打开与另存对话框不限定文件类型，可选中任意文件且另存无类型提示。根因——`md_app.pyw` 内嵌窗口 SAVE_DIALOG 未传 `file_types`；浏览器/降级路径走原生框时无过滤。修法——`md_app.pyw` 传 `file_types=("Markdown (*.md;*.smd)",)`（pywebview 6.x 要求每元素为完整「描述 (通配)」格式），过滤参数任何形态失败即回退无过滤调用保可用；`md_server.py` 新增 `_pick_file_subprocess`（GetOpenFileNameW，过滤 `.md;.smd`／`.md`／`.smd`／`.txt`／所有文件五档，路径经临时文件回传，与选目录同模式）；`_pickfile.py` 过滤器同步五档。

**变更**

- **文档对齐图表能力面**：README（简介、核心必需表 +4 vendor 行、功能速览）、`docs/分发清单.md`（图表 vendor 4 行、最小分发集更新、皮肤必需依赖注）、`docs/版权与开源组件声明.md`（组件表 +6 行、许可要点补 MIT/EPL-1.0/BSD-3、pip 版差异注）；`LICENSES/` +6 文件（版本与 vendor 一一锁定；viz-js 包无 LICENSE 文件，MIT 文本手写并附 Graphviz EPL-1.0 注记）。
- **服务版本 53→54**：`MD_SERVER_VERSION` 自愈换代，旧页面自动刷新至图表能力版。

**测试**

- **`_test_dist_verify.py` 22/22 PASS**：干净目录组装 + junction 9 目录 + 真实服务 + 6 vendor 路由与双皮肤路由断言；版本断言改动态读 `MD_SERVER_VERSION`（原硬编码 52 系 v1.11.4 时期漏同步）。
- **指南围栏与语法校验**：5 个围栏提取成功，wavedrom/vega `JSON.parse` PASS；`markdown-editor.html` 内嵌 JS 与双 vendor `node --check` PASS。

**说明**

- 版本直接进 2 时代：同一版本内新增四引擎、跟随开关与文件对话框行为变更，为发布以来最大能力面增量。
- pip 安装版（markdowneditor-ldxs）不含四个图表目录，差异已在分发清单与版权声明注明。

---

## v1.11.4（2026-10-19）

**修复**

- **大纲点击跳转严重错位**：现象——点击左侧大纲条目，编辑区滚动位置与目标标题偏差极大（长文档折行场景偏差逾万像素，目标行常不在视口内）。根因——跳转滚动用行高线性估算（`行号 × lineHeight`），而编辑区为 `pre-wrap` 软折行排版，一个逻辑行占多个视觉行，估算误差随行号累积；光标定位（字符偏移）本身精确，仅滚动位置失准。修法——`buildOutline` 点击处理器改为直测光标真实位置：`setSel` 后经 `Selection.getRangeAt(0).getBoundingClientRect()` 读取光标视口坐标，`绝对位置 = scrollTop + 视口内偏移` 一次性回写（`-2 行高`留上下文）；Range 直测零累计误差、软折行天然包含，不依赖镜像测量表（该表存在约 3% 校准累计误差，对锚间插值联动无害，对绝对位置跳转为全量暴露），分屏联动代码未触碰。目标行位于文档末尾下方内容不足时按 `maxScrollTop` 钳制（物理极限，行为与预期一致）。验证——新增 `_test_outline_jump.py`（playwright 真实浏览器，130 行重度折行文档）8/8 PASS：中部标题跳转后精确落视口顶部（偏移 50.1px = 2×行高 25.2，误差 0.3px）、末尾标题滚至 `maxScrollTop` 极限且可见、光标均落目标行行首、旧行高估算偏差 14591px（证明折行偏差真实）、首项跳回顶部、无页面错误；`_test_list_ui.py` 回归 3/3 PASS。

---

## v1.11.3（2026-10-19）

**修复**

- **有序列表编号改为"接力"语义（v1.11.2 语义修正）**：现象——软回车混排 `1.`/`-`/`-` 后再输入 `1.` 或 `2.`，v1.11.2 按输入数字渲染（输入 `1.` 显示 1.），用户期望显示 2.（接续区域内有序项计数）。根因——v1.11.2 采用 CommonMark 语义（`<ol start=N>` 尊重输入数字），与本项目"显示编号由编辑器统一管理"的定位不符；另用户截图反馈的"混排仍连续编号"系编辑器页面未刷新（页面 JS 为修复前版本，服务端 HTML 每请求读盘、无缓存，刷新即新）。修法——`parseList` 增加 `seq` 参数（编号区域内已出现的有序项数，由块循环跨列表维护）：显示编号 = 区域内第 N 个有序项，**输入数字仅是语法标记不参与显示**；无序项不占编号；空行/标题/引用/表格/代码块/水平线/段落均打断区域并清零重计；嵌套子列表为独立编号区域（seq 从 0 起）。验证：`_test_list_parse.py` 18/18 PASS（含用户四例：混排切分、空行分隔、空行后 `2.` 显示 1.、软回车后 `1.`/`2.` 均显示 2. 3.、多段交替接力、输入数字无视、嵌套有序独立、标题打断重置）；新增 `_test_list_ui.py`（playwright 真实浏览器）3/3 PASS——逐行软回车敲入实测 preview DOM 为 `ol / ul / ol[start=2]`、空行后 `2.` 重置为 1.、无页面错误；表格 8/8、smd 33/33、keepalive、routes 回归全 PASS。

---

## v1.11.2（2026-10-18）

**修复**

- **有序/无序列表软换行混排 + 有序列表起始序号丢失**：现象——① 软回车（单换行）连续输入时 `1.` 后跟 `-`、`-`，无序行被吸进同一有序列表，渲染成序号 2.、3.（标记被吞）；② 单独出现的 `2.` 起始有序列表被强制从 1. 计数显示。根因——`parseList` 把同缩进下所有列表标记行收进同一列表，容器类型由首项决定，不区分标记类型；`<ol>` 输出不带 `start` 属性。修法——`markdown-editor.html` 的 `parseList`：① 同缩进下标记类型切换（有序↔无序）即收口当前列表，由外层块循环开新列表（与 CommonMark「不同 marker 不合并」一致）；② 有序列表按首项原始数字输出 `<ol start="N">`（N=1 时省略属性）。验证：新增 `_test_list_parse.py`（提取解析器段跑 node）13/13 PASS——混排切分、空行分隔、`2.` 保留 start、反向混排（无序→有序）、三标记连续混切、纯列表/星号/加号/嵌套/task/大数起始序号/列表后段落不吞全部覆盖；表格回归 8/8、解析器段 `node --check` 通过。

---

## v1.11.1（2026-10-18）

**修复**

- **启动画面不可见（窗口全透明、永不退场）+ 淡出时机重锚定**：现象——启动画面窗口已创建但完全不可见，且从不自行消失（只能靠启动器杀进程收场）。根因（分层定位）——① `_splash.py` 的 `WM_PAINT` 处理用 `GetDC/ReleaseDC` 绘制但从不 Validate 更新区域，产生 WM_PAINT 风暴；Win32 消息优先级 `WM_PAINT > WM_TIMER`，风暴把 timer 消息永久饿死——fade-in（alpha 0→246）从不执行，窗口保持初始 alpha=0 即全透明，超时退场同样失效。实测证据：消息循环 3 秒内收到数百个 WM_PAINT、零个 WM_TIMER。② 原淡出锚点是"服务版本就绪 + 盲等 0.45s"，与窗口真实加载无关：机器慢时 WebView2/浏览器冷启动空档无覆盖，机器快时提前退场。修法——① `_proc` 的 WM_PAINT 分支画完显式 `ValidateRect(hwnd, None)`（附 argtypes 声明），风暴消失、timer 恢复；② 淡出锚点改为**页面会话上线**：前端页面加载完成后发首个心跳（v1.8.0 会话机制）即代表"窗口真正加载出来"，`/api/version` 响应新增 `sessions` 字段（活跃会话数，`MD_SERVER_VERSION` 51→52），`_splash.py` 的 `_poll_ready` 轮询改为等 `sessions>=1` 再淡出（快机器一闪而过、慢机器撑到窗口出现，全自动）；③ `md_launch.pyw` 成功路径不再主动 `close_splash`（交给 splash 自理），失败路径（服务未就绪）保留硬关，`life` 超时兜底保留。验证：`_test_splash_session.py` 7/7 PASS——version 带 sessions 字段、无窗口时撑住 2s+（旧逻辑会提前退场）、会话上线后 0.25s 淡出销毁、life 兜底 2.34s 退场；fade-in 实测 alpha 0→246 正常；回归 startup_perf 12/12、keepalive 11/11、routes、RAG 19/19 全 PASS。

---

## v1.11.0（2026-10-18）

**变更**

- **启动提速（服务就绪 1.5~2.5s → 0.4~0.8s，四项优化 + 一项根因修复）**：现象——双击 `.md` 到页面可编辑体感 3~5s。根因（实测定位）——① 便携 Python 为 embeddable 发行版（`._pth` 不注入脚本目录），服务以主脚本模式 `python md_server.py` 启动，主脚本永不命中 `__pycache__` 的 .pyc，每次冷启动现场编译 85KB 源码耗时 ~1.05s；② 本机对未监听端口为 drop 非 RST，`md_launch.server_version` 探测超时 1.5s / `md_app.service_alive` 超时 2s，服务就绪前发出的探测请求被挂满超时才失败，就绪感知被额外拖慢 1~2s；③ `close_splash` 主线程同步等待启动画面淡出（0.9s）；④ `wait_version` 轮询粒度 0.25s、`/open` 开浏览器固定延迟 0.25s；⑤ `katex.min.js`（270KB）同步加载阻塞 HTML 解析。修法——① 新增 `_md_run.py` 启动 shim（手工注入脚本目录后 `import md_server` 走 .pyc 缓存再 `main()`，`python md_server.py` 直跑路径保留不变），`md_launch.start_server` 与 `md_app.ensure_service` 均改走 shim；② 探测超时统一收紧到 0.3s；③ `close_splash` 的兜底终止移入后台线程，淡出动画不再阻塞开浏览器；④ `wait_version` 改 `time.time()` 计时 + 0.05s 粒度（顺带消除原 `t += 0.25` 计数与 sleep 不同步的隐患），`/open` Timer 0.25→0.05s；⑤ `katex.min.js` 加 `defer`（前端本有「katex 未到则轮询补渲染」兜底，语义不变）。配套：`kill_stale_services`（md_launch）与 `md_stop.cmd` 的进程匹配规则同步兼容 `md_server.py` 与 `_md_run.py` 两种命令行，自愈换代与手动停止不受启动方式影响；`MD_SERVER_VERSION` 50→51。验证：`_test_startup_perf.py` 12/12 PASS——shim 冷启动（无 pyc）1.1s 可就绪并生成 .pyc、warm 启动中位 0.77s、launcher 真实链路（`start_server`→`wait_version`）三轮 0.38/0.72/0.36s、直跑 `md_server.py` 路径不破坏、进程命令行同时命中 launcher 换代杀进程规则与 md_stop.cmd 过滤规则、页面携带 defer 属性的 katex 引用；回归 keepalive 11/11、routes、RAG 19/19、RAG UI 13/13、LLM UI 17/17 全 PASS。

---

## v1.10.0（2026-10-18）

**变更**

- **RAG 默认路径改为空**：现象——`rag-assistant` 路径默认值写死为开发机绝对路径，分发给任何其他用户都是无效配置。根因——默认值应表达"未配置"而非"某台机器的布局"。修法——`RAG_DEFAULTS.path` 默认空字符串，前端输入框保留示例路径 placeholder，空路径时启动按钮报「路径无效或不存在」指引填写。验证：`_test_rag.py` 回归 PASS（默认值断言、空路径拒绝）。

**新增**

- **LLM OpenAI 兼容后端（外部 API）**：现象——润色/智能备注只能走 LM Studio / Ollama 本地推理，无法调用 OpenAI、DeepSeek、硅基流动等云端 OpenAI 兼容 API。修法——`llm_client.py` 加 `openai` 后端：默认 `https://api.openai.com/v1`，base_url 填根地址自动补 `/v1`（两种填法都通）；`api_key` 字段（Bearer 头），无 key / 未选模型在调用前明确报错而非发出必败请求；模型列表走 `GET /v1/models`。`md_server.py` 配置归一白名单加 `openai`、api_key 字符串归一；润色/解释路由的"需先选模型"检查扩展到 openai 后端。前端 backend 下拉加「OpenAI 兼容（外部 API）」、API Key 输入行（openai 时显示）、地址 placeholder 与默认值随 backend 切换。验证：`_test_llm_websearch.py` 34/34 PASS（URL 拼接含 /v1 自动补与防重复、auth 头、无 key/无模型前置校验、lmstudio/ollama 回归、归一白名单、配置往返、路由校验）；`_test_llm_ui.py` 17/17 PASS（key 行显隐、placeholder 联动、无 key 时模型拉取被拦且提示明确、保存落盘与重开回读）。
- **联网查询（润色 / AI 解释可选网络资料注入）**：现象——润色/解释仅凭模型自身知识，无法参考时效性网络信息。修法——新增 `web_search.py`（配置驱动，模式取自 rag-assistant 的 search.py，按本项目零依赖约束全部用标准库 urllib 重写）：5 个搜索源 DuckDuckGo（免费无 key）/ Tavily / Google Custom Search / Bing / 自定义 API（URL 用 `{q}` `{key}` 占位），返回统一 `{results:[{title,url,snippet}],success,error}`，key 用户自填；`md_server.py` 在 llm 配置内加 `web_search` 子段（enabled/backend/各 key/custom_url/max_results 1~10，脏数据归一回默认），润色与 AI 解释路由在开关开启时先检索选中文本（截断 200 字）、结果拼【网络资料】段进 system prompt 再交 LLM；搜索失败或无结果**静默降级**为纯模型路径并在响应带 `web_search: "degraded"` 标志，前端 toast 提示「联网搜索失败，已用纯模型结果」，成功注入 toast「已结合联网资料润色/解释」；RAG 按钮路径不受任何影响，两上下文源完全独立。前端 AI 设置面板加联网区块：开关、搜索源下拉、按搜索源动态显隐的 key/URL 输入行、结果条数。验证：`_test_llm_websearch.py`（各搜索源缺配置时的明确报错、归一限幅、降级标志 off/degraded、openai 后端回归）；真实链路验证——本机网络访问 DuckDuckGo 超时的环境下，开启联网的润色请求 29.5s 返回 `ok=true web_search=degraded` + 正常润色文本，降级路径不阻断写作流；`py_compile` 与 inline JS `node --check` 全过；keepalive 11/11、RAG 19/19、RAG UI 13/13 回归 PASS。

---

## v1.9.0（2026-10-18）

**新增**

- **RAG 检索增强润色/解释（rag-assistant 集成）**：现象——润色/解释仅凭本地 LLM 通用知识，无法参考用户自有知识库。修法——接入 rag-assistant 外部 API（`:8767`，与编辑器职责边界：编辑器只负责拉起服务、按协议传参检索、把返回上下文拼进既有 LLM prompt，原润色/解释路径零改动）：① `rag_client.py`（移植 structured-writer 成熟实现，3 次重试应对冷启动 embedding 首请求慢）；② `md_server.py` 新增路由——`GET /api/rag-status`（health + KB 列表 + 本地子进程状态探测）、`POST /api/rag/start`（异步冷启动：stderr 落临时文件防 pipe 满卡死、`PYTHONIOENCODING=utf-8`、45×2s 轮询就绪、子进程挂掉回读 Traceback 供诊断；解释器按 venv→PATH→py→sys.executable 顺序选——编辑器内嵌 Python 为纯净标准库，跑不动 rag-assistant 的 torch/chromadb 重依赖）、`POST /api/rag/stop`（terminate→wait 3s→kill→清 :8767 全部 PID→等端口释放；带看护自动重启场景返回明确提示）、`POST /api/rag/rewrite|annotate`（`/api/kb/query` 拿 `context` → 注入 system prompt 参考资料段 → 走既有 `llm_client` 生成；RAG 离线/空结果返回 `ok:false` 带指引文案）；配置存 `runtime/settings.json` rag 段（path 默认 `C:\Users\sm001\WorkBuddy\rag-assistant`、kb 空=自动路由，脏数据归一回默认）；③ 前端——选区浮动条加「RAG润色」、批注 Modal 加「RAG解释」（均复用既有润色预览/批注回填流程），AI 设置 Modal 加 RAG 管理区（状态行 + KB 下拉 + 启动/停止按钮 + 路径手动输入，随 `/api/rag/save` 一并持久化）；按钮可用性联动：页面加载与每 15s 探测 `/api/rag-status`，在线才点亮 RAG 按钮，离线置灰带提示。编辑器退出不联动停 RAG，仅按钮手动停。验证：`_test_rag.py` 19/19 PASS（路由/配置往返/归一/离线错误路径/启动参数校验/解释器选择）；`_test_rag_ui.py` 13/13 PASS（按钮初始置灰、面板状态/控件、保存落盘 rag 段）；`_test_rag_e2e.py` 7/7 PASS（真实冷启动→在线→query 协议契约返回 `context/has_context/sources/kb`→停止→端口释放）；`py_compile` 与 inline JS `node --check` 全过；keepalive 11/11 回归 PASS。

---

## v1.8.0（2026-10-18）

**变更**

- **支持多开：每个文件独立窗口，共享本地服务**：现象——每次从资源管理器打开 `.md` 都会先强杀全部旧编辑器窗口（`md_launch.pyw` 的 `kill_stale_apps` 按进程路径 taskkill），只能单开；而服务层本就共享（浏览器模式多标签复用同一 18766 后端），窗口层却全局互斥。根因——「关闭后回收」与「多开并存」被错误耦合：用全局强杀代替各窗口自管生命周期。修法——三处改动：① `md_launch.pyw` 删除 `kill_stale_apps()`，每个 `.md` 独立打开内嵌窗口/浏览器标签，端口复用与版本自愈换代逻辑保留（仅服务版本不匹配时换代，不影响正常多开）；② `md_server.py` 心跳由全局单值改为**按会话计数**：前端每标签经 `sessionStorage` 生成会话 token（同标签刷新/bfcache 恢复保持一致），`/api/ping?tok=`、`/api/bye?tok=` 按 token 登记/下线对应会话；`do_POST` 把 ping/bye 转发给 `do_GET`——此前 `sendBeacon` 的 `/api/bye` 走 POST 无路由被 404，页面正常关闭时退出信号实际从未生效；③ 看门狗判定改为「**任一会话存活即保活**，全部会话 bye 后进入宽限倒计时，宽限期内出现新会话心跳即撤销退出」——关闭单个窗口不再影响其它窗口，最后一个窗口关闭后服务自动退出；无 bye 的强杀场景沿用幽灵清理（会话按最后心跳停滞超 orphan 宽限清除，全清后按 `max(最后心跳, 服务启动)` 超时回收）。同一文件被多窗口打开时，草稿缓存按路径共享、最后写者胜（既有语义，未改）。验证：行为级时序 PASS（ping A/B 两会话 → bye A 后服务仍活、B 保活，再见 B → 2s 宽限内无心跳即退出；lifecycle.log 记录 `bye tok=… live=N` 与退出原因）；`_test_keepalive.py` 11/11 PASS；`py_compile` 与 inline JS `node --check` 全过；浏览器端 `sendBeacon` 带 tok 链路实测到达后端。

---

## v1.7.0（2026-10-18）

**新增**

- **保存失败备份与打开时恢复**：现象——保存（临时文件 + `os.replace` 原子替换）因目标异常失败时，本次全部改动只存在于解包工作目录，而会话结束即被 `clear_tmp` 清掉、下次打开回到旧包；失败残片处理也不一致（增量保存有 `finally` 清理，全量重建没有），残片散落原地。根因——失败 tmp 是本次内容跨会话的唯一幸存副本，删之即数据丢失，留之则无恢复入口。修法——失败一律保留 tmp（`<文档名>.smd.tmp<毫秒时间戳>`，名字自含目标路径与时间）：`save_from_dir` 去掉失败删残片的 `finally`，成功替换后 tmp 被 `os.replace` 消费天然无残留；`pack_from_dir`/`_save_json` 失败天然保留。打开 `.smd` 文档时服务端扫描同名 `.tmp<时间戳>` 备份（`GET /api/save-backups`），前端 toast 询问「是否恢复」，用户点击才经 `POST /api/restore-backup` 覆盖 `.smd`（三重校验：同目录同名 `.tmp\d+` 模式 + zip 有效性，防误传任意路径覆盖好包；目标在不在均允许落位），恢复后清该文档本地草稿，`base_dir_for` 指纹检测自动重解包，备份随之消费。正文文字另受既有 localStorage 草稿恢复保护；批注与图片资产依赖本备份通道（实测一次只读导致的失败保存中，批注仅存在于备份 tmp）。验证：单测 6/6 PASS（最小包构建/只读失败抛错且 tmp 保留含新内容/报错文案/恢复校验/恢复落位+指纹重解包+备份消费/乱传路径拒绝）；inline JS `node --check` 全过。
- **保存失败报错说人话**：现象——目标文件被外部置只读（OneDrive/手工均可）时 `os.replace` 报 `[WinError 5] 拒绝访问`，原始异常文案不指向根因。修法——`_friendly_save_error` 检测目标只读位（`st_mode & 0o222`），报「目标文件为只读……请解除只读后重新保存」并附失败备份 tmp 路径；`/api/save`、`/api/save-as` 统一换用。不代用户改文件属性（文件状态属用户领地，只报错不动手）。验证：单测断言报错含「只读」与 tmp 路径。

**修复**

- **页面被直接拽掉后服务永久悬挂（僵尸服务占端口）**：现象——WebView2 进程被终止时 pagehide 跑不到，`/api/bye` 发不出（lifecycle.log 无记录、窗口进程数为 0 仍占 18766 端口），看门狗 `if not bye: continue` 永久等待，须手动杀进程。根因——退出判定单一依赖页面告别信号，信号缺失即无出口。修法——加兜底：无 bye 且心跳断流超过 orphan 宽限（默认 300s，环境变量 `MD_EXIT_ORPHAN_GRACE` 可调）同样退出，基准取 `max(_LAST_PING, _START_TIME)`（起服务后从无页面接入的孤儿服务同样回收）；后台标签页心跳节流最长约 1 分钟，300s 不误杀最小化/切走窗口；「只要心跳还在服务就活着」的原语义保留。退出路径收敛为 `_do_stop(reason)`，lifecycle.log 记录退出原因。验证：5 场景行为级测试 PASS（bye 主路径退出/心跳断流兜底退出/孤儿兜底退出/心跳持续存活不退/bye 宽限期内不退）。

---

## v1.6.0（2026-10-17）

**新增**

- **选区批注（标注跟文本内容走，不跟位置走）**：现象——长文写作需要对特定片段挂备注，且编辑后标注不能错位失效。修法——编辑区由 `<textarea>` 换为 `contenteditable` div（`-webkit-user-modify:read-write-plaintext-only` 纯文本模式 + `pre-wrap` 渲染 `\n` 文本节点；非 Chromium 兜底手动拦截 Enter/粘贴/拖放），27 处 `editor.value`/`selectionStart/End` 读写收敛为 `getText()/setText()/getSel()/setSel()`（TreeWalker 定位文本节点，Range 换算偏移），上层解析/渲染/分块/镜像测量管线零改动。批注运行时锚 = 编辑区内真实 `<span data-aid>` 包裹层（对 `textContent` 零影响，源文视图与渲染完全透明）；持久化锚 = 片段文本快照。语义：文本还在 → 标注保留、快照经 MutationObserver（150ms 防抖）实时同步；片段被删光/替换 → 标注自动失效剔除；重开文档 → 按快照在正文中重找出现位置重新包裹（跳过已包裹区间），找不到即自然失效并在回写时剪枝。保存回传正文整体替换后按内存快照重锚定（`annReanchorLocal`）。持久化：`.md` → `<文档名>.assets/annotations.json`；`.smd` → 包内 `assets/annotations.json`（`_smd.PROTECTED` 白名单豁免孤儿清理，写后增量追加进包，全量整理亦保留）。交互：编辑区内选中文本 → 浮动工具条（`#selTools`，mousedown 防夺焦丢选区）→「备注」包裹新标注并弹批注 Modal；点正文虚线标注段打开 Modal（有拖选时不误触）；Modal 含备注编辑、删除标注、「AI 解释」回填；状态栏常驻批注计数；关闭页面用 `sendBeacon` 兜底落盘。验证：CDP 全流程 e2e 35/35 PASS（含重锚定、点击打开、建批注、持久化往返、过期剪枝）；`.smd` 批注往返 8/8 PASS（入包、增量保存保留、compact 保留）。
- **LLM 润色 + 智能备注 + 工具栏 AI 配置**：现象——润色需跳出工具找外部 AI，备注无内容提示。修法——`llm_client.py`（移植 structured-writer 成熟实现，纯标准库 urllib，LM Studio `:1234` / Ollama `:11434` 双后端 OpenAI 兼容 API，`list_models/test_connection/chat` + `polish/explain` 业务封装）；后端路由 `GET/PUT /api/annotations`、`POST /api/annotate`（选段解释）、`POST /api/rewrite`（润色）、`GET/PUT /api/llm-config`（持久化 `runtime/settings.json` llm 段，backend 白名单 + 数值限幅归一）、`POST /api/llm-models|llm-test`（模型列表/连通测试，业务失败一律 200+`ok:false` 前端统一读 error）。润色走"稳"流程：选区 → 浮动条「润色」→ 预览 Modal（原文/新文对照，新文可先手动微调）→「替换原文」才落编辑区（按原文快照重找定位，execCommand 进原生 undo 栈，替换区域内的批注 span 随覆盖自然剪枝）；配置 Modal：backend 下拉、base_url、模型下拉（打开即静默预取实加载列表）、timeout/max_tokens/temperature、测试连接。验证：CDP e2e 真机闭环——LM Studio qwen3-8b 实调 `/api/rewrite` 返回润色文本，预览确认后原文被精确替换、邻近批注无恙；配置 Modal 表单往返/模型列表拉取/超时数值回读全过。

**修复**

- **载入文档后状态栏统计不刷新**：现象——通过 `?file=` / 最近文件 / 内置文档载入后，字数/行数停在 0 直到首次输入。根因——`applyDocWithDraft` 只调 `render()` 不调 `updateStats()`（启动时序在文档异步载入前已跑过一次统计）。修法——`applyDocWithDraft` 两个分支（含"用磁盘版本"回退）在 `render()` 后补 `updateStats()`。验证：CDP e2e 载入 97 字文档状态栏即时显示。
- **浏览器标签页无图标**：现象——浏览器模式与打印导出页标签页 404 favicon。修法——`GET /favicon.ico` 路由返回 `md-editor.ico`（Cache-Control 86400）。验证：HTTP 200 image/x-icon，页面控制台零 404。
- **润色替换按钮偶发无效果**：现象——预览 Modal 点「替换原文」后原文未变（开发期 CDP 测试捕获）。根因——处理器内 `closeRw()` 先置 `rwCtx=null`，下一行仍读 `rwCtx.text` 抛 TypeError 中断。修法——先捕获 `orig=rwCtx.text` 再 `closeRw()`。验证：修复后 e2e 对应断言通过。

**变更**

- **HTTP 服务线程化（`socketserver.ThreadingTCPServer` + `daemon_threads`）**：现象——LLM 调用最长可达 timeout 秒（默认 180），单线程 `TCPServer` 期间心跳/保存/全部路由被卡死。修法——每请求一线程；LLM 动作路由业务性失败（连不上/没模型/空文本）统一 200 + `ok:false`，前端按 error 提示。验证：挂起慢 LLM 调用（不可达地址 30s 超时）期间 `/api/version` 亚秒响应。

**测试**

- `_test_routes.py` 新增 14 条全 PASS：批注读写/拒脏/落盘位置、LLM 配置归一限幅/落盘、模型列表与连通测试的失败路径、空文本拒绝、Ollama 无模型拦截、线程化不阻塞。
- `_test_smd_ann.py` 新增 8 条全 PASS：批注入 .smd 包、包内内容正确、增量保存/全量整理后保留、按包路径回读。
- `_e2e_cdp.ps1` 新增：CDP（DevTools Protocol over PowerShell 原生 WebSocket）浏览器真机 e2e 35 条全 PASS——contenteditable 内核（DIV 化、统计、分块渲染）、批注全交互链（重锚定、点击、新建、持久化、剪枝）、真实 LM Studio 润色替换闭环、LLM 配置 Modal、零页面异常。`_test_paged_e2e.py` 端口随副本改 18766。
- 回归：`_test_table_split.py` 8/8、`_test_smd.py` 33/33 PASS；内嵌窗口（pywebview + WebView2）拉起、页面加载、桥接 `api_version()` 调用 OK；原版（18765/v44）与副本（18766/v46）双实例共存互不干扰。

---

## v1.5.0（2026-10-17）

**新增**

- **分屏滚动联动（镜像硬锚 + 锚间百分比，单向）**：现象——分屏模式下编辑区滑动预览不跟随；此前数版在"全文仅两三个标题夹一张巨表"的文档（如发布进度表）上节点错位或预览跳段（表格中段行被整段掠过，"#36/#30 之后直接到 #44"）。修法——**节点是硬锚，节点之间是百分比**：新增编辑器镜像测量层（`#mirror`，与 textarea 同字体/行高/宽度/折行参数，逐行量出每行真实像素位置，按编辑器实际内容高整表缩放校准），软折行自动包含、零行号近似；预览侧标题元素（h1-h4）盖 `data-anchor-line` 源行标与镜像行号对应。同步规则——① **锚间百分比**：锚不可见时，所在区间两锚之间按编辑器像素进度 `f` 对预览区间像素高度插值，预览连续扫过区间全部内容，不丢段、不跳变；② **硬锚锁定**：锚 H 可见时权重 `w = 1 − H编辑器视口偏移 ÷ 视口高`（H 在视口底 w=0，到视口顶 w=1），滚动位置从百分比平滑渐变到硬锚 `H预览位置 − H编辑器视口内偏移`——锚到视口顶时两侧位置分毫不差；锚出顶瞬间的硬锚值恰为下一区间百分比 f=0 的起点，全程连续。首尾不足处用虚拟顶/底锚；编辑区到底（容差 48px）预览钉到底。重建时机：`render()` 入口（内容变化必经）+ 字体就绪 + 窗口缩放（防抖）。单向——仅编辑区挂 `scroll` 监听（rAF 节流），预览不回牵。已知限制：多行块级公式 `$$…$$` 行内化后源行号累计漂移（单行公式无影响）；节点稀疏的文档（如全文仅两个标题夹一张巨表）区间中段存在与两侧版式密度差成比例的渐进滞后（连续滑过、无跳变，锚点越密残差越小）。验证：真实文档《发布进度》实测——`## 发布地图` 锚两侧 2px 锁定；巨表前后滚动预览逐行连续经过此前被跳过的表格中段行，跳段消失；抽出真实函数源码过 `new Function` 编译；三套回归全绿（47/47、33/33、8/8）。

**修复**

- **大纲误收代码块内标题**：现象——fenced code block 内的 `# 注释` 行被大纲面板当作标题收入（如 `# 代码块第 N 行` 逐行混入大纲）。根因——`buildOutline` 逐行匹配 `^#{1,6}` 无 fence 感知。修法——扫描时跟踪 ```/~~~ 开闭状态，fence 内跳过（与分块、锚点打标口径一致）。验证：含 20 行注释代码块的测试档大纲干净，三套回归全绿。

---

## v1.4.0（2026-10-17）

**修复**

- **表格幽灵列（多余单元格被切出）**：现象——打印导出与预览中，表格右侧多出一列孤立单元格，仅个别行有内容，且该行原单元格尾部残留 `\`、新列起首残留反引号；窄列被挤压成一字一行竖排。根因——前端表格解析器 `splitRow` 对行做裸 `split('|')`，不识别 GFM 转义：单元格内行内代码 `` `\|` `` 中的竖线被当作列分隔符，该行被多切出一格。修法——切分前将 `\|` 替换为占位符、切分后还原为字面竖线（GFM 规范：表格单元格内 `\|` 恒为字面竖线，行内代码内也不例外）；正文行列数对齐表头——超出的单元格合并进本行前一列（以 `|` 接回，内容不丢失），不足的补空单元格使列边框对齐。预览与打印导出共用同一解析器，一处修复两处生效。验证：`_test_table_split.py` 8/8 PASS（测试对象为从 markdown-editor.html 抽取的真实函数源码），浏览器实测同构 9 列表格导出 8 列严丝合缝、行内代码竖线原样保留。

**变更**

- **便携运行时内置 Pillow**：现象——超高长图切片功能依赖 Pillow，而内嵌便携运行时未携带，运行时切片静默退化为整图保留（fail-closed），功能在最终用户环境不可用。修法——官方 wheel（pillow-13.0.0-cp311-cp311-win_amd64）原样解包进 `python/Lib/site-packages/`；许可文本随包保留（wheel 自带合并 LICENSE 覆盖 HPND 核心与捆入 C 库全文），收录 `LICENSES/Pillow-LICENSE.txt` 并更新 `LICENSES/README.txt` 与 `docs/版权与开源组件声明.md`（HPND/MIT-CMU 允许任何目的免费再分发，无传染性，与 AGPL-3.0-or-later 不冲突）。验证：内嵌解释器 `import PIL` 13.0.0 正常，切片 E2E（E42-E47）全绿。

**测试**

- `_test_table_split.py` 新增 8 条全 PASS：`\|` 转义还原、裸竖线多切后合并回前一列（内容不丢）、格数不足补齐、对齐样式、正常表格不受影响。
- `_test_paged_e2e.py` 回归 47/47 PASS（含此前因运行时缺 Pillow 而失败的切片组 E42-E46）；`_test_smd.py` 回归 33/33 PASS。

---

## v1.3.0（2026-10-16）

**本次改动：打印导出排版治理（基础正文样式注入 + 版面缩放纪律 + 图片版面适配）与打印/分页双入口合并**

**新增**

- **打印导出基础正文样式**：现象——分页导出的表格无边框、代码块/引用块无样式。根因——`build_paged_html` 仅注入 @page/页码、katex、目录、排版设置四层 CSS，编辑器预览的基础 `.markdown-body` 样式从未进入导出（`.html` 导出自带基础样式块故无此病）。修法——新增 `PAGED_BASE_CSS` 镜像预览基础样式（表格细边框、表头底色、pre/code/blockquote/hr），以固定色值替代 CSS 变量（导出文档内变量未定义）；注入序在排版设置之前，设置面板 `!important` 规则（如三线表）覆盖关系不变。验证：E2E E2/E3/E18/E19。
- **超高长图切片续排**：现象——2000×5140 级长截图打印导出时，整图压一页只剩 ~95mm 窄条（宽高比物理约束），文字不可读。修法——渲染高超过版心的图由服务端在导出期用 PIL 竖切为小条带（渲染高 = 版心高/6，下限 20mm）满宽续排，如表格跨页一样流入页面剩余空间、接不下才推页（页面留白上限 = 一条带高）；切点吸附静默行——目标切点 ±8mm 窗口内取行亮度最平稳处（截图空白行/段间隙）下刀，不切断文字行、不重叠不遗漏；切片缓存键 = 内容 sha1 + 条带几何（strip_px），几何参数变更时旧切片不复用；切片为导出渲染期产物，写入 `_slice/` 由 `/static` 服务，源资产一个字节不动（SSOT）；PIL 缺失或读图失败原样保留整图（fail-closed）。验证：E2E E41-E47（切片落盘/条数/原引用替换/小图不切/幂等复用）+ 真实文章长图浏览器实测（11 条满宽续排、末条后正文正常接排）。
- **保存时清理无引用资产**：现象——sha1 去重修复前的历史旧包内残留无引用资产死重（实测一包重复收编同一张 1MB 图两份，正文只引用其一）。修法——`_smd` 双守门：`save_from_dir` 保存时对照 doc.md 引用集删除解包目录中未被引用的资产，且孤儿存在即强制全量重建（追加式包结构下增量保存清不掉旧 entry）；`pack_from_dir` 打包时过滤未被引用的文件（另存为/整理同口径）。引用识别口径 `assets/<文件名>` 与包内格式契约一致；删除失败保守留存不阻断保存。夹具同步：T1/T2/T8 旧契约（无引用资产入包）改为引用对齐，新增 T14（目录孤儿 + 包内孤儿一次清除、稳态增量退化）/T16（打包过滤守门）。验证：`_test_smd.py` 33/33 PASS + `_test_paged_e2e.py` 47/47 回归。
- **版面缩放纪律（借鉴 Cogito_Scribit STYLE_GUIDE 一章、十一章）**：现象——长 token 行与超宽单元格在打印态会触发 Chromium 整本 shrink-to-fit 或横向溢出。修法——print 态 `*{box-sizing:border-box}`；pre `white-space:pre-wrap + overflow-wrap:anywhere`（print 无滚动条，超宽行直接裁切）；td/th `word-break:keep-all + overflow-wrap:anywhere`（中文不拆词、超长串兜底断行）；表格 `width:100% + table-layout:auto` 允许跨页切分，`thead{display:table-header-group}` 跨页自动重复表头，`tr/li{break-inside:avoid}` 行不腰斩。验证：E2E E4-E7。
- **引用编号索引表列宽**：现象——表头为 `编号|引用|出处` 的索引表列宽随内容漂移。修法——导出时识别该表头自动加 `ref-table` 类，`table-layout:fixed` 固定列宽 8%/47%/45%（STYLE_GUIDE 1.2），普通表格不受影响。验证：E2E E11-E13。

**变更**

- **目录版式对齐书册规范（STRUCTURE_GUIDE 6.4 + STYLE_GUIDE 11.4）**：现象——目录条目为"标题+裸页码"行内拼接，无点线、页码不成列。修法——条目改 flex 基线行：标题文本 + 点线引导（dotted leader，`flex:1` 撑满）+ 页码右对齐列（`tabular-nums` 等宽数字），一级加粗、二三级缩进保持；页码由填充脚本按标题锚真实落页回填，全部条目页码右缘统一成列、点线与页码留 6px 间距不重叠。验证：E2E E33/E34 + 浏览器实测截图。
- **页码形态对齐书册规范（6.4）**：现象——页码为"第 X 页 / 共 Y 页"居中小字，不符书册惯例。修法——默认模板改纯数字 `{p}`；位置新增「外侧（奇右偶左）」并设为默认（`@bottom-right`/`@bottom-left` 双占位盒，填充脚本按显示页码奇偶选盒）；页码 9pt 灰阶；封面/目录无页码（目录页不编号沿用）；显式选择居中/顶部等位置仍被尊重。前端旧默认一次性迁移（仅当页码模板仍为旧默认串——整组设置从未手动改过——才升级，显式自定义不动）。验证：E2E E35/E36/E38 + 浏览器实测奇页右下「1」。
- **分页规则对齐书籍标准（6.2 逐条）**：现象——分页行为为编辑器自创组合，与书册规范不一致。修法——`h1{break-before:page}` 每篇独立起页；`h2,h3,h4{break-after:avoid}` 标题不落页末；`p{orphans:2;widows:2}` 段落防孤立行；`li{orphans:1;widows:1}`（单行 bullet 配 widows 2 会永久推页留白，6.2 判例）；`hr{break-inside:avoid;break-after:avoid}` 且不加 break-before（hr+h2 保护链整块推页留半页空白，2026-08-28 判例）；纵向结构（table/pre）允许内容单元间拆页——pre 此前误加 `break-inside:avoid` 已去除（长代码块整块搬页仍装不下会溢出裁切）；blockquote 不拆保持。验证：E2E E26-E31。
- **图片版面规则定版**：现象——图片仅有 max 约束、行内随文流。修法——img 改 `display:block` 块级居中（图版独立成行惯例）+ `break-inside:avoid` 图不腰斩 + 既有 max-width/max-height 版面约束（宽超按宽缩、高超按高缩）；渲染高不超版心的图整图原子一页（上页空间不足推页留白，不因剩余空间缩放——图版尺寸稳定纪律）；超过版心的长截图转入切片续排（见「超高长图切片」）。书族正文无光栅图判例（全部为文本标注图），本条按图版惯例与十一章内容盒纪律（内容不超 ICB）执行。验证：E2E E32。

**修复**

- **图片超出版面**：现象——分页导出中高图直接溢出纸面。根因——导出对 img 无任何尺寸约束。修法——img `max-width:100%` + `max-height=纸高−上下边距−2mm`（命名纸张映射表 A0–B5/Letter/Legal/Ledger，自定义纸取 ph，下限 20mm）；浏览器对 img 的 max 约束天然保持宽高比——宽超按宽缩、高超按高缩。验证：E2E E10/E16/E20 + 浏览器截图。
- **长图打印产出连续空白页、图不可见**：现象——2000×5140 长截图打印导出后图消失，图位之后连续多页整页空白。根因——图片占位预算算术缺陷：初版安全余量仅 1mm（A4 图高 246mm），叠加 img 自身 `.8em` 外边距与段落后实际占位 ≈253mm，超出 247mm 版心——图在任一页都放不下，Paged.js 反复推新页并把图溢出裁掉。修法——打印版 img `margin:0 auto`、`p:has(>img){margin:0}`（正文图均包裹在段内，段落外边距同样计入占位）、预算余量改 2mm（A4=245mm）。验证：浏览器实测原图导出（空白页消失）+ E2E E39/E40。
- **打印/分页双入口合并**：现象——「打印」与「分页」两按钮调用同一 `/api/export-paged`，产物完全相同，语义重复。根因——打印按钮历史上为 `window.print()`，因内嵌窗口阻塞改为生成分页 HTML 后与「分页」沦为平行入口。修法——合并为单「打印」按钮（原分页处理器 + 防重入），设置面板文案与诊断信标统一为「打印」，产物名保留「分页版 HTML」。验证：`btnPrint` 引用清零 + inline script `node --check` 通过。
- **目录计入页码**：现象——目录页被编为「第 1 页」，正文从第 2 页起，目录条目页码同步偏移，不符书册惯例。根因——页脚填充脚本按物理页序无脑 `i+1` 填充全部页面，目录条目页码用 Paged.js 原生 `target-counter`（同为物理页序），两处口径都含目录页。修法——页码全部改由填充脚本确定性自管：纯目录页（页内有 `.md-toc-wrap` 且无正文标题锚）不编页码；正文页码 = 物理页序 − 前置纯目录页数，总页数为正文页数；目录条目页码弃用 `target-counter`，由脚本按标题锚真实落页的显示页码回填 `<span class="md-toc-pg">`，与页脚口径严格一致；无目录时行为退化为原物理页序（向后兼容）。验证：E2E E21-E24 + 浏览器实测（目录页脚空白、正文首页「第 1 页 / 共 5 页」、条目 1/2/3/4 与落页一致）。

**测试**

- **`_test_paged_e2e.py` 扩至 47 条全 PASS**：真实服务全链路——基础样式注入、表头跨页重复、行不腰斩、单元格断行纪律、图片版面高度（A4=245.00mm / 自定义 210×140 边距20=98.00mm / Legal=303.60mm）、ref-table 识别与列宽、三线表覆盖顺序、目录规则与填充脚本、超高长图切片（切片落盘/条数/原引用替换/小图不切/幂等复用）、`_test_smd.py` 回归 28/28 PASS；Paged.js 浏览器实测（目录形态/外侧页码/长图续排/末页正文接排）。

---

## v1.2.0

**本次改动：自包含文档格式 `.smd`（正文+图片单文件 ZIP 容器）、增量保存两阶段提交、阈值自动整理、右键/双击关联与原生打开框支持、跨容器资产双向换算与收编三规则、内嵌桥薄化统一写盘入口**

**新增**

- **`.smd` 自包含文档格式**：现象——`.md + <文档名>.assets/` 成对目录在网盘同步、邮件发送、移动归档时易散。修法——`_smd.py` 实现 ZIP 容器（`doc.md` + `assets/` + `meta.json`），服务端三条路由（`GET /api/file` 读、`POST /api/file` 写、`POST /api/paste-image` 贴图）按后缀分支：读取时解包到 `runtime/tmp/<hash>/` 幂等工作目录并返回图片基址，前端 `fixLocalImages` 以该基址走现有 `/img` 代理；写入时正文落工作目录 `doc.md` 后增量回包。普通 `.md` 全链路行为不变。验证：`_test_smd.py` 17/17 通过（详见测试节）。
- **增量保存（两阶段提交）**：现象——大量图片时保存若整包重写需重压全部资源（8MB 图包为秒级~十秒级）。修法——顺序字节拷贝当前包到临时副本（旧 entry 不重新压缩，成本为顺序 IO），副本上仅追加变化的 entry（重名以后写为准，`warnings` 压掉 Duplicate name 设计依赖告警），fsync 后 `os.replace` 原子替换。实测：改字保存追加 2 entry、包大小 385→650 字节（对照全量重建为 MB 级 IO）；任意时刻断电原包完好，不存在半写状态。
- **阈值自动整理**：死空间以解包目录现状为准计算——包内 entry 不在当前 `assets/`（业务上已替换/删除）或同名不同大小均计死空间，占比 >30% 且文件 >5MB 时全量重建原子替换。实测：8MB 图被替换后首次保存即触发（dead≈96%），整理后旧图 entry 清除、包体积 8391499→8391602 字节（新图等大），后续保存恢复纯增量。
- **另存为格式选择器**：现象——`.smd` 与 `.md` 的选择依赖手输文件名后缀，易误存。修法——保存对话框新增格式下拉（`Markdown 文档（.md）` / `自包含文档（.smd）`），文件名输入框不再携带后缀，提交时统一剥离用户误填后缀并拼接所选格式；打开对话框时按当前文档格式预选。验证：`node --check` 通过；服务端按后缀识别逻辑不变，前端规范化后两种格式落点正确。
- **内嵌另存为弹框类型限定**：现象——内嵌窗口模式「另存为」的原生保存对话框（pywebview SAVE_DIALOG）未传 `file_types`，文件类型显示“所有文件 (*.*)”。修法——`md_app.pyw` 的 `pick_save_path` 传入 `file_types=(“Markdown (*.md;*.smd)”,)`（pywebview 6.x 每个元素须为完整“描述 (通配)”格式；多元素交替对写法触发`ValueError: not a valid file filter`，异常被外层捕获后静默返回，表现为按钮点开无反应）；另加两层可用性兜底——过滤参数任何异常先记 `runtime/md_app.log` 再回退无过滤调用，保证按钮永远可弹。验证：两版 `py_compile` 通过；以本机嵌入式 Python 实测 `parse_file_type`——新格式解析为(`Markdown`, `*.md;*.smd`) 通过、旧错误格式复现与日志一致的 ValueError，根因闭环。
- **「打开」按钮过滤修复（内嵌与浏览器模式同时生效）**：现象——「打开」弹框无 `.smd` 类型（仅 .md/.txt/所有文件）。根因——两版 `md_server.py` 的 `/api/open-file` 路由调用 `_pick_file_subprocess`，但该函数定义缺失（历史清理误删），每次点击即 `NameError`→500→前端兜底 WebView2 内置文件框（无类型过滤）。修法——补回 `_pick_file_subprocess(initdir)`：子进程执行 `_pickfile.py`（GetOpenFileNameW，过滤器第一组即 `Markdown (*.md;*.smd)`），`hwndOwner=GetForegroundWindow()` 置前，路径经临时文件回传；`MD_SERVER_VERSION` 44→45 / 52→53 触发版本自愈换代。验证：两版 `py_compile` 通过；嵌入式 Python 实测 `import md_server` 后函数存在、签名为 `(initdir='')`。
- **安全与关联**：解包前逐条校验 ZIP entry 名，拒绝绝对路径/盘符/`..` 穿越（实测构造恶意包被拒）；`install.cmd` 注册 `.smd` 关联（`MDViewer.smd` ProgID + shim 转发，纯 ASCII 断言 PASS）；原生打开框过滤器加 `*.smd`；浏览器兜底入口（拿不到完整路径）对 `.smd` 明确提示拒绝而非读成乱码。
- **跨容器资产双向换算**：现象——普通 `.md` 另存 `.smd`、`.smd` 改名另存 `.md` 时，磁盘契约 `<文档名>.assets/` 与包内契约 `assets/` 互不对认，图片必然断链。修法——服务端新增 `_rewrite_assets_ref` 助手（左边界断言防误伤）：打包时把 `<文档名>.assets/` 引用统一改写为 `assets/` 后进包；导出时反向改写并把图片落盘到目标目录；资产源三级解析（`base/assets` → 源文档同目录 `<文档名>.assets` → 手写图收编）。验证：单测 T10/T11 + 真实服务 E2E（另存→改名导出→图片数量一致）。
- **手写图保存时收编进容器**：现象——用户手写绝对路径引用（如 `C:/user/x.png`），`.smd` 打包时原样进包，包不自包含，换机碎图。修法——`md_assets.materialize_into` 核心抽取（落盘目录与引用前缀参数化），`.smd` 打包与增量保存前统一物化：真实存在的本地图收编进容器、引用改写为容器契约；不存在的原样保留破图可见（fail-closed）；网络图维持外链不收编。验证：T12 + E2E F2/F3。
- **保存回传正文同步编辑区**：现象——服务端收编/契约改写后编辑区仍显示旧引用，所见非所存。修法——`/api/file` 与 `/api/save-as` 响应回传新正文，前端 `applySavedContent` 三处共享（Ctrl+S／自动保存／另存为）。验证：E2E F1/U1/U4。

**修复**

- **另存 `.smd` 资产断链**：现象——普通 `.md` 另存 `.smd` 后包内零图片（用户实测复现）。根因——前端 `base=null`（普通文档会话无解包目录），后端资产源断链。修法——payload 携带 `src`（源文档路径），后端按三级解析回退到源文档同目录资产。验证：E2E E1/E2。
- **`.md` 重复收编膨胀**：现象——每按一次保存 `.assets` 多一张 `_1`/`_2` 重复图。根因——编辑区不同步导致每次保存重跑物化，同名冲突走 `_unique` 加号。修法——响应回传正文同步编辑区 + 物化内容寻址复用（sha1 同字节文件直接复用文件名，编辑区未同步的重复保存幂等零膨胀）。验证：T13 + E2E F1a/F1b。
- **包内正文换行符漂移**：现象——包内 `doc.md` 与响应正文字节不一致。根因——文本模式写盘 LF→CRLF，`save_from_dir` 按原始字节进包，且 `needs_compact` 尺寸比对误判死空间。修法——`doc.md` 写盘统一 `newline=""`。验证：E2E F3b。
- **内嵌窗口桥平行实现收编（桥薄化）**：现象——`md_app.pyw` 桥自写磁盘旧逻辑（`save_as`/`paste_image` 等六方法）：`.smd` 另存被强加 `.md` 后缀、粘贴图写到 `.smd` 旁挂错误目录、新契约全部漏网。根因——桥为历史平行实现，保存规则双处维护必然分叉。修法——桥瘦身为 `pick_save_path`（只弹原生对话框选路径），六条保存入口（Ctrl+S／自动保存／另存为×2／粘贴图×2）统一走服务端三条路由；死方法删除。验证：桥方法表断言 + E2E U1-U4。

**测试**

- **`_test_smd.py` 17→28 条全 PASS**：打包-解包正文/图片字节一致、增量追加与重名覆盖语义、保存后工作目录复用、断电残片不影响原包（sha256 不变）、路径穿越防御、外部修改触发重解包、阈值整理触发/体积回落/旧资源清除、无图文档打包、双向契约换算、手写图收编与 fail-closed、重复保存幂等零膨胀；真实服务 E2E 全绿（收编/换算/粘贴图落位/字节一致）。

**说明**

- 网络图片（http/https）不进包保持 URL 原样，与普通文档物化规则一致；`.smd` 保存时物化照常执行，但贴图已在工作目录、网络图维持外链，仅手写的外部本地图被收编进包。
- 数据互通：`.smd` 改后缀 `.zip` 即可解出 `doc.md`+`assets/`，无私有二进制格式；反向按结构打包亦可打开。
- 服务端 `MD_SERVER_VERSION` 36→39，已开启的旧实例经现有版本自愈机制换代后生效。
- ZIP 格式（PKWARE 公开规范，无专利）与 Python 标准库 `zipfile`（PSF）合规声明已写入 README 与版权文档。

---

## v1.1.0

**本次改动：图片链路三类渲染修复（空格路径／下划线改写／协商缓存）、按文件路径草稿保护、启动载入策略收敛、引用与列表缩进隔离、排版 H3 与 H4~H6 拆分、保存假失败根除、死代码清理、AGPL-3.0 授权落定、分发包补齐**

**新增**

- **按文件路径隔离的草稿保护**：现象——未落盘的编辑在刷新或重开后退回磁盘版本，且旧逻辑在载入后无条件把磁盘内容回写草稿存储，未保存修改不可恢复。修法——新增按路径隔离的草稿表（`md-editor-drafts-v1`），四个载入入口（URL 打开／「打开」按钮／最近文档／内置文档）统一走草稿感知载入：草稿与磁盘内容不一致时恢复草稿，并以非阻塞 toast 提供「用磁盘版本」动作按钮；手动保存、自动落盘、另存为成功后清除对应草稿。验证：真实浏览器 E2E 十二项（草稿恢复、放弃草稿、落盘清草稿、外部修改后刷新取新内容、全程原生弹窗监听为零）全部通过。
- **排版面板 H3 与 H4~H6 拆分**：现象——「H3~H6」单行一键覆盖四级标题（`TS_MAP` 的 `h3` 键映射 h3～h6），三级标题无法独立于四至六级设置字体字号对齐。修法——`TS_KEYS` 增加 `h4`，`TS_MAP` 的 `h3` 收窄为仅 h3，新增 `h4` 键覆盖 h4～h6，面板拆为「H3 标题」「H4~H6 标题」两行。验证：面板出现 `data-ts="h4"` 控件，规则按新键生成。
- **分发包补齐运行文件**：现象——分发包缺 `md_assets.py`、`md_app.pyw`、`docs/` 内置文档（《使用指南》《版权与开源组件声明》为 `/doc` 接口运行依赖），包内保存链路报错（见修复）、内嵌窗口模式失效、默认文档加载失败。修法——三者在 v1.1.0 分发包补齐（入库文件 221 → 226）；宣传类文件（介绍文章、宣传图、宣传视频）仍不入包。验证：release zip 实下载解包，逐项核对十三项全部通过。

---

**修复**

- **文件名含下划线的图片被改写为斜体标记**：现象——粘贴图片（文件名恒为 `20261015_181923_3419.png` 三段下划线）及一切含下划线的图片、链接路径，预览不生成 `<img>`／`<a>`，或 `src` 被改写为 `20261015<em>181923</em>3419.png` 后请求 404。根因——`parseInline` 先将图片／链接替换为 HTML 标签、后执行强调替换 `_([^_]+)_`，属性值内的下划线被当作强调语法。修法——图片／链接生成的开标签先进占位符（`\x00T` 词元），行内格式化仅作用于占位符之外的纯文本，末尾统一还原；链接只占位开标签，链接文字仍参与加粗与强调。验证：真实浏览器实测两张下划线图片 `src` 干净、链接 `href` 干净、链接内文字的强调照常渲染。
- **文件名含空格的图片语法整段不渲染**：现象——`![说明](MDEditor 使用指南.assets/内嵌示例图.png)` 之类带空格路径，预览裸露原始标记。根因——内联图片／链接正则的 URL 段为 `[^) ]+`，不允许空格。修法——URL 段改为 `([^)]+?)` 非贪婪匹配（兼容可选标题语法），图片与链接两条正则同步。验证：默认文档（使用指南）图片 `naturalWidth > 0` 实测加载成功。
- **保存报 500 `cannot access local variable 'added'`，实为假失败**：现象——分发包内保存报 500，但内容实际已写盘；界面报错、草稿不清除、自动落盘静默失效。根因——`md_assets.py` 缺失时懒导入将 `materialize_images` 置 `None`，`/api/file` 与 `/api/save-as` 的 `if materialize_images:` 为假跳过赋值，响应构造引用未绑定的 `added` 抛 `UnboundLocalError`；`write` 在该异常之前执行，数据无损失。修法——两处调用点前补 `added = []` 兜底（`MD_SERVER_VERSION` 35 → 36）。验证：py_compile 通过，包内复测无 500。
- **引用块跟随正文缩进**：现象——正文设置首行缩进后，引用块内段落一并缩进。根因——缩进规则选择器 `#preview p` 命中 blockquote 内的 `<p>`（松散列表 `li>p` 同理），而引用、列表设为「无」时不生成任何规则，正文规则随之泄漏。修法——引用、列表为「无」时生成中性化规则（`text-indent:0 !important`、`padding-left:0 !important`），引用与列表的缩进设置和正文彻底隔离。验证：生成的样式表含两条中性化规则，引用段不受正文缩进影响实测。
- **图片刷新后陈旧，须强制刷新才更新**：现象——磁盘图片已替换，普通刷新（F5）仍显示旧图，仅 Ctrl+F5 可见新图。根因——`/img` 响应 `Cache-Control: max-age=3600` 且 URL 稳定，浏览器将图片缓存一小时；文字内容走 `/api/file`（no-store）故仅图片陈旧。修法——改为协商缓存：响应携带 `ETag`（mtime-size）与 `Cache-Control: no-cache`，`If-None-Match` 命中返回 304 不重传，文件变更即 200 返回新图（服务端 v35）。验证：真实浏览器 F5 后六张配图全部带 `If-None-Match` 回源，未变更时 304。

---

**变更**

- **启动一律载入默认文档，旧全局缓存退役**：现象——启动显示陈旧的指南快照，图片位置与当前版本不符且全部 404。根因——初始化保留「全局缓存键 `md-editor-content-v1` 优先」的历史路径，陈旧快照遮蔽默认文档；该状态下无文件上下文，相对路径图片丢失基址（`/img` 按工具根目录兜底解析必然 404）。修法——启动一律走默认文档的草稿感知载入，旧键一次性清除；`scheduleSave` 的无文件分支同步退役，草稿存储收敛为按文件路径的单一来源。验证：种入旧值启动后显示真指南、旧键清除、图片加载成功；无旧值常规启动回归通过。
- **死代码清理**：`md_server.py` 的 `do_POST` 内 `/api/save-as`、`/api/paste-image` 路由各重复三次，后两次不可达，删除 112 行；`markdown-editor.html` 中 `katexCssText` 的重复 fetch 两处删除；`md_launch.pyw` 的 `if False else` 残留与孤立 `import io` 移除。验证：py_compile 通过，`grep` 路由计数归一。
- **授权落定为 GNU AGPL-3.0-or-later**：新增 `LICENSE`（GNU 官方全文）与全部源码 SPDX 头（Copyright 2026 wUwproject），《版权与开源组件声明》与 README 许可节同步改写；与随附第三方组件（KaTeX、Paged.js MIT，Python PSF）兼容，`LICENSES/` 目录保留。分发仓库同步设为公开。

## v1.0.6

**本次改动：生命周期自动化（关页面即停服务、闲置永不误停）；删除 WebView2 内核与全部内嵌遗留，项目 1.2GB → 58MB**

**新增**

- **页面关闭驱动的服务退出**：现象——浏览器关闭后服务常驻，须手动双击 `md_stop.cmd`。修法——前端在 `pagehide` 事件经 `navigator.sendBeacon('/api/bye')` 上报；服务端登记 `_BYE_AT`，由守护线程在 8 秒宽限期后确认（`MD_EXIT_GRACE` 可覆盖），期间任何新心跳（页面刷新即发）清零撤销。`runtime/settings.json` 的 `auto_stop:false` 可整体关闭。验证：闲置 12 秒服务存活、发送关闭通知后停止、关闭后 1.5 秒恢复心跳撤销成功三场景全绿，`runtime/lifecycle.log` 记录 `page closed -> stop service`。
- **撤销机制防刷新误杀**：刷新页面会先触发 `pagehide` 再加载新页面心跳，宽限期内恢复心跳即撤销退出，刷新不误停。

**变更**

- **废弃"空闲超时"判据**：此前一版按"连续 120 秒无心跳即退出"实现，切标签页、最小化、长时间编辑中途离开均属"闲置但未关闭"，会被误停。改为仅以页面卸载通知为判据，闲置永不退出；该设计缺陷在实机验证中确认后纠正。
- **删除 WebView2 内核与内嵌遗留**：删除 `runtime/WebView2/`（734.6MB）、`runtime/WebView2.zip`（346.8MB）、`runtime/userdata/` 及两份备份（共 68.1MB），释放 1149.5MB；随删 `runtime/unpack_runtime.py`、`md_clear_cache.cmd`、老式目录框脚本 `_pickdir.py`（删除前确认服务端 0 引用）。`docs/版权与开源组件声明.md` 同步删去 WebView2 Runtime / pywebview / pythonnet 三行及对应许可要点；`install.cmd` 去掉首次安装解压内核步骤，复核仍为纯 ASCII。
- **有意保留项**：`md_app.pyw`、`md_launch.pyw` 的内嵌判定分支与 pywebview/pythonnet 包保留——内核不存在时 `embedded_available()` 自然返回 False 自动走浏览器模式，留退路且不占空间。验证：清理后服务页面 200、内置文档 2 篇、常用目录 4 项、ping 正常。

---

## v1.0.5

**本次改动："打开"改后端原生文件框、"浏览"改 IFileOpenDialog 现代目录框，去掉老式回退与死代码，常用目录读注册表解析 OneDrive 重定向**

**新增**

- **`GET /api/open-file` 原生打开文件框**：现象——浏览器模式"打开"按钮走 `<input type="file">`，安全沙箱只给文件名不给路径，`change` 回调里 `addRecent(null, f.name)` 路径恒空，"保存"不可写回、`.assets` 无基址。修法——新增 `_pickfile.py`（纯 ctypes 调 `comdlg32.GetOpenFileNameW`，`hwndOwner=GetForegroundWindow()` 跟随浏览器窗口置前），服务端子进程+临时文件回传返回 `{ok,path}`；前端 `openFileNative()` 优先走该接口取完整路径后经 `/api/file` 载入并设 `currentFile`，接口失败自动退回 `<input type=file>`。验证：打开后保存立即可用、图片物化正常落入 `.assets`。
- **`_pickdir_modern.py` 现代目录选择框**：原"浏览…"为 XP 风格 `SHBrowseForFolder` 树状框。改为纯 ctypes 手写 COM vtable 调 `CLSID_FileOpenDialog`/`IID_IFileOpenDialog`，`FOS_PICKFOLDERS|FOS_FORCEFILESYSTEM|FOS_PATHMUSTEXIST`，`Show(GetForegroundWindow())` 置前。验证：`CoCreateInstance`/`GetOptions`/`SetOptions` 全部 `hr=0`（current=0x1808）。

**修复**

- **取消后弹第二个老式框**：现象——现代框点"取消"后又弹出老式树状框。根因——"三态返回+不可用回退"设计中，取消信号未成功写回即触发回退。修法——去掉回退逻辑，`_pick_dir_subprocess()` 只调现代框，取消与不可用均返回空串并写 `runtime/pickdir.log` 诊断。
- **`/api/browse-dir` 四份重复定义**：仅 1 份可用（走 modern），另 3 份分别调用已不存在的 `_pick_dir_win()` 与嵌入式 Python 根本没有的 tkinter，全部删除。
- **常用目录指向 C 盘空壳**：现象——"另存为"快捷按钮的桌面/文档指向无效路径。根因——`expanduser("~")` 拼接，真实桌面在 OneDrive 重定向路径。修法——`/api/common-dirs` 改读注册表 `HKCU\...\User Shell Folders`（Desktop/Personal/Downloads GUID）并展开环境变量。实测：`desktop=D:\...\OneDrive\Desktop`、`docs=D:\...\OneDrive\文档`、`downloads=D:\Users\...\Downloads`。

---

## v1.0.4

**本次改动：引入内嵌窗口模式（pywebview+WebView2）并经卡死排查后按决策放弃，还原浏览器模式、移除系统托盘；页面 23 处原生 alert 全部替换为 toast；新增启动旧窗口清理与卡死看门狗**

**新增**

- **`md_app.pyw` 内嵌窗口入口**：pywebview 6.2.1 + pythonnet 开原生窗口指向本地服务，自带 WebView2 内核优先（`WEBVIEW2_BROWSER_EXECUTABLE_FOLDER`）、系统 Runtime 兜底；暴露 py API（pick_folder/save_file/paste_image 等），窗口尺寸记忆 `runtime/window.json`。前端双模式：`pywebviewready` 置 `HAS_PY`，浏览目录/另存/贴图"有桥走 py 直连、无桥走 HTTP"。`install.cmd` 首次安装自动解压内核（实测 347MB→737MB 仅 3.9 秒）。端到端实测：内嵌窗口出现、自带内核加载、页面回调桥 OK。许可核验：pywebview BSD-3、WebView2 Runtime 微软免费可分发（原样+声明两条件）、Chrome EULA 禁再分发故不采用。
- **卡死自动取证看门狗**：`md_app.pyw` 加 `_install_hang_watchdog()`——后台线程每 2 秒心跳，实际延迟 >1.5s 即把 `sys._current_frames()` 全线程调用栈写入 `runtime/hang.log`（仅异常时写）。实测心跳日志正常、未卡时为空。项目首次具备"用户现场卡死事后定位到代码行"的能力。
- **`kill_stale_apps()` 启动清理**：现象——启动器每次新开窗口却从不关旧 `md_app` 窗口，桌面叠多个旧版本窗口。修法——按命令行含 `md_app.pyw` 精确匹配后 taskkill（不误伤其它 pythonw 脚本），main 入口最先调用；`kill_stale_services()` 收紧为只杀命令行含 `md_server.py` 的进程；新增 `kill_port_holder()` 按端口兜底。效果：每次打开必然是最新代码。
- **`GET /api/open-external` 外部浏览器打开**：分页/打印原用 `window.open`/`window.print()`，在 WebView2 嵌入窗口内会阻塞界面。统一改为服务端 `threading.Thread(webbrowser.open)` 交系统默认浏览器（白名单仅 `/` 相对路径与 `http://127.0.0.1:PORT/`），打印语义=生成分页 HTML 后浏览器 Ctrl+P。
- **`GET /api/log` 与 `uiBeacon()` 探针**：分页/打印/导出按钮点击上报 `runtime/ui.log`；分页流程埋分步打点 + `AbortController` 45 秒超时 + 防重入。

**修复**

- **页面卡死真根因为原生 `alert()` 同步阻塞**：现象——分页按钮点击后窗口"未响应"，服务端导出正常完成（540KB、mtime 与点击时刻吻合），`SendMessageTimeoutW(WM_NULL)` 探测窗口确认为真未响应。根因——页面 23 处原生 `alert()` 同步阻塞 JS 主线程，且此前测试用例 `j.ok` 恒为 true、从不触发失败分支。修法——全部替换为自绘 `showToast()`（右上角浮层、失败类标红、3~6 秒自动消失），`alert(` 存量归零。
- **"改了没生效"的系统化对策**：多轮修改未达用户侧，后以"清空 `ui.log` 后观察新埋点"实证用户窗口运行的是旧版页面。配套：`Cache-Control: no-store`（页面本身无缓存，根因是旧窗口未关）+ `kill_stale_apps()` + `userdata/` 重命名移除并干净重建（实测 53.8MB 运行数据）。
- **"滚动卡死"与 GPU 精简内核排除**：补回误删的 `dxcompiler.dll`（20.5MB）与 `onnxruntime.dll`（11.1MB）；内核完整性核查仅缺 3 个 `.sig` 与 Installer 目录；`settings.json` 新增 `disable_gpu` 软件渲染逃生开关。自动化压测（复用 md_app Api 注入 js_api 桥 + 逐按钮 click + 注入 onerror 捕获）：全部按钮 click 1~8ms、JS 错误为空。

**变更**

- **放弃内嵌窗口，还原浏览器模式**：卡点定位在 pywebview WinForms 宿主层——Python 心跳无阻塞记录、页面探针未收到任何输入事件、Windows 事件日志无崩溃、内核完整、软件渲染无效、合成输入（含真实滚轮/按键消息）无法复现。按决策 `settings.json` 设 `embed_window: false`，内嵌代码全部保留仅由开关控制。实测：进程只剩 `md_server` 一个，浏览器自动打开，服务 v27。
- **移除系统托盘**：托盘（`md_server.py` 内纯 ctypes `Shell_NotifyIconW`，窗口类 `MDViewerTrayWnd`）的最小化/新建/退出菜单动作实测不可靠，移除 `build_tray()` 调用改纯常驻；托盘类保留不删。验证：重启后 `FindWindowW('MDViewerTrayWnd')` 返回 0，退出方式为 `md_stop.cmd`（按命令行匹配 `md_server.py`，纯 ASCII）。

---

## v1.0.3

**本次改动：图片物化随文档落盘（base64/blob 引用/本机路径统一进 `<文档名>.assets/`）、内置文档实体化、保存按钮门禁、保存默认名取一级标题、`.assets` 改为有图才建**

**新增**

- **`md_assets.py` 图片物化**：`materialize_images(doc_path, content)` 把 Markdown 内 base64 data URI、WorkBuddy blob 引用、本机绝对路径/file:/// 三类图片统一写入 `<文档名>.assets/`（文件名取 alt 文本、非法字符清洗、重名加序号），引用改写为相对路径；http(s)/锚点/已是相对路径保持不动，任何异常原样返回不破坏文档。挂载于 `/api/save-as`、`/api/file` 写盘前与 `md_app` 保存桥。实测：`assets: ['图A.png','图B.png']`、引用改写 `![图A](终测.assets/图A.png)`。
- **内置文档实体化**：内置指南与版权声明由 JS 内存常量改为工具目录实体文件 `docs/*.md`（版权文档用 `materialize_images` 生成，同步验证物化链），新增 `GET /docs-list` 与 `GET /doc?file=`；打开内置文档即设 `currentFile` 为其实体路径，点保存直接落盘。实测：`/doc` 返回真实路径、保存回写原路径、预览取图 200。
- **`GET /api/paste-image` 剪贴板贴图**：剪贴板图存入 `<文档名>.assets/<时间戳>.png` 并返回与存放位置一致的相对路径引用（v1.0.1 首版实现，本版统一引用风格去掉多余 `./` 前缀）。

**修复**

- **`save-as` 路由 500 `name '_LAST_DOC_DIR' is not defined`**：根因——批量补丁脚本中一个替换断言失败导致整个脚本未落盘，前序改动亦未生效，后续补丁引用了从未定义的变量。对策确立：脚本式改动分步提交、每步独立写盘并核验。
- **嵌入式 Python 导入同目录模块失败**：embedded 发行版 `sys.path` 不含脚本目录，`from md_assets import ...` 抛 `ModuleNotFoundError` 被 `try/except` 静默吞掉，表现为"代码改了没生效"。修法——import 本地模块前显式 `sys.path.insert(0, HERE)`，并在 `md_server` 加 `runtime/md_assets.err` 错误落盘，杜绝静默失败。

**变更**

- **保存按钮门禁**：无路径时「保存」禁用（`sb.disabled=!currentFile` + opacity .45 + 状态栏"未另存为"），弹窗只属于「另存为」；物化只在落盘时发生，未保存文档贴图被拦并提示先保存。
- **保存默认文件名取文档第一个一级标题**：`docTitleForSave()` 正则取 `# xxx`、剔除非法字符、限 60 字、无标题退回"未命名.md"。
- **`.assets` 改为按需创建**：删除 `/api/file`、`/api/save-as` 及 `md_app` 共 6 处无条件建目录调用与 `_ensure_assets_dir`，目录仅由物化逻辑与贴图接口在真有图片时创建。实测四场景：无图保存仅 `['无图.md']`、有图保存成对出现、已存文档贴图补建目录、无图内置文档无 `.assets`。

---

## v1.0.2

**本次改动：目录/文件对话框全链路 ctypes 化（嵌入式 Python 无 tkinter 的根治）、Win32 启动画面、"每次打开都重启服务"的版本单一来源根治（热启动 2s+ → 0.15s）、托盘图标与双开修复**

**新增**

- **纯 ctypes 目录/文件对话框**：现象——"浏览"目录弹窗在服务线程与子进程两版 tkinter 实现下均弹不出。根因——便携嵌入式 Python 根本不含 tkinter（`import tkinter` 即 `No module named`），与线程无关。修法——`_pickdir.py` 纯 ctypes 调 `shell32.SHBrowseForFolderW`（`restype=c_void_p` 防 64 位指针截断、子进程 `CoInitializeEx(STA)`、路径经临时文件回传）。另修保存弹窗按钮样式（独立 `.sv-btn`，原蹭工具栏样式字大框小）。
- **Win32 启动画面 `_splash.py`**：纯 ctypes/GDI 绘制（图标 `LoadImageW`+`DrawIconEx`、圆角 `SetWindowRgn`、淡入淡出 `SetLayeredWindowAttributes`），splash 自起线程轮询 `/api/version`，版本就绪后 0.45 秒触发淡出，启动器 `WM_CLOSE` 兜底。关键实现约束：全部句柄/指针参数显式 `argtypes`，否则 64 位句柄按 int 截断（定时器失效、文字画不出）。
- **托盘图标加载与窗口管理**：托盘图标改 `LoadImageW` 从 `md-editor.ico` 加载 16×16（失败降级默认）；左键单击 toggle 编辑器窗口（`EnumWindows` 匹配标题，最小化恢复/前台最小化/后台前置），右键菜单（新建/退出），退出先对所有编辑器窗口 `PostMessageW(WM_CLOSE)` 再删图标停服务。

**修复**

- **每次打开都杀服务重启（重大）**：现象——热启动也要 2 秒+，且页面常是旧版。根因——`md_launch.pyw` 的 `VERSION` 常量自初始值 2 起从未同步，而 `md_server` 已演进至 11，`server_version()==VERSION` 永假触发自愈重启。修法——`md_launch` 直接 `from md_server import MD_SERVER_VERSION as VERSION`，版本单一来源。实测：冷启动 2.11 秒（含启动画面全程）、热启动 0.15 秒。
- **启动一次开两个编辑器**：根因——`/open` 路由"先开浏览器再回响应"，浏览器冷启动超过启动器 5 秒超时，兜底逻辑又开一次。修法——`/open` 先回响应再 `threading.Timer(0.25)` 异步开浏览器（实测响应 0.010s），兜底收紧为仅 `URLError`，超时 5→8 秒。实测：冷启动 1.83 秒、热启动 0.17 秒。

**变更**

- **启动器轮询参数**：按使用反馈恢复 0.25 秒轮询与 0.6 秒等待（此前为提速改 0.1s，感知差异由浏览器冷启动主导，服务冷启动实测仅 0.51 秒）。

---

## v1.0.1

**本次改动：文档工程三件套（新建/另存为/粘贴图片），保存弹框从嵌套容器迁移至 body 级并修复禁用出口，目录浏览从 tkinter 迁至子进程方案**

**新增**

- **「新建」与另存为链路**：工具栏「新建」+Ctrl+N（内存文档）；保存模态框（文件名+目录+浏览）；`POST /api/save-as` 落盘；自动保存分流（有路径直写原文件，内存文档到点弹一次保存框）。`MD_SERVER_VERSION` 2→3。
- **`POST /api/paste-image`**：剪贴板图片落盘 `<文档名>.assets/` 并返回相对路径引用（实测 2993B 落盘）。
- **独立「另存为」按钮**：总是弹框、回填当前文件名与上次目录。
- **`GET /api/browse-dir` 目录浏览**：首版经 tkinter `askdirectory`（服务线程内，后于 v1.0.2 根治为 ctypes 方案）。

**修复**

- **保存弹框常显且 hidden 失效**：根因——`#svOverlay` 的 inline `display:flex` 特异性压过 `[hidden]` 属性的 UA 样式。修法——`#svOverlay[hidden]{display:none !important;}`。
- **点保存无反应、点排版时保存框跟着冒出**：根因——svOverlay 整块被插进排版面板内部，成为 tsOverlay 子元素，祖先隐藏时整个子树不渲染。修法——迁移至 body 级与 ts/fm 面板平级。验证：点保存 `getBoundingClientRect` 1280×720 真实遮罩、排版面板 hidden 状态不再联动、填名保存文件落盘。
- **保存按钮被两个加载出口禁用**：内置文档与冷启动默认文档两处均 `disabled=true`，内存文档无法另存为。修法——两处改启用，"另存为"语义与「保存」解耦。
- **路由锚点错插 `do_POST`**：GET 路由被插进 POST 分支致 404（`/api/browse-dir`），移回 `do_GET`。铁律沉淀：`md_server` 加 GET 路由锚 `/api/version` 后，POST 路由锚 `/api/export-html`，混用必 404。

---

## v1.0.0

**本次改动：首个正式版——目录清理、独立桌面快捷方式、双平台建仓（Gitee/GitHub）与 git-sync 注册**

**变更**

- **目录清理**：删除调试产物（`.playwright-cli/`、`_patch17*`、`_s0.js`、`.mdinstall.bak`、两个误建空目录、`icon-preview.png`）；`document.paged.html` 保留作导出样例。
- **`desktop-shortcut.cmd`**：独立桌面快捷方式脚本（目标 `MarkdownEditor.exe` + 图标），不装右键关联也能像传统应用双击使用；`_mklnk.ps1` 同步重写（快捷方式目标从 pythonw+pyw 改为 exe+图标）。
- **双平台建仓与发布注册**：Gitee `wUwproject/maby_tool` + GitHub `Ldxs001/maby_tool` 双 remote（gitee https / origin ssh 443）；仓库根 `MarkdownEditor/` 子目录 217 文件与源一致，`git status` 干净；git-sync `config.json` + `manifest` 注册（source_path/repo_path/version 1.0.0），双端 push 通过。exe 重编译单独 commit。

---

## v0.10.0

**本次改动：服务版本自愈与打开方式治理（file:// 自检指引）、最近文件管理、图片体系（/img 代理+相对路径+静态兜底）、分页页数稳定判定**

**新增**

- **后端版本自愈**：现象——旧 pythonw 后端常驻导致公式占位符裸露、图片碎图标（`md_launch` 见端口占用即复用旧服务）。修法——`md_server` 加 `MD_SERVER_VERSION` 与 `/api/version` 路由、`/` 页面 `Cache-Control: no-store`；`md_launch` 端口占用时校验版本：匹配复用、不符则 `taskkill /FI "PID ne <self>"` 清旧+自起+轮询 `/api/version` 确认（15 秒），失败兜底开页面。实测：假旧服务（无 version 路由）→ 自愈到新版、katex/img/editor 全 200、pythonw 收敛 1 个。
- **file:// 双击直开自检**：主 IIFE 首行检测 `location.protocol==='file:'` → fetch `/api/version` 探测服务，在线自动跳转 `http://127.0.0.1:18765/`，离线渲染指引页并阻断编辑器初始化。
- **最近文件管理**：工具栏「文件」面板——内置文档区 + MRU 列表（最多 12 条，文件名+完整路径+时间，当前文件高亮），右键/关联打开自动记路径可重载切换；状态栏当前文件指示 + `document.title` 同步。
- **图片体系**：新增 `GET /img?path=` 代理（扩展名白名单 jpg/jpeg/png/webp/gif/svg/bmp），前端 `fixLocalImages()` 把本机绝对路径/file:/// 与无协议相对路径（base=当前文档目录）统一转代理；服务端加根级静态兜底（未匹配 GET 路由→白名单扩展名→工具目录下文件，防穿越）；导出时图片路径还原为 file:/// 绝对路径。实测：网络图与本地图双图 `naturalWidth` 加载成功。
- **分页页数稳定判定**：现象——页码"第 1 页/共 2 页"与实际页数不一致。根因——MutationObserver 在分页逐步进行时就填充且 dataset 防重不更新。修法——连续 4 次 250ms 页数稳定才 disconnect 并一次性填全。实测：多页页码逐页一致。

**修复**

- **tsFill 三重 bug**：①`fillSel(s,vals,labels)` 参数传反致字体下拉显示 CSS 串而非友好名；②对齐选项误填进字体下拉而 `data-algn` 下拉从未填充；③无重复填充防护。重写后实测：字体首项"(默认)"、对齐 5 项、无泄漏。
- **双「应用」按钮**：PAGE_HTML 自带 `ts-foot` 与插入的 `ts-foot` 叠加，去重。
- **base64 示例图替换网络商标图**：网络示例图改 PIL 生成 240×150 base64 内嵌图（1732 字符 data URI，离线零图源依赖）；同时修 `fixLocalImages` 把 `data:` URI 误当相对路径转代理致 404。

---

## v0.9.0

**本次改动：长文分块增量渲染（6 万字全量渲染 25.5 秒冻结主线程 → 编辑单字只重渲所在块 4.5 秒）、公式排版行、/api/fonts 注册表字体枚举（775 个）、公式块级对齐真因修复、文档合规收尾**

**新增**

- **分块增量渲染**：`splitBlocks`（fence 感知 H1/H2 切块）+ 块 hash（djb2）比对 + `.pblk` 容器逐块异步渲染（setTimeout 分片）+ 防抖自适应（>3 万字 600ms）。实测：6 万字（80 公式/40 表格）首渲 15.2 秒分片不冻结、编辑单字只重渲所在块 4.5 秒（5.7 倍）；十万字可正确渲染、输入流畅。
- **排版面板「公式」行**：字号→`.katex{font-size}`（实测 20pt→26.67px 生效）、对齐→`.katex-display`（仅块级，行内公式跟随所在段落）；KaTeX 字体固定不给字体选项。
- **`GET /api/fonts`**：py 侧 winreg 枚举注册表字体（HKLM+HKCU，去 `(TrueType)` 后缀、`&` 拆分家族）775 个，面板打开自动填充「本机字体」组，取代需授权弹窗的 `queryLocalFonts`（该按钮后续删除）。

**修复**

- **公式对齐不生效**：根因——`katex.min.css` 自带 `.katex-display>.katex{display:block;text-align:center}`，内层强制居中盖掉外层容器设置。修法——math 对齐规则补内层选择器 `#preview .katex-display>.katex`。实测：outer/inner computed 均 right、公式右缘与容器右缘重合。
- **面板左侧边距不齐**：页面/页码/目录三区（v0.6.0 加入）被锚在 `.ts-body` 容器外的 `ts-foot` 前，未吃到内边距（左右缘 375px vs 391px）。修法——三区移回 `.ts-body` 闭合前，复测 6 个分隔线全部对齐。

**变更**

- **合规盘点**：KaTeX(MIT)/Paged.js(MIT)/Python(PSF)/KaTeX 字体(SIL OFL 1.1) 均允许随软件捆绑分发，条件为保留许可文本，`LICENSES/` 四文件齐备；示例图 base64 内嵌无第三方素材；默认字体为系统字体非分发物。
- **`README.md`**：中文全量说明（首次安装、正确打开方式、文件清单三分类、功能速览、卸载、许可）。

---

## v0.8.0

**本次改动：分页与 HTML 导出组装从 JS 全部移至 Python（`/api/export-paged`、`/api/export-html`），前端只 POST，根除 JS 字符串拼接类错误**

**变更**

- **`build_paged_html()` 全权组装**：TOC 构建（h1-h3 加 id、插入位置 top/afterh1、独占页）、`@page` CSS（纸张/边距/页码 margin box 占位）、KaTeX CSS 内嵌（字体路径转 `/static/katex/fonts/`）、Paged.js polyfill 内嵌、页码填充脚本。前端删除 `buildPagedHtml`/`PAGED_JS`/`katexCssText` 预取（瘦身约 10KB）。实测：531KB、3 页、页码一致、14pt→18.67px 生效、TOC 2 条。
- **`build_standalone_html()`**：`.html` 导出组装移 py（图片路径还原/katex css/tsCss 全 py 侧），前端只剩 POST。实现约束：含字面 `%` 的模板禁用 `%` 格式化（CSS `100%` 触发 `unsupported format character`），改用 `__TOKEN__` replace。
- **切换载入改同步 `render()`**：`loadBuiltin`/`loadDefault`/`loadFile` 同步渲染，消除 120ms 防抖窗口的"点了没反应"体感。

**修复**

- **内置文档载入变字符串 "undefined"**：根因——`BUILTIN_DOCS` 定义在 `var SAMPLE=` 之前，var 提升致初始化时为 undefined。修法——移到 SAMPLE 赋值后。

---

## v0.7.0

**本次改动：Paged.js 分页导出全链路（纸张/页边距/页码/目录），六级连环问题实测定位修复**

**新增**

- **分页导出**：面板新增页面（A0~B3/Letter/自定义 mm+四向边距）、页码（开关/位置 5 档/模板/字号）、目录（开关/文首或第一个一级标题下/独占页）三区；「分页」按钮 → `buildPagedHtml()` → `POST /api/export`（文件名白名单 `^[A-Za-z0-9._-]+\.html$`）→ `window.open` 打开成品。
- **页码与目录实现**：margin box 占位 + 导出 HTML 内嵌 MutationObserver 分页后直填 DOM（Paged.js 0.4.3 下 margin box content 渲染损坏的降级方案）；目录条目 `target-counter` 页码引用。终态实测：3 页、页码逐页一致、TOC 4 条带页码、公式与缩进全对。

**修复**

- 分页导出六级问题逐一定位修复：①blob: URL 非层级地址致 Paged.js 目录锚抛 `Failed to construct 'URL'` → 写盘走 http；②`@bottom-center` margin box 必须嵌在 `@page{}` 内；③margin box content 渲染损坏 → 占位+JS 直填（见上）；④KaTeX MathML `<math>` 被 Paged.js 解析器剥离 → `output:'html'`；⑤占位符 NUL 字符被 innerHTML 解析丢弃 → 换 PUA 字符 U+E000/U+E001；⑥`restoreMath` 在 276KB katex.js 未下载完时竞态放弃 → 轮询等待后整体重渲染。

---

## v0.6.0

**本次改动：排版面板 v2~v4——按元素字体+字号+对齐+缩进（正文/引用/列表三行独立）、本机字体接入，tsCfg 键升 v2/v3 自动迁移**

**新增**

- **面板 v2**：每元素字体+字号(pt) 双控件；段落缩进三态（无/首行缩进/悬挂）+ 字符数（em=字号×字符数）；表头/首列独立 checkbox+取色器；存储键 `md-editor-typeset-v2`。
- **面板 v3 按元素缩进**：缩进区拆为正文/引用块/列表三行各自 mode+chars；引用缩进作用于 `blockquote p`（border-left 不动），li 悬挂时 marker 不动文字右移；v2 全局 indent 自动迁移至 p。
- **面板 v4 对齐**：每元素行加对齐下拉（默认/左/居中/右/两端），`applyTypeset` 生成 `text-align` 规则。
- **本机字体**：`window.queryLocalFonts()`（Local Font Access API，127.0.0.1 属安全上下文）按 family 去重排序进全部字体下拉，localStorage 缓存免重扫，API 不可用/拒绝时静默回退内置列表。

---

## v0.5.0

**本次改动：编辑器五项功能升级——自动落盘、KaTeX 公式本地化、排版面板（模态框）、三线表与悬挂缩进、导出 HTML 公式离线可见**

**新增**

- **自动落盘**：缓存层文案改「已存入缓存」；自动落盘设置 0~60 分钟（0=仅手动），到点且 dirty 且有当前文件时 POST 写回原文件，状态栏显示落盘时间。
- **KaTeX 0.16.21 本地部署**：dist 含 fonts/contrib 共 6MB（MIT 可随仓库分发）；服务端 `/static/` 路由（normpath 防穿越）；渲染管线内核零改动——`extractMath` 按 ``` 围栏分段提取行内/块级公式存占位符，`restoreMath` 用 TreeWalker 恢复并 `katex.render`。
- **排版面板 v1**：模态框面板，正文/H1/H2/H3~H6/引用/列表/表格/代码各一字体下拉（宋黑雅楷仿等线 Arial Georgia Times Courier），生成 `#ts-style` 动态 CSS（预览+导出共用）。
- **三线表开关与悬挂缩进开关**：三线表（去竖线三条横线）+ 表头/首列底色高亮；悬挂缩进 `p{padding-left:2em;text-indent:-2em}`。
- **导出 HTML 公式离线**：改用 preview 渲染后 DOM，内嵌 `katex.min.css` 全文 + ts-style 动态样式，字体断链时 MathML 布局退化可用。实测：面板隐显、公式渲染、本地图片代理、静态资源全 200、穿越 403。

**修复**

- **排版面板"关不掉"**：根因——`#tsOverlay{display:flex}` 特异性压过 hidden 属性的 UA `display:none`。修法——`#tsOverlay[hidden]{display:none !important;}`。

---

## v0.4.0

**本次改动：csc shim 可执行文件根治"打开方式显示 Python"，纯程序化生成多尺寸图标并接入关联三处与 exe 内嵌**

**新增**

- **`MarkdownEditor.cs` → `MarkdownEditor.exe` shim**：现象——`.md` 右键/打开方式列表显示 "Python"（Win11 选择器对无 FriendlyTypeName 的 ProgID 显示 command 里 exe 的 FileDescription；command 直连 pythonw.exe 则 FriendlyTypeName 也治不了，ASSOCSTR_FRIENDLYAPPNAME 解析链实证）。修法——install.cmd 自动用系统自带 csc（Framework64 v4.0.30319）编译 shim（AssemblyDescription="Markdown Editor"），功能为转发 .md 路径给便携 pythonw；右键 verb/双击关联/兜底 ProgID 三处 command 全部改指 shim，并注册 `Applications\MarkdownEditor.exe`。用户实测选择器显示 "Markdown Editor"。
- **程序化图标 `gen_icon.py`**：PIL 纯程序化生成 `md-editor.ico`（256~16 七尺寸）——点阵拼 "MD"、青→紫→粉色相渐变圆角色块、深色圆角底，零字体零素材。接入三处 `DefaultIcon` + csc `/win32icon` 内嵌。

---

## v0.3.0

**本次改动：安装链路治理——Win11 右键菜单、cmd 纯 ASCII 铁律、UserChoice Deny ACE 突破、孤儿 ProgID 修补、OpenWithList 清理**

**修复**

- **右键菜单"没出现"（两层）**：①Win11 新右键菜单隐藏传统 shell 项——install.cmd 默认启用旧版菜单（`HKCU\...\CLSID\{86ca1aa0-...}\InprocServer32` 空值），传 `nolegacy` 才不启用；②command 值引号嵌套被 reg 剥引号致命令损坏——改为 `%PYW% %HERE%\md_launch.pyw "%%1"`（路径无空格仅 %1 加引号）。
- **cmd 脚本编码事故（终极方案纯 ASCII）**：UTF-8 无 BOM 的 .cmd 按 GBK 逐字节读取，中文尾字节与语法字符配对成乱码致引号/括号失配、脚本崩溃——先试 GBK 转码仍乱码（与磁盘真实状态脱节），终态三个 .cmd 全部重写纯 ASCII（英文提示），字节级验证 max byte ≤ 126，任何代码页下字节相同。铁律：交付双击运行的 .cmd/.bat 一律纯 ASCII，中文提示需求改由 Python/PowerShell 实现。
- **UserChoice 删除被 ACL 拦截（多层定位）**：`FileExts\.md\UserChoice` 有显式 `SetValue|Deny` ACE（Windows 防关联劫持），reg.exe 静默失败；`RegDeleteKeyW` P/Invoke 亦失败。修法——改 .NET `Registry.CurrentUser.DeleteSubKey`（权限检查在父键）成功；并以双保险在 `HKCU\Classes` 补建孤儿 ProgID "Markdown Document" 实体（该键原指向不存在的 ProgID）。终态：UserChoice cleared、双击归位。
- **「打开方式」列表残留 pythonw**：OpenWithList 历史 pythonw 条目删除+MRUList 重写，Classes 与 FileExts 两层 `OpenWithProgids` 注册 `MDViewer.md`。实测重跑后列表与图标归位。

---

## v0.2.0

**本次改动：打包嵌入式 Python 摆脱系统依赖，托盘由 pystray 重写为纯 ctypes 零第三方**

**变更**

- **便携 Python**：`python-3.11.9-embed-amd64` 解压至工具 `python/`（34 项约 11MB），`install.cmd` 启动项改指 `%~dp0python\pythonw.exe`，目标机无需安装 Python。`md_launch.pyw` 本就以 `sys.executable`+脚本目录定位，无需改动。
- **托盘零第三方**：pystray 重写为纯 ctypes `Shell_NotifyIcon`，失败自动降级常驻不崩。兼容修补：该 embed 分发 `ctypes.wintypes` 缺 `LRESULT`/`UINT_PTR` 显式定义（Win64 宽度）；`LoadIconW` 资源 ID 须 cast `c_wchar_p`（MAKEINTRESOURCE 约定）。

**验证**

- `python/python.exe` 下 py_compile 通过；HTTP GET `/`、`/api/file` 读写/404 全 PASS；`md_launch.pyw` 端到端拉起后端 PASS；托盘初始化无报错。

---

## v0.1.0

**本次改动：项目起点——零依赖单文件 Markdown 编辑器 + 本地服务化 + .md 关联安装器**

**新增**

- **`markdown-editor.html`**：单文件编辑器，解析内核为纯手写正则（`parseInline`/`parseList`/`parseTable`/`parseMarkdown`），不引 marked.js/markdown-it。
- **`md_server.py`**：标准库 http.server 后端，`/api/file` 路由读写本地文件（绕开 `file://` 禁止 JS 读盘的限制），前端加 `?file=` 注入适配层（解析内核零改动，仅 UI 段新增保存按钮）；可选 pystray 托盘（缺失降级常驻）。
- **安装器**：`install.cmd`/`uninstall.cmd`（HKCU 注册 .md 右键菜单+默认关联+快捷方式，无需管理员可逆）、`md_launch.pyw`（Explorer 传路径，启动/复用后端开浏览器）、`md_stop.cmd`、`_mklnk.ps1`。

**验证**

- py_compile 通过；HTTP 路由/读/写/404 冒烟全 PASS；后端启动+端口探测链路验证通过。已知限制如实记录：Win11 新版右键菜单第三方项可能仅在"显示更多选项"（legacy 开关应对）；install.cmd 会改 .md 双击关联（卸载还原）。

---
