# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""AI 侧栏的浏览器级回归（headless Chrome + CDP，不依赖 playwright）：

- 骨架：第三栏默认隐藏，菜单项 / 快捷键 / 选区气泡三个入口都能打开
- 上下文：打开时冻结选区原文，引用块显示正确
- 交互：拖宽写进 localStorage；发送、渲染、错误重试；插入 / 替换
- 生命周期：切换文档清空会话

本文件按任务增量追加探测器；每个 PROBE_* 都是一次完整的页面求值。
探测器内部带看门狗（8s），任何一步抛错都会把错误带回 Python，而不是让 CDP 干等。
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

HERE = _ROOT
sys.path.insert(0, HERE)
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-52s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


PROBE_SKELETON = r"""
(function(){
  function q(s){ return document.querySelector(s); }
  function vis(el){ return el ? !el.hidden : null; }
  var out = {err: null};
  return new Promise(function(resolve){
    var done = false;
    function doneOnce(){ if (done) return; done = true; resolve(out); }
    setTimeout(doneOnce, 8000);   /* 看门狗：任何一步抛错都不让 CDP 干等 */
    try {
      out.paneExists = !!q('#aiPane');
      out.hiddenInitially = q('#aiPane') ? q('#aiPane').hidden : null;
      out.menuItem = !!q('#btnAISidebar');
      out.bubbleBtn = !!q('#selAI');
      if (q('#btnAISidebar')) q('#btnAISidebar').click();
      out.openAfterMenu = vis(q('#aiPane'));
      if (q('#aiClose')) q('#aiClose').click();
      out.closedAfterX = q('#aiPane') ? q('#aiPane').hidden : null;

      var ed = q('#editor');
      ed.textContent = '第一段文字\n第二段文字';
      var node = ed.firstChild;
      var r = document.createRange();
      r.setStart(node, 0); r.setEnd(node, 4);
      var sel = window.getSelection();
      sel.removeAllRanges(); sel.addRange(r);
      ed.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));

      setTimeout(function(){
        try {
          out.bubbleVisible = vis(q('#selTools'));
          if (q('#selAI')) q('#selAI').click();
          setTimeout(function(){
            try {
              out.openAfterBubble = vis(q('#aiPane'));
              out.ctxVisible = vis(q('#aiCtxBox'));
              out.ctxText = q('#aiCtxText') ? q('#aiCtxText').textContent : '';
              out.inputFocused = document.activeElement === q('#aiInput');
              document.dispatchEvent(new KeyboardEvent('keydown',
                {key: 'A', ctrlKey: true, shiftKey: true, bubbles: true}));
              out.hiddenAfterShortcut = q('#aiPane') ? q('#aiPane').hidden : null;
              document.dispatchEvent(new KeyboardEvent('keydown',
                {key: 'A', ctrlKey: true, shiftKey: true, bubbles: true}));
              out.openAfterShortcut = vis(q('#aiPane'));
              var rz = q('#aiResizer'), pane = q('#aiPane');
              out.resizerVisible = vis(rz);
              out.basisBefore = pane ? getComputedStyle(pane).flexBasis : null;
              if (rz) {
                rz.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, clientX: 100}));
                document.dispatchEvent(new MouseEvent('mousemove',
                  {bubbles: true, clientX: window.innerWidth - 420}));
                document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
              }
              out.widthStored = localStorage.getItem('md-ai-w');
              out.basisAfter = pane ? getComputedStyle(pane).flexBasis : null;
            } catch (e) { out.err = String(e); }
            doneOnce();
          }, 120);
        } catch (e) { out.err = String(e); doneOnce(); }
      }, 120);
    } catch (e) { out.err = String(e); doneOnce(); }
  });
})()
"""


if __name__ == "__main__":
    res = run_expr(PROBE_SKELETON)
    check("探测器无异常", not res.get("err"), str(res.get("err")))
    check("侧栏存在", res.get("paneExists") is True, str(res))
    check("默认隐藏", res.get("hiddenInitially") is True, str(res.get("hiddenInitially")))
    check("AI 菜单里有「AI 侧栏」", res.get("menuItem") is True, str(res))
    check("选区气泡有「问 AI」", res.get("bubbleBtn") is True, str(res))
    check("菜单可打开侧栏", res.get("openAfterMenu") is True, str(res))
    check("× 可关闭侧栏", res.get("closedAfterX") is True, str(res))
    check("选中后气泡出现", res.get("bubbleVisible") is True, str(res))
    check("气泡「问 AI」打开侧栏", res.get("openAfterBubble") is True, str(res))
    check("上下文块可见", res.get("ctxVisible") is True, str(res))
    check("上下文是选中原文", res.get("ctxText") == "第一段文", repr(res.get("ctxText")))
    check("打开后输入框聚焦", res.get("inputFocused") is True, str(res))
    check("Ctrl+Shift+A 关闭", res.get("hiddenAfterShortcut") is True, str(res))
    check("Ctrl+Shift+A 再开", res.get("openAfterShortcut") is True, str(res))
    check("拖条可见", res.get("resizerVisible") is True, str(res))
    check("拖宽写入 localStorage", res.get("widthStored") == "420", repr(res.get("widthStored")))
    check("拖宽即时生效", res.get("basisAfter") == "420px",
          "%r -> %r" % (res.get("basisBefore"), res.get("basisAfter")))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)
