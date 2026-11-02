# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 导出版面的界面级回归：

- 导出请求体带 page（排版 → 分页 的纸张与四边距），默认 A4 + 25/18/25/18
- 改成 A5 + 20/15/20/15 并应用后，请求体跟着变
- 请求体带表头底色开关与色值，默认开、#dbe5ff；关掉后 headOn=false
"""
# --- 测试入口 shim：同 _test_browser 口径 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

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


EXPR = r"""
(function(){
  function openTs(){
    document.getElementById('btnSettings').click();
    var tabs=document.querySelectorAll('#setTabs .set-tab');
    for(var i=0;i<tabs.length;i++){
      if(tabs[i].getAttribute('data-tab')==='typeset')tabs[i].click();
    }
  }
  var caps=[], orig=window.fetch;
  window.fetch=function(url,opt){
    var u=String(url||'');
    if(u.indexOf('/api/save-dialog')===0){
      return Promise.resolve({json:function(){
        return Promise.resolve({ok:true,path:'C:\\tmp\\p.docx'});}});
    }
    if(u.indexOf('/api/export-docx')===0){
      try{caps.push(JSON.parse(opt.body));}catch(e){}
      return Promise.resolve({json:function(){
        return Promise.resolve({ok:false,error:'stub'});}});
    }
    return orig.apply(window,arguments);
  };
  function exportOnce(){ document.getElementById('btnExportDocx').click(); }
  return new Promise(function(resolve){
    setTimeout(function(){
      openTs();
      exportOnce();                       /* 1) 默认值 */
      setTimeout(function(){
        document.getElementById('tsPaper').value='A5';
        document.getElementById('tsMt').value='20';
        document.getElementById('tsMr').value='15';
        document.getElementById('tsMb').value='20';
        document.getElementById('tsMl').value='15';
        document.getElementById('tsHeadOn').checked=false;
        document.getElementById('tsHeadColor').value='#ffcc00';
        document.getElementById('tsApply').click();
        document.getElementById('tsClose').click();
        exportOnce();                     /* 2) 改过之后 */
        setTimeout(function(){
          openTs();
          document.getElementById('tsPnOn').value='on';
          document.getElementById('tsPnPos').value='bc';
          document.getElementById('tsPnTpl').value='第 {p} 页 / 共 {P} 页';
          document.getElementById('tsPnSize').value='10';
          document.getElementById('tsApply').click();
          document.getElementById('tsClose').click();
          exportOnce();                   /* 3) 页码设置 */
          setTimeout(function(){
            window.fetch=orig;
            resolve(caps);
          },1800);
        },1800);
      },1800);
    },2200);
  });
})()
"""


def main():
    tmp = tempfile.mkdtemp(prefix="mdpageui-")
    try:
        doc = os.path.join(tmp, "版面界面.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write("# 标题\n\n正文 English。\n\n| A | B |\n|---|---|\n| 1 | 2 |\n")
        url = "http://127.0.0.1:%d/?file=%s" % (PORT, urllib.parse.quote(doc))
        caps = run_expr(EXPR, url=url) or []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    check("三次导出请求都拿到了", len(caps) >= 3, "n=%d" % len(caps))
    p1 = caps[0] if caps else {}
    p2 = caps[1] if len(caps) > 1 else {}
    p3 = caps[2] if len(caps) > 2 else {}
    pg1 = p1.get("page") or {}
    pg2 = p2.get("page") or {}
    pg3 = p3.get("page") or {}
    check("默认纸张 A4", pg1.get("paper") == "A4", str(pg1))
    check("默认边距 25/18/25/18",
          [pg1.get("mt"), pg1.get("mr"), pg1.get("mb"), pg1.get("ml")] == [25, 18, 25, 18],
          str(pg1))
    check("改后纸张 A5", pg2.get("paper") == "A5", str(pg2))
    check("改后边距 20/15/20/15",
          [pg2.get("mt"), pg2.get("mr"), pg2.get("mb"), pg2.get("ml")] == [20, 15, 20, 15],
          str(pg2))
    check("默认表头底色开 + #dbe5ff",
          p1.get("tableHeadOn") is True and p1.get("tableHeadColor") == "#dbe5ff",
          str({k: p1.get(k) for k in ("tableHeadOn", "tableHeadColor")}))
    check("关掉后 headOn=false",
          p2.get("tableHeadOn") is False, str({k: p2.get(k) for k in ("tableHeadOn",)}))
    check("色值随面板走", p2.get("tableHeadColor") == "#ffcc00",
          str(p2.get("tableHeadColor")))
    pn = pg3.get("pn") or {}
    check("页码开关随面板", pn.get("on") == "on", str(pn))
    check("页码位置随面板", pn.get("pos") == "bc", str(pn))
    check("页码模板随面板", pn.get("tpl") == "第 {p} 页 / 共 {P} 页", str(pn))
    check("页码字号随面板", pn.get("size") == 10, str(pn))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
