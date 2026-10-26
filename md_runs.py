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

import _smd

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
}
'''

_PY_DRIVER = r'''
import contextlib, io, os, sys, traceback

# 有 matplotlib 就先把它按住：后端固定 Agg（否则 plt.show() 会弹窗并卡住到超时），
# 字体补中文字族（默认 DejaVu 没有中文，标题会显示成方块）。没有 matplotlib 时
# 这两步都静默跳过——随包内置的运行时本来就没有它。
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "PingFang SC",
                                       "Noto Sans CJK SC", "Source Han Sans SC",
                                       "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
except Exception:
    pass


def _save_figure(wd, rid):
    """执行完把还没关的 matplotlib 图落成 png（与 R 的 png() 设备同一条口径）。

    只认真正 import 过 pyplot 的代码：随包内置的 3.11.9 没有 matplotlib，
    这里直接跳过，不额外装依赖。savefig 之后统一 close('all')——不关的话，
    下一块会把上一块的图再存一遍，图就串了。
    """
    plt = sys.modules.get("matplotlib.pyplot")
    if plt is None:
        return
    try:
        nums = plt.get_fignums()
    except Exception:
        return
    if not nums:
        return
    try:
        fig = plt.figure(nums[-1])
        fig.savefig(os.path.join(wd, rid + ".png"), dpi=150,
                    facecolor="white", bbox_inches="tight")
    except Exception:
        pass
    finally:
        try:
            plt.close("all")
        except Exception:
            pass


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
    _save_figure(wd, rid)
    io.open(os.path.join(wd, rid + ".out.txt"), "w", encoding="utf-8").write(ob.getvalue())
    io.open(os.path.join(wd, rid + ".err.txt"), "w", encoding="utf-8").write(eb.getvalue())
    io.open(os.path.join(wd, rid + ".status"), "w", encoding="utf-8").write(
        "ok" if not err else "err\t" + err)
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


def _exe_now(lang):
    """当前配置应使用的解释器。

    R 没装时返回空串——空串不参与「换了没」的比对，免得 R 一时不可用
    就把好好的会话掐掉。
    """
    try:
        return _py_exe() if lang == "python" else (_r_exe() or "")
    except Exception:
        return ""


def _annotate(res, lang):
    """内置运行时缺第三方库时，补一句能直接照做的提示。

    `ModuleNotFoundError` 只说缺哪个包，用户看到的却是「我明明装了 pandas」——
    实际是没指到本机解释器。提示把人指回设置面板，别让人去重装库。
    """
    if (not res.get("ok")) and lang == "python" and res.get("runtime") == "builtin" \
            and "ModuleNotFoundError" in (res.get("error") or ""):
        res["hint"] = ("当前用的是随包内置 Python（只有标准库）。要用第三方库，"
                       "在「设置 → 外部工具」里把 Python 指到装了它的解释器，再运行一次。")
    return res


