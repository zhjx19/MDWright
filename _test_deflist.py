# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""定义列表回归（R1）：
- 术语行 + 后续 ": " 定义行 → <dl><dt><dd>
- 一条术语可带多条定义
- 定义的续行缩进 4 空格并入同一条定义
- 定义后紧跟的普通段落必须独立成 <p>（不得被并进 <dd>）
- 行首 ": " 但上一行不是术语 → 按普通段落处理（不凭空造 dl）
前端部分从 markdown-editor.html 提取 /*PARSER_START*/../*PARSER_END*/ 段跑 node。
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
HTML = os.path.join(HERE, "markdown-editor.html")
JS = os.path.join(HERE, "_tmp_deflist.js")
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
var fails = 0;
function report(name, ok, detail){
  if(!ok) fails++;
  console.log((ok?'PASS ':'FAIL ')+name+(ok?'':' | '+detail));
}

var o = parseMarkdown("术语\n: 定义");
report('基本定义列表', o.indexOf('<dl><dt>术语</dt><dd>定义</dd></dl>') >= 0, o);

o = parseMarkdown("术语\n: 定义一\n: 定义二");
report('多条定义', o.indexOf('<dd>定义一</dd><dd>定义二</dd>') >= 0, o);

o = parseMarkdown("术语\n: 第一行\n    第二行");
report('多行定义(缩进续行)', o.indexOf('第二行') >= 0 && o.indexOf('<dd>') >= 0, o);

o = parseMarkdown("术语\n: 定义\n普通段落");
report('定义后接段落不吞', o.indexOf('<p>普通段落</p>') >= 0, o);

o = parseMarkdown(": 单独一行");
report('无术语行时冒号行按段落', o.indexOf('<dl>') < 0, o);

o = parseMarkdown("术语\n: **粗**定义");
report('定义内行内解析', o.indexOf('<strong>粗</strong>') >= 0, o);

o = parseMarkdown("术语\n: 定义\n\n下一段");
report('空行后的段落独立', o.indexOf('<p>下一段</p>') >= 0, o);

/* I3：前置句 + 术语 + 定义（无空行）——不得产出字面 ": " 段落 */
o = parseMarkdown("引导句\n术语\n: 定义");
report('前置句+术语+定义 不产生字面冒号', o.indexOf('<p>: ') < 0, o);
report('前置句+术语 合成定义列表', o.indexOf('<dl>') >= 0, o);

/* M3：多行定义的续行要保留换行（<br>），不能挤成一格 */
o = parseMarkdown("术语\n: 第一行\n    第二行");
report('多行定义保留换行', o.indexOf('第一行<br>第二行') >= 0, o);

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
