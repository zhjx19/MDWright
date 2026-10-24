# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""README 截图生成器（可重录）：起本地后端 → headless Edge 打开 → CDP 截图 → 合成落盘。

为什么要有这个脚本：README 里的截图必须能随时重录。手工截一次就丢，界面一改
截图立刻过期，而没人记得当初拍的是哪份文档、哪个视图、什么尺寸。这里把
「哪份文档 + 哪个视图 + 多大窗口 + 怎么合成」全部写成代码，跑一条命令全量重出。

用法（在仓库根目录）：

    python\\python.exe docs\\screenshots\\_make_screenshots.py            # 全部重出
    python\\python.exe docs\\screenshots\\_make_screenshots.py writing    # 只重出某一张

依赖：本机 Edge（或 Chrome）+ 仓库自带的 Pillow（`python/Lib/site-packages/PIL`）。
不联网：所有页面素材来自本机后端与仓库内置的离线依赖。
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import _cdp                                   # noqa: E402  同目录 CDP 客户端（标准库实现）
from PIL import Image, ImageDraw, ImageFilter, ImageFont   # noqa: E402

PORT = int(os.environ.get("MD_SHOT_PORT") or 18790)   # 私有端口：绝不占用用户正在用的 18766
BASE = "http://127.0.0.1:%d" % PORT
DEMO = os.path.join(HERE, "demo")
OUT = HERE

# 画面：内容区尺寸（CSS px）。设备像素比固定 2，落盘前缩回 1x，字缘更干净。
W, H = 1600, 900
SCALE = 2
PAD = 40              # 卡片四周留白（暗色底）
RADIUS = 26
BACKDROP = (18, 21, 27)
SHADOW = (8, 9, 12)

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
TITLE_FONTS = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


# ---------------------------------------------------------------- 基础工具
def find_browser():
    for p in BROWSER_CANDIDATES:
        if os.path.isfile(p):
            return p
    raise SystemExit("找不到 Edge/Chrome：%s" % ", ".join(BROWSER_CANDIDATES))


def http_json(path, payload=None, timeout=60):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ensure_server():
    """后端起不来就自己起一个；返回 (proc or None)。"""
    try:
        http_json("/api/version", timeout=3)
        return None
    except Exception:
        pass
    proc = subprocess.Popen([os.path.join(ROOT, "python", "python.exe"), "md_server.py"],
                            cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW,
                            env=dict(os.environ, MD_PORT=str(PORT)))
    end = time.time() + 30
    while time.time() < end:
        try:
            http_json("/api/version", timeout=2)
            return proc
        except Exception:
            time.sleep(0.3)
    raise SystemExit("后端 30s 内没起来（%s）" % BASE)


