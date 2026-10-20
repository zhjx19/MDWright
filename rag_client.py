# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""RAG 客户端 — 通过 HTTP 调 rag-assistant 8767 外部 API（纯标准库零依赖）。

只做检索不做生成：/api/kb/query 返回知识库摘录 context，由调用方拼进 LLM prompt。
移植自 structured-writer 的成熟实现；3 次重试是因为冷启动时 embedding
模型首次加载慢，首请求超时属正常现象。
"""
import json
import urllib.request
import urllib.error
from typing import Optional


class RAGClientError(Exception):
    pass


class RAGClient:
    def __init__(self, base_url="http://127.0.0.1:8767", timeout=60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def query(self, kb: str, query_text: str, top_k: int = 5,
              score_threshold: Optional[float] = None,
              include_header: bool = False) -> dict:
        """检索知识库返回上下文，不调用 LLM 生成

        参数:
            kb: 知识库名称，空字符串=自动路由
            query_text: 查询文本
            top_k: 返回文档数
            score_threshold: 相似度阈值
            include_header: 是否返回文档元数据（headers）

        返回:
            {"context": str, "sources": list, "has_context": bool,
             "kb": str, "headers": dict} (headers 仅 include_header=True 时有)
        """
        body = {
            "kb": kb or "",
            "query": query_text,
            "top_k": top_k,
            "include_header": include_header,
        }
        if score_threshold is not None:
            body["score_threshold"] = score_threshold

        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

        # 超时重试：冷启动时 embedding 第一次加载慢
        for attempt in range(3):
            req = urllib.request.Request(
                f"{self.base_url}/api/kb/query",
                data=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                raise RAGClientError(f"HTTP {e.code}: {err_body[:300]}")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 2:
                    continue
                raise RAGClientError(f"连接失败({attempt + 1}次重试): {getattr(e, 'reason', e)}")
        # unreachable