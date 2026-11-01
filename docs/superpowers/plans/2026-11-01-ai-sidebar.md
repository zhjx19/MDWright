# AI 侧栏实施计划（v3.5.0）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 选中编辑器里的文字，在右侧侧栏里多轮追问 AI，并把回答插回文档或替换原选区。

**Architecture:** 前端仍在单文件 `mdwright.html` 里加第三栏（`#aiPane`）与会话状态；后端在 `md_server.py` 增加 `POST /api/chat`，复用 `llm_client.LLMClient` 与现有联网检索，不引第三方依赖。会话只存在窗口内存里，切文档即清空。

**Tech Stack:** Python 3.11 标准库（`http.server`、`urllib`）、原生 JS（无框架）、headless Chrome + CDP（`tests/_test_browser.py`）。

**Spec:** `docs/superpowers/specs/2026-11-01-ai-sidebar-design.md`

## Global Constraints

- 单文件前端：所有 HTML/CSS/JS 继续写在 `mdwright.html`，不新增静态资源。
- 无第三方依赖：后端只用标准库；测试不要求 playwright（用现成的 CDP 脚手架）。
- 业务失败一律 HTTP 200 + `{"ok": false, "error": "..."}`，与 `/api/rewrite` 一致。
- 模型输出必须经 `parseMarkdown()`（内部已 `escapeHtml`）渲染，禁止直接 `innerHTML` 模型原文。
- 上下文总预算 32000 字符；单条用户消息上限 20000；选区/全文各 30000。
- 改动 `.py` 不写 `<-` 一类无关风格；保持现有中文注释口吻。
- 发布三处联动：`MD_SERVER_VERSION` +1、`APP_VERSION` → `3.5.0`、`CHANGELOG.md` 首段。

## Review Focus

- **多轮角色顺序**：最后一条必须是 `user`；末尾的 `assistant`（失败重试留下的半截）要被丢掉，不能把 assistant 当问题发出去。
- **超长输入**：32k 预算下先丢最早的问答，再截文档，再截选区；不能把最后一轮问题丢掉。
- **替换定位**：原文被改过时按 `indexOf` 重定位；找不到就不改文档，只提示。
- **重复请求**：`ai.busy` 期间再点发送不得发第二次。
- **切文档**：会话与上下文一起清空，避免 A 文档的内容进入 B 文档的提问。

---

### Task 1: 后端 `/api/chat`

**Files:**
- Modify: `md_server.py`（新增常量与 `_chat_prepare()`；`do_POST` 增加路由）
- Test: `tests/_test_chat_api.py`（新建）

**Interfaces:**
- Produces: `_chat_prepare(obj) -> (msgs, selection, document, truncated)`；`POST /api/chat` 接受 `{messages, context:{selection,document}, config?}`，返回 `{ok, text, web_search, truncated}`。
- Consumes: `_llm_from_request(obj)`、`_llm_config_from_request(obj)`、`_ws_mod`、`_LLM_ERR`。

- [ ] **Step 1: 写失败测试**（`tests/_test_chat_api.py`）

```python
# 起一个进程内服务（18766），把 llm_client 的 urlopen 换成捕获器
import json, os, sys, threading, time, urllib.request, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import llm_client, md_server

CAP = {}
def fake_urlopen(req, timeout=None):
    CAP["url"] = req.full_url
    CAP["payload"] = json.loads(req.data.decode("utf-8"))
    class R:
        def read(self): return json.dumps({"choices":[{"message":{"content":"答"}}]}).encode()
        def __enter__(self): return self
        def __exit__(self,*a): return False
    return R()

llm_client.urllib.request.urlopen = fake_urlopen
httpd = md_server.ReuseTCPServer(("127.0.0.1", 18766), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

def post(body):
    req = urllib.request.Request("http://127.0.0.1:18766/api/chat",
        data=json.dumps(body).encode(), headers={"Content-Type":"application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())

CFG = {"backend":"openai","base_url":"http://fake.local/v1","model":"m","api_key":"k"}
```

