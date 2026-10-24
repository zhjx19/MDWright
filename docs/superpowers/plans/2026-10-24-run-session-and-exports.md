# 代码块运行会话与导出链路 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 R/Python 代码块共享一个常驻解释器会话、运行结果落盘并在重开后恢复、导出 Word 时带上结果与三线表，同时把文件菜单拆成「最近文件 / 内置文档」并新增「关于」。

**Architecture:** 新增 `md_runs.py` 承担两件事——常驻解释器会话（每「文档 × 语言」一个进程，文件握手协议）与运行结果侧车（`.md` / `.smd` / 未命名三种落点）。`md_server.py` 只做 HTTP 转发；`md_pandoc.py` 增加「按代码原文把输出注入 markdown」与「docx 三线表 XML 改写」两个纯函数；`mdwright.html` 负责恢复与展示。

**Tech Stack:** Python 3.11 标准库（`subprocess` / `threading` / `zipfile` / `xml.etree`）、Base R、原生 HTML+JS；测试沿用仓库既有 `_test_*.py` 独立用例模式（无 pytest）。

**Spec:** `docs/superpowers/specs/2026-10-24-run-session-and-exports-design.md`

## Global Constraints

- 后端只用标准库与 Base R，**不得引入第三方依赖**；R 驱动不得依赖 jsonlite。
- 现有 `/api/run-r` / `/api/run-py` 的入参 `{code}` 与出参字段（`ok/stdout/stderr/error/image/runtime/python`）**必须保持向后兼容**；无 `doc`/`token` 时退化为一次性执行。
- 单次执行超时默认 60 秒；超时杀会话，下次运行自动重建。
- 输出按代码原文匹配（`(lang, code)` 全等），代码改动即视为无输出，不展示过期结果。
- `.smd` 的运行产物必须放包内 `runs/`，**不得放 `assets/`**（`save_from_dir()` 会清理未引用的孤儿资产）。
- 新运行文件 `md_runs.py` 必须同时登记到 `installer/_build_installer.py` 的 `DIST_FILES` 与 `docs/分发清单.md`。
- 所有写盘路径在服务端规范化；前端不拼绝对路径。
- 测试一律 `python\python.exe tests\_test_xxx.py` 单跑，全套 `python\python.exe tests\run_all.py`；跑全套前先 `md_stop.cmd`。

## Review Focus

- **同一文档两块同时点运行**：第二块必须得到 409 与「上一块还在运行」，而不是两个请求抢同一个解释器把输出写串。
- **代码改一个字后重开文档**：旧输出不得出现（匹配不上就是空），不能错位贴到别的块上。
- **R 代码里用户自己调 `sink()` / 画图**：不能把会话的握手通道弄坏，`DONE` 标记必须仍能到达。
- **`.smd` 保存一次后运行图仍在**：孤儿清理不得吃掉 `runs/`。
- **Word 三线表后的文件仍能被打开**：元素顺序不合 schema 会直接报「文件已损坏」，必须回读自检。

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `md_runs.py`（新增） | 会话进程池 + 侧车读写 + 图片落位。对外：`run_code()` / `read_outputs()` / `reset()` / `gc_idle()` / `shutdown_all()` |
| `md_server.py` | `/api/run-*` 端点转发、`APP_VERSION`、`/api/version` 增 `app` 字段、`/api/export-docx` 增 `threeLine` |
| `md_pandoc.py` | `inject_run_outputs()`（注入）+ `three_line_tables()`（改 XML） |
| `_smd.py` | `write_runs_entries()` / `read_runs_entry()`（包内 `runs/` 读写） |
| `mdwright.html` | 输出恢复、`⟳ 会话` 按钮、文件菜单拆分、关于窗口 |
| `tests/_test_run_session.py` | 会话层 |
| `tests/_test_run_outputs.py` | 侧车三种落点 |
| `tests/_test_run_export.py` | Word 注入 + 三线表 |
| `tests/_test_run_ui.py` | 浏览器级：变量复用、刷新恢复、重置按钮 |
| `tests/_test_about.py` | 菜单拆分 + 关于窗口 |

---

### Task 1: 常驻会话（`md_runs.py` + 两个驱动）

**Files:**
- Create: `md_runs.py`
- Modify: `md_server.py`（`/api/run-r`、`/api/run-py` 改为委托；新增 `/api/run-reset`）
- Test: `tests/_test_run_session.py`

**Interfaces:**
- Produces:
  - `run_code(lang, code, doc_key, timeout=60) -> dict`，返回键：`ok, stdout, stderr, error, image, runtime, python, restarted, timeout`
  - `reset(doc_key=None, lang=None) -> list[str]`（返回被杀掉的键）
  - `gc_idle() -> None`、`shutdown_all() -> None`
  - `doc_key_of(doc, token) -> str`
- Consumes: `md_tools.version_of`（已有）

- [ ] **Step 1: 写失败测试**

```python
# tests/_test_run_session.py
# -*- coding: utf-8 -*-
"""常驻会话：变量跨块、超时、重置、并发拒绝。"""
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
import json, sys, threading, time, urllib.error, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.argv = ["md_server.py"]
import md_server  # noqa: E402

PORT = 18791
httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)
fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


def post(path, obj, timeout=120):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


def main():
    doc = "T:/runsession/probe.md"
    # R：变量跨两次请求
    post("/api/run-r", {"code": "x <- 41", "doc": doc})
    r, _ = post("/api/run-r", {"code": "x + 1", "doc": doc})
    check("R 变量跨块存活", r.get("ok") is True and "42" in (r.get("stdout") or ""),
          str(r)[:200])

    # Python：变量跨两次请求
    post("/api/run-py", {"code": "y = 41", "doc": doc})
    p, _ = post("/api/run-py", {"code": "print(y + 1)", "doc": doc})
    check("Python 变量跨块存活", p.get("ok") is True and "42" in (p.get("stdout") or ""),
          str(p)[:200])

    # 报错不杀会话：出错后再用旧变量仍可用
    post("/api/run-r", {"code": "stop('boom')", "doc": doc})
    r2, _ = post("/api/run-r", {"code": "x * 2", "doc": doc})
    check("R 报错后会话仍可用", r2.get("ok") is True and "82" in (r2.get("stdout") or ""),
          str(r2)[:200])

    # 超时：杀掉会话，下次重建
    t, _ = post("/api/run-r", {"code": "Sys.sleep(3)", "doc": doc, "timeout": 1})
    check("超时返回错误", t.get("ok") is False and "超时" in (t.get("error") or ""),
          str(t)[:200])
    r3, _ = post("/api/run-r", {"code": "exists('x')", "doc": doc})
    check("超时后自动重建且变量已丢",
          r3.get("ok") is True and "FALSE" in (r3.get("stdout") or "")
          and r3.get("restarted") is True, str(r3)[:200])

    # 并发：一块在跑时第二块被拒
    out = {}

    def slow():
        out["a"], code = post("/api/run-r", {"code": "Sys.sleep(2)", "doc": doc}, timeout=60)
        out["code"] = code

    th = threading.Thread(target=slow)
    th.start()
    time.sleep(0.5)
    second, sc = post("/api/run-r", {"code": "1", "doc": doc}, timeout=10)
    th.join(timeout=60)
    check("并发第二块被拒 409", sc == 409 and "还在运行" in (second.get("error") or ""),
          "%s %s" % (sc, str(second)[:160]))

    # 重置：变量清空
    post("/api/run-reset", {"doc": doc})
    r4, _ = post("/api/run-r", {"code": "exists('x')", "doc": doc})
    check("重置后变量消失", "FALSE" in (r4.get("stdout") or ""), str(r4)[:200])

    # 无 doc/token：一次性执行，不跨块
    post("/api/run-r", {"code": "z <- 1"})
    r5, _ = post("/api/run-r", {"code": "exists('z')"})
    check("无 doc 时退化为一次性执行", "FALSE" in (r5.get("stdout") or ""), str(r5)[:200])

    md_server.md_runs.shutdown_all()
    httpd.shutdown(); httpd.server_close()
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python\python.exe tests\_test_run_session.py`
Expected: FAIL —— `ModuleNotFoundError: No module named 'md_runs'` 或 `/api/run-reset` 404。

