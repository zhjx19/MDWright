# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""图表进 Word 的前端那一段（v3.3.0）：真浏览器里点「导出 Word」，看请求体。

要验的就三件：
- 预览里渲染好的 SVG 栅格化成 PNG 交上来（base64 以 PNG 魔数开头、长度像真图）；
- 交上来的「语言 + 源码」与围栏逐字一致，后端才认得出该换哪一块；
- mermaid 用 SVG 文字标签（没有 foreignObject）——否则 Word 里图是空框。
后端换成图片、落进 docx 的那一头在 `_test_diagram_docx.py`。
"""
# --- 测试入口 shim ---
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.argv = ["md_server.py"]
from _test_browser import find_browser, run_expr   # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-48s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


DOC = """# 图表导出

正文一段。

```mermaid
graph TD
A[开始] --> B{判断}
B --> C[结束]
```

```dot
digraph G { A -> B; }
```
"""

PROBE = r"""
(function(){
  function settled(){
    var ds=document.querySelectorAll('#preview .diagram');
    if(ds.length<2) return false;
    for(var i=0;i<ds.length;i++){
      if(!ds[i].classList.contains('diagram-ok')) return false;
    }
    return true;
  }
  return new Promise(function(resolve){
    var t0=Date.now();
    (function wait(){
      if(!settled()){
        if(Date.now()-t0>25000){
          resolve({timeout:true, stage:'render',
                   count:document.querySelectorAll('#preview .diagram').length});
          return;
        }
        setTimeout(wait,200); return;
      }
      var ds=document.querySelectorAll('#preview .diagram');
      var svgs=document.querySelectorAll('#preview .diagram svg');
      var foreign=0;
      for(var i=0;i<svgs.length;i++){
        if(svgs[i].querySelector('foreignObject')) foreign++;
      }
      var body=null;
      var orig=window.fetch;
      window.fetch=function(u,o){
        var url=String(u);
        if(url.indexOf('/api/save-dialog')>=0){
          return Promise.resolve({json:function(){return Promise.resolve(
            {ok:true, path:'C:/tmp/diagram-test.docx'});}});
        }
        if(url.indexOf('/api/export-docx')>=0){
          try{ body=JSON.parse(o.body); }catch(e){ body={err:String(e)}; }
          return Promise.resolve({json:function(){return Promise.resolve(
            {ok:true, path:'C:/tmp/diagram-test.docx',
             diagrams:2, diagramTotal:2});}});
        }
        return orig.apply(window,arguments);
      };
      var dataLangs=[];
      for(var k=0;k<ds.length;k++) dataLangs.push(ds[k].getAttribute('data-lang'));
      document.getElementById('btnExportDocx').click();
      (function waitBody(){
        if(!body){
          if(Date.now()-t0>45000){ resolve({timeout:true, stage:'request', foreign:foreign}); return; }
          setTimeout(waitBody,200); return;
        }
        var items=body.diagrams||[];
        resolve({
          svgCount:svgs.length, foreign:foreign, dataLangs:dataLangs,
          diagramCount:items.length,
          langs:items.map(function(d){return d.lang;}),
          lengths:items.map(function(d){return (d.png||'').length;}),
          heads:items.map(function(d){return (d.png||'').slice(0,12);}),
          widths:items.map(function(d){return d.width;}),
          codes:items.map(function(d){return d.code;}),
          markdown:body.markdown||'',
          toast:(document.querySelector('#mdToast')||{}).textContent||''
        });
      })();
    })();
  });
})()
"""


def main():
    if not find_browser():
        print("SKIP 本机没有 Chromium 内核浏览器")
        print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
        sys.exit(77)

    tmp = tempfile.mkdtemp(prefix="mddiagui-")
    doc = os.path.join(tmp, "图表.md")
    try:
        with open(doc, "w", encoding="utf-8", newline="\n") as f:
            f.write(DOC)
        url = ("http://127.0.0.1:18777/?file="
               + urllib.parse.quote(doc.replace("\\", "/")))
        r = run_expr(PROBE, url=url)
        if r.get("timeout"):
            check("图表渲染并发出导出请求", False, str(r))
        else:
            check("两张图都渲染完成", r.get("svgCount") == 2, str(r)[:200])
            check("mermaid 没有 foreignObject（Word 才认）",
                  r.get("foreign") == 0, str(r)[:200])
            check("请求体带两张位图", r.get("diagramCount") == 2, str(r)[:200])
            check("语言按文档顺序交回", r.get("langs") == ["mermaid", "dot"],
                  str(r.get("langs")))
            check("DOM 上有 data-lang", r.get("dataLangs") == ["mermaid", "dot"],
                  str(r.get("dataLangs")))
            heads = r.get("heads") or []
            check("base64 是 PNG（魔数对）",
                  len(heads) == 2 and all(h.startswith("iVBORw0KGgo") for h in heads),
                  str(heads))
            lens = r.get("lengths") or [0, 0]
            check("图不是空白小图", len(lens) == 2 and min(lens) > 2000, str(lens))
            widths = r.get("widths") or []
            check("宽度是 10~100 的百分比",
                  len(widths) == 2 and all(isinstance(w, int) and 10 <= w <= 100
                                           for w in widths), str(widths))
            codes = r.get("codes") or []
            check("源码原文逐字交回",
                  len(codes) == 2 and "graph TD" in codes[0] and "digraph" in codes[1]
                  and codes[0].endswith("C[结束]"), str(codes)[:200])
            check("源文里围栏还在（后端负责换）",
                  "```mermaid" in (r.get("markdown") or ""))
            check("提示已导出", "已导出" in (r.get("toast") or ""), r.get("toast"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
