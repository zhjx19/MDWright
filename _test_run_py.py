# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Python 代码块执行回归（v2.6.0，走内置便携运行时）：
- stdout 捕获（含中文）
- 异常 -> ok:false 且带最后一行错误
- 空代码拒绝
- 不残留临时脚本
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
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
        with urllib.request.urlopen(req, timeout=120) as r:
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
        j = post("/api/run-py", {"code": 'print("你好 Python")\nprint(1+1)'})
        check("Python：ok", j.get("ok") is True, str(j)[:200])
        check("Python：stdout 含中文", "你好 Python" in (j.get("stdout") or ""),
              j.get("stdout"))
        check("Python：stdout 含计算结果", "2" in (j.get("stdout") or ""), j.get("stdout"))
        check("Python：无图字段", not (j.get("image") or ""), str(j.get("image")))

        j = post("/api/run-py", {"code": 'raise ValueError("炸了")'})
        check("Python 异常：ok=false", j.get("ok") is False, str(j)[:160])
        check("Python 异常：错误含原文", "炸了" in ((j.get("error") or "") + (j.get("stderr") or "")),
              str(j)[:200])

        j = post("/api/run-py", {"code": "  "})
        check("Python 空代码：明确拒绝",
              j.get("ok") is False and "空" in (j.get("error") or ""), str(j)[:120])

        # 中文源码 + 多行
        j = post("/api/run-py",
                 {"code": '# 注释\n名称 = "张三"\nprint(f"你好，{名称}")\n'})
        check("Python 中文变量与 f-string", "你好，张三" in (j.get("stdout") or ""),
              j.get("stdout"))

        d = os.path.join(HERE, "runtime", "tmp", "py")
        left = [n for n in os.listdir(d)] if os.path.isdir(d) else []
        check("Python 临时脚本不残留", not left, str(left[:5]))
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
