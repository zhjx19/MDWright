# MDEditor R2 导出新格式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 MDEditor 加两条新导出出口——**Word `.docx`**（本地 pandoc，LaTeX 公式落为 Word 原生 OMML 公式）与 **PDF 直出文件**（headless Chromium 打印，无对话框，Typora 路线）。

**Architecture:** 两条出口都沿用现有「前端把渲染结果/源文交给后端 → 后端组装落盘」的分层：Word 走 **markdown 源**（pandoc 吃源文，公式原生转 OMML），PDF 走 **分页 HTML**（复用 `build_paged_html`，用 headless Chromium 的 `--print-to-pdf` 出文件）。外部工具（pandoc / Chromium 内核浏览器）统一由一个探测模块负责，缺失时按钮置灰、明确报错。

**Tech Stack:** Python 3.11 标准库（subprocess/zipfile/re），pandoc 3.10（外部，用户自备），Chromium 内核浏览器（Edge/Chrome，系统自带），原生 HTML/CSS/JS 单页前端。

**Spec:** `docs/superpowers/specs/2026-10-21-mdeditor-capability-expansion-design.md`（§5 导出新格式设计 / §7.1 统一探测 / §8 测试策略 / §9 文档）

## Global Constraints

- **零新增依赖**：后端只用 Python 标准库；不装 pip 包、不引 npm 包。pandoc 与浏览器是**外部工具**，用户自备。
- **后端仅标准库**，须在 Python 3.11 内嵌运行时下可跑。
- **不在本轮做**：外部工具路径的**手工配置 UI**（`PUT /api/tools` 与设置面板「外部工具」区属 R4）、R 代码块执行、quarto 消费、reference.docx 样式模板定制。
- **fail-closed**：工具缺失 / 导出失败一律明确报错并**不产出半成品文件**；不得吞异常返回「成功」。
- **导出不污染文档目录**：中间产物（pandoc 的 tmp.md、浏览器 user-data-dir）一律放系统临时目录；最终产物（`.docx` / `.pdf`）与文档同目录。
- **服务版本**：`MD_SERVER_VERSION` 当前 55；本轮只在 Task 6 递增到 56（触发旧页面自愈刷新）。
- **测试端口**：既有测试占 18766；新增导出测试用 **18777**（与 R1 的 `_test_browser.py` 一致）。
- **每个任务结束提交一次**，提交信息中文、动词开头。
- **既有 22+ 个 `_test_*.py` 必须保持绿**；R1 已把 5 个 playwright 依赖用例与 `_test_rag_e2e.py`（写死他人机器路径）登记为环境豁免。

## Review Focus

规格暗示、但单个任务测试容易漏掉的五类输入/条件（每条在对应任务里有断言）：

1. **未保存的新文档（`currentFile` 为空）**——导出必须提示「请先保存文档」，而不是写到奇怪的位置或崩掉。→ Task 3/4/5
2. **`.smd` 自包含文档导出**——图片在 ZIP 包内，工作目录必须是解包目录（`_smd.base_dir_for`），否则图片全丢且不报错。→ Task 3
3. **pandoc 缺失 / 浏览器缺失**——必须给出可执行的下一步（装什么、怎么配），且**不产出文件**。→ Task 1/3/4
4. **PDF 页数与分页 DOM 不一致**（分页未跑完就被打印）——不得输出半截 PDF；要么重试成功，要么明确失败。→ Task 4
5. **文件名/路径含中文、空格、`#`、`%`**——导出路径与 CDP/命令行传参必须能承受（走列表参数而非拼接 shell 字符串）。→ Task 3/4

---

## File Structure

**新建**

| 文件 | 职责 |
|---|---|
| `md_tools.py` | 外部工具探测（pandoc / 浏览器 / R / quarto）：候选路径 → 首个存在者 → 版本；供 R2 与 R4 共用 |
| `md_pandoc.py` | 方言 → pandoc markdown 的预处理（Callout、图片 `{N}`、图表围栏）+ pandoc 调用封装 |
| `_test_tools.py` | 探测顺序、首个存在者、版本解析、返回结构 |
| `_test_pandoc_prep.py` | 三则方言转换（纯函数，不依赖 pandoc 安装） |
| `_test_docx.py` | 真 pandoc 端到端：docx 产出、OMML、脚注、图片嵌入、缺工具报错 |
| `_test_pdf.py` | 真浏览器端到端：PDF 产出、页数校验、纸张尺寸、缺浏览器报错 |
| `_test_export_ui.py` | 浏览器级：两个新按钮存在、无工具时置灰、点击后 toast |

**修改**

| 文件 | 改动 |
|---|---|
| `md_server.py` | ① `GET /api/tools`；② `POST /api/export-docx`；③ `POST /api/export-pdf`；④ `GET /api/reveal`（在资源管理器里定位文件）；⑤ `MD_SERVER_VERSION` 55→56 |
| `markdown-editor.html` | 工具栏加「Word」「PDF」两个按钮；导出 payload 抽成 `pagedPayload()`；按钮置灰逻辑（启动时查 `/api/tools`）；成功后 toast + 「打开所在目录」 |
| `CHANGELOG.md` | v2.2.0 条目 |
| `README.md` | 功能速览 + 文件清单补 `md_tools.py` / `md_pandoc.py` |
| `docs/MDEditor 使用指南.md` | 「保存与导出」章补 Word / PDF 两种出口与依赖说明 |
| `docs/分发清单.md` | 补两个新模块 + 外部工具前提（pandoc / 浏览器） |

