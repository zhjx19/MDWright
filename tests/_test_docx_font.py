# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 导出字体（v3.4.0）的端到端回归（需本机 pandoc）：

- 传了标题/正文中文与西文字体 → styles.xml 无主题字体残留；标题（majorFont）
  与正文（minorFont）各落到各的字体，docDefaults 写死正文两槽
- 代码块（Verbatim Char）仍是 Consolas：等宽字体不跟随设置
- theme1.xml 的 major/minorFont 分别同步（导出后新插内容的兜底）
- 不传字体 → 默认 黑体（标题）/ 宋体（正文）/ Times New Roman
- 脏字体名（含 < > { }）→ 安全回落默认，且产出的 docx 仍能读回
- 与三线表同开：两条 XML 改写互不打架
"""
# --- 测试入口 shim：同 _test_docx.py（便携运行时不自动挂 script dir）---
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


MD = """# 一级标题 Heading

正文中文 English text。

## 二级 Sub

- 列表项 item

> 引用 quote

| 列A | 列B |
|---|---|
| 1 | 2 |

行内 `code` 与代码块：

```r
x <- 1
```
"""


def docxml(path):
    z = zipfile.ZipFile(path)
    return (z, z.read("word/styles.xml").decode("utf-8", "replace"),
            z.read("word/theme/theme1.xml").decode("utf-8", "replace")
            if "word/theme/theme1.xml" in z.namelist() else "")


def rfonts_near(xml, style_id, span=1200):
    i = xml.find('w:styleId="%s"' % style_id)
    if i < 0:
        return ""
    m = re.search(r"<w:rFonts[^/]*/>", xml[i:i + span])
    return m.group(0) if m else ""


def pandoc_roundtrip(path):
    import md_tools
    exe = md_tools.find_pandoc("")
    if not exe:
        return True, "缺 pandoc（跳过回读）"
    r = subprocess.run([exe, "-f", "docx", "-t", "markdown", path],
                       capture_output=True, timeout=120)
    return r.returncode == 0, (r.stderr or b"").decode("utf-8", "replace")[:200]


def main():
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    tmp = tempfile.mkdtemp(prefix="mdfont-")
    try:
        doc = os.path.join(tmp, "字体.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write(MD)

        # 1) 指定字体：西文 Georgia、正文中文宋体、标题中文楷体
        j = post("/api/export-docx", {"path": doc, "markdown": MD,
                                      "latinFont": "Georgia", "cjkFont": "SimSun",
                                      "headingFont": "KaiTi",
                                      "outPath": os.path.join(tmp, "指定字体.docx")})
        check("指定字体导出 ok", j.get("ok") is True, str(j)[:300])
        check("响应回显生效字体",
              (j.get("fonts") or {}) == {"latin": "Georgia", "cjk": "SimSun",
                                         "heading": "KaiTi"},
              str(j.get("fonts")))
        out = j.get("path") or ""
        if out and os.path.isfile(out):
            z, styles, theme = docxml(out)
            check("主题字体属性已清零", not re.findall(r'w:\w+Theme="[^"]*"', styles),
                  str(re.findall(r'w:\w+Theme="[^"]*"', styles)[:3]))
            i = styles.find("docDefaults")
            dd = re.search(r"<w:rFonts[^/]*/>", styles[i:i + 500])
            dd = dd.group(0) if dd else ""
            check("docDefaults 西文=Georgia", 'w:ascii="Georgia"' in dd, dd)
            check("docDefaults 中文=正文宋体", 'w:eastAsia="SimSun"' in dd, dd)
            head = rfonts_near(styles, "Heading1")
            check("标题落到标题字体（楷体），不跟正文",
                  'w:eastAsia="KaiTi"' in head and "SimSun" not in head, head)
            code = rfonts_near(styles, "VerbatimChar")
            check("代码块仍是 Consolas（等宽不跟随）",
                  'w:ascii="Consolas"' in code and "KaiTi" not in code, code)
            check("theme latin 同步", theme.count('typeface="Georgia"') >= 2,
                  str(re.findall(r'<a:latin typeface="[^"]*"', theme)))
            check("theme 标题档(major) 同步", "KaiTi" in theme.split("<a:minorFont>")[0],
                  str(re.findall(r'<a:ea typeface="[^"]*"', theme)))
            check("theme 正文档(minor) 同步", "SimSun" in theme.split("<a:minorFont>")[-1],
                  str(re.findall(r'<a:ea typeface="[^"]*"', theme)))
            ok, detail = pandoc_roundtrip(out)
            check("改字体后 docx 结构可读", ok, detail)

        # 2) 不传字体 → 默认 标题黑体 / 正文宋体 / 西文 TNR
        j2 = post("/api/export-docx", {"path": doc, "markdown": MD,
                                       "outPath": os.path.join(tmp, "默认字体.docx")})
        check("默认字体导出 ok", j2.get("ok") is True, str(j2)[:300])
        check("默认为 黑体 + 宋体 + TNR",
              (j2.get("fonts") or {}) == {"latin": "Times New Roman", "cjk": "SimSun",
                                          "heading": "SimHei"},
              str(j2.get("fonts")))
        out2 = j2.get("path") or ""
        if out2 and os.path.isfile(out2):
            _, styles2, theme2 = docxml(out2)
            check("默认 docDefaults 写死正文宋体/TNR",
                  'w:ascii="Times New Roman"' in styles2 and 'w:eastAsia="SimSun"' in styles2)
            check("默认标题是黑体", 'w:eastAsia="SimHei"' in rfonts_near(styles2, "Heading2"),
                  rfonts_near(styles2, "Heading2"))
            ok2, detail2 = pandoc_roundtrip(out2)
            check("默认字体 docx 结构可读", ok2, detail2)

        # 3) 脏字体名 → 安全回落，不产坏文件
        j3 = post("/api/export-docx", {"path": doc, "markdown": MD,
                                       "latinFont": 'Bad<Font>&"x"', "cjkFont": "宋体{1}",
                                       "headingFont": "Ha<ck>",
                                       "outPath": os.path.join(tmp, "脏字体.docx")})
        check("脏字体名仍导出成功", j3.get("ok") is True, str(j3)[:300])
        check("脏字体名回落默认",
              (j3.get("fonts") or {}) == {"latin": "Times New Roman", "cjk": "SimSun",
                                          "heading": "SimHei"},
              str(j3.get("fonts")))
        out3 = j3.get("path") or ""
        if out3 and os.path.isfile(out3):
            z3 = zipfile.ZipFile(out3)
            raw3 = z3.read("word/styles.xml").decode("utf-8", "replace")
            check("脏字体名未写进 XML", "Bad<Font>" not in raw3 and "Ha<ck>" not in raw3)
            ok3, detail3 = pandoc_roundtrip(out3)
            check("脏字体名 docx 结构可读", ok3, detail3)

        # 4) 与三线表同开：两条改写互不打架
        j4 = post("/api/export-docx", {"path": doc, "markdown": MD, "threeLine": True,
                                       "latinFont": "Cambria", "cjkFont": "KaiTi",
                                       "headingFont": "Microsoft YaHei",
                                       "outPath": os.path.join(tmp, "字体加三线表.docx")})
        check("字体 + 三线表导出 ok", j4.get("ok") is True, str(j4)[:300])
        out4 = j4.get("path") or ""
        if out4 and os.path.isfile(out4):
            z4 = zipfile.ZipFile(out4)
            d4 = z4.read("word/document.xml").decode("utf-8", "replace")
            _, styles4, _ = docxml(out4)
            check("三线表仍在（表头下框线）", 'w:val="single"' in d4 and "<w:tblBorders>" in d4)
            check("字体仍在",
                  'w:ascii="Cambria"' in styles4
                  and 'w:eastAsia="KaiTi"' in styles4
                  and 'w:eastAsia="Microsoft YaHei"' in styles4)
            ok4, detail4 = pandoc_roundtrip(out4)
            check("字体 + 三线表 docx 结构可读", ok4, detail4)

        # 5) 文档目录不留 .part
        leftovers = [n for n in os.listdir(tmp) if n.endswith(".part")]
        check("无残留 .part", not leftovers, str(leftovers))
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
