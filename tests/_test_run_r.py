# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""R 代码块执行回归（R4，需本机 Rscript；本机 d:\\R-4.6.1）：
- stdout 捕获（含中文）
- base plot 产出真图（非空白）；ggplot 末值未 print 也能出图
- R 错误 → ok:false 且带错误原文
- 语法错误 → ok:false
- 不画图时**不返回图**（png 设备空跑也会生成文件，必须判空白）
- 空代码 / 缺 R 运行时 → 明确报错
- 跑完不残留临时文件
"""
# --- 测试入口 shim：本文件在 tests/ 下。便携运行时（python311._pth）不会把 script dir
# 加进 sys.path，所以 tests/ 与仓库根两个都显式挂上，跨用例 import 与根模块 import 才成立 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import md_server  # noqa: E402

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
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "HTTP %d" % e.code}


def main():
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        j = post("/api/run-r", {"code": 'cat("你好 R\\n"); print(sum(1:3))'})
        check("纯输出：ok", j.get("ok") is True, str(j)[:200])
        check("纯输出：stdout 含中文", "你好 R" in (j.get("stdout") or ""), j.get("stdout"))
        check("纯输出：不含图", not (j.get("image") or ""), str(j.get("image")))

        j = post("/api/run-r", {"code": 'plot(1:10, main="t")'})
        img = j.get("image") or ""
        check("base plot：ok 且有图", j.get("ok") is True and img and os.path.isfile(img),
              str(j)[:200])
        if img and os.path.isfile(img):
            check("base plot：是合法 PNG", open(img, "rb").read(8) == b"\x89PNG\r\n\x1a\n")

        j = post("/api/run-r", {"code":
                 'library(ggplot2); ggplot(mtcars, aes(wt, mpg)) + geom_point()'})
        check("ggplot 末值未 print 也出图",
              j.get("ok") is True and (j.get("image") or "")
              and os.path.isfile(j.get("image")), str(j)[:200])

        # 控制台语义：裸表达式自动打印（用户不该为了看结果手写 print()）
        j = post("/api/run-r", {"code": "1:10"})
        out = j.get("stdout") or ""
        check("裸表达式自动打印 1:10",
              j.get("ok") is True and "[1]" in out and "10" in out, out[:120])

        j = post("/api/run-r", {"code": "mtcars"})
        out = j.get("stdout") or ""
        check("裸表达式自动打印 mtcars", j.get("ok") is True and len(out) > 200,
              out[:120])

        j = post("/api/run-r", {"code": "x <- 42\nx"})
        out = j.get("stdout") or ""
        check("赋值不打印、裸变量打印",
              j.get("ok") is True and "[1] 42" in out, out[:120])

        j = post("/api/run-r", {"code": "invisible(1)"})
        check("invisible 不打印", j.get("ok") is True
              and not (j.get("stdout") or "").strip(), repr(j.get("stdout")))

        j = post("/api/run-r", {"code": 'stop("boom 中文错误")'})
        check("R 错误：ok=false", j.get("ok") is False, str(j)[:200])
        check("R 错误：带原文", "boom" in (j.get("error") or ""), str(j.get("error")))

        j = post("/api/run-r", {"code": "x <- 1 +"})
        check("语法错：ok=false", j.get("ok") is False, str(j)[:160])

        j = post("/api/run-r", {"code": "   "})
        check("空代码：明确拒绝", j.get("ok") is False and "空" in (j.get("error") or ""),
              str(j)[:160])

        # 缺 R：临时把 find_r 打空
        import md_tools
        saved = md_tools.find_r
        md_tools.find_r = lambda configured="": None
        try:
            j = post("/api/run-r", {"code": "1+1"})
        finally:
            md_tools.find_r = saved
        check("缺 R 运行时：明确报错",
              j.get("ok") is False and "R" in (j.get("error") or ""), str(j)[:200])

        # 临时文件不残留（除图之外）
        rdir = os.path.join(HERE, "runtime", "tmp", "r")
        leftovers = []
        if os.path.isdir(rdir):
            leftovers = [n for n in os.listdir(rdir)
                         if not n.endswith(".png")]
        check("中间文件不残留", not leftovers, str(leftovers[:6]))
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
