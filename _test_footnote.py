# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""脚注解析回归（R1）：
- 编号按【引用首次出现顺序】（用户 2026-10-21 决定）
- 未定义的引用保持字面，不渲染成坏链接
- 定义行剥离出正文，文末生成脚注区
- 定义可多行（续行缩进 4 空格），空行终止
- 引用与定义可分处不同块（文档级语义）
- 代码块内的 [^x] 不参与解析
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
JS = os.path.join(HERE, "_tmp_footnote.js")
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
function doc(src){
  var fx = extractFootnotes(src);
  return { body: parseMarkdown(fx.src, fx), fx: fx, sec: buildFootnoteSection(fx) };
}
var fails = 0;
function report(name, ok, detail){
  if(!ok) fails++;
  console.log((ok?'PASS ':'FAIL ')+name+(ok?'':' | '+detail));
}

/* 1 基本引用+定义 */
var r = doc("正文[^a]。\n\n[^a]: 说明文字");
var ref1 = '<sup class="fn-ref"><a href="#fn-1" id="fnref-1">1</a></sup>';
report('基本引用+定义', r.body.indexOf(ref1) >= 0 && r.sec.indexOf('说明文字') >= 0,
       'body=' + r.body + ' sec=' + r.sec);

/* 2 编号按引用序（定义顺序相反） */
r = doc("甲[^b]乙[^a]\n\n[^a]: A\n[^b]: B");
var refs = (r.body.match(/fnref-(\d+)/g)||[]).map(function(s){return s.replace('fnref-','');});
report('编号按引用序', refs.join(',') === '1,2', 'refs=' + refs.join(','));
report('定义内容对应编号', r.sec.indexOf('B') >= 0 && r.sec.indexOf('A') >= 0, r.sec);

/* 3 未定义引用保持字面 */
r = doc("看这个[^missing]就行");
report('未定义引用保持字面', r.body.indexOf('[^missing]') >= 0 && r.body.indexOf('fn-ref') < 0, r.body);

/* 4 定义行不进正文 */
r = doc("正文\n\n[^a]: 说明");
report('定义行不进正文', r.body.indexOf('[^a]:') < 0, r.body);

/* 5 多行定义 */
r = doc("正文[^a]\n\n[^a]: 第一行\n    第二行");
report('多行定义', r.sec.indexOf('第二行') >= 0, r.sec);

/* 6 代码块内的引用不生效 */
r = doc("```\n[^a]\n```\n\n[^a]: 说明");
report('代码块内引用不生效', r.body.indexOf('[^a]') >= 0, r.body);

/* 7 重复引用同一标签共用编号 */
r = doc("x[^a] y[^a]\n\n[^a]: 说明");
var nums = (r.body.match(/fnref-(\d+)/g)||[]);
report('重复引用共用编号', nums.length===2 && nums[0]===nums[1], nums.join(','));

/* 8 无脚注的文档不产生脚注区（不得凭空插入空 section） */
r = doc("只有正文");
report('无脚注不生成脚注区', r.sec === '', r.sec);

/* I4：剥离定义行必须保持行数不变（行号是分屏联动的锚点基准） */
var src9 = "正文[^a]\n\n[^a]: 说明\n    续行\n\n后文";
var fx9 = extractFootnotes(src9);
report('剥离后行数不变(I4)', fx9.src.split('\n').length === src9.split('\n').length,
       'in=' + src9.split('\n').length + ' out=' + fx9.src.split('\n').length);

/* M5：代码块里的 [^a] 不算引用——不得因此生成一条没人引用的脚注 */
var r9 = doc("```\n[^a]\n```\n\n[^a]: 定义");
report('代码块内引用不产生脚注条目(M5)', r9.fx.order.length === 0,
       'order=' + JSON.stringify(r9.fx.order));

/* M3：脚注正文的续行保留换行 */
var r10 = doc("正文[^a]\n\n[^a]: 第一行\n    第二行");
report('脚注续行保留换行(M3)', r10.sec.indexOf('第一行<br>第二行') >= 0, r10.sec);

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
