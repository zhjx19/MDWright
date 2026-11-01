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


PROBE_CHAT = r"""
(function(){
  function q(s){ return document.querySelector(s); }
  var out = {err: null, bodies: [], disabledDuring: null};
  var realFetch = window.fetch;
  window.fetch = function(u, o){
    if (String(u).indexOf('/api/chat') >= 0) {
      out.bodies.push(JSON.parse(o.body));
      var mode = out.mode || 'ok';
      return Promise.resolve({ json: function(){
        return Promise.resolve(mode === 'err'
          ? {ok: false, error: '后端连不上'}
          : {ok: true, text: '**加粗** 回答'});
      }});
    }
    return realFetch.apply(window, arguments);
  };
  return new Promise(function(resolve){
    var done = false;
    function doneOnce(){ if (done) return; done = true; resolve(out); }
    setTimeout(doneOnce, 8000);
    try {
      q('#btnAISidebar').click();               /* 无选区也能开 */
      q('#aiInput').value = '这段什么意思';
      q('#aiSend').click();
      out.disabledDuring = q('#aiSend').disabled;
      setTimeout(function(){
        try {
          var bots = document.querySelectorAll('.ai-msg.bot');
          out.botCount = bots.length;
          out.botHtml = bots.length ? bots[bots.length-1].querySelector('.ai-body').innerHTML : '';
          out.botText = bots.length ? bots[bots.length-1].querySelector('.ai-body').textContent : '';
          out.userText = (document.querySelector('.ai-msg.user .ai-body') || {}).textContent || '';
          var b0 = out.bodies[0] || {};
          out.msgRoles = (b0.messages || []).map(function(m){ return m.role; });
          out.sentContent = (b0.messages && b0.messages[0]) ? b0.messages[0].content : '';
          out.ctxSelection = b0.context ? b0.context.selection : 'no-context';
          /* 错误 + 重试 */
          out.mode = 'err';
          q('#aiInput').value = '第二个问题';
          q('#aiInput').dispatchEvent(new KeyboardEvent('keydown',
            {key: 'Enter', bubbles: true}));
          setTimeout(function(){
            try {
              var errs = document.querySelectorAll('.ai-msg.err');
              out.errCount = errs.length;
              out.errText = errs.length ? errs[errs.length-1].textContent : '';
              var retry = document.querySelector('.ai-msg.err button[data-ai-do="retry"]');
              out.hasRetry = !!retry;
              out.beforeRetry = out.bodies.length;
              if (retry) retry.click();
              setTimeout(function(){
                try {
                  out.afterRetry = out.bodies.length;
                  out.disabledAfter = q('#aiSend').disabled;
                } catch (e) { out.err = String(e); }
                doneOnce();
              }, 200);
            } catch (e) { out.err = String(e); doneOnce(); }
          }, 200);
        } catch (e) { out.err = String(e); doneOnce(); }
      }, 200);
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

    res2 = run_expr(PROBE_CHAT)
    check("对话探测器无异常", not res2.get("err"), str(res2.get("err")))
    check("用户消息上屏", "这段什么意思" in (res2.get("userText") or ""), str(res2.get("userText")))
    check("回答渲染 Markdown", "<strong>加粗</strong>" in (res2.get("botHtml") or ""),
          str(res2.get("botHtml")))
    check("请求只带 user 消息", res2.get("msgRoles") == ["user"], str(res2.get("msgRoles")))
    check("请求内容正确", res2.get("sentContent") == "这段什么意思", str(res2.get("sentContent")))
    check("无选区时 context.selection 为 null", res2.get("ctxSelection") is None,
          repr(res2.get("ctxSelection")))
    check("生成中禁用发送", res2.get("disabledDuring") is True, str(res2.get("disabledDuring")))
    check("失败显示错误气泡", res2.get("errCount", 0) >= 1 and "后端连不上" in (res2.get("errText") or ""),
          str(res2.get("errText")))
    check("错误气泡带重试", res2.get("hasRetry") is True, str(res2.get("hasRetry")))
    check("重试会重新发请求", (res2.get("afterRetry") or 0) > (res2.get("beforeRetry") or 0),
          "%r -> %r" % (res2.get("beforeRetry"), res2.get("afterRetry")))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)
