# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""常驻会话：变量跨块、报错不杀会话、超时重建、并发拒绝、重置。

执行模型见 docs/superpowers/specs/2026-10-24-run-session-and-exports-design.md §4.1。
"""
# --- 测试入口 shim ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import json
import sys
import threading
import time
import urllib.error
import urllib.request

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

DOC = "T:/runsession/probe.md"          # 不存在的路径也合法：会话键只需一个稳定标识


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
        try:
            return json.loads(e.read().decode("utf-8")), e.code
        except Exception:
            return {"ok": False, "error": "HTTP %d" % e.code}, e.code


def main():
    # ---- R：变量跨两次请求 ----
    post("/api/run-r", {"code": "x <- 41", "doc": DOC})
    r, _ = post("/api/run-r", {"code": "x + 1", "doc": DOC})
    check("R 变量跨块存活", r.get("ok") is True and "42" in (r.get("stdout") or ""),
          str(r)[:200])

    # ---- Python：变量跨两次请求 ----
    post("/api/run-py", {"code": "y = 41", "doc": DOC})
    p, _ = post("/api/run-py", {"code": "print(y + 1)", "doc": DOC})
    check("Python 变量跨块存活", p.get("ok") is True and "42" in (p.get("stdout") or ""),
          str(p)[:200])

    # ---- 报错不杀会话 ----
    post("/api/run-r", {"code": "stop('boom')", "doc": DOC})
    r2, _ = post("/api/run-r", {"code": "x * 2", "doc": DOC})
    check("R 报错后会话仍可用", r2.get("ok") is True and "82" in (r2.get("stdout") or ""),
          str(r2)[:200])

    # ---- 超时：杀掉会话，下次重建且变量已丢 ----
    t, _ = post("/api/run-r", {"code": "Sys.sleep(3)", "doc": DOC, "timeout": 1})
    check("超时返回错误", t.get("ok") is False and "超时" in (t.get("error") or ""),
          str(t)[:200])
    r3, _ = post("/api/run-r", {"code": "exists('x')", "doc": DOC})
    check("超时后自动重建且变量已丢",
          r3.get("ok") is True and "FALSE" in (r3.get("stdout") or "")
          and r3.get("restarted") is True, str(r3)[:200])

    # ---- 并发：一块在跑时第二块被拒 ----
    def slow():
        post("/api/run-r", {"code": "Sys.sleep(2)", "doc": DOC}, timeout=60)

    th = threading.Thread(target=slow)
    th.start()
    time.sleep(0.6)
    second, sc = post("/api/run-r", {"code": "1", "doc": DOC}, timeout=10)
    th.join(timeout=60)
    check("并发第二块被拒 409", sc == 409 and "还在运行" in (second.get("error") or ""),
          "%s %s" % (sc, str(second)[:160]))

    # ---- 重置：变量清空 ----
    post("/api/run-reset", {"doc": DOC})
    r4, _ = post("/api/run-r", {"code": "exists('x')", "doc": DOC})
    check("重置后变量消失", "FALSE" in (r4.get("stdout") or ""), str(r4)[:200])

    # ---- 无 doc/token：一次性执行，不跨块 ----
    post("/api/run-r", {"code": "z <- 1"})
    r5, _ = post("/api/run-r", {"code": "exists('z')"})
    check("无 doc 时退化为一次性执行", "FALSE" in (r5.get("stdout") or ""), str(r5)[:200])

    # ---- 空代码仍按原样拒绝 ----
    e, sec = post("/api/run-r", {"code": "   ", "doc": DOC})
    check("空代码返回 400", sec == 400 and e.get("ok") is False, "%s %s" % (sec, e))

    md_server.md_runs.shutdown_all()
    httpd.shutdown()
    httpd.server_close()
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