- [ ] **Step 3: 新建 `md_runs.py`（会话部分）**

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
"""代码块运行：常驻解释器会话 + 运行结果侧车。

会话协议（不依赖 jsonlite / 任何第三方包）：
  父进程把源码写进 <workdir>/<id>.code，向子进程 stdin 写一行 <id>；
  子进程执行后写 <id>.out.txt / <id>.err.txt / <id>.png(R) / <id>.status，
  再往 stdout 回一行 `DONE <id>`。父进程等到这一行（或超时杀进程）后读文件。
"""
import hashlib
import io
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_SESS = {}                    # (doc_key, lang) -> _Session
_BUSY = set()                 # 正在跑的 key
_GUARD = threading.RLock()
IDLE_SECONDS = 30 * 60

_R_DRIVER = r'''
args <- commandArgs(trailingOnly = TRUE); wd <- args[1]; setwd(wd)
repeat {
  id <- readLines("stdin", n = 1, warn = FALSE)
  if (length(id) == 0) break
  id <- trimws(id); if (id == "") next
  if (id == "QUIT") break
  code <- paste(readLines(file.path(wd, paste0(id, ".code")), warn = FALSE,
                          encoding = "UTF-8"), collapse = "\n")
  err <- NULL
  con_err <- file(file.path(wd, paste0(id, ".err.txt")), open = "wt", encoding = "UTF-8")
  sink(file.path(wd, paste0(id, ".out.txt")), split = FALSE)
  sink(con_err, type = "message")
  png(file.path(wd, paste0(id, ".png")), width = 1200, height = 800, res = 150)
  exprs <- tryCatch(parse(text = code),
                    error = function(e) { err <<- conditionMessage(e); NULL })
  if (!is.null(exprs)) {
    for (i in seq_along(exprs)) {
      if (!is.null(err)) break
      r <- tryCatch(withVisible(eval(exprs[[i]], envir = globalenv())),
                    error = function(e) { err <<- conditionMessage(e); NULL })
      if (is.null(err) && !is.null(r)) {
        v <- r$value
        if (is.function(v)) tryCatch(v(), error = function(e) err <<- conditionMessage(e))
        else if (isTRUE(r$visible)) print(v)
      }
    }
  }
  try(invisible(dev.off()), silent = TRUE)
  try(sink(type = "message"), silent = TRUE); try(sink(), silent = TRUE)
  try(close(con_err), silent = TRUE)
  writeLines(if (is.null(err)) "ok" else paste0("err\t",
             gsub("[\r\n]+", " ", err)), file.path(wd, paste0(id, ".status")))
  cat("DONE ", id, "\n", sep = ""); flush(stdout())
}
'''

_PY_DRIVER = r'''
import contextlib, io, os, sys, traceback
wd = sys.argv[1]
ns = {"__name__": "__main__"}
for line in sys.stdin:
    rid = line.strip()
    if not rid:
        continue
    if rid == "QUIT":
        break
    code = io.open(os.path.join(wd, rid + ".code"), encoding="utf-8").read()
    ob, eb = io.StringIO(), io.StringIO()
    err = ""
    try:
        with contextlib.redirect_stdout(ob), contextlib.redirect_stderr(eb):
            exec(compile(code, "<block>", "exec"), ns)
    except SystemExit:
        pass
    except BaseException:
        err = traceback.format_exc().strip().splitlines()[-1]
    io.open(os.path.join(wd, rid + ".out.txt"), "w", encoding="utf-8").write(ob.getvalue())
    io.open(os.path.join(wd, rid + ".err.txt"), "w", encoding="utf-8").write(eb.getvalue())
    io.open(os.path.join(wd, rid + ".status"), "w", encoding="utf-8").write(
        "ok" if not err else "err\t" + err)
    sys.stdout.write("DONE " + rid + "\n")
    sys.stdout.flush()
'''


def doc_key_of(doc, token):
    """文档键：有路径用规范路径，否则用前端令牌；都没有返回空（一次性执行）。"""
    if doc:
        return os.path.normcase(os.path.abspath(doc))
    if token:
        return "untitled:" + str(token)
    return ""


def _workdir(key, lang):
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    d = os.path.join(HERE, "runtime", "tmp", "runs", "sess", h + "-" + lang)
    os.makedirs(d, exist_ok=True)
    return d


def _r_exe():
    import md_tools
    try:
        settings = _load_settings()
        cfg = (settings.get("tools") if isinstance(settings, dict) else {}) or {}
        p = md_tools.find_rscript(md_tools._cfg(cfg, "rscript_path", "rscript"))
    except Exception:
        p = None
    return p or md_tools.find_rscript("rscript")


