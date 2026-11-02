# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 目录的界面级回归：

- 「设置 → 排版」有目录开关，默认不勾
- 勾选并应用后写进 localStorage，重开面板回填
- 导出请求体带 docxToc=true
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
        return Promise.resolve({ok:true,path:'C:\\tmp\\toc.docx'});}});
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
      var cb=document.getElementById('tsDocxToc');
      if(!cb){ resolve({missing:true}); return; }
      var first=cb.checked;
      cb.checked=true;
      document.getElementById('tsApply').click();
      var saved=null;
      try{saved=JSON.parse(localStorage.getItem('md-editor-typeset-v3')||'{}').docx||null;}catch(e){}
      document.getElementById('tsClose').click();
      openTs();
      var reopen=document.getElementById('tsDocxToc').checked;
      document.getElementById('tsClose').click();
      document.getElementById('btnExportDocx').click();
      setTimeout(function(){
        window.fetch=orig;
        resolve({first:first, saved:saved, reopen:reopen, caps:caps});
      },1800);
    },2200);
  });
})()
"""


def main():
    tmp = tempfile.mkdtemp(prefix="mdtocui-")
    try:
        doc = os.path.join(tmp, "目录界面.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write("# 标题\n\n正文 English。\n")
        url = "http://127.0.0.1:%d/?file=%s" % (PORT, urllib.parse.quote(doc))
        res = run_expr(EXPR, url=url) or {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    check("开关存在", not res.get("missing"), str(res.get("missing")))
    check("默认不勾", res.get("first") is False, str(res.get("first")))
    check("勾选后写进 localStorage", (res.get("saved") or {}).get("toc") is True,
          str(res.get("saved")))
    check("重开面板回填已勾选", res.get("reopen") is True, str(res.get("reopen")))
    caps = res.get("caps") or []
    p = caps[-1] if caps else {}
    check("导出请求体 docxToc=true", p.get("docxToc") is True, str(p.get("docxToc")))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
