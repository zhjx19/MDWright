# -*- coding: utf-8 -*-
"""keepalive 会话计数测试：多开共享服务背景下，ping/bye 按 token 上下线，
只剩一个会话下线时服务才进入待退出；待退期间新会话心跳撤销退出。
跑完自清理（不在测试内触发看门狗 os._exit，退出判定由行为级验证覆盖）。"""
import threading
import time
import sys
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import md_server  # noqa: E402

httpd = md_server.ReuseTCPServer(("127.0.0.1", 18766), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)


def call(path, method="GET"):
    req = urllib.request.Request("http://127.0.0.1:18766" + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except Exception:
        return 0


fails = []


def check(name, cond, detail=""):
    print("%-30s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


md_server._LIVE_SESSIONS.clear()
md_server._BYE_AT[0] = 0.0

check("GET ping tok=A", call("/api/ping?tok=A") == 200)
check("GET ping tok=B", call("/api/ping?tok=B") == 200)
check("two sessions live", len(md_server._LIVE_SESSIONS) == 2)

check("POST bye tok=A forwarded", call("/api/bye?tok=A", "POST") == 200)
check("one session left", len(md_server._LIVE_SESSIONS) == 1)
check("A bye keeps service (B alive => no exit timer)",
      md_server._BYE_AT[0] == 0.0)

check("POST bye tok=B", call("/api/bye?tok=B", "POST") == 200)
check("no session left", len(md_server._LIVE_SESSIONS) == 0)
check("last bye arms exit timer", md_server._BYE_AT[0] > 0)

check("new ping unarms exit (refresh/reopen)",
      call("/api/ping?tok=C") == 200
      and md_server._LIVE_SESSIONS.get("C") is not None
      and md_server._BYE_AT[0] == 0.0)

check("missing tok normalizes to legacy slot",
      call("/api/bye") == 200 and md_server._LIVE_SESSIONS.get("_legacy") is None)

httpd.shutdown()
print("\nRESULT: %s (%d fail)" % ("PASS" if not fails else "FAIL", len(fails)))
sys.exit(1 if fails else 0)