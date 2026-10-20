# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""R1 浏览器级验证（CDP）：真实页面里新语法的 DOM 结果。
本文件按任务逐段扩写：
- Task 2：脚注区落在预览末尾、编号上标、跨块引用
- Task 3：Callout 容器
- Task 6：front matter 不进正文
- Task 9：代码高亮 span
依赖 Task 1 的 _test_browser.py 通道（本机无 playwright）。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


PROBE = r"""
(function(){
  var DOC = %s;
  var ed = document.getElementById('editor');
  ed.textContent = DOC;
  ed.dispatchEvent(new Event('input', {bubbles:true}));
  return new Promise(function(resolve){
    setTimeout(function(){
      var pv = document.querySelector('#preview');
      var refs = pv.querySelectorAll('.fn-ref');
      var fnblk = pv.querySelector('.fnblk');
      resolve({
        text: pv.textContent || '',
        html: pv.innerHTML || '',
        refCount: refs.length,
        firstNum: refs.length ? refs[0].textContent : '',
        secondNum: refs.length > 1 ? refs[1].textContent : '',
        fnblk: !!fnblk,
        fnItems: fnblk ? fnblk.querySelectorAll('.footnotes li').length : 0,
        fnText: fnblk ? fnblk.textContent : '',
        isLast: !!(fnblk && pv.lastElementChild === fnblk)
      });
    }, 1600);
  });
})()
"""


def probe(doc):
    return run_expr(PROBE % json.dumps(doc, ensure_ascii=False))


def test_footnote():
    res = probe("""# 第一章

脚注引用[^a]，跨块引用[^b]。

# 第二章

[^a]: 甲说明
[^b]: 乙说明
""")
    check("脚注：两条引用都渲染为上标", res.get("refCount") == 2, str(res.get("refCount")))
    check("脚注：编号按引用序 1/2",
          res.get("firstNum") == "1" and res.get("secondNum") == "2",
          "%r/%r" % (res.get("firstNum"), res.get("secondNum")))
    check("脚注：区存在", res.get("fnblk") is True)
    check("脚注：两条条目", res.get("fnItems") == 2, str(res.get("fnItems")))
    check("脚注：正文含说明",
          "甲说明" in (res.get("fnText") or "") and "乙说明" in (res.get("fnText") or ""),
          res.get("fnText"))
    check("脚注：区在预览末尾", res.get("isLast") is True)
    check("脚注：定义行不进正文", "[^a]:" not in (res.get("text") or ""), res.get("text"))


def test_frontmatter():
    res = probe("""---
title: 我的文档
author: zhang
tags:
  - a
  - b
---

# 正文标题

正文内容
""")
    txt = res.get("text") or ""
    check("front matter：YAML 不进预览", ("title:" not in txt) and ("author:" not in txt), txt[:120])
    check("front matter：分隔线不进预览", txt.count("---") == 0, txt[:120])
    check("front matter：正文照常渲染", "正文内容" in txt and "正文标题" in txt, txt[:120])


if __name__ == "__main__":
    test_footnote()
    test_frontmatter()
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)
