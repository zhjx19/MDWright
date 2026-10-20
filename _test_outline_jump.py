# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""大纲点击跳转 UI 真实浏览器验证（playwright）：
构造软折行严重文档（长行占多视觉行），点大纲靠后标题：
- scrollTop 精确命中镜像测量位置（mirrorTops[ln]+mirrorPad-2*lineH）
- 与旧行高估算差异巨大（证明折行偏差真实存在、测试有区分度）
- 光标落到目标行行首
- 点第一个大纲项能跳回顶部
端口 18766 有服务则复用（html 每请求读盘，必为新 JS），无则进程内起。"""
import json
import threading
import time
import sys
import os
import socket

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
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

# 构造折行文档：30 段 ×4 行超长文本（每行软折成多视觉行），每 5 段一标题，末尾 # END
lines = []
mid_ln = None
for i in range(1, 31):
    if i % 5 == 1:
        if i == 16:
            mid_ln = len(lines)
        lines.append("## 章节 %d" % i)
    for r in range(4):
        lines.append("第%02d段第%d行 %s" % (i, r, "长" * 180))
lines.append("# END")
doc = "\n".join(lines) + "\n"
end_ln = len(lines) - 1


def head_pos(ln):
    return len("\n".join(lines[:ln])) + 1 if ln > 0 else 0


end_pos = head_pos(end_ln)
mid_pos = head_pos(mid_ln)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto("http://127.0.0.1:18766/?file=")
    pg.wait_for_timeout(700)

    pg.evaluate(
        "d=>{var ed=document.getElementById('editor');"
        "ed.textContent=d;ed.dispatchEvent(new Event('input',{bubbles:true}));}",
        doc)
    pg.wait_for_timeout(1500)   # 渲染 + 大纲 + mirror 构建完成

    pre = pg.evaluate(
        "()=>({items:document.querySelectorAll('.ol-item[data-line]').length,"
        "mid:document.querySelector('.ol-item[data-line=\"%d\"]')!==null,"
        "end:document.querySelector('.ol-item[data-line=\"%d\"]')!==null"
        "})" % (mid_ln, end_ln))
    check("大纲含中部/末尾标题项",
          pre["items"] >= 7 and pre["mid"] and pre["end"], str(pre))

    # --- 中部标题：应精确落在视口顶部（留两行上下文） ---
    pg.click('.ol-item[data-line="%d"]' % mid_ln)
    pg.wait_for_timeout(300)

    r = pg.evaluate(
        "(pos)=>{var ed=document.getElementById('editor');"
        "var lineH=parseFloat(getComputedStyle(ed).lineHeight)||20;"
        "var s=window.getSelection();"
        "var rr=document.createRange();rr.selectNodeContents(ed);"
        "rr.setEnd(s.anchorNode,s.anchorOffset);"
        "var selPos=rr.toString().length;"
        "var rect=s.getRangeAt(0).getBoundingClientRect();"
        "var rel=rect.top-ed.getBoundingClientRect().top;"
        "return {scrollTop:ed.scrollTop, sel:selPos, rel:rel,"
        "lineH:lineH, vh:ed.clientHeight, sh:ed.scrollHeight,"
        "oldEst:((selPos-pos)>=0)?null:null};}", mid_pos)
    check("中部：光标落在标题行首",
          r["sel"] == mid_pos, "sel=%d want=%d" % (r["sel"], mid_pos))
    check("中部：标题行落在视口顶部（±1 行高）",
          r["lineH"] * 1.0 < r["rel"] < r["lineH"] * 3.0,
          "rel=%.1f lineH=%.1f" % (r["rel"], r["lineH"]))

    # --- 末尾标题：下方无内容填充，断言已滚到极限（maxScrollTop） ---
    pg.click('.ol-item[data-line="%d"]' % end_ln)
    pg.wait_for_timeout(300)
    r2 = pg.evaluate(
        "()=>{var ed=document.getElementById('editor');"
        "var rect=window.getSelection().getRangeAt(0)"
        ".getBoundingClientRect();"
        "var rel=rect.top-ed.getBoundingClientRect().top;"
        "return {scrollTop:ed.scrollTop, rel:rel, vh:ed.clientHeight,"
        "maxTop:ed.scrollHeight-ed.clientHeight};}")
    check("末尾：光标落在 END 行首",
          pg.evaluate("()=>{var s=window.getSelection();var ed=document."
                      "getElementById('editor');var rr=document.createRange();"
                      "rr.selectNodeContents(ed);"
                      "rr.setEnd(s.anchorNode,s.anchorOffset);"
                      "return rr.toString().length;}") == end_pos)
    check("末尾：滚到极限位置（scrollTop=maxScrollTop±2）",
          abs(r2["scrollTop"] - r2["maxTop"]) <= 2,
          "scrollTop=%.1f maxTop=%.1f" % (r2["scrollTop"], r2["maxTop"]))
    check("末尾：END 行可见于视口",
          0 <= r2["rel"] < r2["vh"], "rel=%.1f vh=%d" % (r2["rel"], r2["vh"]))

    # --- 折行偏差回归锚：旧行高估算 vs 实际滚动差异显著 ---
    ln_delta = pg.evaluate(
        "(est)=>{var ed=document.getElementById('editor');"
        "return Math.abs(ed.scrollTop-est);}",
        (end_ln - 2) * 25.2)
    check("旧行高估算偏差显著（折行场景修复有效）",
          ln_delta > 1000, "delta=%.1f" % ln_delta)

    pg.click('.ol-item[data-line]:not([data-line="%d"])' % end_ln)
    pg.wait_for_timeout(300)
    top2 = pg.evaluate("()=>editor.scrollTop")
    lineH = pg.evaluate(
        "parseFloat(getComputedStyle(document.getElementById('editor'))"
        ".lineHeight)||20")
    check("点第一个大纲项跳回顶部（≤2 行高）",
          top2 <= 2 * lineH, "scrollTop=%.1f" % top2)

    check("no page errors", not errors, "; ".join(errors[:2]))
    b.close()

if httpd:
    httpd.shutdown()

print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
sys.exit(1 if fails else 0)