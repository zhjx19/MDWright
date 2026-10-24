# tests/ —— 回归测试

这些是**逐文件独立**的回归测试：每个 `_test_*.py` 自带上下游，单跑一个文件就能验证一件事，
不需要 pytest、不需要先收集用例、也不共享状态。文件名保持建库时的 `_test_` 前缀不变
（`CHANGELOG.md` 里几十处引用按原名可查）。

## 怎么跑

在**仓库根目录**执行（脚本内部会把仓库根挂上 `sys.path` 与 `HERE`，不依赖当前目录，但示例文件与临时产物按仓库根落位）：

```bat
:: 单个
python\python.exe tests\_test_routes.py

:: 全部（串行，逐文件超时保护）
python\python.exe tests\run_all.py

:: 只跑名字含 parse 的
python\python.exe tests\run_all.py --only parse
```

用随包便携运行时（`python\python.exe`）跑最稳：它就是程序自己用的那个 3.11.9。

## 依赖

| 依赖 | 哪些测试需要 | 缺了会怎样 |
|---|---|---|
| 内置便携 Python | 全部 | — |
| Node（PATH 里） | 解析器类（`_test_escape`、`_test_table_split`、`_test_list_parse`、`_test_deflist`、`_test_callout`、`_test_footnote`、`_test_frontmatter`、`_test_inline_ext`、`_test_fence`、`_test_live_blocks` 等） | 从 `mdwright.html` 抽前端函数源码跑不了 |
| 本机 Edge / Chrome | `_test_browser`、`_test_menu_ui`、`_test_live_view`、`_test_syntax_ui`、`_test_export_ui` 等 UI 级 | 浏览器级用例失败 |
| playwright（可选） | `_test_list_repro`、`_test_list_ui`、`_test_llm_ui`、`_test_outline_jump`、`_test_rag_ui` | 未安装时报 **SKIP**（退出码 77），不算失败；浏览器级能力优先用 `_test_browser` 的 CDP 方案 |
| pandoc | `_test_docx`、`_test_pandoc_prep` | Word 导出验证失败 |
| Rscript | `_test_run_r` | R 代码块执行验证失败 |
| 联网搜索配置 | `_test_llm_websearch` | 该用例失败（其余不受影响） |
| RAG 服务 | `_test_rag`、`_test_rag_e2e` | 该组失败或超时（其余不受影响） |

**没有 mock 冒充真跑**：跑不通的用例就报失败，不会假装通过。

> **跑之前先确认本机没有 MDWright 正在运行**（托盘里有图标、或 `md_stop.cmd` 之前没跑）。
> 部分用例（如 `_test_keepalive`）自己在 18766 起一份服务，正式实例占着这个端口时，
> 请求会打到正式实例上，用例体里那份服务收不到 ping，于是报出与代码无关的 FAIL。

## 各组大概在测什么

| 组 | 文件 | 关注点 |
|---|---|---|
| 前端解析器 | `_test_escape` `_test_table_split` `_test_list_parse` `_test_deflist` `_test_callout` `_test_footnote` `_test_frontmatter` `_test_inline_ext` `_test_fence` `_test_img_width` `_test_highlight` | 从 `mdwright.html` 抽 `/*PARSER_START*/…/*PARSER_END*/` 段真实源码跑 Node，比的是真函数不是副本 |
| 后端路由与生命周期 | `_test_routes` `_test_keepalive` `_test_splash_session` `_test_startup_perf` `_test_outpath` `_test_tools` | 本地服务起停、端口探活、外部工具探测 |
| 导出 | `_test_docx` `_test_pdf` `_test_paged_e2e` `_test_export_css` `_test_export_ui` `_test_smd` `_test_smd_ann` | Word / PDF / 分页 HTML / `.smd` 打包与批注 |
| 代码块执行 | `_test_run_py` `_test_run_r` `_test_llm_deepseek` `_test_llm_websearch` `_test_llm_ui` `_test_rag*` | 便携 Python、Rscript、AI 润色与检索 |
| 浏览器级 UI | `_test_browser` `_test_menu_ui` `_test_live_view` `_test_live_blocks` `_test_syntax_ui` `_test_outline_jump` `_test_list_ui` `_test_copy_btn` | 起本地服务 + 无头浏览器，用 CDP 在页面里求值断言 |
| 发布前自验 | `_test_dist_verify` | 按 `docs/分发清单.md` 最小集组装干净目录，从零启动跑全链路 |

## 约定

- **一个文件只测一件事**，失败时看最后一个 `PASS/FAIL` 行就能定位。
- 需要起服务的用例自己挑端口（多为 18777，与正式服务 18766 隔离）。
- 临时产物落在仓库根且已被 `.gitignore` 覆盖（`_tmp_*`、`_slice/`、`document.paged*.html` 等）；跑完不要手工清 `runtime/`，那是程序自己的配置目录。
- 新增用例：复制一个同类文件改断言即可，**路径用文件头的 `_ROOT`**，别用当前目录相对路径。
