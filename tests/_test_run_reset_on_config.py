# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""解释器改了，代码块会话要跟着换（v3.3.1）。

用户实测报的障：装好 3.3.0，在设置里填了本机 python.exe，跑 Python 块仍报
`ModuleNotFoundError: No module named 'pandas'`。

根因不是库没装，而是**会话的解释器在启动时就定死了**：文档里先跑过一块（那时
Python 路径还空着，用的是随包内置 3.11.9），之后再改设置，同一个文档继续复用
那个老会话，仍跑内置解释器。现场证据是那块会话的 `_driver.py` 比 settings.json
早 29 秒。

要验的：
- 内置运行时缺库时，响应里带上 hint（指回设置面板），不只是干巴巴的报错；
- PUT /api/tools 改了 python_path → 该语言的会话被清掉，响应 `reset` 说明清了谁；
- 清完之后同一个文档再跑 → 换成新解释器（`restarted:true`，能 import pandas）；
- 配置没变再保存一次 → 不清会话（不能每次点保存就把变量全丢）；
- 绕过接口直接改 settings.json（手工编辑 / 路径原来填错回落过）→ 下一次运行
  也会自己换解释器，不靠前端配合。

需要本机有一个装了 pandas 的解释器；没有就 SKIP（exit 77）。
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

import io
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

PORT = 18794
fails = []


def check(name, cond, detail=""):
    print("%-42s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
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


def interp_with_pandas():
    """找一个真能 import pandas 的解释器（随包内置没有）。"""
    cands = [shutil.which("python") or "", sys.executable]
    for c in cands:
        if not c or not os.path.isfile(c):
            continue
        try:
            r = subprocess.run([c, "-c", "import pandas"], capture_output=True,
                               timeout=90, creationflags=0x08000000)
        except Exception:
            continue
        if r.returncode == 0:
            return c
    return ""


def main():
    local_py = interp_with_pandas()
    if not local_py:
        print("SKIP 没找到装了 pandas 的解释器（内置运行时没有，属正常）")
        print("\nALL PASS")
        sys.exit(77)

    tmp = tempfile.mkdtemp(prefix="mdpycfg-")
    settings = os.path.join(tmp, "settings.json")
    doc = os.path.join(tmp, "会话.md")
    empty = {"pandoc_path": "", "rscript_path": "", "python_path": "",
             "quarto_path": "", "browser_path": ""}

    def write_settings(tools):
        with io.open(settings, "w", encoding="utf-8") as f:
            f.write(json.dumps({"_comment": "test", "tools": tools}, ensure_ascii=False))

    def read_tools():
        try:
            with io.open(settings, encoding="utf-8") as f:
                data = json.load(f)
            cfg = data.get("tools") if isinstance(data, dict) else None
            return cfg if isinstance(cfg, dict) else {}
        except Exception:
            return {}

    write_settings(empty)
    # 服务端写这份 settings，md_runs 读同一份：生产里本来就是同一个文件
    md_server.SETTINGS_PATH = settings
    md_runs._settings_tools = read_tools

    def run(code, timeout=120):
        return post("/api/run-py", {"code": code, "doc": doc, "timeout": timeout})

    def put_tools(tools):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/tools" % PORT,
            data=json.dumps({"config": tools}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="PUT")
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))

    print("本机解释器：%s" % local_py)
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        j = run("import pandas\nprint(pandas.__version__)")
        check("留空时用随包内置", j.get("runtime") == "builtin", str(j)[:200])
        check("内置缺库照实报错", j.get("ok") is False
              and "ModuleNotFoundError" in (j.get("error") or ""), str(j)[:200])
        check("缺库时给一句 hint", bool(j.get("hint")), str(j)[:200])

        jy = run("y = 1\nprint('ok')")
        check("先把内置会话跑起来", jy.get("runtime") == "builtin", str(jy)[:160])

        save = put_tools(dict(empty, python_path=local_py))
        check("保存路径成功", save.get("ok") is True, str(save)[:200])
        check("换了 Python 就写进 reset", "python" in (save.get("reset") or []),
              str(save.get("reset")))
        check("没换 R 不动 R", "r" not in (save.get("reset") or []), str(save.get("reset")))

        j2 = run("import pandas as pd\nprint(pd.__version__)\nprint('y' in globals())")
        check("同一文档换成新解释器", j2.get("ok") is True, str(j2)[:240])
        check("运行时标为本机解释器", j2.get("runtime") == "local", str(j2)[:200])
        check("新解释器能用 pandas", j2.get("stdout", "").strip().count(".") >= 1,
              repr(j2.get("stdout")))
        check("保存时就把老会话清了", "False" in (j2.get("stdout") or ""),
              repr(j2.get("stdout")))

        j3 = run("x = 42\nprint('变量已就位')")
        check("配置没再变，会话不复位", j3.get("restarted") is False, str(j3.get("restarted")))
        j4 = run("print(x)")
        check("前一块的变量还在", (j4.get("stdout") or "").strip() == "42",
              repr(j4.get("stdout")))

        same = put_tools(dict(empty, python_path=local_py))
        check("原样再保存不清会话", (same.get("reset") or []) == [], str(same.get("reset")))
        j5 = run("print(x)")
        check("原样保存后变量仍在", (j5.get("stdout") or "").strip() == "42",
              repr(j5.get("stdout")))

        # 绕过接口：直接改文件（手工编辑 settings.json / 路径原来填错回落过都走这条）
        write_settings(dict(empty, python_path=""))
        j6 = run("print(type(x).__name__ if 'x' in globals() else 'gone')")
        check("手改配置也会换回内置", j6.get("runtime") == "builtin", str(j6)[:200])
        check("手改配置也重建会话", j6.get("restarted") is True, str(j6.get("restarted")))
        check("换了解释器变量从头来", "gone" in (j6.get("stdout") or ""),
              repr(j6.get("stdout")))
    finally:
        httpd.shutdown()
        httpd.server_close()
        md_runs.shutdown_all()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
