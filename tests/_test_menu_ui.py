# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""菜单栏 / 设置面板 / 导出保存框的浏览器级回归（UI 重构）。

覆盖：
- 工具栏只剩 5 个菜单 + 设置（旧的平铺按钮已收进下拉）
- 菜单点击开合、Esc 关闭、编辑项写入格式标记
- 设置面板 5 个页签可切换，外部工具页显示真实探测结果
- Word 导出：先弹保存框（此处用 stub 拦 fetch），再带着 outPath 发导出请求
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

import json
import os
import sys
import tempfile

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
sys.path.insert(0, HERE)
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


PROBE_MENU = r"""
(function(){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return Array.prototype.slice.call(document.querySelectorAll(s)); }
  var labels = qa('#menuBar .menu-label').map(function(b){return b.textContent.trim();});
  var out = {
    labels: labels,
    settingsBtn: !!q('#btnSettings'),
    // 旧的平铺按钮：不应再直接出现在 header 里（只能在下拉内）
    flatBtns: qa('#toolbar > .tb-group > .tb-btn, #toolbar > .tb-group > .tb-btn').length,
    rightBtns: qa('#toolbar .tb-group.right .tb-btn').map(function(b){return b.textContent.trim();}),
    fmtCount: qa('#fmtBtns .menu-item[data-fmt]').length,
    fmtTotal: qa('#fmtBtns .menu-item').length
  };
  // 打开「编辑」菜单
  var editLabel = qa('#menuBar .menu-label').filter(function(b){return b.textContent.trim()==='编辑';})[0];
  editLabel.click();
  out.openAfterClick = editLabel.getAttribute('aria-expanded');
  out.popVisible = (function(){
    var pop = editLabel.parentNode.querySelector('.menu-pop');
    return getComputedStyle(pop).display !== 'none';
  })();
  // 写入加粗：选中整段文字后点「加粗」，应包裹而不替换
  var ed = document.getElementById('editor');
  ed.focus();
  ed.textContent = 'abc';
  var rng = document.createRange();
  rng.selectNodeContents(ed);
  var sel = window.getSelection();
  sel.removeAllRanges(); sel.addRange(rng);
  var bold = qa('#fmtBtns .menu-item').filter(function(b){return b.getAttribute('data-fmt')==='B';})[0];
  bold.click();
  out.afterBold = ed.textContent;
  // Esc 关闭菜单
  document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
  out.closedByEsc = editLabel.getAttribute('aria-expanded');
  // 打开设置面板
  q('#btnSettings').click();
  out.settingsOpen = !q('#tsOverlay').hidden;
  out.tabs = qa('#setTabs .set-tab').map(function(b){return b.textContent.trim();});
  out.activeTab = (qa('#setTabs .set-tab[data-active="1"]')[0]||{}).textContent;
  // 切到外部工具页
  var toolsTab = qa('#setTabs .set-tab').filter(function(b){return b.getAttribute('data-tab')==='tools';})[0];
  toolsTab.click();
  out.toolsSectionVisible = !q('.set-sec[data-sec="tools"]').hidden;
  out.typesetHidden = q('.set-sec[data-sec="typeset"]').hidden;
  return new Promise(function(resolve){
    setTimeout(function(){
      out.toolPandoc = (q('#setToolPandoc')||{}).textContent || '';
      out.toolBrowser = (q('#setToolBrowser')||{}).textContent || '';
      resolve(out);
    }, 1200);
  });
})()
"""

PROBE_WORD = r"""
(function(){
  var calls = [];
  var orig = window.fetch;
  window.fetch = function(u, o){
    var url = String(u);
    calls.push(url);
    if (url.indexOf('/api/save-dialog') >= 0){
      return Promise.resolve({json:function(){return Promise.resolve(
        {ok:true, path:'D:\\导出测试\\文档.docx'});}});
    }
    if (url.indexOf('/api/export-docx') >= 0){
      return Promise.resolve({json:function(){return Promise.resolve(
        {ok:true, path:'D:\\导出测试\\文档.docx'});}});
    }
    return orig.apply(window, arguments);
  };
  var btn = document.getElementById('btnExportDocx');
  btn.click();
  return new Promise(function(resolve){
    setTimeout(function(){
      var t = document.querySelector('#mdToast');
      resolve({calls: calls, toast: t ? t.textContent : '',
               disabledAtStart: btn.disabled});
    }, 900);
  });
})()
"""


