# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""代码高亮 vendor 与许可登记测试（R1）：
- highlight.js 11.11.1 common 构建落地，且**语言集含 R**（用户点名要求）
- 两套主题（亮/暗）就地分发
- 许可全文按 BSD-3-Clause 登记（highlight.js 不是 MIT）
- 分发清单与版权声明同步登记
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
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def read(p):
    if not os.path.exists(p):
        return ""
    return open(p, encoding="utf-8", errors="replace").read()


def main():
    js = os.path.join(HERE, "highlight", "highlight.min.js")
    check("vendor 存在", os.path.exists(js))
    if os.path.exists(js):
        txt = read(js)
        # cdnjs 的 common 构建把各语言声明为 grmr_<lang>:，运行期统一注册；
        # 故按 grmr_ 前缀断言语言集，不能找 registerLanguage("r")
        check("语言集含 R", "grmr_r:" in txt)
        check("语言集含 javascript", "grmr_javascript:" in txt)
        check("语言集含 python", "grmr_python:" in txt)
        size = os.path.getsize(js)
        check("体积在合理区间(60KB~400KB)", 60 * 1024 <= size <= 400 * 1024, "%d bytes" % size)
    for st in ("github.css", "github-dark.css"):
        p = os.path.join(HERE, "highlight", "styles", st)
        check("主题存在 " + st, os.path.exists(p))
        if os.path.exists(p):
            check("主题非空 " + st, os.path.getsize(p) > 500, "%d bytes" % os.path.getsize(p))

    lic = os.path.join(HERE, "LICENSES", "highlight.js-BSD-3-Clause.txt")
    check("许可全文存在", os.path.exists(lic))
    if os.path.exists(lic):
        t = read(lic)
        check("许可含 BSD 三条款标识",
              "Redistribution and use in source and binary forms" in t
              and "Neither the name of the copyright holder" in t)

    dist = os.path.join(HERE, "docs", "分发清单.md")
    check("分发清单登记 highlight.js", "highlight.js" in read(dist))
    ldoc = os.path.join(HERE, "docs", "版权与开源组件声明.md")
    check("版权声明登记 highlight.js", "highlight.js" in read(ldoc))
    check("版权声明写明 BSD-3-Clause", "BSD-3" in read(ldoc))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
