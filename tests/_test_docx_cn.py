# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 中文版式（v3.7.0 第二步）回归：

- 正文：首行缩进 2 字符（firstLineChars=200）、1.5 倍行距（line=360 auto）
- 标题：黑色（清掉 pandoc 的 accent1 蓝）、加粗、小二/三号/小三/小四
- 代码块：四周 1pt 边框 + 浅底 + 左缩进 3 字符、五号
- 行内代码：浅底、五号（仍是 Consolas）
- 引用：左侧 3pt 边框、去首行缩进
- 表格单元格（Compact）：五号
- 图注居中、去斜体；Figure 居中
- docxCn=false → 样式一律不动（保留 pandoc 默认）
- 与字体 / 三线表 / 版面同开互不打架，docx 可回读
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


MD = """# 一级标题

这是第一段正文。行内 `code` 与公式 $a^2$。

## 二级标题

> 引用一段话。

- 列表项

| 列A | 列B |
|---|---|
| 1 | 2 |

```r
x <- 1
```

![示意](no-such.png)
"""


def styles_of(path):
    z = zipfile.ZipFile(path)
    return z.read("word/styles.xml").decode("utf-8", "replace")


def block(styles, sid):
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
    if not pandoc():
        print("缺 pandoc，跳过")
        sys.exit(77)
    tmp = tempfile.mkdtemp(prefix="mdcn-")
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        doc = os.path.join(tmp, "中文版式.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write(MD)

        j = post("/api/export-docx", {"path": doc, "markdown": MD,
                                      "docxCn": True,
                                      "outPath": os.path.join(tmp, "cn.docx")})
        check("中文版式导出 ok", j.get("ok") is True, str(j)[:300])
        out = j.get("path") or ""
        if not (out and os.path.isfile(out)):
            check("产出 docx", False, "缺文件")
        else:
            s = styles_of(out)
            body = block(s, "BodyText")
            first = block(s, "FirstParagraph")
            check("正文首行缩进 2 字符",
                  'firstLineChars="200"' in body and 'firstLineChars="200"' in first,
                  body[:400])
            check("正文 1.5 倍行距",
                  'w:line="360"' in body and 'w:lineRule="auto"' in body, body[:400])
            h1 = block(s, "Heading1")
            check("H1 去掉蓝色", "themeColor" not in h1 and 'w:color' not in h1, h1[:400])
            check("H1 加粗", "<w:b />" in h1 or "<w:b/>" in h1, h1[:400])
            check("H1 小二（18pt=36）", 'w:sz w:val="36"' in h1, h1[:400])
            h2 = block(s, "Heading2")
            check("H2 三号（16pt=32）", 'w:sz w:val="32"' in h2, h2[:400])
            h3 = block(s, "Heading3")
            check("H3 小三（15pt=30）", 'w:sz w:val="30"' in h3, h3[:400])
            h4 = block(s, "Heading4")
            check("H4 小四（12pt=24）", 'w:sz w:val="24"' in h4, h4[:400])
            code = block(s, "SourceCode")
            check("代码块有边框", "<w:pBdr>" in code, code[:500])
            check("代码块浅底", 'w:fill="F2F2F2"' in code, code[:500])
            check("代码块左缩进 3 字符", 'leftChars="300"' in code, code[:500])
            check("代码块五号（10.5pt=21）", 'w:sz w:val="21"' in code, code[:500])
            inline = block(s, "VerbatimChar")
            check("行内代码浅底", 'w:fill="F2F2F2"' in inline, inline[:400])
            check("行内代码仍是 Consolas", 'w:ascii="Consolas"' in inline, inline[:400])
            quote = block(s, "BlockText")
            check("引用左侧边框", "<w:left" in quote and "<w:pBdr>" in quote, quote[:500])
            check("引用去首行缩进", 'firstLine="0"' in quote or 'firstLineChars="0"' in quote,
                  quote[:500])
            compact = block(s, "Compact")
            check("表格单元格五号", 'w:sz w:val="20"' in compact, compact[:400])
            cap = block(s, "ImageCaption")
            check("图注居中", 'w:jc w:val="center"' in cap, cap[:400])
            caption = block(s, "Caption")
            check("图注去斜体（继承自 Caption）",
                  "<w:i />" not in caption and "<w:i/>" not in caption, caption[:400])
            fig = block(s, "Figure")
            check("Figure 居中", 'w:jc w:val="center"' in fig, fig[:400])
            ok, detail = readable(out)
            check("中文版式 docx 结构可读", ok, detail)

        # 2) 关掉 → 样式保持 pandoc 默认
        j2 = post("/api/export-docx", {"path": doc, "markdown": MD,
                                       "docxCn": False,
                                       "outPath": os.path.join(tmp, "plain.docx")})
        out2 = j2.get("path") or ""
        check("关闭中文版式导出 ok", j2.get("ok") is True, str(j2)[:300])
        if out2 and os.path.isfile(out2):
            s2 = styles_of(out2)
            check("关闭后正文不缩进", "firstLineChars" not in block(s2, "BodyText"))
            check("关闭后标题保留默认蓝色",
                  "themeColor" in block(s2, "Heading1"), block(s2, "Heading1")[:400])
            check("关闭后代码块无边框", "<w:pBdr>" not in block(s2, "SourceCode"))
            ok2, detail2 = readable(out2)
            check("关闭后 docx 结构可读", ok2, detail2)

        # 3) 与字体 / 三线表 / 版面同开
        j3 = post("/api/export-docx", {
            "path": doc, "markdown": MD, "docxCn": True, "threeLine": True,
            "tableHeadOn": True, "tableHeadColor": "#dbe5ff",
            "latinFont": "Georgia", "cjkFont": "SimSun", "headingFont": "SimHei",
            "page": {"paper": "A4", "mt": 25, "mr": 18, "mb": 25, "ml": 18},
            "outPath": os.path.join(tmp, "all.docx")})
        check("全套同开导出 ok", j3.get("ok") is True, str(j3)[:300])
        out3 = j3.get("path") or ""
        if out3 and os.path.isfile(out3):
            s3 = styles_of(out3)
            d3 = zipfile.ZipFile(out3).read("word/document.xml").decode("utf-8", "replace")
            check("中文版式仍在（正文缩进）", 'firstLineChars="200"' in block(s3, "BodyText"))
            check("字体仍在", 'w:eastAsia="SimHei"' in block(s3, "Heading1"))
            check("版面仍在", 'w:w="11906"' in d3)
            check("表头底色仍在", 'w:fill="DBE5FF"' in d3)
            ok3, detail3 = readable(out3)
            check("全套 docx 结构可读", ok3, detail3)
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