---

### Task 1: 外部工具探测模块 + `GET /api/tools`

**Files:**
- Create: `md_tools.py`
- Modify: `md_server.py`（新增路由，放在 `/api/version` 之后）
- Test: `_test_tools.py`

**Interfaces:**
- Consumes: `runtime/settings.json` 的 `tools` 段（R4 才写入，本轮读空即走自动探测）
- Produces:
  - `md_tools.find_pandoc(configured="") -> str|None`
  - `md_tools.find_browser(configured="") -> str|None`
  - `md_tools.find_r(configured="") -> str|None`
  - `md_tools.find_quarto(configured="") -> str|None`
  - `md_tools.version_of(path) -> str`（失败返回 `""`）
  - `md_tools.probe_all(configured=None) -> dict`：`{"pandoc": {"found","path","version"}, "browser": {...}, "r": {...}, "quarto": {...}}`
  - 路由 `GET /api/tools` → `{"ok": true, "tools": probe_all()}`

- [ ] **Step 1: 写失败的测试**

创建 `_test_tools.py`：

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""外部工具探测回归（R2）：
- _first_existing 取候选里第一个真实存在的文件
- version_of 对不存在的程序返回 ""（不抛）
- probe_all 返回四个工具键，结构固定；pandoc/browser 缺失时不崩
- 配了不存在的路径时回落到自动探测（不因用户手填错误就判缺失）
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import md_tools  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def main():
    real = sys.executable                      # 一定存在的可执行文件
    check("_first_existing 跳过不存在项",
          md_tools._first_existing(["/no/such/pandoc.exe", real]) == real)
    check("_first_existing 全不存在返回 None",
          md_tools._first_existing(["/no/a", "/no/b"]) is None)

    check("version_of 不存在的程序返回空串",
          md_tools.version_of("/no/such/pandoc.exe") == "")

    t = md_tools.probe_all()
    check("probe_all 含四个工具键",
          set(t.keys()) == {"pandoc", "browser", "r", "quarto"}, str(sorted(t.keys())))
    for k, v in t.items():
        check("probe_all[%s] 结构固定" % k,
              set(v.keys()) == {"found", "path", "version"}, str(v))
        check("probe_all[%s] found 与 path 一致" % k,
              bool(v["found"]) == bool(v["path"]), str(v))

    # 手填了不存在的路径 → 回落到自动探测，而不是直接判缺失
    t2 = md_tools.probe_all({"pandoc": "/no/such/pandoc.exe"})
    check("错误的显式路径回落到自动探测",
          set(t2.keys()) == {"pandoc", "browser", "r", "quarto"})

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_tools.py`
Expected: FAIL（`ModuleNotFoundError: No module named 'md_tools'`）

- [ ] **Step 3: 实现 `md_tools.py`**

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""外部工具探测：pandoc / Chromium 内核浏览器 / Rscript / quarto。

探测顺序：settings.json 显式路径 → PATH → 常见安装目录 / 注册表。
找不到不抛异常，返回 None——调用方据此**置灰按钮并给安装指引**，
而不是在导出中途炸掉（fail-closed 的正向形态：失败要前置且可说人话）。

注意：显式路径填错时**回落**到自动探测，而不是直接判缺失——
用户手填一次笔误不该让功能永久不可用。
"""
import os
import shutil
import subprocess
import sys

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# R 的安装位置由注册表给出（与盘符无关，本机实测 HKLM\SOFTWARE\R-core\R\4.6.1 → d:\R-4.6.1）
_R_REG_KEY = r"SOFTWARE\R-core\R"


def _first_existing(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


def version_of(path):
    """取程序 --version 首行；失败返回空串（不抛，探测阶段要静默）。"""
    if not path or not os.path.isfile(path):
        return ""
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=8,
                           creationflags=_NO_WINDOW)
        out = (r.stdout or "") + (r.stderr or "")
        for ln in out.splitlines():
            if ln.strip():
                return ln.strip()[:120]
    except Exception:
        pass
    return ""


def _which(name):
    p = shutil.which(name)
    return p if p else None


def find_pandoc(configured=""):
    cands = [configured, _which("pandoc")]
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    lad = os.environ.get("LOCALAPPDATA", "")
    pd = os.environ.get("ProgramData", r"C:\ProgramData")
    cands += [
        os.path.join(pf, "Pandoc", "pandoc.exe"),
        os.path.join(lad, "Pandoc", "pandoc.exe"),
        os.path.join(pd, "chocolatey", "bin", "pandoc.exe"),
        # Quarto / RStudio 自带 pandoc（未单独安装时最常见的来源）
        os.path.join(pf, "Quarto", "bin", "tools", "pandoc.exe"),
        os.path.join(pf, "RStudio", "resources", "app", "bin", "quarto",
                     "bin", "tools", "pandoc.exe"),
        os.path.join(pf86, "RStudio", "resources", "app", "bin", "quarto",
                     "bin", "tools", "pandoc.exe"),
    ]
    return _first_existing(cands)


def find_browser(configured=""):
    cands = [configured]
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    cands += [
        os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
    ]
    return _first_existing(cands)


def _r_install_dirs():
    """从注册表读 R 安装目录（与盘符无关）；读不到返回空列表。"""
    out = []
    if sys.platform != "win32":
        return out
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _R_REG_KEY) as k:
            i = 0
            while True:
                try:
                    ver = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, ver) as vk:
                        ip, _ = winreg.QueryValueEx(vk, "InstallPath")
                        if ip:
                            out.append(ip)
                except OSError:
                    continue
    except Exception:
        pass
    return out


def find_r(configured=""):
    cands = [configured, _which("Rscript")]
    for d in _r_install_dirs():
        cands.append(os.path.join(d, "bin", "x64", "Rscript.exe"))
        cands.append(os.path.join(d, "bin", "Rscript.exe"))
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    if os.path.isdir(os.path.join(pf, "R")):
        for name in sorted(os.listdir(os.path.join(pf, "R")), reverse=True):
            cands.append(os.path.join(pf, "R", name, "bin", "x64", "Rscript.exe"))
    return _first_existing(cands)


def find_quarto(configured=""):
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    return _first_existing([configured, _which("quarto"),
                            os.path.join(pf, "Quarto", "bin", "quarto.exe")])


def _entry(path):
    return {"found": bool(path), "path": path or "", "version": version_of(path) if path else ""}


def probe_all(configured=None):
    """一次性探测四个工具。configured 形如 {"pandoc": "...", ...}（R4 才写入）。"""
    c = configured or {}
    return {
        "pandoc": _entry(find_pandoc(c.get("pandoc", ""))),
        "browser": _entry(find_browser(c.get("browser", ""))),
        "r": _entry(find_r(c.get("rscript", ""))),
        "quarto": _entry(find_quarto(c.get("quarto", ""))),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_tools.py`