PROBE_DEEPSEEK = r"""
(function(){
  document.getElementById('btnLLM').click();
  return new Promise(function(resolve){
    setTimeout(function(){
      var backend = document.getElementById('llmBackend');
      backend.value = 'deepseek';
      backend.dispatchEvent(new Event('change', {bubbles:true}));
      setTimeout(function(){
        var keyRow = document.getElementById('llmKeyRow');
        var base = document.getElementById('llmBase');
        var model = document.getElementById('llmModel');
        var opts = [].map.call(model.options, function(o){return o.value;});
        resolve({
          panelOpen: !document.getElementById('llmOverlay').hidden,
          keyVisible: getComputedStyle(keyRow).display !== 'none',
          baseValue: base.value,
          basePlaceholder: base.placeholder,
          models: opts,
          selected: model.value
        });
      }, 400);
    }, 900);
  });
})()
"""


PROBE_EDIT = r"""
(function(){
  var out={};
  out.insCode=!!document.getElementById('btnInsCode');
  out.insFoot=!!document.getElementById('btnInsFootnote');
  out.runSel=!!document.getElementById('btnRunSel');
  out.mathIn=!!document.getElementById('btnInsMathIn');
  out.mathBlock=!!document.getElementById('btnInsMathBlock');
  out.insImage=!!document.getElementById('btnInsImage');
  out.light=document.body.classList.contains('light');
  out.baseFont=getComputedStyle(document.documentElement)
      .getPropertyValue('--base-font').trim();
  var ed=document.getElementById('editor');
  var sel=window.getSelection();
  function selectAll(){
    ed.focus();
    var rng=document.createRange(); rng.selectNodeContents(ed);
    sel.removeAllRanges(); sel.addRange(rng);
  }
  ed.textContent='abc'; selectAll();
  document.getElementById('btnInsCode').click();
  out.afterCode=ed.textContent;
  ed.textContent='正文'; selectAll();
  document.getElementById('btnInsFootnote').click();
  out.afterFoot=ed.textContent;
  ed.textContent='E'; selectAll();
  document.getElementById('btnInsMathIn').click();
  out.afterMathIn=ed.textContent;
  ed.textContent='abc'; selectAll();
  document.getElementById('btnInsMathBlock').click();
  out.afterMathBlock=ed.textContent;
  return out;
})()
"""

PROBE_R = r"""
(function(){
  var ed=document.getElementById('editor');
  ed.textContent='```python\nprint("py 输出")\n```\n\n```r\ncat("r 输出")\n```\n';
  ed.dispatchEvent(new Event('input',{bubbles:true}));
  return new Promise(function(resolve){
    setTimeout(function(){
      var btns=[].slice.call(document.querySelectorAll('#preview .run-btn'));
      if(btns.length<2){ resolve({count:btns.length}); return; }
      var pyBtn=btns[0], rBtn=btns[1];
      function outOf(b){ var o=b.parentNode.nextSibling; return (o&&o.textContent)||''; }
      pyBtn.click();
      setTimeout(function(){
        var pyOut=outOf(pyBtn);
        rBtn.click();
        setTimeout(function(){
          resolve({count:btns.length, pyOut:pyOut, rOut:outOf(rBtn),
                   disabled: pyBtn.disabled || rBtn.disabled});
        }, 6000);
      }, 6000);
    }, 1200);
  });
})()
"""


