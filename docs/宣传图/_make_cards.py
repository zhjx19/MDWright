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
06 导出卡的截图来自**真的 Word**：本仓库导出 docx → Word 打印预览 → 截窗，缺 Word
时自动退回「分页 HTML 两页」的老画法（详见 shot_word() 的注释）。
"""
import base64
import io
import os
import shutil
import subprocess
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
.hero .mark{font-size:168px;font-weight:800;letter-spacing:8px;
            background:linear-gradient(92deg,#8ab4f8 0%,#a68cf5 52%,#c58af9 100%);
            -webkit-background-clip:text;background-clip:text;color:transparent;
            line-height:1.1;padding-top:18px}
.hero .en{margin-top:10px;font-size:46px;font-weight:600;letter-spacing:14px;
          color:#7f8ba3;text-indent:14px}
.hero .hook{margin-top:32px;font-size:29px;color:#c9d3e4;letter-spacing:.6px}
.hero .sub{margin-top:16px;font-size:23px;color:#8d99b0;letter-spacing:.8px}
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
  <div class="mark">墨匠</div>
  <div class="en">MDWright</div>
  <div class="hook">Markdown 编辑器很多，能跑 Python / R、交付成品 Word 的，不多</div>
  <div class="sub">Windows 上的单机 Markdown 写作台</div>
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


def build_html(raw, has_word=False):
    """把裸图拼成卡片页；图片内联成 data URI，页面自包含、不依赖任何外部路径。

    卡片编号按顺序自动生成，不写死：缺 Word 时「Word 导出」这张卡整张不出现，
    其余卡片顺次顶上来，不会留空号。
    """
    def img(name):
        return '<img src="%s" alt="">' % b64(os.path.join(raw, name))

    items = [
        ("标题卡", hero()),
        ("写作渲染", feat("左边写，右边看",
                        "常用语法即写即见，公式与表格离线渲染",
                        img("_raw_writing.png"))),
        ("即时渲染", feat("即时渲染：点中一段，就地改源码",
                        "预览即编辑面：点中的那一段展开成源码框，改完自动重排",
                        img("_raw_live.png"))),
        ("图表引擎", feat("图表写在围栏里就出图",
                        "Mermaid / Graphviz / Vega-Lite 随包内置，不联网",
                        img("_raw_diagrams.png"))),
        ("代码运行", feat("代码块直接跑，输出留在原处",
                        "带 python / r 标记的围栏自带「▶ 运行」，用的是随包运行时",
                        img("_raw_code.png"))),
    ]
    if has_word:
        items.append(("Word导出", feat(
            "导出就是成品：Word 里也是三线表",
            "pandoc 转 .docx，导出后按 OOXML 注入顶线 / 表头线 / 底线",
            img("_raw_word.png"))))
    items += [
        ("分页导出", feat("分页导出：目录、页码、纸张",
                        "Paged.js 组版，浏览器里 Ctrl+P 直接出 PDF",
                        '<div class="pages">%s%s</div>'
                        % (img("_raw_page1.png"), img("_raw_page2.png")))),
        ("收尾", outro()),
    ]
    cards = [("%02d-%s" % (i + 1, slug), html) for i, (slug, html) in enumerate(items)]
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
    word = shot_word(raw)
    return raw, word


# ---------------------------------------------------------------- Word 三线表截图
# 这张卡要证明的是「导出到 Word 的表格落成三线表」，所以必须是 Word 自己的排版结果，
# 不能用 HTML 复刻。实测出来的四条约束（都踩过）：
#   1. 文档不能放 %TEMP%——Word 会以「受保护的视图」打开，随后的自动化调用直接卡死；
#   2. ExportAsFixedFormat 在本机 Office 上必挂（新建空文档也一样），所以走窗口截图；
#   3. 普通视图里关不掉段落标记（View.ShowParagraphs 写入无效），改用**打印预览**，
#      它显示的就是打印结果，不带任何编辑标记；
#   4. 捕获用 PrintWindow(PW_RENDERFULLCONTENT)——CopyFromScreen 会被别的窗口遮挡。
# 另外不主动杀 Word：用户可能有未保存的稿子，检测到在运行就退出并提示先关掉。
WORD_MD = """## 三线表：学术与出版排版的基本盘

正文照常写，表格在导出时按三线表落版：顶线、表头下横线、底线，其余横线一律不画。

