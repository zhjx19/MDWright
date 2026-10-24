# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""列表解析回归测试（v1.11.2 修复项 + 历史行为）：
- 有序/无序混排软换行不吸进同一列表（CommonMark：不同 marker 开新列表）
- 有序列表保留首项起始序号（<ol start=N>）
- 回归：纯列表、嵌套、task、空行分隔、反向混排
从 mdwright.html 提取 /*PARSER_START*/../*PARSER_END*/ 段跑 node。"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "mdwright.html")
JS = os.path.join(HERE, "_tmp_list_parse.js")
RESULTS = []


def check(name, ok, extra=""):
    RESULTS.append((name, ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + extra) if extra else ""))


def main():
    src = open(HTML, encoding="utf-8").read()
    m = re.search(r"/\*PARSER_START\*/(.*?)/\*PARSER_END\*/", src, re.S)
    if not m:
        print("FAIL parser segment not found")
        sys.exit(1)
    harness = m.group(1) + r"""
var CASES = [
  // [name, input, expected] —— 编号接力语义：显示编号=区域内第N个有序项，
  // 输入数字仅是语法标记不参与显示；无序项不占编号；空行/其他块打断即重置。
  // 无序标记方言：+ = 实心(u-solid)、- = 空心(u-hollow)；星号不作列表标记（专注斜体/加粗）。
  ["混排软换行切分(用户例1)", "1. a\n- b\n- c",
   "<ol><li>a</li></ol><ul><li class=\"u-hollow\">b</li><li class=\"u-hollow\">c</li></ul>"],
  ["空行分隔各自成表(用户例2)", "1. a\n\n- b",
   "<ol><li>a</li></ol><ul><li class=\"u-hollow\">b</li></ul>"],
  ["空行后有序从1重计(用户例3)", "1. a\n\n- b\n- c\n\n2. d",
   "<ol><li>a</li></ol><ul><li class=\"u-hollow\">b</li><li class=\"u-hollow\">c</li></ul><ol><li>d</li></ol>"],
  ["接力编号:输入1续2(用户例4a)", "1. a\n- b\n- c\n1. d\n1. e",
   "<ol><li>a</li></ol><ul><li class=\"u-hollow\">b</li><li class=\"u-hollow\">c</li></ul><ol start=\"2\"><li>d</li><li>e</li></ol>"],
  ["接力编号:输入2/3续2(用户例4b)", "1. a\n- b\n- c\n2. d\n3. e",
   "<ol><li>a</li></ol><ul><li class=\"u-hollow\">b</li><li class=\"u-hollow\">c</li></ul><ol start=\"2\"><li>d</li><li>e</li></ol>"],
  ["多段交替接力", "1. a\n- b\n2. c\n+ d\n3. e",
   "<ol><li>a</li></ol><ul><li class=\"u-hollow\">b</li></ul><ol start=\"2\"><li>c</li></ol><ul><li class=\"u-solid\">d</li></ul><ol start=\"3\"><li>e</li></ol>"],
  ["反向混排: 无序后接有序", "- a\n1. b\n2. c",
   "<ul><li class=\"u-hollow\">a</li></ul><ol><li>b</li><li>c</li></ol>"],
  ["纯有序无start属性", "1. a\n2. b\n3. c",
   "<ol><li>a</li><li>b</li><li>c</li></ol>"],
  ["输入数字被无视", "5. e\n6. f",
   "<ol><li>e</li><li>f</li></ol>"],
  ["纯无序-空心", "- a\n- b",
   "<ul><li class=\"u-hollow\">a</li><li class=\"u-hollow\">b</li></ul>"],
  ["纯无序+实心", "+ a\n+ b",
   "<ul><li class=\"u-solid\">a</li><li class=\"u-solid\">b</li></ul>"],
  ["加减混排同表各样式", "+ a\n- b",
   "<ul><li class=\"u-solid\">a</li><li class=\"u-hollow\">b</li></ul>"],
  ["星号不再作列表标记(单行字面)", "* a",
   "<p>* a</p>"],
  ["星号列表旧行为已移除", "* a\n* b",
   "<p><em> a<br></em> b</p>"],
  ["嵌套子列表", "- a\n  - b\n- c",
   "<ul><li class=\"u-hollow\">a<ul><li class=\"u-hollow\">b</li></ul></li><li class=\"u-hollow\">c</li></ul>"],
  ["嵌套有序独立编号", "1. a\n   1. b\n   2. c\n2. d",
   "<ol><li>a<ol><li>b</li><li>c</li></ol></li><li>d</li></ol>"],
  ["task 列表", "- [x] done\n- [ ] todo",
   '<ul><li class="task"><input type="checkbox" disabled checked> done</li><li class="task"><input type="checkbox" disabled> todo</li></ul>'],
  ["三标记混切(星号出列)", "1. a\n- b\n2. c\n* d",
   "<ol><li>a</li></ol><ul><li class=\"u-hollow\">b</li></ul><ol start=\"2\"><li>c</li></ol><p>* d</p>"],
  ["标题打断重置编号", "1. a\n# T\n2. b",
   "<ol><li>a</li></ol><h1>T</h1><ol><li>b</li></ol>"],
  ["列表后段落不吞", "1. a\npara",
   "<ol><li>a</li></ol><p>para</p>"],
];
var fails = 0;
for (var i = 0; i < CASES.length; i++) {
  var got = parseMarkdown(CASES[i][1]);
  var ok = got === CASES[i][2];
  if (!ok) { fails++; }
  console.log((ok ? "PASS " : "FAIL ") + CASES[i][0] +
        (ok ? "" : "\n  want: " + CASES[i][2] + "\n  got : " + got));
}
process.exit(fails ? 1 : 0);
"""
    open(JS, "w", encoding="utf-8").write(harness)
    r = subprocess.run(["node", JS], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=HERE)
    out = (r.stdout or "") + (r.stderr or "")
    lines = [ln for ln in out.splitlines()
             if ln.startswith(("PASS", "FAIL"))]
    for ln in lines:
        check(ln[5:].strip().split("\n")[0], ln.startswith("PASS"))
    if not lines:
        print("FAIL node harness did not run (rc=%s)\n%s"
              % (r.returncode, out.strip()[:500]))
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
        if os.path.exists(JS):
            os.remove(JS)
        sys.exit(1)


if __name__ == "__main__":
    main()