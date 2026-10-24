# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""Callout 提示块解析回归（R1）：
- 五型 NOTE / TIP / IMPORTANT / WARNING / CAUTION
- 可带自定义标题；不带标题时用类型名作标题
- 普通引用块（无 [!TYPE]）行为不变
- 标题与正文都走行内解析（可含强调/行内代码）
- 代码块内的 > [!NOTE] 不生效
前端部分从 mdwright.html 提取 /*PARSER_START*/../*PARSER_END*/ 段跑 node。
"""
import os
import re
import subprocess
import sys

# Windows 控制台默认 GBK，失败详情里可能含 GBK 外字符（如脚注回链 ↩）；
# 统一 stdout 为 UTF-8 + replace，避免「打印」把测试搞崩。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "mdwright.html")
JS = os.path.join(HERE, "_tmp_callout.js")
RESULTS = []


def check(name, ok, extra=""):
    RESULTS.append((name, ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" | " + extra) if extra else ""))


def main():
    src = open(HTML, encoding="utf-8").read()
    m = re.search(r"/\*PARSER_START\*/(.*?)/\*PARSER_END\*/", src, re.S)
    if not m:
        print("FAIL parser segment not found")
        sys.exit(1)
    harness = m.group(1) + r"""
var KINDS = ["NOTE","TIP","IMPORTANT","WARNING","CAUTION"];
var fails = 0;
function report(name, ok, detail){
  if(!ok) fails++;
  console.log((ok?'PASS ':'FAIL ')+name+(ok?'':' | '+detail));
}
/* 五型：容器类名 + 默认标题 = 类型名 */
for (var i=0;i<KINDS.length;i++){
  var k = KINDS[i];
  var out = parseMarkdown("> [!" + k + "]\n> 内容");
  var wantCls = 'callout-' + k.toLowerCase();
  var wantTitle = '<p class="callout-title">' + k + '</p>';
  report('类型 ' + k, out.indexOf(wantCls) >= 0 && out.indexOf(wantTitle) >= 0, out);
}
/* 自定义标题 */
var out2 = parseMarkdown("> [!NOTE] 自定义标题\n> 内容");
report('自定义标题', out2.indexOf('<p class="callout-title">自定义标题</p>') >= 0, out2);
/* 正文多行 */
var out3 = parseMarkdown("> [!TIP]\n> 第一行\n> 第二行");
report('正文多行', out3.indexOf('第一行') >= 0 && out3.indexOf('第二行') >= 0, out3);
/* 普通引用不受影响 */
var out4 = parseMarkdown("> 普通引用");
report('普通引用不变', out4.indexOf('<blockquote>') >= 0 && out4.indexOf('callout') < 0, out4);
/* 标题可含行内强调 */
var out5 = parseMarkdown("> [!WARNING] **粗**标题\n> 内容");
report('标题行内解析', out5.indexOf('<strong>粗</strong>') >= 0, out5);
/* 代码块内的 callout 语法不生效 */
var out6 = parseMarkdown("```\n> [!NOTE]\n> x\n```");
report('代码块内不生效', out6.indexOf('callout') < 0, out6);
process.exit(fails ? 1 : 0);
"""
    open(JS, "w", encoding="utf-8").write(harness)
    r = subprocess.run(["node", JS], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=HERE)
    out = (r.stdout or "") + (r.stderr or "")
    lines = [ln for ln in out.splitlines() if ln.startswith(("PASS", "FAIL"))]
    for ln in lines:
        check(ln[5:].strip().split(" | ")[0], ln.startswith("PASS"))
    if not lines:
        print("FAIL node harness did not run (rc=%s)\n%s" % (r.returncode, out.strip()[:500]))
        if os.path.exists(JS):
            os.remove(JS)
        sys.exit(1)
    fails_detail = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
    if fails_detail:
        print("\n".join(out.splitlines()))
    if os.path.exists(JS):
        os.remove(JS)
    fails = [n for n, ok in RESULTS if not ok]
    print("\n%d/%d passed" % (len(RESULTS) - len(fails), len(RESULTS)))
    if fails:
        print("FAILED:", "; ".join(fails))
        sys.exit(1)


if __name__ == "__main__":
    main()
