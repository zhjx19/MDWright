# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 导出的端到端回归（R2，需本机 pandoc）：
- 产出 .docx（合法 ZIP）
- 公式落为 OMML（<m:oMath>），不是 LaTeX 文本
- 脚注进 word/footnotes.xml
- 图片按相对路径嵌入 word/media/
- front matter 进 docProps/core.xml
- 未保存文档明确报错，不产文件
- 文件名含中文/空格/# 也能正常导出
"""
import json
import os
import shutil
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PORT = 18777
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
        # 路由用 400/500 + JSON 体报错，解析出来便于断言
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "HTTP %d" % e.code}


MD = """---
title: 导出测试
---

# 一级标题

行内公式 $E=mc^2$，块级：

$$
\\int_0^1 x^2\\,dx = \\frac{1}{3}
$$

脚注引用[^a]。

> [!NOTE]
> 提示内容

![图](assets/pic.png)

[^a]: 脚注说明
"""

# 1x1 PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082")


def main():
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    tmp = tempfile.mkdtemp(prefix="mddocx-")
    try:
        doc = os.path.join(tmp, "文档 名#1.md")
        os.makedirs(os.path.join(tmp, "assets"), exist_ok=True)
        with open(doc, "w", encoding="utf-8") as f:
            f.write(MD)
        with open(os.path.join(tmp, "assets", "pic.png"), "wb") as f:
            f.write(PNG)

        j = post("/api/export-docx", {"path": doc, "markdown": MD})
        check("接口 ok", j.get("ok") is True, str(j)[:300])
        out = j.get("path") or ""
        check("落盘在同目录且为 .docx",
              out.lower().endswith(".docx") and os.path.dirname(out) == tmp, out)
        if out and os.path.isfile(out):
            z = zipfile.ZipFile(out)
            names = z.namelist()
            x = z.read("word/document.xml").decode("utf-8", "replace")
            check("是合法 docx（含 word/document.xml）", "word/document.xml" in names)
            check("公式为 OMML", "<m:oMath" in x, x[:200])
            check("分数结构存在", ("<m:f>" in x) or ("<m:num>" in x))
            check("无 LaTeX 源码残留", "\\\\frac" not in x and "$$" not in x)
            check("脚注进 footnotes.xml",
                  "word/footnotes.xml" in names
                  and "脚注说明" in z.read("word/footnotes.xml").decode("utf-8", "replace"))
            check("图片嵌入 word/media",
                  any(n.startswith("word/media/") for n in names),
                  str([n for n in names if n.startswith("word/media")]))
            check("front matter 进核心属性",
                  "导出测试" in z.read("docProps/core.xml").decode("utf-8", "replace"))
            check("Callout 落为引用块（无 [!NOTE] 字面）", "[!NOTE]" not in x)

        # 未保存文档 → 明确报错且不产文件
        j2 = post("/api/export-docx", {"path": "", "markdown": "# x\n"})
        check("未保存文档明确报错",
              j2.get("ok") is False and "保存" in (j2.get("error") or ""), str(j2))
        check("未保存时不产文件", not os.path.exists(os.path.join(tmp, ".docx")))
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