def _load_settings():
    import json
    p = os.path.join(HERE, "runtime", "settings.json")
    try:
        with io.open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class _Session(object):
    def __init__(self, key, lang, exe, workdir):
        self.key, self.lang, self.workdir = key, lang, workdir
        self.seq = 0
        self.dead = False
        self.used = time.time()
        driver = os.path.join(workdir, "_driver.py" if lang == "python" else "_driver.R")
        with io.open(driver, "w", encoding="utf-8", newline="\n") as f:
            f.write(_PY_DRIVER if lang == "python" else _R_DRIVER)
        argv = ([exe, "-u", "-X", "utf8", driver, workdir] if lang == "python"
                else [exe, driver, workdir])
        self.proc = subprocess.Popen(argv, cwd=workdir, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", errors="replace",
                                     bufsize=1, creationflags=_NO_WINDOW)

    def kill(self):
        self.dead = True
        try:
            self.proc.kill()
        except Exception:
            pass

    def run(self, code, timeout):
        self.used = time.time()
        self.seq += 1
        rid = "b%04d" % self.seq
        with io.open(os.path.join(self.workdir, rid + ".code"), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write(code)
        for ext in (".out.txt", ".err.txt", ".status", ".png"):
            try:
                os.remove(os.path.join(self.workdir, rid + ext))
            except OSError:
                pass
        try:
            self.proc.stdin.write(rid + "\n")
            self.proc.stdin.flush()
        except Exception:
            self.dead = True
            return {"ok": False, "error": "会话已断开", "timeout": False}
        timer = threading.Timer(timeout, self.kill)
        timer.start()
        try:
            line = self.proc.stdout.readline()
        finally:
            timer.cancel()
        if line.strip() != "DONE " + rid:
            self.dead = True
            return {"ok": False, "error": "执行超时（%d 秒）或会话中断" % timeout,
                    "timeout": True}
        return self._collect(rid)

    def _collect(self, rid):
        def _read(ext):
            try:
                with io.open(os.path.join(self.workdir, rid + ext),
                             encoding="utf-8", errors="replace") as f:
                    return f.read()
            except Exception:
                return ""
        status = _read(".status").strip()
        out, err = _read(".out.txt")[:20000], _read(".err.txt")[:20000]
        bad = status.startswith("err")
        png = os.path.join(self.workdir, rid + ".png")
        return {"ok": not bad,
                "stdout": out, "stderr": err,
                "error": status.split("\t", 1)[1] if bad and "\t" in status else "",
                "image": png if os.path.isfile(png) else "", "timeout": False}


def _spawn(key, lang):
    if lang == "python":
        import md_tools
        try:
            settings = _load_settings()
            cfg = (settings.get("tools") if isinstance(settings, dict) else {}) or {}
            exe = md_tools.find_python(md_tools._cfg(cfg, "python_path", "python")) \
                or sys.executable
        except Exception:
            exe = sys.executable
    else:
        exe = _r_exe()
        if not exe:
            raise RuntimeError("未检测到 Rscript：请在「设置 → 外部工具」填写路径")
    return _Session(key, lang, exe, _workdir(key, lang))


def run_code(lang, code, doc_key, timeout=60):
    key = (doc_key, lang)
    if not doc_key:
        # 一次性执行：建临时会话，跑完即杀（保持旧行为）
        s = _spawn("oneshot", lang)
        try:
            return s.run(code, timeout)
        finally:
            s.kill()
    with _GUARD:
        if key in _BUSY:
            return {"busy": True, "ok": False, "error": "上一块还在运行，请等它结束"}
        _BUSY.add(key)
    restarted = False
    try:
        with _GUARD:
            s = _SESS.get(key)
            if s is None or s.dead:
                if s is not None:
                    restarted = True
                s = _spawn(key[0], lang)
                _SESS[key] = s
        res = s.run(code, timeout)
        res["restarted"] = restarted
        return res
    finally:
        with _GUARD:
            _BUSY.discard(key)


def reset(doc_key=None, lang=None):
    killed = []
    with _GUARD:
        for k in list(_SESS):
            if (doc_key is None or k[0] == doc_key) and (lang is None or k[1] == lang):
                _SESS.pop(k).kill()
                killed.append("%s/%s" % (k[0], k[1]))
    return killed


def gc_idle():
    now = time.time()
    with _GUARD:
        for k in list(_SESS):
            s = _SESS[k]
            if s.dead or now - s.used > IDLE_SECONDS:
                _SESS.pop(k).kill()


def shutdown_all():
    with _GUARD:
        for s in list(_SESS.values()):
            s.kill()
        _SESS.clear()
```

- [ ] **Step 4: 改 `md_server.py` 的三个端点**

在 `/api/run-py`、`/api/run-r` 分支里把「自己起进程」换成委托；新增 `/api/run-reset`：

```python
        if u.path in ("/api/run-r", "/api/run-py"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                lang = "r" if u.path.endswith("-r") else "python"
                code = obj.get("code") or ""
                key = md_runs.doc_key_of((obj.get("doc") or "").strip(),
                                         (obj.get("token") or "").strip())
                timeout = int(obj.get("timeout") or 60)
                res = md_runs.run_code(lang, code, key, timeout=timeout)
                if res.get("busy"):
                    self._send(409, json.dumps({"ok": False, "error": res["error"]},
                                               ensure_ascii=False))
                    return
                # 图片与侧车处理在 Task 2 接上；此处先原样返回
                self._send(200, json.dumps(res, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/run-reset":
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                killed = md_runs.reset((obj.get("doc") or "").strip() or None,
                                       obj.get("lang") or None)
                self._send(200, json.dumps({"ok": True, "killed": killed},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
```

同时在文件顶部 `import md_runs`，服务启动时起一条回收线程，并在退出路径（现有 `atexit` 或 `finally`）加 `md_runs.shutdown_all()`：

```python
def _start_run_gc():
    def _loop():
        while True:
            time.sleep(300)
            try:
                md_runs.gc_idle()
            except Exception:
                pass
    t = threading.Thread(target=_loop, name="run-session-gc", daemon=True)
    t.start()
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python\python.exe tests\_test_run_session.py`
Expected: `ALL PASS`

- [ ] **Step 6: 回归既有运行用例**

Run: `python\python.exe tests\_test_run_r.py` 与 `_test_run_py.py`
Expected: 两个都 ALL PASS（无 doc 时走一次性执行，行为不变）。

- [ ] **Step 7: 提交**

```bash
git add md_runs.py md_server.py tests/_test_run_session.py
git commit -m "feat: R/Python 代码块常驻会话（变量跨块）"
```

---

### Task 2: 输出侧车（`.md` / `.smd` / 未命名）

**Files:**
- Modify: `md_runs.py`（新增侧车读写 + 图片落位）、`md_server.py`（`/api/run-*` 写盘、新增 `GET /api/run-outputs`）、`_smd.py`（包内 `runs/` 读写）
- Test: `tests/_test_run_outputs.py`

**Interfaces:**
- Produces（`md_runs.py`）：
  - `read_outputs(doc_path, token) -> list[dict]`
  - `save_output(lang, code, res, doc_path, token) -> dict`（返回给前端的条目，含 `image` 相对引用）
  - `asset_ref(doc_path, token, image_abs) -> str`（前端可直接放进 `<img src>`）
- Consumes：Task 1 的 `run_code()`

- [ ] **Step 1: 写失败测试**

```python
# tests/_test_run_outputs.py
# -*- coding: utf-8 -*-
"""侧车：三种落点、代码改动失效、坏文件容错、.smd 孤儿清理不吃 runs/。"""
import io, json, os as _os, sys as _sys, shutil, tempfile, time
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
sys.path.insert(0, _ROOT)
import md_runs, _smd  # noqa: E402

fails = []
def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)

def main():
    tmp = tempfile.mkdtemp(prefix="mdruns-")
    try:
        # --- .md：落点与图片 ---
        doc = os.path.join(tmp, "a.md")
        io.open(doc, "w", encoding="utf-8").write("# t\n")
        png = os.path.join(tmp, "src.png")
        shutil.copy2(os.path.join(_ROOT, "docs", "screenshots", "writing.png"), png)
        entry = md_runs.save_output("r", "x <- 1", {"stdout": "[1] 1\n", "image": png},
                                    doc, "")
        store = os.path.join(tmp, "a.md.assets", "runs", "run-outputs.json")
        check(".md 侧车落位", os.path.isfile(store), store)
        check(".md 图片落到 runs/", bool(entry.get("image")) and
              os.path.isfile(os.path.join(tmp, "a.md.assets", "runs",
                                          os.path.basename(entry["image"]))), str(entry))
        back = md_runs.read_outputs(doc, "")
        check("读回按代码匹配", any(b["code"] == "x <- 1" for b in back), str(back)[:200])

        # --- 代码改动 → 匹配不到 ---
        check("代码改动后匹配不到",
              not any(b["code"] == "x <- 2" for b in back), str(back)[:120])

        # --- 坏文件容错 ---
        io.open(store, "w", encoding="utf-8").write("{坏 json")
        check("侧车损坏当空", md_runs.read_outputs(doc, "") == [], "")
        io.open(store, "w", encoding="utf-8").write("{}" )

        # --- .smd：包内 runs/ 且保存不清理 ---
        smd = os.path.join(tmp, "b.smd")
        src_dir = os.path.join(tmp, "pack")
        os.makedirs(os.path.join(src_dir, "assets"), exist_ok=True)
        io.open(os.path.join(src_dir, "doc.md"), "w", encoding="utf-8").write("# t\n")
        _smd.pack_from_dir(smd, os.path.join(src_dir, "doc.md"),
                           os.path.join(src_dir, "assets"))
        md_runs.save_output("r", "y <- 2", {"stdout": "ok\n", "image": png}, smd, "")
        import zipfile
        with zipfile.ZipFile(smd) as z:
            names = z.namelist()
        check(".smd 包内有 runs/侧车", any(n.startswith("runs/") for n in names), str(names)[:200])
        bdir = _smd.base_dir_for(smd)
        # 触发一次 .smd 保存（会清理 assets/ 孤儿）后，runs/ 仍在
        io.open(os.path.join(bdir, "doc.md"), "a", encoding="utf-8").write("追加\n")
        _smd.save_from_dir(smd, bdir)
        with zipfile.ZipFile(smd) as z:
            names2 = z.namelist()
        check(".smd 保存后 runs/ 未被清理",
              any(n.startswith("runs/") for n in names2), str(names2)[:200])

        # --- 未命名：临时区 ---
        e3 = md_runs.save_output("python", "z = 3", {"stdout": "3\n"}, "", "tok123")
        check("未命名落点在 runtime/tmp/runs", os.path.isfile(os.path.join(
            _ROOT, "runtime", "tmp", "runs", "tok123", "run-outputs.json")), str(e3))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        md_runs.shutdown_all()
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python\python.exe tests\_test_run_outputs.py`
Expected: FAIL —— `AttributeError: module 'md_runs' has no attribute 'save_output'`

- [ ] **Step 3: 实现侧车（追加到 `md_runs.py`）**

```python
RUNS_DIR = "runs"
_DOC_SUFFIX = ".assets"


def _md_store(doc_path):
    d = os.path.join(os.path.dirname(os.path.abspath(doc_path)),
                     os.path.basename(doc_path) + _DOC_SUFFIX, RUNS_DIR)
    return d


def _tmp_store(token):
    return os.path.join(HERE, "runtime", "tmp", "runs", token or "untitled")


def _load_list(store_json):
    try:
        with io.open(store_json, encoding="utf-8") as f:
            data = json.load(f)
        blocks = data.get("blocks") if isinstance(data, dict) else None
        return blocks if isinstance(blocks, list) else []
    except Exception:
        return []


def _write_list(store_json, blocks):
    os.makedirs(os.path.dirname(store_json), exist_ok=True)
    payload = json.dumps({"version": 1, "blocks": blocks}, ensure_ascii=False, indent=1)
    if len(payload.encode("utf-8")) > 2 * 1024 * 1024:
        return False
    tmp = store_json + ".part"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
    os.replace(tmp, store_json)
    return True


def save_output(lang, code, res, doc_path, token=""):
    """把一次运行结果写进侧车；返回给前端的条目（image 为可渲染引用）。"""
    image_abs = res.get("image") or ""
    entry = {"lang": lang, "code": code,
             "stdout": (res.get("stdout") or "")[:20000],
             "stderr": (res.get("stderr") or "")[:20000],
             "error": res.get("error") or "",
             "image": "", "runtime": res.get("runtime") or "",
             "python": res.get("python") or "",
             "ranAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if not doc_path and not token:
        return entry
    if doc_path and _smd_like(doc_path):
        import _smd
        bdir = _smd.base_dir_for(doc_path)
        store = os.path.join(bdir, RUNS_DIR, "run-outputs.json")
        if image_abs and os.path.isfile(image_abs):
            name = "run-" + hashlib.sha1(code.encode("utf-8")).hexdigest()[:10] + ".png"
            os.makedirs(os.path.join(bdir, RUNS_DIR), exist_ok=True)
            shutil.copy2(image_abs, os.path.join(bdir, RUNS_DIR, name))
            entry["image"] = "runs/" + name
            _smd.write_runs_entries(doc_path, bdir, [os.path.join(bdir, RUNS_DIR, name)])
        blocks = _load_list(store)
        blocks = [b for b in blocks if (b.get("lang"), b.get("code")) != (lang, code)]
        blocks.append(entry)
        _write_list(store, blocks)
        _smd.write_runs_entries(doc_path, bdir, [store])
        return entry
    if doc_path:
        store_dir = _md_store(doc_path)
        store = os.path.join(store_dir, "run-outputs.json")
        if image_abs and os.path.isfile(image_abs):
            name = "run-" + hashlib.sha1(code.encode("utf-8")).hexdigest()[:10] + ".png"
            os.makedirs(store_dir, exist_ok=True)
            dst = os.path.join(store_dir, name)
            shutil.copy2(image_abs, dst)
            entry["image"] = (os.path.basename(doc_path) + _DOC_SUFFIX +
                              "/" + RUNS_DIR + "/" + name).replace("\\", "/")
        blocks = _load_list(store)
        blocks = [b for b in blocks if (b.get("lang"), b.get("code")) != (lang, code)]
        blocks.append(entry)
        _write_list(store, blocks)
        return entry
    # 未命名
    store_dir = _tmp_store(token)
    store = os.path.join(store_dir, "run-outputs.json")
    if image_abs and os.path.isfile(image_abs):
        name = "run-" + hashlib.sha1(code.encode("utf-8")).hexdigest()[:10] + ".png"
        os.makedirs(store_dir, exist_ok=True)
        shutil.copy2(image_abs, os.path.join(store_dir, name))
        entry["image"] = name
    blocks = _load_list(store)
    blocks = [b for b in blocks if (b.get("lang"), b.get("code")) != (lang, code)]
    blocks.append(entry)
    _write_list(store, blocks)
    return entry


def _smd_like(path):
    try:
        import _smd
        return _smd.is_smd(path)
    except Exception:
        return False


def read_outputs(doc_path, token=""):
    if doc_path and _smd_like(doc_path):
        import _smd
        bdir = _smd.base_dir_for(doc_path)
        return _load_list(os.path.join(bdir, RUNS_DIR, "run-outputs.json"))
    if doc_path:
        return _load_list(os.path.join(_md_store(doc_path), "run-outputs.json"))
    if token:
        return _load_list(os.path.join(_tmp_store(token), "run-outputs.json"))
    return []
```

补 `import json, shutil` 到 `md_runs.py` 顶部。

- [ ] **Step 4: `_smd.py` 增两个函数**

```python
def write_runs_entries(smd_path, base_dir, paths):
    """把 runs/ 下的文件按相对路径追加进包（不参与 assets 孤儿清理）。"""
    entries = []
    for p in paths:
        rel = os.path.relpath(p, base_dir).replace(os.sep, "/")
        if rel.startswith("runs/") and os.path.isfile(p):
            entries.append((rel, p))
    if entries:
        _append_entries(smd_path, entries)
```

- [ ] **Step 5: 端点接上侧车与读取**

`/api/run-*` 在返回前加：

```python
                entry = md_runs.save_output(lang, code, res,
                                            (obj.get("doc") or "").strip(),
                                            (obj.get("token") or "").strip())
                res.update({"image": entry.get("image") or "",
                            "saved": bool(entry.get("ranAt"))})
```

新增读取端点：

```python
        if u.path == "/api/run-outputs":
            try:
                q = urllib.parse.parse_qs(u.query)
                blocks = md_runs.read_outputs((q.get("doc") or [""])[0],
                                              (q.get("token") or [""])[0])
                self._send(200, json.dumps({"ok": True, "blocks": blocks},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python\python.exe tests\_test_run_outputs.py`
Expected: `ALL PASS`

- [ ] **Step 7: 登记分发清单 + 提交**

- `installer/_build_installer.py` 的 `DIST_FILES` 加 `"md_runs.py"`
- `docs/分发清单.md` 第二节表格加一行 `md_runs.py`（缺失后果：运行会话与输出存档失效，预览与导出均无输出）
- `tests/_test_dist_verify.py` 若断言最小集文件数，同步更新

```bash
git add md_runs.py _smd.py md_server.py installer/_build_installer.py docs/分发清单.md tests/_test_run_outputs.py
git commit -m "feat: 运行结果侧车（.md/.smd/未命名）"
```

---

### Task 3: 前端恢复输出 + 会话重置按钮

**Files:**
- Modify: `mdwright.html`
- Test: `tests/_test_run_ui.py`

**Interfaces:**
- Consumes：`GET /api/run-outputs`、`POST /api/run-reset`、`/api/run-*` 返回的 `image`（相对引用）

- [ ] **Step 1: 写失败测试**

```python
# tests/_test_run_ui.py
# -*- coding: utf-8 -*-
"""浏览器：变量跨块、刷新后输出恢复、重置按钮。"""
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
import os, sys, tempfile
sys.path.insert(0, _ROOT)
from _test_browser import run_expr  # noqa: E402

fails = []
def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)

PROBE = r"""
(function(){
  var ed = document.getElementById('editor');
  ed.textContent = '```r\nx <- 40\n```\n\n```r\nx + 2\n```\n';
  ed.dispatchEvent(new Event('input', {bubbles:true}));
  return new Promise(function(resolve){
    setTimeout(function(){
      var btns = [].slice.call(document.querySelectorAll('#preview .run-btn'));
      if(btns.length < 2){ resolve({count:btns.length}); return; }
      btns[0].click();
      setTimeout(function(){
        btns[1].click();
        setTimeout(function(){
          var outs = [].slice.call(document.querySelectorAll('#preview .r-out'));
          resolve({
            count: btns.length,
            out2: outs[1] ? outs[1].textContent : '',
            resetBtn: !!document.getElementById('btnResetSession')
          });
        }, 6000);
      }, 6000);
    }, 1200);
  });
})()
"""

RESTORE = r"""
(function(){
  return new Promise(function(resolve){
    setTimeout(function(){
      var outs = [].slice.call(document.querySelectorAll('#preview .r-out'))
        .filter(function(o){ return !o.hidden && o.textContent.trim(); });
      resolve({restored: outs.length, text: outs[0] ? outs[0].textContent : ''});
    }, 2500);
  });
})()
"""

def main():
    doc = os.path.join(tempfile.mkdtemp(prefix="mdrunui-"), "ui.md")
    open(doc, "w", encoding="utf-8").write("# t\n")
    url = "http://127.0.0.1:18777/?file=" + doc.replace("\\", "/")
    r = run_expr(PROBE, url=url)
    check("两块各有一个运行按钮", r.get("count") == 2, str(r.get("count")))
    check("第二块能用到第一块的变量", "42" in (r.get("out2") or ""), str(r.get("out2"))[:120])
    check("工具栏有会话重置按钮", r.get("resetBtn") is True, str(r.get("resetBtn")))
    r2 = run_expr(RESTORE, url=url)
    check("刷新后输出从侧车恢复", (r2.get("restored") or 0) >= 1, str(r2)[:160])
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python\python.exe tests\_test_run_ui.py`
Expected: FAIL —— 第二块报 `object 'x' not found`；重置按钮不存在；刷新后无输出。

- [ ] **Step 3: 改前端**

1. 顶部工具条「跟随」之后插入（与相邻按钮同一样式类）：

```html
<button class="tb-btn" id="btnResetSession" title="重置代码运行会话（清空变量）">⟳ 会话</button>
```

2. `mountRunners()` 之后调用 `restoreRunOutputs()`，并在 `render()` 末尾也调用：

```js
  var runDocKey = function(){
    return { doc: (typeof currentPath === 'string' && currentPath) ? currentPath : '',
             token: (function(){
               try {
                 var t = sessionStorage.getItem('md-doc-token');
                 if(!t){ t = 'd' + Math.random().toString(36).slice(2, 10);
                         sessionStorage.setItem('md-doc-token', t); }
                 return t;
               } catch(e){ return 'd0'; }
             })() };
  };
  function renderRunOut(out, j, lang){
    var html = '';
    if(j && j.ok){
      if(j.stdout) html += '<pre class="r-out-txt">' + escapeHtml(j.stdout) + '</pre>';
      if(j.image) html += '<img class="r-out-img" src="' + escapeHtml(j.image) + '">';
      if(!j.stdout && !j.image) html += '<div class="r-out-line">（执行完成，无输出）</div>';
    } else {
      html += '<pre class="r-out-err">' + escapeHtml((j && j.error) || '执行失败') + '</pre>';
      if(j && j.stdout) html += '<pre class="r-out-txt">' + escapeHtml(j.stdout) + '</pre>';
    }
    if(lang === 'python' && j && j.runtime){
      html += '<div class="r-out-line">' + (j.runtime === 'local' ? '本地解释器' : '随包内置')
            + ' · ' + escapeHtml(j.python || 'Python') + '</div>';
    }
    if(!runDocKey().doc){
      html += '<div class="r-out-line">当前文档未保存为 .md，运行结果只在本次使用期间保留</div>';
    }
    out.innerHTML = html;
    out.hidden = false;
  }
  function restoreRunOutputs(){
    var k = runDocKey();
    var qs = '?doc=' + encodeURIComponent(k.doc) + '&token=' + encodeURIComponent(k.token);
    fetch('/api/run-outputs' + qs).then(function(r){ return r.json(); }).then(function(j){
      if(!j || !j.ok) return;
      var map = {};
      (j.blocks || []).forEach(function(b){ map[b.lang + '\u0000' + b.code] = b; });
      var wraps = document.querySelectorAll('#preview pre[data-runner]');
      for(var i = 0; i < wraps.length; i++){
        var w = wraps[i], lang = w.getAttribute('data-runner');
        var code = w.querySelector('code');
        var out = w.nextSibling;
        if(!code || !out || !out.classList || !out.classList.contains('r-out')) continue;
        var hit = map[lang + '\u0000' + code.textContent];
        if(hit){
          renderRunOut(out, {ok: !hit.error, stdout: hit.stdout, stderr: hit.stderr,
                             error: hit.error, image: hit.image,
                             runtime: hit.runtime, python: hit.python}, lang);
        }
      }
    }).catch(function(){});
  }
  document.getElementById('btnResetSession').addEventListener('click', function(){
    var k = runDocKey();
    fetch('/api/run-reset', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(k)}).then(function(r){ return r.json(); }).then(function(j){
        showToast(j && j.ok ? '代码运行会话已重置（变量已清空）' : '重置失败');
      }).catch(function(){ showToast('重置失败'); });
  });
```

3. `runCodeBlock()` 的请求体加 `doc`/`token`，并把渲染改为调用 `renderRunOut(out, j, lang)`（删除原来的内联 html 拼接）；成功分支加：

```js
        if(j && j.restarted){ showToast('代码运行会话已重启，之前的变量已丢失'); }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python\python.exe tests\_test_run_ui.py`
Expected: `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add mdwright.html tests/_test_run_ui.py
git commit -m "feat: 运行输出刷新后恢复 + 会话重置按钮"
```

---

### Task 4: Word 注入 + 三线表

**Files:**
- Modify: `md_pandoc.py`、`md_server.py`（`/api/export-docx` 收 `threeLine`）、`mdwright.html`（导出时带上开关状态）
- Test: `tests/_test_run_export.py`

**Interfaces:**
- Produces：
  - `md_pandoc.inject_run_outputs(md_text, blocks) -> str`（`blocks` 为 Task 2 的侧车数组）
  - `md_pandoc.three_line_tables(docx_path, pandoc_exe) -> None`
- Consumes：`md_runs.read_outputs()`

- [ ] **Step 1: 写失败测试**

```python
# tests/_test_run_export.py
# -*- coding: utf-8 -*-
"""Word：输出注入 + 三线表（受开关控制）。"""
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
import os, re, subprocess, sys, tempfile, zipfile
sys.path.insert(0, _ROOT)
import md_pandoc  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

fails = []
def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)

def main():
    md = ("```r\nx <- 1\n```\n\n"
          "| 列1 | 列2 |\n|---|---|\n| a | b |\n")
    blocks = [{"lang": "r", "code": "x <- 1", "stdout": "[1] 5.5\n",
               "error": "", "image": ""}]
    out_md = md_pandoc.inject_run_outputs(md, blocks)
    check("输出被注入到代码块之后",
          "```output" in out_md and "[1] 5.5" in out_md, out_md[:200])
    check("未命中的块不注入",
          out_md.count("```output") == 1, str(out_md.count("```output")))
    check("代码源码未被改动", "x <- 1" in out_md, out_md[:120])

    if not md_pandoc.md_tools.find_pandoc(""):
        print("SKIP: 本机无 pandoc")
        sys.exit(77)

    tmp = tempfile.mkdtemp(prefix="mdexport-")
    docx = os.path.join(tmp, "t.docx")
    md_pandoc.export_docx(md, None, docx)
    with zipfile.ZipFile(docx) as z:
        xml0 = z.read("word/document.xml").decode("utf-8")
    check("默认不改表格（无 tblBorders）", "<w:tblBorders>" not in xml0, "")

    md_pandoc.three_line_tables(docx, md_pandoc.md_tools.find_pandoc(""))
    with zipfile.ZipFile(docx) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    check("三线表：有 tblBorders", "<w:tblBorders>" in xml, "")
    check("三线表：无竖线",
          re.search(r'<w:left w:val="none"', xml) and re.search(r'<w:right w:val="none"', xml), "")
    check("三线表：表头行有底边", "<w:tcBorders>" in xml, "")
    # 结构自检：能被 pandoc 回读
    r = subprocess.run([md_pandoc.md_tools.find_pandoc(""), "-f", "docx", "-t", "markdown", docx],
                       capture_output=True, timeout=120)
    check("改完的 docx 仍可被 pandoc 读回", r.returncode == 0,
          (r.stderr or b"").decode("utf-8", "replace")[:200])
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python\python.exe tests\_test_run_export.py`
Expected: FAIL —— `AttributeError: module 'md_pandoc' has no attribute 'inject_run_outputs'`

- [ ] **Step 3: 实现 `md_pandoc.inject_run_outputs`**

```python
def inject_run_outputs(md_text, blocks):
    """按 (lang, code) 把运行结果注入到对应围栏块之后；未命中不动。

    围栏扫描复用 prepare_markdown 的同一条规则（``` 与 ~~~ 各自配对），
    因此 ` ```mermaid {30} ` 这类带参数的围栏也能被正确整块跳过，
    不会把围栏内部当成正文再误判一次。
    """
    want = {}
    for b in blocks or []:
        want[(b.get("lang") or "", (b.get("code") or "").strip("\n"))] = b
    if not want:
        return md_text
    lines = md_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        mark = m.group(2)
        info = (m.group(3) or "").strip()
        lang = info.split()[0].lower() if info else ""
        close_re = re.compile(r"^\s*" + re.escape(mark) + r"\s*$")
        body, j = [], i + 1
        while j < len(lines) and not close_re.match(lines[j]):
            body.append(lines[j])
            j += 1
        if j >= len(lines):                 # 未闭合：原样输出，不猜
            out.extend(lines[i:])
            break
        out.extend(lines[i:j + 1])          # 原封不动保留围栏本身
        hit = want.get((lang, "\n".join(body).strip("\n"))) if lang in ("r", "python") else None
        if hit:
            if hit.get("error"):
                out.append("```output")
                out.append("[错误] " + hit["error"])
                if hit.get("stdout"):
                    out.extend(hit["stdout"].rstrip("\n").split("\n"))
                out.append("```")
            elif hit.get("stdout"):
                out.append("```output")
                out.extend(hit["stdout"].rstrip("\n").split("\n"))
                out.append("```")
            if hit.get("image"):
                out.append("")
                out.append('![运行输出](<%s>){80}' % hit["image"].replace("\\", "/"))
            out.append("")
        i = j + 1
    return "\n".join(out)
```

- [ ] **Step 4: 实现 `md_pandoc.three_line_tables`**

```python
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_TBL_PR_AFTER = {"tblBorders"}   # 插在 tblLayout / tblLook 之前
_TBL_PR_ORDER = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
                 "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd",
                 "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook"]
_TC_PR_ORDER = ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd",
                "noWrap", "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark"]


def _insert_ordered(parent, child, order):
    tag = child.tag.split("}")[-1]
    idx = order.index(tag) if tag in order else len(order)
    for i, el in enumerate(list(parent)):
        t = el.tag.split("}")[-1]
        if t in order and order.index(t) > idx:
            parent.insert(i, child)
            return
    parent.append(child)


def three_line_tables(docx_path, pandoc_exe):
    """把 docx 里所有表格改成三线表；结构不合规就让整次导出失败。"""
    import shutil
    import tempfile
    import zipfile
    import xml.etree.ElementTree as ET

    def q(tag):
        return "{%s}%s" % (_W_NS, tag)

    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        raw = z.read("word/document.xml")
        others = {n: z.read(n) for n in names if n != "word/document.xml"}
    ET.register_namespace("w", _W_NS)
    root = ET.fromstring(raw)
    for tbl in root.iter(q("tbl")):
        pr = tbl.find(q("tblPr"))
        if pr is None:
            pr = ET.SubElement(tbl, q("tblPr"))
            tbl.remove(pr); tbl.insert(0, pr)
        old = pr.find(q("tblBorders"))
        if old is not None:
            pr.remove(old)
        borders = ET.Element(q("tblBorders"))
        for side, sz in (("top", "12"), ("bottom", "12"),
                         ("left", "0"), ("right", "0"),
                         ("insideH", "0"), ("insideV", "0")):
            el = ET.SubElement(borders, q(side))
            el.set(q("val"), "single" if sz != "0" else "none")
            el.set(q("sz"), sz if sz != "0" else "0")
            el.set(q("space"), "0")
            el.set(q("color"), "auto")
        _insert_ordered(pr, borders, _TBL_PR_ORDER)
        first_tr = tbl.find(q("tr"))
        if first_tr is not None:
            for tc in first_tr.findall(q("tc")):
                tcpr = tc.find(q("tcPr"))
                if tcpr is None:
                    tcpr = ET.Element(q("tcPr"))
                    tc.insert(0, tcpr)
                oldb = tcpr.find(q("tcBorders"))
                if oldb is not None:
                    tcpr.remove(oldb)
                tb = ET.Element(q("tcBorders"))
                bottom = ET.SubElement(tb, q("bottom"))
                bottom.set(q("val"), "single")
                bottom.set(q("sz"), "8")
                bottom.set(q("space"), "0")
                bottom.set(q("color"), "auto")
                _insert_ordered(tcpr, tb, _TC_PR_ORDER)
    new_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    tmp = docx_path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, new_xml if n == "word/document.xml" else others[n])
    os.replace(tmp, docx_path)

    # 回读自检：读不出即判失败，绝不落一个打不开的 docx
    r = subprocess.run([pandoc_exe, "-f", "docx", "-t", "markdown", docx_path],
                       capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("三线表改写后 docx 结构校验失败：%s"
                           % (r.stderr or b"").decode("utf-8", "replace")[:200])
```

- [ ] **Step 5: 接进导出端点**

`/api/export-docx` 分支：读 `threeLine`，在 `md_pandoc.export_docx(...)` 之后（或之前注入 md）：

```python
                md_text = obj.get("markdown") or ""
                blocks = md_runs.read_outputs(md_path, (obj.get("token") or "").strip())
                md_text = md_pandoc.inject_run_outputs(md_text, blocks)
                ...
                md_pandoc.export_docx(md_text, md_path, out, ...)
                if obj.get("threeLine"):
                    md_pandoc.three_line_tables(out, md_tools.find_pandoc(...))
```

前端 `btnExportDocx` 的请求体（`mdwright.html` 里 `fetch('/api/export-docx'…`）改成：

```js
        body:JSON.stringify({path:currentFile, markdown:cjkSpaceMarkdown(getText()),
                             outPath:outPath,
                             threeLine:!!(tsCfg&&tsCfg.table&&tsCfg.table.three)})})
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python\python.exe tests\_test_run_export.py`
Expected: `ALL PASS`

- [ ] **Step 7: 回归既有导出用例**

Run: `python\python.exe tests\_test_docx.py`、`_test_pandoc_prep.py`、`_test_export_css.py`
Expected: 三个都 ALL PASS

- [ ] **Step 8: 提交**

```bash
git add md_pandoc.py md_server.py mdwright.html tests/_test_run_export.py
git commit -m "feat: Word 导出注入运行结果 + 三线表"
```

---

### Task 5: 文件菜单拆分 + 关于窗口

**Files:**
- Modify: `mdwright.html`、`md_server.py`（`APP_VERSION` + `/api/version` 增 `app`）
- Test: `tests/_test_about.py`、`tests/_test_menu_ui.py`

**Interfaces:**
- Produces：`/api/version` 响应新增 `"app": "3.2.0"`
- Consumes：无

- [ ] **Step 1: 写失败测试**

```python
# tests/_test_about.py
# -*- coding: utf-8 -*-
"""文件菜单拆分 + 关于窗口。"""
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
import sys
sys.path.insert(0, _ROOT)
from _test_browser import run_expr  # noqa: E402

fails = []
def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)

PROBE = r"""
(function(){
  function q(s){ return document.querySelector(s); }
  var fileLabel = [].slice.call(document.querySelectorAll('#menuBar .menu-label'))
    .filter(function(b){ return b.textContent.trim() === '文件'; })[0];
  fileLabel.click();
  var items = [].slice.call(fileLabel.parentNode.querySelectorAll('.menu-item'))
    .map(function(b){ return b.textContent.trim(); });
  var about = document.getElementById('btnAbout');
  var out = {items: items, hasAbout: !!about};
  if(about) about.click();
  return new Promise(function(resolve){
    setTimeout(function(){
      var ov = q('#aboutOverlay');
      out.open = !!ov && !ov.hidden;
      out.text = ov ? ov.textContent : '';
      document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
      setTimeout(function(){
        out.closedByEsc = !!ov && ov.hidden;
        // 最近文件入口只显示最近
        var recent = document.getElementById('btnRecent');
        if(recent) recent.click();
        setTimeout(function(){
          var fm = q('#fmOverlay');
          out.recentMode = fm ? fm.getAttribute('data-mode') : '';
          out.hasRecentList = !!q('#fmList');
          resolve(out);
        }, 400);
      }, 300);
    }, 600);
  });
})()
"""

def main():
    r = run_expr(PROBE)
    for want in ("最近文件…", "内置文档（帮助）…", "关于"):
        check("文件菜单含 %s" % want, any(want.startswith(x.rstrip('…')) for x in r.get("items") or []),
              str(r.get("items")))
    check("关于窗口能打开", r.get("open") is True, str(r.get("open")))
    check("关于窗口显示版本 3.2.0", "3.2.0" in (r.get("text") or ""), (r.get("text") or "")[:120])
    check("关于窗口含许可与上游说明",
          "AGPL" in (r.get("text") or "") and "MDEditor" in (r.get("text") or ""), "")
    check("Esc 关闭关于", r.get("closedByEsc") is True, str(r.get("closedByEsc")))
    check("最近文件入口走 recent 模式", r.get("recentMode") == "recent", str(r.get("recentMode")))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python\python.exe tests\_test_about.py`
Expected: FAIL —— 无 `btnAbout` / 无 `#aboutOverlay`

- [ ] **Step 3: 改菜单与新增关于窗口**

1. 文件菜单：把 `<button class="menu-item" id="btnFiles">…</button>` 换成三项：

```html
        <button class="menu-item" id="btnRecent" role="menuitem">最近文件…</button>
        <button class="menu-item" id="btnBuiltin" role="menuitem">内置文档（帮助）…</button>
        <div class="menu-sep"></div>
        <button class="menu-item" id="btnAbout" role="menuitem">关于</button>
```

2. 新增遮罩（放在 `#fmOverlay` 之后）：

```html
<div id="aboutOverlay" hidden>
  <div id="aboutBox" role="dialog" aria-modal="true" aria-label="关于 MDWright">
    <img src="mdwright.ico" alt="" width="40" height="40">
    <div class="ab-name">MDWright</div>
    <div class="ab-ver">版本 <span id="aboutVer">—</span></div>
    <div class="ab-desc">Windows 单机 Markdown 写作台：写作照 Markdown 的来，输出照排版的来。</div>
    <div class="ab-lic">AGPL-3.0-or-later · 衍生自 MDEditor v2.0</div>
    <div class="ab-btns">
      <button id="abGuide" type="button">打开使用指南</button>
      <button id="abLicense" type="button">打开许可声明</button>
      <button id="abOk" type="button">确定</button>
    </div>
  </div>
</div>
```

3. 样式（与 `#fmOverlay` 同一套视觉）：

```css
  #aboutOverlay{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:99;
    display:flex;align-items:center;justify-content:center;}
  #aboutOverlay[hidden]{display:none !important;}
  #aboutBox{width:360px;padding:22px 24px;border-radius:12px;background:var(--panel);
    border:1px solid var(--border);box-shadow:0 18px 44px rgba(0,0,0,.42);
    display:flex;flex-direction:column;align-items:center;gap:8px;font-size:13px;}
  #aboutBox .ab-name{font-size:17px;font-weight:700;}
  #aboutBox .ab-ver{color:var(--muted);}
  #aboutBox .ab-desc,#aboutBox .ab-lic{color:var(--muted);text-align:center;line-height:1.6;}
  #aboutBox .ab-btns{display:flex;gap:8px;margin-top:6px;}
```

4. JS：

```js
  function openFileManager(mode){
    document.getElementById('fmOverlay').setAttribute('data-mode', mode);
    renderFileList(mode);              /* 现有函数（mdwright.html:3763）加一个 mode 形参 */
    document.getElementById('fmOverlay').hidden = false;
  }
  document.getElementById('btnRecent').addEventListener('click', function(){ openFileManager('recent'); });
  document.getElementById('btnBuiltin').addEventListener('click', function(){ openFileManager('builtin'); });
  function aboutOpen() {
    document.getElementById('aboutOverlay').hidden = false;
    fetch('/api/version').then(function(r){ return r.json(); }).then(function(j){
      if(j && j.app) document.getElementById('aboutVer').textContent = j.app;
    }).catch(function(){});
  }
  function aboutClose(){ document.getElementById('aboutOverlay').hidden = true; }
  document.getElementById('btnAbout').addEventListener('click', aboutOpen);
  document.getElementById('abOk').addEventListener('click', aboutClose);
  document.getElementById('aboutOverlay').addEventListener('click', function(e){
    if(e.target === this) aboutClose();
  });
```

`renderFileList(mode)`：现有实现（`mdwright.html:3763`）里两段 `html+=…` 分别包一层 `if(mode !== 'recent'){…}`（内置文档段）与 `if(mode !== 'builtin'){…}`（最近文件段），标题留在各自分支内；无参调用时按 `'all'` 处理，保持 `renderFileList()` 原有行为。

5. `md_server.py`：顶部加 `APP_VERSION = "3.2.0"`；`/api/version` 响应体加 `"app": APP_VERSION`（`do_GET` 与 `do_POST` 里三处返回都要加，`_test_dist_verify` 读的是同一响应）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python\python.exe tests\_test_about.py` 与 `python\python.exe tests\_test_menu_ui.py`
Expected: 两个都 ALL PASS

- [ ] **Step 5: 提交**

```bash
git add mdwright.html md_server.py tests/_test_about.py
git commit -m "feat: 文件菜单拆分（最近文件/内置文档）+ 关于窗口"
```

---

### Task 6: 文档与发版口径

**Files:**
- Modify: `docs/MDWright 使用指南.md`、`AGENTS.md`、`CHANGELOG.md`、`md_server.py`（`MD_SERVER_VERSION`）
- Test: `python\python.exe tests\run_all.py`

- [ ] **Step 1: 使用指南补三处**

- 「R 代码块」章：说明**同一文档内的块共享一个会话**（前一块的变量后一块能用）、`⟳ 会话` 按钮清空变量、块报错不影响会话
- 「R / Python 代码块」章：说明运行结果**会存到文档旁边的 `runs/`**，重开文档仍在；代码改动后旧结果不再显示
- 「导出 Word」章：补「运行结果会一起导出」「三线表由排版面板的开关控制」
- 语法速查表：无新增语法，不必加行

- [ ] **Step 2: `AGENTS.md` 发布口径改为三处**

把「发布必改两处」改成「发布必改三处」：`CHANGELOG.md` 首段、`md_server.APP_VERSION`、`md_server.MD_SERVER_VERSION`。

- [ ] **Step 3: 写 CHANGELOG 段并升版本号**

`CHANGELOG.md` 顶部加 `## v3.2.0（2026-10-24）`，按既有体例（现象/根因/修法/验证）写 5 组：运行会话、输出存档、Word 注入与三线表、菜单与关于、测试。同时 `MD_SERVER_VERSION` 66 → 67。

- [ ] **Step 4: 跑全套**

Run: `cmd /c md_stop.cmd` 然后 `python\python.exe tests\run_all.py`
Expected: 除 `_test_rag_e2e`（本机无 rag-assistant，既有基线）外全部 PASS/SKIP；新增 5 个用例必须 PASS。

- [ ] **Step 5: 提交**

```bash
git add CHANGELOG.md md_server.py docs/MDWright\ 使用指南.md AGENTS.md
git commit -m "docs: v3.2.0 发布记录与使用指南"
```

---

## 自检记录

| 检查 | 结果 |
|---|---|
| Spec 覆盖 | §4.1→Task1；§4.2→Task2；§4.3→Task1/2；§4.4→Task3；§4.5→Task4；§4.6→Task5；§8→Task6 |
| 占位符 | 无 TBD / "适当处理" 类空话；每步给到可粘贴的代码或命令 |
| 类型一致 | `run_code()` / `read_outputs()` / `save_output()` / `inject_run_outputs()` / `three_line_tables()` 在 Task 1/2/4 之间的签名与调用处一致 |
| Review Focus 落地 | 并发 409→Task1 测试；代码改动失效→Task2 测试；R 自调 sink→Task1 驱动（sink 先关再写 DONE）；`.smd` 孤儿→Task2 测试；docx 可打开→Task4 pandoc 回读 |