class _Session(object):
    def __init__(self, key, lang, exe, workdir, meta=None):
        self.key, self.lang, self.workdir = key, lang, workdir
        self.exe = exe          # 记下这次用的解释器，配置变了要据此重建
        self.meta = meta or {}
        self.seq = 0
        self.dead = False
        self.used = time.time()
        driver = os.path.join(workdir, "_driver.py" if lang == "python" else "_driver.R")
        with io.open(driver, "w", encoding="utf-8", newline="\n") as f:
            f.write(_PY_DRIVER if lang == "python" else _R_DRIVER)
        argv = ([exe, "-u", "-X", "utf8", driver, workdir] if lang == "python"
                else [exe, driver, workdir])
        self.proc = subprocess.Popen(
            argv, cwd=workdir, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
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
        # 完成信号看「状态文件写出来没有」，**不读 stdout**：
        # 用户代码随时可能往 stdout 写（自己 sink() 后 cat、os.system/子进程继承 stdout），
        # 拿 stdout 当握手通道会被打乱，表现为假超时且变量全丢。
        status_path = os.path.join(self.workdir, rid + ".status")
        deadline = time.time() + timeout
        while not os.path.isfile(status_path):
            if self.proc.poll() is not None:
                self.dead = True
                return {"ok": False, "stdout": "", "stderr": "",
                        "error": "会话已退出（代码可能终止了解释器进程）",
                        "image": "", "timeout": False}
            if time.time() >= deadline:
                self.kill()
                return {"ok": False, "stdout": "", "stderr": "",
                        "error": "执行超时（%d 秒）或会话中断" % timeout,
                        "image": "", "timeout": True}
            time.sleep(0.05)
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
        import md_tools
        exe = _py_exe()
        # 「谁跑的」必须标明：随包内置还是本机解释器，决定第三方包能不能 import
        runtime = "builtin" if os.path.normcase(exe) == os.path.normcase(sys.executable) \
            else "local"
        try:
            ver = md_tools.version_of(exe) or ""
        except Exception:
            ver = ""
        meta = {"runtime": runtime, "python": ver or "Python %s" % ".".join(
            map(str, sys.version_info[:3]))}
    else:
        exe = _r_exe()
        if not exe:
            raise RuntimeError("未检测到 R 运行时（Rscript.exe）：请安装 R，"
                               "或在「设置 → 外部工具」里指定 Rscript 路径")
        meta = {}
    return _Session(key, lang, exe, _workdir(key, lang), meta)


def run_code(lang, code, doc_key, timeout=60):
    """跑一段代码。有 doc_key 走常驻会话（变量跨块），否则一次性执行后即杀。"""
    if not doc_key:
        s = _spawn("oneshot", lang)
        try:
            res = s.run(code, timeout)
            res["restarted"] = False
            res.update(s.meta)
            return _annotate(res, lang)
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
            # 解释器换了就重建会话：会话用哪个解释器在 _spawn 时定死，
            # 不重建会一直用旧的那个——表现就是「设置里明明填了 Python，
            # 还是 ModuleNotFoundError」。改设置时服务端已顺手清一次，
            # 这里兜住「设置没走接口」的情况（手改了 settings.json、路径原来填错回落过）。
            exe_now = _exe_now(lang)
            if s is not None and not s.dead and exe_now \
                    and os.path.normcase(getattr(s, "exe", "")) != os.path.normcase(exe_now):
                _SESS.pop(key).kill()
                s = None
                restarted = True
            if s is None or s.dead:
                if s is not None:
                    restarted = True
                s = _spawn(key[0], lang)
                _SESS[key] = s
        res = s.run(code, timeout)
        res["restarted"] = restarted
        res.update(s.meta)
        return _annotate(res, lang)
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


# ── 运行结果侧车 ────────────────────────────────────────────────
# 落点：.md → <doc>.md.assets/runs/；.smd → 包内 runs/；未命名 → runtime/tmp/runs/<token>/
# 单开 runs/ 而不是塞进 assets/：.smd 的 save_from_dir 会清掉 assets 里没被正文
# 引用的孤儿资产，运行图的引用写在侧车里、不在正文，放 assets 会被下一次保存静默删掉。
RUNS_DIR = "runs"
_DOC_SUFFIX = ".assets"


def _store_dir(doc_path, token=""):
    """侧车所在目录（绝对）。.smd 用解包目录，未命名用临时区。"""
    if doc_path:
        try:
            if _smd.is_smd(doc_path):
                return os.path.join(_smd.base_dir_for(doc_path), RUNS_DIR)
        except Exception:
            pass
        return os.path.join(os.path.dirname(os.path.abspath(doc_path)),
                            os.path.basename(doc_path) + _DOC_SUFFIX, RUNS_DIR)
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


def _img_name(code):
    return "run-" + hashlib.sha1(code.encode("utf-8")).hexdigest()[:10] + ".png"


def save_output(lang, code, res, doc_path="", token=""):
    """把一次运行结果写进侧车；返回写入的条目（image 为 runs/ 内文件名）。"""
    if not doc_path and not token:
        return {}
    store_dir = _store_dir(doc_path, token)
    try:
        os.makedirs(store_dir, exist_ok=True)
    except Exception:
        return {}
    entry = {"lang": lang, "code": code,
             "stdout": (res.get("stdout") or "")[:20000],
             "stderr": (res.get("stderr") or "")[:20000],
             "error": res.get("error") or "",
             "image": "", "runtime": res.get("runtime") or "",
             "python": res.get("python") or "",
             "ranAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
    src_png = res.get("image") or ""
    if src_png and os.path.isfile(src_png):
        name = _img_name(code)
        try:
            shutil.copy2(src_png, os.path.join(store_dir, name))
            entry["image"] = name
        except Exception:
            entry["image"] = ""
    store = os.path.join(store_dir, "run-outputs.json")
    blocks = [b for b in _load_list(store)
              if (b.get("lang"), b.get("code")) != (lang, code)]
    blocks.append(entry)
    _write_list(store, blocks)
    if doc_path and _is_smd(doc_path):
        try:
            _smd.write_runs_entries(doc_path, _smd.base_dir_for(doc_path),
                                    [store] + ([os.path.join(store_dir, entry["image"])]
                                               if entry["image"] else []))
        except Exception:
            pass
    return entry


def image_abs(doc_path="", token="", name=""):
    """侧车里的图片文件名 → 绝对路径（不存在则空串）。"""
    if not name:
        return ""
    try:
        p = os.path.join(_store_dir(doc_path, token), name)
    except Exception:
        return ""
    return p if os.path.isfile(p) else ""


def read_outputs(doc_path="", token=""):
    """读侧车；image 相对文件名解析成 imageAbs（绝对路径，可直接给 /img?path=）。"""
    if not doc_path and not token:
        return []
    try:
        store_dir = _store_dir(doc_path, token)
    except Exception:
        return []
    blocks = _load_list(os.path.join(store_dir, "run-outputs.json"))
    out = []
    for b in blocks:
        if not isinstance(b, dict) or "code" not in b:
            continue
        b = dict(b)
        rel = b.get("image") or ""
        abs_p = os.path.join(store_dir, rel) if rel else ""
        b["imageAbs"] = abs_p if (abs_p and os.path.isfile(abs_p)) else ""
        out.append(b)
    return out


def _is_smd(path):
    try:
        return _smd.is_smd(path)
    except Exception:
        return False
