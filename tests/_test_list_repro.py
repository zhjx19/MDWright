# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""用户原始输入完整复现（v1.11.3 验证）：
截图场景逐行软回车敲入（含中文/反斜杠/引号），断言 preview 实际 DOM。
- 顶格 - 混排：1. / · · / 2.（接力）
- 缩进 - 嵌套：1. > 嵌套 · ·，后续 2. 接力
- 文首正常 ol 与后文互不干扰"""
# --- 测试入口 shim：本文件在 tests/ 下。便携运行时（python311._pth）不会把 script dir
# 加进 sys.path，所以 tests/ 与仓库根两个都显式挂上，跨用例 import 与根模块 import 才成立 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import threading
import time
import sys
import os
import socket

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
sys.path.insert(0, HERE)

fails = []


def check(name, cond, detail=""):
    print("%-40s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def port_in_use():
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", 18766)) == 0
    finally:
        s.close()


httpd = None
if not port_in_use():
    sys.argv = ["md_server.py"]
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", 18766),
                                     md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)

try:
    from playwright.sync_api import sync_playwright  # noqa: E402
except ImportError:
    # 没装 playwright 不算代码坏：这是缺一件可选开发工具。返回 77，run_all 记为 SKIP。
    print("SKIP 需要 playwright：pip install playwright && python -m playwright install chromium")
    sys.exit(77)

USER_TEXT = "\n".join([
    "你没有说你的具体场景，大概可能有两种：",
    "1. AI录音笔已经转录好A\\B\\C...角的文本；",
    "2. 整段录音扔给某个agent。",
    "",
    "一种是誊抄、替换加扩写，一种是转写、替换加扩写，有相似部分我就不拆分了，一并说。要准备的工作：",
    "",
    "1. 拿到一份已经转写好的文本，分A\\B\\C...角，让llm帮你在这份原始文本上\"检出及上报\"以下几点：",
    "- 第一次出现某角色的行数或原句（方便你直接定位）；",
    "- 总共出现过多少位角色。",
    "2. ",
])

NESTED_TEXT = "\n".join([
    "1. 拿到一份已经转写好的文本：",
    "   - 第一次出现某角色的行数或原句；",
    "   - 总共出现过多少位角色。",
    "2. 继续",
])

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto("http://127.0.0.1:18766/?file=")
    pg.wait_for_timeout(700)

    # 场景1：用户截图原文（顶格 - 混排软回车）
    pg.click("#editor")
    for ln in USER_TEXT.split("\n"):
        pg.keyboard.type(ln)
        pg.keyboard.press("Enter")
    pg.wait_for_timeout(1000)
    struct = pg.eval_on_selector_all(
        "#preview .pblk ol, #preview .pblk ul",
        "els=>els.map(e=>e.tagName.toLowerCase()"
        "+(e.getAttribute('start')?('['+e.getAttribute('start')+']'):'')"
        "+':'+Array.from(e.children).map(li=>li.textContent).join('|'))")
    # 期望：文首 ol(2项)；工作区 ol(1项拿到..) + ul(2项··) + ol[2](空)
    want = ["ol:AI录音笔已经转录好A\\B\\C...角的文本；|整段录音扔给某个agent。",
            "ol:拿到一份已经转写好的文本，分A\\B\\C...角，让llm帮你在这份原始文本上\"检出及上报\"以下几点：",
            "ul:第一次出现某角色的行数或原句（方便你直接定位）；|总共出现过多少位角色。",
            "ol[2]:"]
    check("用户原文: 混排渲染 ol/ul/ol[2]", struct == want, str(struct))

    # 场景2：缩进 - 嵌套（用户截图左上打勾那份）
    pg.keyboard.press("Control+a")
    for ln in NESTED_TEXT.split("\n"):
        pg.keyboard.type(ln)
        pg.keyboard.press("Enter")
    pg.wait_for_timeout(1000)
    struct2 = pg.eval_on_selector_all(
        "#preview .pblk ol, #preview .pblk ul",
        "els=>els.map(e=>e.tagName.toLowerCase()"
        "+(e.getAttribute('start')?('['+e.getAttribute('start')+']'):'')"
        "+':'+Array.from(e.children).map(li=>li.textContent).join('|'))")
    # 期望：顶层 1 个 ol 两项；嵌套 ul 在第一个 li 内（querySelectorAll
    # 会把嵌套 ul 一并列出，故共 2 个元素，顺序 ol 在前）
    want2 = ["ol:拿到一份已经转写好的文本：第一次出现某角色的行数或原句；总共出现过多少位角色。|继续",
             "ul:第一次出现某角色的行数或原句；|总共出现过多少位角色。"]
    check("缩进嵌套: 顶层 ol 两项 + 嵌套 ul",
          struct2 == want2, str(struct2))
    nested = pg.eval_on_selector(
        "#preview .pblk ol > li:first-child > ul",
        "el => Array.from(el.children).map(li=>li.textContent).join('|')")
    check("缩进嵌套: 子项为 ul 圆点",
          nested == "第一次出现某角色的行数或原句；|总共出现过多少位角色。",
          str(nested))

    check("no page errors", not errors, "; ".join(errors[:2]))
    b.close()

if httpd:
    httpd.shutdown()

print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
sys.exit(1 if fails else 0)