Expected: ALL PASS（本机 pandoc 会命中 RStudio 自带那份）

- [ ] **Step 5: 加路由**

在 `md_server.py` 的 `do_GET` 里、`/api/version` 分支之后插入：

```python
        if u.path == "/api/tools":
            # 外部工具探测（pandoc / 浏览器 / R / quarto）：前端据 found 决定按钮置灰
            try:
                import md_tools
                settings = _load_json(SETTINGS_PATH, {})
                cfg = settings.get("tools") if isinstance(settings, dict) else {}
                if not isinstance(cfg, dict):
                    cfg = {}
                self._send(200, json.dumps({"ok": True, "tools": md_tools.probe_all(cfg)},
                                           ensure_ascii=False),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
```

- [ ] **Step 6: 验证路由**

Run: 起服务后 `curl http://127.0.0.1:18766/api/tools`（或用 python urllib）
Expected: `{"ok":true,"tools":{"pandoc":{"found":true,...},"browser":{"found":true,...},...}}`

- [ ] **Step 7: 提交**

```bash
git add md_tools.py _test_tools.py md_server.py
git commit -m "feat: 外部工具探测模块（pandoc/浏览器/R/quarto）与 /api/tools"
```

---

### Task 2: 方言 → pandoc 预处理

**Files:**
- Create: `md_pandoc.py`
- Test: `_test_pandoc_prep.py`

**Interfaces:**
- Consumes: R1 定稿的方言（Callout、图片 `{N}`、图表围栏）
- Produces:
  - `md_pandoc.prepare_markdown(src) -> str`（纯函数）
  - `md_pandoc.export_docx(md_text, md_path, out_path) -> str`（返回 pandoc 可执行路径；失败抛 `RuntimeError`）

- [ ] **Step 1: 写失败的测试**

创建 `_test_pandoc_prep.py`：

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""方言 → pandoc markdown 预处理回归（R2）：
只做 pandoc 不认的三件事（Callout / 图片宽度 {N} / 图表围栏），其余原样透传。
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import md_pandoc  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def prep(s):
    return md_pandoc.prepare_markdown(s)


def main():
    # 1 Callout → 引用块 + 粗体类型名
    out = prep("> [!NOTE]\n> 内容\n")
    check("Callout 转引用块粗体", "> **NOTE**" in out and "[!NOTE]" not in out, out)
    out = prep("> [!WARNING] 自定义标题\n> 内容\n")
    check("Callout 带标题", "> **WARNING** 自定义标题" in out, out)
    out = prep("> 普通引用\n")
    check("普通引用不动", out.strip() == "> 普通引用", out)

    # 2 图片 {N} → pandoc {width=N%}
    out = prep("![图](a.png){30}\n")
    check("图片宽度转 pandoc 属性", "{width=30%}" in out and "{30}" not in out, out)
    out = prep("![图](a.png)\n")
    check("无宽度图片不动", out.strip() == "![图](a.png)", out)
    out = prep("![图](a.png){150}\n")
    check("超 100 钳到 100", "{width=100%}" in out, out)

    # 3 图表围栏：剥掉 {N}，语言保留（pandoc 当普通代码块）
    out = prep("```mermaid {30}\ngraph TD\nA-->B\n```\n")
    check("图表围栏剥宽度", "```mermaid\n" in out and "{30}" not in out, out)
    out = prep("```mermaid\ngraph TD\nA-->B\n```\n")
    check("图表围栏无宽度原样", "```mermaid\n" in out, out)

    # 4 其余语法原样透传（pandoc 原生支持）
    src = "脚注[^a]\n\n[^a]: 说明\n\n==高亮== x^2^\n\n公式 $E=mc^2$\n\n术语\n: 定义\n"
    check("脚注/高亮/上下标/公式/定义列表原样",
          prep(src) == src, prep(src))

    # 5 代码块里的 Callout 语法与 {30} 不得被改写
    src = "```\n> [!NOTE]\n![图](a.png){30}\n```\n"
    check("代码块内不改写", prep(src) == src, prep(src))

    # 6 front matter 原样（pandoc 读作 metadata）
    src = "---\ntitle: t\n---\n\n正文\n"
    check("front matter 原样", prep(src) == src, prep(src))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_pandoc_prep.py`
Expected: FAIL（`No module named 'md_pandoc'`）

- [ ] **Step 3: 实现 `md_pandoc.py`**

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word（.docx）导出：方言 → pandoc markdown → pandoc 调用。

**只做 pandoc 不认的三件事**：Callout、图片宽度 `{N}`、图表围栏的 `{N}`。
脚注 / 定义列表 / YAML front matter / 行内高亮 / 上下标 / 公式 pandoc 原生支持，
一律原样透传——**不要在这里重写 pandoc 已会的东西**（重复实现必然走样）。

公式：`$...$` / `$$...$$` 交给 pandoc，docx 侧落为 Word 原生公式（OMML），
实测 `<m:oMath>` / `<m:sSup>` / `<m:f>` 齐全，不需要任何图像化或文本化降级。
"""
import os
import re
import subprocess
import sys

import md_tools

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_FENCE_RE = re.compile(r"^(\s*)(```|~~~)(.*)$")
_CALLOUT_RE = re.compile(r"^(\s*>\s*)\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$")
_IMG_W_RE = re.compile(r"(!\[[^\]]*\]\([^)]+\))\s*\{([1-9]\d{0,2})\}")


