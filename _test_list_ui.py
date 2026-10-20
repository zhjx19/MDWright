# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""列表编号接力 UI 真实浏览器验证（playwright）：
模拟用户逐行软回车敲入混排列表，断言 preview 实际 DOM（非纯解析器单测）。
- 1. / - / - / 1. / 1. → 1. / · · / 2. 3.（接力，输入数字无视）
- 空行后 2. → 重置显示 1.
端口 18766 有服务则复用（html 每请求读盘，必为新 JS），无则进程内起。"""
import json
import threading
import time
import sys
import os
import socket
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

fails = []


def check(name, cond, detail=""):
    print("%-44s %s %s" % (name, "PASS" if cond else "FAIL", detail))
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

from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto("http://127.0.0.1:18766/?file=")
    pg.wait_for_timeout(700)

    # 确认页面 JS 是新版：parseList 已带 seq 语义（间接验证——旧页面无此行为）
    pg.click("#editor")
    pg.keyboard.type("1. a")
    pg.keyboard.press("Enter")
    pg.keyboard.type("- b")
    pg.keyboard.press("Enter")
    pg.keyboard.type("- c")
    pg.keyboard.press("Enter")
    pg.keyboard.type("1. d")
    pg.keyboard.press("Enter")
    pg.keyboard.type("1. e")
    pg.wait_for_timeout(900)

    struct = pg.eval_on_selector_all(
        "#preview > .pblk > *",
        "els=>els.map(e=>e.tagName.toLowerCase()"
        "+(e.getAttribute('start')?('['+e.getAttribute('start')+']'):'')"
        "+':'+Array.from(e.children).map(li=>li.textContent).join('|'))")
    check("混排软回车: ol(1) ul(2) ol[start=2](2)",
          struct == ["ol:a", "ul:b|c", "ol[2]:d|e"], str(struct))

    # 空行分隔 → 编号重置显示 1.
    pg.keyboard.press("Enter")
    pg.keyboard.press("Enter")
    pg.keyboard.type("2. z")
    pg.wait_for_timeout(900)
    struct2 = pg.eval_on_selector_all(
        "#preview > .pblk > *",
        "els=>els.map(e=>e.tagName.toLowerCase()"
        "+(e.getAttribute('start')?('['+e.getAttribute('start')+']'):'')"
        "+':'+Array.from(e.children).map(li=>li.textContent).join('|'))")
    check("空行后 2. 重置为 1.",
          struct2 == ["ol:a", "ul:b|c", "ol[2]:d|e", "ol:z"], str(struct2))


    check("no page errors", not errors, "; ".join(errors[:2]))
    b.close()

if httpd:
    httpd.shutdown()

print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
sys.exit(1 if fails else 0)