# -*- coding: utf-8 -*-
"""RAG 在线端到端验证（仅集成契约）：拉起 → 探测 → query 按协议传参返回 → 停止。
RAG 内部检索行为（路由策略、耗时、NLI）属 rag-assistant 自身职责，不在验证范围。"""
# --- 测试入口 shim：本文件在 tests/ 下。便携运行时（python311._pth）不会把 script dir
# 加进 sys.path，所以 tests/ 与仓库根两个都显式挂上，跨用例 import 与根模块 import 才成立 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import threading
import time
import sys
import os
import json
import urllib.request
import urllib.error

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import md_server  # noqa: E402

httpd = md_server.ReuseTCPServer(("127.0.0.1", 18766), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

BASE = "http://127.0.0.1:18766"
RAG_PATH = os.environ.get("MD_RAG_PATH", r"C:\Users\sm001\WorkBuddy\rag-assistant")
fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


def call(path, method="GET", body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


if md_server._probe_rag()["online"]:
    print("8767 已在线，跳过冷启动阶段")
    started_here = False
else:
    started_here = True
    st, j = call("/api/rag/start", "POST", {"path": RAG_PATH})
    check("POST /api/rag/start accepted", st == 200 and j.get("ok") is True, str(j)[:160])

    t0 = time.time()
    online = False
    while time.time() - t0 < 240:
        time.sleep(5)
        if md_server._probe_rag()["online"]:
            online = True
            break
    check("rag-assistant online (cold start)", online, "waited %.0fs" % (time.time() - t0))

# --- 集成契约：状态/列表/query 传参与返回结构 ---
st, j = call("/api/rag-status")
check("rag-status online=True", st == 200 and j.get("online") is True, str(j)[:160])
check("rag-status kbs non-empty list", isinstance(j.get("kbs"), list) and len(j.get("kbs", [])) > 0,
      str(j.get("kbs"))[:160])
st, j = call("/api/rag/start", "POST", {"path": RAG_PATH})
check("rag/start while online -> rejected", st == 200 and j.get("ok") is False, str(j)[:160])

try:
    hit = md_server._ragc.RAGClient(timeout=240).query("", "项目结构", top_k=3)
    check("query returns contract shape",
          isinstance(hit, dict) and "has_context" in hit and "context" in hit
          and "sources" in hit and "kb" in hit, str(hit)[:160])
    print("  has_context=%s kb=%s ctx_len=%d" % (hit.get("has_context"), hit.get("kb"),
                                                 len(hit.get("context") or "")))
except Exception as e:
    check("query returns contract shape", False, str(e))

# --- 停止（仅当本脚本启动的） ---
if started_here:
    st, j = call("/api/rag/stop", "POST", {}, timeout=30)
    print("  stop result: %s %s" % (st, str(j)[:120]))
    check("rag/stop succeeds or reports watchdog revival",
          (st == 200 and j.get("ok") is True) or "自动重启" in (j.get("error") or ""), str(j)[:160])
    print("  8767 after stop: online=%s" % md_server._probe_rag()["online"])

httpd.shutdown()
print("\nRESULT: %s (%d fail)" % ("PASS" if not fails else "FAIL", len(fails)))
sys.exit(1 if fails else 0)