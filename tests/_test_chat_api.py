# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""/api/chat（AI 侧栏）路由级回归：

- 多轮顺序与角色：system 在最前，末尾必须是 user，末尾 assistant 被丢弃
- 选区 / 整篇文档进入 system 提示词
- 超长历史按预算裁剪并回传 truncated
- 空消息、缺模型、后端连接失败都走 200 + ok:false

用真 HTTP 服务跑路由，把 LLMClient.chat 换成捕获器——不碰网络。
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
import sys
import threading
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import llm_client  # noqa: E402
import md_server  # noqa: E402

PORT = 18766
fails = []
CAP = {"messages": None, "calls": 0, "raise": None}


def check(name, cond, detail=""):
    print("%-52s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


def fake_chat(self, messages, max_tokens=None, temperature=None):
    CAP["calls"] += 1
    CAP["messages"] = messages
    if CAP["raise"]:
        raise llm_client.LLMError(CAP["raise"])
    return "答"


llm_client.LLMClient.chat = fake_chat

httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

CFG = {"backend": "openai", "base_url": "http://fake.local/v1",
       "model": "m", "api_key": "k"}


def post(body):
    req = urllib.request.Request(
        "http://127.0.0.1:%d/api/chat" % PORT,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))


def reset(err=None):
    CAP.update({"messages": None, "calls": 0, "raise": err})


try:
    # 1) 两轮 + 选区
    reset()
    j = post({"config": CFG,
              "messages": [{"role": "user", "content": "这段话在说什么"},
                           {"role": "assistant", "content": "先说结论"},
                           {"role": "user", "content": "再短一点"}],
              "context": {"selection": "被选中的原文"}})
    msgs = CAP["messages"] or []
    check("chat: ok + text", j.get("ok") is True and j.get("text") == "答", str(j))
    check("chat: system 在最前", bool(msgs) and msgs[0]["role"] == "system", str(msgs[:1]))
    check("chat: 选区进入 system", "被选中的原文" in (msgs[0]["content"] if msgs else ""), "")
    check("chat: 历史顺序不变",
          [m["role"] for m in msgs[1:]] == ["user", "assistant", "user"],
          str([m["role"] for m in msgs[1:]]))
    check("chat: truncated=false", j.get("truncated") is False, str(j.get("truncated")))

    # 2) 末尾 assistant 被丢弃
    reset()
    post({"config": CFG,
          "messages": [{"role": "user", "content": "问题"},
                       {"role": "assistant", "content": "半截回答"}],
          "context": None})
    msgs = CAP["messages"] or []
    check("chat: 末尾 assistant 被丢弃",
          bool(msgs) and msgs[-1]["role"] == "user", str([m["role"] for m in msgs]))

    # 3) 空消息
    reset()
    j = post({"config": CFG, "messages": []})
    check("chat: 空消息 ok=false", j.get("ok") is False and j.get("error"), str(j))
    check("chat: 空消息不调模型", CAP["calls"] == 0, str(CAP["calls"]))

    # 4) 超长历史裁剪
    reset()
    long_hist = []
    for i in range(23):
        long_hist.append({"role": "user", "content": "问题%d" % i + "甲" * 1400})
        long_hist.append({"role": "assistant", "content": "答%d" % i + "乙" * 1400})
    long_hist.append({"role": "user", "content": "最后的问题"})
    j = post({"config": CFG, "messages": long_hist})
    msgs = CAP["messages"] or []
    check("chat: 超长历史 truncated=true", j.get("truncated") is True, str(j.get("truncated")))
    check("chat: 裁剪后仍以 user 结尾",
          bool(msgs) and msgs[-1]["role"] == "user" and msgs[-1]["content"] == "最后的问题",
          str(msgs[-1] if msgs else None))
    check("chat: 裁剪后条数变少", len(msgs) < len(long_hist) + 1,
          "%d vs %d" % (len(msgs), len(long_hist) + 1))

    # 4b) 连续两条 user（上一条失败后客户端只发两次 user）+ 长文档：
    #     裁剪绝不能把最后一轮问题一起丢掉，否则下一次重试还是同样形状，会话卡死
    reset()
    j = post({"config": CFG,
              "messages": [{"role": "user", "content": "上一问" + "甲" * 2000},
                           {"role": "user", "content": "最后这个问题"}],
              "context": {"selection": "", "document": "文" * 30000}})
    msgs = CAP["messages"] or []
    check("chat: 连续 user + 长文不丢最后一轮",
          j.get("ok") is True and bool(msgs) and msgs[-1]["role"] == "user"
          and msgs[-1]["content"] == "最后这个问题", str(j))
    check("chat: 该情形仍标 truncated", j.get("truncated") is True, str(j.get("truncated")))

    # 4c) 非对象 body 不能落成 500
    reset()
    j = post([])
    check("chat: 非对象 body 走 200+ok:false", j.get("ok") is False, str(j))

    # 5) 整篇文档
    reset()
    post({"config": CFG,
          "messages": [{"role": "user", "content": "全文讲了什么"}],
          "context": {"selection": "", "document": "整篇文档的内容"}})
    sysp = (CAP["messages"] or [{}])[0].get("content", "")
    check("chat: 全文进入 system", "【整篇文档】" in sysp and "整篇文档的内容" in sysp, sysp[:80])

    reset()
    post({"config": CFG, "messages": [{"role": "user", "content": "只问问题"}]})
    sysp = (CAP["messages"] or [{}])[0].get("content", "")
    check("chat: 不带全文时不注入", "【整篇文档】" not in sysp, sysp[:80])

    # 6) 缺模型
    reset()
    j = post({"config": {"backend": "openai", "base_url": "http://fake.local/v1",
                         "model": "", "api_key": "k"},
              "messages": [{"role": "user", "content": "hi"}]})
    check("chat: 缺模型 ok=false", j.get("ok") is False and "模型" in (j.get("error") or ""), str(j))
    check("chat: 缺模型不调模型", CAP["calls"] == 0, str(CAP["calls"]))

    # 7) 连接失败归一
    reset("连接失败: boom")
    j = post({"config": CFG, "messages": [{"role": "user", "content": "hi"}]})
    check("chat: 连接失败 ok=false + 可读文案",
          j.get("ok") is False and "连接失败" in (j.get("error") or ""), str(j))
finally:
    httpd.shutdown()
    httpd.server_close()

print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
sys.exit(1 if fails else 0)
