# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""方言 → pandoc markdown 预处理回归（R2）：
只做 pandoc 不认的几件事（Callout / 图片宽度 {N} / 图表围栏的 {N} / 花括号上下标 ^{} _{}），
其余原样透传——脚注、定义列表、front matter、行内高亮、^x^ 与 ~x~ 形式的上下标、
公式都是 pandoc 原生能力。
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
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
sys.path.insert(0, HERE)
import md_pandoc  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def prep(s):
    return md_pandoc.prepare_markdown(s)


def main():
    # 1 Callout → 引用块 + 粗体类型名
    out = prep("> [!NOTE]\n> 内容\n")
    check("Callout 转引用块粗体", "> **NOTE**" in out and "[!NOTE]" not in out, out)
    out = prep("> [!WARNING] 自定义标题\n> 内容\n")
    check("Callout 带标题", "> **WARNING** 自定义标题" in out, out)
    out = prep("> 普通引用\n")
    check("普通引用不动", out.strip() == "> 普通引用", out)

    # 2 图片 {N} → pandoc {width=N%}
    out = prep("![图](a.png){30}\n")
    check("图片宽度转 pandoc 属性", "{width=30%}" in out and "{30}" not in out, out)
    out = prep("![图](a.png)\n")
    check("无宽度图片不动", out.strip() == "![图](a.png)", out)
    out = prep("![图](a.png){150}\n")
    check("超 100 钳到 100", "{width=100%}" in out, out)

    # 3 图表围栏：剥掉 {N}，语言保留（pandoc 当普通代码块）
    out = prep("```mermaid {30}\ngraph TD\nA-->B\n```\n")
    check("图表围栏剥宽度", "```mermaid\n" in out and "{30}" not in out, out)
    out = prep("```mermaid\ngraph TD\nA-->B\n```\n")
    check("图表围栏无宽度原样", "```mermaid\n" in out, out)

    # 4 其余语法原样透传（pandoc 原生支持）
    src = "脚注[^a]\n\n[^a]: 说明\n\n==高亮== x^2^\n\n公式 $E=mc^2$\n\n术语\n: 定义\n"
    check("脚注/高亮/上下标/公式/定义列表原样", prep(src) == src, prep(src))

    # 5 代码块里的 Callout 语法与 {30} 不得被改写
    src = "```\n> [!NOTE]\n![图](a.png){30}\n```\n"
    check("代码块内不改写", prep(src) == src, prep(src))

    # 6 front matter 原样（pandoc 读作 metadata）
    src = "---\ntitle: t\n---\n\n正文\n"
    check("front matter 原样", prep(src) == src, prep(src))

    # 7 围栏必须按**同种标记**配对：``` 块里的 ~~~ 不是结束符
    src = "```markdown\n> [!NOTE]\n~~~\n![x](y.png){30}\n```\n"
    out = prep(src)
    check("``` 块内的 ~~~ 不结束围栏",
          "[!NOTE]" in out and "{30}" in out and "**NOTE**" not in out, out)

    # 8 ~~~ 块里的 ``` 同理
    src = "~~~\n> [!NOTE]\n```\n![x](y.png){30}\n~~~\n"
    out = prep(src)
    check("~~~ 块内的 ``` 不结束围栏",
          "[!NOTE]" in out and "{30}" in out, out)

    # 9 花括号上下标 → pandoc 的 ^..^ / ~..~
    out = prep("x^{2} 与 H_{2}O\n")
    check("花括号上标转 pandoc", "x^2^" in out and "^{2}" not in out, out)
    check("花括号下标转 pandoc", "H~2~O" in out and "_{2}" not in out, out)
    out = prep("x^{a b}\n")
    check("含空格的花括号上标转义空格", "x^a\\ b^" in out, out)
    out = prep("见注^{[1]}\n")
    check("编号形上标转 pandoc", "见注^[1]^" in out, out)

    # 10 公式与行内代码里的花括号上下标一律不动（LaTeX 写法不能被改写）
    src = "公式 $e^{i\\pi}+1=0$ 与 $\\sum_{k=1}^{n}k$\n"
    check("行内公式不动", prep(src) == src, prep(src))
    src = "$$\n\\sum_{k=1}^{n} k\n$$\n"
    check("块级公式不动", prep(src) == src, prep(src))
    src = "说明 `x^{1} H_{2}` 原样\n"
    check("行内代码不动", prep(src) == src, prep(src))
    src = "```\nx^{1} H_{2}\n```\n"
    check("围栏内不动", prep(src) == src, prep(src))

    # 11 幂等：转换结果再跑一遍不变
    once = prep("x^{2} H_{2}O 见注^{[1]}\n")
    check("花括号上下标转换幂等", prep(once) == once, prep(once))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
