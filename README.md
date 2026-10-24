# MDWright

**Windows 上的单机 Markdown 写作台。** 左侧写、右侧即时渲染；排版、分页、导出、代码块运行全部在本地完成，断网照常用。

![写作与渲染](docs/screenshots/writing.png)

---

## 它解决什么问题

用 Word 写技术文档，公式、代码、图表的排版会反复返工；用在线编辑器，稿子不在自己机器上，断网就干不了活。MDWright 把两件事分开：**写作体验按 Markdown 的来，输出质量按排版的来**——`.md` 是唯一事实来源，PDF / Word 是从它渲染出来的成品。

- **零安装依赖**：程序自带便携 Python 运行时，双击即用，不需要另装解释器、不需要管理员权限。
- **零联网依赖**：KaTeX、Paged.js、Mermaid、Graphviz、WaveDrom、Vega-Lite 全部随包内置，数学公式与图表离线渲染。
- **零数据上传**：文档读写走本地后端（`127.0.0.1`），AI 润色默认接本地模型（LM Studio / Ollama）。

## 功能

| 能力 | 说明 |
|---|---|
| 实时渲染 | 分屏 / 仅编辑 / 仅预览 / 即时渲染（点段即改，块内直接写源码）四种模式显式切换 |
| 数学公式 | KaTeX 离线渲染，行内 `$…$` 与块级 `$$…$$` |
| 图表 | Mermaid（流程/时序/状态/类）、Graphviz `dot`、WaveDrom 时序图、Vega-Lite 数据图 |
| 排版 | 逐元素字体/字号、段落缩进、对齐、表格样式、页面纸张与页边距，全部可视化配置 |
| 分页导出 | Paged.js 组版，纸张、页边距、页码、自动目录、目录独占一页；「导出 → 打印（分页 HTML）」生成成品并交给系统浏览器，浏览器里打印或存为 PDF |
| Word 导出 | 经 pandoc 转 `.docx`，保留标题层级与公式 |
| PDF 直出 | 调本机 Chromium 内核浏览器（Edge / Chrome）无头打印，边距与页码按当前设置 |
| 批注 | 选区批注，随文档保存，可逐条跳转 |
| AI 润色 | 接本地 LM Studio / Ollama，也支持 OpenAI 兼容端点与 DeepSeek |
| 可执行代码块 | 带 `r` / `python` 语言标记的代码块带「▶ 运行」，输出与图形显示在块下方 |
| 自包含文档 | `.smd` 把正文、图片、批注打包成单个文件，跨机器取用要素齐全 |
| 多开 | 多个窗口/标签共享一个后端进程，文件各自独立 |

![分页导出](docs/screenshots/paged-export.png)

## 安装

### 方式一：安装包（推荐）

到本仓库的 **Releases** 页下载 `MDWright-Setup-vX.Y.Z.exe`，双击安装。

- 默认装到 `%LOCALAPPDATA%\MDWright`，**不需要管理员权限**，可在向导里改路径。
- 装完会自动注册：`.md` / `.smd` 右键菜单、双击关联、桌面与开始菜单快捷方式、「设置 → 应用」卸载条目。
- 卸载用开始菜单里的「Uninstall MDWright」，或「设置 → 应用 → MDWright」。

### 方式二：绿色版 / 从仓库直接运行

把整个仓库目录拷到任意位置（路径可含中文，但**不要放在需要管理员权限的目录**），然后：

```bat
python\pythonw.exe md_launch.pyw
```

或者双击 `MDWright.exe`（它只是转发参数给内置 pythonw 的启动器）。

想让右键菜单、快捷方式、文件关联一并生效，再执行一次：

```bat
install.cmd
```

> **不要直接双击 `mdwright.html`**。这个文件由本地后端服务提供，`file://` 方式打开没有后端，页面会提示你走正确入口。

## 外部工具路径：pandoc / 浏览器 / Rscript

程序本身不需要任何外部工具就能写作和预览。三项功能依赖外部程序，**都支持手工指定路径**——装在不常见的位置、装了多个版本、或不想动 PATH，都填一下就行。

### 在哪里设置

工具栏 **「设置」→「外部工具」** 页签。四个输入框，右边实时显示探测到的版本：

| 输入框 | 对应功能 | 典型路径 |
|---|---|---|
| **pandoc（Word 导出）** | 导出 `.docx` | `C:\Program Files\Pandoc\pandoc.exe` |
| **浏览器（PDF 直出）** | 用 Chromium 内核无头打印 PDF | `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` |
| **Rscript（R 代码块）** | 运行带 `r` 标记的代码块、出图 | `C:\Program Files\R\R-4.4.1\bin\x64\Rscript.exe` |
| **quarto（暂时不用）** | 预留位，本版没有功能消费 | — |

填的是**可执行文件的完整路径，带 `.exe`**，不要填目录。填完点「保存路径」。

### 留空时怎么找

留空 = 自动探测，顺序如下：