断言（每条一个 `check()`）：

1. 两轮对话 + 选区 → `ok` 为真、`text == "答"`、`CAP["payload"]["messages"][0]["role"] == "system"` 且系统消息里含选中原文、后续消息顺序 `user/assistant/user` 不变。
2. 末尾是 assistant → 该条被丢弃（payload 最后一条是 user）。
3. `messages: []` → `ok` 为假、`error` 非空。
4. 23 条历史 + 每轮 3000 字 → `truncated` 为真，且历史条数变少、最后一条仍是 user。
5. `context.document` 传入 → 系统消息里含 `【整篇文档】`；不传则不含。
6. `config` 不带 `model`（openai）→ `ok` 为假、`error` 提示模型。
7. `fake_urlopen` 抛 `urllib.error.URLError("boom")` → `ok` 为假、`error` 含“连接失败”。

- [ ] **Step 2: 跑测试确认失败**

Run: `python\python.exe tests\_test_chat_api.py`
Expected: 404 / `ok` 缺失 → FAIL。

- [ ] **Step 3: 实现**

`md_server.py` 顶部常量区（`LLM_DEFAULTS` 附近）新增：

```python
# ---- AI 侧栏（/api/chat）的上下文预算与提示词 ----
CHAT_BUDGET = 32000
CHAT_MAX_DOC = 30000
CHAT_MAX_ONE = 20000
_CHAT_SYS = ("你是文档写作与阅读助手。用户在编辑一篇 Markdown 文档，会就选中的文字提问"
             "或要求改写。请围绕给定文本回答，使用 Markdown；不确定就说不确定，"
             "不要编造原文没有的事实；除非用户要求，不要重复原文。")


def _chat_prepare(obj):
    """把请求体收敛成 (消息列表, 选区, 全文, 是否截断)。

    消息只接受 user/assistant 与已知字段；末尾 assistant 丢掉；超预算先丢最早
    的一问一答，再截全文，最后截选区——最后一轮问题永远保留。
    """
    ctx = obj.get("context") if isinstance(obj.get("context"), dict) else {}
    sel_raw = str(ctx.get("selection") or "")
    doc_raw = str(ctx.get("document") or "")
    truncated = len(sel_raw) > CHAT_MAX_DOC or len(doc_raw) > CHAT_MAX_DOC
    sel = sel_raw[:CHAT_MAX_DOC]
    doc = doc_raw[:CHAT_MAX_DOC]
    msgs = []
    for m in (obj.get("messages") or []):
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            continue
        c = str(m.get("content") or "")
        if c.strip():
            msgs.append({"role": m["role"], "content": c})
    while msgs and msgs[-1]["role"] != "user":
        msgs.pop()
    if msgs and len(msgs[-1]["content"]) > CHAT_MAX_ONE:
        msgs[-1]["content"] = msgs[-1]["content"][:CHAT_MAX_ONE]
        truncated = True

    def total():
        return sum(len(m["content"]) for m in msgs) + len(sel) + len(doc)

    while len(msgs) > 1 and total() > CHAT_BUDGET:
        msgs = msgs[2:] if len(msgs) >= 2 and msgs[0]["role"] == "user" else msgs[1:]
        truncated = True
    over = total() - CHAT_BUDGET
    if over > 0 and doc:
        cut = min(len(doc), over)
        doc, over = doc[:-cut], over - cut
        truncated = True
    if over > 0 and sel:
        sel = sel[:-min(len(sel), over)]
        truncated = True
    return msgs, sel, doc, truncated
```

`do_POST` 里，紧跟现有 `if u.path in ("/api/llm-models", ...)` 那段之后加：