def _clamp(pct):
    return min(100, int(pct))


def prepare_markdown(src):
    """把本文方言改写成 pandoc 认得的 markdown。"""
    out = []
    fence = False
    for ln in src.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _FENCE_RE.match(ln):
            # 围栏行：图表围栏的 `{N}` 宽度参数 pandoc 不认，剥掉；语言保留
            if not fence:
                m = _FENCE_RE.match(ln)
                info = m.group(3).strip()
                info = re.sub(r"\s*\{[1-9]\d{0,2}\}\s*$", "", info)
                out.append(m.group(1) + m.group(2) + (info if info else ""))
                fence = True
            else:
                out.append(ln)
                fence = False
            continue
        if fence:
            out.append(ln)          # 代码块内部一律不动
            continue
        m = _CALLOUT_RE.match(ln)
        if m:
            kind, title = m.group(2), m.group(3)
            out.append(m.group(1) + "**" + kind + "**" + ((" " + title) if title else ""))
            continue
        out.append(_IMG_W_RE.sub(
            lambda mm: mm.group(1) + "{width=" + str(_clamp(mm.group(2))) + "%}", ln))
    return "\n".join(out)


def _workdir_for(md_path):
    """图片相对路径的基准：普通 .md 用所在目录；.smd 用解包目录（包内 assets 才可见）。"""
    if not md_path:
        return ""
    try:
        import _smd
        if _smd.is_smd(md_path):
            return _smd.base_dir_for(md_path)
    except Exception:
        pass
    return os.path.dirname(os.path.abspath(md_path))


def export_docx(md_text, md_path, out_path):
    """跑 pandoc 出 docx。返回 pandoc 路径；失败抛 RuntimeError（文案面向用户）。"""
    pandoc = md_tools.find_pandoc()
    if not pandoc:
        raise RuntimeError("未检测到 pandoc.exe：请安装 pandoc（winget install JohnMacFarlane.Pandoc）"
                           "或在后续版本的「外部工具」中指定路径")
    workdir = _workdir_for(md_path)
    tmp_md = out_path + ".src.md"
    try:
        with open(tmp_md, "w", encoding="utf-8", newline="\n") as f:
            f.write(prepare_markdown(md_text))
        cmd = [pandoc, "-f", "markdown+mark", "-t", "docx", "-o", out_path]
        if workdir:
            cmd += ["--resource-path=" + workdir]
        cmd.append(tmp_md)
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180,
                           creationflags=_NO_WINDOW)
        if r.returncode != 0 or not os.path.isfile(out_path):
            detail = ((r.stderr or r.stdout or "").strip() or "未知错误")[:400]
            raise RuntimeError("pandoc 导出失败：%s" % detail)
        return pandoc
    finally:
        try:
            if os.path.exists(tmp_md):
                os.remove(tmp_md)
        except Exception:
            pass
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_pandoc_prep.py`
Expected: ALL PASS

- [ ] **Step 5: 提交**

```bash
git add md_pandoc.py _test_pandoc_prep.py
git commit -m "feat: 方言→pandoc 预处理（Callout/图片宽度/图表围栏）"
```

---

### Task 3: `POST /api/export-docx`

**Files:**
- Modify: `md_server.py`（路由）
- Test: `_test_docx.py`

**Interfaces:**
- Consumes: `md_pandoc.export_docx`；请求体 `{path, markdown}`
- Produces: `{ok: true, path: "<落盘的 .docx 绝对路径>"}` 或 `{ok: false, error}`

- [ ] **Step 1: 写失败的测试**

创建 `_test_docx.py`：

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 导出的端到端回归（R2，需本机 pandoc）：
- 产出 .docx（合法 ZIP）
- 公式落为 OMML（<m:oMath>），不是 LaTeX 文本
- 脚注进 word/footnotes.xml
- 图片按相对路径嵌入 word/media/
- 未保存文档（path 为空）明确报错，不产文件
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PORT = 18777
fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def post(path, obj):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=200) as r:
        return json.loads(r.read().decode("utf-8"))


MD = """---
title: 导出测试
---

# 一级标题

行内公式 $E=mc^2$，块级：

$$
\\int_0^1 x^2\\,dx = \\frac{1}{3}
$$

脚注引用[^a]。

> [!NOTE]
> 提示内容

![图](assets/pic.png)

[^a]: 脚注说明
"""


def main():
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    tmp = tempfile.mkdtemp(prefix="mddocx-")
    try:
        doc = os.path.join(tmp, "文档 名#1.md")
        os.makedirs(os.path.join(tmp, "assets"), exist_ok=True)
        with open(doc, "w", encoding="utf-8") as f:
            f.write(MD)
        # 1×1 PNG（真实图片，供 pandoc 嵌入）
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
            "00000049454e44ae426082")
        with open(os.path.join(tmp, "assets", "pic.png"), "wb") as f:
            f.write(png)

        j = post("/api/export-docx", {"path": doc, "markdown": MD})
        check("接口 ok", j.get("ok") is True, str(j)[:300])
        out = j.get("path") or ""
        check("落盘在同目录且为 .docx",
              out.lower().endswith(".docx") and os.path.dirname(out) == tmp, out)
        if out and os.path.isfile(out):
            z = zipfile.ZipFile(out)
            names = z.namelist()
            x = z.read("word/document.xml").decode("utf-8", "replace")
            check("是合法 docx（含 word/document.xml）", "word/document.xml" in names)
            check("公式为 OMML", "<m:oMath" in x, x[:200])
            check("分数结构存在", "<m:f>" in x or "<m:num>" in x)
            check("无 LaTeX 源码残留", "\\\\frac" not in x and "$$" not in x)
            check("脚注进 footnotes.xml",
                  "word/footnotes.xml" in names
                  and "脚注说明" in z.read("word/footnotes.xml").decode("utf-8", "replace"))
            check("图片嵌入 word/media", any(n.startswith("word/media/") for n in names),
                  str([n for n in names if n.startswith("word/media")]))
            check("front matter 进核心属性",
                  "导出测试" in z.read("docProps/core.xml").decode("utf-8", "replace"))

        # 未保存文档 → 明确报错且不产文件
        j2 = post("/api/export-docx", {"path": "", "markdown": "# x\n"})
        check("未保存文档明确报错", j2.get("ok") is False and "保存" in (j2.get("error") or ""),
              str(j2))
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_docx.py`
Expected: FAIL（404 / `ok` 缺失）

