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


def prepare_markdown(src, diagrams=None):
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
                            out.append("![](<%s>){width=%d%%}"
                                       % (str(hit["path"]).replace("\\", "/"), w))
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
        out.append(_brace_scripts(_norm_img_params(ln)))
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


def three_line_tables(docx_path, pandoc_exe):
    """把 docx 里所有表格改成三线表（上/下 + 表头下，共三条线，无竖线）。

    直接改 word/document.xml：pandoc 只写 tblStyle、不写任何显式边框，
    改样式表就得随包一个 reference.docx（还不能按开关生效），所以选改 XML。
    改完用 pandoc 回读一次做结构自检——读不出即判失败，绝不落一个打不开的文件。
    """
    import xml.etree.ElementTree as ET

    def q(tag):
        return "{%s}%s" % (_W_NS, tag)

    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        raw = z.read("word/document.xml")
        others = {n: z.read(n) for n in names if n != "word/document.xml"}
    ET.register_namespace("w", _W_NS)
    root = ET.fromstring(raw)
    for tbl in root.iter(q("tbl")):
        pr = tbl.find(q("tblPr"))
        if pr is None:
            pr = ET.Element(q("tblPr"))
            tbl.insert(0, pr)
        old = pr.find(q("tblBorders"))
        if old is not None:
            pr.remove(old)
        borders = ET.Element(q("tblBorders"))
        for side, sz in (("top", "12"), ("left", "0"), ("bottom", "12"),
                         ("right", "0"), ("insideH", "0"), ("insideV", "0")):
            el = ET.SubElement(borders, q(side))
            el.set(q("val"), "single" if sz != "0" else "none")
            el.set(q("sz"), sz)
            el.set(q("space"), "0")
            el.set(q("color"), "auto")
        _insert_ordered(pr, borders, _TBL_PR_ORDER)
        first_tr = tbl.find(q("tr"))
        if first_tr is not None:
            for tc in first_tr.findall(q("tc")):
                tcpr = tc.find(q("tcPr"))
                if tcpr is None:
                    tcpr = ET.Element(q("tcPr"))
                    tc.insert(0, tcpr)
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


def export_docx(md_text, md_path, out_path, configured="", diagrams=None, stats=None):
    """跑 pandoc 出 docx。成功返回 pandoc 路径；失败抛 RuntimeError（文案面向用户）。

    diagrams：前端渲染好的图表位图列表（`lang` / `code` / `png`(base64) / `width`）。
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
            dmap[diagram_key(item.get("lang"), item.get("code"))] = {
                "path": p, "width": item.get("width")}
        prepared = prepare_markdown(md_text, dmap)
        if stats is not None:
            stats["diagrams"] = (count_diagram_fences(md_text)
                                 - count_diagram_fences(prepared))
        with open(tmp_md, "w", encoding="utf-8", newline="\n") as f:
            f.write(prepared)
        cmd = [pandoc, "-f", "markdown+mark", "-t", "docx", "-o", staged_out]
        if workdir:
            cmd.append("--resource-path=" + workdir)
        cmd.append(tmp_md)
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180,
                           creationflags=_NO_WINDOW)
        if r.returncode != 0 or not os.path.isfile(staged_out):
            detail = ((r.stderr or r.stdout or "").strip() or "未知错误")[:400]
            raise RuntimeError("pandoc 导出失败：%s" % detail)
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
