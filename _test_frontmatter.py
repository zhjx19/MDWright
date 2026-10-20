# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""YAML front matter 回归（R1）：
- 仅文档第一行是 --- 时生效，到下一个 --- / ... 为止；剥离出正文
- 极简子集：嵌套 map、列表、标量（字符串去引号 / 数字 / 布尔 / null）
- 未闭合、非法 YAML、非首行触发 → 一律 meta=null 且正文完整（fail-closed，不吞内容）
- 重复键视为非法
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
JS = os.path.join(HERE, "_tmp_frontmatter.js")
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
function rep(name, ok, detail){ if(!ok)fails++; console.log((ok?'PASS ':'FAIL ')+name+(ok?'':' | '+detail)); }

/* 1 基本解析与剥离 */
var r = extractFrontMatter("---\ntitle: 我的文档\nauthor: zhang\n---\n\n正文");
rep('front matter 剥离', r.src.indexOf('---') < 0 && r.src.indexOf('正文') >= 0, JSON.stringify(r));
rep('title 解析', r.meta && r.meta.title === '我的文档', JSON.stringify(r.meta));
rep('author 解析', r.meta && r.meta.author === 'zhang', JSON.stringify(r.meta));

/* 2 嵌套 map 与列表 */
r = extractFrontMatter("---\ntags:\n  - a\n  - b\nmeta:\n  k: v\n---\n正文");
rep('列表解析', r.meta && Array.isArray(r.meta.tags) && r.meta.tags.join(',') === 'a,b', JSON.stringify(r.meta));
rep('嵌套 map 解析', r.meta && r.meta.meta && r.meta.meta.k === 'v', JSON.stringify(r.meta));

/* 3 标量类型 */
r = extractFrontMatter("---\nn: 42\nok: true\nnil: ~\ns: \"引号值\"\n---\n正文");
rep('数字/布尔/空/引号', r.meta && r.meta.n === 42 && r.meta.ok === true && r.meta.nil === null && r.meta.s === '引号值', JSON.stringify(r.meta));

/* 4 未闭合 → 当普通内容 */
r = extractFrontMatter("---\ntitle: x\n正文");
rep('未闭合不吞内容', r.meta === null && r.src.indexOf('title: x') >= 0, JSON.stringify(r));

/* 5 非法 YAML → meta=null 但正文完整 */
r = extractFrontMatter("---\n这不是 yaml\n---\n正文");
rep('非法 YAML 降级', r.meta === null && r.src.indexOf('正文') >= 0, JSON.stringify(r));

/* 6 非首行的 --- 不触发 */
r = extractFrontMatter("正文\n\n---\n\n后文");
rep('非首行不触发', r.meta === null && r.src.indexOf('---') >= 0, JSON.stringify(r));

/* 7 空 front matter（只有两行 ---） */
r = extractFrontMatter("---\n---\n正文");
rep('空 front matter 不崩', r.meta !== null && r.src.indexOf('正文') >= 0, JSON.stringify(r));

/* 8 重复键视为非法 */
r = extractFrontMatter("---\na: 1\na: 2\n---\n正文");
rep('重复键降级', r.meta === null && r.src.indexOf('正文') >= 0, JSON.stringify(r));

/* 9 以 ... 结束同样有效 */
r = extractFrontMatter("---\ntitle: t\n...\n正文");
rep('以 ... 结束', r.meta && r.meta.title === 't' && r.src.indexOf('正文') >= 0, JSON.stringify(r));

/* 10 I4：剥离 front matter 必须保持行数不变（行号是分屏联动锚点基准） */
var s10 = "---\ntitle: t\nauthor: a\n---\n\n正文\n";
var r10 = extractFrontMatter(s10);
rep('剥离后行数不变(I4)', r10.src.split('\n').length === s10.split('\n').length,
    'in=' + s10.split('\n').length + ' out=' + r10.src.split('\n').length);

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
