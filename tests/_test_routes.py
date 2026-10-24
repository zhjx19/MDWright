# -*- coding: utf-8 -*-
"""md_server 新路由冒烟测试（批注读写/LLM 配置/失败路径），跑完自清理。"""
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
import json
import os
import sys
import urllib.request
import urllib.parse

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import md_server  # noqa: E402

DOC = os.path.join(os.environ.get("TEMP", "/tmp"), "mda_test", "测试文档.md")

httpd = md_server.ReuseTCPServer(("127.0.0.1", 18766), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)


def call(path, method="GET", body=None):
    req = urllib.request.Request(
        "http://127.0.0.1:18766" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


fails = []


def check(name, cond, detail=""):
    print("%-18s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


try:
    s, b = call("/api/llm-config")
    j = json.loads(b)
    check("llm-config GET", s == 200 and j["ok"] and j["config"]["backend"] in ("lmstudio", "ollama"))

    s, b = call("/api/annotations?path=" + urllib.parse.quote(DOC, safe=""))
    j = json.loads(b)
    check("annotations GET(空)", s == 200 and j["ok"] and j["annotations"] == [])

    ann = [{"id": "a1", "text": "被标注的句子", "note": "备注内容", "created": 1, "updated": 2}]
    s, b = call("/api/annotations", "POST", {"path": DOC, "annotations": ann})
    check("annotations POST", s == 200 and json.loads(b)["ok"] is True)

    s, b = call("/api/annotations?path=" + urllib.parse.quote(DOC, safe=""))
    j = json.loads(b)
    check("annotations 回读", j.get("annotations") == ann, b[:200])
    apath = os.path.join(os.path.dirname(DOC), "测试文档.assets", "annotations.json")
    check("落盘位置正确", os.path.exists(apath), apath)

    s, b = call("/api/annotations", "POST", {"path": DOC, "annotations": "not-a-list"})
    check("annotations 拒脏", s == 400)

    s, b = call("/api/llm-config", "POST", {"config": {"backend": "ollama", "timeout": 99999, "bogus": "x"}})
    j = json.loads(b)
    check("llm-config 归一", j["ok"] and j["config"]["timeout"] == 600 and "bogus" not in j["config"], b[:200])
    saved = json.load(open(os.path.join(HERE, "runtime", "settings.json"), encoding="utf-8"))
    check("llm-config 落盘", saved.get("llm", {}).get("backend") == "ollama")
    # 还原：删掉 llm 段，避免影响后续真实使用
    saved.pop("llm", None)
    json.dump(saved, open(os.path.join(HERE, "runtime", "settings.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    bad = {"backend": "lmstudio", "base_url": "http://127.0.0.1:1"}  # 不可达端口，立即失败
    s, b = call("/api/llm-models", "POST", {"config": bad})
    j = json.loads(b)
    check("llm-models 失败路径", s == 200 and j["ok"] is False and "error" in j, b[:160])
    s, b = call("/api/llm-test", "POST", {"config": bad})
    j = json.loads(b)
    check("llm-test 失败路径", s == 200 and j["ok"] is False and j.get("message"), b[:160])
    s, b = call("/api/annotate", "POST", {"text": "   "})
    check("annotate 空文本", json.loads(b)["ok"] is False)
    s, b = call("/api/rewrite", "POST", {"text": ""})
    check("rewrite 空文本", json.loads(b)["ok"] is False)
    s, b = call("/api/annotate", "POST", {"config": {"backend": "ollama", "model": ""}, "text": "你好"})
    check("annotate ollama无模型", json.loads(b).get("error") == "该后端需先在 LLM 设置中选择模型", b[:200])

    # 线程化验证：挂一个慢 LLM 调用（不可达长超时），期间心跳/保存必须照常响应
    import threading as _th
    slow = {"config": {"backend": "lmstudio", "base_url": "http://10.255.255.1:1234", "timeout": 30}}
    t0 = time.time()
    _th.Thread(target=lambda: call("/api/rewrite", "POST", dict(slow, text="慢调用")), daemon=True).start()
    time.sleep(0.5)
    t1 = time.time()
    s, b = call("/api/version")
    dt = time.time() - t1
    check("线程化不阻塞", s == 200 and dt < 1.0, "version 耗时 %.2fs" % dt)
    print("   (慢调用已后台挂起 %.1fs，daemon 线程随进程退出)" % (time.time() - t0))
finally:
    httpd.shutdown()
    import shutil
    shutil.rmtree(os.path.dirname(DOC), ignore_errors=True)

print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
sys.exit(1 if fails else 0)