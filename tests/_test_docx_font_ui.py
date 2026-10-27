# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word 导出字体的界面级回归（R1）：
- 「设置 → 排版」里有中/西文两个下拉，默认 SimSun / Times New Roman
- 常用组在前、本机字体组在 /api/fonts 回来后补上
- 应用后写进 localStorage，重开面板能回填
- 导出请求体真的带上了 latinFont / cjkFont（不是只在界面上摆着）

页面用 `?file=` 打开一个临时文档：否则 currentFile 为空，点导出只会在
「请先保存文档」那句提示上停下，根本走不到请求体。
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
  var captured=null, orig=window.fetch;
  window.fetch=function(url,opt){
    var u=String(url||'');
    if(u.indexOf('/api/save-dialog')===0){
      return Promise.resolve({json:function(){
        return Promise.resolve({ok:true,path:'C:\\tmp\\t.docx'});}});
    }
    if(u.indexOf('/api/export-docx')===0){
      try{captured=JSON.parse(opt.body);}catch(e){}
      return Promise.resolve({json:function(){
        return Promise.resolve({ok:false,error:'stub'});}});
    }
    return orig.apply(window,arguments);
  };
  return new Promise(function(resolve){
    setTimeout(function(){
      openTs();
      var c=document.querySelector('select[data-docxfont="cjk"]');
      var l=document.querySelector('select[data-docxfont="latin"]');
      var first={cjk:c?c.value:null, latin:l?l.value:null};
      var presets={
        cjk:c?c.querySelectorAll('optgroup[label="\u5e38\u7528"] option').length:0,
        latin:l?l.querySelectorAll('optgroup[label="\u5e38\u7528"] option').length:0};
      var sys={
        cjk:c?c.querySelectorAll('optgroup[label="\u672c\u673a\u5b57\u4f53"] option').length:0,
        latin:l?l.querySelectorAll('optgroup[label="\u672c\u673a\u5b57\u4f53"] option').length:0};
      c.value='SimHei'; l.value='Georgia';
      document.getElementById('tsApply').click();
      var saved=null;
      try{saved=JSON.parse(localStorage.getItem('md-editor-typeset-v3')||'{}').docx||null;}catch(e){}
      document.getElementById('tsClose').click();
      openTs();
      var reopen={cjk:c.value, latin:l.value};
      document.getElementById('tsClose').click();
      document.getElementById('btnExportDocx').click();
      setTimeout(function(){
        window.fetch=orig;
        resolve({first:first, presets:presets, sys:sys, saved:saved, reopen:reopen,
                 toast:(document.querySelector('#mdToast')||{}).textContent||'',
                 payload:captured?{latinFont:captured.latinFont, cjkFont:captured.cjkFont}:null});
      },2000);
    },2000);
  });
})()
"""


def main():
    tmp = tempfile.mkdtemp(prefix="mdfontui-")
    try:
        doc = os.path.join(tmp, "字体界面.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write("# 标题\n\n正文 English。\n")
        url = "http://127.0.0.1:%d/?file=%s" % (PORT, urllib.parse.quote(doc))
        res = run_expr(EXPR, url=url)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    first = res.get("first") or {}
    check("中文下拉默认宋体", first.get("cjk") == "SimSun", str(first))
    check("西文下拉默认 Times New Roman", first.get("latin") == "Times New Roman", str(first))
    presets = res.get("presets") or {}
    check("常用组已填充（中文 >=7 项）", (presets.get("cjk") or 0) >= 7, str(presets))
    check("常用组已填充（西文 >=7 项）", (presets.get("latin") or 0) >= 7, str(presets))
    sysf = res.get("sys") or {}
    check("本机组已由 /api/fonts 填充",
          (sysf.get("cjk") or 0) > 50 and (sysf.get("latin") or 0) > 50, str(sysf))
    check("应用后写进 localStorage",
          (res.get("saved") or {}) == {"cjk": "SimHei", "latin": "Georgia"},
          str(res.get("saved")))
    check("重开面板回填已保存字体",
          (res.get("reopen") or {}) == {"cjk": "SimHei", "latin": "Georgia"},
          str(res.get("reopen")))
    check("导出请求带上字体",
          (res.get("payload") or {}) == {"latinFont": "Georgia", "cjkFont": "SimHei"},
          str(res.get("payload")) + " toast=" + str(res.get("toast")))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
