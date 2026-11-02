# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 独行图对齐回归：

- 不带参数 → Figure（居中）
- `{c}` → Figure；`{l}` → FigureLeft（左）；`{r}` → FigureRight（右）
- 面板「图片」默认对齐（imgAlign）在没有显式参数时生效
- 三个段落样式的 jc 分别是 center / left / right
- 有题注的图仍走 CaptionedFigure（居中）
- 行内图、并排块不包 Figure Div
"""
# --- 测试入口 shim：同 _test_docx.py ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import base64
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
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


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


def styles_of(path):
    z = zipfile.ZipFile(path)
    return (z.read("word/document.xml").decode("utf-8", "replace"),
            z.read("word/styles.xml").decode("utf-8", "replace"))


def img_paras(doc):
    out = []
    for m in re.finditer(r"<w:p\b.*?</w:p>", doc, re.S):
        t = m.group(0)
        if "<w:drawing" not in t:
            continue
        st = re.search(r'<w:pStyle w:val="([^"]+)"', t)
        out.append(st.group(1) if st else "")
    return out


def style_block(styles, sid):
    m = re.search(r'<w:style [^>]*w:styleId="%s".*?</w:style>' % re.escape(sid),
                  styles, re.S)
    return m.group(0) if m else ""


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
    import md_pandoc
    exe = pandoc()
    if not exe:
        print("缺 pandoc，跳过")
        sys.exit(77)
    tmp = tempfile.mkdtemp(prefix="mda-")
    try:
        img = os.path.join(tmp, "a.png")
        with open(img, "wb") as f:
            f.write(PNG)
        src = img.replace("\\", "/")

        md = ("![](<%s>)\n\n" % src
              + "![图](<%s>){l}\n\n" % src
              + "![图](<%s>){r}\n\n" % src
              + "![图](<%s>){c}\n\n" % src
              + "![题注](<%s> \"图 1\")\n\n" % src
              + "看这张 ![](<%s>) 行内图\n\n" % src
              + "@@ begin fill {50|50}\n"
              + "![](<%s>)\n" % src + "![](<%s>)\n" % src
              + "@@ end fill\n")
        out = os.path.join(tmp, "align.docx")
        md_pandoc.export_docx(md, None, out, exe, cn=True)
        doc, styles = styles_of(out)
        got = img_paras(doc)
        check("默认/题注/行内/并排都在", len(got) >= 6, str(got))
        check("默认图 → Figure", got[0] == "Figure", str(got[:2]))
        check("{l} → FigureLeft", got[1] == "FigureLeft", str(got[:3]))
        check("{r} → FigureRight", got[2] == "FigureRight", str(got[:4]))
        check("{c} → Figure", got[3] == "Figure", str(got[:5]))
        check("有题注仍走 CaptionedFigure", got[4] == "CaptionedFigure", str(got[:6]))
        check("行内图不套 Figure", got[5] not in
              ("Figure", "FigureLeft", "FigureRight"), str(got[:7]))
        check("并排图不套 Figure", got[6] not in
              ("Figure", "FigureLeft", "FigureRight"), str(got[6:]))
        for sid, jc in (("Figure", "center"), ("FigureLeft", "left"),
                        ("FigureRight", "right")):
            b = style_block(styles, sid)
            check("%s 样式 jc=%s" % (sid, jc), 'w:jc w:val="%s"' % jc in b, b[:400])
            if sid != "Figure":
                check("%s 继承 Figure（不带正文缩进）" % sid,
                      '<w:basedOn w:val="Figure"' in b and "firstLine" not in b, b[:400])
        ok, detail = readable(out)
        check("对齐 docx 结构可读", ok, detail)

        # 面板默认对齐（left）：没有显式参数时走 img_align
        out3 = os.path.join(tmp, "api-left.docx")
        md_pandoc.export_docx(md, None, out3, exe, cn=True, img_align="left")
        d3, _ = styles_of(out3)
        g3 = img_paras(d3)
        check("面板默认左对齐 → FigureLeft", g3 and g3[0] == "FigureLeft", str(g3[:2]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
