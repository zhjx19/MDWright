# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""导出按钮的浏览器级回归（R2）：
- 工具栏出现「Word」「PDF」两个按钮
- 工具探测完成后按 found 决定是否 disable（本机 pandoc/浏览器都在 → 不置灰）
- 未保存文档时点击给出「请先保存」提示
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

import os
import sys

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
sys.path.insert(0, HERE)
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


EXPR = r"""
(function(){
  var d = document.getElementById('btnExportDocx');
  var p = document.getElementById('btnExportPdf');
  return new Promise(function(resolve){
    setTimeout(function(){
      var state = {docx: !!d, pdf: !!p,
                   docxDisabled: d ? d.disabled : null,
                   pdfDisabled: p ? p.disabled : null,
                   docxTitle: d ? d.title : '',
                   pdfTitle: p ? p.title : ''};
      if (p) p.click();
      setTimeout(function(){
        var t = document.querySelector('#mdToast');
        resolve({state: state, toastText: t ? t.textContent : ''});
      }, 800);
    }, 1800);
  });
})()
"""

if __name__ == "__main__":
    res = run_expr(EXPR)
    st = res.get("state") or {}
    check("Word 按钮存在", st.get("docx") is True, str(res))
    check("PDF 按钮存在", st.get("pdf") is True, str(res))
    check("工具可用时两个按钮不置灰",
          st.get("docxDisabled") is False and st.get("pdfDisabled") is False,
          "docx=%r pdf=%r" % (st.get("docxDisabled"), st.get("pdfDisabled")))
    check("未保存文档点击给「先保存」提示", "保存" in (res.get("toastText") or ""),
          res.get("toastText"))
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)