- [ ] **Step 3: 实现路由**

在 `md_server.py` 的 `do_POST` 里、`/api/export-paged` 分支之后插入：

```python
        if u.path == "/api/export-docx":
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                md_path = (obj.get("path") or "").strip()
                md_text = obj.get("markdown") or ""
                if not md_path:
                    self._send(400, json.dumps({"ok": False, "error": "请先保存文档再导出 Word"},
                                               ensure_ascii=False))
                    return
                if not os.path.isfile(md_path):
                    self._send(400, json.dumps({"ok": False, "error": "文档不存在：%s" % md_path},
                                               ensure_ascii=False))
                    return
                stem = os.path.splitext(os.path.basename(md_path))[0]
                out = os.path.join(os.path.dirname(os.path.abspath(md_path)), stem + ".docx")
                import md_pandoc
                md_pandoc.export_docx(md_text, md_path, out)
                self._send(200, json.dumps({"ok": True, "path": out}, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_docx.py`
Expected: ALL PASS（10 条）

- [ ] **Step 5: 提交**

```bash
git add md_server.py _test_docx.py
git commit -m "feat: Word 导出（pandoc，LaTeX 落 OMML 公式）"
```

---

### Task 4: `POST /api/export-pdf`（两趟法）

**Files:**
- Modify: `md_server.py`（路由 + helper）
- Test: `_test_pdf.py`

**Interfaces:**
- Consumes: `build_paged_html`；请求体与 `/api/export-paged` 同构（`{path, bodyHtml, tsCss, cfg, docTitle}`）
- Produces: `{ok: true, path, pages: N}` 或 `{ok: false, error}`

**关键实现约束：**
- 浏览器访问的 URL 端口必须取 `self.server.server_address[1]`（真实监听端口），**不能用模块常量 `PORT`**——否则测试端口（18777）下 headless 会去连 18766 的旧服务。
- 两趟：`--dump-dom` 数 `.pagedjs_page` 得 P；`--print-to-pdf` 数 PDF 页得 Q；`Q==P` 才算成功，否则按预算序列 30000→60000→120000 重试，仍不等则报错**不落文件**。

- [ ] **Step 1: 写失败的测试**

创建 `_test_pdf.py`：

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""PDF 直出端到端回归（R2，需本机 Chromium 内核浏览器）：
- 产出合法 PDF（%PDF 头）
- 页数与分页 DOM 一致（两趟法校验，防半截 PDF）
- 纸张尺寸跟随 @page（A4 → MediaBox 595×842 附近）
- 未保存文档明确报错
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PORT = 18777
fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def post(path, obj):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


BODY = "<h1>第一章</h1><p>正文段落</p><p>" + ("填充内容。" * 400) + "</p>"


