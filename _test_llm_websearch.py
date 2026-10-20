# -*- coding: utf-8 -*-
"""OpenAI 兼容后端 + 联网查询测试：
- llm_client openai 分支（URL 拼接 / key 与 model 必填校验，不发真实请求）
- web_search 各 backend 的参数校验与归一（离线路径，不发真实请求）
- md_server 配置归一 / 往返 / 润色路由的联网注入与降级标志
settings.json 重定向临时文件。"""
import threading
import time
import sys
import os
import json
import urllib.request
import urllib.error
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import md_server  # noqa: E402
import llm_client  # noqa: E402
import web_search  # noqa: E402

TMP = tempfile.mkdtemp(prefix="md_ws_test_")
md_server.SETTINGS_PATH = os.path.join(TMP, "settings.json")

httpd = md_server.ReuseTCPServer(("127.0.0.1", 18766), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

BASE = "http://127.0.0.1:18766"
fails = []


def check(name, cond, detail=""):
    print("%-52s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


def call(path, method="GET", body=None, timeout=60):
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


# ── llm_client openai 分支 ──
c = llm_client.LLMClient({"backend": "openai"})
check("openai default base_url", c.base_url == "https://api.openai.com/v1", c.base_url)
check("openai chat url", c._chat_url() == "https://api.openai.com/v1/chat/completions")
check("openai models url", c._models_url() == "https://api.openai.com/v1/models")

c2 = llm_client.LLMClient({"backend": "openai", "base_url": "https://api.deepseek.com"})
check("openai auto /v1 suffix", c2._chat_url() == "https://api.deepseek.com/v1/chat/completions",
      c2._chat_url())
c3 = llm_client.LLMClient({"backend": "openai", "base_url": "https://api.siliconflow.cn/v1/"})
check("openai explicit /v1 kept (no dup)",
      c3._chat_url() == "https://api.siliconflow.cn/v1/chat/completions", c3._chat_url())

c4 = llm_client.LLMClient({"backend": "openai", "api_key": "sk-x", "model": "m1"})
check("openai auth header", c4._headers().get("Authorization") == "Bearer sk-x")
try:
    llm_client.LLMClient({"backend": "openai", "model": "m1"}).list_models()
    check("openai no key raises", False)
except llm_client.LLMError as e:
    check("openai no key raises", "API Key" in str(e), str(e))
try:
    llm_client.LLMClient({"backend": "openai", "api_key": "sk-x"}).chat([{"role": "user",
                                                                          "content": "x"}])
    check("openai no model raises", False)
except llm_client.LLMError as e:
    check("openai no model raises", "模型" in str(e), str(e))

check("lmstudio url unchanged",
      llm_client.LLMClient({"backend": "lmstudio"})._chat_url() == "http://localhost:1234/v1/chat/completions")
check("ollama url unchanged",
      llm_client.LLMClient({"backend": "ollama"})._chat_url() == "http://localhost:11434/api/chat")

# ── web_search 离线校验 ──
ws = web_search.WebSearch({"enabled": False})
r = ws.search("test")
check("ws disabled -> error", not r["success"] and "已关闭" in r["error"])

ws = web_search.WebSearch({"enabled": True})
r = ws.search("   ")
check("ws empty query -> error", not r["success"])

for backend, keyerr in (("tavily", "Tavily API Key"), ("bing", "Bing API Key"),
                        ("google", "Google API Key 或 CX"), ("custom", "自定义 API URL")):
    r = web_search.WebSearch({"enabled": True, "backend": backend}).search("q")
    check("ws %s no config -> error" % backend, not r["success"] and keyerr in r["error"],
          str(r.get("error")))

r = web_search.WebSearch({"enabled": True, "backend": "bogus", "max_results": 99}).search("q")
check("ws bogus backend falls back to duckduckgo", r["error"] != "联网搜索已关闭")

fmt = web_search.format_results([{"title": "T1", "url": "http://a", "snippet": "S1"},
                                 {"title": "", "url": "", "snippet": "x" * 500}])
check("format_results shape", "[1] T1 (http://a)" in fmt and "[2]" in fmt and "…" in fmt,
      fmt[:80])

# ── md_server 归一与往返 ──
n = md_server._norm_llm_config({"backend": "openai", "api_key": " sk-x "})
check("norm: openai in whitelist", n["backend"] == "openai")
check("norm: api_key stripped", n["api_key"] == "sk-x")
check("norm: ws defaults", n["web_search"] == md_server.WS_DEFAULTS, str(n["web_search"]))

n = md_server._norm_llm_config({"web_search": {"enabled": 1, "backend": "TAVILY",
                                               "max_results": 50, "api_key": 123}})
w = n["web_search"]
check("norm: ws enabled bool", w["enabled"] is True)
check("norm: ws backend case-insensitive", w["backend"] == "tavily")
check("norm: ws max_results clamped", w["max_results"] == 10)
check("norm: ws dirty api_key -> empty", w["api_key"] == "")

n = md_server._norm_llm_config({"backend": "bogus"})
check("norm: bogus backend -> default lmstudio", n["backend"] == "lmstudio")

st, j = call("/api/llm-config")
check("GET llm-config has web_search", st == 200 and isinstance(j["config"].get("web_search"), dict))
st, j = call("/api/llm-config", "POST", {"config": {"backend": "openai", "api_key": "sk-1",
                                                    "web_search": {"enabled": True,
                                                                   "backend": "bing",
                                                                   "bing_key": "bk"}}})
check("POST llm-config with ws ok", st == 200 and j.get("ok") is True, str(j)[:120])
st, j = call("/api/llm-config")
check("ws persisted roundtrip",
      j["config"]["api_key"] == "sk-1" and j["config"]["web_search"]["enabled"] is True
      and j["config"]["web_search"]["bing_key"] == "bk", str(j["config"].get("web_search")))

st, j = call("/api/version")
check("version -> %d" % md_server.MD_SERVER_VERSION,
      st == 200 and j.get("version") == md_server.MD_SERVER_VERSION, str(j))

# ── 润色路由：openai 后端校验 & 联网降级 ──
st, j = call("/api/rewrite", "POST", {"text": "测试",
                                      "config": {"backend": "openai", "model": "gpt-4o-mini"}})
check("rewrite openai no key -> ok:false with hint",
      st == 200 and j.get("ok") is False and "API Key" in j.get("error", ""), str(j)[:160])
st, j = call("/api/rewrite", "POST", {"text": "测试",
                                      "config": {"backend": "openai", "api_key": "sk-x"}})
check("rewrite openai no model -> ok:false with hint",
      st == 200 and j.get("ok") is False and "模型" in j.get("error", ""), str(j)[:160])

# 联网开启 + 不可达 custom url → 静默降级（LM Studio 在线时整链走通）
lmstudio_up = False
try:
    urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=3)
    lmstudio_up = True
except Exception:
    pass
print("(LM Studio :1234 online: %s)" % lmstudio_up)

cfg = {"backend": "lmstudio", "web_search": {"enabled": True, "backend": "custom",
                                             "custom_url": "http://127.0.0.1:9/x?q={q}"}} if lmstudio_up else None
if cfg:
    st, j = call("/api/rewrite", "POST", {"text": "测试文本", "config": cfg}, timeout=120)
    check("rewrite ws unreachable -> degraded flag",
          st == 200 and j.get("ok") is True and j.get("web_search") == "degraded", str(j)[:160])
else:
    print("(skip online-path ws tests: LM Studio offline)")

# 联网关闭 → off 标志
if lmstudio_up:
    st, j = call("/api/rewrite", "POST", {"text": "测试文本",
                                          "config": {"backend": "lmstudio"}}, timeout=120)
    check("rewrite ws off -> off flag",
          st == 200 and j.get("ok") is True and j.get("web_search") == "off", str(j)[:160])

httpd.shutdown()
print("\nRESULT: %s (%d fail)" % ("PASS" if not fails else "FAIL", len(fails)))
sys.exit(1 if fails else 0)