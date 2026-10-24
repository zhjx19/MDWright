# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""编辑区右键菜单的二级下拉：展开状态必须互斥。

症状（v3.1.0 报回）：右键菜单里悬停「标题」展开二级，再把鼠标移到「强调」，
「标题」的二级不收起，两个 pop 同时 display:block，叠在一起（后开的盖在前一个上）。
把鼠标移到普通一级项（如「复制」）时，已展开的二级同样一直挂着。

根因：openSub() 只在 mouseenter 时打开，全文件没有任何「关闭兄弟」或「离开即收」的路径。

覆盖：
- 悬停一个二级行 → 只展开 1 个 pop
- 再悬停另一二级行 → 仍是 1 个 pop，前一个收起
- 悬停普通一级项 → 0 个 pop
- 鼠标移出整个菜单 → 0 个 pop
- 悬停二级 pop 内部条目 → 保持展开（不能把要点的菜单收掉）
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

import sys

sys.path.insert(0, _ROOT)
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


PROBE_CTX_SUB = r"""
(function(){
  var menu = document.getElementById('ctxMenu');
  var ed = document.getElementById('editor');
  function rows(){ return [].slice.call(menu.children).filter(function(el){
    return el.classList.contains('ctx-sub'); }); }
  function plains(){ return [].slice.call(menu.children).filter(function(el){
    return el.classList.contains('menu-item') && !el.classList.contains('ctx-sub'); }); }
  /* 用户看得见的口径：有几个二级 pop 真的 display 着 */
  function vis(){
    return [].slice.call(menu.querySelectorAll('.sub-pop')).filter(function(p){
      return getComputedStyle(p).display !== 'none'; }).length;
  }
  /* 真实指针移动会同时产生 mouseover（冒泡）与 mouseenter（不冒泡），两条都发 */
  function hover(el){
    if(!el) return;
    el.dispatchEvent(new MouseEvent('mouseover', {bubbles:true, cancelable:true}));
    el.dispatchEvent(new MouseEvent('mouseenter', {bubbles:false, cancelable:true}));
  }
  var out = {};
  ed.focus();
  ed.dispatchEvent(new MouseEvent('contextmenu',
      {bubbles:true, cancelable:true, clientX:200, clientY:200}));
  out.menuOpen = menu.getAttribute('data-open') === '1';
  var subs = rows();
  /* 只取行自身的文本节点：textContent 会把 pop 里的条目文字也算进来 */
  out.labels = subs.map(function(w){
    var t = '';
    for(var i = 0; i < w.childNodes.length; i++){
      if(w.childNodes[i].nodeType === 3) t += w.childNodes[i].nodeValue;
    }
    return t.trim(); });
  out.plainCount = plains().length;

  hover(subs[0]);
  out.visAfterFirst = vis();
  out.firstOpen = subs[0].getAttribute('data-open') === '1';

  hover(subs[1]);
  out.visAfterSecond = vis();
  out.firstAfterSecond = subs[0].getAttribute('data-open') === '1';
  out.secondOpen = subs[1].getAttribute('data-open') === '1';

  hover(plains()[1]);
  out.visAfterPlain = vis();

  hover(subs[0]);
  out.visBeforeLeave = vis();
  menu.dispatchEvent(new MouseEvent('mouseleave', {bubbles:false, cancelable:true}));
  out.visAfterLeave = vis();

  /* 二级 pop 内部条目：悬停它不能把自家 pop 收掉，否则点不到 */
  hover(subs[0]);
  var inner = subs[0].querySelector('.sub-pop .menu-item');
  hover(inner);
  out.visOnInner = vis();
  out.innerOpen = subs[0].getAttribute('data-open') === '1';

  /* 点二级条目仍然生效：走同一条委托，写入 **abc** */
  ed.textContent = 'abc';
  var rng = document.createRange(); rng.selectNodeContents(ed);
  var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(rng);
  hover(subs[1]);
  var bold = [].slice.call(subs[1].querySelectorAll('.menu-item')).filter(function(b){
    return b.getAttribute('data-ctx') === 'fmt:B'; })[0];
  if(bold) bold.click();
  out.afterBold = ed.textContent;
  out.menuClosedAfterClick = menu.getAttribute('data-open') === '1';
  return out;
})()
"""


def main():
    r = run_expr(PROBE_CTX_SUB)
    check("右键弹出菜单", r.get("menuOpen") is True, str(r.get("menuOpen")))
    check("四个二级行都在（标题/强调/块/插入）",
          r.get("labels") == ["标题", "强调", "块", "插入"], str(r.get("labels")))
    check("悬停一级的二级行只展开 1 个 pop", r.get("visAfterFirst") == 1,
          "vis=%r" % (r.get("visAfterFirst"),))
    check("移到另一二级行：仍是 1 个 pop（不叠）", r.get("visAfterSecond") == 1,
          "vis=%r" % (r.get("visAfterSecond"),))
    check("前一行的二级已收起", r.get("firstAfterSecond") is False,
          "firstOpen=%r" % (r.get("firstAfterSecond"),))
    check("新的那一行已展开", r.get("secondOpen") is True,
          "secondOpen=%r" % (r.get("secondOpen"),))
    check("移到普通一级项：二级收起", r.get("visAfterPlain") == 0,
          "vis=%r" % (r.get("visAfterPlain"),))
    check("移出整个菜单：二级收起", r.get("visAfterLeave") == 0,
          "before=%r after=%r" % (r.get("visBeforeLeave"), r.get("visAfterLeave")))
    check("悬停二级 pop 内部：保持展开", r.get("visOnInner") == 1 and r.get("innerOpen") is True,
          "vis=%r open=%r" % (r.get("visOnInner"), r.get("innerOpen")))
    check("点二级条目仍写入格式标记", r.get("afterBold") == "**abc**",
          str(r.get("afterBold")))
    check("点完菜单关闭", r.get("menuClosedAfterClick") is False,
          str(r.get("menuClosedAfterClick")))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