class Browser(object):
    """一个 headless 浏览器会话；页面级操作全走 CDP。"""

    def __init__(self, browser, width=W, height=H, scale=SCALE):
        self.prof = tempfile.mkdtemp(prefix="mdw-shot-")
        self.proc = subprocess.Popen(
            [browser, "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", "--hide-scrollbars",
             "--force-color-profile=srgb", "--remote-debugging-port=0",
             "--user-data-dir=" + self.prof,
             "--window-size=%d,%d" % (width, height), "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW)
        port = _cdp._devtools_port(self.prof)
        page = next(t for t in _cdp._json_list(port) if t.get("type") == "page")
        self.cdp = _cdp.CDP(page["webSocketDebuggerUrl"])
        self.cdp.cmd("Page.enable")
        self.cdp.cmd("Runtime.enable")
        self.cdp.cmd("Emulation.setDeviceMetricsOverride", width=width, height=height,
                     deviceScaleFactor=scale, mobile=False)

    def js(self, expr, timeout=30):
        """求值；异常不抛出，返回 None（截图脚本不该因为一行探测 JS 挂掉）。"""
        try:
            r = self.cdp.cmd("Runtime.evaluate", expression=expr, returnByValue=True,
                             awaitPromise=True)
        except _cdp.CDPError:
            return None
        return r.get("result", {}).get("value")

    def wait(self, expr, timeout=45.0, poll=0.15, what=""):
        end = time.time() + timeout
        while time.time() < end:
            if self.js(expr) is True:
                return True
            time.sleep(poll)
        raise SystemExit("等待超时（%s）：%s" % (what or expr, expr))

    def goto(self, url):
        self.cdp.cmd("Page.navigate", url=url)

    def open_doc(self, md_name, view=None, theme=None):
        """打开仓库里的示例文档；view/theme 由 localStorage 决定，设完必须重载。"""
        url = "%s/?file=%s&v=%d" % (BASE, urllib.parse.quote(os.path.join(DEMO, md_name)),
                                    int(time.time()))
        self.goto(url)
        self.wait("document.readyState==='complete'", what="文档加载")
        if view:
            self.js("localStorage.setItem('md-editor-view', %s)" % json.dumps(view))
        if theme:
            self.js("localStorage.setItem('md-editor-theme', %s)" % json.dumps(theme))
        if view or theme:
            self.goto(url)
        self.wait_rendered()

    def wait_rendered(self):
        """等文档进编辑器、预览出内容、异步图表全部 data-done、字体加载完。"""
        self.wait("(function(){var e=document.getElementById('editor');"
                  "return !!e && e.textContent.trim().length>120;})()", what="文档进编辑器")
        self.wait("(function(){var p=document.getElementById('preview');"
                  "if(!p||!p.children.length)return false;"
                  "if(p.querySelectorAll('.diagram:not([data-done])').length)return false;"
                  "return document.fonts? document.fonts.status==='loaded': true;})()",
                  timeout=60, what="预览渲染")

    def settle(self, seconds=0.8):
        time.sleep(seconds)                     # 让高亮/图表/滚动条收尾

    def rect(self, selector, index=0):
        js = ("(function(){var e=document.querySelectorAll(%s)[%d];"
              "if(!e)return null;var r=e.getBoundingClientRect();"
              "return JSON.stringify({x:r.x,y:r.y,width:r.width,height:r.height});})()"
              % (json.dumps(selector), index))
        v = self.js(js)
        return json.loads(v) if v else None

    def _mouse(self, kind, x, y, button="left", clicks=1):
        p = dict(type=kind, x=x, y=y, button=button, buttons=1 if kind == "mousePressed" else 0,
                 clickCount=clicks)
        if kind == "mouseMoved":
            p["button"] = "none"
            p["buttons"] = 0
        self.cdp.cmd("Input.dispatchMouseEvent", **p)

    def hover(self, selector, index=0):
        r = self.rect(selector, index)
        if not r:
            raise SystemExit("hover 目标不存在：%s[%d]" % (selector, index))
        self._mouse("mouseMoved", r["x"] + r["width"] / 2, r["y"] + r["height"] / 2)
        time.sleep(0.3)

    def click(self, selector, index=0):
        r = self.rect(selector, index)
        if not r:
            raise SystemExit("click 目标不存在：%s[%d]" % (selector, index))
        x, y = r["x"] + r["width"] / 2, r["y"] + r["height"] / 2
        self._mouse("mouseMoved", x, y)
        self._mouse("mousePressed", x, y)
        self._mouse("mouseReleased", x, y)
        time.sleep(0.2)

    def shot(self, path, clip=None, beyond=False):
        params = dict(format="png", captureBeyondViewport=beyond)
        if clip:
            params["clip"] = dict(clip, scale=SCALE)
        data = self.cdp.cmd("Page.captureScreenshot", **params).get("data") or ""
        png = base64.b64decode(data)
        if not png.startswith(b"\x89PNG"):
            raise SystemExit("captureScreenshot 没返回 PNG：%s" % path)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(png)
        os.replace(tmp, path)
        return path

    def close(self):
        try:
            self.cdp.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        shutil.rmtree(self.prof, ignore_errors=True)


# ---------------------------------------------------------------- 合成
def _font(size):
    for p in TITLE_FONTS:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def frame(src_png, out_png, title=None, title_h=96):
    """把裸截图装进「暗底 + 圆角卡 + 投影」的框里；带标题时先留出标题带。"""
    im = Image.open(src_png).convert("RGB")
    im = im.resize((W, H), Image.LANCZOS)
    tw = W + PAD * 2
    th = H + PAD * 2 + (title_h if title else 0)
    canvas = Image.new("RGB", (tw, th), BACKDROP)

    card = Image.new("RGB", (W, H), BACKDROP)
    card.paste(im, (0, 0))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], RADIUS, fill=255)

    top = PAD + (title_h if title else 0)
    shadow = Image.new("RGB", (tw, th), BACKDROP)
    ImageDraw.Draw(shadow).rounded_rectangle(
        [PAD - 6, top + 10, PAD + W + 5, top + H + 16], RADIUS + 4, fill=SHADOW)
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.paste(shadow, (0, 0))
    canvas.paste(card, (PAD, top), mask)

    if title:
        d = ImageDraw.Draw(canvas)
        f = _font(38)
        wtxt = d.textbbox((0, 0), title, font=f)
        d.text(((tw - (wtxt[2] - wtxt[0])) / 2, 26), title, font=f, fill=(233, 236, 242))

    with open(out_png + ".part", "wb") as f:      # 先落 .part，成功再改名
        canvas.save(f, "PNG", optimize=True)
    os.replace(out_png + ".part", out_png)
    return out_png


