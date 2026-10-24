# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""保存链路的两处用户可见行为：

1. 另存为成功后，文件**立刻进「最近文件」**（原来只有打开/选文件才记，刚保存的找不到）；
2. 排版默认值：三线表与表头底色**默认勾选**（新用户打开就是三线表）。
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
  var out = {};
  /* ── 默认值：打开设置 → 排版 ── */
  document.getElementById('btnSettings').click();
  [].slice.call(document.querySelectorAll('#setTabs .set-tab')).filter(function(b){
    return b.getAttribute('data-tab') === 'typeset'; })[0].click();
  out.three = document.getElementById('tsThree').checked;
  out.headOn = document.getElementById('tsHeadOn').checked;
  document.getElementById('tsClose').click();

  /* ── 另存为：走页面内保存框（浏览器模式），目录用测试临时目录 ── */
  var dir = "@@DIR@@";
  var ed = document.getElementById('editor');
  ed.textContent = '# 保存测试\n\n正文\n';
  ed.dispatchEvent(new Event('input', {bubbles:true}));
  document.getElementById('svOverlay').hidden = false;
  document.getElementById('svDir').value = dir;
  document.getElementById('svName').value = 'saved-by-test';
  document.getElementById('svFmt').value = '.md';
  document.getElementById('svGo').click();

  return new Promise(function(resolve){
    setTimeout(function(){
      var rec = [];
      try { rec = JSON.parse(localStorage.getItem('md-editor-recent') || '[]'); } catch(e){}
      out.recent = rec.map(function(r){ return r.name; });
      out.fileExists = false;
      /* 用最近文件面板确认渲染出来的条目 */
      document.getElementById('btnRecent').click();
      setTimeout(function(){
        out.fmItems = [].slice.call(document.querySelectorAll('#fmList .fm-item'))
          .map(function(el){ return el.textContent.trim(); });
        resolve(out);
      }, 300);
    }, 1200);
  });
})()
"""


def main():
    tmp = tempfile.mkdtemp(prefix="mdsaveui-")
    url = "http://127.0.0.1:18777/?file="
    r = run_expr(PROBE.replace("@@DIR@@", tmp.replace("\\", "/")), url=url)

    check("三线表默认勾选", r.get("three") is True, str(r.get("three")))
    check("表头底色默认勾选", r.get("headOn") is True, str(r.get("headOn")))
    names = r.get("recent") or []
    check("另存为后进最近文件", any("saved-by-test" in n for n in names), str(names))
    check("文件真的写到了选定目录",
          os.path.isfile(os.path.join(tmp, "saved-by-test.md")), tmp)
    check("最近文件面板里能看到它",
          any("saved-by-test" in x for x in (r.get("fmItems") or [])),
          str(r.get("fmItems"))[:160])

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
