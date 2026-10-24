# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""导出样式对齐测试（R1）：新语法在独立 HTML 与分页 HTML 中必须有样式，
否则导出后 callout/脚注/高亮全部裸奔（预览与导出不同源）。
另验 front matter 的 title 进入导出文档标题。
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
import threading
import time
import urllib.request

# Windows 控制台默认 GBK，中文断言文本可能含 GBK 外字符
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
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
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (PORT, path), timeout=30) as r:
        return r.read().decode("utf-8")


BODY = ('<p>x</p>'
        '<div class="callout callout-note"><p class="callout-title">NOTE</p><p>内容</p></div>'
        '<p><mark>高亮</mark> 与 H<sub>2</sub>O 与 x<sup>2</sup></p>'
        '<dl><dt>t</dt><dd>d</dd></dl>'
        '<section class="footnotes"><hr class="fn-sep"><ol>'
        '<li id="fn-1">脚注 <a href="#fnref-1" class="fn-back">↩</a></li></ol></section>'
        '<sup class="fn-ref"><a href="#fn-1" id="fnref-1">1</a></sup>')


def main():
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        post("/api/export-html", {"path": None, "bodyHtml": BODY, "tsCss": "",
                                  "docTitle": "我的标题"})
        html = get("/static/document.html")
        for key, needle in [("独立版 callout 容器样式", ".markdown-body .callout"),
                            ("独立版 callout 五型", ".callout-note"),
                            ("独立版 行内高亮", ".markdown-body mark"),
                            ("独立版 定义列表", ".markdown-body dl"),
                            ("独立版 脚注区", ".markdown-body .footnotes"),
                            ("独立版 脚注上标", ".fn-ref"),
                            ("独立版 标题取 front matter", "<title>我的标题</title>")]:
            check(key, needle in html, "缺: " + needle)

        # C1：导出必须内联 highlight.js 主题，否则带 hljs-* span 的代码在导出里全黑
        post("/api/export-html", {"path": None, "tsCss": "", "docTitle": "",
                                  "bodyHtml": '<pre><code><span class="hljs-keyword">def</span></code></pre>'})
        with_hl = get("/static/document.html")
        check("独立版 注入 hljs 主题（C1）", ".hljs-keyword" in with_hl, "缺 hljs 主题 CSS")
        check("独立版 hljs span 保留", "hljs-keyword" in with_hl)

        # I2：非字符串 docTitle（数字/列表）不得让导出 500
        for bad in (123, ["a", "b"]):
            j = post("/api/export-html", {"path": None, "bodyHtml": "<h1>回退标题</h1>",
                                          "tsCss": "", "docTitle": bad})
            ok = j.get("ok") is True
            check("独立版 非法 docTitle %r 不 500（I2）" % (bad,), ok, str(j))
        check("独立版 非法 docTitle 回退首个 h1", "<title>回退标题</title>" in get("/static/document.html"))

        post("/api/export-paged", {"path": None, "bodyHtml": BODY, "tsCss": "",
                                   "docTitle": "我的标题", "cfg": {}})
        paged = get("/static/document.paged.html")
        for key, needle in [("分页版 callout 样式", ".markdown-body .callout"),
                            ("分页版 行内高亮", ".markdown-body mark"),
                            ("分页版 脚注区样式", ".markdown-body .footnotes"),
                            ("分页版 标题取 front matter", "<title>我的标题</title>")]:
            check(key, needle in paged, "缺: " + needle)

        post("/api/export-paged", {"path": None, "tsCss": "", "docTitle": "",
                                   "bodyHtml": '<pre><code><span class="hljs-keyword">def</span></code></pre>',
                                   "cfg": {}})
        check("分页版 注入 hljs 主题（C1）", ".hljs-keyword" in get("/static/document.paged.html"))
    finally:
        httpd.shutdown()
        httpd.server_close()
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
