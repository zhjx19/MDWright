# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 标题自动编号回归：

- 开启后 numbering.xml 新增一个多级 abstractNum：6 级 decimal，lvlText
  `%1` / `%1.%2` / … / `%1.%2.%3.%4.%5.%6`，分别绑定 Heading1..6
- 新增的 numId 不与 pandoc 自带的编号（1000）撞车
- Heading1..6 的样式里带 numPr（对应 ilvl 0..5）
- 关闭 / 不传 → 不新增 abstractNum，标题样式不带 numPr
- 与中文版式同开：标题字号/加粗不被覆盖，docx 可回读
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

正文。

## 二级标题

### 三级标题

#### 四级标题
"""


def parts(path):
    z = zipfile.ZipFile(path)
    return (z.read("word/numbering.xml").decode("utf-8", "replace"),
            z.read("word/styles.xml").decode("utf-8", "replace"))


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
    tmp = tempfile.mkdtemp(prefix="mdhnum-")
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        doc = os.path.join(tmp, "标题编号.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write(MD)

        j = post("/api/export-docx", {"path": doc, "markdown": MD,
                                      "docxNumbering": True,
                                      "outPath": os.path.join(tmp, "num.docx")})
        check("标题编号导出 ok", j.get("ok") is True, str(j)[:300])
        out = j.get("path") or ""
        if not (out and os.path.isfile(out)):
            check("产出 docx", False, "缺文件")
        else:
            num, styles = parts(out)
            abs_ids = [int(x) for x in
                       re.findall(r'<w:abstractNum [^>]*w:abstractNumId="(\d+)"', num)]
            check("新增一个 abstractNum", len(abs_ids) == 2, str(abs_ids))
            aid = max(abs_ids) if abs_ids else -1
            ab = re.search(r'<w:abstractNum [^>]*w:abstractNumId="%d".*?</w:abstractNum>'
                           % aid, num, re.S)
            ab = ab.group(0) if ab else ""
            check("是 multilevel", 'w:multiLevelType w:val="multilevel"' in ab, ab[:300])
            texts = re.findall(r'<w:lvlText w:val="([^"]*)"/>', ab)
            want = ["%1", "%1.%2", "%1.%2.%3", "%1.%2.%3.%4",
                    "%1.%2.%3.%4.%5", "%1.%2.%3.%4.%5.%6"]
            check("六级编号格式正确", texts == want, str(texts))
            pstyles = re.findall(r'<w:pStyle w:val="([^"]*)"/>', ab)
            check("绑定 Heading1..6",
                  pstyles == ["Heading%d" % i for i in range(1, 7)], str(pstyles))

            nums = re.findall(r'<w:num w:numId="(\d+)"[^>]*>\s*'
                              r'<w:abstractNumId w:val="(\d+)"/>', num)
            nid = [int(a) for a, b in nums if b == str(aid)]
            check("新增 num 指向新 abstractNum", bool(nid), str(nums))
            nid = nid[0] if nid else -1
            check("numId 不与自带 1000 撞车", nid != 1000, "nid=%s" % nid)

            for lvl in range(1, 7):
                b = block(styles, "Heading%d" % lvl)
                want_pr = ('<w:numPr><w:ilvl w:val="%d"/><w:numId w:val="%d"/></w:numPr>'
                           % (lvl - 1, nid))
                check("H%d 带 numPr" % lvl, want_pr in b, b[:500])
            ok, detail = readable(out)
            check("编号 docx 结构可读", ok, detail)

        # 2) 关闭 / 不传 → 不新增、标题无 numPr
        j2 = post("/api/export-docx", {"path": doc, "markdown": MD,
                                       "docxNumbering": False,
                                       "outPath": os.path.join(tmp, "plain.docx")})
        out2 = j2.get("path") or ""
        if out2 and os.path.isfile(out2):
            num2, styles2 = parts(out2)
            check("关闭后只有一个 abstractNum",
                  len(re.findall(r"<w:abstractNum ", num2)) == 1,
                  str(re.findall(r'w:abstractNumId="(\d+)"', num2)))
            check("关闭后标题无 numPr", "<w:numPr>" not in block(styles2, "Heading1"))
        j3 = post("/api/export-docx", {"path": doc, "markdown": MD,
                                       "outPath": os.path.join(tmp, "default.docx")})
        out3 = j3.get("path") or ""
        if out3 and os.path.isfile(out3):
            num3, styles3 = parts(out3)
            check("不传默认关闭",
                  len(re.findall(r"<w:abstractNum ", num3)) == 1
                  and "<w:numPr>" not in block(styles3, "Heading1"))

        # 3) 与中文版式同开：标题字号仍在
        j4 = post("/api/export-docx", {"path": doc, "markdown": MD,
                                       "docxNumbering": True, "docxCn": True,
                                       "outPath": os.path.join(tmp, "both.docx")})
        out4 = j4.get("path") or ""
        if out4 and os.path.isfile(out4):
            _, s4 = parts(out4)
            h1 = block(s4, "Heading1")
            check("与中文版式同开：加粗与字号仍在",
                  'w:sz w:val="36"' in h1 and ("<w:b/>" in h1 or "<w:b />" in h1),
                  h1[:500])
            check("与中文版式同开：numPr 仍在", "<w:numPr>" in h1)
            ok4, detail4 = readable(out4)
            check("同开 docx 结构可读", ok4, detail4)
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
