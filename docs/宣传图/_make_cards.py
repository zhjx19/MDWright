# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""宣传图（1600×900 卡片）生成器 —— 与 README 截图共用同一条“真实界面”流水线。

为什么要有它：`docs/宣传图/*.png` 是介绍文档 `docs/MDWright-介绍.md` 的配图。
早期那批卡片拍的是更名前的 MDEditor 界面（旧工具栏、旧配色），界面一改就全过期，
而没人记得当初是怎么排的版。这里把排版、文案、取图全部写成代码：

    起本地后端 → 无头 Edge 驱动真实界面取裸图 → 拼进 HTML 卡片 → 逐张截图落盘

用法（仓库根目录）：

    python\\python.exe docs\\宣传图\\_make_cards.py            # 全部重出
    python\\python.exe docs\\宣传图\\_make_cards.py 03 06      # 只重出编号含 03 / 06 的

卡片是 HTML 排的，改文案/换图都只改这个脚本；纯文字卡（封面、收尾）不依赖截图。
"""
import base64
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))          # docs/宣传图
DOCS = os.path.dirname(HERE)                               # docs
ROOT = os.path.dirname(DOCS)
SHOTS = os.path.join(DOCS, "screenshots")

sys.path.insert(0, SHOTS)
sys.path.insert(0, ROOT)

import _make_screenshots as ms                             # noqa: E402
from PIL import Image                                      # noqa: E402

CARD_W, CARD_H = 1600, 900

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#12151c}
body{font-family:"Microsoft YaHei UI","Microsoft YaHei","PingFang SC",sans-serif;
     -webkit-font-smoothing:antialiased;color:#e8eaf0}
.card{width:1600px;height:900px;position:relative;overflow:hidden;
      background:radial-gradient(1300px 640px at 50% -10%,#1c2231 0%,#14171f 55%,#11141a 100%)}
/* 特性卡：标题 + 圆角面板里的真实界面 */
.feat h2{position:absolute;left:0;right:0;top:44px;text-align:center;
         font-size:40px;font-weight:700;letter-spacing:.5px;color:#eef1f7}
.feat .hint{position:absolute;left:0;right:0;top:98px;text-align:center;
            font-size:22px;color:#94a1b8}
.feat .panel{position:absolute;left:160px;top:146px;width:1280px;height:720px;
             border-radius:18px;overflow:hidden;background:#1a1e26;
             border:1px solid rgba(255,255,255,.09);
             box-shadow:0 34px 90px rgba(0,0,0,.55)}
.feat .panel img{display:block;width:1280px;height:720px}
.feat .pages{display:flex;align-items:center;justify-content:center;gap:56px;height:100%}
.feat .pages img{width:auto;height:640px;border-radius:2px;
                 box-shadow:0 18px 44px rgba(0,0,0,.45)}
/* 封面 */
.hero{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0}
.hero .mark{font-size:150px;font-weight:800;letter-spacing:2px;
            background:linear-gradient(92deg,#8ab4f8 0%,#a68cf5 52%,#c58af9 100%);
            -webkit-background-clip:text;background-clip:text;color:transparent;
            line-height:1.1;padding-top:24px}
.hero .sub{margin-top:26px;font-size:34px;color:#cfd6e4;letter-spacing:1px}
.hero .sub2{margin-top:14px;font-size:24px;color:#8d99b0;letter-spacing:.5px}
.hero .chips{display:flex;gap:18px;margin-top:52px}
.hero .chips span{font-size:24px;color:#cfd6e4;padding:13px 26px;border-radius:999px;
                  border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.03)}
/* 收尾 */
.outro h1{position:absolute;left:0;right:0;top:148px;text-align:center;
          font-size:58px;font-weight:800;letter-spacing:1px}
.outro .row{position:absolute;left:0;right:0;display:flex;justify-content:center;gap:28px}
.outro .row.r1{top:300px}
.outro .row.r2{top:492px}
.outro .box{width:392px;padding:26px 30px;border-radius:16px;
            background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.1)}
.outro .box b{display:block;font-size:26px;color:#8ab4f8;font-weight:700;margin-bottom:12px}
.outro .box p{font-size:20px;line-height:1.6;color:#c2cadb}
.outro .foot{position:absolute;left:0;right:0;bottom:96px;text-align:center;
             font-size:24px;color:#8d99b0}
.outro .foot em{font-style:normal;
                background:linear-gradient(92deg,#8ab4f8,#c58af9);
                -webkit-background-clip:text;background-clip:text;color:transparent}
"""


