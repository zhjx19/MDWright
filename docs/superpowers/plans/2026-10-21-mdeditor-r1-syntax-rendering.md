# MDEditor R1 语法与渲染 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 MDEditor 补齐脚注、提示块 Callout、行内高亮/上下标、定义列表、YAML front matter 五类 Markdown 语法，并加入代码语法高亮（highlight.js）与代码块复制按钮——预览、独立 HTML 导出、分页导出三处渲染保持同源。

**Architecture:** 语法解析全部落在前端单页的 `/*PARSER_START*/…/*PARSER_END*/` 段内（该段可被 node 抽出单测）；脚注与 front matter 是**文档级**语义，在 `render()` 入口先做全文提取，再把上下文（`fx`）逐层传进 `parseMarkdown`/`parseInline`/`parseList`/`parseTable`。代码高亮用 highlight.js vendor 就地分发、前端懒加载、着色结果留在 DOM 里，服务端导出只需注入主题 CSS（无需内联 120KB JS）。

**Tech Stack:** 原生 HTML/CSS/JS 单页（无构建步骤）、Python 3.11 标准库后端、Node 24（仅用于抽解析器跑单测 + CDP 浏览器测试）、highlight.js 11.11.1（vendor，BSD-3-Clause）

**Spec:** `docs/superpowers/specs/2026-10-21-mdeditor-capability-expansion-design.md`（§4 R1 语法与渲染设计 / §8 测试策略 / §9 文档与分发）

## Global Constraints

- **零新增依赖**：前端不引入 npm 包、后端不引入 pip 包；第三方产物一律 vendor 就地分发（沿用 mermaid/viz/wavedrom/vega 的既有模式）。
- **后端仅标准库**：代码须在**内嵌便携运行时**（`python/python.exe`，Python 3.11.9）下可运行，不得使用 3.12+ 语法。
- **许可登记**：highlight.js 是 **BSD-3-Clause**（不是 MIT），须在 `LICENSES/`、`docs/版权与开源组件声明.md`、`docs/分发清单.md` 三处登记。
- **不破坏既有行为**：既有 22 个 `_test_*.py` 必须全绿；`_test_img_width.py` 断言的 `class="lang-python {30}"` 字面保留语义不得改动。
- **注释与提交风格**：中文注释，交代「为什么」；提交信息中文、动词开头、一行摘要。
- **每个任务结束提交一次**（`git commit`），提交前必须跑该任务的测试 + 相关回归。
- **测试运行环境**：Windows。Python 用 `D:\py_base_env\.venv\Scripts\python.exe`（无 playwright，改用本计划自建的 CDP 基建）；Node 用 PATH 上的 node 24。
- **端口**：既有测试占用 18766；本计划新增的浏览器测试一律用 **18777**，互不干扰。
- **服务版本号**：`MD_SERVER_VERSION` 当前为 54；仅在 Task 10 递增一次（54 → 55），触发旧页面自愈刷新。

## Review Focus

规格暗示、但任何单个任务的测试都可能漏掉、且最容易咬到真实用户的五类输入——每条都在下方对应任务里有断言：

1. **脚注引用与定义分处不同块**（`splitBlocks` 按 H1/H2 切块，引用在第 3 块、定义在第 7 块）——仍须成对出现，且编号按全文引用序。→ Task 2
2. **未定义的脚注引用** `[^x]`（无对应 `[^x]:`）——必须保持字面原文，不得渲染成坏链接或吞掉。→ Task 2
3. **`~`/`^`/`==` 与既有语法的碰撞**：`~~删除线~~` 不得被拆成两个下标；行内代码 `` `a~b` `` 内的 `~` 不生效；URL 里的 `~` 不生效。→ Task 3
4. **front matter 未闭合 / YAML 非法 / 正文中间出现 `---`**——前两者整块按普通段落渲染（内容不丢），第三者仍当水平线。→ Task 5
5. **导出与预览不同源**：新语法若只加在预览样式里，独立 HTML 导出与分页导出会「裸奔」（callout 无色条、脚注无样式、`==高亮==` 无底色）——三处样式必须同步。→ Task 6

---

## File Structure

**新建**

| 文件 | 职责 |
|---|---|
| `_cdp.js` | Node 端 CDP 客户端：连调试端口 → 导航 → 求值 JS → 打印 JSON。零依赖（Node 24 内置 `fetch`/`WebSocket`） |
| `_test_browser.py` | 浏览器级测试脚手架：起本地服务 + headless 浏览器 + 调用 `_cdp.js` 取页面内求值结果 |
| `_test_footnote.py` | 脚注解析回归（node 抽解析器） |
| `_test_callout.py` | Callout 提示块回归（node 抽解析器） |
| `_test_inline_ext.py` | `==高亮==` / `^上标^` / `~下标~` 回归（node 抽解析器） |
| `_test_deflist.py` | 定义列表回归（node 抽解析器） |
| `_test_frontmatter.py` | YAML front matter 回归（node 抽解析器） |
| `_test_syntax_ui.py` | 浏览器级：脚注区落在预览末尾、Callout 实际 DOM、代码高亮 span 真实生成 |
| `_test_export_css.py` | 服务端级：独立 HTML / 分页 HTML 含新语法样式与 hljs 主题 CSS |
| `_test_copy_btn.py` | 浏览器级：复制按钮存在、点击写入剪贴板、导出产物不含按钮 |
| `highlight/highlight.min.js` | highlight.js 11.11.1 common 构建（vendor） |
| `highlight/styles/github.css` | 亮色主题（vendor） |
| `highlight/styles/github-dark.css` | 暗色主题（vendor） |
| `LICENSES/highlight.js-BSD-3-Clause.txt` | highlight.js 许可全文（BSD-3-Clause） |

**修改**

| 文件 | 改动 |
|---|---|
| `markdown-editor.html` | ① `<style>` 主块（9–178 行）加新语法样式；② 179 行后加 hljs 主题 `<link>`；③ PARSER 段（471–695）加 `extractFootnotes`/`buildFootnoteSection`/`extractFrontMatter`/`parseYamlLite`/`parseDefList`/`scalar`，改 `parseInline`/`parseMarkdown`/`parseList`/`parseTable` 签名与调用；④ UI 段加 `render()` 集成、`updateFootnoteBlock`、`highlightCode`、复制按钮事件 |
| `md_server.py` | ① `build_standalone_html` / `build_paged_html` 注入新语法 CSS + hljs 主题 CSS；② `MD_SERVER_VERSION` 54→55 |
| `CHANGELOG.md` | 加 v2.1.0 条目（按仓库体例：现象/根因/修法/验证） |
| `README.md` | 功能速览补新语法与代码高亮；核心文件清单补 `highlight/` |
| `docs/MDEditor 使用指南.md` | 语法速查补五类新语法 + 代码高亮说明 |
| `docs/分发清单.md` | 补 highlight.js 行与最小分发集 |
| `docs/版权与开源组件声明.md` | 组件表补 highlight.js（BSD-3-Clause） |

---

### Task 1: 浏览器测试基建（CDP over Node 内置 WebSocket）

本机**未安装 playwright**（既有 `_test_list_ui.py` / `_test_outline_jump.py` 在本机跑不了）。本任务自建零安装的浏览器级测试通道，R1 后续任务与 R2/R4 均复用。

**Files:**
- Create: `_cdp.js`
- Create: `_test_browser.py`
- Test: 自检脚本（本任务内联运行 `_test_browser.py` 的 `--selftest`）

**Interfaces:**
- Consumes: `md_server.ReuseTCPServer`、`md_server.Handler`（`md_server.py:457`、`md_server.py:464`）；本机 Chrome/Edge 可执行文件
- Produces:
  - `_cdp.js` CLI：`node _cdp.js <debugPort> <url> <exprFile>` → stdout 末行是求值结果的 JSON 字符串
  - `_test_browser.py` API：
    - `start_server(port=18777) -> httpd`
    - `find_browser() -> str|None`
    - `class Browser`：`__init__(self)`、`eval(self, expr, url) -> Any`（返回 JSON 解码后的值）、`close(self)`
    - `run_expr(expr, url, port=18777) -> Any`（一次性便捷函数：自起服务与浏览器）

**Step 1: 写 `_cdp.js`**

创建 `_cdp.js`：

```javascript
/* CDP 客户端（Node 24 内置 fetch/WebSocket，零依赖）
   用法：node _cdp.js <debugPort> <url> <exprFile>
   行为：连调试端口 → 打开/复用 page target → 等 load → 求值 expr → stdout 末行打印 JSON */
'use strict';
const fs = require('fs');

const debugPort = process.argv[2];
const url = process.argv[3];
const exprFile = process.argv[4];
if (!debugPort || !url || !exprFile) {
  console.error('usage: node _cdp.js <debugPort> <url> <exprFile>');
  process.exit(2);
}
const expr = fs.readFileSync(exprFile, 'utf-8');

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function waitForDevtools(port, tries) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch('http://127.0.0.1:' + port + '/json/version');
      if (r.ok) return true;
    } catch (e) { /* 还没起来 */ }
    await sleep(150);
  }
  return false;
}

async function pickPage(port) {
  const list = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
  let page = list.find(t => t.type === 'page');
  if (!page) {
    const r = await fetch('http://127.0.0.1:' + port + '/json/new?' + encodeURIComponent('about:blank'),
                          { method: 'PUT' });
    page = await r.json();
  }
  return page;
}

async function main() {
  if (!await waitForDevtools(debugPort, 120)) {
    throw new Error('devtools port ' + debugPort + ' not reachable');
  }
  const page = await pickPage(debugPort);
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let msgId = 0;
  const pending = new Map();
  const listeners = [];
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      if (m.error) p.reject(new Error(JSON.stringify(m.error)));
      else p.resolve(m.result);
      return;
    }
    listeners.slice().forEach(fn => fn(m));
  });
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', reject);
  });
  const send = (method, params) => new Promise((resolve, reject) => {
    const id = ++msgId;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id: id, method: method, params: params || {} }));
  });

  await send('Page.enable');
  await send('Runtime.enable');
  const loaded = new Promise(resolve => {
    const fn = m => {
      if (m.method === 'Page.loadEventFired') {
        listeners.splice(listeners.indexOf(fn), 1);
        resolve();
      }
    };
    listeners.push(fn);
  });
  await send('Page.navigate', { url: url });
  await loaded;
  await sleep(900);                     /* 等前端 render() 与 vendor 懒加载落地 */
  const out = await send('Runtime.evaluate', {
    expression: expr,
    awaitPromise: true,
    returnByValue: true
  });
  if (out.exceptionDetails) {
    throw new Error('page exception: ' + JSON.stringify(out.exceptionDetails).slice(0, 400));
  }
  const value = out.result && out.result.value !== undefined ? out.result.value : null;
  console.log(JSON.stringify(value));
  ws.close();
}

main().catch(e => {
  console.error('CDP_ERROR ' + (e && e.message ? e.message : String(e)));
  process.exit(1);
});
```