def main():
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    tmp = tempfile.mkdtemp(prefix="mdpdf-")
    try:
        doc = os.path.join(tmp, "文档 名#1.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write("# x\n")
        j = post("/api/export-pdf", {"path": doc, "bodyHtml": BODY, "tsCss": "",
                                     "docTitle": "", "cfg": {"paper": "A4", "mt": 25, "mb": 25}})
        check("接口 ok", j.get("ok") is True, str(j)[:300])
        out = j.get("path") or ""
        check("落盘在同目录且为 .pdf",
              out.lower().endswith(".pdf") and os.path.dirname(out) == tmp, out)
        if out and os.path.isfile(out):
            data = open(out, "rb").read()
            check("合法 PDF 头", data[:5] == b"%PDF-", data[:16])
            pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
            check("页数 >= 2（长文分页）", pages >= 2, str(pages))
            check("接口回报页数与实际一致", j.get("pages") == pages,
                  "%r vs %r" % (j.get("pages"), pages))
            mb = re.findall(rb"/MediaBox\s*\[([^\]]*)\]", data)
            if mb:
                n = [float(v) for v in mb[0].split()]
                w, h = n[2] - n[0], n[3] - n[1]
                check("A4 纸张尺寸", abs(w - 595) < 6 and abs(h - 842) < 6, "%r x %r" % (w, h))
            else:
                check("A4 纸张尺寸", False, "no MediaBox")

        j2 = post("/api/export-pdf", {"path": "", "bodyHtml": "<p>x</p>", "tsCss": "",
                                      "cfg": {}})
        check("未保存文档明确报错", j2.get("ok") is False and "保存" in (j2.get("error") or ""),
              str(j2))
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_pdf.py`
Expected: FAIL（404）

- [ ] **Step 3: 实现 helper 与路由**

在 `md_server.py` 的 `build_paged_html` 之后新增：

```python
def _chromium_print_pdf(browser, url, out_pdf, budget_ms):
    """两趟法：先数分页 DOM 的页数，再打印并数 PDF 页数，相等才算成功。

    为什么要两趟：Paged.js 的分页在页面加载后由 JS 异步完成，headless 的
    --print-to-pdf 若在分页跑完前触发，会打出半截文档（且不报任何错）。
    拿 DOM 里的 .pagedjs_page 数量当基准，是唯一不引入 CDP 客户端也能验证的办法。
    """
    prof = tempfile.mkdtemp(prefix="mdpdf-prof-")
    base = [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--user-data-dir=" + prof]
    try:
        r1 = subprocess.run(base + ["--virtual-time-budget=%d" % budget_ms, "--dump-dom", url],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=budget_ms / 1000.0 + 60,
                            creationflags=0x08000000)
        dom = r1.stdout or ""
        want = dom.count("pagedjs_page")
        if want <= 0:
            return 0, 0
        if os.path.exists(out_pdf):
            os.remove(out_pdf)
        r2 = subprocess.run(base + ["--no-pdf-header-footer",
                                    "--virtual-time-budget=%d" % budget_ms,
                                    "--print-to-pdf=" + out_pdf, url],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=budget_ms / 1000.0 + 60,
                            creationflags=0x08000000)
        if not os.path.isfile(out_pdf):
            return want, 0
        data = open(out_pdf, "rb").read()
        if not data.startswith(b"%PDF-"):
            return want, 0
        return want, len(re.findall(rb"/Type\s*/Page[^s]", data))
    finally:
        shutil.rmtree(prof, ignore_errors=True)
```

在 `do_POST` 的 `/api/export-docx` 之后插入：

```python
        if u.path == "/api/export-pdf":
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                md_path = (obj.get("path") or "").strip()
                if not md_path:
                    self._send(400, json.dumps({"ok": False, "error": "请先保存文档再导出 PDF"},
                                               ensure_ascii=False))
                    return
                if not os.path.isfile(md_path):
                    self._send(400, json.dumps({"ok": False, "error": "文档不存在：%s" % md_path},
                                               ensure_ascii=False))
                    return
                import md_tools
                browser = md_tools.find_browser()
                if not browser:
                    self._send(400, json.dumps({"ok": False,
                        "error": "未检测到 Chromium 内核浏览器（Edge/Chrome），无法直出 PDF；"
                                 "可改用「打印」按钮"}, ensure_ascii=False))
                    return
                html = build_paged_html(md_path, obj.get("bodyHtml", ""),
                                        obj.get("tsCss", ""), obj.get("cfg", {}) or {},
                                        obj.get("docTitle") or "")
                name = "document.paged.html"
                with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
                    f.write(html)
                # 端口取真实监听端口：测试可能把服务起在非 18766 上
                port = self.server.server_address[1]
                url = "http://127.0.0.1:%d/static/%s" % (port, name)
                stem = os.path.splitext(os.path.basename(md_path))[0]
                out = os.path.join(os.path.dirname(os.path.abspath(md_path)), stem + ".pdf")
                want = got = 0
                for budget in (30000, 60000, 120000):
                    want, got = _chromium_print_pdf(browser, url, out, budget)
                    if want and want == got:
                        break
                if not (want and want == got):
                    try:
                        if os.path.exists(out):
                            os.remove(out)
                    except Exception:
                        pass
                    self._send(500, json.dumps({"ok": False,
                        "error": "分页未稳定（DOM %d 页 / PDF %d 页），未生成文件；"
                                 "请改用「打印」按钮" % (want, got)}, ensure_ascii=False))
                    return
                self._send(200, json.dumps({"ok": True, "path": out, "pages": got},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
```

同时在文件头 import 区确认 `shutil` 与 `tempfile` 已导入（`md_server.py` 已有）。`creationflags` 用字面量 `0x08000000`——与文件内既有两处（`_pick_file_subprocess` / `_pick_dir_subprocess`）写法一致。

- [ ] **Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_pdf.py`
Expected: ALL PASS（8 条）。若「页数 >= 2」不过，说明填充内容不够长——把 `BODY` 里的 `400` 调到 `800` 再跑。

- [ ] **Step 5: 回归（分页打印链路未受影响）**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_paged_e2e.py`（需 18766 有服务）
Expected: 47/47 PASS

- [ ] **Step 6: 提交**

```bash
git add md_server.py _test_pdf.py
git commit -m "feat: PDF 直出（headless Chromium 两趟法，页数校验防半截文件）"
```

---

### Task 5: 前端两个按钮 + 置灰 + 打开所在目录

**Files:**
- Modify: `markdown-editor.html`（工具栏、payload helper、事件、置灰逻辑）
- Modify: `md_server.py`（`GET /api/reveal`）
- Test: `_test_export_ui.py`

**Interfaces:**
- Consumes: `GET /api/tools`、`POST /api/export-docx`、`POST /api/export-pdf`
- Produces: 工具栏按钮 `#btnExportDocx` / `#btnExportPdf`；`GET /api/reveal?path=<abs path>` → `{ok}`（`explorer /select,`）

- [ ] **Step 1: 写失败的测试**

创建 `_test_export_ui.py`：

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""导出按钮的浏览器级回归（R2）：
- 工具栏出现「Word」「PDF」两个按钮
- 工具探测完成后按 found 决定是否 disable
- 未保存文档时点击给出「请先保存」提示，不发请求
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


EXPR = r"""
(function(){
  var d = document.getElementById('btnExportDocx');
  var p = document.getElementById('btnExportPdf');
  return new Promise(function(resolve){
    setTimeout(function(){
      var state = {docx: !!d, pdf: !!p,
                   docxDisabled: d ? d.disabled : null,
                   pdfDisabled: p ? p.disabled : null};
      if (p) p.click();
      setTimeout(function(){
        var t = document.querySelector('#mdToast');
        resolve(Object.assign(state, {toastText: t ? t.textContent : ''}));
      }, 600);
    }, 1500);
  });
})()
"""

if __name__ == "__main__":
    res = run_expr(EXPR)
    check("Word 按钮存在", res.get("docx") is True, str(res))
    check("PDF 按钮存在", res.get("pdf") is True, str(res))
    check("工具可用时按钮不置灰",
          res.get("docxDisabled") is False and res.get("pdfDisabled") is False,
          "docx=%r pdf=%r" % (res.get("docxDisabled"), res.get("pdfDisabled")))
    check("未保存文档点击给提示", "保存" in (res.get("toastText") or ""),
          res.get("toastText"))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_export_ui.py`
Expected: FAIL（按钮不存在）

- [ ] **Step 3: 实现前端**

① 工具栏（`markdown-editor.html` 的 `btnExportPaged` / `btnExportHtml` 之后）加：

```html
    <button id="btnExportDocx" class="tb-btn" title="导出 Word（.docx，公式转 Word 原生公式）">Word</button><button id="btnExportPdf" class="tb-btn" title="直接导出 PDF 文件（不开打印对话框）">PDF</button>
```

② 把打印按钮的 payload 构造抽成函数（放在 `openExternal` 附近）：

```javascript
  /* 分页类导出共用的请求体：打印 / PDF 直出都用它，避免两处各拼一份 */
  function pagedPayload(){
    var pv=document.getElementById('preview');
    return {
      path: currentFile,
      bodyHtml: pv?pv.innerHTML:'',
      docTitle: (frontMeta && frontMeta.title) || '',
      tsCss: (document.getElementById('ts-style')||{textContent:''}).textContent,
      cfg: (function(){try{return JSON.parse(localStorage.getItem('md-editor-typeset-v3')||'{}').page||{};}catch(e){return {};}})()
    };
  }
```

③ 事件与置灰：

```javascript
  /* ── Word / PDF 导出：外部工具可用才点亮 ────────────────────── */
  var toolState={docx:false,pdf:false};
  function applyToolState(){
    var d=document.getElementById('btnExportDocx'), p=document.getElementById('btnExportPdf');
    if(d){ d.disabled=!toolState.docx; d.title=toolState.docx?'导出 Word（.docx，公式转 Word 原生公式）':'未检测到 pandoc.exe，无法导出 Word'; }
    if(p){ p.disabled=!toolState.pdf;  p.title=toolState.pdf? '直接导出 PDF 文件（不开打印对话框）':'未检测到 Chromium 内核浏览器，无法直出 PDF；可用「打印」'; }
  }
  function probeTools(){
    fetch('/api/tools').then(function(r){return r.json();}).then(function(j){
      var t=(j&&j.tools)||{};
      toolState.docx=!!(t.pandoc&&t.pandoc.found);
      toolState.pdf=!!(t.browser&&t.browser.found);
      applyToolState();
    }).catch(function(){ applyToolState(); });
  }
  document.getElementById('btnExportDocx').addEventListener('click',function(){
    if(!currentFile){ showToast('请先保存文档再导出 Word'); return; }
    showToast('正在导出 Word…');
    fetch('/api/export-docx',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:currentFile, markdown:getText()})})
      .then(function(r){return r.json();})
      .then(function(j){
        if(j&&j.ok){ showToast('已导出：'+j.path, false,
          {label:'打开所在目录', fn:function(){ revealFile(j.path); }}); }
        else{ showToast('导出失败：'+((j&&j.error)||'未知错误')); }
      }).catch(function(e){ showToast('导出失败：'+e.message); });
  });
  document.getElementById('btnExportPdf').addEventListener('click',function(){
    if(!currentFile){ showToast('请先保存文档再导出 PDF'); return; }
    showToast('正在生成 PDF…');
    fetch('/api/export-pdf',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(pagedPayload())})
      .then(function(r){return r.json();})
      .then(function(j){
        if(j&&j.ok){ showToast('已导出 '+j.pages+' 页：'+j.path, false,
          {label:'打开所在目录', fn:function(){ revealFile(j.path); }}); }
        else{ showToast('导出失败：'+((j&&j.error)||'未知错误')); }
      }).catch(function(e){ showToast('导出失败：'+e.message); });
  });
  /* 打开所在目录：资源管理器里选中该文件（/api/reveal 只接受已存在路径） */
  function revealFile(p){
    fetch('/api/reveal?path='+encodeURIComponent(p))
      .then(function(r){return r.json();})
      .then(function(j){ if(!j||!j.ok){ showToast('打开失败：'+((j&&j.error)||'未知错误')); } })
      .catch(function(e){ showToast('打开失败：'+e.message); });
  }
