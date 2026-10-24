# -*- coding: utf-8 -*-
"""E2E: /api/export-paged v40 - base css / table split / img fit / ref-table"""
# --- 测试入口 shim：本文件在 tests/ 下。便携运行时（python311._pth）不会把 script dir
# 加进 sys.path，所以 tests/ 与仓库根两个都显式挂上，跨用例 import 与根模块 import 才成立 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import io, json, sys, threading, time, urllib.request

BASE = "http://127.0.0.1:18766"

# 自己起一份后端：这两个用例原本假定本机已有实例在 18766 上跑，机器没开时就只能
# 报“连接被拒”，看着像代码坏了。改成自给自足——和 _test_routes.py 同一手法。
sys.argv = ["md_server.py"]
import md_server                                              # noqa: E402
httpd = md_server.ReuseTCPServer(("127.0.0.1", 18766), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

FAILS = []

def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + " | " + name + ((" | " + detail) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def post(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

body_a4 = (
    "<h1>打印测试</h1>"
    "<p>正文段落</p>"
    "<table><thead><tr><th>列1</th><th>列2</th></tr></thead>"
    "<tbody><tr><td>a</td><td>b</td></tr></tbody></table>"
    "<table><thead><tr><th>编号</th><th>引用</th><th>出处</th></tr></thead>"
    "<tbody><tr><td>[1]</td><td>x. t (2026)</td><td>KB demo</td></tr></tbody></table>"
    "<pre><code>long code line</code></pre>"
    "<img src=\"/img?path=C:/nonexistent/tall.png\" alt=\"tall\">"
)

# --- Case 1: A4 default ---
j = post("/api/export-paged", {"path": None, "bodyHtml": body_a4, "tsCss": "",
                               "cfg": {"paper": "A4", "mt": 25, "mb": 25}})
check("E1 api ok", j.get("ok") is True, str(j))
with urllib.request.urlopen(BASE + "/static/document.paged.html", timeout=10) as r:
    html = r.read().decode("utf-8")

check("E2 table border css", ".markdown-body th,.markdown-body td{border:1px solid #bbb" in html)
check("E3 th bg css", ".markdown-body th{background:#f0f2f6" in html)
check("E4 thead repeat", ".markdown-body thead{display:table-header-group;}" in html)
check("E5 tr no-split", ".markdown-body tr{break-inside:avoid;}" in html)
check("E6 table allow-split", ".markdown-body table{border-collapse:collapse;margin:1em 0;width:100%;table-layout:auto;font-size:.93em;break-inside:auto;}" in html)
check("E7 cell keep-all+anywhere", "word-break:keep-all;overflow-wrap:anywhere;}" in html)
check("E8 pre pre-wrap", "white-space:pre-wrap !important" in html)
check("E9 border-box", "*{box-sizing:border-box;}" in html)
check("E10 img max-height A4=245", "max-height:245.00mm" in html)
check("E11 ref-table class", '<table class="ref-table">' in html)
check("E12 ref-table col widths", "table.ref-table th:nth-child(2),.markdown-body table.ref-table td:nth-child(2){width:47%;}" in html)
check("E13 normal table untouched", '<table class="ref-table"><thead><tr><th>列1</th>' not in html)
check("E14 order: base before ts override zone", html.find("box-sizing:border-box") < html.find("md-editor-typeset") if "md-editor-typeset" in html else True)

# --- Case 2: custom paper 210x140, margins 20 -> img max-height = 99 ---
j2 = post("/api/export-paged", {"path": None, "bodyHtml": body_a4, "tsCss": "",
                                "cfg": {"paper": "custom", "pw": "210", "ph": "140", "mt": 20, "mb": 20}})
check("E15 api ok custom", j2.get("ok") is True, str(j2))
with urllib.request.urlopen(BASE + "/static/document.paged.html?t=2", timeout=10) as r:
    html2 = r.read().decode("utf-8")
check("E16 img max-height custom=98", "max-height:98.00mm" in html2)

# --- Case 3: three-line table ts_css override still wins (important later in doc) ---
ts = ".markdown-body table{border:none !important;border-top:2px solid currentColor !important;}"
j3 = post("/api/export-paged", {"path": None, "bodyHtml": body_a4, "tsCss": ts,
                                "cfg": {"paper": "A4"}})
check("E17 api ok ts", j3.get("ok") is True)
with urllib.request.urlopen(BASE + "/static/document.paged.html?t=3", timeout=10) as r:
    html3 = r.read().decode("utf-8")
check("E18 ts after base", html3.find("border:none !important") > html3.find("1px solid #bbb"))
check("E19 base still present with ts", "border:1px solid #bbb" in html3)

# --- Case 4: Legal paper map ---
j4 = post("/api/export-paged", {"path": None, "bodyHtml": body_a4, "tsCss": "",
                                "cfg": {"paper": "Legal"}})
with urllib.request.urlopen(BASE + "/static/document.paged.html?t=4", timeout=10) as r:
    html4 = r.read().decode("utf-8")
check("E20 img max-height Legal=303.60", "max-height:303.60mm" in html4)  # 355.6-25-25-2

# --- Case 5: TOC page numbering (v41) ---
j5 = post("/api/export-paged", {"path": None, "bodyHtml": body_a4, "tsCss": "",
                                "cfg": {"paper": "A4", "toc": {"on": "on", "pos": "top", "solo": True},
                                        "pn": {"on": "on", "pos": "bc"}}})
check("E21 api ok toc", j5.get("ok") is True, str(j5))
with urllib.request.urlopen(BASE + "/static/document.paged.html?t=5", timeout=10) as r:
    html5 = r.read().decode("utf-8")
check("E22 toc rule no target-counter", ".md-toc a::after{content:'  ' target-counter" not in html5)
check("E23 filler toc-only logic", "tocOnly" in html5 and "md-toc-pg" in html5)
check("E24 filler skip+shown mapping", "shown[i] = skip[i] ? 0 : ++c" in html5)

# --- Case 6: book-standard pagination + outer page numbers (v42) ---
j6 = post("/api/export-paged", {"path": None, "bodyHtml": body_a4, "tsCss": "",
                                "cfg": {"paper": "A4", "toc": {"on": "on", "pos": "top", "solo": True},
                                        "pn": {"on": "on", "pos": "outer", "tpl": "{p}", "size": 9}}})
check("E25 api ok v42", j6.get("ok") is True, str(j6))
with urllib.request.urlopen(BASE + "/static/document.paged.html?t=6", timeout=10) as r:
    html6 = r.read().decode("utf-8")
check("E26 h1 break-before", "h1{break-before:page;}" in html6)
check("E27 h2-h4 avoid", "h2,h3,h4{break-after:avoid;}" in html6)
check("E28 p orphans/widows", "p{orphans:2;widows:2;}" in html6)
check("E29 li orphans 1/1", "li{orphans:1;widows:1;}" in html6)
check("E30 hr rule", "hr{break-inside:avoid;break-after:avoid;}" in html6)
check("E31 pre no force-avoid", "white-space:pre-wrap !important;overflow-wrap:anywhere !important;break-inside:avoid" not in html6)
check("E32 img block centered", ".markdown-body img{display:block;margin:0 auto;max-width:100%;max-height:" in html6)
check("E33 toc dots css", ".md-toc .toc-dots{flex:1;" in html6)
check("E34 toc flex baseline", ".md-toc a{display:flex;align-items:baseline;" in html6)
check("E35 outer both boxes", '@bottom-right{content:" ";font-size:9pt;}@bottom-left{content:" ";font-size:9pt;}' in html6)
check("E36 filler parity sel", "(shown[i] % 2 === 1) ? sel.odd : sel.even" in html6)
check("E37 filler dots span", "dots.className = 'toc-dots'" in html6)
check("E38 filler gray", "'#666'" in html6)

# --- Case 7: v43 图片版面预算修正 + 超高长图切片 ---
import os as _os
import urllib.parse as _up
from PIL import Image as _Image

# 7a: A4 预算 297-25-25-2 = 245mm；p:has(>img) margin 0
check("E39 img maxh 245.00", "max-height:245.00mm" in html6)
check("E40 p:has(>img) margin0", ".markdown-body p:has(>img){margin:0;}" in html6)

# 7b: 造一张带空白行的长截图（1000x4000，黑条模拟文字行）
_td = _os.path.join(_ROOT, "_tmp_slice_fixture")
_os.makedirs(_td, exist_ok=True)
_tall_png = _os.path.join(_td, "tall.png")
_small_png = _os.path.join(_td, "small.png")
_im = _Image.new("RGB", (1000, 4000), "white")
_px = _im.load()
for band in range(0, 4000, 120):  # 每 120px：60px 黑条 + 60px 空白
    for y in range(band, min(band + 60, 4000)):
        for x in range(100, 900):
            _px[x, y] = (20, 20, 20)
_im.save(_tall_png)
_Image.new("RGB", (800, 400), "white").save(_small_png)

body_slice = (
    '<h1>切片测试</h1><p>前置段落</p>'
    '<p><img src="/img?path=' + _up.quote(_tall_png.replace("\\\\", "/")) + '" alt="long"></p>'
    '<p><img src="/img?path=' + _up.quote(_small_png.replace("\\\\", "/")) + '" alt="small"></p>'
)
j7 = post("/api/export-paged", {"path": None, "bodyHtml": body_slice, "tsCss": "",
                                "cfg": {"paper": "A4", "mt": 25, "mb": 25}})
check("E41 api ok v43", j7.get("ok") is True, str(j7))
with urllib.request.urlopen(BASE + "/static/document.paged.html?t=7", timeout=10) as r:
    html7 = r.read().decode("utf-8")

check("E42 tall sliced to /static/_slice/", '/static/_slice/' in html7)
import re as _re
_strips = _re.findall(r'src="(/static/_slice/([0-9a-f]{12}-\d+)/strip-(\d+)\.png)"', html7)
check("E43 strip count 2..20", 2 <= len(_strips) <= 20, "n=%d" % len(_strips))
_check_ok = bool(_strips)
for _u, _dg, _n in _strips:
    if not _os.path.isfile(_os.path.join(_ROOT,
                                         "_slice", _dg, "strip-%02d.png" % int(_n))):
        _check_ok = False
check("E44 strip files on disk", _check_ok)
check("E45 small img unsliced", "/img?path=" in html7 and 'alt="small"' in html7)
check("E46 tall original gone", 'src="/img?path=' + _up.quote(_tall_png.replace("\\\\", "/")) + '"' not in html7)
# 幂等：重复导出切片文件数不变（复用不重切）
_n_before = len({(d, n) for _, d, n in _strips})
post("/api/export-paged", {"path": None, "bodyHtml": body_slice, "tsCss": "",
                           "cfg": {"paper": "A4", "mt": 25, "mb": 25}})
_n_after = len({(d, n) for _, d, n in
                _re.findall(r'src="(/static/_slice/([0-9a-f]{12}-\d+)/strip-(\d+)\.png)"',
                            urllib.request.urlopen(BASE + "/static/document.paged.html?t=8",
                                                   timeout=10).read().decode("utf-8"))})
check("E47 idempotent re-export", _n_before == _n_after, "%d vs %d" % (_n_before, _n_after))

print("---")
print("TOTAL: %d, FAIL: %d" % (47, len(FAILS)))
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL PASS")
