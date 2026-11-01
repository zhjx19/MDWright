# 选中文本 · AI 侧栏设计（v3.5.0）

日期：2026-11-01　状态：待评审

## 1. 目标

在编辑器里选中一段文字，点气泡上的「问 AI」，右侧打开一个可追问的对话栏；回答能一键插入光标处或替换原选区。

一次做完的四件事：

1. **侧栏**：`#main` 增加第三栏，可开关、可拖宽、宽度记住。
2. **多轮对话**：同一选区可连续追问，历史只在本窗口内存里。
3. **快捷动作**：解释 / 润色 / 翻译 / 压缩 / 找问题，点一下就走。
4. **回写**：助手回答可复制、插入到光标处、替换原选区（带原文快照校验）。

## 2. 现状与缺口

| 事实 | 位置 | 后果 |
|---|---|---|
| 选区气泡只有「备注 / 润色 / ▶运行 / RAG润色」 | `mdwright.html` `#selTools` | 想追问只能反复选中、重新点润色 |
| 「润色」是全屏 Modal，单轮、只能整段替换 | `rwOverlay` / `/api/rewrite` | 没有对话，也看不到解释过程 |
| 后端只有 `polish` / `explain` 两个固定提示词 | `llm_client.py` | 没有通用对话入口 |
| LLM 配置、联网检索、错误归一都已存在 | `llm_client` / `_llm_from_request` | 新接口可直接复用，不引第三方依赖 |

## 3. 决策（已与用户确认）

| 议题 | 决定 | 理由 |
|---|---|---|
| 交互形态 | **多轮对话 + 快捷动作 + 插入/替换** | 一次投入覆盖「问一句」和「改一段」两类需求 |
| 输出方式 | **非流式**（先占位、再一次给全文） | 服务端现有 `urllib` 客户端是整包返回；流式要另做 SSE 与中断语义，留到下一版 |
| 上下文 | **默认只带选区**，可勾选「附带整篇文档」 | 选区足够回答问题，也避免长文档把本地模型拖慢 |
| 会话生命周期 | **单会话、纯内存、切文档即清空** | 不把 A 文档的内容带进 B 文档；不往 `assets/` 写一个新文件类型 |
| 与「润色」的关系 | **保留现有 Modal 不动** | 单段替换仍是最高频路径，Modal 的左右对照更适合它 |
| RAG / 流式 | **本版不做** | 控制范围；接口与 UI 都留了扩展位 |

## 4. 架构

### 4.1 布局与 DOM

```
<main id="main">
  <nav id="outline">…</nav>
  <section id="editorPane">…</section>
  <section id="previewPane">…</section>
  <div id="aiResizer" hidden></div>
  <aside id="aiPane" hidden>…</aside>
</main>
```

- `#aiPane`：`flex:0 0 var(--ai-w,360px)`，`min-width:280px`、`max-width:640px`，`border-left`。
- `#aiResizer`：5px 竖条，`cursor:col-resize`；拖动改 `--ai-w`，松手写 `localStorage['md-ai-w']`。
- 侧栏内部（自上而下）：

| 区块 | 元素 | 行为 |
|---|---|---|
| 标题栏 | 标题、「选中 N 字」、`＋` 新对话、`×` 关闭 | `＋` 清空当前会话（保留选区上下文） |
| 上下文块 | 引用块（默认折 3 行，点击展开）、`附带整篇文档` 勾选 | 勾选状态记 `localStorage['md-ai-withdoc']` |
| 消息区 | `#aiMsgs`，用户/助手气泡 | 助手气泡内用 `parseMarkdown()` 渲染（该函数已对 HTML 转义） |
| 快捷动作 | 解释 / 润色 / 翻译 / 压缩 / 找问题 | 有选区时直接发送，无选区时提示先选中 |
| 输入区 | `textarea` + 发送按钮 | `Enter` 发送、`Shift+Enter` 换行；生成中禁用 |
| 页脚 | 「内容只发给你配置的 AI 后端」 | 常驻一行小字 |

