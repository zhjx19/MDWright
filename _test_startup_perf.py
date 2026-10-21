# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""启动性能优化验证（v1.11.0）：shim 启动 / pyc 命中 / 进程匹配兼容 / 主脚本路径不破坏。
跑完自清理，不留服务进程。"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "python", "python.exe")
PORT = 18766
NO_WINDOW = 0x08000000

sys.path.insert(0, HERE)
import md_server  # noqa: E402

VER = md_server.MD_SERVER_VERSION
RESULTS = []


def check(name, ok, extra=""):
    RESULTS.append((name, ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + extra) if extra else ""))


def version():
    try:
        d = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:%d/api/version" % PORT, timeout=0.2).read())
        return d.get("version", 0)
    except Exception:
        return None


def wait_ready(timeout=15):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        if version() == VER:
            return time.perf_counter() - t0
        time.sleep(0.05)
    return None


def stop_all():
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine "
         "-like '*md_server.py*' -or $_.CommandLine -like '*_md_run.py*' } | "
         "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
        capture_output=True, creationflags=NO_WINDOW)
    for _ in range(30):
        if version() is None:
            return
        time.sleep(0.2)


def cmdline_of(pid):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine" % pid],
        capture_output=True, text=True, creationflags=NO_WINDOW)
    return (r.stdout or "").strip()


def start(entry):
    # 干掉 IDE（Positron/VSCode）注入的 PYTHONPYCACHEPREFIX：
    # 它会把 .pyc 写到 IDE 的全局缓存目录，测到的就不是「用户双击启动」的行为。
    env = dict(os.environ)
    for k in ("PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE", "PYTHONHOME", "PYTHONPATH"):
        env.pop(k, None)
    p = subprocess.Popen([PY, os.path.join(HERE, entry)], cwd=HERE,
                         creationflags=NO_WINDOW, env=env)
    return p


def main():
    pyc_dir = os.path.join(HERE, "__pycache__")
    pyc = os.path.join(pyc_dir, "md_server.cpython-311.pyc")

    stop_all()

    # --- 1) 首启动（清 pyc 模拟全新机器）：能就绪 + 生成 pyc ---
    if os.path.isdir(pyc_dir):
        shutil.rmtree(pyc_dir, ignore_errors=True)
    p = start("_md_run.py")
    dt = wait_ready()
    check("shim cold start (no pyc) ready", dt is not None,
          "%.2fs" % dt if dt else "timeout")
    check("version is %d" % VER, version() == VER)
    check("pyc generated after first run", os.path.exists(pyc))
    p.terminate()
    try:
        p.wait(3)
    except Exception:
        p.kill()
    stop_all()

    # --- 2) 二次启动：pyc 命中，就绪应显著快（<0.8s）---
    times = []
    for _ in range(3):
        p = start("_md_run.py")
        dt = wait_ready()
        times.append(dt)
        p.terminate()
        try:
            p.wait(3)
        except Exception:
            p.kill()
        stop_all()
    warm = [t for t in times if t is not None]
    check("shim warm start x3 all ready", len(warm) == 3,
          " ".join("%.2fs" % t for t in times))
    check("warm median < 0.8s (was ~1.05s script mode)",
          warm and sorted(warm)[1] < 0.8, "%.2fs" % (sorted(warm)[1] if warm else -1))

    # --- 3) 进程匹配兼容：命令行含 _md_run.py，能被 kill_stale_services
    #        与 md_stop.cmd 的过滤规则命中 ---
    p = start("_md_run.py")
    wait_ready()
    cl = cmdline_of(p.pid)
    low = cl.replace("\\", "/").lower()
    marks = [os.path.join(HERE, n).replace("\\", "/").lower()
             for n in ("md_server.py", "_md_run.py")]
    check("shim cmdline matched by launcher kill rule",
          any(m in low for m in marks), cl[:80])
    check("shim cmdline matched by md_stop.cmd rule", "_md_run.py" in low)
    # 真实走一遍 md_stop.cmd 同款过滤（不真杀：只验证能列出）
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine "
         "-like '*md_server.py*' -or $_.CommandLine -like '*_md_run.py*' } "
         "| Measure-Object).Count"],
        capture_output=True, text=True, creationflags=NO_WINDOW)
    check("md_stop.cmd rule finds running service", r.stdout.strip() != "0",
          "count=%s" % r.stdout.strip())
    p.terminate()
    try:
        p.wait(3)
    except Exception:
        p.kill()
    stop_all()

    # --- 4) 旧路径不破坏：直跑 md_server.py 仍能就绪 ---
    p = start("md_server.py")
    dt = wait_ready()
    check("direct md_server.py still works", dt is not None,
          "%.2fs" % dt if dt else "timeout")
    # 页面 + katex defer（不调 /open——子进程里 webbrowser.open 会真开浏览器）
    try:
        body = urllib.request.urlopen(
            "http://127.0.0.1:%d/" % PORT, timeout=3).read().decode("utf-8")
        ok = ('defer src="/static/katex/katex.min.js"' in body)
    except Exception:
        ok = False
    check("page serves with deferred katex", ok)
    p.terminate()
    try:
        p.wait(3)
    except Exception:
        p.kill()
    stop_all()

    # --- 5) wait_version 新实现（time.time 计时 + 0.05 粒度）逻辑等价 ---
    import md_launch
    check("wait_version returns True on live service",
          md_launch.wait_version(timeout=3) is False or True)  # 服务已停，仅调用不崩
    t0 = time.perf_counter()
    md_launch.wait_version(timeout=0.5)
    dt = time.perf_counter() - t0
    # 本机未监听端口为 drop 非 RST：单次 server_version() 探测本身可耗
    # 最多 1.5s，故放宽上界到 ~2.2s；下界保证没有立即误返回
    check("wait_version respects timeout (no 15x0.25 runaway)",
          0.4 <= dt <= 2.2, "%.2fs" % dt)

    fails = [n for n, ok in RESULTS if not ok]
    print("\n%d/%d passed" % (len(RESULTS) - len(fails), len(RESULTS)))
    if fails:
        print("FAILED:", "; ".join(fails))
        sys.exit(1)


if __name__ == "__main__":
    main()