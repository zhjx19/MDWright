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
import os
import re
import subprocess
import sys

import md_tools

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_FENCE_RE = re.compile(r"^(\s*)(```|~~~)(.*)$")
_CALLOUT_RE = re.compile(r"^(\s*>\s*)\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$")
_IMG_W_RE = re.compile(r"(!\[[^\]]*\]\([^)]+\))\s*\{([1-9]\d{0,2})\}")


def _clamp(pct):
    return min(100, int(pct))


def prepare_markdown(src):
    """把本文方言改写成 pandoc 认得的 markdown（幂等，纯函数）。"""
    out = []
    fence = False
    for ln in src.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = _FENCE_RE.match(ln)
        if m:
            if not fence:
                # 开围栏：图表围栏的 `{N}` 宽度 pandoc 不认，剥掉；语言名保留
                info = re.sub(r"\s*\{[1-9]\d{0,2}\}\s*$", "", m.group(3).strip())
                out.append(m.group(1) + m.group(2) + info)
                fence = True
            else:
                out.append(ln)
                fence = False
            continue
        if fence:
            out.append(ln)              # 代码块内部一律不动
            continue
        cm = _CALLOUT_RE.match(ln)
        if cm:
            kind, title = cm.group(2), cm.group(3)
            out.append(cm.group(1) + "**" + kind + "**" + ((" " + title) if title else ""))
            continue
        out.append(_IMG_W_RE.sub(
            lambda mm: mm.group(1) + "{width=" + str(_clamp(mm.group(2))) + "%}", ln))
    return "\n".join(out)


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


def export_docx(md_text, md_path, out_path):
    """跑 pandoc 出 docx。成功返回 pandoc 路径；失败抛 RuntimeError（文案面向用户）。"""
    pandoc = md_tools.find_pandoc()
    if not pandoc:
        raise RuntimeError("未检测到 pandoc.exe：请安装 pandoc"
                           "（winget install JohnMacFarlane.Pandoc），"
                           "或使用自带 pandoc 的 Quarto / RStudio")
    workdir = _workdir_for(md_path)
    tmp_md = out_path + ".src.md"
    try:
        with open(tmp_md, "w", encoding="utf-8", newline="\n") as f:
            f.write(prepare_markdown(md_text))
        cmd = [pandoc, "-f", "markdown+mark", "-t", "docx", "-o", out_path]
        if workdir:
            cmd.append("--resource-path=" + workdir)
        cmd.append(tmp_md)
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180,
                           creationflags=_NO_WINDOW)
        if r.returncode != 0 or not os.path.isfile(out_path):
            detail = ((r.stderr or r.stdout or "").strip() or "未知错误")[:400]
            raise RuntimeError("pandoc 导出失败：%s" % detail)
        return pandoc
    finally:
        try:
            if os.path.exists(tmp_md):
                os.remove(tmp_md)
        except Exception:
            pass