### 4.2 状态

```js
var ai = {
  msgs: [],      // [{role:'user'|'assistant', content:string, error?:bool}]
  ctx: null,     // {s, e, text} —— 打开侧栏那一刻冻结的选区快照
  busy: false,   // 有请求在飞（同一时刻只允许一个）
  withDoc: false
};
```

- **上下文在打开侧栏时冻结**：之后用户再选别的文字，不改变本轮对话的上下文；要换上下文就再点一次气泡的「问 AI」。
- **切文档即清空**：`openFile` / `newDoc` / `.smd` 载入后调用 `aiReset()`；若侧栏开着，消息区插一条系统提示「已切换文档，开始新对话」。
- **不持久化**：消息只在本窗口内存；关闭程序即丢。
- **宽度持久化**，开关状态不持久化（避免下次打开意外挤压排版）。

### 4.3 交互流程

1. 源文里选中文字 → 气泡出现 → 点「问 AI」。
2. 侧栏打开（若已关）、`ai.ctx` 冻结、上下文块显示引用首行与字数、输入框聚焦。
3. 用户输入或点快捷动作 → 组装请求 → 用户气泡入列 + 助手位置显示「正在生成…」。
4. 响应回来：替换占位；失败则换成错误气泡，带「重试」与「打开 AI 设置」。
5. 助手气泡底部常驻三个动作：
   - **复制**：`navigator.clipboard.writeText`，失败回退 `document.execCommand('copy')`。
   - **插入**：在编辑器当前光标处插入纯文本（`insertPlainText`），走原生 undo 栈。
   - **替换**：仅 `ai.ctx` 存在且编辑区可见时可用；先校验快照（见 4.5），成功后禁用该条的「替换」，`scheduleRender(); scheduleSave();`。

入口共三处：工具栏「AI」菜单 → 「AI 侧栏」；选区气泡「问 AI」；快捷键 `Ctrl+Shift+A`（现有快捷键只有 `Ctrl+N` / `Ctrl+S`，不冲突）。

### 4.4 后端：`POST /api/chat`

请求：

```json
{
  "messages": [
    {"role": "user", "content": "这段在说什么？"},
    {"role": "assistant", "content": "…"},
    {"role": "user", "content": "再短一点"}
  ],
  "context": {"selection": "被选中的原文…", "document": null},
  "config": {"backend": "lmstudio", "model": "…"}
}
```

- `context.selection`：打开侧栏时冻结的选区原文；没有选区时为 `null`。
- `context.document`：勾选「附带整篇文档」时才是文档全文，否则 `null`。
- `config`：可选。与 `/api/rewrite` 一致——不带就读 `runtime/settings.json`，带了就用请求体里的（测试与「临时换后端」都靠它）。

响应（业务失败也返回 200，与现有 `/api/rewrite` 约定一致）：

```json
{"ok": true, "text": "…", "web_search": "off|ok|degraded", "truncated": false}
{"ok": false, "error": "后端需先在 AI 设置中选择模型"}
```

校验与限额：

| 项 | 规则 |
|---|---|
| `messages` | 只接受 `user` / `assistant`；必须存在且最后一条是 `user`；单条 `content` 非空 |
| 总长度 | `messages` + `context.selection` + `context.document` 合计 ≤ 32000 字符；超出时**从最早的一问一答开始丢**，仍超就先截 `document`、再截 `selection`，响应带 `truncated: true` |
| 单条上限 | 最新一条 user 消息 > 20000 字符时截断并置 `truncated: true` |
| `context.selection` | ≤ 30000 字符；空 / `null` 则不注入 |
| `context.document` | ≤ 30000 字符；与 `selection` 一起计入总预算，超出先截文档尾部 |
| 模型检查 | 与 `/api/rewrite` 相同：ollama / openai 兼容后端必须已选模型 |
| 联网 | 若 AI 设置里开启了联网查询，用**最新一条 user 消息**当查询词，结果拼进 system prompt；失败降级为纯模型，并在响应里如实标 `degraded` |

