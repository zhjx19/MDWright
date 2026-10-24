# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""导出路径校验回归（UI 重构新增）：
- `_norm_out_path`：默认路径、绝对路径通过；相对路径 / 扩展名不符 / 父目录不存在 /
  指向安装目录 docs/ 一律拒绝并给明确原因
- 端到端：带 outPath 的 Word 导出真的写到用户指定位置
（`/api/save-dialog` 会弹原生框、阻塞等人点，不做自动测试。）
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
import io
import os
import shutil
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
        with urllib.request.urlopen(req, timeout=200) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "HTTP %d" % e.code}


def main():
    tmp = tempfile.mkdtemp(prefix="mdout-")
    doc = os.path.join(tmp, "doc.md")
    open(doc, "w", encoding="utf-8").write("# x\n")
    try:
        # ---- 纯函数：路径校验 ----
        ok, p = md_server._norm_out_path("", doc, "docx")
        check("默认路径落在文档同目录",
              ok and os.path.dirname(os.path.abspath(p)) == tmp and p.endswith(".docx"), p)

        want = os.path.join(tmp, "自定义 名字#1.docx")
        ok, p = md_server._norm_out_path(want, doc, "docx")
        check("绝对路径通过", ok and p == os.path.abspath(want), str(p))

        ok, e = md_server._norm_out_path("relative.docx", doc, "docx")
        check("相对路径被拒", (not ok) and "绝对路径" in e, e)

        ok, e = md_server._norm_out_path(os.path.join(tmp, "x.pdf"), doc, "docx")
        check("扩展名不符被拒", (not ok) and ".docx" in e, e)

        ok, e = md_server._norm_out_path(os.path.join(tmp, "no", "x.docx"), doc, "docx")
        check("父目录不存在被拒", (not ok) and "不存在" in e, e)

        builtin = os.path.join(HERE, "docs", "x.docx")
        ok, e = md_server._norm_out_path(builtin, doc, "docx")
        check("禁止导出到安装目录 docs/", (not ok) and "安装目录" in e, e)

        # ---- 端到端：outPath 生效 ----
        httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.4)
        try:
            chosen = os.path.join(tmp, "用户选的 位置#2.docx")
            j = post("/api/export-docx", {"path": doc, "markdown": "# t\n",
                                          "outPath": chosen})
            check("Word 导出写到用户指定路径",
                  j.get("ok") is True and os.path.normcase(j.get("path") or "") ==
                  os.path.normcase(os.path.abspath(chosen)), str(j)[:200])
            check("指定路径文件确实存在", os.path.isfile(chosen))

            j2 = post("/api/export-docx", {"path": doc, "markdown": "# t\n",
                                           "outPath": os.path.join(tmp, "bad.pdf")})
            check("错误扩展名请求被拒且不产文件",
                  j2.get("ok") is False and not os.path.exists(os.path.join(tmp, "bad.pdf")),
                  str(j2)[:160])
        finally:
            httpd.shutdown()
            httpd.server_close()
        # ---- 保存框：argv 里不得出现 NUL（曾因此让弹框永不出现） ----
        calls = []

        class _Spy2(object):
            def __init__(self, real):
                self.real = real

            def run(self, cmd, *a, **kw):
                calls.append(list(cmd))
                return self.real.run(cmd, *a, **kw)

        spy2 = _Spy2(md_server.subprocess)
        md_server.subprocess = spy2
        try:
            md_server._save_dialog_subprocess("导出 .docx", "x.docx", "", "docx")
        finally:
            md_server.subprocess = spy2.real
        check("保存框被真的调起", bool(calls), str(calls)[:120])
        if calls:
            argv = calls[-1]
            check("argv 中无 NUL 字符（含过滤器就会炸）",
                  all("\0" not in str(x) for x in argv),
                  str([x for x in argv if "\0" in str(x)])[:120])
            check("argv 末位是扩展名", argv[-1] == "docx", str(argv[-3:]))

        # _savefile.py 自检：过滤器结构正确（不弹框）
        import subprocess as _sp
        sel = os.path.join(tmp, "selfcheck.txt")
        py = os.path.join(HERE, "python", "python.exe")
        if not os.path.isfile(py):
            py = sys.executable
        r = _sp.run([py, os.path.join(HERE, "_savefile.py"), sel, "导出", "x.docx", "",
                     "docx", "--selftest"], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=60)
        ok_self = r.returncode == 0 and os.path.isfile(sel) and \
            io.open(sel, encoding="utf-8").read().strip() == "SELFTEST OK"
        check("_savefile.py 自检通过（过滤器结构）", ok_self,
              (r.stderr or r.stdout or "")[-200:])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