```python
        # ---- AI 侧栏：多轮对话（选区/全文作为 system 上下文）----
        if u.path == "/api/chat":
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "error": "请求体解析失败: %s" % e},
                                           ensure_ascii=False), "application/json; charset=utf-8")
                return
            try:
                msgs, sel, doc, truncated = _chat_prepare(obj)
                if not msgs:
                    self._send(200, json.dumps({"ok": False, "error": "没有可发送的消息"},
                                               ensure_ascii=False), "application/json; charset=utf-8")
                    return
                client = _llm_from_request(obj)
                if client.backend in ("ollama", "openai") and not client.model:
                    self._send(200, json.dumps({"ok": False,
                                                "error": "该后端需先在 AI 设置中选择模型"},
                                               ensure_ascii=False), "application/json; charset=utf-8")
                    return
                sysp = _CHAT_SYS
                ws_flag = "off"
                ws_cfg = _llm_config_from_request(obj).get("web_search") or {}
                if ws_cfg.get("enabled"):
                    if _ws_mod is None:
                        ws_flag = "degraded"
                    else:
                        sr = _ws_mod.WebSearch(ws_cfg).search(msgs[-1]["content"][:200])
                        if sr.get("success") and sr.get("results"):
                            ws_flag = "ok"
                            sysp += "\n\n【联网资料】\n" + _ws_mod.format_results(sr["results"])
                        else:
                            ws_flag = "degraded"
                if sel:
                    sysp += "\n\n【选中文本】\n" + sel
                if doc:
                    sysp += "\n\n【整篇文档】\n" + doc
                text = client.chat([{"role": "system", "content": sysp}] + msgs)
                self._send(200, json.dumps({"ok": True, "text": text,
                                            "web_search": ws_flag, "truncated": truncated},
                                           ensure_ascii=False), "application/json; charset=utf-8")
            except _LLM_ERR as e:
                self._send(200, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python\python.exe tests\_test_chat_api.py`
Expected: ALL PASS。

- [ ] **Step 5: 提交**

```bash
git add md_server.py tests/_test_chat_api.py
git commit -m "feat: /api/chat 多轮对话接口（选区/全文上下文 + 预算裁剪）"
```

---

### Task 2: 前端骨架（布局 / 入口 / 拖宽）

**Files:**
- Modify: `mdwright.html`（`<main>` 内加 `#aiResizer`、`#aiPane`；CSS；AI 菜单与选区气泡；快捷键；宽度持久化）
- Test: `tests/_test_chat_ui.py`（新建）

**Interfaces:**
- Produces: 全局（IIFE 内）`aiShow()`, `aiHide()`, `aiToggle()`；DOM id：`aiPane`、`aiResizer`、`aiMsgs`、`aiInput`、`aiSend`、`aiCtxBox`、`aiCtxText`、`aiWithDoc`、`aiNew`、`aiClose`、`aiMeta`；入口按钮 `btnAISidebar`、`selAI`。
- Consumes: 现有 `selTools`、`menu` 组件。

- [ ] **Step 1: 写失败测试**

`tests/_test_chat_ui.py` 用 `run_expr`（`from _test_browser import run_expr`），表达式做三件事：默认隐藏、点菜单打开、选中文字后气泡出现「问 AI」、点开后侧栏可见且引用正确、`Ctrl+Shift+A` 可开关、拖动后宽度写进 `localStorage`。

- [ ] **Step 2: 跑测试确认失败**

Run: `python\python.exe tests\_test_chat_ui.py`
Expected: FAIL（`#aiPane` 不存在）。

- [ ] **Step 3: 实现**