def main():
    # ---- 结构 + 菜单 + 设置 ----
    r = run_expr(PROBE_MENU)
    check("工具栏是 5 个菜单", r.get("labels") == ["文件", "编辑", "视图", "导出", "AI"],
          str(r.get("labels")))
    check("有「设置」按钮", r.get("settingsBtn") is True)
    check("工具栏右侧只有「会话重置 / 设置」两个按钮",
          (r.get("flatBtns") or 0) == 2 and (r.get("rightBtns") or []) == ["⟳ 会话", "设置"],
          str(r.get("rightBtns")))
    check("编辑菜单有 12 个格式项", r.get("fmtCount") == 12, str(r.get("fmtCount")))
    check("编辑菜单共 18 项（含插入类）", r.get("fmtTotal") == 18, str(r.get("fmtTotal")))
    check("点击菜单标签展开", r.get("openAfterClick") == "true" and r.get("popVisible") is True,
          "expanded=%r visible=%r" % (r.get("openAfterClick"), r.get("popVisible")))
    check("加粗项包裹选中文字", r.get("afterBold") == "**abc**", str(r.get("afterBold")))
    check("Esc 关闭菜单", r.get("closedByEsc") == "false", str(r.get("closedByEsc")))
    check("设置面板可打开", r.get("settingsOpen") is True)
    check("设置面板 5 个页签",
          r.get("tabs") == ["外观", "保存", "排版", "分页", "外部工具"], str(r.get("tabs")))
    check("默认落在「外观」页", (r.get("activeTab") or "").strip() == "外观",
          str(r.get("activeTab")))
    check("切到外部工具页只有该节可见",
          r.get("toolsSectionVisible") is True and r.get("typesetHidden") is True,
          "tools=%r typesetHidden=%r" % (r.get("toolsSectionVisible"),
                                         r.get("typesetHidden")))
    check("外部工具页显示 pandoc 探测结果",
          "pandoc" in (r.get("toolPandoc") or "").lower()
          or "Program Files" in (r.get("toolPandoc") or ""),
          r.get("toolPandoc"))
    check("外部工具页显示浏览器探测结果",
          "Edge" in (r.get("toolBrowser") or "") or "Chrome" in (r.get("toolBrowser") or ""),
          r.get("toolBrowser"))

    # ---- AI 面板：DeepSeek 一等后端（R3） ----
    r3 = run_expr(PROBE_DEEPSEEK)
    check("AI 面板可打开", r3.get("panelOpen") is True, str(r3)[:160])
    check("选 DeepSeek 后显示 API Key 行", r3.get("keyVisible") is True, str(r3))
    check("DeepSeek 地址自动填",
          (r3.get("baseValue") or "").startswith("https://api.deepseek.com"),
          str(r3.get("baseValue")))
    check("DeepSeek 模型预设就位",
          r3.get("models") == ["deepseek-chat", "deepseek-reasoner"], str(r3.get("models")))

    # ---- R / Python 代码块：运行按钮与就地输出 ----
    r4 = run_expr(PROBE_R)
    check("R 与 Python 围栏各有一个运行按钮", r4.get("count") == 2, str(r4.get("count")))
    check("Python 块运行回显 stdout", "py 输出" in (r4.get("pyOut") or ""), r4.get("pyOut"))
    check("R 块运行回显 stdout", "r 输出" in (r4.get("rOut") or ""), r4.get("rOut"))
    check("运行结束按钮恢复可用", r4.get("disabled") is False, str(r4))

    # ---- 编辑菜单：插入代码块 / 脚注 / 运行选中；默认亮色与字号 ----
    re_ = run_expr(PROBE_EDIT)
    check("编辑菜单含插入代码块", re_.get("insCode") is True, str(re_))
    check("编辑菜单含插入脚注", re_.get("insFoot") is True, str(re_))
    check("编辑菜单含运行选中代码", re_.get("runSel") is True, str(re_))
    check("编辑菜单含行内/行间公式",
          re_.get("mathIn") is True and re_.get("mathBlock") is True, str(re_))
    check("编辑菜单含插入图片", re_.get("insImage") is True, str(re_))
    check("行内公式写入 $…$", (re_.get("afterMathIn") or "") == "$E$",
          repr(re_.get("afterMathIn")))
    check("行间公式写入 $$ 块",
          "$$\n" in (re_.get("afterMathBlock") or "")
          and (re_.get("afterMathBlock") or "").count("$$") >= 2,
          repr(re_.get("afterMathBlock")))
    check("默认主题为亮色", re_.get("light") is True, str(re_))
    check("正文字号变量已生效", (re_.get("baseFont") or "") == "15px", str(re_.get("baseFont")))
    check("插入代码块写入围栏",
          "```r" in (re_.get("afterCode") or "") and (re_.get("afterCode") or "").count("```") >= 2,
          str(re_.get("afterCode")))
    check("插入脚注写入引用与定义",
          "[^1]" in (re_.get("afterFoot") or "") and "[^1]: " in (re_.get("afterFoot") or ""),
          str(re_.get("afterFoot")))
    check("代码块默认语言默认为 R",
          "```r" in (re_.get("afterCode") or ""), str(re_.get("afterCode")))

    # ---- Word 导出：先选路径再导出 ----
    tmp = tempfile.mkdtemp(prefix="mdmenu-")
    doc = os.path.join(tmp, "菜单测试.md")
    with open(doc, "w", encoding="utf-8") as f:
        f.write("# 菜单测试\n\n正文\n")
    try:
        url = "http://127.0.0.1:18777/?file=" + doc.replace("\\", "/")
        r2 = run_expr(PROBE_WORD, url=url)
        calls = r2.get("calls") or []
        check("Word 导出先调保存对话框",
              any("/api/save-dialog" in c for c in calls), str(calls)[:200])
        check("保存后调导出接口",
              any("/api/export-docx" in c for c in calls), str(calls)[:200])
        check("顺序正确（先保存框后导出）",
              (next((i for i, c in enumerate(calls) if "/api/save-dialog" in c), 99)
               < next((i for i, c in enumerate(calls) if "/api/export-docx" in c), 99)),
              str(calls)[:200])
        check("成功后提示已导出", "已导出" in (r2.get("toast") or ""), r2.get("toast"))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
