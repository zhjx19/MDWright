# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Word（.docx）导出：方言 → pandoc markdown → pandoc 调用。

**只做 pandoc 不认的三件事**：Callout、图片宽度 `{N}`、图表围栏的 `{N}`。
脚注 / 定义列表 / YAML front matter / 行内高亮 / 上下标 / 公式 pandoc 原生支持，
一律原样透传——在这里重写 pandoc 已会的东西，只会让两边慢慢走样。

公式：`$...$` / `$$...$$` 交给 pandoc，docx 侧落为 Word 原生公式（OMML，
实测 `<m:oMath>` / `<m:sSup>` / `<m:f>` 齐全），不做图像化或文本化降级。
"""
import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile

import md_tools

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_FENCE_RE = re.compile(r"^(\s*)(```|~~~)(.*)$")
# 图表围栏：预览侧渲染成 SVG，Word 侧只能嵌位图（前端点导出时先栅格化）。
# 语言名与预览 parseMarkdown 认的那一组保持一致。
DIAGRAM_LANGS = frozenset(("mermaid", "dot", "graphviz", "viz",
                           "wavedrom", "wavejson", "vega", "vega-lite", "vegalite"))
_CALLOUT_RE = re.compile(r"^(\s*>\s*)\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$")
# 图片参数组：`![alt](src){...}`（花括号在这里被完整吃掉，是否合法由 _norm_img_params 判）
_IMG_PARAM_RE = re.compile(r"(!\[[^\]]*\]\([^)]+\))\s*\{([^{}]*)\}")
# 并排块里的图片行：整行只有一张图（宽度/对齐参数允许，随后被忽略）
_FILL_IMG_RE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)]+?)(?:\s+\"([^\"]*)\")?\)\s*(?:\{[^{}]*\})?\s*$")
_FILL_BEGIN_RE = re.compile(r"^\s*@@\s*begin\s+fill\s*\{([^{}]*)\}\s*$", re.I)
_FILL_END_RE = re.compile(r"^\s*@@\s*end\s+fill\s*$", re.I)
# 独占一行的图（允许前导空白与 blockquote 前缀）：title 作题注、alt 只作替代文本
_FIG_LINE_RE = re.compile(
    r"^((?:[ \t]*>[ \t]?)*[ \t]*)!\[([^\]]*)\]\(([^)\n]+?)"
    r"(?:\s+\"([^\"]*)\")?\)(\s*\{[^{}]*\})?\s*$")
# 花括号上下标 ^{..} / _{..}：内容不含花括号与换行；pandoc 认的是 ^..^ 与 ~..~
_SCRIPT_RE = re.compile(r"([\^_])\{([^{}\n]+)\}")
# 改写前要原样保留的两类片段：行内代码与行内公式（LaTeX 的 ^{2} / _{k=1} 不能被改）
_CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
_MATH_INLINE_RE = re.compile(r"\$[^$\n]+\$")


def _clamp(pct):
    return min(100, int(pct))


def _norm_img_params(line):
    """图片参数 `{...}` → pandoc 只认宽度：留 `{width=N%}`，对齐 token 丢弃。

    与预览同一套 fail-closed 口径：出现未知 token（`{30 x}`）、重复宽度或空组时
    **整组原样保留**——宁可让字面露在 Word 里被看见，也不悄悄改用户的意图。
    Word 没有段落级对齐语义，`c/l/r` 在这里是"无副作用地丢"（预览/导出 HTML 各自生效）。
    """
    def repl(m):
        toks = m.group(2).split()
        w = None
        has_al = False
        ok = bool(toks)
        for t in toks:
            if re.fullmatch(r"[1-9]\d{0,2}", t):
                if w is not None:
                    ok = False
                else:
                    w = _clamp(t)
            elif re.fullmatch(r"[clrCLR]", t):
                if has_al:
                    ok = False
                else:
                    has_al = True
            else:
                ok = False
        if not ok:
            return m.group(0)
        return m.group(1) + (("{width=%d%%}" % w) if w is not None else "")

    return _IMG_PARAM_RE.sub(repl, line)


def _fill_line(lines, start):
    """`@@ begin fill {a|b[|c[|d]]}` … `@@ end fill` → 一行并排图。

    Word 里最接近"并排"的表达是**同一段落里的多张行内图**（实测 pandoc 落在同一个
    <w:p>，不带表格框线，宽度按 {width=N%} 等比缩放）。栏宽按比例换算成版面百分比，
    总宽压到 94%：留出图之间的空格，避免 pandoc 换行变成上下排。
    返回 (改写后的行, 下一行下标)；任何不合法都返回 None，调用处按普通文本原样处理。
    """
    m = _FILL_BEGIN_RE.match(lines[start])
    if not m:
        return None
    parts = m.group(1).split("|")
    if not 2 <= len(parts) <= 4:
        return None
    ratios = []
    for p in parts:
        t = p.strip()
        if not re.fullmatch(r"\d+(\.\d+)?", t):
            return None
        v = float(t)
        if v <= 0:
            return None
        ratios.append(v)
    imgs, j = [], start + 1
    while j < len(lines):
        ln = lines[j]
        if _FILL_END_RE.match(ln):
            break
        if not ln.strip():
            j += 1
            continue
        im = _FILL_IMG_RE.match(ln)
        if not im:
            return None                      # 栏内出现非图片行
        imgs.append(im)
        j += 1
    else:
        return None                          # 没有 @@ end fill
    if len(imgs) != len(ratios):
        return None                          # 图数与栏数不等
    total = sum(ratios)
    cells = []
    for r, im in zip(ratios, imgs):
        pct = max(10, int(r / total * 100 * 0.94))
        title = (' "%s"' % im.group(3)) if im.group(3) else ""
        cells.append("![%s](%s%s){width=%d%%}" % (im.group(1), im.group(2), title, pct))
    return " ".join(cells), j + 1


def _figure_caption(line):
    """独占一行的图：title 作题注，alt 只是替代文本（与预览同一口径）。

    pandoc 的 implicit_figures 拿 alt 当 caption，所以这里把 alt 换成 title；
    title 为空就清空 alt——否则 Word 里会凭空多一行题注（预览并没有）。
    行内图与并排块不走这里：它们不是独占一行的段落，pandoc 也不会当 figure。
    """
    m = _FIG_LINE_RE.match(line)
    if not m:
        return line
    lead, alt, src, title, params = m.groups()
    return "%s![%s](%s)%s" % (lead, (title or "").strip(), src, params or "")


def _figure_block(line, img_align="center"):
    """独行图 → 包一层 Figure / FigureLeft / FigureRight Div。

    Word 里图片对齐是段落属性，pandoc 的 markdown 图片属性表达不了；用带
    custom-style 的 Div 指定段落样式，导出后再补齐这三个样式。对齐优先级：
    `{c}` / `{l}` / `{r}` > 面板「图片」默认对齐（img_align）> 居中。
    不是独行图（行内图、并排块、缩进代码）返回 None，交给普通行处理。
    """
    m = _FIG_LINE_RE.match(line)
    if not m:
        return None
    lead, alt, src, title, params = m.groups()
    if ">" not in lead and len(lead.expandtabs(4)) >= 4:
        return None                      # 四空格缩进是代码块，不包 Div
    align = {"left": "l", "right": "r"}.get((img_align or "").strip().lower(), "c")
    pm = re.search(r"\{([^{}]*)\}", params or "")
    if pm:
        toks = pm.group(1).split()
        marks = [t.lower() for t in toks if re.fullmatch(r"[clrCLR]", t)]
        if len(marks) == 1:
            align = marks[0]
    style = {"l": "FigureLeft", "r": "FigureRight"}.get(align, "Figure")
    inner = "%s![%s](%s)%s" % (lead, (title or "").strip(), src, params or "")
    inner = _brace_scripts(_norm_img_params(inner))
    prefix = lead if ">" in lead else ""
    return ["%s::: {custom-style=\"%s\"}" % (prefix, style), inner, prefix + ":::"]


def _mask(text, pattern, store, mark):
    """把匹配到的片段换成长度无关的占位符，原样存进 store，稍后按序还原。"""
    def repl(m):
        store.append(m.group(0))
        return mark + str(len(store) - 1) + mark
    return pattern.sub(repl, text)


def _brace_scripts(line):
    """把 ^{..} / _{..} 改写成 pandoc 认得的 ^..^ / ~..~（纯函数，幂等）。

    两类片段必须原样保留：行内代码（语法示例）与行内公式（LaTeX 自身就用 ^{}），
    所以先占位再改写。内容里的定界符与空格按 pandoc 规范转义——pandoc 的上下标
    遇到裸空格会提前收尾，遇到同名定界符会错配。
    块级公式（$$ 跨行）由 prepare_markdown 的 math_block 状态整段跳过，不到这里。
    """
    if "^{" not in line and "_{" not in line:
        return line
    code_store, math_store = [], []
    s = _mask(line, _CODE_SPAN_RE, code_store, "\x01")
    s = _mask(s, _MATH_INLINE_RE, math_store, "\x00")

    def repl(m):
        delim = "^" if m.group(1) == "^" else "~"
        body = m.group(2).replace(delim, "\\" + delim).replace(" ", "\\ ")
        return delim + body + delim

    s = _SCRIPT_RE.sub(repl, s)
    s = re.sub(r"\x00(\d+)\x00", lambda m: math_store[int(m.group(1))], s)
    s = re.sub(r"\x01(\d+)\x01", lambda m: code_store[int(m.group(1))], s)
    return s


def diagram_key(lang, code):
    """图表围栏的匹配键：语言（小写、去空白）+ 源码原文（去首尾换行）。

    前端在预览里渲染完一张图，就以这个键把 PNG 交回来；键必须逐字对上，
    对不上就保持代码块（fail-closed），不拿错图顶替。
    """
    return ((lang or "").strip().lower(),
            (code or "").replace("\r\n", "\n").strip("\n"))


def count_diagram_fences(src):
    """数源文里的图表围栏个数（导出后回报「几张没渲染成功」用）。"""
    n, fence_mark = 0, ""
    for ln in (src or "").replace("\r\n", "\n").split("\n"):
        m = _FENCE_RE.match(ln)
        if not m:
            continue
        mark = m.group(2)
        if not fence_mark:
            info = re.sub(r"\s*\{[1-9]\d{0,2}\}\s*$", "", (m.group(3) or "").strip()).strip()
            lang = info.split()[0].lower() if info else ""
            if lang in DIAGRAM_LANGS:
                n += 1
            fence_mark = mark
        elif mark == fence_mark:
            fence_mark = ""
    return n


def _fence_block(lines, start, mark):
    """从 start 起找与 mark 同种的闭合行，返回 (块内各行, 闭合行下标)。

    未闭合时下标为 None——调用方原样透传，不猜。
    """
    body, j = [], start
    while j < len(lines):
        m = _FENCE_RE.match(lines[j])
        if m and m.group(2) == mark:
            return body, j
        body.append(lines[j])
        j += 1
    return body, None


def prepare_markdown(src, diagrams=None, img_align="center"):
    """把本文方言改写成 pandoc 认得的 markdown（幂等，纯函数）。

    diagrams：{(语言, 源码): {"path": ..., "width": N}}，是前端在预览里渲染好
    并栅格化的图表位图。命中的图表围栏整块换成一张图——宽度优先取围栏的
    `{N}`，没有就用前端按显示尺寸算出的百分比；没命中就保持代码块，宁可让
    源码留在 Word 里被看见，也不塞一张对不上号的图。
    """
    out = []
    fence_mark = ""          # 当前所在围栏的标记（``` 或 ~~~），空=不在围栏内
    math_block = False       # 是否在 $$ 块级公式内（跨行，整段不参与改写）
    lines = src.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = _FENCE_RE.match(ln)
        if m:
            mark = m.group(2)
            if not fence_mark:
                # 开围栏：图表围栏的 `{N}` 宽度 pandoc 不认，剥掉；语言名保留
                info_raw = (m.group(3) or "").strip()
                wm = re.search(r"\{([1-9]\d{0,2})\}\s*$", info_raw)
                fence_w = int(wm.group(1)) if wm else 0
                info = re.sub(r"\s*\{[1-9]\d{0,2}\}\s*$", "", info_raw).strip()
                if diagrams:
                    lang = info.split()[0].lower() if info else ""
                    if lang in DIAGRAM_LANGS:
                        body, close_at = _fence_block(lines, i + 1, mark)
                        hit = diagrams.get(diagram_key(lang, "\n".join(body)))
                        if close_at is not None and hit:
                            w = _clamp(fence_w) if fence_w else _clamp(hit.get("width") or 95)
                            # alt 留空：pandoc 会把「段落里只有一张图」当插图并拿 alt
                            # 当题注，Word 里就多一行斜体「图表」。
                            img_line = ("![](<%s>){width=%d%%}"
                                        % (str(hit["path"]).replace("\\", "/"), w))
                            out.extend(_figure_block(img_line, img_align) or [img_line])
                            out.append("")
                            i = close_at + 1
                            continue
                out.append(m.group(1) + mark + info)
                fence_mark = mark
            elif mark == fence_mark:
                out.append(ln)
                fence_mark = ""          # 只有**同种**标记能闭合（``` 块里的 ~~~ 是内容）
            else:
                out.append(ln)           # 不同种标记：属于内容，不能被当闭合
            i += 1
            continue
        if fence_mark:
            out.append(ln)               # 代码块内部一律不动
            i += 1
            continue
        if math_block:
            out.append(ln)
            if ln.count("$$") % 2 == 1:
                math_block = False
            i += 1
            continue
        if ln.lstrip().startswith("$$") and ln.count("$$") % 2 == 1:
            math_block = True            # 块级公式开：整段原样透传，内部的 ^{} 是 LaTeX
            out.append(ln)
            i += 1
            continue
        fl = _fill_line(lines, i)
        if fl:
            out.append(fl[0])
            i = fl[1]
            continue
        cm = _CALLOUT_RE.match(ln)
        if cm:
            kind, title = cm.group(2), cm.group(3)
            out.append(cm.group(1) + "**" + kind + "**" + ((" " + title) if title else ""))
            i += 1
            continue
        fb = _figure_block(ln, img_align)
        if fb is not None:
            out.extend(fb)
            i += 1
            continue
        out.append(_brace_scripts(_norm_img_params(_figure_caption(ln))))
        i += 1
    return "\n".join(out)


def inject_run_outputs(md_text, blocks):
    """按 (语言, 代码原文) 把已存档的运行结果插到对应围栏块之后；未命中不动。

    围栏扫描与 prepare_markdown 同一套规则（``` 与 ~~~ 各自配对、带参数的
    围栏整块跳过），不会把围栏内部当正文再判一次。
    文字输出落成 ```output 代码块（等宽呈现），图片按 {80} 宽插成图片。
    """
    want = {}
    for b in blocks or []:
        want[(b.get("lang") or "", (b.get("code") or "").strip("\n"))] = b
    if not want:
        return md_text
    lines = md_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        mark = m.group(2)
        info = (m.group(3) or "").strip()
        lang = info.split()[0].lower() if info else ""
        close_re = re.compile(r"^\s*" + re.escape(mark) + r"\s*$")
        body, j = [], i + 1
        while j < len(lines) and not close_re.match(lines[j]):
            body.append(lines[j])
            j += 1
        if j >= len(lines):                 # 未闭合：原样输出，不猜
            out.extend(lines[i:])
            break
        out.extend(lines[i:j + 1])          # 围栏本身原封不动
        hit = want.get((lang, "\n".join(body).strip("\n"))) if lang in ("r", "python") else None
        if hit:
            if hit.get("error"):
                out.append("```output")
                out.append("[错误] " + hit["error"])
                if hit.get("stdout"):
                    out.extend(hit["stdout"].rstrip("\n").split("\n"))
                out.append("```")
            elif hit.get("stdout"):
                out.append("```output")
                out.extend(hit["stdout"].rstrip("\n").split("\n"))
                out.append("```")
            img = hit.get("imageAbs") or hit.get("image")
            if img:
                out.append("")
                out.append('![运行输出](<%s>){80}' % str(img).replace("\\", "/"))
            out.append("")
        i = j + 1
    return "\n".join(out)


_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_TBL_PR_ORDER = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
                 "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd",
                 "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook"]
_TC_PR_ORDER = ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd",
                "noWrap", "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark"]
# sectPr 里排在 pgSz / pgMar 之后的元素（OOXML 顺序；顺序不合会让 Word 报文件损坏）
_SECT_AFTER_PAGE = ("paperSrc", "pgBorders", "lnNumType", "pgNumType", "cols",
                    "formProt", "vAlign", "noEndnote", "titlePg", "textDirection",
                    "bidi", "rtlGutter", "docGrid", "printerSettings", "sectPrChange")
# styles.xml 里 pPr / rPr 子元素的 schema 顺序（插入位置据此算）
_PPR_ORDER = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
              "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs",
              "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct",
              "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
              "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents",
              "suppressOverlap", "jc", "textDirection", "textAlignment",
              "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr",
              "pPrChange"]
_RPR_ORDER = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps",
              "strike", "dstrike", "outline", "shadow", "emboss", "imprint",
              "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
              "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
              "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
              "eastAsianLayout", "specVanish", "oMath"]


def _insert_ordered(parent, child, order):
    """按 OOXML 子元素顺序插入（顺序不合 schema 会让 Word 报「文件已损坏」）。"""
    tag = child.tag.split("}")[-1]
    idx = order.index(tag) if tag in order else len(order)
    for i, el in enumerate(list(parent)):
        t = el.tag.split("}")[-1]
        if t in order and order.index(t) > idx:
            parent.insert(i, child)
            return
    parent.append(child)


# ── Word 版面：纸张与页边距 ──────────────────────────────────────────
# pandoc 的 sectPr 只写脚注设置，不写 pgSz / pgMar：成品打开时纸张与边距由
# Word 的本机默认值决定，和排版面板的 A4 + 25/18/25/18mm 对不上。这里按面板
# 写死，导出物的版面才是确定的。
_MM2TW = 1440.0 / 25.4                    # 1in = 25.4mm = 1440twips
_PAGE_DEFAULT = {"w": 210.0, "h": 297.0, "mt": 25.0, "mr": 18.0,
                 "mb": 25.0, "ml": 18.0}
_PAGE_LIMIT = {"w": (40.0, 2000.0), "h": (40.0, 2000.0),
               "mt": (0.0, 200.0), "mr": (0.0, 200.0),
               "mb": (0.0, 200.0), "ml": (0.0, 200.0)}


def _page_box(page):
    """页面配置 → mm 数值盒子；任何一项不合法就整盒回落 A4 + 默认边距。

    整盒回落而不是逐项回落：半个自定义纸张配半个默认边距会得到版心不可预期的
    文档，不如给一份确定的 A4。版心（纸宽减左右、纸高减上下）不足 20mm 同样回落。
    """
    p = page if isinstance(page, dict) else {}
    box = {}
    for k, default in _PAGE_DEFAULT.items():
        try:
            v = float(p.get(k, default))
        except (TypeError, ValueError):
            return dict(_PAGE_DEFAULT)
        lo, hi = _PAGE_LIMIT[k]
        if not lo <= v <= hi:
            return dict(_PAGE_DEFAULT)
        box[k] = v
    if box["w"] - box["ml"] - box["mr"] < 20 or box["h"] - box["mt"] - box["mb"] < 20:
        return dict(_PAGE_DEFAULT)
    return box


def _sectpr_xml(xml, box):
    """把 pgSz / pgMar 写进唯一那个 sectPr（字符串级改写，不动其它字节）。"""
    pg_sz = ('<w:pgSz w:w="%d" w:h="%d"/>'
             % (round(box["w"] * _MM2TW), round(box["h"] * _MM2TW)))
    pg_mar = ('<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" '
              'w:header="720" w:footer="720" w:gutter="0"/>'
              % (round(box["mt"] * _MM2TW), round(box["mr"] * _MM2TW),
                 round(box["mb"] * _MM2TW), round(box["ml"] * _MM2TW)))
    page_xml = pg_sz + pg_mar

    m = re.search(r"<w:sectPr\b[^>]*>", xml)
    if not m:
        # pandoc 正常会写 sectPr；真没有就补一个，别把版面丢了
        if "</w:body>" not in xml:
            return xml
        return xml.replace("</w:body>", "<w:sectPr>" + page_xml + "</w:sectPr></w:body>", 1)
    end = xml.find("</w:sectPr>", m.end())
    if end < 0:                            # 自闭合 `<w:sectPr/>` 的兜底
        whole = re.search(r"<w:sectPr\b[^>]*/>", xml)
        if not whole:
            return xml
        new = whole.group(0)[:-2] + ">" + page_xml + "</w:sectPr>"
        return xml[:whole.start()] + new + xml[whole.end():]
    inner = xml[m.end():end]
    # 已有 pgSz / pgMar 先摘掉，避免同一个 sectPr 里出现两份
    inner = re.sub(r"<w:pgSz\b[^>]*/>|<w:pgSz\b[^>]*>.*?</w:pgSz>", "", inner, flags=re.S)
    inner = re.sub(r"<w:pgMar\b[^>]*/>|<w:pgMar\b[^>]*>.*?</w:pgMar>", "", inner, flags=re.S)
    pos = len(inner)
    for tag in _SECT_AFTER_PAGE:
        i = inner.find("<w:" + tag)
        if 0 <= i < pos:
            pos = i
    return xml[:m.end()] + inner[:pos] + page_xml + inner[pos:] + xml[end:]


def set_docx_page(docx_path, page, pandoc_exe="", verify_dir=""):
    """按排版面板的纸张/边距改写 sectPr。返回实际生效的 mm 盒子。

    落盘走 `.part` + 可选 pandoc 回读自检（与字体、三线表同一套规矩）：读不回来
    就抛错，目标文件保持原样。
    """
    box = _page_box(page)
    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        raw = z.read("word/document.xml").decode("utf-8")
        others = {n: z.read(n) for n in names if n != "word/document.xml"}
    new_doc = _sectpr_xml(raw, box)
    if "<w:pgSz" not in new_doc:
        raise RuntimeError("版面改写未生效（document.xml 里找不到 sectPr）")

    tmp = os.path.join(os.path.dirname(os.path.abspath(docx_path)),
                       ".mdeditor-page-%s.docx.part" % uuid.uuid4().hex[:8])
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, new_doc.encode("utf-8") if n == "word/document.xml" else others[n])
    _verify_docx(tmp, pandoc_exe, verify_dir, "版面改写")
    os.replace(tmp, docx_path)
    return {k: round(v, 1) for k, v in box.items()}


# ── Word 中文版式 ────────────────────────────────────────────────────
# pandoc 的默认样式是西文口径：标题蓝色、正文无缩进、代码块只是一段等宽文字。
# 中文稿要的正文缩进 / 1.5 倍行距 / 黑体黑色标题 / 代码块边框，在 styles.xml
# 里改。只动被点名的样式，不碰正文的字符级格式；与字体、版面同一套后处理。
_CN_BODY_PPR = {
    "spacing": '<w:spacing w:before="0" w:after="0" w:line="360" w:lineRule="auto"/>',
    "ind": '<w:ind w:firstLineChars="200" w:firstLine="200"/>',
}
# 样式 id -> (段前, 段后, 字号半磅)
_CN_HEADING_SIZES = {
    "Heading1": (360, 160, 36),            # 小二 18pt
    "Heading2": (300, 120, 32),            # 三号 16pt
    "Heading3": (240, 100, 30),            # 小三 15pt
    "Heading4": (180, 80, 24),             # 小四 12pt
    "Heading5": (160, 60, 24),
    "Heading6": (140, 60, 24),
}


def _cn_plan():
    """样式 id -> (pPr 改动, rPr 改动)；空串表示删掉该属性（如标题的蓝色）。"""
    def sz(n):
        return {"sz": '<w:sz w:val="%d"/>' % n, "szCs": '<w:szCs w:val="%d"/>' % n}

    plan = {
        "Normal": ({"spacing": '<w:spacing w:after="0" w:line="360" w:lineRule="auto"/>'}, None),
        "BodyText": (_CN_BODY_PPR, None),
        "FirstParagraph": (_CN_BODY_PPR, None),
        "BlockText": ({
            "pBdr": ('<w:pBdr><w:left w:val="single" w:sz="24" w:space="4" '
                     'w:color="auto"/></w:pBdr>'),
            "spacing": '<w:spacing w:before="100" w:after="100"/>',
            "ind": '<w:ind w:firstLine="0" w:firstLineChars="0" w:left="480" w:right="480"/>',
        }, None),
        "Compact": ({
            "spacing": '<w:spacing w:before="60" w:after="60"/>',
            "ind": '<w:ind w:firstLine="0" w:firstLineChars="0"/>',
        }, sz(20)),                        # 表格单元格 / 紧凑列表：五号 10pt
        "SourceCode": ({
            "pBdr": ('<w:pBdr>'
                     '<w:top w:val="single" w:sz="8" w:space="4" w:color="BFBFBF"/>'
                     '<w:left w:val="single" w:sz="8" w:space="4" w:color="BFBFBF"/>'
                     '<w:bottom w:val="single" w:sz="8" w:space="4" w:color="BFBFBF"/>'
                     '<w:right w:val="single" w:sz="8" w:space="4" w:color="BFBFBF"/>'
                     '</w:pBdr>'),
            "shd": '<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/>',
            "spacing": '<w:spacing w:before="120" w:after="120"/>',
            "ind": '<w:ind w:leftChars="300" w:left="300" w:firstLine="0" w:firstLineChars="0"/>',
        }, sz(21)),                        # 五号 10.5pt
        "VerbatimChar": (None, dict(
            {"shd": '<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/>'}, **sz(21))),
        "Caption": ({
            "spacing": '<w:spacing w:before="60" w:after="120"/>',
        }, dict({"i": "", "color": '<w:color w:val="595959"/>'}, **sz(21))),
        "ImageCaption": ({"jc": '<w:jc w:val="center"/>'}, None),
        "Figure": ({"jc": '<w:jc w:val="center"/>'}, None),
    }
    for sid, (before, after, size) in _CN_HEADING_SIZES.items():
        plan[sid] = ({
            "spacing": '<w:spacing w:before="%d" w:after="%d"/>' % (before, after),
        }, dict({"b": "<w:b/>", "bCs": "<w:bCs/>", "color": ""}, **sz(size)))
    return plan


def _upsert_xml(inner, tag, xml, order):
    """在 pPr / rPr 内部替换一个子元素，并按 schema 顺序放回。xml 为空 = 删除。"""
    inner = re.sub(r"<w:%s\b[^>]*/>|<w:%s\b[^>]*>.*?</w:%s>" % (tag, tag, tag),
                   "", inner, flags=re.S)
    if not xml:
        return inner
    idx = order.index(tag)
    pos = len(inner)
    for after in order[idx + 1:]:
        m = re.search(r"<w:%s\b" % after, inner)
        if m and m.start() < pos:
            pos = m.start()
    return inner[:pos] + xml + inner[pos:]


def _patch_style_part(block, part, items):
    """改一个 style 里的 pPr / rPr；没有该 part 就按顺序新建。"""
    order = _PPR_ORDER if part == "pPr" else _RPR_ORDER
    open_re = re.compile(r"<w:%s>(.*?)</w:%s>" % (part, part), re.S)
    m = open_re.search(block)
    if m:
        inner = m.group(1)
        for tag, xml in items.items():
            inner = _upsert_xml(inner, tag, xml, order)
        return block[:m.start(1)] + inner + block[m.end(1):]
    self_tag = "<w:%s/>" % part
    if self_tag in block:
        block = block.replace(self_tag, "<w:%s></w:%s>" % (part, part), 1)
        return _patch_style_part(block, part, items)
    new = "".join(items[t] for t in order if items.get(t))
    anchor = block.rfind("</w:style>")
    if part == "pPr":
        rpr_at = block.find("<w:rPr")
        if 0 <= rpr_at < anchor:
            anchor = rpr_at
    return block[:anchor] + "<w:%s>%s</w:%s>" % (part, new, part) + block[anchor:]


def _patch_style(styles, sid, ppr=None, rpr=None):
    m = re.search(r'<w:style [^>]*w:styleId="%s".*?</w:style>' % re.escape(sid),
                  styles, re.S)
    if not m:
        return styles
    block = m.group(0)
    if ppr:
        block = _patch_style_part(block, "pPr", ppr)
    if rpr:
        block = _patch_style_part(block, "rPr", rpr)
    return styles[:m.start()] + block + styles[m.end():]


def _verify_docx(path, pandoc_exe, verify_dir, label):
    """落盘前的结构自检：pandoc 读不回来就当失败，并删掉待落位的 .part。"""
    if not pandoc_exe:
        return
    own = not verify_dir
    work = tempfile.mkdtemp(prefix="mdeditor-%scheck-" % label) if own else verify_dir
    probe = os.path.join(work, "%scheck-%s.docx" % (label, uuid.uuid4().hex[:8]))
    try:
        shutil.copyfile(path, probe)
        r = subprocess.run([pandoc_exe, "-f", "docx", "-t", "markdown", probe],
                           capture_output=True, timeout=120, creationflags=_NO_WINDOW)
    finally:
        try:
            if os.path.exists(probe):
                os.remove(probe)
        except Exception:
            pass
        if own:
            shutil.rmtree(work, ignore_errors=True)
    if r.returncode != 0:
        try:
            os.remove(path)
        except Exception:
            pass
        raise RuntimeError("%s后 docx 结构校验失败：%s"
                           % (label, (r.stderr or b"").decode("utf-8", "replace")[:200]))


def set_docx_cn(docx_path, cn=True, pandoc_exe="", verify_dir=""):
    """把 Word 样式换成中文稿件口径（默认开启，由前端开关控制）。

    只改 styles.xml 里被点名的样式：正文缩进/行距、标题黑色与字号、代码块
    边框底纹、引用左边框、表格单元格字号、图注居中。cn=False 原样返回。
    """
    if not cn:
        return False
    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        if "word/styles.xml" not in names:
            raise RuntimeError("docx 结构异常：缺 word/styles.xml，无法套中文版式")
        styles = z.read("word/styles.xml").decode("utf-8")
        others = {n: z.read(n) for n in names if n != "word/styles.xml"}
    for sid, (ppr, rpr) in _cn_plan().items():
        styles = _patch_style(styles, sid, ppr, rpr)
    if 'firstLineChars="200"' not in styles or 'w:line="360"' not in styles:
        raise RuntimeError("中文版式改写未生效（正文缩进/行距没写进 styles.xml）")

    tmp = os.path.join(os.path.dirname(os.path.abspath(docx_path)),
                       ".mdeditor-cn-%s.docx.part" % uuid.uuid4().hex[:8])
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, styles.encode("utf-8") if n == "word/styles.xml" else others[n])
    _verify_docx(tmp, pandoc_exe, verify_dir, "中文版式改写")
    os.replace(tmp, docx_path)
    return True


# ── 独行图对齐（Word）──────────────────────────────────────────────
# markdown 的图片对齐在 Word 里是段落属性，pandoc 表达不了；prepare_markdown
# 用带 custom-style 的 Div 指定 Figure / FigureLeft / FigureRight。这里在
# styles.xml 里补齐三个样式（Figure 由 pandoc 提供，但默认不一定居中）。
_FIGURE_STYLES = (("Figure", "Figure", None, "center"),
                  ("FigureLeft", "Figure Left", "Figure", "left"),
                  ("FigureRight", "Figure Right", "Figure", "right"))


def _figure_style_xml(sid, name, based, jc):
    return ('<w:style w:type="paragraph" w:customStyle="1" w:styleId="%s">'
            '<w:name w:val="%s"/>%s<w:qFormat/>'
            '<w:pPr><w:jc w:val="%s"/></w:pPr></w:style>'
            % (sid, name, ('<w:basedOn w:val="%s"/>' % based) if based else "", jc))


def set_docx_figure_styles(docx_path, pandoc_exe="", verify_dir=""):
    """确保 Figure（居中）/ FigureLeft / FigureRight 三个段落样式存在。"""
    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        styles = z.read("word/styles.xml").decode("utf-8")
        others = {n: z.read(n) for n in names if n != "word/styles.xml"}
    for sid, name, based, jc in _FIGURE_STYLES:
        if sid == "Figure" and 'w:styleId="%s"' % sid in styles:
            # Figure 由 pandoc 提供：把居中写成显式的
            styles = _patch_style(styles, sid, {"jc": '<w:jc w:val="%s"/>' % jc}, None)
        else:
            # 左右两档 pandoc 会按 custom-style 自动建（basedOn BodyText，带首行
            # 缩进）；整块换掉，改成 basedOn Figure，图片段才不会被缩进推歪。
            styles = re.sub(r'<w:style [^>]*w:styleId="%s".*?</w:style>' % sid,
                            "", styles, flags=re.S)
            styles = styles.replace("</w:styles>",
                                    _figure_style_xml(sid, name, based, jc)
                                    + "</w:styles>", 1)
    if 'w:styleId="FigureLeft"' not in styles or 'w:styleId="FigureRight"' not in styles:
        raise RuntimeError("图片对齐样式未写入（FigureLeft / FigureRight 缺失）")

    tmp = os.path.join(os.path.dirname(os.path.abspath(docx_path)),
                       ".mdeditor-fig-%s.docx.part" % uuid.uuid4().hex[:8])
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, styles.encode("utf-8") if n == "word/styles.xml" else others[n])
    _verify_docx(tmp, pandoc_exe, verify_dir, "图片对齐样式")
    os.replace(tmp, docx_path)
    return True


# ── Word 标题自动编号 ────────────────────────────────────────────────
# 在 numbering.xml 里加一个六级 decimal 多级列表（1 / 1.1 / 1.1.1 …），
# 再把 Heading1..6 的 pPr 绑到对应 ilvl。编号是 Word 的自动编号字段：
# 增删标题、调整层级时重排，不需要（也不会）把号码写进正文文本。
_HEADING_STYLES = ["Heading1", "Heading2", "Heading3",
                   "Heading4", "Heading5", "Heading6"]


def _heading_abstract_num(aid):
    """六级多级列表；pStyle 把每一级绑到对应的标题样式。"""
    lvls = []
    for i, sid in enumerate(_HEADING_STYLES):
        text = ".".join("%%%d" % (j + 1) for j in range(i + 1))
        lvls.append(
            '<w:lvl w:ilvl="%d"><w:start w:val="1"/><w:numFmt w:val="decimal"/>'
            '<w:pStyle w:val="%s"/><w:suff w:val="space"/>'
            '<w:lvlText w:val="%s"/><w:lvlJc w:val="left"/>'
            '<w:pPr><w:ind w:left="0" w:firstLine="0"/></w:pPr></w:lvl>'
            % (i, sid, text))
    return ('<w:abstractNum w:abstractNumId="%d"><w:nsid w:val="%s"/>'
            '<w:multiLevelType w:val="multilevel"/><w:tmpl w:val="%s"/>%s'
            '</w:abstractNum>'
            % (aid, uuid.uuid4().hex[:8].upper(), uuid.uuid4().hex[:8].upper(),
               "".join(lvls)))


def _ensure_numbering_part(ct, rels):
    """numbering.xml 若不在包里，补内容类型与关系（正常 pandoc 都会带）。"""
    if 'PartName="/word/numbering.xml"' not in ct:
        ct = ct.replace(
            "</Types>",
            '<Override PartName="/word/numbering.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
            "</Types>", 1)
    if 'Target="numbering.xml"' not in rels:
        used = set(re.findall(r'\bId="([^"]+)"', rels))
        rid = "rIdNum1"
        while rid in used:
            rid += "x"
        rels = rels.replace(
            "</Relationships>",
            '<Relationship Id="%s" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
            "</Relationships>" % rid, 1)
    return ct, rels


def set_docx_heading_numbers(docx_path, on=True, pandoc_exe="", verify_dir=""):
    """给 Heading1..6 加自动编号（1 / 1.1 / …）。on=False 原样返回。"""
    if not on:
        return False
    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        items = {n: z.read(n) for n in names}
    numbering = items.get("word/numbering.xml")
    numbering = numbering.decode("utf-8") if numbering else None
    styles = items["word/styles.xml"].decode("utf-8")
    ct = items["[Content_Types].xml"].decode("utf-8")
    rels = items["word/_rels/document.xml.rels"].decode("utf-8")

    if numbering:
        aids = [int(x) for x in re.findall(r'<w:abstractNum [^>]*'
                                           r'w:abstractNumId="(\d+)"', numbering)]
        nids = [int(x) for x in re.findall(r'<w:num [^>]*w:numId="(\d+)"', numbering)]
    else:
        numbering = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<w:numbering xmlns:w="%s"></w:numbering>' % _W_NS)
        aids, nids = [], []
    aid = max(aids or [0]) + 1
    nid = max(nids or [0]) + 1
    abs_xml = _heading_abstract_num(aid)
    num_xml = ('<w:num w:numId="%d"><w:abstractNumId w:val="%d"/></w:num>'
               % (nid, aid))
    first_num = re.search(r"<w:num\b", numbering)
    if first_num:
        numbering = numbering[:first_num.start()] + abs_xml + numbering[first_num.start():]
    else:
        numbering = numbering.replace("</w:numbering>", abs_xml + "</w:numbering>", 1)
    numbering = numbering.replace("</w:numbering>", num_xml + "</w:numbering>", 1)
    if 'w:abstractNumId="%d"' % aid not in numbering:
        raise RuntimeError("标题编号未生效（abstractNum 没写进 numbering.xml）")

    for i, sid in enumerate(_HEADING_STYLES):
        styles = _patch_style(styles, sid, {
            "numPr": ('<w:numPr><w:ilvl w:val="%d"/><w:numId w:val="%d"/></w:numPr>'
                      % (i, nid))}, None)
    if 'w:numId w:val="%d"' % nid not in styles:
        raise RuntimeError("标题编号未生效（标题样式没有绑上 numPr）")

    ct, rels = _ensure_numbering_part(ct, rels)
    items["word/numbering.xml"] = numbering.encode("utf-8")
    items["word/styles.xml"] = styles.encode("utf-8")
    items["[Content_Types].xml"] = ct.encode("utf-8")
    items["word/_rels/document.xml.rels"] = rels.encode("utf-8")
    if "word/numbering.xml" not in names:
        names = names + ["word/numbering.xml"]

    tmp = os.path.join(os.path.dirname(os.path.abspath(docx_path)),
                       ".mdeditor-num-%s.docx.part" % uuid.uuid4().hex[:8])
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, items[n])
    _verify_docx(tmp, pandoc_exe, verify_dir, "标题编号改写")
    os.replace(tmp, docx_path)
    return True


# ── Word 页码 ────────────────────────────────────────────────────────
# 页码是 Word 的域（PAGE / NUMPAGES），必须落在页眉/页脚部件的段落里，再由
# sectPr 引用。面板的「分页 → 页码」原本只喂给 Paged.js；这里把同一份配置
# （位置 / 模板 / 字号）翻译成 Word 的 footer/header 部件。
_PN_POS = {"bc": ("footer", "center"), "bl": ("footer", "left"),
           "br": ("footer", "right"), "tc": ("header", "center"),
           "tr": ("header", "right")}
_PN_FONT_COLOR = "595959"


def _xml_text(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _pn_runs(tpl, half_pt):
    """模板文字 + PAGE/NUMPAGES 域；域缓存值先写 1，Word 打开时更新。"""
    rpr = ('<w:rPr><w:sz w:val="%d"/><w:szCs w:val="%d"/>'
           '<w:color w:val="%s"/></w:rPr>' % (half_pt, half_pt, _PN_FONT_COLOR))
    runs = []
    for part in re.split(r"(\{p\}|\{P\})", tpl):
        if not part:
            continue
        if part in ("{p}", "{P}"):
            instr = "PAGE" if part == "{p}" else "NUMPAGES"
            runs.append('<w:r>%s<w:fldChar w:fldCharType="begin"/></w:r>' % rpr)
            runs.append('<w:r>%s<w:instrText xml:space="preserve"> %s </w:instrText></w:r>'
                        % (rpr, instr))
            runs.append('<w:r>%s<w:fldChar w:fldCharType="separate"/></w:r>' % rpr)
            runs.append('<w:r>%s<w:t>1</w:t></w:r>' % rpr)
            runs.append('<w:r>%s<w:fldChar w:fldCharType="end"/></w:r>' % rpr)
        else:
            runs.append('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>'
                        % (rpr, _xml_text(part)))
    return "".join(runs)


def _pn_part_xml(kind, jc, tpl, half_pt):
    tag = "ftr" if kind == "footer" else "hdr"
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:%s xmlns:w="%s" xmlns:r="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships">'
            '<w:p><w:pPr><w:jc w:val="%s"/></w:pPr>%s</w:p></w:p></w:%s>'
            % (tag, _W_NS, jc, _pn_runs(tpl, half_pt), tag))


def _new_part_name(names, base):
    used = set(n.lower() for n in names)
    i = 1
    while ("word/%s%d.xml" % (base, i)).lower() in used:
        i += 1
    return "word/%s%d.xml" % (base, i)


def _new_rel_id(rels, prefix):
    used = set(re.findall(r'\bId="([^"]+)"', rels))
    i = 1
    while (prefix + str(i)) in used:
        i += 1
    return prefix + str(i)


def _settings_add(settings, even):
    def before_compat(xml):
        at = settings_cut.find("<w:compat")
        if at >= 0:
            return settings_cut[:at] + xml + settings_cut[at:]
        return settings_cut.replace("</w:settings>", xml + "</w:settings>", 1)

    settings_cut = settings
    if even and "<w:evenAndOddHeaders" not in settings_cut:
        settings = before_compat("<w:evenAndOddHeaders/>")
        settings_cut = settings
    if "<w:updateFields" not in settings_cut:
        settings = before_compat('<w:updateFields w:val="true"/>')
    return settings


def set_docx_page_numbers(docx_path, pn, pandoc_exe="", verify_dir=""):
    """按「分页 → 页码」写 Word 页眉/页脚。pn.on != "on" 时原样返回。"""
    if not isinstance(pn, dict) or pn.get("on") != "on":
        return False
    pos = str(pn.get("pos") or "bc")
    if pos not in _PN_POS and pos != "outer":
        pos = "bc"
    try:
        size = float(pn.get("size", 9))
    except (TypeError, ValueError):
        size = 9.0
    size = min(24.0, max(6.0, size))
    half_pt = int(round(size * 2))
    tpl = str(pn.get("tpl") or "{p}")[:80]
    if "{p}" not in tpl and "{P}" not in tpl:
        tpl = "{p}"

    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        items = {n: z.read(n) for n in names}
    rels = items["word/_rels/document.xml.rels"].decode("utf-8")
    ct = items["[Content_Types].xml"].decode("utf-8")
    settings = items["word/settings.xml"].decode("utf-8")
    doc = items["word/document.xml"].decode("utf-8")

    # (部件种类, sectPr 里的引用类型, 对齐)：outer = 奇数页右、偶数页左
    if pos == "outer":
        plan = [("footer", "default", "right"), ("footer", "even", "left")]
    else:
        kind, jc = _PN_POS[pos]
        plan = [(kind, "default", jc)]

    refs = []
    for kind, ref_type, jc in plan:
        part_name = _new_part_name(names, kind)
        items[part_name] = _pn_part_xml(kind, jc, tpl, half_pt).encode("utf-8")
        names = names + [part_name]
        rid = _new_rel_id(rels, "rIdFooter" if kind == "footer" else "rIdHeader")
        rels = rels.replace(
            "</Relationships>",
            '<Relationship Id="%s" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/%s" Target="%s"/></Relationships>'
            % (rid, kind, part_name[len("word/"):]), 1)
        ct = ct.replace(
            "</Types>",
            '<Override PartName="/%s" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.%s+xml"/></Types>' % (part_name, kind), 1)
        refs.append('<w:%sReference w:type="%s" r:id="%s"/>' % (kind, ref_type, rid))
        if "<w:%sReference" % kind in doc:
            doc = re.sub(r'<w:%sReference\b[^>]*/>' % kind, "", doc)

    m = re.search(r"<w:sectPr\b[^>]*>", doc)
    if not m:
        raise RuntimeError("页码写入失败：document.xml 里找不到 sectPr")
    doc = doc[:m.end()] + "".join(refs) + doc[m.end():]
    settings = _settings_add(settings, pos == "outer")

    for name, data in (("word/document.xml", doc.encode("utf-8")),
                       ("word/_rels/document.xml.rels", rels.encode("utf-8")),
                       ("[Content_Types].xml", ct.encode("utf-8")),
                       ("word/settings.xml", settings.encode("utf-8"))):
        items[name] = data
    if "<w:footerReference" not in doc and "<w:headerReference" not in doc:
        raise RuntimeError("页码写入失败（sectPr 没有页眉页脚引用）")

    tmp = os.path.join(os.path.dirname(os.path.abspath(docx_path)),
                       ".mdeditor-pn-%s.docx.part" % uuid.uuid4().hex[:8])
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, items[n])
    _verify_docx(tmp, pandoc_exe, verify_dir, "页码改写")
    os.replace(tmp, docx_path)
    return True


def set_docx_update_fields(docx_path, pandoc_exe="", verify_dir=""):
    """在 settings.xml 里打开 updateFields（TOC / 页码域在 Word 打开时刷新）。"""
    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        settings = z.read("word/settings.xml").decode("utf-8")
        others = {n: z.read(n) for n in names if n != "word/settings.xml"}
    if "<w:updateFields" in settings:
        return False
    settings = _settings_add(settings, False)
    tmp = os.path.join(os.path.dirname(os.path.abspath(docx_path)),
                       ".mdeditor-fields-%s.docx.part" % uuid.uuid4().hex[:8])
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, settings.encode("utf-8") if n == "word/settings.xml" else others[n])
    _verify_docx(tmp, pandoc_exe, verify_dir, "更新域设置")
    os.replace(tmp, docx_path)
    return True


def three_line_tables(docx_path, pandoc_exe, header_fill="", borders=True, center=True):
    """把 docx 里所有表格改成三线表（上/下 + 表头下，共三条线，无竖线）。

    直接改 word/document.xml：pandoc 只写 tblStyle、不写任何显式边框，
    改样式表就得随包一个 reference.docx（还不能按开关生效），所以选改 XML。
    改完用 pandoc 回读一次做结构自检——读不出即判失败，绝不落一个打不开的文件。

    header_fill：表头底色（`#RRGGBB` 或 `RRGGBB`）。空值或脏值不写，
    预览里「表头底色」是默认开的，这里由调用方传面板值，保持两边一致。
    borders=False：只写表头底色，不注入三线表边框（预览里两个开关互相独立）。
    center：表格整体居中（`tblPr/jc`）。pandoc 默认左对齐，中文稿的表格通常居中；
    与 borders / fill 互不影响，关掉三线表也照样居中。
    """
    import xml.etree.ElementTree as ET

    fill = ""
    if isinstance(header_fill, str):
        m = re.fullmatch(r"#?([0-9A-Fa-f]{6})", header_fill.strip())
        if m:
            fill = m.group(1).upper()

    def q(tag):
        return "{%s}%s" % (_W_NS, tag)

    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        raw = z.read("word/document.xml")
        others = {n: z.read(n) for n in names if n != "word/document.xml"}
    ET.register_namespace("w", _W_NS)
    root = ET.fromstring(raw)
    tables = list(root.iter(q("tbl")))
    if not tables:
        return
    for tbl in tables:
        pr = tbl.find(q("tblPr"))
        if (borders or center) and pr is None:
            pr = ET.Element(q("tblPr"))
            tbl.insert(0, pr)
        if center and pr is not None:
            oldjc = pr.find(q("jc"))
            if oldjc is not None:
                pr.remove(oldjc)
            jc = ET.Element(q("jc"))
            jc.set(q("val"), "center")
            _insert_ordered(pr, jc, _TBL_PR_ORDER)
        if borders and pr is not None:
            old = pr.find(q("tblBorders"))
            if old is not None:
                pr.remove(old)
            tbl_borders = ET.Element(q("tblBorders"))
            for side, sz in (("top", "12"), ("left", "0"), ("bottom", "12"),
                             ("right", "0"), ("insideH", "0"), ("insideV", "0")):
                el = ET.SubElement(tbl_borders, q(side))
                el.set(q("val"), "single" if sz != "0" else "none")
                el.set(q("sz"), sz)
                el.set(q("space"), "0")
                el.set(q("color"), "auto")
            _insert_ordered(pr, tbl_borders, _TBL_PR_ORDER)
        first_tr = tbl.find(q("tr"))
        if first_tr is not None and (borders or fill):
            for tc in first_tr.findall(q("tc")):
                tcpr = tc.find(q("tcPr"))
                if tcpr is None:
                    tcpr = ET.Element(q("tcPr"))
                    tc.insert(0, tcpr)
                if borders:
                    oldb = tcpr.find(q("tcBorders"))
                    if oldb is not None:
                        tcpr.remove(oldb)
                    tb = ET.Element(q("tcBorders"))
                    bottom = ET.SubElement(tb, q("bottom"))
                    bottom.set(q("val"), "single")
                    bottom.set(q("sz"), "8")
                    bottom.set(q("space"), "0")
                    bottom.set(q("color"), "auto")
                    _insert_ordered(tcpr, tb, _TC_PR_ORDER)
                if fill:
                    olds = tcpr.find(q("shd"))
                    if olds is not None:
                        tcpr.remove(olds)
                    shd = ET.Element(q("shd"))
                    shd.set(q("val"), "clear")
                    shd.set(q("color"), "auto")
                    shd.set(q("fill"), fill)
                    _insert_ordered(tcpr, shd, _TC_PR_ORDER)
    new_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    tmp = docx_path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, new_xml if n == "word/document.xml" else others[n])
    os.replace(tmp, docx_path)

    r = subprocess.run([pandoc_exe, "-f", "docx", "-t", "markdown", docx_path],
                       capture_output=True, timeout=120, creationflags=_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("三线表改写后 docx 结构校验失败：%s"
                           % (r.stderr or b"").decode("utf-8", "replace")[:200])


# ── Word 导出字体 ────────────────────────────────────────────────────
# pandoc 的参考文档把字体整个交给主题（asciiTheme / eastAsiaTheme），落到 Word 里
# 是 Aptos / 等线 一类，不是中文文稿要的「宋体 + Times New Roman」。导出后把主题
# 引用改写成语义相当的显式字体名：白纸黑字写进 styles.xml，Word 没得再挑主题。
#
# 主题分两族，正好对上中文稿的两档：majorFont = 标题（Heading* 用的都是它），
# minorFont = 正文（docDefaults 与 Body Text 等）。所以既能给出「标题黑体 / 正文
# 宋体」，又不用逐个样式列表——判据就是原属性值开头是 major 还是 minor。
DEFAULT_LATIN_FONT = "Times New Roman"
DEFAULT_CJK_FONT = "SimSun"
DEFAULT_HEADING_CJK_FONT = "SimHei"
# 代码块（Verbatim Char）本来就是显式 Consolas，不走主题；因此天然保持等宽。
CODE_FONT = "Consolas"

# 主题属性 → 对应的显式属性槽；中文只认 eastAsia，其余三槽都是西文
_THEME_SLOT = {"asciiTheme": "ascii", "hAnsiTheme": "hAnsi",
               "eastAsiaTheme": "eastAsia", "cstheme": "cs"}
_THEME_ATTR_RE = re.compile(r'w:(asciiTheme|hAnsiTheme|eastAsiaTheme|cstheme)="([^"]*)"')
_THEME_LEFT_RE = re.compile(r'w:(?:ascii|hAnsi|eastAsia|cs)Theme=')
_BAD_FONT_CHARS = set('<>"\'&{}[],\\\r\n\t')
_FONT_ELEM_RE = {
    "latin": re.compile(r'(<a:latin\b[^>]*\btypeface=")[^"]*(")'),
    "ea": re.compile(r'(<a:ea\b[^>]*\btypeface=")[^"]*(")'),
}
_FONT_HANS_RE = re.compile(r'(<a:font\b[^>]*\bscript="(?:Hans|Hant)"[^>]*\btypeface=")[^"]*(")')


def _clean_font_name(name, fallback):
    """字体名要落进 XML 属性：只收安全字符，脏值一律回落默认（不报错、不写坏文件）。"""
    s = (name or "").strip()
    if not s or len(s) > 64 or (_BAD_FONT_CHARS & set(s)):
        return fallback
    return s


def _sub_fonts_in(block, latin, cjk):
    """把一段 theme 字体定义里的 latin / ea / Hans 条目换成给定字体。"""
    for key, val in (("latin", latin), ("ea", cjk)):
        block = _FONT_ELEM_RE[key].sub(lambda m, v=val: m.group(1) + v + m.group(2), block)
    return _FONT_HANS_RE.sub(lambda m: m.group(1) + cjk + m.group(2), block)


def _theme_fonts_xml(xml, latin, cjk, heading_cjk):
    """styles.xml / theme1.xml 的主题字体引用 → 显式字体名（逐字符串替换，不动命名空间）。"""
    def repl(m):
        slot = _THEME_SLOT[m.group(1)]
        # major* = 标题档，minor* = 正文档；西文两档共用同一个值
        head = m.group(2).lower().startswith("major")
        return 'w:%s="%s"' % (slot, (heading_cjk if head else cjk)
                              if slot == "eastAsia" else latin)

    xml = _THEME_ATTR_RE.sub(repl, xml)
    # 主题里的 major/minorFont 块（styles.xml 没有这两块，替换自然空转）
    for tag, cjk_font in (("majorFont", heading_cjk), ("minorFont", cjk)):
        xml = re.sub(r'(<a:%s>)(.*?)(</a:%s>)' % (tag, tag),
                     lambda m, f=cjk_font: (m.group(1) + _sub_fonts_in(m.group(2), latin, f)
                                            + m.group(3)),
                     xml, flags=re.S)
    return xml


def set_docx_fonts(docx_path, latin="", cjk="", heading_cjk="", pandoc_exe="",
                   verify_dir=""):
    """把 docx 的字体改成「西文 latin / 正文中文 cjk / 标题中文 heading_cjk」。

    改两处（与三线表改 document.xml 互不干扰）：

    - `word/styles.xml`：所有 `<w:rFonts>` 的 `*Theme` 属性换成显式字体名——引用
      majorFont 的（各级标题）落到 heading_cjk，引用 minorFont 的（正文根，即
      docDefaults）落到 cjk。
    - `word/theme/theme1.xml`：major/minorFont 两组同步改写，兜底
      「导出后在 Word 里新插内容」的字体。

    显式的非主题字体一律不动 —— Verbatim Char 的 Consolas 由此保持等宽。
    落盘走 `.part` + pandoc 回读自检：读不回来就抛错，目标文件保持原样。
    `verify_dir` 是回读用的临时目录（导出流程传自己的临时目录）：回读读的是
    **临时副本**，文档目录里只写不读；不给就自己开一个。
    """
    latin = _clean_font_name(latin, DEFAULT_LATIN_FONT)
    cjk = _clean_font_name(cjk, DEFAULT_CJK_FONT)
    heading_cjk = _clean_font_name(heading_cjk, DEFAULT_HEADING_CJK_FONT)
    theme_name = "word/theme/theme1.xml"
    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        if "word/styles.xml" not in names:
            raise RuntimeError("docx 结构异常：缺 word/styles.xml，无法设置字体")
        styles = z.read("word/styles.xml").decode("utf-8")
        theme = z.read(theme_name).decode("utf-8") if theme_name in names else None
        others = {n: z.read(n) for n in names
                  if n not in ("word/styles.xml", theme_name)}

    new_styles = _theme_fonts_xml(styles, latin, cjk, heading_cjk)
    if (_THEME_LEFT_RE.search(new_styles)
            or ('w:eastAsia="%s"' % cjk) not in new_styles
            or ('w:ascii="%s"' % latin) not in new_styles):
        raise RuntimeError("字体改写未生效（styles.xml 主题属性未被完全替换）")
    others["word/styles.xml"] = new_styles.encode("utf-8")
    if theme:
        others[theme_name] = _theme_fonts_xml(theme, latin, cjk, heading_cjk).encode("utf-8")

    tmp = os.path.join(os.path.dirname(os.path.abspath(docx_path)),
                       ".mdeditor-font-%s.docx.part" % uuid.uuid4().hex[:8])
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, others[n])
    _verify_docx(tmp, pandoc_exe, verify_dir, "字体改写")
    os.replace(tmp, docx_path)
    return latin, cjk, heading_cjk


def _workdir_for(md_path):
    """图片相对路径的基准：普通 .md 用所在目录；.smd 用解包目录（包内 assets 才可见）。"""
    if not md_path:
        return ""
    try:
        import _smd
        if _smd.is_smd(md_path):
            return _smd.base_dir_for(md_path)
    except Exception:
        pass
    return os.path.dirname(os.path.abspath(md_path))


_SVG_EXT_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"
_ASVG_NS = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"


def _inject_svg_diagrams(docx_path, png_sha_to_svg):
    """给图表 PNG 补一份 SVG 子图：Word 2016+ 用矢量显示，旧版/其它阅读器回退 PNG。

    pandoc 对 SVG→docx 的支持随版本变化（3.8 会嵌 SVG，但缺 rsvg-convert 时不留
    PNG fallback；2.x 直接不支持）。这里不依赖它：先让 pandoc 正常嵌位图，再在
    生成好的 docx 上做后处理，把同一张图的 SVG 作为 `<asvg:svgBlip>` 扩展挂上去，
    PNG 继续留作 fallback。按 PNG 字节的 sha256 匹配，不依赖 pandoc 起的媒体名。
    """
    if not png_sha_to_svg:
        return 0
    with zipfile.ZipFile(docx_path) as z:
        items = {n: z.read(n) for n in z.namelist()}
    doc = items.get("word/document.xml")
    rels = items.get("word/_rels/document.xml.rels")
    ct = items.get("[Content_Types].xml")
    if doc is None or rels is None or ct is None:
        return 0
    doc_s = doc.decode("utf-8")
    rels_s = rels.decode("utf-8")
    ct_s = ct.decode("utf-8")

    # 关系表：目标（media/xxx.png）→ rId；pandoc 的图片关系都指向 media/
    rel_by_target = {}
    for tag in re.findall(r"<Relationship\b[^>]*/>", rels_s):
        mid = re.search(r'\bId="([^"]+)"', tag)
        mtarget = re.search(r'\bTarget="([^"]+)"', tag)
        if mid and mtarget:
            rel_by_target[mtarget.group(1)] = mid.group(1)

    injected = 0
    new_rels = []
    used_ids = set(rel_by_target.values())
    for name in sorted(items.keys()):
        if not name.startswith("word/media/") or not name.lower().endswith(".png"):
            continue
        svg = png_sha_to_svg.get(hashlib.sha256(items[name]).digest())
        if not svg:
            continue
        target = name[len("word/"):]                 # media/rId9.png
        png_rid = rel_by_target.get(target)
        if not png_rid:
            continue
        svg_name = "word/media/diagram-svg-%02d.svg" % injected
        bump = 0
        while svg_name in items:
            bump += 1
            svg_name = "word/media/diagram-svg-%02d-%d.svg" % (injected, bump)
        items[svg_name] = svg
        svg_rid = "rIdSvg%d" % (injected + 1)
        while svg_rid in used_ids:
            svg_rid += "x"
        used_ids.add(svg_rid)
        new_rels.append(
            '<Relationship Id="%s" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/image" Target="%s"/>'
            % (svg_rid, svg_name[len("word/"):]))

        pat = re.compile(
            r'(<a:blip\b[^>]*\br:embed="%s"[^>]*?)(/>|>(.*?)</a:blip>)'
            % re.escape(png_rid), re.S)
        ext = ('<a:ext uri="%s"><asvg:svgBlip xmlns:asvg="%s" r:embed="%s"/></a:ext>'
               % (_SVG_EXT_URI, _ASVG_NS, svg_rid))

        def _sub(m, ext=ext):
            if m.group(2) == "/>":
                return (m.group(1) + "><a:extLst>" + ext +
                        "</a:extLst></a:blip>")
            inner = m.group(3) or ""
            if "<a:extLst>" in inner:
                inner = inner.replace("</a:extLst>", ext + "</a:extLst>", 1)
            else:
                inner += "<a:extLst>" + ext + "</a:extLst>"
            return m.group(1) + ">" + inner + "</a:blip>"

        new_doc, count = pat.subn(_sub, doc_s)
        if count:
            doc_s = new_doc
            injected += 1
    if not injected:
        return 0
    if 'Extension="svg"' not in ct_s:
        ct_s = ct_s.replace(
            "</Types>",
            '<Default Extension="svg" ContentType="image/svg+xml"/></Types>', 1)
    rels_s = rels_s.replace("</Relationships>",
                            "".join(new_rels) + "</Relationships>", 1)
    items["word/document.xml"] = doc_s.encode("utf-8")
    items["word/_rels/document.xml.rels"] = rels_s.encode("utf-8")
    items["[Content_Types].xml"] = ct_s.encode("utf-8")

    tmp = docx_path + ".svg.tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in items.items():
            z.writestr(n, data)
    os.replace(tmp, docx_path)
    return injected


def export_docx(md_text, md_path, out_path, configured="", diagrams=None, stats=None,
               fonts=None, page=None, cn=None, num=None, pn=None, img_align="center",
               toc=None):
    """跑 pandoc 出 docx。成功返回 pandoc 路径；失败抛 RuntimeError（文案面向用户）。

    diagrams：前端渲染好的图表位图列表（`lang` / `code` / `png`(base64) / `width`）。
    fonts：`{"latin": ..., "cjk": ..., "heading": ...}`，空值即默认 Times New Roman /
    SimSun / SimHei（heading 是标题中文档，西文两档共用 latin）；
    给了就在落位**之前**改好字体（改坏了不会留下一个半成品），实际生效值写回
    `stats["fonts"]`。不给则完全不动字体（截图等旁路调用沿用 pandoc 主题）。
    page：`{"w", "h", "mt", "mr", "mb", "ml"}`（mm），给了就写进 sectPr，实际生效
    值写回 `stats["page"]`；不给则完全不动版面（旁路调用保持原样）。
    cn：True 时套中文版式（正文缩进/行距、标题黑体黑色、代码块边框、引用左边框、
    表格单元格字号、图注居中）；不传/False 则完全不动样式。
    num：True 时给 Heading1..6 加自动编号（1 / 1.1 / …）；不传/False 不动编号。
    pn：`{"on": "on", "pos": ..., "tpl": ..., "size": ...}`，给了就写页眉/页脚页码；
    不传或 on != "on" 则不动页眉页脚。
    img_align：独行图在 Word 里的默认对齐（left / center / right）；图片自带的
    `{l}` / `{r}` / `{c}` 优先。
    toc：True 时让 pandoc 在文首插 TOC 域（1–3 级，标题「目录」），并打开
    updateFields；不传/False 不生成目录。
    图片落进本次临时目录再按绝对路径引用——不往用户文档目录扔中间文件，.smd
    解包目录也不会被污染。stats 若给了 dict，会写入 `diagrams`：真正嵌进 Word
    的张数，供前端提示「还有几张没渲染成功」。

    落盘策略（两个坑都要避开）：
    - 源码 md 放系统临时目录（不污染用户文档目录）；
    - **待落位的 docx 必须建在目标同目录**：Windows 上 `os.replace` 不能跨卷
      （C: 的 %TEMP% → D: 的文档目录会报 WinError 17），所以暂存文件放在目标目录里，
      命名带随机串隐藏，成功才 replace、失败即删。
    """
    pandoc = md_tools.find_pandoc(configured)
    if not pandoc:
        raise RuntimeError("未检测到 pandoc.exe：请安装 pandoc"
                           "（winget install JohnMacFarlane.Pandoc），"
                           "或使用自带 pandoc 的 Quarto / RStudio")
    workdir = _workdir_for(md_path)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    stage = tempfile.mkdtemp(prefix="mdeditor-pandoc-")
    tmp_md = os.path.join(stage, "src.md")
    staged_out = os.path.join(out_dir, ".mdeditor-%s.docx.part" % uuid.uuid4().hex[:10])
    dmap = {}
    svg_map = {}          # sha256(PNG 字节) -> SVG 字节：导出后给同一张图补矢量子图
    try:
        for idx, item in enumerate(diagrams or []):
            item = item if isinstance(item, dict) else {}
            b64 = item.get("png") or ""
            if b64.startswith("data:"):
                b64 = b64.split(",", 1)[-1]
            try:
                raw = base64.b64decode(b64)
            except Exception:
                continue
            if not raw:
                continue
            p = os.path.join(stage, "diagram_%02d.png" % idx)
            with open(p, "wb") as f:
                f.write(raw)
            svg_text = item.get("svg") or ""
            if isinstance(svg_text, str) and svg_text.lstrip().startswith("<svg"):
                svg_map[hashlib.sha256(raw).digest()] = svg_text.encode("utf-8")
            dmap[diagram_key(item.get("lang"), item.get("code"))] = {
                "path": p, "width": item.get("width")}
        prepared = prepare_markdown(md_text, dmap, img_align)
        if stats is not None:
            stats["diagrams"] = (count_diagram_fences(md_text)
                                 - count_diagram_fences(prepared))
        with open(tmp_md, "w", encoding="utf-8", newline="\n") as f:
            f.write(prepared)
        cmd = [pandoc, "-f", "markdown+mark", "-t", "docx", "-o", staged_out]
        if toc:
            cmd += ["--toc", "--toc-depth=3", "--metadata", "toc-title=目录"]
        if workdir:
            cmd.append("--resource-path=" + workdir)
        cmd.append(tmp_md)
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180,
                           creationflags=_NO_WINDOW)
        if r.returncode != 0 or not os.path.isfile(staged_out):
            detail = ((r.stderr or r.stdout or "").strip() or "未知错误")[:400]
            raise RuntimeError("pandoc 导出失败：%s" % detail)
        if cn:
            set_docx_cn(staged_out, True, pandoc, verify_dir=stage)
            if stats is not None:
                stats["docxCn"] = True
        if num:
            set_docx_heading_numbers(staged_out, True, pandoc, verify_dir=stage)
            if stats is not None:
                stats["docxNumbering"] = True
        if 'custom-style="Figure' in prepared:
            set_docx_figure_styles(staged_out, pandoc, verify_dir=stage)
        if fonts is not None:
            f = fonts if isinstance(fonts, dict) else {}
            got = set_docx_fonts(staged_out, f.get("latin") or "", f.get("cjk") or "",
                                 f.get("heading") or "", pandoc, verify_dir=stage)
            if stats is not None:
                stats["fonts"] = {"latin": got[0], "cjk": got[1], "heading": got[2]}
        if page is not None:
            got_page = set_docx_page(staged_out, page, pandoc, verify_dir=stage)
            if stats is not None:
                stats["page"] = got_page
        if pn and set_docx_page_numbers(staged_out, pn, pandoc, verify_dir=stage):
            if stats is not None:
                stats["pageNumbers"] = True
        if toc:
            set_docx_update_fields(staged_out, pandoc, verify_dir=stage)
            if stats is not None:
                stats["docxToc"] = True
        if svg_map:
            injected = _inject_svg_diagrams(staged_out, svg_map)
            if stats is not None:
                stats["svgDiagrams"] = injected
        os.replace(staged_out, out_path)      # 同卷 → 原子落位
        return pandoc
    except PermissionError:
        raise RuntimeError("目标目录不可写：%s（多因位于 Program Files，"
                           "需管理员权限或以普通目录另存）" % out_dir)
    finally:
        try:
            if os.path.exists(staged_out):
                os.remove(staged_out)
        except Exception:
            pass
        shutil.rmtree(stage, ignore_errors=True)
