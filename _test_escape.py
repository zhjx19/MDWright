# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""反斜杠转义测试（v2.0.0）：
- \\X（X 为 ASCII 标点）→ 字面 X，行内语法不再生效（\\!\\[..\\](..) 不再变成真 <a>）
- 代码段内反斜杠保持字面（CommonMark：代码段优先于转义）
- 转义经 escapeHtml 还原（\\< → &lt;，不产生真标签）
- 无反斜杠的正常图片/强调完全不受影响（回归）
前端部分从 markdown-editor.html 提取 /*PARSER_START*/../*PARSER_END*/ 段跑 node。
"""
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "markdown-editor.html")


def js_part():
    src = open(HTML, encoding="utf-8").read()
    m = re.search(r"/\*PARSER_START\*/(.*?)/\*PARSER_END\*/", src, re.S)
    assert m, "PARSER segment not found"
    harness = m.group(1) + r"""
const cases = [
  // [输入, 期望输出或 null（null=断言无 <a>/<img>/反斜杠残留）]
  ["\\!\\[a\\](x.png)", "![a](x.png)"],
  ["\\!\\[a 40%\\](x.png)\\{40\\}", "![a 40%](x.png){40}"],
  ["\\*x\\*", "*x*"],
  ["\\_x\\_", "_x_"],
  ["\\<b\\>", "&lt;b&gt;"],
  ["\\\\", "\\"],
  ["`a\\*b`", "<code>a\\*b</code>"],                    // 代码段内转义符保持字面
  ["[\\*x\\*](u)", '<a href="u" target="_blank" rel="noopener">*x*</a>'],
  ["![a](x.png)", '<img src="x.png" alt="a">'],         // 无反斜杠回归：真图片照常
  ["**b**", "<strong>b</strong>"],                      // 无反斜杠回归：加粗照常
];
let fails = 0;
for (const [input, expect] of cases) {
  const out = parseInline(input);
  if (out === expect) { console.log('PASS ' + JSON.stringify(input)); continue; }
  console.log('FAIL ' + JSON.stringify(input) + ' -> ' + out + ' (expect ' + expect + ')'); fails++;
}
/* 端到端：指南示例整行走块解析，不得产生链接/图片/反斜杠残留 */
const md = parseMarkdown("\\!\\[内嵌示例图\\](MDEditor 使用指南.assets/内嵌示例图.png)\n");
if (md.indexOf('<a ') >= 0 || md.indexOf('<img') >= 0 || md.indexOf('\\') >= 0
    || md.indexOf('![内嵌示例图](MDEditor 使用指南.assets/内嵌示例图.png)') < 0) {
  console.log('FAIL md guide-style -> ' + md.slice(0, 200)); fails++;
} else console.log('PASS md guide-style literal');
console.log('JS-FAILS=' + fails);
"""
    tmp = os.path.join(HERE, "_tmp_escape.js")
    open(tmp, "w", encoding="utf-8").write(harness)
    r = subprocess.run(["node", tmp], capture_output=True, text=True)
    os.remove(tmp)
    out = r.stdout
    print(out.rstrip())
    if r.stderr.strip():
        print("STDERR:", r.stderr[:200])
    n_fail = len(re.findall(r"^FAIL", out, re.M)) + (
        0 if re.search(r"^JS-FAILS=0$", out, re.M) else 1)
    n_pass = len(re.findall(r"^PASS ", out, re.M))
    print("%s js escape cases (%d pass / %d fail)" % (
        "PASS" if (n_fail == 0 and n_pass >= 10) else "FAIL", n_pass, n_fail))
    return n_fail == 0 and n_pass >= 10


if __name__ == "__main__":
    ok = js_part()
    raise SystemExit(0 if ok else 1)