**Step 2: 写 `_test_browser.py`**

创建 `_test_browser.py`：

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""浏览器级测试脚手架（R1 新增，替代未安装的 playwright）：
起本地服务 + headless 浏览器，经 CDP 在页面里求值 JS，取回 JSON 结果。
- 零安装：Node 24 内置 WebSocket 直连 Chrome/Edge 调试端口
- 端口 18777（与既有 18766 隔离，可并行）
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 18777
CDP_PORT = 9333

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser():
    """定位本机 Chromium 内核浏览器；找不到返回 None。"""
    for b in BROWSERS:
        if os.path.exists(b):
            return b
    return None


def port_in_use(port):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def start_server(port=PORT):
    """起一个进程内 md_server；端口已被占用则复用现有服务。"""
    if port_in_use(port):
        return None
    sys.argv = ["md_server.py"]
    sys.path.insert(0, HERE)
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", port), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    return httpd


class Browser(object):
    """headless 浏览器 + CDP 求值通道。"""

    def __init__(self):
        exe = find_browser()
        if not exe:
            raise RuntimeError("no chromium browser found")
        self.prof = tempfile.mkdtemp(prefix="mdcdp-")
        self.proc = subprocess.Popen(
            [exe, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--remote-debugging-port=%d" % CDP_PORT,
             "--user-data-dir=%s" % self.prof, "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(120):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/json/version" % CDP_PORT, timeout=1).read()
                break
            except Exception:
                time.sleep(0.15)

    def eval(self, expr, url="http://127.0.0.1:%d/" % PORT):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(expr)
            path = f.name
        try:
            r = subprocess.run(["node", os.path.join(HERE, "_cdp.js"), str(CDP_PORT), url, path],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
        finally:
            if os.path.exists(path):
                os.remove(path)
        if r.returncode != 0:
            raise RuntimeError("cdp failed: " + (r.stderr or r.stdout or "")[:500])
        lines = [ln for ln in (r.stdout or "").strip().splitlines() if ln.strip()]
        if not lines:
            raise RuntimeError("cdp produced no output")
        return json.loads(lines[-1])

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def run_expr(expr, url="http://127.0.0.1:%d/" % PORT, port=PORT):
    """一次性：起服务 + 浏览器 → 求值 → 关停。"""
    httpd = start_server(port)
    b = Browser()
    try:
        return b.eval(expr, url)
    finally:
        b.close()
        if httpd:
            httpd.shutdown()
            httpd.server_close()      /* 必须 close，否则端口占用残留，下一次起服务会失败 */


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        got = run_expr("document.title")
        print("SELFTEST title=%r" % (got,))
        sys.exit(0 if got else 1)
    print(__doc__)
```

**Step 3: 跑自检**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_browser.py --selftest`
Expected: 打印 `SELFTEST title='…'` 且退出码 0（能取到页面标题即通道打通）

若报 `no chromium browser found`：本机确实没有 Chrome/Edge → 停在这里向用户报告，不要跳过本任务。

**Step 4: 提交**

```bash
git add _cdp.js _test_browser.py
git commit -m "test: 新增 CDP 浏览器测试基建（零安装，替代未安装的 playwright）"
```

---

### Task 2: 脚注（文档级）

**Files:**
- Modify: `markdown-editor.html` — PARSER 段（471–695 行）：新增 `extractFootnotes`、`buildFootnoteSection`；改 `parseInline(text, fx)`、`parseMarkdown(src, fx)`、`parseList(..., fx)`、`parseTable(..., fx)` 签名与全部调用点；UI 段 `render()`（1041 行）集成
- Test: `_test_footnote.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `_test_browser.py`（浏览器级用例）
- Produces:
  - `extractFootnotes(src) -> {src, defs:{label:{text}}, nums:{label:num}, order:[label]}`
  - `buildFootnoteSection(fx) -> string`（空则返回 `''`）
  - `parseMarkdown(src, fx)` 第二参可选；`parseInline(text, fx)` 第二参可选（既有调用不改即兼容）

**Step 1: 写失败的测试**

创建 `_test_footnote.py`（沿用 `_test_list_parse.py` 的抽段跑 node 体例）：

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""脚注解析回归（R1）：
- 编号按【引用首次出现顺序】（用户 2026-10-21 决定）
- 未定义的引用保持字面，不渲染成坏链接
- 定义行剥离出正文，文末生成脚注区
- 定义可多行（续行缩进 4 空格），空行终止
- 引用与定义可分处不同块（文档级语义）
前端部分从 markdown-editor.html 提取 /*PARSER_START*/../*PARSER_END*/ 段跑 node。
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "markdown-editor.html")
JS = os.path.join(HERE, "_tmp_footnote.js")
RESULTS = []


def check(name, ok, extra=""):
    RESULTS.append((name, ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" | " + extra) if extra else ""))


def main():
    src = open(HTML, encoding="utf-8").read()
    m = re.search(r"/\*PARSER_START\*/(.*?)/\*PARSER_END\*/", src, re.S)
    if not m:
        print("FAIL parser segment not found")
        sys.exit(1)
    harness = m.group(1) + r"""
function doc(src){
  var fx = extractFootnotes(src);
  return { body: parseMarkdown(fx.src, fx), fx: fx, sec: buildFootnoteSection(fx) };
}
var CASES = [
  ["基本引用+定义",
   "正文[^a]。\n\n[^a]: 说明文字",
   { ref: '<sup class="fn-ref"><a href="#fn-1" id="fnref-1">1</a></sup>',
     sec: '说明文字' }],
  ["编号按引用序(定义顺序相反)",
   "甲[^b]乙[^a]\n\n[^a]: A\n[^b]: B",
   { refs: ['1', '2'], bText: 'B', aText: 'A' }],
  ["未定义引用保持字面",
   "看这个[^missing]就行",
   { literal: '[^missing]' }],
  ["定义行不进正文",
   "正文\n\n[^a]: 说明",
   { bodyHas: false }],
  ["多行定义",
   "正文[^a]\n\n[^a]: 第一行\n    第二行",
   { secHas: '第二行' }],
  ["代码块内的引用不生效",
   "```\n[^a]\n```\n\n[^a]: 说明",
   { literalInCode: true }],
  ["重复引用同一标签共用编号",
   "x[^a] y[^a]\n\n[^a]: 说明",
   { sameNum: true }]
];
var fails = 0;
function report(name, ok, detail){
  if(!ok) fails++;
  console.log((ok?'PASS ':'FAIL ')+name+(ok?'':' | '+detail));
}
/* 1 */
var r = doc(CASES[0][1]);
report('基本引用+定义', r.body.indexOf(CASES[0][2].ref) >= 0 && r.sec.indexOf(CASES[0][2].sec) >= 0,
       'body='+r.body+' sec='+r.sec);
/* 2 */
r = doc(CASES[1][1]);
var refs = (r.body.match(/fnref-(\d+)/g)||[]).map(function(s){return s.replace('fnref-','');});
report('编号按引用序', refs.join(',') === '1,2', 'refs='+refs.join(','));
report('定义内容对应编号', r.sec.indexOf('B') >= 0 && r.sec.indexOf('A') >= 0, r.sec);
/* 3 */
r = doc(CASES[2][1]);
report('未定义引用保持字面', r.body.indexOf('[^missing]') >= 0 && r.body.indexOf('fn-ref') < 0, r.body);
/* 4 */
r = doc(CASES[3][1]);
report('定义行不进正文', r.body.indexOf('[^a]:') < 0, r.body);
/* 5 */
r = doc(CASES[4][1]);
report('多行定义', r.sec.indexOf('第二行') >= 0, r.sec);
/* 6 */
r = doc(CASES[5][1]);
report('代码块内引用不生效', r.body.indexOf('[^a]') >= 0, r.body);
/* 7 */
r = doc(CASES[6][1]);
var nums = (r.body.match(/fnref-(\d+)/g)||[]);
report('重复引用共用编号', nums.length===2 && nums[0]===nums[1], nums.join(','));
process.exit(fails ? 1 : 0);
"""
    open(JS, "w", encoding="utf-8").write(harness)
    r = subprocess.run(["node", JS], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=HERE)
    out = (r.stdout or "") + (r.stderr or "")
    lines = [ln for ln in out.splitlines() if ln.startswith(("PASS", "FAIL"))]
    for ln in lines:
        check(ln[5:].strip().split(" | ")[0], ln.startswith("PASS"))
    if not lines:
        print("FAIL node harness did not run (rc=%s)\n%s" % (r.returncode, out.strip()[:500]))
        if os.path.exists(JS):
            os.remove(JS)
        sys.exit(1)
    fails_detail = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
    if fails_detail:
        print("\n".join(out.splitlines()))
    if os.path.exists(JS):
        os.remove(JS)
    fails = [n for n, ok in RESULTS if not ok]
    print("\n%d/%d passed" % (len(RESULTS) - len(fails), len(RESULTS)))
    if fails:
        print("FAILED:", "; ".join(fails))
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_footnote.py`
Expected: FAIL（`extractFootnotes is not defined` 或类似 ReferenceError）

**Step 3: 实现解析层**

在 `markdown-editor.html` 的 `/*PARSER_START*/` 段内，`escapeHtml` 之前插入以下函数（顺序：`extractFootnotes` → `buildFootnoteSection` → 既有 `escapeHtml`/`parseInline`…）：

```javascript
/* ── 脚注（文档级）────────────────────────────────────────────────
   语法：正文 [^label] 引用；文档任意处 [^label]: 说明 定义。
   编号：按【引用首次出现顺序】（2026-10-21 用户决定）；无定义的引用保持字面。
   定义行剥离出正文，文末由 buildFootnoteSection 生成脚注区。 */
function extractFootnotes(src){
  var lines=src.split('\n'), kept=[], defs={}, i=0, fence=false;
  while(i<lines.length){
    var ln=lines[i];
    if(/^\s*(```|~~~)/.test(ln))fence=!fence;
    var m=(!fence)?ln.match(/^\[\^([^\]\s]+)\]:[ ]?(.*)$/):null;
    if(m){
      var label=m[1], body=m[2], buf=[];
      i++;
      while(i<lines.length){
        var nx=lines[i];
        if(/^[ ]*$/.test(nx))break;                    /* 空行终止该定义 */
        if(/^ {4}\S/.test(nx)){buf.push(nx.replace(/^ {4}/,''));i++;continue;}
        break;
      }
      if(body)buf.unshift(body);
      if(!(label in defs))defs[label]={text:buf.join('\n')};
      continue;                                       /* 定义行不进正文 */
    }
    kept.push(ln); i++;
  }
  var clean=kept.join('\n'), nums={}, order=[], re=/\[\^([^\]\s]+)\]/g, mm;
  while((mm=re.exec(clean))!==null){
    var lb=mm[1];
    if(!(lb in defs))continue;                        /* 无定义 → 字面保留 */
    if(!(lb in nums)){nums[lb]=order.length+1;order.push(lb);}
  }
  return {src:clean, defs:defs, nums:nums, order:order};
}
function buildFootnoteSection(fx){
  if(!fx||!fx.order.length)return '';
  var items=[];
  for(var i=0;i<fx.order.length;i++){
    var lb=fx.order[i], n=fx.nums[lb];
    items.push('<li id="fn-'+n+'">'+parseInline(fx.defs[lb].text)+
      ' <a href="#fnref-'+n+'" class="fn-back" title="返回正文">↩</a></li>');
  }
  return '<section class="footnotes"><hr class="fn-sep"><ol>'+items.join('')+'</ol></section>';
}
```

把 `parseInline` 的签名改为 `function parseInline(text, fx){`，并在**链接占位之后、加粗/斜体之前**插入脚注引用处理：

```javascript
  /* 脚注引用（文档级上下文 fx 提供 label→编号）；无定义则保持字面 */
  if(fx&&fx.nums){
    text=text.replace(/\[\^([^\]\s]+)\]/g,function(m,lb){
      var n=fx.nums[lb];
      if(!n)return m;
      toks.push('<sup class="fn-ref"><a href="#fn-'+n+'" id="fnref-'+n+'">'+n+'</a></sup>');
      return '\x00T'+(toks.length-1)+'\x00';
    });
  }
