# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""拖放 URI → 本机路径的解析（md_app.pyw）。"""
import importlib.util
import os as _os
import sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

spec = importlib.util.spec_from_file_location("md_app_drop", _os.path.join(_ROOT, "md_app.pyw"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

fails = []


def check(name, got, want):
    ok = got == want
    print("%-46s %s %s" % (name, "PASS" if ok else "FAIL",
                           "" if ok else "got=%r want=%r" % (got, want)))
    if not ok:
        fails.append(name)


check("盘符 + 反斜杠", mod._drop_path_from_uri("file:///C:/a/b.md"), r"C:\a\b.md")
check("URL 编码空格", mod._drop_path_from_uri("file:///C:/a/b%20c.md"), r"C:\a\b c.md")
check("中文文件名", mod._drop_path_from_uri("file:///C:/a/%E6%B5%8B%E8%AF%95.md"),
      "C:\\a\\测试.md")
check(".smd", mod._drop_path_from_uri("file:///D:/x/y.smd"), r"D:\x\y.smd")
check("非 md/smd 拒绝", mod._drop_path_from_uri("file:///C:/a/b.txt"), "")
check("目录拒绝", mod._drop_path_from_uri("file:///C:/a/"), "")
check("http 拒绝", mod._drop_path_from_uri("https://example.com/a.md"), "")
check("UNC 共享", mod._drop_path_from_uri("file://server/share/x.smd"),
      r"\\server\share\x.smd")


class FakeBrowser:
    def __init__(self):
        self.calls = []

    def open(self, url, *a, **k):
        self.calls.append(url)
        return True


real = FakeBrowser()
proxy = mod._NoFileBrowser(real)
check("file:// 不交给系统浏览器", proxy.open("file:///C:/x.md"), False)
check("http 仍然交给系统浏览器", proxy.open("https://example.com"), True)
check("只拦 file://", real.calls, ["https://example.com"])

print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
sys.exit(1 if fails else 0)
