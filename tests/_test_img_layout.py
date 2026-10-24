# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""图片排版三件套（v3.2.0，解析层）：

1. 图片段不吃首行缩进——独占一行的图输出 `<p class="p-img">`；
2. 图片对齐——`{30 c}` / `{c}` / `{l}` / `{r}`，写在段落上（`class="p-img al-x"`），
   图自身保留 `data-al` 供导出链路后续使用；非法组合按 fail-closed 原样留在正文；
3. 多图并排——`@@ begin fill {50|50}` … `@@ end fill`，2~4 栏，比例按权重归一（`fr`），
   栏内图占满栏宽；写坏（未闭合 / 栏数越界 / 栏内非图 / 比例非数字）整段原样显示。

口径：这里只测解析产物（预览正确性）；导出三链路另测。
"""
# --- 测试入口 shim ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT
HTML = os.path.join(HERE, "mdwright.html")
fails = []


def check(name, ok, detail=""):
    print("%-44s %s %s" % (name, "PASS" if ok else "FAIL", detail if not ok else ""))
    if not ok:
        fails.append(name)


HARNESS = r"""
function t(name, src, subs, bans){
  var html;
  try { html = parseMarkdown(src); }
  catch(e){ return {name:name, ok:false, got:'EXCEPTION: '+e.message}; }
  subs = subs || []; bans = bans || [];
  var ok = subs.every(function(s){ return html.indexOf(s) >= 0; })
        && bans.every(function(s){ return html.indexOf(s) < 0; });
  return {name:name, ok:ok, got:html};
}
var cases = [];

/* ── 1. 图片段分类：独占一行的图 → p.p-img ─────────────────── */
cases.push(t('图片段打 p-img 类', '![a](x.png)',
  ['<p class="p-img"><img'], ['class="p-img al-']));
cases.push(t('宽度参数仍生效', '![a](x.png){30}',
  ['class="p-img"', 'style="width:30%"']));
cases.push(t('图文混排不是图片段', '看这张 ![a](x.png)',
  ['<p>看这张 '], ['p-img']));
cases.push(t('链接包图不算图片段', '[![a](x.png)](u.html)',
  ['<a href="u.html"'], ['p-img']));

/* ── 2. 对齐写法 ─────────────────────────────────────────── */
cases.push(t('{30 c} 宽+居中', '![a](x.png){30 c}',
  ['class="p-img al-c"', 'style="width:30%"', 'data-al="c"']));
cases.push(t('{l} 只对齐不改宽', '![a](x.png){l}',
  ['class="p-img al-l"'], ['style="width:']));
cases.push(t('{c} 只对齐不改宽', '![a](x.png){c}',
  ['class="p-img al-c"'], ['style="width:']));
cases.push(t('{r} 右对齐', '![a](x.png){r}', ['class="p-img al-r"']));
cases.push(t('{50 R} 大写也认', '![a](x.png){50 R}',
  ['class="p-img al-r"', 'style="width:50%"']));
cases.push(t('{45 l} 带标题共存', '![a](x.png "t"){45 l}',
  ['class="p-img al-l"', 'title="t"', 'style="width:45%"']));

/* ── 3. fail-closed：参数写错则后缀原样，但图仍要渲染 ────────
   （CHANGELOG v2.0.0 口径：「{0}/非数字不生效且后缀字面保留」——不能因为
     写坏一个参数就把整张图降级成源码） */
cases.push(t('非法对齐字母原样', '![a](x.png){30 x}',
  ['{30 x}', '<img src="x.png"'], ['al-x', 'data-al']));
cases.push(t('两个对齐词原样', '![a](x.png){c r}',
  ['{c r}', '<img src="x.png"'], ['p-img al-']));
cases.push(t('两个数字原样', '![a](x.png){30 40}',
  ['{30 40}', '<img src="x.png"'], ['style="width:']));
cases.push(t('{0} 仍原样（回归）', '![a](x.png){0}',
  ['{0}', '<img src="x.png"'], ['style="width:']));

