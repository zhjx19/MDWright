# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""外部工具探测：pandoc / Chromium 内核浏览器 / Rscript / quarto。

探测顺序：settings.json 显式路径 → PATH → 常见安装目录 / 注册表。
找不到不抛异常，返回 None——调用方据此**置灰按钮并给安装指引**，
而不是在导出中途炸掉（失败要前置，且要说人话）。

两条刻意的设计：
- 显式路径填错时**回落**到自动探测，而不是直接判缺失——用户一次笔误
  不该让功能永久不可用；
- R 的位置走注册表 `HKLM\\SOFTWARE\\R-core\\R\\<ver>\\InstallPath`，
  这是唯一与盘符无关的探测法（本机实测装在 d:\\R-4.6.1，扫 C:\\Program Files
  永远找不到）。
"""
import os
import shutil
import subprocess
import sys

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_R_REG_KEY = r"SOFTWARE\R-core\R"


def _first_existing(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


def version_of(path):
    """取程序 --version 的首个非空行；失败返回空串（探测阶段必须静默）。"""
    if not path or not os.path.isfile(path):
        return ""
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=3,
                           creationflags=_NO_WINDOW)
        out = (r.stdout or "") + (r.stderr or "")
        for ln in out.splitlines():
            if ln.strip():
                return ln.strip()[:120]
    except Exception:
        pass
    return ""


def _which(name):
    p = shutil.which(name)
    return p if p else None


def find_pandoc(configured=""):
    cands = [configured, _which("pandoc")]
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    lad = os.environ.get("LOCALAPPDATA", "")
    pd = os.environ.get("ProgramData", r"C:\ProgramData")
    cands += [
        os.path.join(pf, "Pandoc", "pandoc.exe"),
        os.path.join(lad, "Pandoc", "pandoc.exe"),
        os.path.join(pd, "chocolatey", "bin", "pandoc.exe"),
        # Quarto / RStudio 自带 pandoc：未单独安装时最常见的来源
        os.path.join(pf, "Quarto", "bin", "tools", "pandoc.exe"),
        os.path.join(pf, "RStudio", "resources", "app", "bin", "quarto",
                     "bin", "tools", "pandoc.exe"),
        os.path.join(pf86, "RStudio", "resources", "app", "bin", "quarto",
                     "bin", "tools", "pandoc.exe"),
    ]
    return _first_existing(cands)


def find_browser(configured=""):
    cands = [configured]
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    cands += [
        os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
    ]
    return _first_existing(cands)


def _r_install_dirs():
    """从注册表读 R 安装目录（与盘符无关）；读不到返回空列表。"""
    out = []
    if sys.platform != "win32":
        return out
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _R_REG_KEY) as k:
            i = 0
            while True:
                try:
                    ver = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, ver) as vk:
                        ip, _ = winreg.QueryValueEx(vk, "InstallPath")
                        if ip:
                            out.append(ip)
                except OSError:
                    continue
    except Exception:
        pass
    return out


def find_r(configured=""):
    cands = [configured, _which("Rscript")]
    for d in _r_install_dirs():
        cands.append(os.path.join(d, "bin", "x64", "Rscript.exe"))
        cands.append(os.path.join(d, "bin", "Rscript.exe"))
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    r_root = os.path.join(pf, "R")
    if os.path.isdir(r_root):
        for name in sorted(os.listdir(r_root), reverse=True):
            cands.append(os.path.join(r_root, name, "bin", "x64", "Rscript.exe"))
    return _first_existing(cands)


def find_quarto(configured=""):
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    return _first_existing([configured, _which("quarto"),
                            os.path.join(pf, "Quarto", "bin", "quarto.exe")])


def _entry(path, want_version=True):
    """want_version=False 用于 GUI 程序（浏览器）：它不认 --version，
    真去跑一次会**弹出窗口并卡约 8 秒**——只读探测绝不能有这种副作用。"""
    return {"found": bool(path),
            "path": path or "",
            "version": (version_of(path) if (path and want_version) else "")}


def _cfg(configured, *names):
    """读配置：优先规格 §7.2 的键名（xxx_path），同时兼容短键名（R4 之前的写法）。"""
    c = configured or {}
    for n in names:
        v = c.get(n)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def probe_all(configured=None):
    """一次性探测四个工具。configured 形如 {"pandoc_path": "...", ...}（规格 §7.2）。"""
    c = configured or {}
    return {
        "pandoc": _entry(find_pandoc(_cfg(c, "pandoc_path", "pandoc"))),
        # 浏览器不取版本：Edge/Chrome 不认 --version，跑起来会开窗口（见 _entry）
        "browser": _entry(find_browser(_cfg(c, "browser_path", "browser")),
                          want_version=False),
        "r": _entry(find_r(_cfg(c, "rscript_path", "rscript"))),
        "quarto": _entry(find_quarto(_cfg(c, "quarto_path", "quarto"))),
    }
