# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""DeepSeek 一等后端回归（R3）：
- 默认地址 https://api.deepseek.com/v1；填根地址自动补 /v1
- chat / models 端点按 OpenAI 兼容惯例拼接；Bearer 鉴权
- **deepseek-reasoner 不发送 temperature**（官方口径：reasoner 不支持采样参数）
- deepseek-chat 照常发送 temperature
- 既有 openai 后端行为不变（URL / 鉴权 / temperature 回归）
- 配置归一白名单接受 deepseek
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import llm_client  # noqa: E402
import md_server  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail))
    if not cond:
        fails.append(name)


class _Resp(object):
    def __init__(self, body):
        self._b = body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def capture(cfg, messages=None):
    """跑一次 chat()，返回 (url, headers, payload_dict)。"""
    seen = {}

    class _Req(object):
        def __init__(self, url, data=None, headers=None, method=None):
            seen["url"] = url
            seen["headers"] = headers or {}
            seen["data"] = data

    real_request = llm_client.urllib.request.Request
    real_urlopen = llm_client.urllib.request.urlopen

    def fake_urlopen(req, timeout=None):
        body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
        return _Resp(body)

    llm_client.urllib.request.Request = _Req
    llm_client.urllib.request.urlopen = fake_urlopen
    try:
        c = llm_client.LLMClient(cfg)
        c.chat(messages or [{"role": "user", "content": "hi"}])
    finally:
        llm_client.urllib.request.Request = real_request
        llm_client.urllib.request.urlopen = real_urlopen
    payload = json.loads(seen["data"].decode("utf-8")) if seen.get("data") else {}
    return seen.get("url"), seen.get("headers") or {}, payload


def main():
    # ---- 地址与端点 ----
    c = llm_client.LLMClient({"backend": "deepseek"})
    check("默认地址补成 /v1", c.base_url == "https://api.deepseek.com/v1", c.base_url)

    c = llm_client.LLMClient({"backend": "deepseek", "base_url": "https://api.deepseek.com"})
    check("填根地址自动补 /v1", c.base_url == "https://api.deepseek.com/v1", c.base_url)

    url, headers, payload = capture({"backend": "deepseek",
                                     "base_url": "https://api.deepseek.com/v1",
                                     "api_key": "sk-test", "model": "deepseek-chat"})
    check("chat 端点正确", url == "https://api.deepseek.com/v1/chat/completions", str(url))
    check("Bearer 鉴权", headers.get("Authorization") == "Bearer sk-test", str(headers))
    check("deepseek-chat 带 temperature", "temperature" in payload, str(sorted(payload)))

    # ---- reasoner：不传采样参数 ----
    url, headers, payload = capture({"backend": "deepseek",
                                     "base_url": "https://api.deepseek.com/v1",
                                     "api_key": "sk-test", "model": "deepseek-reasoner"})
    check("reasoner 不传 temperature", "temperature" not in payload, str(sorted(payload)))
    check("reasoner 不传 top_p", "top_p" not in payload, str(sorted(payload)))
    check("reasoner 正常带 model 与 messages",
          payload.get("model") == "deepseek-reasoner" and payload.get("messages"), str(payload)[:160])

    # 大小写/前缀变体也要识别（用户可能填 DeepSeek-Reasoner）
    _, _, payload2 = capture({"backend": "deepseek", "api_key": "sk",
                              "model": "DeepSeek-Reasoner"})
    check("reasoner 识别不区分大小写", "temperature" not in payload2, str(sorted(payload2)))

    # ---- 缺 key 明确报错 ----
    try:
        llm_client.LLMClient({"backend": "deepseek", "model": "deepseek-chat"})._headers()
        ok, err = False, ""
    except llm_client.LLMError as e:
        ok, err = True, str(e)
    check("缺 API Key 明确报错", ok and "API Key" in err, err)

    # ---- openai 回归 ----
    url, headers, payload = capture({"backend": "openai", "api_key": "sk-o",
                                     "model": "gpt-4o-mini"})
    check("openai 端点不变", url == "https://api.openai.com/v1/chat/completions", str(url))
    check("openai 仍带 temperature", "temperature" in payload, str(sorted(payload)))
    check("openai 鉴权不变", headers.get("Authorization") == "Bearer sk-o")

    # ---- 配置归一 ----
    n = md_server._norm_llm_config({"backend": "deepseek"})
    check("归一接受 deepseek", n["backend"] == "deepseek", n["backend"])
    n2 = md_server._norm_llm_config({"backend": "deepsek"})
    check("笔误后端回落到默认", n2["backend"] == md_server.LLM_DEFAULTS["backend"], n2["backend"])

    # ---- 前端：选项与模型预设 ----
    html = open(os.path.join(HERE, "mdwright.html"), encoding="utf-8").read()
    check("前端有 DeepSeek 后端选项", 'value="deepseek"' in html)
    check("前端给出 deepseek-chat 预设", "deepseek-chat" in html)
    check("前端给出 deepseek-reasoner 预设", "deepseek-reasoner" in html)

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
