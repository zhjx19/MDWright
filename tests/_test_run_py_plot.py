# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""Python 代码块出图回归（v3.3.0）：

Python 走的是 `exec` + stdout 捕获，本来没有图；现在执行完会看一眼 pyplot 里
还开着的 figure，savefig 成 `<id>.png`，交给与 R 同一条落盘 / 预览链路。

要验的四件：
- 画了图 → 回一个真 PNG（魔数对、不是空白图），文字输出照样在；
- 图的 figure 被 close 掉 → 下一块不会把上一块的图再存一遍（不串图）；
- 再画一张 → 出新的图，文件名不重复；
- 代码报错 → ok:false 带错误，但已经画出来的东西仍然留下（与 R 的 png 设备一致）。

随包内置的 3.11.9 没有 matplotlib，所以本用例先找一个装了 matplotlib 的解释器；
一个都没有就 SKIP（exit 77），不算失败。
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

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import md_server          # noqa: E402
import md_runs            # noqa: E402

PORT = 18777
fails = []

PLOT = (
    "import matplotlib\n"
    "matplotlib.use('Agg')\n"
    "import matplotlib.pyplot as plt\n"
    "plt.plot([1, 2, 3], [2, 1, 3])\n"
    "print('画完了')\n"
)


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


def post(path, obj):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "HTTP %d" % e.code}


def interp_with_mpl():
    """找一个真能 import matplotlib 的解释器（内置运行时没有）。"""
    cands = [sys.executable, shutil.which("python") or ""]
    for c in cands:
        if not c or not os.path.isfile(c):
            continue
        try:
            r = subprocess.run([c, "-c", "import matplotlib"], capture_output=True,
                               timeout=60, creationflags=0x08000000)
        except Exception:
            continue
        if r.returncode == 0:
            return c
    return ""


def png_ok(path):
    if not (path and os.path.isfile(path)):
        return False
    if os.path.getsize(path) < 2500:          # 空白图的体积远小于真图
        return False
    with open(path, "rb") as f:
        return f.read(8) == b"\x89PNG\r\n\x1a\n"


def main():
    py = interp_with_mpl()
    if not py:
        print("SKIP 没找到装了 matplotlib 的解释器（内置运行时没有，属正常）")
        print("\nALL PASS")
        sys.exit(77)
    print("解释器：%s" % py)
    md_runs._py_exe = lambda: py              # 只在本进程生效，等价于「设置里填了本机 Python」

    tmp = tempfile.mkdtemp(prefix="mdpyp-")
    doc = os.path.join(tmp, "出图.md")        # 给了文档路径才走常驻会话（变量跨块）

    def run(code, timeout=120):
        return post("/api/run-py", {"code": code, "doc": doc, "timeout": timeout})

    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        j = run(PLOT)
        check("画图块 ok", j.get("ok") is True, str(j)[:200])
        check("文字输出照样在", "画完了" in (j.get("stdout") or ""), j.get("stdout"))
        img1 = j.get("image") or ""
        check("回了图片路径", bool(img1), str(j)[:200])
        check("是有效 PNG（魔数 + 非空白）", png_ok(img1), img1)
        check("图落进文档 assets", ("assets" in img1.replace("/", "\\")
                                    and "runs" in img1.replace("/", "\\")), img1)

        j2 = run("print('这一块没画图')")
        check("没画图的块不串上一张图", not (j2.get("image") or ""),
              str(j2.get("image")))
        check("上一块的图没被覆盖", png_ok(img1), img1)

        j3 = run("plt.plot([1, 2], [2, 1])\nprint('第二张')")
        img3 = j3.get("image") or ""
        check("再画一张出新图", png_ok(img3), str(j3)[:200])
        check("两张图不是同一个文件", bool(img3) and img3 != img1, "%s vs %s" % (img1, img3))

        j4 = run("plt.plot([1, 2], [3, 4])\nraise ValueError('炸了')")
        check("报错时 ok=false", j4.get("ok") is False, str(j4)[:160])
        check("报错仍带原文", "炸了" in ((j4.get("error") or "") + (j4.get("stderr") or "")),
              str(j4)[:200])
        check("报错前画的内容仍留下", png_ok(j4.get("image") or ""), str(j4.get("image")))

        # 中文标题不能是方块：驱动里补了中文字族，并把 unicode_minus 关掉
        j5 = run("import matplotlib.pyplot as plt\n"
                 "print(plt.rcParams['font.sans-serif'][0])\n"
                 "print(plt.rcParams['axes.unicode_minus'])")
        check("默认字体给了中文字族", "YaHei" in (j5.get("stdout") or "")
              or "SimHei" in (j5.get("stdout") or "")
              or "PingFang" in (j5.get("stdout") or "")
              or "Noto" in (j5.get("stdout") or ""), j5.get("stdout"))
        check("负号按普通字符画", "False" in (j5.get("stdout") or ""), j5.get("stdout"))

        # plt.show() 在无头后端里不该卡住（卡住就要等 60 秒超时）
        t0 = time.time()
        j6 = run("plt.plot([1, 2], [1, 2])\nplt.show()\nprint('没卡住')", timeout=20)
        cost = time.time() - t0
        check("plt.show() 不阻塞", j6.get("ok") is True and cost < 15,
              "%.1fs %s" % (cost, str(j6)[:160]))
        check("show() 的图照样出", png_ok(j6.get("image") or ""), str(j6.get("image")))
    finally:
        httpd.shutdown()
        httpd.server_close()
        md_runs.reset(doc, None)
        md_runs.shutdown_all()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
