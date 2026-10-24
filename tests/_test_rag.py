# -*- coding: utf-8 -*-
"""RAG 路由行为测试：status / 配置持久化 / 离线错误路径 / 启动参数校验。
settings.json 重定向到临时文件，不污染真实配置；不触发真实冷启动（太重），
若本机 8767 恰好在线则追加在线 query 分支。"""
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
import tempfile

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import md_server  # noqa: E402

TMP = tempfile.mkdtemp(prefix="md_rag_test_")
md_server.SETTINGS_PATH = os.path.join(TMP, "settings.json")

httpd = md_server.ReuseTCPServer(("127.0.0.1", 18766), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

BASE = "http://127.0.0.1:18766"
fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


# --- 基础 ---
st, j = call("/api/version")
check("GET /api/version matches MD_SERVER_VERSION",
      st == 200 and j.get("version") == md_server.MD_SERVER_VERSION, str(j))

probe = md_server._probe_rag()
online = probe["online"]
print("(local 8767 online: %s)" % online)

# --- 状态探测 ---
st, j = call("/api/rag-status")
check("GET /api/rag-status ok", st == 200 and j.get("ok") is True, str(j)[:120])
check("rag-status online matches probe", j.get("online") == online, str(j)[:120])
check("rag-status has kbs list", isinstance(j.get("kbs"), list))
check("rag-status has path/kb fields", "path" in j and "kb" in j)

# --- 配置持久化 ---
st, j = call("/api/llm-config")
check("GET /api/llm-config has rag", st == 200 and isinstance(j.get("rag"), dict), str(j)[:120])
check("rag default path", j.get("rag", {}).get("path") == md_server.RAG_DEFAULTS["path"])

st, j = call("/api/llm-config", "POST",
             {"config": {"backend": "lmstudio"},
              "rag": {"path": "D:/some/where", "kb": "kb1"}})
check("POST llm-config with rag ok", st == 200 and j.get("ok") is True, str(j)[:120])
st, j = call("/api/llm-config")
check("rag persisted roundtrip",
      j.get("rag", {}).get("path") == "D:/some/where" and j.get("rag", {}).get("kb") == "kb1",
      str(j.get("rag")))

nc = md_server._norm_rag_config({"path": 123, "kb": None})
check("_norm_rag_config dirty input -> defaults",
      nc["path"] == md_server.RAG_DEFAULTS["path"] and nc["kb"] == "", str(nc))

# --- 检索增强动作（离线错误路径；在线真实检索由 _test_rag_e2e.py 覆盖，
#     此处不触发真实 query —— RAG 假死/冷启动慢时结果不稳定且属被集成方内部行为）---
if not online:
    st, j = call("/api/rag/rewrite", "POST", {"text": "测试文本"})
    check("rag/rewrite offline -> ok:false", st == 200 and j.get("ok") is False, str(j)[:160])
    check("rag/rewrite offline error mentions RAG", "RAG" in j.get("error", ""), str(j.get("error"))[:160])
    st, j = call("/api/rag/annotate", "POST", {"text": "测试文本"})
    check("rag/annotate offline -> ok:false", st == 200 and j.get("ok") is False, str(j)[:160])
    st, j = call("/api/rag/rewrite", "POST", {"text": ""})
    check("rag/rewrite empty text -> ok:false", st == 200 and j.get("ok") is False)
    try:
        md_server._ragc.RAGClient(timeout=2).query("", "test")
        check("RAGClient offline query raises", False)
    except md_server._ragc.RAGClientError:
        check("RAGClient offline query raises", True)
    except Exception as e:
        check("RAGClient offline query raises", False, str(e))
else:
    print("(8767 online: online-path checks covered by _test_rag_e2e.py)")

# --- 启动参数校验（不真正冷启动） ---
st, j = call("/api/rag/start", "POST", {"path": "Z:/not/exist"})
check("rag/start bad path -> ok:false",
      st == 200 and j.get("ok") is False and "路径" in j.get("error", ""), str(j)[:160])

tmpdir = tempfile.mkdtemp(prefix="md_fake_rag_")
st, j = call("/api/rag/start", "POST", {"path": tmpdir})
check("rag/start dir without main.py -> ok:false",
      st == 200 and j.get("ok") is False and "main.py" in j.get("error", ""), str(j)[:160])

if online:
    # start 已在线拒绝：仅在探测结果与后端一致时才有意义（假死竞态下会真拉起，
    # 有副作用）；为稳定起见仅在 stderr 断言离线双确认后执行
    if not md_server._probe_rag()["online"]:
        print("(probe unstable, skip already-online check)")
    else:
        st, j = call("/api/rag/start", "POST", {"path": r"C:\Users\sm001\WorkBuddy\rag-assistant"})
        check("rag/start already online -> rejected",
              st == 200 and j.get("ok") is False and "已在运行" in j.get("error", ""), str(j)[:160])
else:
    print("(8767 offline, already-online check N/A)")

# --- 解释器选择 ---
cmd = md_server._rag_python_cmd(tmpdir)
check("_rag_python_cmd returns cmd list", isinstance(cmd, list) and len(cmd) >= 1, str(cmd))
check("_rag_python_cmd interpreter exists", os.path.isfile(cmd[0]), str(cmd))

httpd.shutdown()
print("\nRESULT: %s (%d fail)" % ("PASS" if not fails else "FAIL", len(fails)))
sys.exit(1 if fails else 0)