# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""中英混排自动补空格回归（R5）：
- 汉字紧贴 ASCII 字母/数字 → 中间补一个空格（`按Esc退出` → `按 Esc 退出`）
- 已有空格的、全角标点旁的一律不动；函数幂等，重复渲染不会越补越多
- 行内代码 / 围栏代码块里的内容一个字符都不许动
- Word 导出走的那条（cjkSpaceMarkdown）与预览同一套规则

与其它解析器用例同法：从 mdwright.html 抽真实函数源码跑 node，比的是真函数不是副本。
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

import io
import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
HTML = os.path.join(HERE, "mdwright.html")

try:
    SRC = io.open(HTML, encoding="utf-8").read()
except OSError as e:
    print("SKIP 读不到 mdwright.html：%s" % e)
    sys.exit(77)


def grab(name):
    m = re.search(r"function %s\([\s\S]*?\n\}" % name, SRC)
    if not m:
        raise SystemExit("mdwright.html 里找不到 function %s" % name)
    return m.group(0)


JS = r"""
var PASS = 0, FAIL = 0;
function check(name, cond, detail) {
  if (cond) { PASS++; console.log('PASS ' + name); }
  else { FAIL++; console.log('FAIL ' + name + (detail ? ' :: ' + detail : '')); }
}
""" + grab("cjkSpace") + "\n" + grab("cjkSpaceMarkdown") + r"""

// ---- T1 汉字紧贴英文 ----
check('T1 汉字+英文', cjkSpace('用Python写') === '用 Python 写', cjkSpace('用Python写'));
// ---- T2 汉字紧贴数字 ----
check('T2 汉字+数字', cjkSpace('共10条') === '共 10 条', cjkSpace('共10条'));
// ---- T3 英文紧贴汉字（反向） ----
check('T3 英文+汉字', cjkSpace('Esc退出') === 'Esc 退出', cjkSpace('Esc退出'));
// ---- T4 已有空格不动 ----
check('T4 已有空格不动', cjkSpace('用 Python 写') === '用 Python 写', cjkSpace('用 Python 写'));
// ---- T5 全角标点旁不动 ----
check('T5 全角标点不动', cjkSpace('你好，world。') === '你好，world。', cjkSpace('你好，world。'));
// ---- T6 纯英文/纯中文不动 ----
check('T6a 纯中文不动', cjkSpace('中文内容') === '中文内容');
check('T6b 纯英文不动', cjkSpace('hello world 1.0') === 'hello world 1.0');
// ---- T7 幂等 ----
var once = cjkSpace('v3.0.0版本');
check('T7 幂等', cjkSpace(once) === once, once);
// ---- T8 markdown 级：正文补、行内代码不补 ----
var md = '用Python写`中文abc`代码';
check('T8 正文补/行内代码不补',
      cjkSpaceMarkdown(md) === '用 Python 写`中文abc`代码', cjkSpaceMarkdown(md));
// ---- T9 围栏代码块整体不动 ----
var fence = '前言中文abc\n\n```python\nx = "中文abc"\n```\n\n后用Python';
var out9 = cjkSpaceMarkdown(fence);
check('T9a 围栏内未改', out9.indexOf('x = "中文abc"') > 0, out9);
check('T9b 围栏外已补',
      out9.indexOf('前言中文 abc') === 0 && out9.indexOf('后用 Python') > 0, out9);
// ---- T10 波浪线围栏与多行 ----
var tilde = '中文abc\n~~~\n中文abc\n~~~\n中文abc';
var out10 = cjkSpaceMarkdown(tilde);
check('T10 波浪围栏内未改', out10.split('\n')[2] === '中文abc', out10);

console.log('---');
console.log('TOTAL: ' + (PASS + FAIL) + ', FAIL: ' + FAIL);
if (FAIL > 0) { process.exit(1); }
"""

tmp = os.path.join(tempfile.gettempdir(), "_t_cjk_%d.js" % os.getpid())
io.open(tmp, "w", encoding="utf-8").write(JS)
try:
    r = subprocess.run(["node", tmp], capture_output=True, text=True, encoding="utf-8")
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr)
finally:
    try:
        os.remove(tmp)
    except Exception:
        pass
sys.exit(r.returncode)
