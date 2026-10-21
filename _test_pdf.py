# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""PDF 直出端到端回归（R2，需本机 Chromium 内核浏览器）：
- 产出合法 PDF（%PDF 头）
- 页数与分页 DOM 一致（两趟法校验，防半截 PDF）
- 纸张尺寸跟随 @page（A4 → MediaBox 595×842 附近）
- 未保存文档明确报错
"""
import json
import os
import re
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
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
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "HTTP %d" % e.code}


BODY = "<h1>第一章</h1><p>正文段落</p><p>" + ("填充内容。" * 1200) + "</p>"


def main():
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    tmp = tempfile.mkdtemp(prefix="mdpdf-")
    try:
        doc = os.path.join(tmp, "文档 名#1.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write("# x\n")
        j = post("/api/export-pdf", {"path": doc, "bodyHtml": BODY, "tsCss": "",
                                     "docTitle": "", "cfg": {"paper": "A4", "mt": 25, "mb": 25}})
        check("接口 ok", j.get("ok") is True, str(j)[:300])
        out = j.get("path") or ""
        check("落盘在同目录且为 .pdf",
              out.lower().endswith(".pdf")
              and os.path.normcase(os.path.dirname(out)) == os.path.normcase(tmp), out)
        if out and os.path.isfile(out):
            data = open(out, "rb").read()
            check("合法 PDF 头", data[:5] == b"%PDF-", str(data[:16]))
            pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
            check("页数 >= 2（长文分页）", pages >= 2, str(pages))
            check("接口回报页数与实际一致", j.get("pages") == pages,
                  "%r vs %r" % (j.get("pages"), pages))
            mb = re.findall(rb"/MediaBox\s*\[([^\]]*)\]", data)
            if mb:
                n = [float(v) for v in mb[0].split()]
                w, h = n[2] - n[0], n[3] - n[1]
                check("A4 纸张尺寸", abs(w - 595) < 6 and abs(h - 842) < 6,
                      "%r x %r" % (w, h))
            else:
                check("A4 纸张尺寸", False, "no MediaBox")

        j2 = post("/api/export-pdf", {"path": "", "bodyHtml": "<p>x</p>", "tsCss": "",
                                      "cfg": {}})
        check("未保存文档明确报错",
              j2.get("ok") is False and "保存" in (j2.get("error") or ""), str(j2))
        after = [n for n in os.listdir(tmp) if n.lower().endswith(".pdf")]
        check("未保存时不新增 PDF",
              len(after) == (1 if (out and os.path.isfile(out)) else 0), str(after))
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