组装后的消息序列：

```
system: 你是文档写作与阅读助手……（写作约束）
system: 【选中文本】\n<context.selection>        （非空时）
system: 【整篇文档】\n<context.document>      （非空时）
messages: [...]                                （已裁剪的历史）
```

错误处理：沿用 `LLMError` → `{ok:false,error}`；HTTP 层异常才回 500。服务端不缓存、不共享会话状态（多窗口互不影响）。

隐私：文本只发往用户配置的 LLM 端点（默认本机 LM Studio / Ollama）；不经过本项目任何服务器。

### 4.5 替换的定位与安全

沿用润色 Modal 已验证的做法：

1. 发请求时记下 `{s, e, text}`（`ai.ctx` 的副本）。
2. 点「替换」时读取当前 `getText()`；若 `now.substring(s,e) === text` 就直接用。
3. 否则 `now.indexOf(text)` 重新定位；找不到 → 提示「原文已变化，请重新选中后重试」，不改文档。
4. 用 `setSel(s,e)` + `insertPlainText(answer)` 覆盖，随后 `scheduleRender(); scheduleSave();`。
5. 成功后禁用该条的「替换」，避免二次点击把新内容再包一层。

## 5. 错误与边界

| 场景 | 表现 |
|---|---|
| 未配置模型 / 后端连不上 | 错误气泡 + 「打开 AI 设置」；不丢用户已输入的内容 |
| 超时（默认 180s） | 错误气泡写明超时；「重试」重发最后一条 |
| 请求在飞时再点发送 | 发送按钮禁用，`ai.busy` 挡住 |
| 文档切换 / 新建 | 清空会话；侧栏保持打开状态 |
| 预览 / 即时渲染模式 | 侧栏可用、可问；「插入 / 替换」置灰（编辑区不可见） |
| 选区为空 | 气泡不显示；快捷动作提示「先选中一段文字」 |
| 文档超长（附带整篇） | 侧栏显示「文档过长，已截断」，请求带 `truncated` |

## 6. 测试

- `tests/_test_chat_api.py`（新）：起假 OpenAI 兼容端点；断言多轮顺序、system 里带选区、超长裁剪与 `truncated`、空消息、未选模型、连不上五种情况。
- `tests/_test_chat_ui.py`（新）：playwright；没装则 `exit 77`（SKIP）。断言：气泡 → 侧栏打开、上下文文案正确、请求体含 messages/context、回答渲染、插入与替换生效、失败重试、切文档清空、宽度持久化、`Ctrl+Shift+A`。
- 回归：`_test_llm_ui.py`、`_test_smd_ann.py`、`_test_menu_ui.py` 必须仍绿。

## 7. 发布

- `MD_SERVER_VERSION` +1（新增路由）；`APP_VERSION` → `3.5.0`；`CHANGELOG.md` 首段按体例写。
- 文档：使用指南新增「AI 侧栏」一节；README 功能表加一行。
- 分发清单不新增文件（前端仍是单文件 `mdwright.html`，无新依赖）。

## 8. 风险与取舍

| 风险 | 处置 |
|---|---|
| 单文件前端再长 ~400 行 | 可接受；解析与启动成本经实测主要不在这里 |
| 长上下文拖慢本地模型 | 默认只带选区；历史裁剪；上下文块显示字数 |
| 模型输出注入 HTML | 复用 `parseMarkdown`（已 `escapeHtml`），不直接 `innerHTML` 模型原文 |
| 替换打错位置 | 原文快照 + `indexOf` 复核 + 失败不改文档 + 成功后禁用 |
| 无流式导致「等很久没反应」 | 占位文案写「正在生成…（本地模型可能需要一些时间）」，与现有润色一致 |

## 9. 本版不做

流式输出、RAG 检索、会话持久化 / 跨文档共享、预览区选区、生成中断、token 用量显示。
