# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""查找 / 替换的浏览器级回归（Ctrl+F / Ctrl+H）：

覆盖：
- Ctrl+F 打开查找条并聚焦，默认不显示替换行
- 边输入边计数（不区分大小写），下一个 / 上一个循环定位
- Ctrl+H 展开替换行；替换当前、全部替换后正文正确
- Esc 关闭查找条
- 仅预览模式：可在渲染结果里查找，替换按钮置灰
"""
# --- 测试入口 shim：本文件在 tests/ 下。便携运行时（python311._pth）不会把 script dir
# 加进 sys.path，所以 tests/ 与仓库根两个都显式挂上，跨用例 import 与根模块 import 才成立 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import sys

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
sys.path.insert(0, HERE)
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


PROBE = r"""
(function(){
  var out = {};
  var ed = document.getElementById('editor');
  function key(k, opts){
    var e = new KeyboardEvent('keydown', Object.assign({key:k, bubbles:true}, opts||{}));
    document.dispatchEvent(e);
  }
  function typeInto(id, val){
    var el = document.getElementById(id);
    el.value = val;
    el.dispatchEvent(new Event('input', {bubbles:true}));
  }

  ed.textContent = 'alpha Beta alpha\n第二行 alpha';
  ed.dispatchEvent(new Event('input', {bubbles:true}));

  /* Ctrl+F：查找条打开、不显示替换行、焦点在查找框 */
  key('f', {ctrlKey:true});
  out.opened = !document.getElementById('findBar').hidden;
  out.replaceHidden = document.getElementById('findReplaceRow').hidden === true;
  out.focusId = document.activeElement && document.activeElement.id;

  typeInto('findInput', 'alpha');
  out.count = document.getElementById('findCount').textContent;
  document.getElementById('findNext').click();
  out.countNext = document.getElementById('findCount').textContent;
  document.getElementById('findPrev').click();
  out.countPrev = document.getElementById('findCount').textContent;

  /* Ctrl+H：展开替换行 */
  key('h', {ctrlKey:true});
  out.replaceShown = document.getElementById('findReplaceRow').hidden === false;
  typeInto('replaceInput', 'X');
  document.getElementById('replaceOne').click();
  out.afterOne = ed.textContent;
  out.countAfterOne = document.getElementById('findCount').textContent;
  document.getElementById('replaceAll').click();
  out.afterAll = ed.textContent;

  key('Escape');
  out.closed = document.getElementById('findBar').hidden;

  /* 仅预览：在渲染结果里查找，替换按钮置灰 */
  var view = document.querySelector('.view-item[data-view="preview"]');
  view.click();
  return new Promise(function(resolve){
    setTimeout(function(){
      key('f', {ctrlKey:true});
      typeInto('findInput', 'Beta');
      out.previewCount = document.getElementById('findCount').textContent;
      out.replaceDisabled = document.getElementById('replaceOne').disabled === true
                         && document.getElementById('replaceAll').disabled === true;
      key('Escape');
      resolve(out);
    }, 700);
  });
})()
"""


def main():
    r = run_expr(PROBE)
    check("Ctrl+F 打开查找条", r.get("opened") is True, str(r))
    check("默认不显示替换行", r.get("replaceHidden") is True, str(r))
    check("焦点落在查找框", r.get("focusId") == "findInput", str(r.get("focusId")))
    check("计数正确（不区分大小写）", r.get("count") == "1/3", str(r.get("count")))
    check("下一个定位 2/3", r.get("countNext") == "2/3", str(r.get("countNext")))
    check("上一个回到 1/3", r.get("countPrev") == "1/3", str(r.get("countPrev")))
    check("Ctrl+H 展开替换行", r.get("replaceShown") is True, str(r))
    check("替换当前只改第一处",
          r.get("afterOne") == "X Beta alpha\n第二行 alpha", repr(r.get("afterOne")))
    check("替换后计数刷新", r.get("countAfterOne") == "1/2", str(r.get("countAfterOne")))
    check("全部替换改完剩余命中",
          r.get("afterAll") == "X Beta X\n第二行 X", repr(r.get("afterAll")))
    check("Esc 关闭查找条", r.get("closed") is True, str(r))
    check("仅预览模式可查找", r.get("previewCount") == "1/1", str(r.get("previewCount")))
    check("仅预览模式替换按钮置灰", r.get("replaceDisabled") is True, str(r))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
