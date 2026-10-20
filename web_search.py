# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""联网搜索模块（纯标准库 urllib 零依赖）。

配置驱动，key 用户自填；返回统一 {"results":[{title,url,snippet}], "success", "error"}。
支持：DuckDuckGo（免费无 key）/ Tavily / Google Custom Search / Bing / 自定义 API。
模式移植自 rag-assistant 的 search.py，按本项目零依赖约束全部用 urllib 重写。
"""
import json
import logging
import urllib.parse
import urllib.request
import re

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class WebSearch:
    """联网搜索。config 形如:
    {"enabled": bool, "backend": "duckduckgo"|"tavily"|"google"|"bing"|"custom",
     "api_key": "", "google_key": "", "google_cx": "", "bing_key": "",
     "custom_url": "", "max_results": int}
    """

    BACKENDS = ("duckduckgo", "tavily", "google", "bing", "custom")

    def __init__(self, config=None):
        cfg = config if isinstance(config, dict) else {}
        self.enabled = bool(cfg.get("enabled"))
        self.backend = str(cfg.get("backend") or "duckduckgo").lower()
        if self.backend not in self.BACKENDS:
            self.backend = "duckduckgo"
        self.api_key = str(cfg.get("api_key") or "")
        self.google_key = str(cfg.get("google_key") or "")
        self.google_cx = str(cfg.get("google_cx") or "")
        self.bing_key = str(cfg.get("bing_key") or "")
        self.custom_url = str(cfg.get("custom_url") or "")
        try:
            self.max_results = max(1, min(10, int(cfg.get("max_results", 3))))
        except Exception:
            self.max_results = 3

    def search(self, query, max_results=None):
        """执行搜索。返回 {"results": [{title,url,snippet}], "success": bool, "error": str}"""
        if not self.enabled:
            return {"results": [], "success": False, "error": "联网搜索已关闭"}
        if not str(query).strip():
            return {"results": [], "success": False, "error": "搜索关键词为空"}
        n = max_results or self.max_results
        try:
            fn = {"duckduckgo": self._duckduckgo, "tavily": self._tavily,
                  "google": self._google, "bing": self._bing,
                  "custom": self._custom}[self.backend]
            return fn(str(query), n)
        except Exception as e:
            logger.error("搜索失败: %s", e)
            return {"results": [], "success": False, "error": str(e)}

    # ---- DuckDuckGo（免费无 key；html 端点纯 HTML 抓取） ----
    def _duckduckgo(self, query, n):
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        results = []
        for m in re.finditer(
                r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
                r'.*?class="result__snippet"[^>]*>(.*?)</',
                html, re.DOTALL):
            results.append({
                "title": re.sub(r"<.*?>", "", m.group(2)).strip(),
                "url": m.group(1),
                "snippet": re.sub(r"<.*?>", "", m.group(3)).strip(),
            })
            if len(results) >= n:
                break
        if not results:
            return {"results": [], "success": False, "error": "DuckDuckGo 未返回结果（可能被限流）"}
        return {"results": results, "success": True}

    # ---- Tavily（需 api_key） ----
    def _tavily(self, query, n):
        if not self.api_key:
            return {"results": [], "success": False, "error": "Tavily API Key 未配置"}
        payload = json.dumps({"api_key": self.api_key, "query": query,
                              "max_results": n}).encode("utf-8")
        req = urllib.request.Request("https://api.tavily.com/search", data=payload,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        out = [{"title": r.get("title", ""), "url": r.get("url", ""),
                "snippet": r.get("content", "")}
               for r in data.get("results", [])[:n]]
        if not out:
            return {"results": [], "success": False, "error": "Tavily 未返回结果"}
        return {"results": out, "success": True}

    # ---- Google Custom Search JSON API（需 google_key + google_cx） ----
    def _google(self, query, n):
        if not self.google_key or not self.google_cx:
            return {"results": [], "success": False, "error": "Google API Key 或 CX 未配置"}
        url = ("https://www.googleapis.com/customsearch/v1?key=" +
               urllib.parse.quote(self.google_key) + "&cx=" +
               urllib.parse.quote(self.google_cx) + "&q=" +
               urllib.parse.quote(query) + "&num=%d" % min(n, 10))
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        out = [{"title": i.get("title", ""), "url": i.get("link", ""),
                "snippet": i.get("snippet", "")}
               for i in data.get("items", [])[:n]]
        if not out:
            return {"results": [], "success": False, "error": "Google 未返回结果"}
        return {"results": out, "success": True}

    # ---- Bing Search API v7（需 bing_key） ----
    def _bing(self, query, n):
        if not self.bing_key:
            return {"results": [], "success": False, "error": "Bing API Key 未配置"}
        url = ("https://api.bing.microsoft.com/v7.0/search?q=" +
               urllib.parse.quote(query) + "&count=%d" % min(n, 50))
        req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": self.bing_key})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        out = [{"title": i.get("name", ""), "url": i.get("url", ""),
                "snippet": i.get("snippet", "")}
               for i in data.get("webPages", {}).get("value", [])[:n]]
        if not out:
            return {"results": [], "success": False, "error": "Bing 未返回结果"}
        return {"results": out, "success": True}

    # ---- 自定义 API（URL 中 {q} 与 {key} 占位；返回 JSON，兼容常见结构） ----
    def _custom(self, query, n):
        if not self.custom_url:
            return {"results": [], "success": False, "error": "自定义 API URL 未配置"}
        url = (self.custom_url
               .replace("{q}", urllib.parse.quote(query))
               .replace("{key}", urllib.parse.quote(self.api_key)))
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (data.get("results") or data.get("items")
                     or data.get("data") or [])
        out = []
        for item in items[:n]:
            if isinstance(item, str):
                out.append({"title": "", "url": "", "snippet": item})
            elif isinstance(item, dict):
                out.append({
                    "title": str(item.get("title", item.get("name", "")) or ""),
                    "url": str(item.get("url", item.get("link", "")) or ""),
                    "snippet": str(item.get("snippet", item.get(
                        "body", item.get("content", item.get("description", "")))) or ""),
                })
        if not out:
            return {"results": [], "success": False, "error": "自定义 API 未返回结果"}
        return {"results": out, "success": True}


def format_results(results, max_chars=2400):
    """把搜索结果格式化为 prompt 注入用的【网络资料】文本。"""
    lines = []
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        snippet = (r.get("snippet") or "").strip()
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"
        url = (r.get("url") or "").strip()
        head = ("[%d] %s" % (i, title)) if title else ("[%d]" % i)
        if url:
            head += " (%s)" % url
        lines.append(head + ("\n" + snippet if snippet else ""))
    text = "\n\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（已截断）"
    return text