# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""启动画面锚点测试（v1.11.1）：淡出时机跟"页面会话上线"走，而非服务就绪+盲等。
1. 无窗口时撑住（sessions=0 → 不淡出）
2. 页面 ping 上线后 ~1.5s 内淡出销毁
3. life 超时兜底退场（窗口永远没起来的故障路径）
4. /api/version 带 sessions 字段
跑完自清理。"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "python", "python.exe")
# 独立测试端口：彻底避开生产端口 18766（外部页面 beat / 残留服务 /
# SO_REUSEADDR 双绑定都会让轮询结果不可信）
PORT = 18767
NO_WINDOW = 0x08000000

sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import md_server  # noqa: E402

VER = md_server.MD_SERVER_VERSION
RESULTS = []

u = ctypes.windll.user32
u.FindWindowW.restype = ctypes.c_void_p
u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]


def check(name, ok, extra=""):
    RESULTS.append((name, ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + extra) if extra else ""))


def splash_alive():
    return bool(u.FindWindowW("MDWrightSplash2", None))


def start_splash(life):
    return subprocess.Popen(
        [PY, os.path.join(HERE, "_splash.py"), "", str(life),
         str(PORT), str(VER)], cwd=HERE, creationflags=NO_WINDOW)


def get(path):
    return urllib.request.urlopen(
        "http://127.0.0.1:%d%s" % (PORT, path), timeout=1).read().decode("utf-8")


def main():
    httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    md_server._LIVE_SESSIONS.clear()

    # 0) version 带 sessions 字段且当前为 0
    d = json.loads(get("/api/version"))
    check("version has sessions field",
          d.get("version") == VER and d.get("sessions") == 0, str(d))

    # 1) 无窗口：splash 必须撑住（旧逻辑在 version 就绪+0.45s 就撤）
    sp = start_splash(life=30)
    t0 = time.time()
    while time.time() - t0 < 1.5 and not splash_alive():
        time.sleep(0.02)
    check("splash appears", splash_alive())
    time.sleep(2.0)  # 服务早已就绪，但无页面会话
    check("splash holds while no window (2s+, old logic would exit)",
          splash_alive())

    # 2) 页面上线（模拟前端加载完成后的首个 ping）→ 淡出
    t1 = time.time()
    get("/api/ping?tok=splash-test")
    gone_at = None
    while time.time() - t1 < 4.0:
        if not splash_alive():
            gone_at = time.time() - t1
            break
        time.sleep(0.05)
    check("splash fades after session online", gone_at is not None,
          "%.2fs after ping" % gone_at if gone_at else "still alive at 4s")
    check("fade latency < 1.5s (poll 0.15s + fade 0.8s)",
          gone_at is not None and gone_at < 1.5,
          "%.2fs" % gone_at if gone_at else "-")
    sp.wait(5)

    # 3) life 兜底：无会话时到点退场（窗口永远没起来的故障路径）
    md_server._LIVE_SESSIONS.clear()
    sp2 = start_splash(life=2)
    t2 = time.time()
    while time.time() - t2 < 6.0 and not splash_alive():
        time.sleep(0.02)
    check("splash (life=2) appears", splash_alive())
    gone2 = None
    while time.time() - t2 < 8.0:
        if not splash_alive():
            gone2 = time.time() - t2
            break
        time.sleep(0.05)
    check("splash exits via life fallback", gone2 is not None,
          "%.2fs (life=2 + fade)" % gone2 if gone2 else "-")
    sp2.wait(5)

    httpd.shutdown()
    fails = [n for n, ok in RESULTS if not ok]
    print("\n%d/%d passed" % (len(RESULTS) - len(fails), len(RESULTS)))
    if fails:
        print("FAILED:", "; ".join(fails))
        sys.exit(1)


if __name__ == "__main__":
    main()