# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 页码回归：

- 底部居中：生成 footer 部件，含 PAGE / NUMPAGES 字段，字号与灰度取面板
- 外侧（奇右偶左）：footer default + even 两个部件，settings 开 evenAndOddHeaders
- 顶部居中：生成 header 部件并从 sectPr 引用
- 关闭 / 不传：不生成部件、不写引用
- 内容类型、关系、docx 回读都必须成立
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


MD = "# 标题\n\n正文。\n"


def read(path, name):
    z = zipfile.ZipFile(path)
    return z.read(name).decode("utf-8", "replace") if name in z.namelist() else ""


def names(path):
    return zipfile.ZipFile(path).namelist()


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
    tmp = tempfile.mkdtemp(prefix="mdpn-")
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        doc = os.path.join(tmp, "页码.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write(MD)

        # 1) 底部居中 + 第 {p} 页 / 共 {P} 页
        j = post("/api/export-docx", {
            "path": doc, "markdown": MD,
            "page": {"paper": "A4", "mt": 25, "mr": 18, "mb": 25, "ml": 18,
                     "pn": {"on": "on", "pos": "bc",
                            "tpl": "第 {p} 页 / 共 {P} 页", "size": 9}},
            "outPath": os.path.join(tmp, "bc.docx")})
        check("底部居中导出 ok", j.get("ok") is True, str(j)[:300])
        out = j.get("path") or ""
        if out and os.path.isfile(out):
            ns = names(out)
            foot = [n for n in ns if re.match(r"word/footer\d+\.xml$", n)]
            check("生成 footer 部件", len(foot) == 1, str(foot))
            f = read(out, foot[0]) if foot else ""
            check("含 PAGE 字段", " PAGE " in f, f[:400])
            check("含 NUMPAGES 字段", " NUMPAGES " in f, f[:400])
            check("页码居中", 'w:jc w:val="center"' in f, f[:400])
            check("字号 9pt=18 半磅", 'w:sz w:val="18"' in f, f[:400])
            check("灰度 595959", 'w:color w:val="595959"' in f, f[:400])
            check("模板文字进部件", "第 " in f and " 页 / 共 " in f, f[:400])

            sect = read(out, "word/document.xml")
            check("sectPr 引用 footer", "<w:footerReference" in sect
                  and 'w:type="default"' in sect, sect[-600:])
            check("没有 header 引用", "<w:headerReference" not in sect)
            rels = read(out, "word/_rels/document.xml.rels")
            check("关系表登记 footer", "relationships/footer" in rels, rels[:500])
            ct = read(out, "[Content_Types].xml")
            check("内容类型登记 footer",
                  "wordprocessingml.footer+xml" in ct, ct[:600])
            st = read(out, "word/settings.xml")
            check("要求 Word 更新域", "<w:updateFields" in st, st[:400])
            ok, detail = readable(out)
            check("页码 docx 结构可读", ok, detail)

        # 2) 外侧：奇右偶左，两份 footer
        j2 = post("/api/export-docx", {
            "path": doc, "markdown": MD,
            "page": {"paper": "A4", "pn": {"on": "on", "pos": "outer",
                                           "tpl": "{p}", "size": 9}},
            "outPath": os.path.join(tmp, "outer.docx")})
        out2 = j2.get("path") or ""
        if out2 and os.path.isfile(out2):
            ns2 = names(out2)
            foot2 = sorted(n for n in ns2 if re.match(r"word/footer\d+\.xml$", n))
            check("外侧生成两份 footer", len(foot2) == 2, str(foot2))
            sect2 = read(out2, "word/document.xml")
            check("sectPr 有 default + even",
                  'w:type="default"' in sect2 and 'w:type="even"' in sect2, sect2[-700:])
            st2 = read(out2, "word/settings.xml")
            check("settings 开奇偶页不同", "<w:evenAndOddHeaders" in st2, st2[:400])
            js = [re.search(r'w:jc w:val="([a-z]+)"', read(out2, n) or "")
                  for n in foot2]
            got = [m.group(1) if m else "" for m in js]
            check("奇数页右、偶数页左", set(got) == {"right", "left"}, str(got))

        # 3) 顶部居中：header 部件
        j3 = post("/api/export-docx", {
            "path": doc, "markdown": MD,
            "page": {"paper": "A4", "pn": {"on": "on", "pos": "tc",
                                           "tpl": "{p}", "size": 10}},
            "outPath": os.path.join(tmp, "tc.docx")})
        out3 = j3.get("path") or ""
        if out3 and os.path.isfile(out3):
            ns3 = names(out3)
            head = [n for n in ns3 if re.match(r"word/header\d+\.xml$", n)]
            check("生成 header 部件", len(head) == 1, str(head))
            h = read(out3, head[0]) if head else ""
            check("顶部页码居中", 'w:jc w:val="center"' in h, h[:400])
            check("字号 10pt=20 半磅", 'w:sz w:val="20"' in h, h[:400])
            sect3 = read(out3, "word/document.xml")
            check("sectPr 引用 header", "<w:headerReference" in sect3, sect3[-600:])

        # 4) 关闭 / 不传：不生成部件
        for tag, page in (("off", {"paper": "A4", "pn": {"on": "off"}}),
                          ("none", {"paper": "A4"})):
            j4 = post("/api/export-docx", {"path": doc, "markdown": MD,
                                           "page": page,
                                           "outPath": os.path.join(tmp, tag + ".docx")})
            out4 = j4.get("path") or ""
            if out4 and os.path.isfile(out4):
                ns4 = names(out4)
                check("%s 不生成页眉页脚" % tag,
                      not [n for n in ns4 if re.match(r"word/(footer|header)\d+\.xml$", n)],
                      str([n for n in ns4 if "footer" in n or "header" in n]))
                sect4 = read(out4, "word/document.xml")
                check("%s 不写引用" % tag,
                      "<w:footerReference" not in sect4
                      and "<w:headerReference" not in sect4)

        # 5) 模板只写 {p} → 不含 NUMPAGES
        j5 = post("/api/export-docx", {
            "path": doc, "markdown": MD,
            "page": {"paper": "A4", "pn": {"on": "on", "pos": "br",
                                           "tpl": "{p}", "size": 9}},
            "outPath": os.path.join(tmp, "br.docx")})
        out5 = j5.get("path") or ""
        if out5 and os.path.isfile(out5):
            f5 = read(out5, "word/footer1.xml")
            check("只写 {p} 时不带 NUMPAGES",
                  " PAGE " in f5 and "NUMPAGES" not in f5, f5[:400])
            check("底部右侧对齐", 'w:jc w:val="right"' in f5, f5[:400])
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
