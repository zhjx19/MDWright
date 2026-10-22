# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""即时渲染（live）模式浏览器级回归（v2.6.1）：

- 视图循环出现第 4 态「即时」，进入后 #editorPane 隐藏（单栏满宽）
- 非 live 模式下点预览块**不**进入编辑（守卫）
- live 下点某块 → 块内出现 textarea.pblk-src，内容是该块原文
- 改字后失焦 → 主缓冲更新、该块重渲成新内容、其它块不受影响、退出编辑态
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-44s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


DOC = "\n".join([
    "# \u6807\u9898\u4e00",
    "\u7b2c\u4e00\u6bb5\u5185\u5bb9",
    "",
    "## \u6807\u9898\u4e8c",
    "\u7b2c\u4e8c\u6bb5\u5185\u5bb9",
    "",
])

PROBE = r"""
(function(){
  var out={};
  var ed=document.getElementById('editor');
  ed.textContent=%s;
  ed.dispatchEvent(new Event('input',{bubbles:true}));
  function wait(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  function pblks(){ return [].slice.call(document.querySelectorAll('#preview .pblk')); }
  return new Promise(function(resolve){
    wait(700).then(function(){
      /* 非 live：点块不应进入编辑 */
      var b0=pblks()[0];
      if(b0){ (b0.querySelector('p')||b0).click(); }
      return wait(80);
    }).then(function(){
      out.splitNoEdit = !document.querySelector('#preview textarea.pblk-src');
      /* 切到「即时」（循环点击，最多 6 次） */
      var btn=document.getElementById('btnView');
      for(var i=0;i<6 && !document.body.classList.contains('view-live');i++) btn.click();
      out.viewLive=document.body.classList.contains('view-live');
      out.btnText=btn.textContent.trim();
      out.editorHidden=getComputedStyle(document.getElementById('editorPane')).display==='none';
      return wait(700);
    }).then(function(){
      out.blockCount=pblks().length;
      if(out.blockCount<2){ resolve(out); return; }
      var blk=pblks()[1];
      (blk.querySelector('p')||blk).click();
      return wait(150).then(function(){
        var ta=blk.querySelector('textarea.pblk-src');
        out.taShown=!!ta;
        out.taValue=ta?ta.value:'';
        out.editingClass=blk.classList.contains('editing');
        if(!ta){ resolve(out); return; }
        ta.value='## \u6807\u9898\u4e8c\n\u6539\u540e\u7684\u7b2c\u4e8c\u6bb5';
        ta.dispatchEvent(new Event('blur'));
        return wait(700);
      }).then(function(){
        out.editorText=document.getElementById('editor').textContent;
        out.stillEditing=blk.classList.contains('editing');
        var after=pblks();
        out.blockCount2=after.length;
        out.block1Text=after[1]?after[1].textContent:'';
        out.block0Text=after[0]?after[0].textContent:'';
        resolve(out);
      });
    });
  });
})()
""" % json.dumps(DOC, ensure_ascii=False)


def main():
    out = run_expr(PROBE)
    check("切到即时视图（第 4 态）", out.get("viewLive") is True, str(out.get("viewLive")))
    check("视图按钮显示「即时」", out.get("btnText") == "\u5373\u65f6", str(out.get("btnText")))
    check("即时视图下编辑栏隐藏", out.get("editorHidden") is True, str(out.get("editorHidden")))
    check("非 live 模式点块不进编辑", out.get("splitNoEdit") is True, str(out.get("splitNoEdit")))
    check("文档切成 2 块", out.get("blockCount") == 2, str(out.get("blockCount")))
    check("点块出现源码框", out.get("taShown") is True, str(out.get("taShown")))
    ta = out.get("taValue") or ""
    check("源码框内容是该块原文", ("## \u6807\u9898\u4e8c" in ta) and ("\u7b2c\u4e8c\u6bb5\u5185\u5bb9" in ta),
          repr(ta[:60]))
    check("该块进入 editing 态", out.get("editingClass") is True, str(out.get("editingClass")))
    check("改字回写主缓冲", "\u6539\u540e\u7684\u7b2c\u4e8c\u6bb5" in (out.get("editorText") or ""),
          repr((out.get("editorText") or "")[:80]))
    check("失焦后退出编辑态", out.get("stillEditing") is False, str(out.get("stillEditing")))
    check("块数不变", out.get("blockCount2") == 2, str(out.get("blockCount2")))
    check("该块重渲成新内容", "\u6539\u540e\u7684\u7b2c\u4e8c\u6bb5" in (out.get("block1Text") or ""),
          repr((out.get("block1Text") or "")[:60]))
    check("其它块不受影响", "\u7b2c\u4e00\u6bb5\u5185\u5bb9" in (out.get("block0Text") or ""),
          repr((out.get("block0Text") or "")[:60]))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    return not fails


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
