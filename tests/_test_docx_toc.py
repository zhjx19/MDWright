# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 目录回归：

- 开启后 document.xml 有 TOC 域（1-3 级）、目录标题是「目录」
- settings.xml 有 updateFields（Word 打开时生成目录条目）
- 关闭 / 不传 → 无 TOC 域
- 与页码同开时 updateFields 只写一次
"""
# --- 测试入口 shim：同 _test_docx.py ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT
PORT = 18790
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


MD = "# 一级\n\n正文\n\n## 二级\n\n### 三级\n\n#### 四级\n"


def read(path, name):
    z = zipfile.ZipFile(path)
    return z.read(name).decode("utf-8", "replace") if name in z.namelist() else ""


def pandoc():
    import md_tools
    return md_tools.find_pandoc("")


def readable(path):
    exe = pandoc()
    if not exe:
        return True, "缺 pandoc（跳过回读）"
    r = subprocess.run([exe, "-f", "docx", "-t", "markdown", path],
                       capture_output=True, timeout=120)
    return r.returncode == 0, (r.stderr or b"").decode("utf-8", "replace")[:200]


def main():
    if not pandoc():
        print("缺 pandoc，跳过")
        sys.exit(77)
    tmp = tempfile.mkdtemp(prefix="mdtoc-")
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        doc = os.path.join(tmp, "目录.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write(MD)

        j = post("/api/export-docx", {"path": doc, "markdown": MD,
                                      "docxToc": True,
                                      "outPath": os.path.join(tmp, "toc.docx")})
        check("目录导出 ok", j.get("ok") is True, str(j)[:300])
        out = j.get("path") or ""
        if out and os.path.isfile(out):
            d = read(out, "word/document.xml")
            check("有 TOC 域", "TOC \\o" in d, d[:0] + "缺 TOC")
            check("目录深度 1-3", '\\o &quot;1-3&quot;' in d or '\\o "1-3"' in d, d[:0])
            check("目录标题是中文", bool(re.search(
                r'<w:pStyle w:val="TOCHeading" />.*?目录.*?</w:p>', d, re.S)),
                "TOCHeading 段落不是「目录」")
            check("有 TOCHeading 样式", 'w:pStyle w:val="TOCHeading"' in d)
            st = read(out, "word/settings.xml")
            check("要求 Word 更新域", "<w:updateFields" in st, st[:300])
            ok, detail = readable(out)
            check("目录 docx 结构可读", ok, detail)

        # 关闭 / 不传
        for tag, extra in (("off", {"docxToc": False}), ("none", {})):
            j2 = post("/api/export-docx", dict({"path": doc, "markdown": MD,
                                                "outPath": os.path.join(tmp, tag + ".docx")},
                                               **extra))
            out2 = j2.get("path") or ""
            if out2 and os.path.isfile(out2):
                d2 = read(out2, "word/document.xml")
                check("%s 不生成 TOC" % tag, "TOC \\o" not in d2)
                check("%s 不写 updateFields" % tag,
                      "<w:updateFields" not in read(out2, "word/settings.xml"))

        # 与页码同开：updateFields 只写一次
        j3 = post("/api/export-docx", {
            "path": doc, "markdown": MD, "docxToc": True,
            "page": {"paper": "A4", "pn": {"on": "on", "pos": "bc",
                                           "tpl": "{p}", "size": 9}},
            "outPath": os.path.join(tmp, "both.docx")})
        out3 = j3.get("path") or ""
        if out3 and os.path.isfile(out3):
            st3 = read(out3, "word/settings.xml")
            check("TOC + 页码：updateFields 只一次",
                  st3.count("<w:updateFields") == 1, st3[:400])
            ok3, detail3 = readable(out3)
            check("TOC + 页码 docx 结构可读", ok3, detail3)
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