# ---------------------------------------------------------------- 卡片定义
def b64(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


def feat(title, hint, img_html):
    hint_html = '<div class="hint">%s</div>' % hint if hint else ""
    top = "146px" if not hint else "146px"
    return ('<section class="card feat"><h2>%s</h2>%s'
            '<div class="panel" style="top:%s">%s</div></section>'
            % (title, hint_html, top, img_html))


def hero():
    return """<section class="card hero">
  <div class="mark">MDWright</div>
  <div class="sub">Windows 上的单机 Markdown 写作台</div>
  <div class="sub2">写作 · 排版 · 分页导出，全部在本机完成，断网照常用</div>
  <div class="chips"><span>全部离线</span><span>即时渲染</span><span>选区批注</span>
  <span>代码块可运行</span><span>分页 · Word · PDF</span></div>
</section>"""


def outro():
    return """<section class="card outro">
  <h1>像传统应用一样使用</h1>
  <div class="row r1">
    <div class="box"><b>① 双击即开</b><p>双击 .md 文件或桌面图标，用系统浏览器打开编辑界面，也可切内嵌窗口</p></div>
    <div class="box"><b>② 用完全退</b><p>关掉所有页面后本地服务自动退出，不常驻、不留后台进程</p></div>
    <div class="box"><b>③ 全部离线</b><p>KaTeX、Paged.js 与四种图表引擎随包内置，断网不影响任何功能</p></div>
  </div>
  <div class="row r2">
    <div class="box"><b>图片自动归档</b><p>粘贴即存入「文档名.assets/」，引用自动改写，整目录拷走即可用</p></div>
    <div class="box"><b>版权透明</b><p>内置「版权与开源组件声明」，KaTeX / Paged.js / Python 许可随附</p></div>
  </div>
  <div class="foot">本工具由 <em>AI 辅助生成</em> · 写作现场，永不丢稿</div>
</section>"""


def build_html(raw):
    """把裸图拼成卡片页；图片内联成 data URI，页面自包含、不依赖任何外部路径。"""
    def img(name):
        return '<img src="%s" alt="">' % b64(os.path.join(raw, name))

    paged = '<div class="pages">%s%s</div>' % (img("_raw_page1.png"), img("_raw_page2.png"))
    cards = [
        ("01-标题卡", hero()),
        ("02-写作渲染", feat("左边写，右边看",
                            "常用语法即写即见，公式与表格离线渲染",
                            img("_raw_writing.png"))),
        ("03-即时渲染", feat("即时渲染：点中一段，就地改源码",
                            "预览即编辑面：点中的那一段展开成源码框，改完自动重排",
                            img("_raw_live.png"))),
        ("04-图表引擎", feat("图表写在围栏里就出图",
                            "Mermaid / Graphviz / Vega-Lite 随包内置，不联网",
                            img("_raw_diagrams.png"))),
        ("05-代码运行", feat("代码块直接跑，输出留在原处",
                            "带 python / r 标记的围栏自带「▶ 运行」，用的是随包运行时",
                            img("_raw_code.png"))),
        ("06-分页导出", feat("导出就是成品：目录、页码、纸张",
                            "Paged.js 组版，浏览器里 Ctrl+P 直接出 PDF",
                            paged)),
        ("07-收尾", outro()),
    ]
    body = "\n".join('<div data-name="%s">%s</div>' % (n, h) for n, h in cards)
    html = ("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<style>%s</style></head><body>%s</body></html>" % (CSS, body))
    return html, cards


# ---------------------------------------------------------------- 取裸图 + 截图
def shoot_raws():
    """跑一遍 README 截图流水线，留下裸图（卡片用），同时顺手刷新 README 截图。"""
    raw = tempfile.mkdtemp(prefix="mdw-cards-")
    ms.RAW_DIR = raw
    srv = ms.ensure_server()
    br = None
    try:
        br = ms.Browser(ms.find_browser())
        for fn in (ms.shot_writing, ms.shot_code, ms.shot_live,
                   ms.shot_diagrams, ms.shot_paged):
            fn(br)
    finally:
        if br:
            br.close()
        if srv is not None:
            try:
                srv.terminate()
            except Exception:
                pass
    return raw


def capture(html_path, cards, out_dir, want=frozenset()):
    """逐张滚到视口再截：CDP 的 clip 在本机 Edge 上不裁切，整页一次拍又会超尺寸。"""
    tmp = tempfile.mkdtemp(prefix="mdw-card-shot-")
    br = ms.Browser(ms.find_browser(), width=CARD_W, height=CARD_H, scale=2)
    made = []
    try:
        br.goto("file:///" + html_path.replace("\\", "/"))
        br.wait("document.readyState==='complete'", what="卡片页加载")
        br.wait("(function(){var a=document.images;for(var i=0;i<a.length;i++)"
                "{if(!a[i].complete)return false;}return true;})()", timeout=60,
                what="卡片内联图解码")
        br.settle(0.4)
        for i, (name, _html) in enumerate(cards):
            if want and not any(w in name for w in want):
                continue
            br.js("window.scrollTo(0,%d)" % (i * CARD_H))
            br.settle(0.25)
            p = br.shot(os.path.join(tmp, "_card%02d.png" % i))
            Image.open(p).convert("RGB").resize((CARD_W, CARD_H), Image.LANCZOS).save(
                os.path.join(out_dir, name + ".png"), "PNG", optimize=True)
            made.append(name + ".png")
    finally:
        br.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return made


def clean_raws():
    """shot_* 直接调用绕过了 _make_screenshots.main() 的清理，这里补上。"""
    for f in os.listdir(SHOTS):
        if f.startswith("_raw_"):
            try:
                os.remove(os.path.join(SHOTS, f))
            except Exception:
                pass


def main(argv):
    want = frozenset(argv[1:])
    raw = shoot_raws()
    html, cards = build_html(raw)
    html_path = os.path.join(raw, "_cards.html")
    with io.open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    try:
        made = capture(html_path, cards, HERE, want)
    finally:
        shutil.rmtree(raw, ignore_errors=True)
        clean_raws()
    for n in made:
        print("OK  %s" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
