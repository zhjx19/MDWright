# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""安装后要出现在「设置 → 应用 → 安装的应用」（v3.3.2）。

用户实测报的障：最近两个版本装完，Windows 的「安装的应用」里找不到它。

现场证据（HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MDWright）：
- `DisplayName` 整个值不存在——Windows 只认这个值，没有它就不列举；
- `DisplayIcon` = `\\mdwright.ico`、`UninstallString` = `"\\UninstallMDWright.exe"`
  都是**根相对路径**，说明 `%HERE%` 展开成了空串；
- 安装目录里 `UninstallMDWright.exe` 没编译出来，`.smd` 关联与快捷方式也没建。

根因：`install.cmd` 是 **LF-only** 行尾。cmd.exe 解析 LF-only 的批处理会把
`if (...)` 段和相邻 `reg add` 揉在一起，只有零散几行真正执行——`set "HERE=..."`
没生效，第 5 步的 `reg add` 只落下几条、DisplayName 那条干脆丢了。
本机复现：同一份内容写成 CRLF 全部正确，写成 LF 只剩一条 `DisplayIcon=\\mdwright.ico`。

要守的：
- 随包的 .cmd 一律 CRLF（仓库与 staging 都查），`.gitattributes` 声明 eol=crlf；
- 构建期强制改写，并有一条 staging 断言（漏了就直接构建失败）；
- 安装程序自己写卸载条目（DisplayName 等），install.cmd 半途失败也不影响显示；
- 中文 DisplayName 按 UTF-8 读（install.cmd 里 `chcp 65001`），不是乱码；
- 把 install.cmd 里真实的 ARP 命令行抽出来跑一遍，值必须是绝对路径。

真跑注册表，但只用测试键 HKCU\\Software\\MDWrightArpTest，跑完删掉。
"""
# --- 测试入口 shim：本文件在 tests/ 下。便携运行时（python311._pth）不会把 script dir
# 加进 sys.path，所以 tests/ 与仓库根两个都显式挂上，跨用例 import 与根模块 import 才成立 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import os
import re
import shutil
import subprocess
import sys
import tempfile
import winreg

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = _ROOT
STAGING = os.path.join(ROOT, "_setup_staging")
fails = []

CMD_FILES = ["install.cmd", "uninstall.cmd", "md_stop.cmd", "desktop-shortcut.cmd"]
ARP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MDWright"
TEST_KEY = r"Software\MDWrightArpTest"


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


def eol(path):
    with open(path, "rb") as f:
        data = f.read()
    crlf = data.count(b"\r\n")
    return crlf, data.count(b"\n") - crlf


def read_test_key():
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY) as k:
            i = 0
            while True:
                try:
                    name, val, _t = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[name] = val
                i += 1
    except OSError:
        pass
    return out


def drop_test_key():
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
    except OSError:
        pass


def arp_lines():
    """把 install.cmd 里真正登记卸载条目的命令行整段抽出来（不复制、不改写）。"""
    with open(os.path.join(ROOT, "install.cmd"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    head = [ln for ln in lines[:8] if ln.strip().lower().startswith("chcp")]
    body = [ln for ln in lines
            if ln.strip().startswith("reg add") and ARP_KEY in ln]
    return head, body


def run_batch(tmp, text, name):
    path = os.path.join(tmp, name)
    with open(path, "wb") as f:
        f.write(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
    subprocess.run(["cmd", "/c", name], cwd=tmp, capture_output=True, timeout=120)


def main():
    print("仓库：%s" % ROOT)

    for root, label in ((ROOT, "仓库"), (STAGING, "staging")):
        if not os.path.isdir(root):
            continue
        for fn in CMD_FILES:
            p = os.path.join(root, fn)
            if not os.path.isfile(p):
                check("%s %s 存在" % (label, fn), False, "missing")
                continue
            crlf, lf = eol(p)
            check("%s %s 是 CRLF" % (label, fn), lf == 0 and crlf > 0,
                  "CRLF=%d LF-only=%d" % (crlf, lf))

    attrs = os.path.join(ROOT, ".gitattributes")
    text = ""
    if os.path.isfile(attrs):
        with open(attrs, encoding="utf-8") as f:
            text = f.read()
    check(".gitattributes 声明 .cmd 用 CRLF",
          re.search(r"\*\.cmd\s+text\s+eol=crlf", text) is not None, text[:120])

    with open(os.path.join(ROOT, "installer", "_build_installer.py"), encoding="utf-8") as f:
        builder = f.read()
    check("构建期强制改写 .cmd 行尾", "def force_crlf(" in builder
          and "force_crlf(os.path.join(root, fn))" in builder)
    check("staging 有 LF-only 就构建失败", "LF-only" in builder and "SystemExit" in builder)

    with open(os.path.join(ROOT, "installer", "_setup_win.cs"), encoding="utf-8") as f:
        setup = f.read()
    check("安装程序自己建卸载条目", "EnsureArpEntry" in setup
          and "CreateSubKey" in setup)
    for field in ("DisplayName", "DisplayVersion", "InstallLocation",
                  "DisplayIcon", "UninstallString", "Publisher"):
        check("安装程序写 %s" % field,
              re.search(r'SetValue\("%s"' % field, setup) is not None)

    head, body = arp_lines()
    check("install.cmd 里有卸载条目命令行", len(body) >= 4, "抽到 %d 行" % len(body))
    check("install.cmd 按 UTF-8 读（chcp）", bool(head), str(head))

    if len(body) >= 4:
        tmp = tempfile.mkdtemp(prefix="mdarp-")
        try:
            fixed = [ln.replace(ARP_KEY, TEST_KEY) for ln in body]
            prefix = 'set "HERE=%s"' % tmp
            crlf_text = "\r\n".join(head + [prefix] + fixed) + "\r\n"

            drop_test_key()
            run_batch(tmp, crlf_text, "arp_ok.cmd")
            got = read_test_key()
            want_ico = os.path.join(tmp, "mdwright.ico")
            want_unins = '"%s"' % os.path.join(tmp, "UninstallMDWright.exe")
            check("CRLF：写出了 DisplayName",
                  got.get("DisplayName") == "墨匠 MDWright", repr(got.get("DisplayName")))
            check("CRLF：DisplayIcon 是绝对路径",
                  got.get("DisplayIcon") == want_ico, repr(got.get("DisplayIcon")))
            check("CRLF：UninstallString 是绝对路径",
                  got.get("UninstallString") == want_unins,
                  repr(got.get("UninstallString")))
            check("CRLF：NoModify = 1", got.get("NoModify") == 1,
                  repr(got.get("NoModify")))

            # 旁证：同样的内容写成 LF-only，cmd 会揉错——这正是线上症状的来源。
            # 不当作失败条件（不同 Windows 版本的 LF 容错不一样），只打印出来。
            drop_test_key()
            lf_text = crlf_text.replace("\r\n", "\n")
            p = os.path.join(tmp, "arp_lf.cmd")
            with open(p, "wb") as f:
                f.write(lf_text.encode("utf-8"))
            subprocess.run(["cmd", "/c", "arp_lf.cmd"], cwd=tmp,
                           capture_output=True, timeout=120)
            lf_got = read_test_key()
            print("   [INFO] LF-only 版本落到注册表的是：%r" % (lf_got,))
            drop_test_key()
        finally:
            drop_test_key()
            shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