1. `runtime/settings.json` 里 `tools.*` 填的路径（即上表）；
2. `PATH` 环境变量里的同名命令；
3. 常见安装目录：
   - pandoc：`%ProgramFiles%\Pandoc`、`%LOCALAPPDATA%\Pandoc`、`%ProgramData%\chocolatey\bin`，以及 **Quarto / RStudio 自带的 pandoc**（没单独装 pandoc 时最常命中）；
   - 浏览器：`%ProgramFiles(x86)%` 与 `%ProgramFiles%` 下的 Edge、Chrome；
   - R：注册表 `HKLM\SOFTWARE\R-core\R\<版本>\InstallPath` 登记的目录，再扫 `%ProgramFiles%\R\<最新版本>`。
4. 都找不到 → 对应按钮置灰，鼠标悬停给出缺失原因。**不会导出半成品**。

R 走注册表这一条是有意的：R 常常装在 `D:\` 这类非系统盘，只扫 `C:\Program Files` 永远扫不到。

### 填错了会怎样

**自动回落到自动探测**，不会把功能永久锁死——一次笔误不该让导出按钮消失。

判定方法很直接：输入框右侧显示的是**实际生效的那个程序**（版本号 + 完整路径）。如果显示的路径不是你填的那条，说明你填的那个没被采纳（路径不存在、或不是可执行文件），这时按显示的路径核对，或点「重新检测」再看一次。

### 直接改配置文件

设置面板写的就是这个文件，也可以用编辑器直接改：

```
<安装目录>\runtime\settings.json
```

```json
{
  "tools": {
    "pandoc_path": "",
    "rscript_path": "",
    "quarto_path": "",
    "browser_path": ""
  }
}
```

- 全部留空字符串 = 全部走自动探测；
- 只认识这四个键，其余键在读入时丢弃；
- 非字符串值会被归成空串，不会让程序崩；
- 改完保存，回到设置面板点「重新检测」（或重启程序）生效。

> 路径里的反斜杠要写成 `\\`（JSON 转义），例如 `"rscript_path": "D:\\R-4.6.1\\bin\\x64\\Rscript.exe"`。

### 关于 Python

**Python 路径不可配置，也不打算开放。** 带 `python` 标记的代码块固定使用随包内置的便携运行时（3.11.9）：

- 只有标准库，**没有 pip**，装不了第三方包；
- 只回显 `stdout` / `stderr`，不采集图形；
- 需要画图、需要 `tidyverse` 之类，用带 `r` 标记的代码块——R 的图和输出会显示在代码块下方。

这样设计是为了可复现：同一份 `.md` 换台机器打开，代码块的行为一致，不会因为谁的 `PATH` 里恰好有个装了半套包的 Python 而变样。

## 常用操作

| 操作 | 快捷键 / 入口 |
|---|---|
| 新建 | `Ctrl+N` |
| 保存 | `Ctrl+S`（无当前文件时弹另存为） |
| 带页码目录的成品 | 「导出 → 打印（分页 HTML）」，在打开的浏览器里打印或存 PDF |
| 内置文档 | 「文件」→ 内置文档 → 使用指南 |
| 视图切换 | 工具栏「视图」菜单（分屏 / 仅编辑 / 仅预览 / 即时渲染） |
| 退出后台 | 托盘图标右键，或 `md_stop.cmd` |

## 截图

![图表引擎](docs/screenshots/diagrams.png)

## 目录

```
md_launch.pyw          启动器：起后端、探活端口、拉起窗口
md_server.py           本地后端：文件读写、导出组版、批注、AI 路由、代码块执行
mdwright.html          编辑器界面（由后端提供，勿直接双击）
md_tools.py            外部工具探测（pandoc / 浏览器 / Rscript / quarto）
md_pandoc.py           Word 导出（pandoc 调用与预处理）
_smd.py                .smd 自包含文档格式
_splash.py             启动画面
md_app.pyw             WebView2 内嵌窗口模式
python/                内置便携 Python 运行时
docs/                  使用指南、版权与开源组件声明
katex/ pagedjs/ mermaid/ viz/ wavedrom/ vega/ highlight/   离线前端依赖
installer/             安装包构建脚本（仅用系统自带 csc.exe）
```

## 自己构建安装包

只需要 Windows 自带的 .NET Framework 编译器（`csc.exe`），没有第三方构建依赖：

```bat
python\python.exe installer\_build_installer.py
```

产物在 `_setup_out\MDWright-Setup-vX.Y.Z.exe`。版本号取自 `CHANGELOG.md` 的第一条 `## vX.Y.Z`。

## 许可

本项目以 **GNU Affero General Public License v3.0 or later** 发布，© 2026 wUwproject，全文见 [LICENSE](LICENSE)。

- 可以自由使用、学习、修改、再分发，修改后的版本须同样以 AGPL-3.0-or-later 开源。
- 以网络服务方式向他人提供本程序或其修改版时，须按 AGPL 第 13 条向使用者提供对应源码。

随包分发的第三方组件（KaTeX、Paged.js、Mermaid、viz-js、WaveDrom、Vega、highlight.js、Python、Pillow）各自的许可证与全文见 [docs/版权与开源组件声明.md](docs/版权与开源组件声明.md) 与 `LICENSES/`。

变更历史见 [CHANGELOG.md](CHANGELOG.md)。
