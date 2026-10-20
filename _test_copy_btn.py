# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""代码块复制按钮测试（R1）：
- 预览里每个代码块带「复制」按钮，点击把该块代码写入剪贴板
- 导出产物（独立 HTML / 分页 HTML）**不得**含按钮（服务端剥离：独立 HTML 内
  clipboard 在 file:// 下不可靠，且按钮对读者无意义）
"""
import json
import os
import sys
import threading
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PORT = 18777

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def post(path, obj):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (PORT, path), timeout=30) as r:
        return r.read().decode("utf-8")


BUTTON_BODY = ('<div class="code-wrap"><pre><code class="lang-python" data-lang="python">x = 1</code></pre>'
               '<button type="button" class="copy-btn" title="复制代码">复制</button></div>')


def main():
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        post("/api/export-html", {"path": None, "bodyHtml": BUTTON_BODY, "tsCss": ""})
        html = get("/static/document.html")
        check("独立 HTML 不含复制按钮", "copy-btn" not in html, html[:200])
        check("独立 HTML 保留代码内容", "x = 1" in html)

        post("/api/export-paged", {"path": None, "bodyHtml": BUTTON_BODY, "tsCss": "", "cfg": {}})
        paged = get("/static/document.paged.html")
        check("分页 HTML 不含复制按钮", "copy-btn" not in paged, paged[:200])
        check("分页 HTML 保留代码内容", "x = 1" in paged)
    finally:
        httpd.shutdown()
        httpd.server_close()

    from _test_browser import run_expr
    expr = r"""
    (function(){
      var ed=document.getElementById('editor');
      ed.textContent='```python\nx = 1\n```\n\n```js\nlet y = 2\n```';
      ed.dispatchEvent(new Event('input',{bubbles:true}));
      /* 截获剪贴板写入：clipboard.writeText 是只读属性，整体替换 */
      var copied=[];
      try{
        Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
          writeText:function(t){copied.push(t);return Promise.resolve();}
        }});
      }catch(e){}
      return new Promise(function(resolve){
        setTimeout(function(){
          var btns=document.querySelectorAll('#preview .copy-btn');
          if(btns.length<2){ resolve({btnCount:btns.length}); return; }
          btns[0].click();
          setTimeout(function(){
            btns[1].click();
            setTimeout(function(){
              resolve({btnCount:btns.length, copied:copied,
                       codeCount:document.querySelectorAll('#preview pre code').length});
            },250);
          },250);
        },1400);
      });
    })()
    """
    res = run_expr(expr)
    check("预览：每个代码块一个复制按钮", res.get("btnCount") == 2, str(res.get("btnCount")))
    copied = res.get("copied") or []
    check("预览：点击复制该块代码", any("x = 1" in c for c in copied), str(copied))
    check("预览：第二块复制自己的代码", any("let y = 2" in c for c in copied), str(copied))
    check("预览：按钮不污染代码文本",
          not any("复制" in c for c in copied), str(copied))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
