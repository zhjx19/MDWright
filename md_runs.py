# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""代码块运行：常驻解释器会话 + 运行结果侧车。

会话协议（不依赖 jsonlite / 任何第三方包）：
  父进程把源码写进 `<workdir>/<id>.code`，向子进程 stdin 写一行 `<id>`；
  子进程执行后写 `<id>.out.txt` / `<id>.err.txt` / `<id>.png`(R) / `<id>.status`，
  再往 stdout 回一行 `DONE <id>`。父进程等到这一行（或超时杀进程）后读文件。

为什么要常驻：同一文档里前面的代码块定义的变量，后面的块要能直接用
（脚本式"每次新进程"做不到）。为什么用文件握手而不是 JSON over pipe：
R 侧不保证有 jsonlite，Base R 只认文本；把代码放文件也免掉一切转义问题。

设计见 docs/superpowers/specs/2026-10-24-run-session-and-exports-design.md §4.1。
"""
import hashlib
import io
import json
import os
import shutil
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


def _settings_tools():
    try:
        with io.open(os.path.join(HERE, "runtime", "settings.json"), encoding="utf-8") as f:
            data = json.load(f)
        cfg = data.get("tools") if isinstance(data, dict) else None
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _py_exe():
    """本机解释器（设置里填了才用）→ 否则随包内置。与 _run_py_code 同一口径。"""
    import md_tools
    cfg = _settings_tools()
    v = md_tools._cfg(cfg, "python_path", "python")
    p = md_tools.find_python(v) if v else None
    return p or sys.executable


def _r_exe():
    import md_tools
    cfg = _settings_tools()
    return md_tools.find_r(md_tools._cfg(cfg, "rscript_path", "rscript"))


def _png_blank(path):
    """判定 png 是不是空白图。

    png 设备即使一行图都没画也会生成文件（纯白）；不判就会出现一个空白图块。
    与 md_server 里同名判据一致：实测空白图 0 个暗像素、真图数千以上。
    """
    try:
        from PIL import Image
        im = Image.open(path).convert("L")
        return sum(im.histogram()[:250]) == 0
    except Exception:
        try:
            return os.path.getsize(path) < 2500
        except Exception:
            return True


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
        self.proc = subprocess.Popen(
            argv, cwd=workdir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
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
            return {"ok": False, "stdout": "", "stderr": "", "error": "会话已断开",
                    "image": "", "timeout": False}
        timer = threading.Timer(timeout, self.kill)
        timer.start()
        try:
            line = self.proc.stdout.readline()
        finally:
            timer.cancel()
        if line.strip() != "DONE " + rid:
            self.dead = True
            return {"ok": False, "stdout": "", "stderr": "",
                    "error": "执行超时（%d 秒）或会话中断" % timeout,
                    "image": "", "timeout": True}
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
        shown = png if (os.path.isfile(png) and not _png_blank(png)) else ""
        return {"ok": not bad, "stdout": out, "stderr": err,
                "error": status.split("\t", 1)[1] if bad and "\t" in status else "",
                "image": shown, "timeout": False}


def _spawn(key, lang):
    if lang == "python":
        exe = _py_exe()
    else:
        exe = _r_exe()
        if not exe:
            raise RuntimeError("未检测到 R 运行时（Rscript.exe）：请安装 R，"
                               "或在「设置 → 外部工具」里指定 Rscript 路径")
    return _Session(key, lang, exe, _workdir(key, lang))


def run_code(lang, code, doc_key, timeout=60):
    """跑一段代码。有 doc_key 走常驻会话（变量跨块），否则一次性执行后即杀。"""
    if not doc_key:
        s = _spawn("oneshot", lang)
        try:
            res = s.run(code, timeout)
            res["restarted"] = False
            return res
        finally:
            s.kill()
    key = (doc_key, lang)
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
