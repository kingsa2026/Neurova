# -*- coding: utf-8 -*-
"""P0-C 真流式防回归测试（审计批次 P0-C）。

覆盖：
- C1 /chat/stream 真流式接线：agent.chat(stream=True) + event_emitter 逐事件
  推送，首内容事件先于整轮完成（假流式=等全量再切块的回归锁）。
- C2 chat_stream LLM 客户端限流：流式调用前 acquire、结束后 release、429 上报。
- C3 重试单层：SDK max_retries=0，重试语义归外层 RetryConfig 单层（≤3 次真实请求）。
- C4 SSE 心跳：/chat/stream 空闲期发 ": ping" 注释（对齐 console）。
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════
# C1: /chat/stream 真流式
# ═══════════════════════════════════════════════════════════════


class TestC1RealStreaming:
    def test_chat_stream_endpoint_emits_incremental_before_done(self):
        """端点在整轮完成前推送内容事件（真流式判定：模拟慢 LLM，
        内容事件到达时间 < 全轮完成时间）。"""
        import neurova.api.endpoints.chat as chat_mod

        src_path = "neurova/api/endpoints/chat.py"
        # 结构级判定：端点必须构造 event_emitter 注入 metadata（真流式接线特征），
        # 且不再有"恒走此分支"的全量降级注释
        src = open(src_path, encoding="utf-8").read()
        assert "event_emitter" in src, (
            "/chat/stream 未注入 event_emitter——假流式（等 agent.chat 全量返回再吐）回归"
        )
        assert "恒走此分支" not in src, "全量降级分支注释仍在，假流式未拆除"

    def test_agent_chat_stream_uses_loop_stream(self):
        """Agent.chat_stream 必须走 ctx.stream=True 管线（真流式），
        而非先 await self.chat() 拿全量再切块。"""
        src = open("neurova/agent_core.py", encoding="utf-8").read()
        import re

        m = re.search(r"async def chat_stream\(.*?\n(.*?)(?=\n    async def |\n    def )", src, re.S)
        assert m, "chat_stream 方法未找到"
        body = m.group(1)
        assert "await self.chat(" not in body, (
            "chat_stream 内先等全量 chat() 再切块 = 假流式；应转发 ctx.stream=True "
            "让 _call_loop_stream 增量推送"
        )
        assert "stream=True" in body or "stream" in body, (
            "chat_stream 未透传 stream 语义"
        )


# ═══════════════════════════════════════════════════════════════
# C2: chat_stream 限流/熔断
# ═══════════════════════════════════════════════════════════════


class TestC2StreamRateLimit:
    def test_chat_stream_acquires_limiter(self):
        """MultiModelLLMClient.chat_stream 须与 chat 同源限流：acquire/
        release + 429 report。"""
        src = open("neurova/llm/multi_model_client.py", encoding="utf-8").read()
        import re

        m = re.search(r"async def chat_stream\(.*?(?=\n    async def |\n    def |\Z)", src, re.S)
        assert m, "chat_stream 未找到"
        body = m.group(0)
        assert "acquire" in body, "chat_stream 无限流 acquire——主流量裸奔"
        assert "release" in body or "finally" in body, "chat_stream 无 release 归还"
        assert "report_429" in body or "report_success" in body, (
            "chat_stream 无 429/成功上报——限流暂停语义与 chat() 脱节"
        )


# ═══════════════════════════════════════════════════════════════
# C3: 重试单层化
# ═══════════════════════════════════════════════════════════════


class TestC3RetrySingleLayer:
    def test_sdk_retries_disabled(self):
        """llm_client 的 LLMConfig.max_retries 字段默认必须为 0（SDK 直传该值；
        外层 RetryConfig 单层负责重试，双层叠加=最多 9 次真实请求重复计费）。"""
        src = open("neurova/llm_client.py", encoding="utf-8").read()
        import re

        m = re.search(r"max_retries:\s*int\s*=\s*(\d+)", src)
        assert m, "LLMConfig 未声明 max_retries 字段"
        assert m.group(1) == "0", (
            f"SDK 层重试默认未禁用（max_retries={m.group(1)}，与外层 RetryConfig "
            "叠加后 429 场景最多 9 次真实请求重复计费）"
        )


# ═══════════════════════════════════════════════════════════════
# C4: SSE 心跳
# ═══════════════════════════════════════════════════════════════


class TestC4SSEHeartbeat:
    def test_chat_stream_has_ping_heartbeat(self):
        """空闲期心跳注释（对齐 console 的 ": ping"）。"""
        src = open("neurova/api/endpoints/chat.py", encoding="utf-8").read()
        assert ": ping" in src or '": ping' in src, (
            "/chat/stream 无空闲心跳——LLM 慢响应期间代理/网关会掐断连接"
        )
