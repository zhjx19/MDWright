# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""图片排版三件套（v3.2.0）的**预览**实际效果——真实浏览器里量 computed style。

解析产物对不对由 `_test_img_layout.py` 管；这里只回答用户能看见的那三件事：
1. 开了正文首行缩进，独占一行的图**不跟着缩**；
2. 没写对齐标记的图跟随排版面板「图片」档（默认居中），写了 `{l}` 的压过面板；
3. `@@ begin fill` 真的排成多列，`{N}` 宽度仍然生效。

导出三链路（独立 HTML / 分页 / docx）不在本文件，按计划另测。
"""
# --- 测试入口 shim ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import os
import sys

sys.path.insert(0, _ROOT)
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-44s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


PROBE = r"""
(function(){
  var out = {};
  /* ── ① 在排版面板里打开"正文首行缩进 2 字符" ── */
  document.getElementById('btnSettings').click();
  [].slice.call(document.querySelectorAll('#setTabs .set-tab')).filter(function(b){
    return b.getAttribute('data-tab') === 'typeset'; })[0].click();
  var indSel = document.querySelector('select[data-ind="p"]');
  var indChr = document.querySelector('input[data-indchars="p"]');
  indSel.value = 'first';
  indChr.value = '2';
  document.getElementById('tsApply').click();
  document.getElementById('tsClose').click();
  out.indentSet = indSel.value + '/' + indChr.value;
  var IMG1 = "@@IMG1@@", IMG2 = "@@IMG2@@";

  /* ── ② 写入被测文档 ── */
  var ed = document.getElementById('editor');
  ed.textContent = [
    '正文段落,测首行缩进。',
    '',
    '![a](nofile-a.png)',
    '',
    '![b](nofile-b.png){l}',
    '',
    '![c](nofile-c.png){30 r}',
    '',
    '@@ begin fill {50|50}',
    '![d](' + IMG1 + ')',
    '![e](' + IMG2 + ')',
    '@@ end fill',
    ''
  ].join('\n');
  ed.dispatchEvent(new Event('input', {bubbles:true}));

  return new Promise(function(resolve){
    setTimeout(function(){
      var prev = document.getElementById('preview');
      function imgs(){ return [].slice.call(prev.querySelectorAll('img')); }
      function byName(n){
        return imgs().filter(function(i){ return (i.getAttribute('src')||'').indexOf(n) >= 0; })[0];
      }
      function paraOf(img){ return img ? img.closest('p') : null; }
      function cs(el, prop){ return el ? getComputedStyle(el)[prop] : ''; }

      var pa = byName('nofile-a.png'), pb = byName('nofile-b.png'), pc = byName('nofile-c.png');
      var pA = paraOf(pa), pB = paraOf(pb), pC = paraOf(pc);
      var firstP = prev.querySelector('p');

      out.nImg = imgs().length;
      out.firstPIndent = cs(firstP, 'textIndent');
      out.imgParaIndent = cs(pA, 'textIndent');
      out.imgParaClass = pA ? pA.className : '';
      out.alignDefault = cs(pA, 'textAlign');
      out.alignExplicitL = cs(pB, 'textAlign');
      out.alignExplicitR = cs(pC, 'textAlign');
      out.widthC = pc ? (pc.style.width || cs(pc, 'width')) : '';

      var fill = prev.querySelector('.img-fill');
      out.fillExists = !!fill;
      if(fill){
        out.fillDisplay = cs(fill, 'display');
        out.fillCols = (cs(fill, 'gridTemplateColumns') || '').trim().split(/\s+/).length;
        var fd = byName('writing.png');
        out.fillImgLoaded = fd ? fd.naturalWidth : 0;
        out.fillImgBox = fd ? Math.round(fd.getBoundingClientRect().width) : 0;
        out.fillBox = Math.round(fill.getBoundingClientRect().width);
      }
      resolve(out);
    }, 900);
  });
})()
"""


def main():
    # 用仓库里的真实图片：破图在 Chromium 下不吃 width:100%，会让"栏内占满"测不出来
    img1 = os.path.join(_ROOT, "docs", "screenshots", "writing.png").replace("\\", "/")
    img2 = os.path.join(_ROOT, "docs", "screenshots", "diagrams.png").replace("\\", "/")
    r = run_expr(PROBE.replace("@@IMG1@@", img1).replace("@@IMG2@@", img2))
    check("五个图都在预览里", r.get("nImg") == 5, str(r.get("nImg")))
    check("正文段落有首行缩进", r.get("firstPIndent") not in ("", "0px"), str(r.get("firstPIndent")))
    check("图片段不吃首行缩进", r.get("imgParaIndent") == "0px", str(r.get("imgParaIndent")))
    check("图片段带 p-img 类", "p-img" in (r.get("imgParaClass") or ""), str(r.get("imgParaClass")))
    check("未标记的图默认居中", r.get("alignDefault") == "center", str(r.get("alignDefault")))
    check("{l} 压过面板默认", r.get("alignExplicitL") == "left", str(r.get("alignExplicitL")))
    check("{30 r} 右对齐", r.get("alignExplicitR") == "right", str(r.get("alignExplicitR")))
    check("{N} 宽度仍写进样式", (r.get("widthC") or "").startswith("30"),
          str(r.get("widthC")))
    check("多图并排是两列网格", r.get("fillExists") is True
          and r.get("fillDisplay") == "grid" and r.get("fillCols") == 2,
          "display=%r cols=%r" % (r.get("fillDisplay"), r.get("fillCols")))
    check("栏内图占满栏宽",
          (r.get("fillImgLoaded") or 0) > 0
          and (r.get("fillImgBox") or 0) > 10
          and abs((r.get("fillImgBox") or 0) - (r.get("fillBox") or 0) / 2) < 12,
          "img=%r fill=%r natural=%r" % (r.get("fillImgBox"), r.get("fillBox"),
                                         r.get("fillImgLoaded")))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
