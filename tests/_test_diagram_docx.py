# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""图表围栏 → Word 位图的导出链路回归（v3.3.0）：

预览把 mermaid / dot / wavedrom / vega 渲染成 SVG，Word 只吃位图，所以导出时
前端栅格化后连同「语言 + 源码原文」交回后端，后端按这两项把围栏整块换成一张图。
本文件管三件事：
- 键必须逐字对上，对不上就保持代码块（fail-closed，不塞错图）；
- 宽度优先取围栏的 `{N}`，没有就用前端按显示尺寸算的百分比；
- 真导出一份 docx：图片进 word/media，围栏源码不残留在正文里。
前端那一段（栅格化 + 请求体）在 `_test_diagram_export_ui.py`。
"""
# --- 测试入口 shim ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import base64
import os
import sys
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.argv = ["md_server.py"]
import md_pandoc          # noqa: E402
import md_tools           # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-48s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


MERMAID = "```mermaid\ngraph TD\nA-->B\n```\n"
DOT = "```dot\ndigraph { A -> B }\n```\n"


def prep(src, diagrams=None):
    return md_pandoc.prepare_markdown(src, diagrams)


def main():
    # ---- 1 纯改写：命中就换图，没命中保持代码块 ----
    key = md_pandoc.diagram_key("mermaid", "graph TD\nA-->B")
    out = prep(MERMAID, {key: {"path": "C:/tmp/d0.png", "width": 80}})
    check("命中围栏换成图片", "![](<C:/tmp/d0.png>)" in out, out)
    check("围栏源码不再出现", "graph TD" not in out, out)
    check("无 {N} 时用前端宽度", "{width=80%}" in out, out)
    check("反斜杠路径转正斜杠",
          "C:\\" not in prep(MERMAID, {key: {"path": r"C:\tmp\d0.png", "width": 80}}), out)

    miss = md_pandoc.diagram_key("mermaid", "graph LR\nB-->C")
    out = prep(MERMAID, {miss: {"path": "x.png", "width": 80}})
    check("键对不上保持代码块（语言保留）", "```mermaid" in out and "graph TD" in out, out)
    out = prep(MERMAID, {md_pandoc.diagram_key("dot", "graph TD\nA-->B"):
                         {"path": "x.png", "width": 80}})
    check("语言不同不算命中", "```mermaid" in out, out)

    # ---- 2 宽度：围栏 {N} 优先于前端算出的百分比 ----
    out = prep("```mermaid {30}\ngraph TD\nA-->B\n```\n",
               {key: {"path": "x.png", "width": 80}})
    check("围栏 {30} 优先", "{width=30%}" in out, out)
    out = prep("```mermaid {150}\ngraph TD\nA-->B\n```\n",
               {key: {"path": "x.png", "width": 80}})
    check("超 100 钳到 100", "{width=100%}" in out, out)
    out = prep("```mermaid\ngraph TD\nA-->B\n```\n", {key: {"path": "x.png"}})
    check("前端没给宽度时落 95%", "{width=95%}" in out, out)

    # ---- 3 边界：CRLF、未闭合 ----
    out = prep(MERMAID.replace("\n", "\r\n"),
               {md_pandoc.diagram_key("mermaid", "graph TD\r\nA-->B"):
                {"path": "x.png", "width": 70}})
    check("CRLF 源文也能对上", "![](" in out, out)
    out = prep("```mermaid\ngraph TD\nA-->B\n", {key: {"path": "x.png", "width": 70}})
    check("未闭合围栏原样透传", out.startswith("```mermaid"), out)

    # ---- 4 计数：导出后回报「几张没渲染成功」 ----
    src = MERMAID + DOT + "\n```r\n1 + 1\n```\n"
    check("只数图表围栏", md_pandoc.count_diagram_fences(src) == 2,
          str(md_pandoc.count_diagram_fences(src)))
    check("普通代码块不计", md_pandoc.count_diagram_fences("```r\n1\n```\n") == 0)

    # ---- 5 真导出：图进 word/media，源码不进正文 ----
    pandoc = md_tools.find_pandoc("")
    png = os.path.join(_ROOT, "docs", "screenshots", "writing.png")
    if not pandoc or not os.path.isfile(png):
        print("SKIP 真导出（缺 pandoc 或示例图）")
        print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
        sys.exit(77 if fails == [] else 1)

    with open(png, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    md = "正文\n\n" + MERMAID + "\n" + DOT + "\n"
    diagrams = [{"lang": "mermaid", "code": "graph TD\nA-->B", "png": b64, "width": 60}]
    tmp = tempfile.mkdtemp(prefix="mddiag-")
    out_docx = os.path.join(tmp, "t.docx")
    stats = {}
    try:
        md_pandoc.export_docx(md, None, out_docx, pandoc,
                              diagrams=diagrams, stats=stats)
        check("导出成功但没有落一个空文件",
              os.path.isfile(out_docx) and os.path.getsize(out_docx) > 2000,
              str(os.path.getsize(out_docx) if os.path.isfile(out_docx) else -1))
        z = zipfile.ZipFile(out_docx)
        media = [n for n in z.namelist() if n.startswith("word/media/")]
        body = z.read("word/document.xml").decode("utf-8", "replace")
        z.close()
        check("图片进 word/media", len(media) >= 1, str(media))
        check("正文里有图", "<w:drawing>" in body)
        check("mermaid 源码没残留", "graph TD" not in body)
        check("没有多出题注（alt 留空）", "图表" not in body, body[:200])
        check("未渲染的围栏仍是代码块", "digraph" in body, body[:200])
        check("回报嵌入了 1 张", stats.get("diagrams") == 1, str(stats))
        check("源文里共 2 张图表", md_pandoc.count_diagram_fences(md) == 2)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
