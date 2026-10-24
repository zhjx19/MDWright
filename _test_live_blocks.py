# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""即时渲染的块映射单测（v2.6.1）：

把 mdwright.html 里的 splitBlocks / splitBlocksRaw 抽出来跑 node，
验证"预览块序号 i ↔ 原文区间 i"这条铁律：

- splitBlocks(text).join('\\n') === text          （切块是原文的精确分区）
- splitBlocksRaw(text) 各区间切片按 '\\n' 拼回 === text
- 两者块数一致
- 第 i 个原文区间 === splitBlocks(text)[i]        （逐块对齐，才是安全拼接的前提）

边界：空文档、首行即标题、尾随换行、围栏内 # 不切、多块、连续空行。
"""
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "mdwright.html")


def extract_fn(src, name):
    """按大括号配对抽出一个 function 定义（这两个函数体内只有成对的 {1,2} 正则，安全）。"""
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


CASES = [
    "para1\n\n# A\npara2",
    "# A\npara2",
    "",
    "para1\n",
    "a\n```\n# not heading\n```\n# real",
    "# A\n## B\n### C",
    "x\n# A\ny\n# B\nz",
    "***\n\n- a\n- b\n",
    "para\n\n\n\n# H\nbody",
    "只有一段没有标题的正文\n第二行\n",
    "~~~markdown\n```r\n# not heading\nplot(mtcars$wt)\n```\n~~~\n# real\nbody",
]


def main():
    src = open(HTML, encoding="utf-8").read()
    fns = (extract_fn(src, "fenceMarker") + "\n" +
           extract_fn(src, "fenceIsOpen") + "\n" +
           extract_fn(src, "splitBlocks") + "\n" +
           extract_fn(src, "splitBlocksRaw"))
    cases_js = ",\n".join('"%s"' % "".join(
        "\\n" if ch == "\n" else ("\\" + ch if ch in '"\\' else ch) for ch in c)
        for c in CASES)
    harness = fns + r"""
const CASES = [
""" + cases_js + r"""
];
let fails = 0;
for (const t of CASES) {
  const blocks = splitBlocks(t);
  const ranges = splitBlocksRaw(t);
  const label = JSON.stringify(t).slice(0, 40);

  if (blocks.join('\n') !== t) {
    console.log('FAIL partition ' + label); fails++; continue;
  }
  const rebuilt = ranges.map(r => t.slice(r.start, r.end)).join('\n');
  if (rebuilt !== t) {
    console.log('FAIL rebuild ' + label + ' -> ' + JSON.stringify(rebuilt)); fails++; continue;
  }
  if (ranges.length !== blocks.length) {
    console.log('FAIL count ' + label + ' ' + ranges.length + '!=' + blocks.length); fails++; continue;
  }
  let aligned = true;
  for (let i = 0; i < blocks.length; i++) {
    if (t.slice(ranges[i].start, ranges[i].end) !== blocks[i]) {
      console.log('FAIL align ' + label + ' block#' + i); aligned = false; break;
    }
  }
  if (!aligned) { fails++; continue; }
  console.log('PASS ' + label + '  blocks=' + blocks.length);
}
console.log('JS-FAILS=' + fails);
"""
    tmp = os.path.join(HERE, "_tmp_live_blocks.js")
    open(tmp, "w", encoding="utf-8").write(harness)
    r = subprocess.run(["node", tmp], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    os.remove(tmp)
    out = (r.stdout or "").rstrip()
    print(out)
    if r.stderr.strip():
        print("STDERR:", r.stderr[:300])
    n_fail = len(re.findall(r"^FAIL", out, re.M)) + (
        0 if re.search(r"^JS-FAILS=0$", out, re.M) else 1)
    n_pass = len(re.findall(r"^PASS ", out, re.M))
    ok = (n_fail == 0 and n_pass == len(CASES))
    print("%s live block-map (%d pass / %d fail)" % ("PASS" if ok else "FAIL", n_pass, n_fail))
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
