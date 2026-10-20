# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""R1 浏览器级验证（CDP）：真实页面里新语法的 DOM 结果。
本文件按任务逐段扩写：
- Task 2：脚注区落在预览末尾、编号上标、跨块引用
- Task 3：Callout 容器
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


DOC = """# 第一章

脚注引用[^a]，跨块引用[^b]。

# 第二章

[^a]: 甲说明
[^b]: 乙说明
"""

EXPR = r"""
(function(){
  var DOC = %s;
  var ed = document.getElementById('editor');
  ed.textContent = DOC;
  ed.dispatchEvent(new Event('input', {bubbles:true}));
  return new Promise(function(resolve){
    setTimeout(function(){
      var refs = document.querySelectorAll('#preview .fn-ref');
      var fnblk = document.querySelector('#preview .fnblk');
      var lastChild = document.querySelector('#preview').lastElementChild;
      resolve({
        refCount: refs.length,
        firstNum: refs.length ? refs[0].textContent : '',
        secondNum: refs.length > 1 ? refs[1].textContent : '',
        fnblk: !!fnblk,
        fnItems: fnblk ? fnblk.querySelectorAll('.footnotes li').length : 0,
        fnText: fnblk ? fnblk.textContent : '',
        isLast: !!(fnblk && lastChild === fnblk),
        bodyHasDef: (document.querySelector('#preview').textContent || '').indexOf('[^a]:') >= 0
      });
    }, 1600);
  });
})()
""" % json.dumps(DOC, ensure_ascii=False)

if __name__ == "__main__":
    res = run_expr(EXPR)
    check("两条引用都渲染为上标", res.get("refCount") == 2, str(res))
    check("引用编号按引用序 1/2",
          res.get("firstNum") == "1" and res.get("secondNum") == "2", str(res))
    check("脚注区存在", res.get("fnblk") is True, str(res))
    check("脚注区两条条目", res.get("fnItems") == 2, str(res))
    check("脚注正文含说明", "甲说明" in (res.get("fnText") or "")
          and "乙说明" in (res.get("fnText") or ""), str(res.get("fnText")))
    check("脚注区在预览末尾", res.get("isLast") is True, str(res))
    check("定义行不进正文", res.get("bodyHasDef") is False, str(res))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)
