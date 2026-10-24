# R5：编辑体验打磨（工具栏收敛、中英混排、代码块运行、右键菜单）

日期：2026-10-24　状态：实施中

## 背景

v3.0.0 的界面与运行链路稳定后，用户提出四处摩擦：

1. 工具栏最左边还挂着产品名「MDWright」，占了菜单的位置却不再提供信息（安装包与窗口标题已经说了）；
2. 中文里夹英文/数字时没有空格，读起来挤（`按Esc退出`、`用Python写`）；
3. 代码块运行按「脚本」语义执行，与 R/Python 控制台不一致：
   - R 里 `mtcars`、`1:10`、`mpg |> count(class)` 在控制台会自动打印，这里不打印，除非手写 `print()`；
   - Python 走随包 3.11.9（只有标准库），`import pandas` 必然失败，且路径不可配；
4. 编辑区没有右键菜单，剪切/复制/粘贴要靠键盘。

## 决策（用户已确认）

| 项 | 决定 |
|---|---|
| Python 双路线默认 | 留空 = 随包内置；在「设置 → 外部工具」填了路径才走本地解释器 |
| 中英空格作用域 | 预览与导出同步（单文件 HTML / 分页 HTML / PDF / Word） |
| 右键菜单项 | 基础编辑（撤销/重做/剪切/复制/粘贴/全选）+ Markdown 快捷（加粗/斜体/行内代码/链接/表格/公式） |

## 实施

### 1. 工具栏去掉产品名
`mdwright.html`：删 `<div class="tb-group brand">MDWright</div>` 与 `.brand` 规则。菜单从「文件」直接起步。

### 2. 中文与英文/数字之间自动补空格
- 渲染期补，**源文一个字节都不改**：`cjkSpace()` 只处理「汉字紧贴 ASCII 字母/数字」，
  幂等、不动全角标点。
- `parseInline()` 在代码段/转义占位之后、`escapeHtml` 之前调用 → 覆盖正文、标题、表格、列表；
  行内代码、公式、URL 因占位符隔断天然不受影响。
- Word 导出吃的是 markdown 源文（pandoc），故加 `cjkSpaceMarkdown()`：按行扫描跳过围栏代码、
  按 `` ` `` 跳过行内代码后，对剩余片段套同一函数——**同一套规则只实现一次**（都在 JS 里）。

### 3. 代码块运行
- **R**：`_R_WRAPPER` 不再整段 `eval`，改为 `parse()` 后逐表达式 `withVisible(eval(...))`，
  可见值自动 `print`——这就是 R 控制台语义，不需要用户手写 `print()`；赋值、`library()`
  仍不打印；`ggplot` 对象照旧走 `print` 画图。
- **Python**：`_run_py_code(code, python_exe=None)`，`/api/run-py` 读 `tools.python_path`：
  填了且文件存在 → 用本地解释器，否则回落内置。返回体带 `runtime`（`builtin`/`local`）
  与 `python`（版本行），输出块下方显示一行「内置 Python 3.11.9」或「本地 Python 3.12.4」，
  不让用户猜这段代码是谁跑的。
- `md_tools.py`：新增 `python_path` 键与 `find_python()`；**只认显式配置**，不去 PATH 乱探
  （留空就是内置，探测会让行为随机器漂移）。

### 4. 编辑区右键菜单
新增 `#ctxMenu`（复用菜单视觉），绑在 `#editor` 的 `contextmenu`：
- 编辑项走 `document.execCommand`（contenteditable 原生撤销栈）；
- 粘贴走 `navigator.clipboard.readText()` + `insertText`（127.0.0.1 是安全上下文）；
- Markdown 项直接复用 `applyFormat(fmtDefs[i])`，与「编辑」菜单同一个实现，不另写一套；
- 菜单 `mousedown` 一律 `preventDefault`，保住选区（与工具栏菜单同一教训）。

## 验证

- `tests/_test_cjk_space.py`（新增）：从 `mdwright.html` 抽 JS 函数，跑文本级与 markdown 级用例；
- `tests/_test_run_r.py`：补「裸表达式自动打印」用例（`1:10`、`mtcars`、管道结果）；
- `tests/_test_run_py.py`：补「填了有效路径走本地 / 填了假路径回落内置」；
- `tests/_test_tools.py`：工具键从 4 个改为 5 个；
- 全套 `tests/run_all.py` 跑一遍；
- 截图与宣传图**在这四处改完之后**统一重拍（脚本已入库，一条命令）。

## 不做

- 不做「自动探测本地 Python 优先」（行为随机器漂移，用户已否）；
- 不重录宣传视频（`MDWright-intro.mp4` 已删）；
- 不改 `.smd` 与 `.md` 的落盘内容（空格只存在于渲染与 Word 导出）。
