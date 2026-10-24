# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""浏览器级：变量跨块、刷新后输出恢复、会话重置按钮。"""
# --- 测试入口 shim ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, _ROOT)
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


PROBE = r"""
(function(){
  var ed = document.getElementById('editor');
  ed.textContent = '```r\nx <- 40\n```\n\n```r\nx + 2\n```\n';
  ed.dispatchEvent(new Event('input', {bubbles:true}));
  return new Promise(function(resolve){
    setTimeout(function(){
      var btns = [].slice.call(document.querySelectorAll('#preview .run-btn'));
      if(btns.length < 2){ resolve({count: btns.length}); return; }
      btns[0].click();
      setTimeout(function(){
        btns[1].click();
        setTimeout(function(){
          var outs = [].slice.call(document.querySelectorAll('#preview .r-out'));
          resolve({
            count: btns.length,
            out1: outs[0] ? outs[0].textContent : '',
            out2: outs[1] ? outs[1].textContent : '',
            resetBtn: !!document.getElementById('btnResetSession'),
          });
        }, 7000);
      }, 7000);
    }, 1200);
  });
})()
"""

RESTORE = r"""
(function(){
  return new Promise(function(resolve){
    setTimeout(function(){
      var outs = [].slice.call(document.querySelectorAll('#preview .r-out'))
        .filter(function(o){ return !o.hidden && o.textContent.trim(); })
        .map(function(o){ return o.textContent; });
      resolve({restored: outs.length, texts: outs});
    }, 3000);
  });
})()
"""

RESET = r"""
(function(){
  var btn = document.getElementById('btnResetSession');
  if(!btn) return Promise.resolve({ok:false});
  btn.click();
  return new Promise(function(resolve){
    setTimeout(function(){ resolve({ok:true}); }, 1200);
  });
})()
"""


def main():
    tmp = tempfile.mkdtemp(prefix="mdrunui-")
    doc = os.path.join(tmp, "ui.md")
    # 内容必须与 PROBE 里写进编辑区的一致：重开后按 (语言, 代码原文) 匹配侧车，
    # 文件里没有这两块就没有可恢复的对象（这正是"代码改了就不显示旧结果"的口径）。
    with open(doc, "w", encoding="utf-8") as f:
        f.write("```r\nx <- 40\n```\n\n```r\nx + 2\n```\n")
    url = "http://127.0.0.1:18777/?file=" + doc.replace("\\", "/")

    r = run_expr(PROBE, url=url)
    check("两块各有一个运行按钮", r.get("count") == 2, str(r.get("count")))
    check("第一块跑出结果（无输出也算完成）", r.get("out1") is not None, str(r.get("out1"))[:80])
    check("第二块能用到第一块的变量", "42" in (r.get("out2") or ""),
          str(r.get("out2"))[:120])
    check("工具栏有会话重置按钮", r.get("resetBtn") is True, str(r.get("resetBtn")))

    r2 = run_expr(RESTORE, url=url)
    check("刷新后输出从侧车恢复", (r2.get("restored") or 0) >= 1, str(r2)[:160])
    check("恢复里含第二块的 42", "42" in "".join(r2.get("texts") or []), str(r2.get("texts"))[:160])

    r3 = run_expr(RESET, url=url)
    check("重置按钮可点", r3.get("ok") is True, str(r3))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
