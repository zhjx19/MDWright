# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 图注口径回归：

- `![说明](x.png "图 1 结构")` → title 作题注，alt 不出现
- `![说明](x.png)` → 不出题注（Word 里不再凭空多一行斜体 alt）
- 行内图 / 并排块里的图不产生题注
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
import os
import re
import shutil
import sys
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT
fails = []
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def main():
    import md_pandoc
    import md_tools
    exe = md_tools.find_pandoc("")
    if not exe:
        print("缺 pandoc，跳过")
        sys.exit(77)
    tmp = tempfile.mkdtemp(prefix="mdcap-")
    try:
        img = os.path.join(tmp, "a.png")
        with open(img, "wb") as f:
            f.write(PNG)
        src = img.replace("\\", "/")

        md = ('![说明](%s "图 1 结构")\n\n' % src
              + '![说明二](%s)\n\n' % src
              + '文字里的 ![行内](%s "行内题注")\n\n' % src
              + '@@ begin fill {50|50}\n'
              + '![甲](%s "并排甲")\n' % src
              + '![乙](%s "并排乙")\n' % src
              + '@@ end fill\n')
        out = os.path.join(tmp, "cap.docx")
        md_pandoc.export_docx(md, None, out, exe, cn=True)
        doc = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8", "replace")

        caps = re.findall(r"<w:p\b.*?</w:p>", doc, re.S)
        cap_paras = [p for p in caps if 'w:pStyle w:val="ImageCaption"' in p]
        cap_text = "".join("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
                           for p in cap_paras)
        check("只出一处图注（alt-only / 行内 / 并排都不出）",
              len(cap_paras) == 1, "n=%d text=%r" % (len(cap_paras), cap_text))
        check("题注取 title", cap_text == "图 1 结构", repr(cap_text))
        check("题注里没有 alt 文本", "说明" not in cap_text, repr(cap_text))
        for word in ("说明二", "行内题注", "并排甲", "并排乙"):
            check("题注不含 %s" % word, word not in cap_text, repr(cap_text))
        ok = "CaptionedFigure" in doc
        check("有题的图走 Figure", ok, "缺 CaptionedFigure")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