def montage_pages(page_pngs, out_png, title):
    """两页并排的成品预览图（分页导出那张）。"""
    tw = W + PAD * 2
    th = H + PAD * 2
    canvas = Image.new("RGB", (tw, th), BACKDROP)
    d = ImageDraw.Draw(canvas)
    f = _font(38)
    bbox = d.textbbox((0, 0), title, font=f)
    d.text(((tw - (bbox[2] - bbox[0])) / 2, 30), title, font=f, fill=(233, 236, 242))

    imgs = [Image.open(p).convert("RGB") for p in page_pngs]
    if not imgs:
        raise SystemExit("没有页面可拼")
    top, bottom = 132, th - 46
    avail = bottom - top
    gap = 48
    scaled = [i.resize((int(i.width * avail / i.height), avail), Image.LANCZOS) for i in imgs]
    total = sum(i.width for i in scaled) + gap * (len(scaled) - 1)
    x = (tw - total) // 2

    # 投影层一次画完再模糊：逐张 paste 会把已贴好的上一页整块盖掉（实踩）
    shadow = Image.new("L", (tw, th), 0)
    sd = ImageDraw.Draw(shadow)
    x0 = x
    for img in scaled:
        sd.rectangle([x0 - 6, top + 8, x0 + img.width + 6, top + avail + 16], fill=110)
        x0 += img.width + gap
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.paste(Image.new("RGB", (tw, th), (8, 9, 12)), (0, 0), shadow)

    x0 = x
    for img in scaled:
        canvas.paste(img, (x0, top))
        x0 += img.width + gap

    tmp = out_png + ".part"
    with open(tmp, "wb") as f:
        canvas.save(f, "PNG", optimize=True)
    os.replace(tmp, out_png)
    return out_png


# ---------------------------------------------------------------- 各张截图
def shot_writing(br):
    br.open_doc("demo.md", view="split")
    br.settle()
    raw = br.shot(os.path.join(HERE, "_raw_writing.png"))
    _keep_raw(raw)
    return frame(raw, os.path.join(OUT, "writing.png"))


def shot_live(br):
    """即时渲染：真的点中一个正文块，让它就地展开源码编辑框。"""
    br.open_doc("demo.md", view="live")
    br.settle(1.0)
    idx = br.js("(function(){var b=document.querySelectorAll('#preview .pblk');"
                "for(var i=0;i<b.length;i++){"
                "if((b[i].textContent||'').indexOf('MDWright 是 Windows')>=0)return i;}"
                "return 1;})()") or 1
    br.click("#preview .pblk", idx)
    br.wait("!!document.querySelector('#preview .pblk.editing textarea.pblk-src')",
            what="即时渲染就地编辑")
    br.settle(0.6)
    raw = br.shot(os.path.join(HERE, "_raw_live.png"))
    _keep_raw(raw)
    return frame(raw, os.path.join(OUT, "live-view.png"))


def shot_code(br):
    """可执行代码块：真点「▶ 运行」，等输出落到块下方。"""
    br.open_doc("code.md", view="split")
    br.settle(0.8)
    br.hover(".run-btn")
    br.click(".run-btn")
    br.wait("(function(){var o=document.querySelector('.r-out');"
            "if(!o||o.hidden)return false;"
            "return !!o.querySelector('.r-out-txt,.r-out-err,.r-out-line');})()",
            timeout=90, what="代码块执行输出")
    br.hover(".run-btn")
    br.settle(0.6)
    raw = br.shot(os.path.join(HERE, "_raw_code.png"))
    _keep_raw(raw)
    return frame(raw, os.path.join(OUT, "code-run.png"))


def shot_diagrams(br):
    br.open_doc("diagrams.md", view="split")
    br.settle(1.2)
    raw = br.shot(os.path.join(HERE, "_raw_diagrams.png"))
    _keep_raw(raw)
    return frame(raw, os.path.join(OUT, "diagrams.png"))


