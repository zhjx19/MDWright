# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""行内高亮 / 上标 / 下标回归（R1）：
- ==高亮== → <mark>；^上标^ → <sup>；~下标~ → <sub>
- 删除线 ~~x~~ 优先于下标（不得被拆成两个下标）
- 行内代码段内的 ~ ^ = 不生效（代码段优先）
- 链接 URL 里的 ~ 不被当成下标定界符
- 图床常见写法：H~2~O、x^2^、==重点==
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
JS = os.path.join(HERE, "_tmp_inline_ext.js")
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
var CASES = [
  // [名称, 输入, 必须包含的片段]
  ["高亮", "==重点==", "<mark>重点</mark>"],
  ["高亮含中文标点", "==注意：此处==", "<mark>注意：此处</mark>"],
  ["上标", "x^2^", "x<sup>2</sup>"],
  ["下标", "H~2~O", "H<sub>2</sub>O"],
  ["删除线优先于下标", "~~删~~", "<del>删</del>"],
  ["删除线不被拆成下标", "~~x~~", "<del>x</del>"],
  ["代码段内波浪号不生效", "`a~b`", "<code>a~b</code>"],
  ["代码段内尖号与等号不生效", "`a^b^ ==c==`", "<code>a^b^ ==c==</code>"],
  ["URL 内波浪号不被当下标", "[l](http://a.com/~x/~y)", 'href="http://a.com/~x/~y"'],
  ["单个波浪号不成对时保持字面", "a ~ b", "a ~ b"],
  ["单个尖号不成对时保持字面", "a ^ b", "a ^ b"],
  /* I6：裸 URL（非 markdown 链接）里的两个 ~ 不得被当成下标 */
  ["裸 URL 内波浪号不被当下标", "see https://example.com/~user/~bob here",
   "https://example.com/~user/~bob"],
  ["裸 URL 内下划线不被当斜体", "see https://example.com/~a_b_c here",
   "https://example.com/~a_b_c"]
];
var fails = 0;
for (var i=0;i<CASES.length;i++){
  var out = parseInline(CASES[i][1]);
  var ok = out.indexOf(CASES[i][2]) >= 0;
  if(!ok){ fails++; console.log('FAIL '+CASES[i][0]+' -> '+out+' (expect '+CASES[i][2]+')'); }
  else console.log('PASS '+CASES[i][0]);
}
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
