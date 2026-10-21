# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""外部工具探测回归（R2）：
- _first_existing 取候选里第一个真实存在的文件
- version_of 对不存在的程序返回 ""（不抛）
- probe_all 返回四个工具键，结构固定；缺失时不崩
- 配了不存在的路径时回落到自动探测（不因用户手填错误就判缺失）
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import md_tools  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


def main():
    real = sys.executable                      # 一定存在的可执行文件
    check("_first_existing 跳过不存在项",
          md_tools._first_existing(["/no/such/pandoc.exe", real]) == real)
    check("_first_existing 全不存在返回 None",
          md_tools._first_existing(["/no/a", "/no/b"]) is None)
    check("version_of 不存在的程序返回空串",
          md_tools.version_of("/no/such/pandoc.exe") == "")
    check("version_of 真实程序能给出版本",
          "Python" in md_tools.version_of(real), md_tools.version_of(real))

    t = md_tools.probe_all()
    check("probe_all 含四个工具键",
          set(t.keys()) == {"pandoc", "browser", "r", "quarto"}, str(sorted(t.keys())))
    for k, v in t.items():
        check("probe_all[%s] 结构固定" % k,
              set(v.keys()) == {"found", "path", "version"}, str(v))
        check("probe_all[%s] found 与 path 一致" % k,
              bool(v["found"]) == bool(v["path"]), str(v))

    # 手填了不存在的路径 → 回落到自动探测，而不是直接判缺失
    t2 = md_tools.probe_all({"pandoc": "/no/such/pandoc.exe"})
    check("错误的显式路径回落到自动探测",
          set(t2.keys()) == {"pandoc", "browser", "r", "quarto"})
    check("回落结果与自动探测同源",
          t2["pandoc"] == t["pandoc"], "%r vs %r" % (t2["pandoc"], t["pandoc"]))

    # 规格 §7.2 的键名（R4 会按这套写 settings）必须被认
    seen = []
    orig_find = md_tools.find_pandoc
    md_tools.find_pandoc = lambda configured="": (seen.append(configured),
                                                  orig_find(configured))[1]
    try:
        md_tools.probe_all({"pandoc_path": "/x/pandoc.exe"})
    finally:
        md_tools.find_pandoc = orig_find
    check("认规格键名 pandoc_path", seen and seen[0] == "/x/pandoc.exe", str(seen))

    # Critical：探测不得为了拿版本号去启动浏览器（Edge 会开窗口并卡约 8 秒）
    calls = []
    orig = md_tools.version_of
    md_tools.version_of = lambda p: (calls.append(p), orig(p))[1]
    try:
        t4 = md_tools.probe_all()
    finally:
        md_tools.version_of = orig
    check("探测不为浏览器启动进程取版本",
          t4["browser"]["path"] not in calls,
          "spawned: %r" % ([c for c in calls if c == t4["browser"]["path"]],))

    import time as _time
    t0 = _time.time()
    md_tools.probe_all()
    dt = _time.time() - t0
    check("整轮探测 < 5s", dt < 5.0, "%.2fs" % dt)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