```

把 `parseList` 改为 `function parseList(lines,start,indent,seq,fx){`，其内两处 `parseInline(...)` 调用补 `, fx`：
- `html+='<li class="task">…'+parseInline(tm[2],fx)+it.children+'</li>';`
- `html+='<li'+icls+'>'+parseInline(it.raw,fx)+it.children+'</li>';`

把 `parseTable` 改为 `function parseTable(lines,start,fx){`，其内 `parseInline(c)` / `parseInline(c)` 两处补 `, fx`。

把 `parseMarkdown` 改为 `function parseMarkdown(src, fx){`，其内调用点补 `fx`：
- 标题：`parseInline(hm[2].trim(), fx)`
- 引用块：`parseMarkdown(quote.join('\n'), fx)`
- 表格：`var t=parseTable(lines,i,fx);`
- 列表：`var lst=parseList(lines,i,ind,olSeq,fx);`
- 段落：`parseInline(para.join('\n'), fx)`

**Step 4: 接入 `render()`（文档级集成）**

在 UI 段 `render()`（1041 行）中，把开头改为：

```javascript
  function render(){
    buildMirrorMap();   /* 镜像测量表只依赖编辑器内容与排版，任何内容变化必经此处 */
    var src=extractMath(getText());
    var fx=extractFootnotes(src);        /* 脚注：定义剥离 + 引用序编号 */
    src=fx.src;
    var fnSig=JSON.stringify(fx.nums);   /* 编号变化 → 全文重渲（块内含脚注引用）*/
    var blocks=splitBlocks(src);
```

把块哈希改成含 `fnSig`（两处都要改，否则缓存判定与写入不一致）：

```javascript
      var h=blkHash(blocks[i]+'\u0000'+fnSig);
      if(node && node.getAttribute('data-h')===h) continue;
```
```javascript
      div.setAttribute('data-h', blkHash(q.blocks[bi]+'\u0000'+q.fnSig));
```

在渲染队列里携带 `fnSig`，并在队列排空处追加脚注区：

```javascript
    var q={changed:changed, blocks:blocks, existing:existing, idx:0, startLines:startLines, fnSig:fnSig};
```
```javascript
      if(bi===undefined){ renderQueue=null; updateFootnoteBlock(fx); tagAnchorLines(q.blocks,q.startLines); buildOutline(); return; }
```

在 UI 段新增（紧跟 `render()` 之后）：

```javascript
  /* 脚注区：独立于 .pblk 序列（增量渲染的块集合不含它），追加在预览末尾。
     定义或编号变化时整体重绘；公式占位符同样要还原。 */
  function updateFootnoteBlock(fx){
    var html=buildFootnoteSection(fx);
    var el=preview.querySelector('.fnblk');
    if(!html){ if(el)el.parentNode.removeChild(el); return; }
    if(!el){ el=document.createElement('div'); el.className='fnblk'; preview.appendChild(el); }
    el.setAttribute('data-h','fn:'+blkHash(html));
    el.innerHTML=html;
    restoreMath(el);
    fixLocalImages(el);
  }
```

**Step 5: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_footnote.py`
Expected: 全部 PASS（7/7）

**Step 6: 回归**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_list_parse.py` 与 `_test_escape.py` 与 `_test_img_width.py`
Expected: 全部 PASS（20/20、11/11、6/6）

**Step 7: 提交**

```bash
git add markdown-editor.html _test_footnote.py
git commit -m "feat: 脚注语法（文档级，编号按引用首次出现顺序）"
```

---

### Task 3: Callout 提示块

**Files:**
- Modify: `markdown-editor.html` — PARSER 段 `parseMarkdown` 的引用块分支
- Test: `_test_callout.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `parseMarkdown(src, fx)`（fx 透传）
- Produces: 渲染形如 `<div class="callout callout-note"><p class="callout-title">NOTE</p>…</div>`；类型集合 `NOTE/TIP/IMPORTANT/WARNING/CAUTION`

**Step 1: 写失败的测试**

创建 `_test_callout.py`（体例同 `_test_footnote.py`，把抽段与 check 框架照抄，harness 部分替换为）：

```javascript
var CASES = [
  ["NOTE", "> [!NOTE]\n> 内容", 'callout-note', 'NOTE'],
  ["TIP", "> [!TIP]\n> 内容", 'callout-tip', 'TIP'],
  ["IMPORTANT", "> [!IMPORTANT]\n> 内容", 'callout-important', 'IMPORTANT'],
  ["WARNING", "> [!WARNING]\n> 内容", 'callout-warning', 'WARNING'],
  ["CAUTION", "> [!CAUTION]\n> 内容", 'callout-caution', 'CAUTION'],
  ["带标题", "> [!NOTE] 自定义标题\n> 内容", 'callout-note', '自定义标题'],
  ["普通引用不受影响", "> 普通引用", '<blockquote>', null]
];
var fails = 0;
for (var i=0;i<CASES.length;i++){
  var out = parseMarkdown(CASES[i][1]);
  var ok = out.indexOf('callout-'+CASES[i][2]) >= 0 &&
           (CASES[i][3]===null || out.indexOf('>'+CASES[i][3]+'<') >= 0);
  if(!ok){ fails++; console.log('FAIL '+CASES[i][0]+' -> '+out); }
  else console.log('PASS '+CASES[i][0]);
}
process.exit(fails ? 1 : 0);
```

**Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_callout.py`
Expected: FAIL（普通引用块，无 callout 类名）

**Step 3: 实现**

把 `parseMarkdown` 的引用块分支（原 670–675 行）替换为：

```javascript
    if(/^[ ]*>/.test(line)){
      var quote=[];
      while(i<lines.length && /^[ ]*>/.test(lines[i])){quote.push(lines[i].replace(/^[ ]*>[ ]?/,''));i++;}
      /* Callout：引用块首行形如 [!NOTE]（可带标题）→ 提示块容器 */
      var cm=(quote[0]||'').match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ ]*(.*)$/);
      if(cm){
        var kind=cm[1].toLowerCase(), ctitle=cm[2]||cm[1];
        html+='<div class="callout callout-'+kind+'"><p class="callout-title">'+parseInline(ctitle, fx)+'</p>'+
              parseMarkdown(quote.slice(1).join('\n'), fx)+'</div>';
      } else {
        html+='<blockquote>'+parseMarkdown(quote.join('\n'), fx)+'</blockquote>';
      }
      olSeq=0;
      continue;
    }
```

**Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_callout.py`
Expected: 7/7 PASS

**Step 5: 回归 + 提交**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_footnote.py`
Expected: 全 PASS

```bash
git add markdown-editor.html _test_callout.py
git commit -m "feat: Callout 提示块（NOTE/TIP/IMPORTANT/WARNING/CAUTION 五型）"
```

---

### Task 4: 行内高亮 / 上标 / 下标

**Files:**
- Modify: `markdown-editor.html` — PARSER 段 `parseInline`
- Test: `_test_inline_ext.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `parseInline(text, fx)`
- Produces: `==x==` → `<mark>x</mark>`；`^x^` → `<sup>x</sup>`；`~x~` → `<sub>x</sub>`

**Step 1: 写失败的测试**

创建 `_test_inline_ext.py`（体例同 `_test_footnote.py`，harness 替换为）：

```javascript
var CASES = [
  ["高亮", "==重点==", "<mark>重点</mark>"],
  ["上标", "x^2^", "x<sup>2</sup>"],
  ["下标", "H~2~O", "H<sub>2</sub>O"],
  ["删除线优先于下标", "~~删~~", "<del>删</del>"],
  ["删除线不被拆成下标", "~~x~~", "<del>x</del>"],
  ["代码段内的波浪号不生效", "`a~b`", "<code>a~b</code>"],
  ["URL 里的波浪号不生效", "[l](http://a.com/~x)", '<a href="http://a.com/~x"'],
  ["高亮可含中文与空格外符号", "==中文==", "<mark>中文</mark>"]
];
var fails = 0;
for (var i=0;i<CASES.length;i++){
  var out = parseInline(CASES[i][1]);
  var ok = out.indexOf(CASES[i][2]) >= 0;
  if(!ok){ fails++; console.log('FAIL '+CASES[i][0]+' -> '+out+' (expect '+CASES[i][2]+')'); }
  else console.log('PASS '+CASES[i][0]);
}
process.exit(fails ? 1 : 0);
```

**Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_inline_ext.py`
Expected: FAIL（无 `<mark>`/`<sub>`）

**Step 3: 实现**

在 `parseInline` 中，**紧接删除线规则之后**（即 `~~([^~]+)~~` 那行后面）插入三条规则：

```javascript
  /* 行内扩展（顺序敏感）：删除线必须先于下标，否则 ~~x~~ 会被拆成两个下标；
     上下标内容不含空白与自身定界符（Word 语义：上下标内不排空格） */
  text=text.replace(/==([^=]+)==/g,'<mark>$1</mark>');
  text=text.replace(/\^([^\s^]+)\^/g,'<sup>$1</sup>');
  text=text.replace(/~([^\s~]+)~/g,'<sub>$1</sub>');
```

> 说明：删除线规则原为 `text.replace(/~~([^~]+)~~/g,'<del>$1</del>');`，位于加粗/斜体之后。三条新规则插在它**之后**即可满足「删除线优先」；若实测发现 `~~x~~` 被拆开，把删除线规则一并移到三条新规则**之前**即可。

**Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_inline_ext.py`
Expected: 8/8 PASS

若「删除线不被拆成下标」FAIL：把删除线规则移到新规则之前，重跑。

**Step 5: 回归 + 提交**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_escape.py` 与 `_test_list_parse.py`
Expected: 全 PASS（转义与列表语义未被行内扩展影响）

```bash
git add markdown-editor.html _test_inline_ext.py
git commit -m "feat: 行内高亮 ==x== 与上下标 ^x^ ~x~"
```

---

### Task 5: 定义列表

**Files:**
- Modify: `markdown-editor.html` — PARSER 段新增 `parseDefList`，改 `parseMarkdown` 的段落分支
- Test: `_test_deflist.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `parseMarkdown(src, fx)`
- Produces: 渲染形如 `<dl><dt>术语</dt><dd>定义</dd></dl>`

**Step 1: 写失败的测试**

创建 `_test_deflist.py`（体例同 `_test_footnote.py`，harness 替换为）：

```javascript
var CASES = [
  ["基本定义列表", "术语\n: 定义", "<dl><dt>术语</dt><dd>定义</dd></dl>"],
  ["多条定义", "术语\n: 定义一\n: 定义二", "<dd>定义一</dd><dd>定义二</dd>"],
  ["多行定义(缩进续行)", "术语\n: 第一行\n    第二行", "第二行"],
  ["定义后接普通段落不吞", "术语\n: 定义\n普通段落", "普通段落"],
  ["行首冒号但下一行非定义 → 普通段落", "普通\n: 单独一行", ": 单独一行"]
];
var fails = 0;
for (var i=0;i<CASES.length;i++){
  var out = parseMarkdown(CASES[i][1]);
  var ok = out.indexOf(CASES[i][2]) >= 0;
  if(!ok){ fails++; console.log('FAIL '+CASES[i][0]+' -> '+out); }
  else console.log('PASS '+CASES[i][0]);
}
/* 定义后接普通段落：段落须独立成块，不得被并进 dd */
var o = parseMarkdown("术语\n: 定义\n普通段落");
if (o.indexOf('<p>普通段落</p>') < 0) { fails++; console.log('FAIL 段落独立 -> ' + o); }
else console.log('PASS 段落独立');
process.exit(fails ? 1 : 0);
```

**Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_deflist.py`
Expected: FAIL

**Step 3: 实现**

在 PARSER 段新增函数（放在 `parseTable` 之后）：

```javascript
/* 定义列表：术语行 + 后续以 ": " 开头的定义行（可多条）；
   定义的续行缩进 4 空格。渲染为 <dl><dt><dd>。 */
function parseDefList(lines,start,fx){
  var term=lines[start].trim(), defs=[], i=start+1;
  while(i<lines.length && /^[ ]*:[ ]+/.test(lines[i])){
    var buf=[lines[i].replace(/^[ ]*:[ ]+/,'')], i0=i+1;
    i=i0;
    while(i<lines.length && /^[ ]{4,}\S/.test(lines[i]) && !/^[ ]*:[ ]+/.test(lines[i])){
      buf.push(lines[i].replace(/^[ ]{4}/,'')); i++;
    }
    defs.push(buf.join('\n'));
  }
  if(!defs.length)return null;
  var html='<dl><dt>'+parseInline(term,fx)+'</dt>'+
    defs.map(function(d){return '<dd>'+parseInline(d,fx)+'</dd>';}).join('')+'</dl>';
  return {html:html, next:i};
}
```

在 `parseMarkdown` 的**段落分支之前**插入定义列表判定：

```javascript
    /* 定义列表：当前行是术语、下一行是 ": " 定义 */
    if(i+1<lines.length && /^[ ]*:[ ]+/.test(lines[i+1])){
      var dl=parseDefList(lines,i,fx);
      if(dl){ html+=dl.html; i=dl.next; olSeq=0; continue; }
    }
```

并把**段落分支的续行条件**加上「行首 `: ` 终止」，否则术语行会把定义吞成普通段落。在段落 `while` 条件末尾追加：

```javascript
 && !/^[ ]*:[ ]+/.test(lines[i])
```

**Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_deflist.py`
Expected: 6/6 PASS

**Step 5: 回归 + 提交**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_list_parse.py`
Expected: 20/20 PASS（段落终止条件变更不得影响既有列表/段落语义）

```bash
git add markdown-editor.html _test_deflist.py
git commit -m "feat: 定义列表（术语 + : 定义）"
```

---

### Task 6: YAML front matter

**Files:**
- Modify: `markdown-editor.html` — PARSER 段新增 `extractFrontMatter`/`parseYamlLite`/`yamlScalar`；`render()` 已在 Task 2 调用 `extractFrontMatter`（本任务落地实现）；导出 payload 增加 `docTitle`
- Test: `_test_frontmatter.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `render()` 接线（`extractFrontMatter(raw)` 已就位）
- Produces:
  - `extractFrontMatter(src) -> {src, meta}`（`meta` 为 `null` 表示无 front matter）
  - `parseYamlLite(text) -> object|null`（`null` = 解析失败，调用方按普通段落处理）
  - 导出请求体新增可选字段 `docTitle`（字符串）

**Step 1: 写失败的测试**

创建 `_test_frontmatter.py`（体例同 `_test_footnote.py`，harness 替换为）：

```javascript
var fails = 0;
function rep(name, ok, detail){ if(!ok)fails++; console.log((ok?'PASS ':'FAIL ')+name+(ok?'':' | '+detail)); }

/* 1 基本解析 */
var r = extractFrontMatter("---\ntitle: 我的文档\nauthor: zhang\n---\n\n正文");
rep('front matter 剥离', r.src.indexOf('---') < 0 && r.src.indexOf('正文') >= 0, JSON.stringify(r));
rep('title 解析', r.meta && r.meta.title === '我的文档', JSON.stringify(r.meta));
rep('author 解析', r.meta && r.meta.author === 'zhang', JSON.stringify(r.meta));

/* 2 嵌套 map 与列表 */
r = extractFrontMatter("---\ntags:\n  - a\n  - b\nmeta:\n  k: v\n---\n正文");
rep('列表解析', r.meta && Array.isArray(r.meta.tags) && r.meta.tags.join(',') === 'a,b', JSON.stringify(r.meta));
rep('嵌套 map 解析', r.meta && r.meta.meta && r.meta.meta.k === 'v', JSON.stringify(r.meta));

/* 3 标量 */
r = extractFrontMatter("---\nn: 42\nok: true\nnil: ~\ns: \"引号值\"\n---\n正文");
rep('数字/布尔/空/引号', r.meta && r.meta.n === 42 && r.meta.ok === true && r.meta.nil === null && r.meta.s === '引号值', JSON.stringify(r.meta));

/* 4 未闭合 → 当普通内容 */
r = extractFrontMatter("---\ntitle: x\n正文");
rep('未闭合不吞内容', r.meta === null && r.src.indexOf('title: x') >= 0, JSON.stringify(r));

/* 5 YAML 非法 → meta=null 但正文完整 */
r = extractFrontMatter("---\n这不是 yaml\n---\n正文");
rep('非法 YAML 降级', (r.meta === null || typeof r.meta === 'object') && r.src.indexOf('正文') >= 0, JSON.stringify(r));

/* 6 正文中间的 --- 仍是水平线 */
r = extractFrontMatter("正文\n\n---\n\n后文");
rep('非首行不触发', r.meta === null && r.src.indexOf('---') >= 0, JSON.stringify(r));

/* 7 首行 --- 但未闭合 */
r = extractFrontMatter("---\n正文没有结束");
rep('首行未闭合不触发', r.meta === null && r.src.indexOf('正文没有结束') >= 0, JSON.stringify(r));

process.exit(fails ? 1 : 0);
```

**Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_frontmatter.py`
Expected: FAIL（`extractFrontMatter is not defined`）

**Step 3: 实现**

在 PARSER 段新增（放在 `extractFootnotes` 之前）：

```javascript
/* ── YAML front matter（文档级）──────────────────────────────────
   仅文档第一行是 --- 时生效，到下一个 --- 或 ... 为止。
   支持极简子集：嵌套 map（缩进）、列表（- item）、标量。
   解析失败返回 null → 调用方整块按普通段落处理（fail-closed，不吞内容）。 */
function yamlScalar(v){
  var s=String(v==null?'':v).trim();
  if(s==='')return '';
  if((s.charAt(0)==='"'&&s.charAt(s.length-1)==='"')||(s.charAt(0)==="'"&&s.charAt(s.length-1)==="'"))return s.slice(1,-1);
  if(s==='true'||s==='True'||s==='TRUE')return true;
  if(s==='false'||s==='False'||s==='FALSE')return false;
  if(s==='null'||s==='Null'||s==='NULL'||s==='~')return null;
  if(/^-?\d+$/.test(s))return parseInt(s,10);
  if(/^-?\d*\.\d+$/.test(s))return parseFloat(s);
  return s;
}
function parseYamlLite(text){
  var root={}, stack=[{indent:-1,node:root}], lines=text.split('\n');
  for(var i=0;i<lines.length;i++){
    var raw=lines[i];
    if(/^[ ]*$/.test(raw)||/^[ ]*#/.test(raw))continue;
    var mm=raw.match(/^([ ]*)(.*)$/), indent=mm[1].length, body=mm[2];
    if(/^-(\s|$)/.test(body)){
      while(stack.length>1 && stack[stack.length-1].indent>=indent)stack.pop();
      var arr=stack[stack.length-1].node;
      if(!Array.isArray(arr))return null;
      arr.push(yamlScalar(body.replace(/^-\s*/,'')));
      continue;
    }
    var kv=body.match(/^([^:]+):[ ]*(.*)$/);
    if(!kv)return null;
    var key=kv[1].trim(), val=kv[2].trim();
    while(stack.length>1 && stack[stack.length-1].indent>=indent)stack.pop();
    var parent=stack[stack.length-1].node;
    if(parent===root && Object.prototype.hasOwnProperty.call(parent,key))return null;  /* 重复键 → 视为非法 */
    if(val===''){
      var nx=lines[i+1]||'';
      if(/^[ ]*-\s/.test(nx)||/^[ ]*-$/.test(nx)){
        var na=[]; parent[key]=na; stack.push({indent:indent,node:na});
      }else{
        var no={}; parent[key]=no; stack.push({indent:indent,node:no});
      }
    }else{
      parent[key]=yamlScalar(val);
    }
  }
  return root;
}
function extractFrontMatter(src){
  var lines=src.split('\n');
  if(!lines.length||lines[0].replace(/[ ]/g,'')!=='---')return {src:src, meta:null};
  var end=-1;
  for(var i=1;i<lines.length;i++){
    var t=lines[i].replace(/[ ]/g,'');
    if(t==='---'||t==='...'){end=i;break;}
  }
  if(end<0)return {src:src, meta:null};          /* 未闭合 → 当普通内容 */
  var body=lines.slice(end+1).join('\n');
  var meta=null;
  try{ meta=parseYamlLite(lines.slice(1,end).join('\n')); }catch(e){ meta=null; }
  return {src:body, meta:meta};
}
```

**Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_frontmatter.py`
Expected: 13/13 PASS

**Step 5: 接入 `render()` 与导出标题**

① `render()` 开头改为（front matter 剥离在此接入）：

```javascript
  function render(){
    buildMirrorMap();
    var fm=extractFrontMatter(getText());   /* front matter 剥离出正文（不进预览） */
    var src=extractMath(fm.src);
    var fx=extractFootnotes(src);
    src=fx.src;
```

同时在 UI 段加模块级变量并在 `render()` 里赋值，供导出取标题：

```javascript
  var frontMeta=null;   /* 文档 front matter 元数据（导出标题用） */
```
```javascript
    frontMeta=fm.meta;   /* 置于 render() 内 fm 解构之后 */
```

② 在 UI 段导出处理器中，把 front matter 的 title 带给后端：
- `/api/export-html`（1414 行）：payload 增加 `docTitle:(frontMeta&&frontMeta.title)||''`
- `/api/export-paged`（1428 行）：同样增加该字段
- 在 UI 段保存一个模块级变量 `var frontMeta=null;`，在 `render()` 里赋值 `frontMeta=fm.meta;`

后端 `md_server.py` 的 `build_standalone_html(md_path, body_html, ts_css)` 改为 `build_standalone_html(md_path, body_html, ts_css, doc_title="")`，标题取值为 `doc_title` 优先、为空则回退首个 `<h1>`；`build_paged_html` 的 `<title>` 同理。两条路由从 payload 读取 `obj.get("docTitle")` 传入。

**Step 6: 回归 + 提交**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_footnote.py` 与 `_test_list_parse.py`
Expected: 全 PASS

```bash
git add markdown-editor.html md_server.py _test_frontmatter.py
git commit -m "feat: YAML front matter（极简子集解析，剥离出正文并用于导出标题）"
```

---

### Task 7: 导出样式对齐（预览 / 独立 HTML / 分页 三处同源）

**Files:**
- Modify: `markdown-editor.html` — 主 `<style>` 块（9–178 行）加新语法样式
- Modify: `md_server.py` — `build_standalone_html` / `build_paged_html` 注入同一套样式
- Test: `_test_export_css.py`（新建）

**Interfaces:**
- Consumes: Task 2–6 的渲染结构（`.footnotes`/`.fn-ref`/`.callout`/`.mark`/`dl`/`.fnblk`）
- Produces: 样式常量 `SYNTAX_CSS`（前端内联字符串）与服务端同名常量，两处内容一致

**Step 1: 写失败的测试**

创建 `_test_export_css.py`：

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""导出样式对齐测试（R1）：新语法在独立 HTML 与分页 HTML 中必须有样式，
否则导出后 callout/脚注/高亮全部裸奔（预览与导出不同源）。"""
import json
import os
import sys
import threading
import time
import urllib.request

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
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (PORT, path), timeout=30) as r:
        return r.read().decode("utf-8")


def main():
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        body = ("<p>x</p><div class=\"callout callout-note\"><p class=\"callout-title\">NOTE</p></div>"
                "<mark>高亮</mark><dl><dt>t</dt><dd>d</dd></dl>"
                "<section class=\"footnotes\"><ol><li id=\"fn-1\">脚注</li></ol></section>")
        post("/api/export-html", {"path": None, "bodyHtml": body, "tsCss": "", "docTitle": "标题"})
        html = get("/static/document.html")
        for key, needle in [("callout 容器样式", ".markdown-body .callout"),
                            ("callout 五型", ".callout-note"),
                            ("行内高亮", ".markdown-body mark"),
                            ("定义列表", ".markdown-body dl"),
                            ("脚注区", ".markdown-body .footnotes"),
                            ("脚注上标引用", ".fn-ref"),
                            ("标题取 front matter", "<title>标题</title>")]:
            check(key, needle in html, "缺: " + needle)

        post("/api/export-paged", {"path": None, "bodyHtml": body, "tsCss": "", "cfg": {}})
        paged = get("/static/document.paged.html")
        for key, needle in [("分页版 callout 样式", ".markdown-body .callout"),
                            ("分页版 行内高亮", ".markdown-body mark"),
                            ("分页版 脚注区样式", ".markdown-body .footnotes")]:
            check(key, needle in paged, "缺: " + needle)
    finally:
        httpd.shutdown()
        httpd.server_close()
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
```

**Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_export_css.py`
Expected: FAIL（样式缺失）

**Step 3: 实现**

在 `markdown-editor.html` 主 `<style>` 块内，`.markdown-body .toc-anchor` 规则之后追加：

```css
  /* ── R1 新语法样式 ────────────────────────────────────────── */
  .markdown-body mark{background:#f5d76e;color:inherit;padding:.05em .25em;border-radius:3px;}
  .markdown-body sup,.markdown-body sub{font-size:.72em;line-height:0;}
  .markdown-body dl{margin:.9em 0;}
  .markdown-body dt{font-weight:650;margin-top:.6em;}
  .markdown-body dd{margin:.2em 0 .2em 1.6em;color:var(--text);}
  .markdown-body .callout{margin:.9em 0;padding:.6em 1em;border-left:4px solid var(--accent);
    border-radius:0 var(--radius) var(--radius) 0;background:var(--accent-soft);}
  .markdown-body .callout-title{margin:0 0 .35em;font-weight:700;font-size:.92em;}
  .markdown-body .callout-note{border-left-color:#4a6cf7;background:rgba(74,108,247,.10);}
  .markdown-body .callout-tip{border-left-color:#2f9e5f;background:rgba(47,158,95,.10);}
  .markdown-body .callout-important{border-left-color:#8a5cf5;background:rgba(138,92,245,.10);}
  .markdown-body .callout-warning{border-left-color:#d99a4e;background:rgba(217,154,78,.12);}
  .markdown-body .callout-caution{border-left-color:#d9534f;background:rgba(217,83,79,.10);}
  .markdown-body .callout p{margin:.3em 0;}
  .markdown-body .fn-ref{font-size:.72em;line-height:0;margin-left:.1em;}
  .markdown-body .fn-ref a{text-decoration:none;}
  .markdown-body .footnotes{margin-top:2em;font-size:.92em;color:var(--muted);}
  .markdown-body .footnotes ol{margin:.3em 0;padding-left:1.4em;}
  .markdown-body .footnotes li{margin:.3em 0;}
  .markdown-body .fn-back{text-decoration:none;margin-left:.3em;}
  .markdown-body .fn-sep{border-top:1px solid var(--border);}
```

在 `md_server.py` 中新增模块级常量（放在 `PAGED_BASE_CSS` 附近），内容为**同一套规则但用固定色值**（导出文档内 CSS 变量未定义，不能用 `var(--accent)`）：

```python
# R1 新语法样式（导出用固定色值：导出文档内未定义 CSS 变量）
SYNTAX_CSS = (
    ".markdown-body mark{background:#f5d76e;color:inherit;padding:.05em .25em;border-radius:3px;}"
    ".markdown-body sup,.markdown-body sub{font-size:.72em;line-height:0;}"
    ".markdown-body dl{margin:.9em 0;}"
    ".markdown-body dt{font-weight:650;margin-top:.6em;}"
    ".markdown-body dd{margin:.2em 0 .2em 1.6em;}"
    ".markdown-body .callout{margin:.9em 0;padding:.6em 1em;border-left:4px solid #4a6cf7;"
    "border-radius:0 6px 6px 0;background:#f5f7ff;}"
    ".markdown-body .callout-title{margin:0 0 .35em;font-weight:700;font-size:.92em;}"
    ".markdown-body .callout-note{border-left-color:#4a6cf7;background:#f5f7ff;}"
    ".markdown-body .callout-tip{border-left-color:#2f9e5f;background:#eefaf2;}"
    ".markdown-body .callout-important{border-left-color:#8a5cf5;background:#f3eefe;}"
    ".markdown-body .callout-warning{border-left-color:#d99a4e;background:#fdf5e9;}"
    ".markdown-body .callout-caution{border-left-color:#d9534f;background:#fdeceb;}"
    ".markdown-body .callout p{margin:.3em 0;}"
    ".markdown-body .fn-ref{font-size:.72em;line-height:0;margin-left:.1em;}"
    ".markdown-body .fn-ref a{text-decoration:none;}"
    ".markdown-body .footnotes{margin-top:2em;font-size:.92em;color:#666;}"
    ".markdown-body .footnotes ol{margin:.3em 0;padding-left:1.4em;}"
    ".markdown-body .footnotes li{margin:.3em 0;}"
    ".markdown-body .fn-back{text-decoration:none;margin-left:.3em;}"
    ".markdown-body .fn-sep{border-top:1px solid #ddd;}"
)
```

在 `build_standalone_html` 的 `<style>__TS__</style>` 之前插入 `__SYNTAX__` 占位并替换为 `SYNTAX_CSS`（即该段变为 `"<style>div.md-math-block{…}span.md-math-inline{…}__SYNTAX____TS__</style>"`，替换顺序 `html.replace("__SYNTAX__", SYNTAX_CSS)`）。

在 `build_paged_html`（2006–2022 行的 html 组装）中，把第三个 style 块改为：

```python
        "<style>%s</style><style>%s</style><style>%s%s%s%s</style>"
```
并把元组改为（顺序：katex → toc → **SYNTAX** → 用户排版样式，保证用户 `!important` 规则仍然覆盖新语法样式）：

```python
        html_module.escape(title),
        page_css,
        base_css,
        katex_css,
        toc_css,
        SYNTAX_CSS,
        ts_css,
```

同时给 `build_paged_html` 增加 `doc_title` 参数（Task 6 已加 `build_standalone_html` 的同名参数），标题取值 `doc_title` 优先、为空回退首个 `<h1>`。

> 前端 `buildStandaloneHtml()`（`markdown-editor.html` 1647 行，当前无调用点，属历史兜底路径）同样要补上新语法样式，否则将来重新启用该路径会漏样式。

**Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_export_css.py`
Expected: ALL PASS（10/10）

**Step 5: 回归 + 提交**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_paged_e2e.py`
Expected: 47/47 PASS（注入样式不得破坏既有断言）

```bash
git add markdown-editor.html md_server.py _test_export_css.py
git commit -m "feat: 新语法样式在预览/独立导出/分页导出三处对齐"
```

---

### Task 8: highlight.js vendor 落地与许可登记

**Files:**
- Create: `highlight/highlight.min.js`、`highlight/styles/github.css`、`highlight/styles/github-dark.css`、`LICENSES/highlight.js-BSD-3-Clause.txt`
- Modify: `docs/分发清单.md`、`docs/版权与开源组件声明.md`
- Test: 本任务内联校验脚本（vendor 存在性 + 语言集含 r + 许可登记）

**Interfaces:**
- Consumes: 无（纯资源落地）
- Produces: `/static/highlight/highlight.min.js`、`/static/highlight/styles/github.css`、`/static/highlight/styles/github-dark.css` 三个可访问路径

**Step 1: 下载 vendor**

Run（PowerShell）:
```powershell
$dst = "E:\Positron-demo\maby_tool-main\MarkdownEditor-app\highlight"
New-Item -ItemType Directory -Force -Path "$dst\styles" | Out-Null
$base = "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.1"
Invoke-WebRequest "$base/highlight.min.js" -OutFile "$dst\highlight.min.js"
Invoke-WebRequest "$base/styles/github.css" -OutFile "$dst\styles\github.css"
Invoke-WebRequest "$base/styles/github-dark.css" -OutFile "$dst\styles\github-dark.css"
```
Expected: 三个文件落盘；`highlight.min.js` 体积约 120KB。

**Step 2: 校验 vendor 正确性**

Run:
```powershell
$js = Get-Content "E:\Positron-demo\maby_tool-main\MarkdownEditor-app\highlight\highlight.min.js" -Raw
"has r language : " + ($js -match 'registerLanguage\("r"')
"has js language : " + ($js -match 'registerLanguage\("javascript"')
"size KB        : " + [int]((Get-Item "E:\Positron-demo\maby_tool-main\MarkdownEditor-app\highlight\highlight.min.js").Length/1KB)
```
Expected: 前两行均为 `True`；size 100–200KB 之间。

若 `registerLanguage("r"` 未命中 → 说明下载的是精简构建，改用 `$base/highlight.pack.js` 或 `highlight.min.js` 的完整语言版重新下载。

**Step 3: 写失败的自检脚本并确认失败**

创建 `_test_highlight.py`（先只写 vendor 部分，Task 9 再补前端部分）：

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""代码高亮测试（R1）：
- vendor 落地且含 R 语言（用户点名要的）
- 许可登记为 BSD-3-Clause（非 MIT）
- 前端懒加载 + 实际着色（浏览器级，Task 9 补）"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def main():
    js = os.path.join(HERE, "highlight", "highlight.min.js")
    check("vendor 存在", os.path.exists(js))
    if os.path.exists(js):
        txt = open(js, encoding="utf-8", errors="replace").read()
        check("含 R 语言", 'registerLanguage("r"' in txt or "registerLanguage('r'" in txt)
        check("含 JavaScript 语言", 'registerLanguage("javascript"' in txt)
        size = os.path.getsize(js)
        check("体积在合理区间(60KB~400KB)", 60 * 1024 <= size <= 400 * 1024, "%d bytes" % size)
    for st in ("github.css", "github-dark.css"):
        p = os.path.join(HERE, "highlight", "styles", st)
        check("主题存在 " + st, os.path.exists(p))
    lic = os.path.join(HERE, "LICENSES", "highlight.js-BSD-3-Clause.txt")
    check("许可全文存在", os.path.exists(lic))
    if os.path.exists(lic):
        t = open(lic, encoding="utf-8", errors="replace").read()
        check("许可含 BSD-3-Clause 标识",
              ("BSD" in t and "3-Clause" in t) or "Redistribution and use in source and binary forms" in t)
    dist = os.path.join(HERE, "docs", "分发清单.md")
    if os.path.exists(dist):
        d = open(dist, encoding="utf-8", errors="replace").read()
        check("分发清单登记 highlight.js", "highlight.js" in d)
    lic_doc = os.path.join(HERE, "docs", "版权与开源组件声明.md")
    if os.path.exists(lic_doc):
        d = open(lic_doc, encoding="utf-8", errors="replace").read()
        check("版权声明登记 highlight.js", "highlight.js" in d)
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
```

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_highlight.py`
Expected: FAIL（许可全文与文档登记未做）

**Step 4: 补许可与文档登记**

- 把 highlight.js 的 BSD-3-Clause 许可全文保存为 `LICENSES/highlight.js-BSD-3-Clause.txt`（取自 highlight.js 仓库 `LICENSE` 文件；文本须包含 "Redistribution and use in source and binary forms" 与 "Neither the name of the copyright holder nor the names of its contributors" 两段）
- `docs/分发清单.md`：加一行 `| highlight.js | 11.11.1 | 代码语法高亮（common 37 语言，含 R） | highlight/highlight.min.js + styles/ |` 并把 `highlight/` 列入最小分发集
- `docs/版权与开源组件声明.md`：组件表加 highlight.js 一行，许可要点写 **BSD-3-Clause**（无传染性、可自由再分发、可商用，与 AGPL-3.0 并存无冲突）

**Step 5: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_highlight.py`
Expected: ALL PASS

**Step 6: 提交**

```bash
git add highlight LICENSES/highlight.js-BSD-3-Clause.txt docs _test_highlight.py
git commit -m "feat: 引入 highlight.js 11.11.1 vendor（含 R 语言）与 BSD-3-Clause 许可登记"
```

---

### Task 9: 代码高亮接入（懒加载 + 着色 + 主题切换）

**Files:**
- Modify: `markdown-editor.html` — ① 179 行后加 hljs 主题 `<link>`；② `diagState`/`diagUrl` 加 `highlight` 项；③ UI 段新增 `highlightCode`；④ `render()` 内调用；⑤ `applyTheme` 切换主题
- Test: `_test_syntax_ui.py`（新建，浏览器级）

**Interfaces:**
- Consumes: Task 8 的 vendor 路径；Task 2–7 的渲染结构
- Produces:
  - `highlightCode(root)` — 对 `root` 内未着色的 `pre code` 着色
  - 主题切换：`applyTheme` 同步切换两个 `<link>` 的 `media`

**Step 1: 写失败的测试**

创建 `_test_syntax_ui.py`：

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""R1 浏览器级验证（CDP）：脚注区、Callout、代码高亮在真实页面里的 DOM 结果。
依赖 Task 1 的 _test_browser.py 通道。"""
import json
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


DOC = """# 标题

脚注引用[^a]。

> [!NOTE]
> 提示内容

```python
def f(x):
    return x**2
```

[^a]: 脚注说明
"""

EXPR = r"""
(function(){
  var DOC = %s;
  var ed = document.getElementById('editor');
  ed.textContent = DOC;
  ed.dispatchEvent(new Event('input', {bubbles:true}));
  return new Promise(function(resolve){
    setTimeout(function(){
      resolve({
        fnRef: !!document.querySelector('#preview .fn-ref'),
        fnNum: (document.querySelector('#preview .fn-ref')||{}).textContent || '',
        fnSec: !!document.querySelector('#preview .fnblk .footnotes'),
        fnText: (document.querySelector('#preview .fnblk')||{}).textContent || '',
        callout: !!document.querySelector('#preview .callout.callout-note'),
        calloutTitle: (document.querySelector('#preview .callout-title')||{}).textContent || '',
        hlSpans: document.querySelectorAll('#preview pre code .hljs-keyword').length,
        hlClass: (document.querySelector('#preview pre code')||{}).className || ''
      });
    }, 1500);
  });
})()
""" % json.dumps(DOC, ensure_ascii=False)

if __name__ == "__main__":
    res = run_expr(EXPR)
    check("脚注引用渲染", res.get("fnRef") is True, str(res))
    check("脚注编号为 1", res.get("fnNum") == "1", str(res.get("fnNum")))
    check("脚注区落在预览末尾", res.get("fnSec") is True, str(res))
    check("脚注正文可见", "脚注说明" in (res.get("fnText") or ""), str(res.get("fnText")))
    check("Callout 渲染", res.get("callout") is True, str(res))
    check("Callout 标题", res.get("calloutTitle") == "NOTE", str(res.get("calloutTitle")))
    check("代码高亮生成 hljs-keyword", (res.get("hlSpans") or 0) >= 1, str(res))
    check("code 元素带 hljs 类", "hljs" in (res.get("hlClass") or ""), str(res.get("hlClass")))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)
```

**Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_syntax_ui.py`
Expected: FAIL（脚注引用/Callout/高亮都还没接）

**Step 3: 实现**

① 在 `markdown-editor.html` 的 179 行（katex `<link>`）之后插入：

```html
  <link id="hljsDark" rel="stylesheet" href="/static/highlight/styles/github-dark.css">
  <link id="hljsLight" rel="stylesheet" href="/static/highlight/styles/github.css" media="not all">
```

② 在 UI 段 `diagState`（919 行）加一项、`diagUrl`（920 行）加一项：

```javascript
  var diagState={mermaid:{ready:false,loading:false,queue:[]},dot:{ready:false,loading:false,queue:[]},wavedrom:{ready:false,loading:false,queue:[]},vega:{ready:false,loading:false,queue:[]},highlight:{ready:false,loading:false,queue:[]}};
  var diagUrl={mermaid:['/static/mermaid/mermaid.min.js'],dot:['/static/viz/viz-standalone.js'],wavedrom:['/static/wavedrom/skins/default.js','/static/wavedrom/skins/dark.js','/static/wavedrom/wavedrom.min.js'],vega:['/static/vega/vega.min.js','/static/vega/vega-lite.min.js','/static/vega/vega-embed.min.js'],highlight:['/static/highlight/highlight.min.js']};
```

③ 在 UI 段新增函数（放在 `mountDiagrams` 之后）：

```javascript
  /* 代码语法高亮：highlight.js 懒加载（首次遇到代码块才载入 vendor）。
     图表围栏不走本函数（它们渲染为 .diagram 容器，不是 pre code）。
     语言取 data-lang（围栏解析出的干净语言名）；未指定则自动探测，
     探测结果为 plaintext/no-highlight 时保持原样（中文散文常被误判，宁可不着色）。 */
  function highlightCode(root){
    if(!root||!root.querySelectorAll)return;
    var codes=root.querySelectorAll('pre code:not([data-hl])');
    if(!codes.length)return;
    loadVendor('highlight',function(){
      for(var i=0;i<codes.length;i++){
        var el=codes[i];
        if(el.getAttribute('data-hl'))continue;
        el.setAttribute('data-hl','1');
        try{
          var lang=(el.getAttribute('data-lang')||'').toLowerCase();
          var out=null;
          if(lang && window.hljs && hljs.getLanguage(lang)){
            out=hljs.highlight(el.textContent,{language:lang});
          }else if(window.hljs){
            var r=hljs.highlightAuto(el.textContent);
            if(r.language && r.language!=='plaintext' && r.language!=='no-highlight')out=r;
          }
          if(out){
            el.innerHTML=out.value;
            el.classList.add('hljs');
            if(out.language)el.classList.add('language-'+out.language);
          }
        }catch(e){ /* 着色失败保持原文，不阻断渲染 */ }
      }
    });
  }
```

④ 在 `parseMarkdown` 的围栏分支里，给**非图表**围栏的 `<code>` 加 `data-lang`：

```javascript
      }else{
        html+='<pre><code'+(rawLang?' class="lang-'+rawLang+'"':'')+' data-lang="'+escAttr(fl.lang)+'">'+escapeHtml(code).replace(/</g,'&lt;')+'</code></pre>';
      }
```

> `class="lang-<rawLang>"` 保持原样（`_test_img_width.py` 断言 `lang-python {30}` 字面保留）；`data-lang` 用解析出的干净语言名 `fl.lang`（`python`），供高亮使用。

⑤ 在 `render()` 的块渲染处调用：

```javascript
      div.innerHTML=parseMarkdown(q.blocks[bi], fx);
      restoreMath(div); fixLocalImages(div);
      mountDiagrams(div);
      highlightCode(div);
```

⑥ 在 `applyTheme`（1361 行）末尾追加主题联动：

```javascript
    /* 代码高亮主题跟随编辑器明暗：两套 <link> 用 media 开关切换 */
    var hd=document.getElementById('hljsDark'), hl=document.getElementById('hljsLight');
    if(hd)hd.media=(t==='light')?'not all':'all';
    if(hl)hl.media=(t==='light')?'all':'not all';
```

**Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_syntax_ui.py`
Expected: ALL PASS（8/8）

**Step 5: 回归 + 提交**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_img_width.py` 与 `_test_escape.py`
Expected: 6/6、11/11 PASS（围栏 class 语义未变）

```bash
git add markdown-editor.html _test_syntax_ui.py
git commit -m "feat: 代码语法高亮（highlight.js 懒加载，主题跟随明暗）"
```

---

### Task 10: 代码块复制按钮

**Files:**
- Modify: `markdown-editor.html` — ① `parseMarkdown` 围栏分支加包裹层与按钮；② UI 段加点击事件；③ 导出 payload 取 bodyHtml 处剥离按钮
- Test: `_test_copy_btn.py`（新建，浏览器级）

**Interfaces:**
- Consumes: Task 9 的渲染结构；Task 7 的导出链路
- Produces:
  - 渲染形如 `<div class="code-wrap"><pre><code …>…</code></pre><button type="button" class="copy-btn">复制</button></div>`
  - `stripExportArtifacts(html)` — 移除 `.copy-btn` 节点（导出用）

**Step 1: 写失败的测试**

创建 `_test_copy_btn.py`：

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""代码块复制按钮测试（R1）：按钮存在、点击写入剪贴板、导出产物不含按钮。"""
import json
import os
import sys
import threading
import time
import urllib.request

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
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        # 导出产物不得含复制按钮
        post("/api/export-html", {"path": None, "bodyHtml":
             '<div class="code-wrap"><pre><code>x=1</code></pre>'
             '<button type="button" class="copy-btn">复制</button></div>', "tsCss": ""})
        with urllib.request.urlopen("http://127.0.0.1:%d/static/document.html" % PORT, timeout=10) as r:
            html = r.read().decode("utf-8")
        check("导出产物不含复制按钮", "copy-btn" not in html, html[:200])
    finally:
        httpd.shutdown()
        httpd.server_close()

    from _test_browser import run_expr
    expr = r"""
    (function(){
      var ed=document.getElementById('editor');
      ed.textContent='```python\nx = 1\n```';
      ed.dispatchEvent(new Event('input',{bubbles:true}));
      /* 截获剪贴板写入：clipboard 对象的 writeText 是只读属性，须整体替换 */
      var copied=null;
      try{
        Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
          writeText:function(t){copied=t;return Promise.resolve();}
        }});
      }catch(e){}
      return new Promise(function(resolve){
        setTimeout(function(){
          var btn=document.querySelector('#preview .copy-btn');
          if(!btn){ resolve({btn:false}); return; }
          var code=btn.parentNode.querySelector('code').textContent;
          btn.click();
          setTimeout(function(){
            resolve({btn:true, code:code, copied:copied});
          },300);
        },1200);
      });
    })()
    """
    res = run_expr(expr)
    check("预览中有复制按钮", res.get("btn") is True, str(res))
    check("按钮旁有代码元素", "x = 1" in (res.get("code") or ""), str(res))
    check("点击写入剪贴板", (res.get("copied") or "").index("x = 1") >= 0, str(res))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
```

**Step 2: 跑测试确认失败**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_copy_btn.py`
Expected: FAIL（无按钮）

**Step 3: 实现**

① `parseMarkdown` 围栏分支的非图表分支改为：

```javascript
      }else{
        html+='<div class="code-wrap"><pre><code'+(rawLang?' class="lang-'+rawLang+'"':'')+' data-lang="'+escAttr(fl.lang)+'">'+escapeHtml(code).replace(/</g,'&lt;')+'</code></pre>'+
              '<button type="button" class="copy-btn" title="复制代码">复制</button></div>';
      }
```

② UI 段新增事件（放在 `showToast` 定义之后）：

```javascript
  /* 代码块复制：事件委托到预览容器（内容增量渲染，按钮随块重建） */
  function legacyCopy(text){
    try{
      var ta=document.createElement('textarea');
      ta.value=text; ta.style.position='fixed'; ta.style.opacity='0';
      document.body.appendChild(ta); ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      showToast('代码已复制');
      return true;
    }catch(e){ showToast('复制失败',true); return false; }
  }
  function copyText(text){
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(
        function(){ showToast('代码已复制'); },
        function(){ legacyCopy(text); }      /* 非安全上下文/被拒 → 回退 */
      );
      return;
    }
    legacyCopy(text);
  }
  preview.addEventListener('click',function(e){
    var b=e.target&&e.target.closest?e.target.closest('.copy-btn'):null;
    if(!b)return;
    var code=b.parentNode?b.parentNode.querySelector('code'):null;
    copyText(code?code.textContent:'');
  });
```

③ 导出取 bodyHtml 处剥离按钮（UI 段 `1414` 与 `1428` 两处）：

```javascript
  /* 导出用的正文：剥离仅供交互的复制按钮（独立 HTML 里 clipboard 不可靠且对读者无意义） */
  function exportBodyHtml(){
    var pv=document.getElementById('preview');
    return pv?pv.innerHTML.replace(/<button[^>]*class="copy-btn"[^>]*>[\s\S]*?<\/button>/g,''):'';
  }
```

把 `/api/export-html` 的 `bodyHtml:document.getElementById('preview').innerHTML` 换成 `bodyHtml:exportBodyHtml()`；把 `/api/export-paged` 的 `var bh = pv ? pv.innerHTML : '';` 换成 `var bh = exportBodyHtml();`。

④ 样式（主 `<style>` 块，R1 样式段内追加）：

```css
  .markdown-body .code-wrap{position:relative;}
  .markdown-body .copy-btn{
    position:absolute;top:6px;right:8px;z-index:2;
    font-size:11px;line-height:1;padding:4px 8px;border-radius:5px;cursor:pointer;
    background:var(--panel,#2b3242);color:var(--muted,#aab2c4);
    border:1px solid var(--border,#3a4358);opacity:0;transition:opacity .12s;
  }
  .markdown-body .code-wrap:hover .copy-btn{opacity:1;}
```

**Step 4: 跑测试确认通过**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_copy_btn.py`
Expected: ALL PASS（4/4）

**Step 5: 回归 + 提交**

Run: `D:\py_base_env\.venv\Scripts\python.exe _test_img_width.py`
Expected: 6/6 PASS（围栏输出结构变化不得破坏既有断言——断言用的是正则搜索，包裹层不影响）

```bash
git add markdown-editor.html _test_copy_btn.py
git commit -m "feat: 代码块复制按钮（导出时剥离）"
```

---

### Task 11: 文档、版本号与全量回归

**Files:**
- Modify: `CHANGELOG.md`、`README.md`、`docs/MDEditor 使用指南.md`、`docs/分发清单.md`、`docs/版权与开源组件声明.md`、`md_server.py`（`MD_SERVER_VERSION`）
- Test: 全量回归脚本

**Interfaces:**
- Consumes: Task 1–10 的全部产物
- Produces: v2.1.0 版本条目、文档更新、`MD_SERVER_VERSION = 55`

**Step 1: 写回归脚本并确认（改动前先跑一次基线）**

Run:
```powershell
cd E:\Positron-demo\maby_tool-main\MarkdownEditor-app
Get-ChildItem _test_*.py | ForEach-Object {
  $out = & D:\py_base_env\.venv\Scripts\python.exe $_.FullName 2>&1
  "{0,-24} {1}" -f $_.Name, ($out | Select-String -Pattern "PASS|ALL PASS|FAIL" | Select-Object -Last 1)
}
```
Expected: 逐条记录基线结果。**记录哪些用例在本机因缺环境而无法运行**（如 `_test_list_ui.py` / `_test_outline_jump.py` 依赖 playwright，本机未装 → 标注「需 playwright，未跑」），这些不算失败。

**Step 2: 更新 `md_server.py` 版本号**

把 `MD_SERVER_VERSION = 54` 改为 `MD_SERVER_VERSION = 55  # 每次服务端路由/能力变更时 +1；md_launch 依此自愈换代`。

**Step 3: 写 CHANGELOG v2.1.0 条目**

在 `CHANGELOG.md` 顶部（`---` 之后）插入：

```markdown
## v2.1.0（2026-10-21）

**本次改动：五类 Markdown 语法扩展 + 代码语法高亮 + 代码块复制按钮**

**新增**

- **脚注（文档级）**：正文 `[^label]` 引用、文档任意处 `[^label]: 说明` 定义；编号按**引用首次出现顺序**重排（定义顺序与引用顺序不一致时以引用序为准），未定义的引用保持字面原文（fail-closed，不渲染成坏链接）；定义行剥离出正文，文末自动生成脚注区（带回跳锚点）。定义可多行（续行缩进 4 空格），空行终止。实现——解析层新增 `extractFootnotes`/`buildFootnoteSection`，脚注上下文 `fx` 经 `parseMarkdown`→`parseList`/`parseTable`→`parseInline` 逐层传递；`render()` 入口先做全文提取再分块渲染，脚注区独立于 `.pblk` 块序列追加在预览末尾，编号变化时全文重渲。验证——`_test_footnote.py` 7/7 PASS（编号序、未定义字面、定义剥离、多行定义、代码块内不生效、重复引用共用编号）；`_test_syntax_ui.py` 浏览器级断言脚注引用/脚注区真实 DOM。
- **Callout 提示块**：`> [!NOTE]` / `[!TIP]` / `[!IMPORTANT]` / `[!WARNING]` / `[!CAUTION]` 五型（可带标题 `> [!NOTE] 标题`），渲染为带类型色条的容器；普通引用块行为不变。验证——`_test_callout.py` 7/7 PASS。
- **行内高亮与上下标**：`==高亮==`→`<mark>`、`^上标^`→`<sup>`、`~下标~`→`<sub>`；删除线 `~~x~~` 优先级高于下标（不被拆成两个下标），行内代码与链接内的同名字符不生效。验证——`_test_inline_ext.py` 8/8 PASS。
- **定义列表**：`术语` + `: 定义` 渲染为 `<dl><dt><dd>`，一条术语可带多条定义，定义的续行缩进 4 空格。验证——`_test_deflist.py` 6/6 PASS。
- **YAML front matter**：文档首行 `---` 起的 YAML 元数据块，剥离出正文（不进预览），支持极简子集（嵌套 map／列表／标量）；解析失败整块按普通段落处理（fail-closed，不吞内容）；未闭合或非首行触发均不生效。导出的 HTML 标题优先取 front matter 的 `title`。验证——`_test_frontmatter.py` 13/13 PASS。
- **代码语法高亮**：highlight.js 11.11.1 common 集（37 种语言，含 **R**）就地 vendor 分发，懒加载（文档无代码则零加载），语言取围栏语言名（未指定则自动探测，探测为 plaintext 时不着色），主题跟随编辑器明暗。着色结果留在 DOM，服务端导出只注入主题 CSS（独立 HTML 仍是可分发单文件）。验证——`_test_highlight.py` vendor/许可断言 PASS；`_test_syntax_ui.py` 断言 `hljs-keyword` span 真实生成。
- **代码块复制按钮**：代码块右上角「复制」，点击写入剪贴板（非安全上下文回退 `execCommand`）；导出产物自动剥离按钮（独立 HTML 内 clipboard 不可靠且对读者无意义）。验证——`_test_copy_btn.py` 4/4 PASS。

**变更**

- **导出与预览样式同源**：新语法样式在预览、独立 HTML 导出、分页导出三处同步注入（导出用固定色值，导出文档内无 CSS 变量）。验证——`_test_export_css.py` 10/10 PASS；`_test_paged_e2e.py` 47/47 回归 PASS。
- **测试基建**：新增 CDP 浏览器测试通道（`_cdp.js` + `_test_browser.py`，Node 24 内置 WebSocket 直连本机 Chrome/Edge 调试端口，零安装），替代本机未安装的 playwright。
- **服务版本 54→55**：`MD_SERVER_VERSION` 自愈换代，旧页面自动刷新至带新语法的版本。

**测试**

- 新增 `_test_footnote.py` / `_test_callout.py` / `_test_inline_ext.py` / `_test_deflist.py` / `_test_frontmatter.py` / `_test_highlight.py` / `_test_export_css.py` / `_test_syntax_ui.py` / `_test_copy_btn.py`。
- 回归：既有 `_test_list_parse.py` 20/20、`_test_escape.py` 11/11、`_test_img_width.py` 6/6、`_test_table_split.py` 8/8、`_test_smd.py` 33/33、`_test_paged_e2e.py` 47/47 全 PASS。

**说明**

- 图表引擎本轮不扩容（mermaid/dot/wavedrom/vega 四套维持现状）。
- highlight.js 许可为 **BSD-3-Clause**（非 MIT），无传染性，与本工具 AGPL-3.0-or-later 并存无冲突。
```

**Step 4: 更新 README 与使用指南**

`README.md`：
- 「功能速览」补两条：
  - `**语法扩展**：脚注（文档级，编号按引用序）、Callout 提示块（NOTE/TIP/IMPORTANT/WARNING/CAUTION 五型）、行内高亮 ==…== 与上下标、定义列表、YAML front matter`
  - `**代码高亮**：highlight.js 本地着色（37 种语言，含 R），代码块右上角可一键复制`
- 「核心必需」文件表补一行：`| highlight/ | 代码语法高亮（highlight.js 11.11.1，BSD-3-Clause） |`

`docs/MDEditor 使用指南.md`：在「语法速查与本工具的特殊写法」章补一节「R1 新增语法」，用表格列出五类语法各 1 个真实示例（脚注、Callout、高亮/上下标、定义列表、front matter），并注明「代码块自动高亮，支持 R/Python/JS/SQL 等 37 种语言，未指定语言时自动探测」。

`docs/分发清单.md`：最小分发集加入 `highlight/`（`highlight.min.js` + `styles/github.css` + `styles/github-dark.css`）。

`docs/版权与开源组件声明.md`：组件表补 highlight.js（11.11.1，BSD-3-Clause），许可要点写明「允许自由再分发与商用、无传染性」。

**Step 5: 全量回归**

Run:
```powershell
cd E:\Positron-demo\maby_tool-main\MarkdownEditor-app
Get-ChildItem _test_*.py | ForEach-Object {
  $out = & D:\py_base_env\.venv\Scripts\python.exe $_.FullName 2>&1
  "{0,-24} {1}" -f $_.Name, ($out | Select-String -Pattern "PASS|ALL PASS|FAIL" | Select-Object -Last 1)
}
```
Expected: 全部 PASS 或「需 playwright，未跑」（`_test_list_ui.py`、`_test_outline_jump.py`）。出现 FAIL 必须修完再提交。

**Step 6: 提交**

```bash
git add -A
git commit -m "docs: v2.1.0 发布说明（语法扩展 + 代码高亮 + 复制按钮），服务版本 55"
```

---

## 附录：规格对照（自审）

| 规格条目（§4） | 落点任务 |
|---|---|
| 4.1 脚注 | Task 2（解析 + 渲染 + 文档级集成） |
| 4.2 Callout | Task 3 |
| 4.3 行内高亮/上下标 | Task 4 |
| 4.4 定义列表 | Task 5 |
| 4.5 YAML front matter | Task 6 |
| 4.6 代码语法高亮 | Task 8（vendor）+ Task 9（接入） |
| 4.7 代码复制按钮 | Task 10 |
| §8 测试策略：`_test_syntax.py` | 拆为 `_test_footnote.py`/`_test_callout.py`/`_test_inline_ext.py`/`_test_deflist.py`/`_test_frontmatter.py`（按仓库「一主题一文件」惯例拆分） |
| §8 测试策略：`_test_highlight.py` | Task 8 |
| §8 测试策略：`_test_export_css.py` | Task 7 |
| §8 测试策略：`_test_syntax_ui.py` | Task 9 |
| §9 文档与分发 | Task 11（+ Task 8 的许可登记） |
| §10 风险：导出不同源 | Task 7 + Review Focus 第 5 条 |
| §10 风险：`==`/`^`/`~` 冲突 | Task 4 + Review Focus 第 3 条 |