- `<main>` 末尾（`</main>` 前）插入 `#aiResizer` 与 `#aiPane` 结构（见 spec 4.1）。
- CSS 追加 `#aiPane / #aiResizer / .ai-head / #aiMsgs / .ai-msg / .ai-chips / .ai-compose` 一组样式（spec 4.1 的排版，颜色走现有变量）。
- AI 菜单在「AI 设置…」前加 `btnAISidebar`。
- `#selTools` 在「润色」后加 `selAI`，标题「选中文本向 AI 提问」。
- JS：`aiShow/aiHide/aiToggle`、宽度 restore/持久化、拖拽、`Ctrl+Shift+A`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python\python.exe tests\_test_chat_ui.py`

- [ ] **Step 5: 提交**

```bash
git add mdwright.html tests/_test_chat_ui.py
git commit -m "feat: AI 侧栏骨架（第三栏 / 入口 / 拖宽持久化）"
```

---

### Task 3: 会话发送与渲染

**Files:**
- Modify: `mdwright.html`
- Test: `tests/_test_chat_ui.py`（追加断言）

**Interfaces:**
- Produces: `ai = {msgs, ctx, busy, withDoc, lastDoc}`、`aiSend(text)`、`aiRenderMsgs()`、`aiSubmit()`。
- Consumes: `POST /api/chat`（Task 1）、`parseMarkdown()`、`showToast()`。

- [ ] **Step 1: 写失败测试**：stub `window.fetch` 拦 `/api/chat`，断言请求体 `messages` 顺序与 `context.selection`，回答渲染为 Markdown（`<strong>`），失败时出现 `.ai-msg.err` 且「重试」可用。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**：消息数组、渲染、发送（`ai.busy` 防重入）、Enter/Shift+Enter、错误气泡 + 重试、`truncated` 提示。

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add mdwright.html tests/_test_chat_ui.py
git commit -m "feat: AI 侧栏多轮对话（发送 / 渲染 / 错误重试）"
```

---

### Task 4: 上下文、快捷动作与回写

**Files:**
- Modify: `mdwright.html`
- Test: `tests/_test_chat_ui.py`（追加断言）

**Interfaces:**
- Produces: `aiSetCtx()`、`aiRenderCtx()`、`aiDocChanged()`、`aiReplace(idx, msg)`；`data-ai-act` 五个快捷动作；`data-ai-do` 的 copy/insert/replace/retry。
- Consumes: `getSel()`、`getText()`、`setSel()`、`insertPlainText()`、`scheduleRender()`、`scheduleSave()`。

- [ ] **Step 1: 写失败测试**：选区上下文显示与字数；`withDoc` 勾选后请求体带 `context.document`；点快捷动作直接发请求；插入后 `#editor` 文本包含回答；替换后原文被换掉、再点替换被禁用；改掉原文后替换提示失败；`updateFileIndicator` 触发新文档时消息清空。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**：`aiSetCtx/aiRenderCtx/aiDocChanged`（挂到 `updateFileIndicator`）、快捷动作提示词表、`aiReplace` 快照校验、按钮动作。

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add mdwright.html tests/_test_chat_ui.py
git commit -m "feat: AI 侧栏上下文、快捷动作与插入/替换"
```

---

### Task 5: 文档、版本与全量回归

**Files:**
- Modify: `md_server.py`（`MD_SERVER_VERSION` +1、`APP_VERSION` = "3.5.0"）
- Modify: `CHANGELOG.md`（首段 `## v3.5.0`）
- Modify: `docs/MDWright 使用指南.md`（新增「AI 侧栏」一节）
- Modify: `README.md`（功能表加一行）
- Test: 全量 `tests/run_all.py`

- [ ] **Step 1: 版本与 CHANGELOG**

- [ ] **Step 2: 文档**

使用指南写清：怎么打开、上下文怎么带、五个快捷动作、插入/替换的限制（预览模式不可用）、内容只发往配置的 AI 后端。

- [ ] **Step 3: 全量回归**

Run: `cmd /c md_stop.cmd` 然后 `python\python.exe tests\run_all.py`
Expected: 除既有基线 `_test_rag_e2e`（本机无 rag-assistant）外全绿。

- [ ] **Step 4: 手工验收一次内嵌窗口**

双击一个 `.md` → 选中一段 → 「问 AI」→ 侧栏出现、上下文正确 → 发一句（本地 LM Studio 未开时应给出可读错误）→ 关掉侧栏再开，宽度与勾选保持。

- [ ] **Step 5: 提交**

```bash
git add md_server.py CHANGELOG.md "docs/MDWright 使用指南.md" README.md
git commit -m "docs: v3.5.0 AI 侧栏说明与版本号"
```