/* ── 4. 多图并排 ─────────────────────────────────────────── */
function fill2(a, b){
  return '@@ begin fill {50|50}\n' + a + '\n' + b + '\n@@ end fill';
}
cases.push(t('两栏并排', fill2('![a](a.png)', '![b](b.png)'),
  ['<div class="img-fill" style="grid-template-columns:50fr 50fr">',
   '<img src="a.png"', '<img src="b.png"', 'style="width:100%"']));
cases.push(t('三栏按权重', '@@ begin fill {2|1|1}\n![a](a.png)\n![b](b.png)\n![c](c.png)\n@@ end fill',
  ['grid-template-columns:2fr 1fr 1fr', 'src="c.png"']));
cases.push(t('四栏', '@@ begin fill {1|1|1|1}\n![a](a.png)\n![b](b.png)\n![c](c.png)\n![d](d.png)\n@@ end fill',
  ['grid-template-columns:1fr 1fr 1fr 1fr', 'src="d.png"']));
cases.push(t('栏内空行容错', '@@ begin fill {50|50}\n![a](a.png)\n\n![b](b.png)\n@@ end fill',
  ['img-fill', 'src="b.png"']));
cases.push(t('栏数与图数不等原样', '@@ begin fill {50|50}\n![a](a.png)\n![b](b.png)\n![c](c.png)\n@@ end fill',
  ['@@ begin fill {50|50}'], ['img-fill']));
cases.push(t('前后正文不受影响', '前文\n\n' + fill2('![a](a.png)', '![b](b.png)') + '\n\n后文',
  ['<p>前文</p>', 'img-fill', '<p>后文</p>']));

/* ── 5. 多图并排的 fail-closed ───────────────────────────── */
cases.push(t('单栏原样', '@@ begin fill {100}\n![a](a.png)\n@@ end fill',
  ['@@ begin fill {100}'], ['img-fill']));
cases.push(t('五栏原样', '@@ begin fill {1|1|1|1|1}\n![a](a.png)\n![b](b.png)\n![c](c.png)\n![d](d.png)\n![e](e.png)\n@@ end fill',
  ['@@ begin fill {1|1|1|1|1}'], ['img-fill']));
cases.push(t('未闭合原样', '@@ begin fill {50|50}\n![a](a.png)\n![b](b.png)',
  ['@@ begin fill {50|50}'], ['img-fill']));
cases.push(t('栏内是文字原样', '@@ begin fill {50|50}\n文字\n![b](b.png)\n@@ end fill',
  ['@@ begin fill {50|50}'], ['img-fill']));
cases.push(t('比例非数字原样', '@@ begin fill {a|b}\n![a](a.png)\n![b](b.png)\n@@ end fill',
  ['@@ begin fill {a|b}'], ['img-fill']));
cases.push(t('缺比例原样', '@@ begin fill\n![a](a.png)\n![b](b.png)\n@@ end fill',
  ['@@ begin fill'], ['img-fill']));

console.log(JSON.stringify(cases));
"""


def main():
    src = open(HTML, encoding="utf-8").read()
    m = re.search(r"/\*PARSER_START\*/(.*?)/\*PARSER_END\*/", src, re.S)
    if not m:
        check("找到 PARSER 段", False, "mdwright.html 里没有 PARSER_START/END 标记")
        sys.exit(1)
    js = m.group(1) + HARNESS
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        r = subprocess.run(["node", path], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    finally:
        os.unlink(path)
    if r.returncode != 0:
        check("node 跑通解析器 harness", False, (r.stderr or r.stdout)[:800])
        sys.exit(1)
    import json
    cases = json.loads(r.stdout.strip().splitlines()[-1])
    for c in cases:
        check(c["name"], c["ok"], c["got"][:220])
    print("\n%s" % ("ALL PASS" if not fails else "FAILED(%d): %s" % (len(fails), fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
