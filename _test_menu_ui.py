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
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
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
    fmtCount: qa('#fmtBtns .menu-item').length
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


def main():
    # ---- 结构 + 菜单 + 设置 ----
    r = run_expr(PROBE_MENU)
    check("工具栏是 5 个菜单", r.get("labels") == ["文件", "编辑", "视图", "导出", "AI"],
          str(r.get("labels")))
    check("有「设置」按钮", r.get("settingsBtn") is True)
    check("旧的平铺按钮已收进下拉", (r.get("flatBtns") or 0) <= 1, str(r.get("flatBtns")))
    check("编辑菜单有 12 个格式项", r.get("fmtCount") == 12, str(r.get("fmtCount")))
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
