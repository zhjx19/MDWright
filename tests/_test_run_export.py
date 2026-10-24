# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 导出：运行结果注入 + 三线表（受排版开关控制）。"""
# --- 测试入口 shim ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import os
import re
import subprocess
import sys
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, _ROOT)
import md_pandoc  # noqa: E402

fails = []
PANDOC = md_pandoc.md_tools.find_pandoc("")


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


MD = ("```r\nx <- 1\n```\n\n"
      "```r\ny <- 2\n```\n\n"
      "```r\nz <- 3\n```\n\n"
      "```mermaid {30}\ngraph TD\nA-->B\n```\n\n"
      "| 列1 | 列2 |\n|---|---|\n| a | b |\n")

BLOCKS = [
    {"lang": "r", "code": "x <- 1", "stdout": "[1] 5.5\n", "stderr": "", "error": "",
     "image": ""},
    {"lang": "r", "code": "y <- 2", "stdout": "", "stderr": "", "error": "boom 中文错误",
     "image": ""},
]


def main():
    out = md_pandoc.inject_run_outputs(MD, BLOCKS)
    check("命中块注入 output 围栏", "```output" in out and "[1] 5.5" in out, out[:200])
    check("命中两个块各注入一个", out.count("```output") == 2, str(out.count("```output")))
    check("出错块注入错误行", "[错误] boom 中文错误" in out, out[:300])
    check("没有存档的块不加东西",
          "z <- 3" in out and out.count("```output") == 2, out[:400])
    check("图表围栏不被误判（仍原样）", "```mermaid {30}" in out, out[:300])
    check("表格等内容没被动", "| 列1 | 列2 |" in out, out[:300])
    check("源码本身没被改写", "x <- 1" in out and "```r" in out, "")

    # 图片输出 → 下行插图片（用存档读回的真实形态：image 是裸文件名、imageAbs 是绝对路径）
    import md_runs
    tmpdoc = os.path.join(tempfile.mkdtemp(prefix="mdimg-"), "d.md")
    open(tmpdoc, "w", encoding="utf-8").write("```r\nplot(1)\n```\n")
    md_runs.save_output("r", "plot(1)",
                        {"stdout": "", "error": "",
                         "image": os.path.join(_ROOT, "docs", "screenshots", "writing.png")},
                        tmpdoc, "")
    blocks = md_runs.read_outputs(tmpdoc, "")
    out2 = md_pandoc.inject_run_outputs("```r\nplot(1)\n```\n", blocks)
    injected = [ln for ln in out2.splitlines() if ln.startswith("![运行输出]")]
    check("图片输出插成图片行", bool(injected), out2[:200])
    check("图片用的是绝对路径（裸文件名 pandoc 找不到）",
          bool(injected) and re.search(r"!\[运行输出\]\(<[A-Za-z]:/", injected[0]) is not None,
          injected[0][:160] if injected else "")

    if not PANDOC:
        print("SKIP: 本机无 pandoc，跳过真导出（77）")
        print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
        sys.exit(77 if not fails else 1)

    tmp = tempfile.mkdtemp(prefix="mdexport-")
    docx = os.path.join(tmp, "t.docx")
    md_pandoc.export_docx(MD, None, docx)
    with zipfile.ZipFile(docx) as z:
        xml0 = z.read("word/document.xml").decode("utf-8")
    check("默认不改表格（无 tblBorders）", "<w:tblBorders>" not in xml0, "")

    md_pandoc.three_line_tables(docx, PANDOC)
    with zipfile.ZipFile(docx) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    check("三线表：有 tblBorders", "<w:tblBorders>" in xml, "")
    check("三线表：左右无框、内部无横线",
          '<w:left w:val="none"' in xml and '<w:right w:val="none"' in xml
          and '<w:insideH w:val="none"' in xml, "")
    check("三线表：表头行有底边", "<w:tcBorders>" in xml, "")
    r = subprocess.run([PANDOC, "-f", "docx", "-t", "markdown", docx],
                       capture_output=True, timeout=120)
    check("改完的 docx 仍可被 pandoc 读回", r.returncode == 0,
          (r.stderr or b"").decode("utf-8", "replace")[:200])

    # ── 端到端：真的走 /api/export-docx（注入 + 三线表都在端点里生效）──
    import json as _json
    import threading
    import urllib.request
    sys.argv = ["md_server.py"]
    import md_server
    import md_runs
    port = 18792
    httpd = md_server.ReuseTCPServer(("127.0.0.1", port), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        tdoc = os.path.join(tmp, "e2e.md")
        with open(tdoc, "w", encoding="utf-8") as f:
            f.write(MD + "\n```r\nplot(1)\n```\n")
        md_runs.save_output("r", "x <- 1", {"stdout": "[1] 5.5\n"}, tdoc, "")
        md_runs.save_output("r", "plot(1)",
                            {"stdout": "", "error": "",
                             "image": os.path.join(_ROOT, "docs", "screenshots", "writing.png")},
                            tdoc, "")
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/export-docx" % port,
            data=_json.dumps({"path": tdoc, "markdown": MD + "\n```r\nplot(1)\n```\n",
                              "outPath": os.path.join(tmp, "e2e.docx"),
                              "threeLine": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            j = _json.loads(resp.read().decode("utf-8"))
        check("端点导出成功", j.get("ok") is True, str(j)[:200])
        with zipfile.ZipFile(os.path.join(tmp, "e2e.docx")) as z:
            xml2 = z.read("word/document.xml").decode("utf-8")
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        check("端到端：文字输出进了 Word", "5.5" in xml2, "")
        check("端到端：运行图真的嵌进去了（<w:drawing> + media）",
              "<w:drawing>" in xml2 and len(media) >= 1, "media=%r" % (media[:3],))
        check("端到端：三线表生效", "<w:tblBorders>" in xml2, "")
        check("端到端：没把语法残渣带进正文",
              "@@" not in xml2 and "{80}" not in xml2, "")
    finally:
        httpd.shutdown()
        httpd.server_close()
        md_runs.shutdown_all()

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
