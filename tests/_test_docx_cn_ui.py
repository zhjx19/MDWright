# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 中文版式的界面级回归：

- 「设置 → 排版」有中文版式开关，默认勾选
- 导出请求体带 docxCn=true
- 取消勾选并应用后写进 localStorage，重开面板回填；请求体跟着变 false
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
        return Promise.resolve({ok:true,path:'C:\\tmp\\cn.docx'});}});
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
      var cb=document.getElementById('tsDocxCn');
      var first=cb?cb.checked:null;
      exportOnce();
      setTimeout(function(){
        cb.checked=false;
        document.getElementById('tsApply').click();
        var saved=null;
        try{saved=JSON.parse(localStorage.getItem('md-editor-typeset-v3')||'{}').docx||null;}catch(e){}
        document.getElementById('tsClose').click();
        openTs();
        var reopen=document.getElementById('tsDocxCn').checked;
        document.getElementById('tsClose').click();
        exportOnce();
        setTimeout(function(){
          window.fetch=orig;
          resolve({first:first, saved:saved, reopen:reopen, caps:caps});
        },1800);
      },1800);
    },2200);
  });
})()
"""


def main():
    tmp = tempfile.mkdtemp(prefix="mdcnui-")
    try:
        doc = os.path.join(tmp, "中文版式界面.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write("# 标题\n\n正文 English。\n")
        url = "http://127.0.0.1:%d/?file=%s" % (PORT, urllib.parse.quote(doc))
        res = run_expr(EXPR, url=url) or {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    caps = res.get("caps") or []
    check("开关存在且默认开", res.get("first") is True, str(res.get("first")))
    check("两次导出请求都拿到了", len(caps) >= 2, "n=%d" % len(caps))
    p1 = caps[0] if caps else {}
    p2 = caps[-1] if caps else {}
    check("默认请求体 docxCn=true", p1.get("docxCn") is True, str(p1.get("docxCn")))
    check("取消后写进 localStorage", (res.get("saved") or {}).get("cn") is False,
          str(res.get("saved")))
    check("重开面板回填未勾选", res.get("reopen") is False, str(res.get("reopen")))
    check("取消后请求体 docxCn=false", p2.get("docxCn") is False, str(p2.get("docxCn")))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
