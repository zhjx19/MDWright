# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
"""MDEditor installer builder (system csc.exe only, zero third-party).

Stages the dist-checklist minimum set, packs payload.zip (UTF-8 entry names),
compiles a WinForms single-file installer with the Windows built-in C#
compiler, then (optionally) runs the built exe with --smoke and asserts the
extraction result.

Usage:
  python installer/_build_installer.py            # build MDEditor-Setup-vX.Y.Z.exe
  python installer/_build_installer.py --smoke    # smoke build + self-check first
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING = os.path.join(SRC, "_setup_staging")
OUT = os.path.join(SRC, "_setup_out")
SMOKE_REPORT = os.path.join(tempfile.gettempdir(), "md_setup_smoke_report.txt")

# dist checklist minimum set (sections 1+2+3+4). Keep in sync with docs checklist.
DIST_DIRS = ["python", "katex", "pagedjs", "LICENSES",
             "mermaid", "viz", "wavedrom", "vega", "highlight"]
DIST_DOCS_FILES = ["MDEditor 使用指南.md", "版权与开源组件声明.md"]
DIST_DOCS_DIRS = ["MDEditor 使用指南.assets"]
DIST_FILES = ["md_launch.pyw", "_md_run.py", "md_server.py", "markdown-editor.html",
              "md-editor.ico", "uninstall-md.ico", "llm_client.py", "web_search.py",
              "rag_client.py", "_smd.py", "md_assets.py", "_splash.py",
              "md_tools.py", "md_pandoc.py", "_cdp.py",
              "_pickdir_modern.py", "_pickfile.py", "md_app.pyw", "LICENSE", "README.md",
              "install.cmd", "MarkdownEditor.cs", "MarkdownEditor.exe", "_mklnk.ps1",
              "uninstall.cmd", "UninstallMDEditor.cs", "desktop-shortcut.cmd", "md_stop.cmd"]


def detect_version():
    with open(os.path.join(SRC, "CHANGELOG.md"), encoding="utf-8") as f:
        m = re.search(r"^## v(\d+\.\d+\.\d+)", f.read(), re.M)
    if not m:
        raise SystemExit("FAIL cannot detect version from CHANGELOG.md")
    return m.group(1)


def find_csc():
    root = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                        "Microsoft.NET", "Framework64")
    vers = sorted((d for d in os.listdir(root) if d.startswith("v4")), reverse=True)
    if not vers:
        raise SystemExit("FAIL .NET Framework 4 csc.exe not found")
    return os.path.join(root, vers[0], "csc.exe")


def make_staging(ver):
    shutil.rmtree(STAGING, ignore_errors=True)
    os.makedirs(STAGING)
    for d in DIST_DIRS:
        shutil.copytree(os.path.join(SRC, d), os.path.join(STAGING, d))
    docs = os.path.join(STAGING, "docs")
    os.makedirs(docs)
    for f in DIST_DOCS_FILES:
        shutil.copy2(os.path.join(SRC, "docs", f), os.path.join(docs, f))
    for d in DIST_DOCS_DIRS:
        shutil.copytree(os.path.join(SRC, "docs", d), os.path.join(docs, d))
    for f in DIST_FILES:
        shutil.copy2(os.path.join(SRC, f), os.path.join(STAGING, f))
    n = sum(len(fs) for _, _, fs in os.walk(STAGING))
    return n


def make_payload_zip():
    zpath = os.path.join(OUT, "payload.zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(STAGING):
            for fn in files:
                full = os.path.join(root, fn)
                arc = os.path.relpath(full, STAGING).replace(os.sep, "/")
                z.write(full, arc)
    return zpath


def compile_installer(ver, out_name):
    os.makedirs(OUT, exist_ok=True)
    zpath = make_payload_zip()
    vpath = os.path.join(OUT, "ver.txt")
    with open(vpath, "w", encoding="utf-8") as f:
        f.write(ver)
    # csc reads source as ANSI unless BOM; add BOM so Chinese literals survive.
    cs_bom = os.path.join(OUT, "_setup_win_bom.cs")
    with open(os.path.join(SRC, "installer", "_setup_win.cs"), encoding="utf-8") as f:
        text = f.read()
    with open(cs_bom, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(text)
    exe = os.path.join(OUT, out_name)
    if os.path.exists(exe):
        os.remove(exe)
    args = [find_csc(), "/nologo", "/target:winexe", "/platform:anycpu",
            "/out:" + exe,
            "/win32icon:" + os.path.join(SRC, "md-editor.ico"),
            "/r:System.IO.Compression.dll",
            "/r:System.IO.Compression.FileSystem.dll",
            "/r:System.Windows.Forms.dll",
            "/r:System.Drawing.dll",
            "/res:" + zpath,
            "/res:" + vpath,
            cs_bom]
    r = subprocess.run(args, capture_output=True, timeout=600)
    if r.returncode != 0 or not os.path.exists(exe):
        print((r.stdout or b"").decode("mbcs", "replace"))
        print((r.stderr or b"").decode("mbcs", "replace"))
        raise SystemExit("FAIL csc compile")
    return exe, os.path.getsize(zpath)


def run_smoke(exe):
    if os.path.exists(SMOKE_REPORT):
        os.remove(SMOKE_REPORT)
    subprocess.run([exe, "--smoke"], timeout=600, capture_output=True)
    for _ in range(40):
        if os.path.exists(SMOKE_REPORT):
            break
        import time
        time.sleep(0.5)
    if not os.path.exists(SMOKE_REPORT):
        raise SystemExit("FAIL smoke report missing")
    rep = {}
    with open(SMOKE_REPORT, encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                k, v = line.rstrip("\n").split("=", 1)
                rep[k] = v
    checks = [
        ("payload extracted", int(rep.get("total_files", "0")) > 500, rep.get("total_files", "?")),
        ("guide md exists (exact Chinese name)",
         rep.get("guide_md_exists") == "1" and "MDEditor 使用指南.md" in rep.get("docs_listing", ""),
         rep.get("docs_listing", "")[:200]),
        ("license doc exists", rep.get("license_doc_exists") == "1", ""),
        ("uninstall icon in payload", rep.get("uninstall_icon_exists") == "1", ""),
        ("uninstaller source in payload", rep.get("uninstaller_cs_exists") == "1", ""),
        ("pythonnet DLL >= 400KB", int(rep.get("pythonnet_dll_size", "0")) > 400 * 1024,
         rep.get("pythonnet_dll_size", "?")),
        ("katex fonts >= 50", int(rep.get("katex_fonts_count", "0")) >= 50,
         rep.get("katex_fonts_count", "?")),
        ("pythonw.exe present", rep.get("pythonw_exists") == "1", ""),
        ("mermaid vendor in payload (>=3MB)",
         int(rep.get("mermaid_vendor_size", "0")) > 3 * 1024 * 1024,
         rep.get("mermaid_vendor_size", "?")),
        ("viz-js vendor in payload (>=1MB)",
         int(rep.get("viz_vendor_size", "0")) > 1024 * 1024,
         rep.get("viz_vendor_size", "?")),
        ("wavedrom vendor in payload (>=50KB)",
         int(rep.get("wavedrom_vendor_size", "0")) > 50 * 1024,
         rep.get("wavedrom_vendor_size", "?")),
        ("wavedrom skins in payload (>=30KB x2)",
         int(rep.get("wavedrom_skin_size", "0")) > 30 * 1024
         and int(rep.get("wavedrom_skin_dark_size", "0")) > 30 * 1024,
         rep.get("wavedrom_skin_size", "?") + "/" + rep.get("wavedrom_skin_dark_size", "?")),
        ("vega-embed vendor in payload (>=50KB)",
         int(rep.get("vega_embed_vendor_size", "0")) > 50 * 1024,
         rep.get("vega_embed_vendor_size", "?")),
        ("version parsed", rep.get("version", "?") != "?", rep.get("version", "?")),
        ("webview2 detected (this machine)", rep.get("webview2") == "1", ""),
    ]
    fails = [name for name, ok, _ in checks if not ok]
    for name, ok, extra in checks:
        print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" | " + extra) if extra else ""))
    return not fails


def verify_staging():
    """分发集必须含导出链路与代码高亮 vendor。

    少了它们的症状是**静默失效**：装完 app 能开、页面能看，只是「Word/PDF」按钮
    永远置灰、代码块永不着色，没有任何报错。所以在这里前置拦住。
    """
    need = [("md_tools.py", 1), ("md_pandoc.py", 1), ("_cdp.py", 1),
            ("highlight/highlight.min.js", 100 * 1024),
            ("highlight/styles/github.css", 500),
            ("highlight/styles/github-dark.css", 500)]
    fails = []
    for rel, min_size in need:
        p = os.path.join(STAGING, rel.replace("/", os.sep))
        ok = os.path.isfile(p) and os.path.getsize(p) >= min_size
        print("%s staging has %s%s" % ("PASS" if ok else "FAIL", rel,
                                       "" if ok else "（缺失或过小）"))
        if not ok:
            fails.append(rel)
    return not fails


def main():
    smoke_mode = "--smoke" in sys.argv
    ver = detect_version()
    n = make_staging(ver)
    print("staging ready: %d files (v%s)" % (n, ver))
    if not verify_staging():
        raise SystemExit("FAIL staging 缺少必需文件（见上）")
    out_name = "_setup_smoke.exe" if smoke_mode else "MDEditor-Setup-v%s.exe" % ver
    exe, zsize = compile_installer(ver, out_name)
    print("BUILD OK: %s (%d KB, payload.zip %d KB)"
          % (exe, os.path.getsize(exe) // 1024, zsize // 1024))
    if smoke_mode:
        ok = run_smoke(exe)
        print("SMOKE %s" % ("PASS" if ok else "FAIL"))
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
