# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""围栏状态机回归（v2.6.3）：

根因：旧实现用单布尔在 ` ``` ` 与 `~~~` 之间来回翻，`~~~markdown` 里嵌 ` ```r `
示例时两者互相"闭合"，示例正文掉出围栏 -> `$..$` 被公式化、`$` 消失。

覆盖：
- fenceIsOpen：同字符且不短才闭合；异标记在围栏内是普通内容
- splitFenced：分段后可无损拼回原文
- extractMath：```/~~~ 围栏内（含嵌套）的 `$` 原样保留；围栏外的 `$..$` 仍被抽取
- parseMarkdown：```r 围栏里的 `$` 原样进代码块，且带 data-lang=r（可运行）
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
import re
import subprocess

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
HTML = os.path.join(HERE, "mdwright.html")


def extract_fn(src, name):
    i = src.index("function " + name + "(")
    j = src.index("{", i)
    depth = 0
    k = j
    while k < len(src):
        c = src[k]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
        k += 1
    raise ValueError("unbalanced braces in " + name)


def js_cases():
    return r"""
let fails = 0;
function ck(name, cond, detail){ console.log((cond?'PASS ':'FAIL ')+name+(cond?'':' -> '+detail)); if(!cond) fails++; }

/* fenceIsOpen */
let st = fenceIsOpen('~~~markdown', null);            // 开
ck('open ~~~', st && st.ch==='~' && st.n===3, JSON.stringify(st));
st = fenceIsOpen('```r', st);                          // 异标记 -> 仍在围栏内
ck('``` inside ~~~ does not close', !!st, JSON.stringify(st));
st = fenceIsOpen('~~~', st);                           // 同标记 -> 闭
ck('~~~ closes ~~~', st===null, JSON.stringify(st));

/* splitFenced 无损拼回 */
const texts = [
  "a\n~~~\nb\n~~~\nc",
  "```r\nplot(mtcars$wt)\n```",
  "~~~markdown\n```r\nplot(mtcars$wt, mtcars$mpg)\n```\n~~~",
  "no fence at all\nsecond line",
];
texts.forEach(function(t,i){
  const segs = splitFenced(t);
  const back = segs.map(function(s){return s.text;}).join('\n');
  ck('splitFenced roundtrip #'+i, back===t, JSON.stringify(back));
});

/* extractMath */
function contains(p){ return p.indexOf('\uE000M')>=0; }
let m = extractMath('```r\nplot(mtcars$wt, mtcars$mpg)\n```');
ck('$ kept in ``` fence', m.indexOf('mtcars$wt')>=0 && !contains(m), JSON.stringify(m));
m = extractMath('~~~markdown\n```r\nplot(mtcars$wt, mtcars$mpg)\n```\n~~~');
ck('$ kept in nested ~~~/```', m.indexOf('mtcars$wt')>=0 && !contains(m), JSON.stringify(m));
ck('mathStore empty for fenced $', mathStore.length===0, String(mathStore.length));
m = extractMath('inline $x+1$ text');
ck('$..$ outside fence extracted', contains(m) && mathStore.length===1, JSON.stringify(m));

/* parseMarkdown: ```r 里的 $ 原样、且可运行 */
const html = parseMarkdown('```r\nplot(mtcars$wt)\n```', {nums:{},order:[],defs:{}});
ck('parseMarkdown keeps $ in r block', html.indexOf('mtcars$wt')>=0, html.slice(0,200));
ck('parseMarkdown marks data-lang=r', html.indexOf('data-lang="r"')>=0, html.slice(0,200));
ck('parseMarkdown no math span', html.indexOf('md-math')<0, html.slice(0,200));

console.log('JS-FAILS='+fails);
"""


def main():
    src = open(HTML, encoding="utf-8").read()
    parser = re.search(r"/\*PARSER_START\*/(.*?)/\*PARSER_END\*/", src, re.S).group(1)
    extmath = extract_fn(src, "extractMath")
    harness = parser + "\nvar mathStore=[];\n" + extmath + "\n" + js_cases()
    tmp = os.path.join(HERE, "_tmp_fence.js")
    open(tmp, "w", encoding="utf-8").write(harness)
    r = subprocess.run(["node", tmp], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    os.remove(tmp)
    out = (r.stdout or "").rstrip()
    print(out)
    if r.stderr.strip():
        print("STDERR:", r.stderr[:400])
    n_fail = len(re.findall(r"^FAIL", out, re.M)) + (
        0 if re.search(r"^JS-FAILS=0$", out, re.M) else 1)
    n_pass = len(re.findall(r"^PASS ", out, re.M))
    ok = (n_fail == 0 and n_pass >= 12)
    print("%s fence regression (%d pass / %d fail)" % ("PASS" if ok else "FAIL", n_pass, n_fail))
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
