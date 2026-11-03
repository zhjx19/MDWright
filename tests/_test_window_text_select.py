# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""嵌入式窗口必须允许选中文字（右侧预览要能选中复制）。

pywebview 的 `text_select` 默认是 **False**，此时它会往页面注入
`body {-webkit-user-select:none; …; user-select:none; cursor:default}`。
编辑器是 `contenteditable`，浏览器照旧允许选中，所以症状只在预览区：
分屏模式下右侧文字整块选不中、无法复制（浏览器模式无此注入，测不出来）。

断言：
- `md_app.pyw` 的 `create_window(...)` 显式传了 `text_select=True`；
- 当前随包 pywebview 的 `text_select` 默认值确实是 False（说明为什么必须显式传）；
- 该参数在 `create_window` 签名里（版本升级后仍被接受）。
"""
# --- 测试入口 shim ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import inspect
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT
fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def main():
    with open(os.path.join(HERE, "md_app.pyw"), encoding="utf-8") as f:
        src = f.read()
    i = src.find("webview.create_window(")
    check("md_app 调用了 create_window", i >= 0)
    call = src[i:i + 900] if i >= 0 else ""
    check("create_window 传 text_select=True", "text_select=True" in call,
          call[:200].replace("\n", " "))

    import webview
    sig = inspect.signature(webview.create_window)
    check("pywebview 仍接受 text_select 参数", "text_select" in sig.parameters,
          str(list(sig.parameters))[:160])
    default = sig.parameters.get("text_select")
    check("pywebview 默认仍是 False（必须显式打开）",
          default is not None and default.default is False,
          "default=%r" % (default.default if default else None))

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    return not fails


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