def shot_paged(br):
    """真的走一遍分页导出接口，把产出的分页 HTML 里前两页拍下来拼图。

    cfg 显式打开页码与自动目录：这两项默认关，而这张图要展示的正是它们。
    """
    demo = os.path.join(DEMO, "paged.md")
    br.open_doc("paged.md", view="split")
    cfg = {"paper": "A4", "mt": 25, "mr": 18, "mb": 25, "ml": 18,
           "pn": {"on": "on", "size": 9, "pos": "center"},
           "toc": {"on": "on", "pos": "top", "solo": True}}
    payload = {"path": demo,
               "bodyHtml": br.js("(document.getElementById('preview')||{innerHTML:''}).innerHTML") or "",
               "docTitle": "",
               "tsCss": br.js("(document.getElementById('ts-style')||{textContent:''}).textContent") or "",
               "cfg": cfg}
    if not payload["bodyHtml"]:
        raise SystemExit("预览为空，分页导出无从谈起")
    j = http_json("/api/export-paged", payload, timeout=120)
    if not j.get("ok"):
        raise SystemExit("分页导出失败：%s" % j.get("error"))

    pages = Browser(browser=find_browser(), width=1300, height=1000, scale=SCALE)
    try:
        pages.goto(BASE + j["url"] + "?t=%d" % int(time.time()))
        pages.wait("document.documentElement.getAttribute('data-paged-done')==='1'",
                   timeout=120, what="Paged.js 分页完成")
        n = pages.js("document.querySelectorAll('.pagedjs_page').length") or 0
        if n < 2:
            raise SystemExit("分页只出了 %d 页" % n)
        # 整篇一次拍完，再按页框坐标裁：CDP 的 clip 在部分 Edge 版本上不生效，
        # 会把整篇文档原样吐回来（实测 3175×4490 = 全篇 @2x），故不信 clip、自己裁。
        full = pages.shot(os.path.join(HERE, "_raw_paged_full.png"), beyond=True)
        _keep_raw(full)
        out = []
        for i in (0, 1):
            r = json.loads(pages.js(
                "(function(){var p=document.querySelectorAll('.pagedjs_page')[%d];"
                "var b=p.getBoundingClientRect();"
                "return JSON.stringify({x:b.x+window.scrollX,y:b.y+window.scrollY,"
                "width:b.width,height:b.height});})()" % i))
            box = (int(round(r["x"] * SCALE)), int(round(r["y"] * SCALE)),
                   int(round((r["x"] + r["width"]) * SCALE)),
                   int(round((r["y"] + r["height"]) * SCALE)))
            p = os.path.join(HERE, "_raw_page%d.png" % (i + 1))
            Image.open(full).convert("RGB").crop(box).save(p)
            _keep_raw(p)
            out.append(p)
    finally:
        pages.close()
    return montage_pages(out, os.path.join(OUT, "paged-export.png"),
                         "分页导出 · 自动目录 · 页码")


SHOTS = [
    ("writing", shot_writing, "写作与渲染"),
    ("code", shot_code, "可执行代码块"),
    ("live", shot_live, "即时渲染：点段即改"),
    ("diagrams", shot_diagrams, "图表引擎"),
    ("paged", shot_paged, "分页导出"),
]

# 宣传图生成器（docs/宣传图/_make_cards.py）要的是裸截图，不是套好框的成品：
# 它自己排版。设了这个目录，每张裸图额外留一份过去。
RAW_DIR = None


def _keep_raw(path):
    if RAW_DIR:
        try:
            shutil.copyfile(path, os.path.join(RAW_DIR, os.path.basename(path)))
        except Exception:
            pass


def main(argv):
    want = set(a.lower() for a in argv[1:])
    browser = find_browser()
    srv = ensure_server()
    br = None
    try:
        br = Browser(browser)
        for key, fn, _label in SHOTS:
            if want and key not in want:
                continue
            out = fn(br)
            print("OK  %-10s -> %s" % (key, os.path.relpath(out, ROOT)))
    finally:
        if br:
            br.close()
        if srv is not None:
            try:
                srv.terminate()
            except Exception:
                pass
    # 清理中间产物（保留脚本与成品）；调试时设 MDW_KEEP=1 留住 raw 图
    if os.environ.get("MDW_KEEP") == "1":
        return 0
    for f in os.listdir(HERE):
        if f.startswith("_raw_"):
            try:
                os.remove(os.path.join(HERE, f))
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
