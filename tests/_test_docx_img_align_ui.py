# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 独行图默认对齐的界面级回归：

- 「排版 → 图片」默认居中，导出请求体 imgAlign=center
- 改成左对齐并应用后，请求体 imgAlign=left
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
        return Promise.resolve({ok:true,path:'C:\\tmp\\a.docx'});}});
    }
    if(u.indexOf('/api/export-docx')===0){
      try{caps.push(JSON.parse(opt.body));}catch(e){}
      return Promise.resolve({json:function(){
        return Promise.resolve({ok:false,error:'stub'});}});
    }
    return orig.apply(window,arguments);
  };
  return new Promise(function(resolve){
    setTimeout(function(){
      openTs();
      var sel=document.querySelector('select[data-algn="img"]');
      var first=sel?sel.value:null;
      document.getElementById('btnExportDocx').click();
      setTimeout(function(){
        if(sel){ sel.value='left'; }
        document.getElementById('tsApply').click();
        document.getElementById('tsClose').click();
        document.getElementById('btnExportDocx').click();
        setTimeout(function(){
          window.fetch=orig;
          resolve({first:first, caps:caps});
        },1800);
      },1800);
    },2200);
  });
})()
"""


def main():
    tmp = tempfile.mkdtemp(prefix="mda-")
    try:
        doc = os.path.join(tmp, "图对齐界面.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write("# 标题\n\n正文 English。\n")
        url = "http://127.0.0.1:%d/?file=%s" % (PORT, urllib.parse.quote(doc))
        res = run_expr(EXPR, url=url) or {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    caps = res.get("caps") or []
    check("图片默认对齐居中", res.get("first") == "center", str(res.get("first")))
    check("两次导出请求都拿到了", len(caps) >= 2, "n=%d" % len(caps))
    p1 = caps[0] if caps else {}
    p2 = caps[1] if len(caps) > 1 else {}
    check("默认请求体 imgAlign=center", p1.get("imgAlign") == "center",
          str(p1.get("imgAlign")))
    check("改后请求体 imgAlign=left", p2.get("imgAlign") == "left",
          str(p2.get("imgAlign")))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
