# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 导出的版面（v3.7.0）回归：

- 导出时把「排版 → 页面」的纸张与页边距写进 sectPr（Word 不再用本机默认纸张）
- A4 210×297mm / 边距 25/18/25/18mm → pgSz 11906×16838、pgMar 1417/1020/1417/1020
- 自定义纸张与字符串数值（localStorage 取出的都是字符串）同样生效
- 脏值（0 / 负数 / 非数字）整盒回落到 A4 + 默认边距，不产坏文件
- 不传 page → 不写 sectPr（截图等旁路调用沿用原行为）
- 三线表可选写表头底色；不传/脏色不写
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


MD = """# 标题

正文一段。

| 列A | 列B |
|---|---|
| 1 | 2 |
| 3 | 4 |
"""


def document_xml(path):
    return zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")


def sect_pr(path):
    m = re.search(r"<w:sectPr\b.*?</w:sectPr>", document_xml(path), re.S)
    return m.group(0) if m else ""


def attr(tag, name):
    m = re.search(r'\bw:%s="([^"]+)"' % name, tag)
    return m.group(1) if m else None


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
    tmp = tempfile.mkdtemp(prefix="mdpage-")
    try:
        # 1) A4 + 默认边距
        out = os.path.join(tmp, "a4.docx")
        md_pandoc.export_docx(MD, None, out, exe, page={
            "w": 210, "h": 297, "mt": 25, "mr": 18, "mb": 25, "ml": 18})
        s = sect_pr(out)
        check("sectPr 里有 pgSz", "<w:pgSz" in s, s[:400])
        pgsz = re.search(r"<w:pgSz\b[^>]*/>", s)
        pgmar = re.search(r"<w:pgMar\b[^>]*/>", s)
        check("A4 宽 11906", pgsz and attr(pgsz.group(0), "w") == "11906",
              pgsz.group(0) if pgsz else "缺 pgSz")
        check("A4 高 16838", pgsz and attr(pgsz.group(0), "h") == "16838",
              pgsz.group(0) if pgsz else "缺 pgSz")
        want = {"top": "1417", "right": "1020", "bottom": "1417", "left": "1020"}
        got = {k: attr(pgmar.group(0), k) for k in want} if pgmar else {}
        check("边距 25/18/25/18mm 换算正确", got == want, str(got))
        ok, detail = readable(out)
        check("A4 导出后 docx 结构可读", ok, detail)

        # 2) 自定义纸张 + 字符串数值（localStorage 原样）
        out2 = os.path.join(tmp, "custom.docx")
        md_pandoc.export_docx(MD, None, out2, exe, page={
            "w": "200", "h": "260", "mt": "20", "mr": "15", "mb": "20", "ml": "15"})
        s2 = sect_pr(out2)
        pgsz2 = re.search(r"<w:pgSz\b[^>]*/>", s2)
        pgmar2 = re.search(r"<w:pgMar\b[^>]*/>", s2)
        check("自定义宽 11339", pgsz2 and attr(pgsz2.group(0), "w") == "11339",
              pgsz2.group(0) if pgsz2 else "缺 pgSz")
        check("自定义高 14740", pgsz2 and attr(pgsz2.group(0), "h") == "14740",
              pgsz2.group(0) if pgsz2 else "缺 pgSz")
        want2 = {"top": "1134", "right": "850", "bottom": "1134", "left": "850"}
        got2 = {k: attr(pgmar2.group(0), k) for k in want2} if pgmar2 else {}
        check("字符串数值也能换算", got2 == want2, str(got2))
        ok2, detail2 = readable(out2)
        check("自定义纸张 docx 结构可读", ok2, detail2)

        # 3) 脏值 → 整盒回落 A4 + 默认边距
        out3 = os.path.join(tmp, "bad.docx")
        md_pandoc.export_docx(MD, None, out3, exe, page={
            "w": 0, "h": -5, "mt": "abc", "mr": None, "mb": 99999, "ml": 18})
        s3 = sect_pr(out3)
        pgsz3 = re.search(r"<w:pgSz\b[^>]*/>", s3)
        pgmar3 = re.search(r"<w:pgMar\b[^>]*/>", s3)
        check("脏值回落 A4",
              pgsz3 and attr(pgsz3.group(0), "w") == "11906"
              and attr(pgsz3.group(0), "h") == "16838",
              pgsz3.group(0) if pgsz3 else "缺 pgSz")
        want3 = {"top": "1417", "right": "1020", "bottom": "1417", "left": "1020"}
        got3 = {k: attr(pgmar3.group(0), k) for k in want3} if pgmar3 else {}
        check("脏值回落默认边距", got3 == want3, str(got3))
        ok3, detail3 = readable(out3)
        check("脏值 docx 结构可读", ok3, detail3)

        # 4) 不传 page → 不写 pgSz（旁路调用保持原样）
        out4 = os.path.join(tmp, "nopage.docx")
        md_pandoc.export_docx(MD, None, out4, exe)
        check("不传 page 时不写 pgSz", "pgSz" not in sect_pr(out4), sect_pr(out4)[:300])

        # 5) 三线表 + 表头底色
        out5 = os.path.join(tmp, "thead.docx")
        md_pandoc.export_docx(MD, None, out5, exe)
        md_pandoc.three_line_tables(out5, exe, header_fill="#DBE5FF")
        d5 = document_xml(out5)
        rows = re.findall(r"<w:tr\b.*?</w:tr>", d5, re.S)
        check("有表头与两行表体", len(rows) == 3, "rows=%d" % len(rows))
        head = rows[0] if rows else ""
        body = rows[1] if len(rows) > 1 else ""
        check("表头每个单元格都有底色", head.count("<w:shd") == 2,
              str(re.findall(r"<w:shd\b[^>]*/>", head)))
        check("底色写入值为大写六位", 'w:fill="DBE5FF"' in head,
              str(re.findall(r"<w:shd\b[^>]*/>", head)))
        check("表体行不吃底色", "<w:shd" not in body, body[:300])
        ok5, detail5 = readable(out5)
        check("表头底色 docx 结构可读", ok5, detail5)

        # 6) 脏色 / 不传 → 不写底色
        out6 = os.path.join(tmp, "nofill.docx")
        md_pandoc.export_docx(MD, None, out6, exe)
        md_pandoc.three_line_tables(out6, exe, header_fill="red;}")
        check("脏色不写进 XML", "<w:shd" not in document_xml(out6))
        ok6, detail6 = readable(out6)
        check("脏色 docx 结构可读", ok6, detail6)

        # 7) 只写表头底色、不要三线表（预览里两个开关互相独立）
        out7 = os.path.join(tmp, "fillonly.docx")
        md_pandoc.export_docx(MD, None, out7, exe)
        md_pandoc.three_line_tables(out7, exe, header_fill="#DBE5FF", borders=False)
        d7 = document_xml(out7)
        check("只填底色时仍写表头 shd", 'w:fill="DBE5FF"' in d7)
        check("只填底色时不注入三线表边框",
              "<w:tblBorders>" not in d7 and "<w:tcBorders>" not in d7)
        ok7, detail7 = readable(out7)
        check("只填底色 docx 结构可读", ok7, detail7)

        # 7) API：排版面板的 page 与表头底色真的到后端
        sys.argv = ["md_server.py"]
        import md_server
        httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.4)
        try:
            doc = os.path.join(tmp, "版面.md")
            with open(doc, "w", encoding="utf-8") as f:
                f.write(MD)
            j = post("/api/export-docx", {
                "path": doc, "markdown": MD, "threeLine": True,
                "tableHeadOn": True, "tableHeadColor": "#dbe5ff",
                "page": {"paper": "A5", "pw": "", "ph": "",
                         "mt": 20, "mr": 15, "mb": 20, "ml": 15},
                "outPath": os.path.join(tmp, "api-a5.docx")})
            check("API 导出 ok", j.get("ok") is True, str(j)[:300])
            outp = j.get("path") or ""
            if outp and os.path.isfile(outp):
                s7 = sect_pr(outp)
                pgsz7 = re.search(r"<w:pgSz\b[^>]*/>", s7)
                check("API 落到 A5 宽 8391",
                      pgsz7 and attr(pgsz7.group(0), "w") == "8391",
                      pgsz7.group(0) if pgsz7 else "缺 pgSz")
                check("API 落到 A5 高 11906",
                      pgsz7 and attr(pgsz7.group(0), "h") == "11906",
                      pgsz7.group(0) if pgsz7 else "缺 pgSz")
                check("API 表头底色生效", 'w:fill="DBE5FF"' in document_xml(outp))
                ok7, detail7 = readable(outp)
                check("API 版面 docx 结构可读", ok7, detail7)

            # 8) API 不传 page → 仍按 A4（应用内导出总要有确定纸张）
            j2 = post("/api/export-docx", {"path": doc, "markdown": MD,
                                           "outPath": os.path.join(tmp, "api-default.docx")})
            outp2 = j2.get("path") or ""
            if outp2 and os.path.isfile(outp2):
                pgsz8 = re.search(r"<w:pgSz\b[^>]*/>", sect_pr(outp2))
                check("API 默认 A4",
                      pgsz8 and attr(pgsz8.group(0), "w") == "11906"
                      and attr(pgsz8.group(0), "h") == "16838",
                      pgsz8.group(0) if pgsz8 else "缺 pgSz")
                check("API 默认无表头底色",
                      "<w:shd" not in document_xml(outp2))

            # 9) API：只开表头底色、关三线表 → 只写底色，不加三线表边框
            j3 = post("/api/export-docx", {
                "path": doc, "markdown": MD, "threeLine": False,
                "tableHeadOn": True, "tableHeadColor": "#dbe5ff",
                "outPath": os.path.join(tmp, "api-fillonly.docx")})
            outp3 = j3.get("path") or ""
            if outp3 and os.path.isfile(outp3):
                d9 = document_xml(outp3)
                check("API 只填底色时写 shd", 'w:fill="DBE5FF"' in d9)
                check("API 关三线表时不注入边框",
                      "<w:tblBorders>" not in d9 and "<w:tcBorders>" not in d9)
        finally:
            httpd.shutdown()
            httpd.server_close()

        leftovers = [n for n in os.listdir(tmp) if n.endswith(".part")]
        check("无残留 .part", not leftovers, str(leftovers))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