```

在页面启动处（`render();updateStats();` 那一段之后）加一行 `probeTools();`。

`showToast` 已支持动作按钮（`opts.label` + `opts.fn`，见 `markdown-editor.html` 的 `.md-toast-act` 分支），无需扩展。

④ 后端加 `GET /api/reveal`（放在 `/api/open-external` 之后）：

```python
        if u.path == "/api/reveal":
            q = urllib.parse.parse_qs(u.query)
            target = q.get("path", [""])[0]
            if not target or not os.path.exists(target):
                self._send(400, json.dumps({"ok": False, "error": "路径不存在"},
                                           ensure_ascii=False))
                return
            try:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target)],
                                 creationflags=NO_WINDOW)
                self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_export_ui.py`
Expected: ALL PASS（4 条）

- [ ] **Step 5: 提交**

```bash
git add markdown-editor.html md_server.py _test_export_ui.py
git commit -m "feat: 工具栏 Word / PDF 导出按钮（工具缺失置灰），/api/reveal 打开所在目录"
```

---

### Task 6: 文档、版本号与全量回归

**Files:**
- Modify: `CHANGELOG.md`、`README.md`、`docs/MDEditor 使用指南.md`、`docs/分发清单.md`、`md_server.py`（`MD_SERVER_VERSION` 55→56）

- [ ] **Step 1: 版本号**

`MD_SERVER_VERSION = 56`。

- [ ] **Step 2: CHANGELOG v2.2.0**

按仓库体例（现象/根因/修法/验证）写条目，必须覆盖：两条新出口、依赖与降级、两条 Critical 级实现约束（PDF 页数校验、`.smd` 工作目录）、测试证据。

- [ ] **Step 3: README / 使用指南 / 分发清单**

- README 功能速览补：「**导出**：`.md` / `.html`（带排版与公式）/ 分页 HTML（Ctrl+P 存 PDF）/ **Word（.docx，公式为 Word 原生公式，需 pandoc）** / **PDF 直出文件（需 Edge/Chrome）**」；文件清单补 `md_tools.py`、`md_pandoc.py`。
- 使用指南「保存与导出」章补两小节：Word 导出（依赖 pandoc、公式如何落地、Callout 如何呈现为引用块）、PDF 直出（依赖浏览器、与「打印」的区别、页数校验失败时怎么办）。
- 分发清单：核心功能表补 `md_tools.py` / `md_pandoc.py` 两行（缺失后果：Word/PDF 导出不可用，其余不变）；「环境前提」补 pandoc 与 Chromium 浏览器。

- [ ] **Step 4: 全量回归**

Run: 逐文件跑全部 `_test_*.py`（沿用 R1 的 `full_regression.py` 思路，跳过 5 个 playwright 用例；外部服务用例单独跑）
Expected: 全 PASS（`_test_rag_e2e.py` 例外，环境依赖已登记）

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "docs: v2.2.0 发布说明（Word / PDF 导出），服务版本 56"
```

---

## 附录：规格对照（自审）

| 规格条目 | 落点任务 |
|---|---|
| §5.1 Word `.docx`（pandoc 通道） | Task 2（预处理 + 调用）+ Task 3（路由） |
| §5.2 PDF 直出（两趟法 + 页数校验 + 预算序列） | Task 4 |
| §5.3 三个按钮的关系（打印保留 / PDF / Word） | Task 5 |
| §4.7 复制按钮不进导出 | R1 已完成（服务端剥离，两条出口共用） |
| §7.1 统一探测（pandoc / 浏览器 / R / quarto） | Task 1（R4 复用同一模块） |
| §7.2 `/api/tools` | Task 1（`PUT` 与设置面板属 R4） |
| §7.4 降级矩阵（pandoc / 浏览器缺失） | Task 1 + Task 5 |
| §8 测试策略 | `_test_tools.py` / `_test_pandoc_prep.py` / `_test_docx.py` / `_test_pdf.py` / `_test_export_ui.py` |
| §9 文档与分发 | Task 6 |
| 风险：外部依赖不自带 | Task 1 探测 + Task 5 置灰 + Task 6 文档 |
| 风险：分页未完成导致半截 PDF | Task 4 两趟法 + 预算重试 |
