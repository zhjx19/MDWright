# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""图片排版三件套的**导出链路**回归（v3.2.0）：

预览在 `_test_img_layout.py` / `_test_img_layout_ui.py`；这里管三条出口：
- 独立 HTML（/api/export-html 的壳：build_standalone_html）——真渲染后量计算样式；
- 分页（build_paged_html）——CSS 层面断言（Paged.js 启动慢，不重复渲染）；
- Word（md_pandoc）——先断言源码改写，再真导出一份解包 document.xml。

约定：Word 不保对齐（pandoc 无对齐语义），但**绝不能把语法残渣印进正文**；
并排用"同一段落的多张行内图"表达（实测 pandoc 落在同一个 <w:p> 里，无表格框线）。
"""
# --- 测试入口 shim ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import os
import re
import sys
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.argv = ["md_server.py"]
import md_server          # noqa: E402
import md_pandoc          # noqa: E402
from _test_browser import run_expr  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


def num(r, key, default=-99):
    """取数值：不能用 `r.get(k) or default`——0 是合法测量值（正好贴边），
    被 `or` 当成假值会换成默认值，把"对齐正确"误判成失败。"""
    v = r.get(key)
    return default if v is None else v


IMG1 = os.path.join(_ROOT, "docs", "screenshots", "writing.png").replace("\\", "/")
IMG2 = os.path.join(_ROOT, "docs", "screenshots", "diagrams.png").replace("\\", "/")

BODY = (
    "<p>正文段落，测试首行缩进。</p>"
    '<p class="p-img"><img src="%s" alt="a" style="width:40%%"></p>'
    '<p class="p-img al-l"><img src="%s" alt="b" style="width:40%%"></p>'
    '<p class="p-img al-r"><img src="%s" alt="c" style="width:30%%"></p>'
    '<div class="img-fill" style="grid-template-columns:50fr 50fr">'
    '<div><img src="%s" alt="d" style="width:100%%"></div>'
    '<div><img src="%s" alt="e" style="width:100%%"></div></div>'
) % (IMG1, IMG1, IMG1, IMG1, IMG2)

# 面板注入的 CSS（applyTypeset 的产物形态：正文缩进 2 字符 + 图片档居中）
TS = "#preview p{text-indent:2em !important;}#preview p.p-img{text-align:center !important;}"

MD = (
    "正文\n\n"
    "![a](a.png)\n\n"
    "![b](b.png){l}\n\n"
    "![c](c.png){30 r}\n\n"
    "![x](x.png){30 x}\n\n"
    "@@ begin fill {50|50}\n![d](%s)\n![e](%s)\n@@ end fill\n"
) % (IMG1, IMG2)

RENDERED = r"""
(function(){
  return new Promise(function(resolve){
    setTimeout(function(){
      var q = function(s){ return document.querySelector(s); };
      function gap(p, side){
        if(!p) return -99;
        var im = p.querySelector('img');
        if(!im) return -99;
        var pr = p.getBoundingClientRect(), ir = im.getBoundingClientRect();
        if(side === 'left') return Math.round(ir.left - pr.left);
        if(side === 'right') return Math.round(pr.right - ir.right);
        return 0;
      }
      var bodyP = q('body > p');
      var imgP = q('p.p-img'), leftP = q('p.p-img.al-l'), rightP = q('p.p-img.al-r');
      var fill = q('.img-fill');
      var fImgs = fill ? [].slice.call(fill.querySelectorAll('img')) : [];
      resolve({
        bodyIndent: bodyP ? getComputedStyle(bodyP).textIndent : '',
        imgIndent: imgP ? getComputedStyle(imgP).textIndent : '',
        centerGapL: gap(imgP, 'left'),
        centerGapR: gap(imgP, 'right'),
        leftGapL: gap(leftP, 'left'),
        leftGapR: gap(leftP, 'right'),
        rightGapL: gap(rightP, 'left'),
        rightGapR: gap(rightP, 'right'),
        fillDisplay: fill ? getComputedStyle(fill).display : '',
        fillCols: fill ? (getComputedStyle(fill).gridTemplateColumns || '').trim().split(/\s+/).length : 0,
        fillImgW: fImgs[0] ? Math.round(fImgs[0].getBoundingClientRect().width) : -1,
        fillBoxW: fill ? Math.round(fill.getBoundingClientRect().width) : -1,
        fillImgN: fImgs.length
      });
    }, 800);
  });
})()
"""

# 分页版：Paged.js 跑完才会把内容搬进 .pagedjs_page，轮询到就绪再量
RENDERED_BREAK = r"""
(function(){
  return new Promise(function(resolve){
    var tries = 0;
    (function wait(){
      var ok = document.querySelector('.pagedjs_page') &&
               document.querySelectorAll('.img-fill img').length === 2;
      if(!ok && tries++ < 48) return setTimeout(wait, 250);
      var pages = [].slice.call(document.querySelectorAll('.pagedjs_page'));
      function pageOf(el){
        var p = el;
        while(p && !(p.classList && p.classList.contains('pagedjs_page'))) p = p.parentNode;
        return p ? pages.indexOf(p) : -1;
      }
      var imgs = [].slice.call(document.querySelectorAll('.img-fill img'));
      resolve({
        imgPages: imgs.map(pageOf),
        sameBox: imgs.length === 2 &&
                 Math.abs(imgs[0].getBoundingClientRect().top -
                          imgs[1].getBoundingClientRect().top) < 3
      });
    })();
  });
})()
"""
RENDERED_PAGED = r"""
(function(){
  return new Promise(function(resolve){
    var tries = 0;
    (function wait(){
      var ready = document.querySelector('.pagedjs_page') &&
                  document.querySelector('p.p-img.al-l img');
      if(!ready && tries++ < 40) return setTimeout(wait, 250);
      function gap(p, side){
        if(!p) return -99;
        var im = p.querySelector('img');
        if(!im) return -99;
        var pr = p.getBoundingClientRect(), ir = im.getBoundingClientRect();
        if(side === 'left') return Math.round(ir.left - pr.left);
        if(side === 'right') return Math.round(pr.right - ir.right);
        return 0;
      }
      resolve({
        pages: document.querySelectorAll('.pagedjs_page').length,
        imgDisplay: document.querySelector('p.p-img img')
            ? getComputedStyle(document.querySelector('p.p-img img')).display : '',
        centerGapL: gap(document.querySelector('p.p-img'), 'left'),
        leftGapL: gap(document.querySelector('p.p-img.al-l'), 'left'),
        leftGapR: gap(document.querySelector('p.p-img.al-l'), 'right'),
        rightGapL: gap(document.querySelector('p.p-img.al-r'), 'left'),
        rightGapR: gap(document.querySelector('p.p-img.al-r'), 'right')
      });
    })();
  });
})()
"""


def main():
    # ── 1. 独立 HTML：CSS 规则 + 真渲染 ────────────────────────
    html = md_server.build_standalone_html(None, BODY, TS, "导出回归")
    check("独立 HTML 有 p-img 缩进归零",
          ".markdown-body p.p-img{text-indent:0 !important;}" in html)
    check("独立 HTML 有 al-l 对齐规则",
          ".markdown-body p.p-img.al-l{text-align:left !important;}" in html)
    check("独立 HTML 有 img-fill 网格",
          ".markdown-body .img-fill{display:grid" in html)
    check("独立 HTML 有栏内图占满栏宽",
          ".markdown-body .img-fill img{width:100%" in html)

    tmp = tempfile.mkdtemp(prefix="mdexport-")
    path = os.path.join(tmp, "exported.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    r = run_expr(RENDERED, url="file:///" + path.replace("\\", "/"))
    check("导出的图不再被首行缩进推歪", r.get("imgIndent") == "0px", str(r.get("imgIndent")))
    check("正文段落仍有首行缩进（对照）",
          r.get("bodyIndent") not in ("", "0px"), str(r.get("bodyIndent")))
    check("默认档的图居中（两侧留白均 > 0）",
          (r.get("centerGapL") or 0) > 10 and (r.get("centerGapR") or 0) > 10,
          "L=%r R=%r" % (r.get("centerGapL"), r.get("centerGapR")))
    check("al-l 的图真的靠左（左贴边、右侧留白）",
          abs(num(r, "leftGapL")) <= 1 and num(r, "leftGapR", 0) > 10,
          "L=%r R=%r" % (r.get("leftGapL"), r.get("leftGapR")))
    check("al-r 的图真的靠右（右贴边、左侧留白）",
          abs(num(r, "rightGapR")) <= 1 and num(r, "rightGapL", 0) > 10,
          "L=%r R=%r" % (r.get("rightGapL"), r.get("rightGapR")))
    check("fill 在导出里是网格两列",
          r.get("fillDisplay") == "grid" and r.get("fillCols") == 2,
          "display=%r cols=%r" % (r.get("fillDisplay"), r.get("fillCols")))
    check("fill 两张图并排且各约半宽",
          r.get("fillImgN") == 2 and (r.get("fillBoxW") or 0) > 0
          and abs((r.get("fillImgW") or 0) - (r.get("fillBoxW") or 0) / 2) < 12,
          "n=%r img=%r box=%r" % (r.get("fillImgN"), r.get("fillImgW"), r.get("fillBoxW")))

    # ── 2. 分页 HTML：同一套规则必须也在（Paged.js 渲染慢，只看 CSS）──
    paged = md_server.build_paged_html(None, BODY, TS, {"paper": "A4"}, "导出回归")
    check("分页 HTML 有 p-img 缩进归零",
          ".markdown-body p.p-img{text-indent:0 !important;}" in paged)
    check("分页 HTML 有 al-l 对齐规则",
          ".markdown-body p.p-img.al-l{text-align:left !important;}" in paged)
    check("分页 HTML 有 al-l 的边距兜底（块级图不吃 text-align）",
          ".markdown-body p.p-img.al-l img{margin-left:0" in paged)
    check("分页 HTML 有 img-fill 网格",
          ".markdown-body .img-fill{display:grid" in paged)

    paged_path = os.path.join(tmp, "paged.html")
    with open(paged_path, "w", encoding="utf-8") as f:
        f.write(paged)
    rp = run_expr(RENDERED_PAGED, url="file:///" + paged_path.replace("\\", "/"))
    check("分页产物真的分页", (rp.get("pages") or 0) >= 1, str(rp.get("pages")))
    check("分页里图是块级（依赖这条，边距才生效）",
          rp.get("imgDisplay") == "block", str(rp.get("imgDisplay")))
    check("分页里默认档居中",
          (rp.get("centerGapL") or 0) > 10, "gapL=%r" % (rp.get("centerGapL"),))
    check("分页里 al-l 的图靠左",
          abs(num(rp, "leftGapL")) <= 2 and num(rp, "leftGapR", 0) > 10,
          "L=%r R=%r" % (rp.get("leftGapL"), rp.get("leftGapR")))
    check("分页里 al-r 的图靠右",
          abs(num(rp, "rightGapR")) <= 2 and num(rp, "rightGapL", 0) > 10,
          "L=%r R=%r" % (rp.get("rightGapL"), rp.get("rightGapR")))

    # ── 分页：并排块不跨页拆散（使用指南里写了这条，必须有测试兜着）──
    filler = "".join("<p>填充段落 %d，把并排块顶到页面底部附近。</p>" % i for i in range(1, 24))
    body2 = (filler +
             '<div class="img-fill" style="grid-template-columns:50fr 50fr">'
             '<div><img src="%s" alt="d" style="width:100%%"></div>'
             '<div><img src="%s" alt="e" style="width:100%%"></div></div>' % (IMG1, IMG2)
             + "<p>后续正文</p>")
    paged2 = md_server.build_paged_html(None, body2, TS, {"paper": "A4"}, "拆页回归")
    p2 = os.path.join(tmp, "paged-break.html")
    with open(p2, "w", encoding="utf-8") as f:
        f.write(paged2)
    rb = run_expr(RENDERED_BREAK, url="file:///" + p2.replace("\\", "/"))
    pages_seen = rb.get("imgPages") or []
    check("分页里并排块不跨页拆散",
          len(pages_seen) == 2 and pages_seen[0] == pages_seen[1]
          and rb.get("sameBox") is True, "%r" % (rb,))

    # ── 3. Word：源码改写（不需要 pandoc）────────────────────
    pre = md_pandoc.prepare_markdown(MD)
    check("Word: {l} 被消化掉", "{l}" not in pre, pre[:160])
    check("Word: {30 r} 只留宽度", "{width=30%}" in pre and "{30 r}" not in pre, pre[:160])
    check("Word: 写坏的 {30 x} 原样保留", "{30 x}" in pre, pre[:160])
    check("Word: fill 起止标记不再出现",
          "@@ begin fill" not in pre and "@@ end fill" not in pre, pre[:200])
    fill_line = [l for l in pre.splitlines() if "a.png" not in l and "{%" in l]
    check("Word: fill 变成同一段落的两张图",
          any(l.count("![") == 2 for l in pre.splitlines()),
          [l for l in pre.splitlines() if l.count("![") == 2][:1] or pre[:200])
    check("Word: fill 每图约半宽",
          bool(re.search(r"\{width=4[0-9]%\}", pre)), pre[:200])

    # ── 4. Word：真导出并解包（缺 pandoc 就 SKIP）──────────────
    if not md_pandoc.md_tools.find_pandoc(""):
        print("Word: 本机无 pandoc，跳过真导出（退出码 77）")
        print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
        sys.exit(77 if not fails else 1)

    out = os.path.join(tmp, "t.docx")
    src_md = os.path.join(tmp, "t.md")
    with open(src_md, "w", encoding="utf-8", newline="\n") as f:
        f.write(MD)
    md_pandoc.export_docx(MD, src_md, out)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    for junk in ("@@", "begin fill", "{l}", "{30 r}", "{width=", "|50"):
        check("Word 正文无残留 %r" % junk, junk not in xml, junk)
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    side_by_side = [p for p in paras if p.count("<w:drawing>") == 2]
    check("Word: fill 的两张图在同一段落（真并排）", len(side_by_side) == 1,
          "含两图的段落数=%d" % len(side_by_side))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
