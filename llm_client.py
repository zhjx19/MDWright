# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""LLM 统一客户端 — LM Studio / Ollama / OpenAI 兼容 / DeepSeek（纯标准库 urllib 零依赖）。

  - LM Studio:  http://<host>:1234/v1/chat/completions
  - Ollama:     http://<host>:11434/api/chat
  - OpenAI 兼容: https://api.openai.com/v1/chat/completions 等（硅基流动、OpenRouter 同构端点通吃）
  - DeepSeek:   https://api.deepseek.com/v1/chat/completions（一等支持：默认地址与模型预设；
                deepseek-reasoner 不支持采样参数，请求体不带 temperature，否则可能 400）

base_url 填到根或 /v1 均可，自动补全。模型列表、配置校验、调用超时与错误归一互相独立，
供 md_server.py 注解/润色/测试共用。
"""
import json
import time
import urllib.request
import urllib.error


class LLMError(Exception):
    pass


class LLMClient:
    """LLM 统一客户端。config 形如:
    {"backend": "lmstudio"|"ollama"|"openai"|"deepseek", "base_url": "...", "model": "",
     "api_key": "", "timeout": 180, "max_tokens": 2048, "temperature": 0.7,
     "web_search": {...联网查询配置，本类不消费，见 web_search.py...}}
    """

    # OpenAI 兼容协议族的后端（同一套端点/鉴权/载荷）
    OPENAI_LIKE = ("openai", "deepseek")

    def __init__(self, config=None):
        cfg = config or {}
        self.backend = (cfg.get("backend") or "lmstudio").lower()
        self.base_url = (cfg.get("base_url") or "").rstrip("/")
        self.model = cfg.get("model") or ""
        self.api_key = cfg.get("api_key") or ""
        try:
            self.timeout = int(cfg.get("timeout", 180))
        except Exception:
            self.timeout = 180
        try:
            self.max_tokens = int(cfg.get("max_tokens", 2048))
        except Exception:
            self.max_tokens = 2048
        try:
            self.temperature = float(cfg.get("temperature", 0.7))
        except Exception:
            self.temperature = 0.7
        if not self.base_url:
            if self.backend == "ollama":
                self.base_url = "http://localhost:11434"
            elif self.backend == "deepseek":
                self.base_url = "https://api.deepseek.com/v1"
            elif self.backend == "openai":
                self.base_url = "https://api.openai.com/v1"
            else:
                self.base_url = "http://localhost:1234"
        # OpenAI 兼容惯例 base_url 含 /v1；填根地址时自动补，两种填法都通
        if self.backend in self.OPENAI_LIKE and not self.base_url.endswith("/v1"):
            self.base_url = self.base_url + "/v1"

    def _is_reasoner(self):
        """DeepSeek 推理模型：不支持采样参数（temperature/top_p），传了可能 400。"""
        return self.backend == "deepseek" and "reasoner" in (self.model or "").lower()

    # ---- 端点与载荷 ----
    def _chat_url(self):
        if self.backend == "ollama":
            return self.base_url + "/api/chat"
        if self.backend in self.OPENAI_LIKE:
            return self.base_url + "/chat/completions"
        return self.base_url + "/v1/chat/completions"

    def _models_url(self):
        if self.backend == "ollama":
            return self.base_url + "/api/tags"
        if self.backend in self.OPENAI_LIKE:
            return self.base_url + "/models"
        return self.base_url + "/v1/models"

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.backend in self.OPENAI_LIKE:
            if not self.api_key:
                label = "DeepSeek" if self.backend == "deepseek" else "OpenAI 兼容"
                raise LLMError("%s 后端需先在 LLM 设置中填写 API Key" % label)
            h["Authorization"] = "Bearer " + self.api_key
        return h

    def list_models(self):
        """取当前后端可用模型名列表。LM Studio/OpenAI: data[].id；Ollama: models[].name。"""
        req = urllib.request.Request(self._models_url(), method="GET",
                                     headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=min(self.timeout, 15)) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as e:
            raise LLMError(str(e))
        if self.backend == "ollama":
            names = [m.get("name", "") for m in data.get("models", [])]
        else:
            names = [m.get("id", "") for m in data.get("data", [])]
        return [n for n in names if n]

    def test_connection(self):
        """返回 (ok, message)。模型列表可为空但连接通 —— 也算成功（提示可刷新）。"""
        try:
            models = self.list_models()
            if models:
                return True, "连接成功，可用模型 %d 个：%s" % (
                    len(models), "、".join(models[:6]) + ("…" if len(models) > 6 else ""))
            return True, "连接成功，但后端未返回模型列表。"
        except Exception as e:
            return False, "连接失败：%s" % e

    def chat(self, messages, max_tokens=None, temperature=None):
        """一次对话，返回回复文本。messages 为 [{"role","content"}, ...]。"""
        mt = max_tokens or self.max_tokens
        tp = temperature if temperature is not None else self.temperature
        if self.backend == "ollama":
            payload = json.dumps({
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"num_predict": mt, "temperature": tp},
            }).encode("utf-8")
        elif self.backend in self.OPENAI_LIKE:
            if not self.model:
                label = "DeepSeek" if self.backend == "deepseek" else "OpenAI 兼容"
                raise LLMError("%s 后端需先在 LLM 设置中选择模型" % label)
            p = {
                "model": self.model,
                "messages": messages,
                "max_tokens": mt,
            }
            # deepseek-reasoner 不支持采样参数：带上 temperature 可能直接 400
            if not self._is_reasoner():
                p["temperature"] = tp
            payload = json.dumps(p).encode("utf-8")
        else:
            p = {"messages": messages, "max_tokens": mt, "temperature": tp}
            if self.model:
                p["model"] = self.model
            payload = json.dumps(p).encode("utf-8")
        req = urllib.request.Request(self._chat_url(), data=payload,
                                     headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            raise LLMError("HTTP %d: %s" % (e.code, err[:300]))
        except urllib.error.URLError as e:
            raise LLMError("连接失败: %s" % getattr(e, "reason", e))
        except Exception as e:
            raise LLMError("LLM 调用异常: %s" % e)
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
            if self.backend == "ollama":
                return data.get("message", {}).get("content", "").strip()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise LLMError("响应解析失败: %s" % e)

    # ---- 本工具业务封装：润色 / 注解 ----
    def polish(self, text):
        """对话式润色（保持语义与长度，优化表达）。保留 markdown 标记不动。"""
        import html as _h
        sysp = ("你是一个中文写作润色助手。用户给你一段文本，请润色优化："
                "保持原意、结构、篇幅和 Markdown 标记（#、*、`、链接等）完全不变，"
                "仅优化表达的通顺、准确与书面化。只输出润色后的文本，不要解释。")
        return self.chat([{"role": "system", "content": sysp},
                          {"role": "user", "content": text}])

    def explain(self, text):
        """注解式解释：对选中片段给出简要的注释/解释，供用户作为备注模板确认后使用。"""
        sysp = ("你是一个 Markdown 文档注释助手。用户给出一段文本，请你为它写一条"
                "简洁的备注/批注：解释它的含义或补充要点，2-4 句，第一人称可省略。"
                "直接输出备注内容，不要引号、不要'备注：'前缀。")
        return self.chat([{"role": "system", "content": sysp},
                          {"role": "user", "content": text}])