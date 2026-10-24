# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""文件菜单拆分（最近文件 / 内置文档）+ 关于窗口。"""
# --- 测试入口 shim ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import sys

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
  function q(s){ return document.querySelector(s); }
  var fileLabel = [].slice.call(document.querySelectorAll('#menuBar .menu-label'))
    .filter(function(b){ return b.textContent.trim() === '文件'; })[0];
  fileLabel.click();
  var items = [].slice.call(fileLabel.parentNode.querySelectorAll('.menu-item'))
    .map(function(b){ return b.textContent.trim(); });
  var out = {items: items, hasAbout: !!document.getElementById('btnAbout')};
  if(out.hasAbout) document.getElementById('btnAbout').click();
  return new Promise(function(resolve){
    setTimeout(function(){
      var ov = q('#aboutOverlay');
      out.open = !!ov && !ov.hidden;
      out.text = ov ? ov.textContent : '';
      var ver = q('#aboutVer');
      out.ver = ver ? ver.textContent.trim() : '';
      document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
      setTimeout(function(){
        out.closedByEsc = !!ov && ov.hidden;
        var recent = document.getElementById('btnRecent');
        if(recent) recent.click();
        setTimeout(function(){
          var fm = q('#fmOverlay');
          out.recentMode = fm ? fm.getAttribute('data-mode') : '';
          out.recentHasBuiltin = !!q('#fmList [data-builtin]');
          out.recentHasList = !!q('#fmList .fm-item');
          if(fm) fm.hidden = true;
          resolve(out);
        }, 400);
      }, 300);
    }, 700);
  });
})()
"""


def main():
    r = run_expr(PROBE)
    items = r.get("items") or []
    check("文件菜单含「最近文件…」", any("最近文件" in x for x in items), str(items))
    check("文件菜单含「内置文档（帮助）…」", any("内置文档" in x and "帮助" in x for x in items),
          str(items))
    check("文件菜单含「关于」", "关于" in items, str(items))
    check("不再有合并项「最近文件 / 内置文档」",
          not any("/" in x and "最近文件" in x for x in items), str(items))
    check("关于窗口能打开", r.get("open") is True, str(r.get("open")))
    check("关于显示版本 3.2.0", r.get("ver") == "3.2.0", str(r.get("ver")))
    text = r.get("text") or ""
    check("关于含许可与上游说明", "AGPL" in text and "MDEditor" in text, text[:120])
    check("Esc 关闭关于", r.get("closedByEsc") is True, str(r.get("closedByEsc")))
    check("最近文件入口走 recent 模式", r.get("recentMode") == "recent", str(r.get("recentMode")))
    check("recent 模式不显示内置文档段",
          r.get("recentHasBuiltin") is False, str(r.get("recentHasBuiltin")))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
