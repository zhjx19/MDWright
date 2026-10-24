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
# --- 测试入口 shim：本文件在 tests/ 下。便携运行时（python311._pth）不会把 script dir
# 加进 sys.path，所以 tests/ 与仓库根两个都显式挂上，跨用例 import 与根模块 import 才成立 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import json
import os
import sys

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
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
      var codes = pv.querySelectorAll('pre code');
      var plain = null;
      for (var i = 0; i < codes.length; i++) {
        if (!codes[i].getAttribute('data-lang') && !codes[i].classList.contains('hljs')) plain = false;
      }
      resolve({
        text: pv.textContent || '',
        html: pv.innerHTML || '',
        refCount: refs.length,
        firstNum: refs.length ? refs[0].textContent : '',
        secondNum: refs.length > 1 ? refs[1].textContent : '',
        fnblk: !!fnblk,
        fnItems: fnblk ? fnblk.querySelectorAll('.footnotes li').length : 0,
        fnText: fnblk ? fnblk.textContent : '',
        isLast: !!(fnblk && pv.lastElementChild === fnblk),
        noteCallout: !!pv.querySelector('.callout.callout-note'),
        noteTitle: (pv.querySelector('.callout-note .callout-title') || {}).textContent || '',
        warnTitle: (pv.querySelector('.callout-warning .callout-title') || {}).textContent || '',
        calloutCount: pv.querySelectorAll('.callout').length,
        quoteCount: pv.querySelectorAll('blockquote').length,
        hlKeywords: pv.querySelectorAll('pre code .hljs-keyword').length,
        hlClass: (function(){ var c = pv.querySelector('pre code'); return c ? c.className : ''; })(),
        hlLang: (function(){ var c = pv.querySelector('pre code'); return c ? c.getAttribute('data-lang') : ''; })(),
        preCodeCount: codes.length,
        plainHl: plain
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


def test_callout():
    res = probe("""> [!NOTE]
> 提示内容

> [!WARNING] 自定义警示
> 第二类

> 普通引用不受影响
""")
    check("Callout：NOTE 容器", res.get("noteCallout") is True, str(res.get("html"))[:200])
    check("Callout：默认标题为类型名", res.get("noteTitle") == "NOTE", res.get("noteTitle"))
    check("Callout：自定义标题", res.get("warnTitle") == "自定义警示", res.get("warnTitle"))
    check("Callout：普通引用仍是 blockquote",
          res.get("quoteCount") == 1 and res.get("calloutCount") == 2,
          "quote=%r callout=%r" % (res.get("quoteCount"), res.get("calloutCount")))


def test_highlight():
    res = probe("""```python
def f(x):
    return x**2
```

```mermaid
graph TD
A-->B
```

```
plain text no lang
```
""")
    check("高亮：生成 hljs-keyword", (res.get("hlKeywords") or 0) >= 1, str(res.get("hlKeywords")))
    check("高亮：code 元素带 hljs 类", "hljs" in (res.get("hlClass") or ""), res.get("hlClass"))
    check("高亮：data-lang 为围栏语言", res.get("hlLang") == "python", res.get("hlLang"))
    check("高亮：图表围栏不产生 pre code",
          res.get("preCodeCount") == 2, "preCode=%r" % (res.get("preCodeCount"),))
    check("高亮：无语言围栏不着色（不自动探测）",
          res.get("plainHl") is False, "plainHl=%r" % (res.get("plainHl"),))


def test_footnote_incremental():
    """C2 回归：先渲染带脚注的文档，再在末尾追加新章节——脚注区必须仍在末尾。
    旧实现只在创建时 append，后续块 appendChild 到 preview 尾部会把脚注区挤到中间。"""
    res = run_expr(r"""
    (function(){
      var ed=document.getElementById('editor');
      ed.textContent='# 第一章\n\n正文[^a]\n\n[^a]: 说明\n';
      ed.dispatchEvent(new Event('input',{bubbles:true}));
      return new Promise(function(resolve){
        setTimeout(function(){
          var pv=document.querySelector('#preview');
          var firstLast = pv.lastElementChild && pv.lastElementChild.className;
          ed.textContent = ed.textContent + '\n## 第二章\n\n后来的内容\n';
          ed.dispatchEvent(new Event('input',{bubbles:true}));
          setTimeout(function(){
            var kids=[].map.call(pv.children, function(e){return e.className;});
            resolve({firstLast:firstLast, kids:kids,
                     lastIsFn: !!(pv.lastElementChild&&pv.lastElementChild.classList.contains('fnblk')),
                     fnCount: pv.querySelectorAll('.fnblk').length});
          },1400);
        },1400);
      });
    })()
    """)
    check("脚注增量：首渲脚注区在末尾", "fnblk" in (res.get("firstLast") or ""), str(res.get("kids")))
    check("脚注增量：追加章节后脚注区仍在末尾",
          res.get("lastIsFn") is True, str(res.get("kids")))
    check("脚注增量：脚注区只有一个", res.get("fnCount") == 1, str(res.get("fnCount")))


if __name__ == "__main__":
    test_footnote()
    test_frontmatter()
    test_callout()
    test_highlight()
    test_footnote_incremental()
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)
