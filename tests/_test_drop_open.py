# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""拖放打开（页面侧）回归：

- 页面暴露 window.mdwDropOpen
- 调用后真的按完整路径载入目标文档（编辑器内容 / 文件名 / 标题都变）
原生 Windows 拖放（md_app.pyw 的 WinForms hook）不在浏览器级测试范围内。
"""
# --- 测试入口 shim：同 _test_browser 口径 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import json
import os
import shutil
import sys
import tempfile
import urllib.parse

HERE = _ROOT
from _test_browser import PORT, run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def main():
    tmp = tempfile.mkdtemp(prefix="mddrop-")
    try:
        a = os.path.join(tmp, "A文档.md")
        b = os.path.join(tmp, "B拖入.md")
        with open(a, "w", encoding="utf-8") as f:
            f.write("# 文档 A\n\n这是 A 的内容。\n")
        with open(b, "w", encoding="utf-8") as f:
            f.write("# 文档 B\n\n这是从拖放载入的 B 内容。\n")
        url = "http://127.0.0.1:%d/?file=%s" % (PORT, urllib.parse.quote(a))
        expr = r"""
(function(){
  return new Promise(function(resolve){
    setTimeout(function(){
      var has=typeof window.mdwDropOpen==='function';
      var before=document.getElementById('statFile').textContent;
      window.mdwDropOpen(%s);
      setTimeout(function(){
        var ed=document.getElementById('editor');
        resolve({has:has, before:before,
                 stat:document.getElementById('statFile').textContent,
                 title:document.title,
                 text:ed?ed.textContent:''});
      },1600);
    },2200);
  });
})()
""" % json.dumps(b.replace("\\", "/"))
        res = run_expr(expr, url=url) or {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    check("window.mdwDropOpen 已暴露", res.get("has") is True, str(res.get("has")))
    check("载入后编辑器是 B 的内容", "从拖放载入的 B" in (res.get("text") or ""),
          (res.get("text") or "")[:80])
    check("文件名切到 B拖入.md", res.get("stat") == "B拖入.md", str(res.get("stat")))
    check("标题切到 B", "B拖入.md" in (res.get("title") or ""), str(res.get("title")))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