| 版本 | 类型 | 主要变更 | 影响 |
| --- | --- | --- | --- |
| v2.2.0 | 新增 | Word（.docx）与 PDF 直出 | 稿子能直接交出去 |
| v3.1.0 | 改进 | 中英混排自动补空格 | 渲染与导出同步 |
| v3.2.0 | 新增 | 代码块常驻会话、结果落盘 | 变量可跨块复用 |
| v3.2.4 | 新增 | 上下标支持 `^{}` / `_{}` | 公式写法更顺手 |
"""

WORD_PS = r"""$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinCap {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after,
      int x, int y, int cx, int cy, uint flags);
  public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
[void][WinCap]::SetProcessDPIAware()

if (Get-Process WINWORD -ErrorAction SilentlyContinue) { Write-Output 'WORD_RUNNING'; exit 3 }

$docx = '%s'
$png  = '%s'

$word = New-Object -ComObject Word.Application
$word.Visible = $true
$word.DisplayAlerts = 0
$word.AutomationSecurity = 3
$doc = $word.Documents.Open($docx, $false, $false)
$word.ActiveWindow.DocumentMap = $false
$word.ActiveWindow.View.ShowTextBoundaries = $false   # 关掉文字边界线（打印预览里也会画）
$word.ActiveWindow.View.ShowBookmarks = $false
$word.WindowState = 0

$hwnd = (Get-Process WINWORD | Sort-Object StartTime -Descending | Select-Object -First 1).MainWindowHandle
[void][WinCap]::SetWindowPos($hwnd, [IntPtr]::Zero, 0, 0, 1280, 1000, 0x0040)
[void][WinCap]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds 700

$doc.PrintPreview()
Start-Sleep -Milliseconds 1500
$word.ActiveWindow.View.Zoom.PageFit = 2
Start-Sleep -Milliseconds 800

$r = New-Object WinCap+RECT
[void][WinCap]::GetWindowRect($hwnd, [ref]$r)
$w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
$ok = [WinCap]::PrintWindow($hwnd, $hdc, 2)
$g.ReleaseHdc($hdc); $g.Dispose()
$bmp.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output "CAPTURED ${w}x${h} ok=$ok"

$doc.ClosePrintPreview()
$doc.Close(0)
$word.Quit()
"""

# 只保留白色页面本体：左侧竖线（文字边界）、页角标记与状态栏都在这个框外
_WORD_CROP = (90, 315, 1215, 940)


def find_winword():
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        for ver in ("root\\Office16", "Office16", "root\\Office15", "Office15"):
            p = os.path.join(base, "Microsoft Office", ver, "WINWORD.EXE")
            if os.path.isfile(p):
                return p
    return ""


def shot_word(raw):
    """用 Word 截一张三线表页面，返回裸图路径；没有 Word 或 Word 正在运行时返回空串。"""
    if not find_winword():
        print("跳过 Word 卡：本机未找到 WINWORD.EXE")
        return ""
    import md_pandoc
    import md_tools

    # runtime/ 已被 .gitignore 忽略，且不是 %TEMP%，Word 不会按受保护视图打开
    work = os.path.join(ROOT, "runtime", "tmp", "wordcard")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    md_path = os.path.join(work, "demo.md")
    docx = os.path.join(work, "demo.docx")
    png = os.path.join(work, "window.png")
    with io.open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(WORD_MD)
    md_pandoc.export_docx(WORD_MD, md_path, docx)
    md_pandoc.three_line_tables(docx, md_tools.find_pandoc(""))

    ps1 = os.path.join(work, "shot_word.ps1")
    with io.open(ps1, "w", encoding="utf-8") as f:
        f.write(WORD_PS % (docx, png))
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", ps1], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out_text = ((r.stdout or "") + (r.stderr or "")).strip()
    if "WORD_RUNNING" in out_text:
        print("跳过 Word 卡：Word 正在运行，先关掉再重跑（不主动杀，怕丢未保存的稿子）")
        return ""
    if r.returncode != 0 or not os.path.isfile(png):
        print("跳过 Word 卡：截图失败 %s" % out_text[-300:])
        return ""

    out = os.path.join(raw, "_raw_word.png")
    Image.open(png).convert("RGB").crop(_WORD_CROP).resize(
        (1280, 720), Image.LANCZOS).save(out, "PNG", optimize=True)
    return out


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
    raw, word = shoot_raws()
    html, cards = build_html(raw, bool(word))
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
