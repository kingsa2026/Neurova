"""流内错误编码铁律测试（OpenClaw 启发 P0-1）

背景（docs/Neurova_OpenClaw代码级对比_2026-09-04.md §3 P0-1）：
  OpenClaw 的流协议铁律（llm-core types.ts L202）："Once invoked, request/
  model/runtime failures should be encoded in the returned stream, not
  thrown"——provider 调用一旦开始，一切失败编码为流内错误消息而非异常。

Neurova 现状与缺口：
  - multi_model_client.chat_stream 是"错误进流"的唯一咽喉（except 分支
    yield {"error": str}），但只有裸字符串，丢掉了异常类别——消费方
    openai_loop._raise_for_error_dict 预留的 error_type 键永远缺失，
    只能靠 HTTP 语义字符串兜底二次猜测（sensetime 404 案的根因链）。
  - llm_client.chat_stream_async 中途失败直接 raise，调用方（本咽喉的
    async for）虽兜底接住进流，但请求发起**之前**的失败（配置缺失、
    客户端构造失败）会绕过咽喉直接炸穿。

铁律落点：
  1. 咽喉补 error_type（五类标准错误，error_mapping 单一事实源）
  2. 首块之前的一切失败编码为流内错误 dict（"No client available" 同样
     归一，不再是无类型裸字符串）
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.llm.multi_model_client import MultiModelLLMClient
from neurova.llm_client import LLMRateLimitError


class TestInStreamErrorEncoding(unittest.TestCase):
    """铁律：chat_stream 的一切失败都编码为流内错误 dict，不抛异常。"""

    def setUp(self):
        self.manager = MultiModelLLMClient(strategy=None).__class__(
            # 占位防误用：实际用 _make_manager 构造
        ) if False else None

    def _make_manager(self):
        manager = MultiModelLLMClient.__new__(MultiModelLLMClient)
        # 最小初始化：只填 chat_stream 路径依赖的字段
        manager._provider_manager = MagicMock()
        manager._clients = {}
        manager._current_provider_id = None
        manager._current_model = None
        return manager

    def _stream_one(self, manager, chunks, exc=None):
        """驱动 chat_stream 到第一个错误 dict 并返回它。"""

        async def _fake_stream(messages, **kwargs):
            for c in chunks:
                yield c
            if exc is not None:
                raise exc

        client = MagicMock()
        client.client.chat_stream_async = _fake_stream
        client.increment_request = MagicMock()
        client.model = "gpt-test"
        client.provider = MagicMock(id="test-provider")
        manager._get_client_for_request = MagicMock(return_value=client)
        chunks_out = list(asyncio.run(_collect(manager.chat_stream([{"role": "user", "content": "hi"}]))))
        return chunks_out

    def test_midstream_exception_yields_error_dict_with_type(self):
        """流中途 provider 异常 → 编码为 {"error", "error_type"} 进流，不抛。"""
        manager = self._make_manager()
        exc = LLMRateLimitError("429 Too Many Requests")
        chunks = self._stream_one(manager, [{"delta": "hello"}], exc=exc)

        err = [c for c in chunks if isinstance(c, dict) and c.get("error")]
        self.assertEqual(len(err), 1, f"异常必须编码进流，got chunks={chunks!r}")
        self.assertEqual(
            err[0]["error_type"],
            "rate_limited",
            "error_type 必须是五类标准错误（error_mapping 单一事实源）",
        )
        self.assertIn("429", err[0]["error"])

    def test_midstream_exception_is_not_raised(self):
        """异常不得穿透 chat_stream 生成器边界（_collect 穿透即断言失败）。"""
        manager = self._make_manager()
        chunks = self._stream_one(manager, [], exc=RuntimeError("boom midstream"))
        err = [c for c in chunks if isinstance(c, dict) and c.get("error")]
        self.assertEqual(len(err), 1)

    def test_no_client_yields_typed_error(self):
        """无可用客户端也走归一化（带 error_type），不再是无类型裸字符串。"""
        manager = self._make_manager()
        manager._get_client_for_request = MagicMock(return_value=None)
        chunks = list(asyncio.run(_collect(manager.chat_stream([{"role": "user", "content": "hi"}]))))
        err = [c for c in chunks if isinstance(c, dict) and c.get("error")]
        self.assertEqual(len(err), 1)
        self.assertIn("error_type", err[0], "No client available 也必须带五类 error_type")

    def test_error_dict_payload_contract(self):
        """错误 dict 契约固定三键：error/error_type/retryable（消费方据此分类）。"""
        manager = self._make_manager()
        chunks = self._stream_one(manager, [], exc=LLMRateLimitError("429"))
        err = [c for c in chunks if isinstance(c, dict) and c.get("error")][0]
        self.assertEqual(set(err.keys()), {"error", "error_type", "retryable"})
        self.assertTrue(err["retryable"])

    def test_failed_call_counted(self):
        """异常进流的同时失败计数不丢（增量可观测性不回退）。"""
        manager = self._make_manager()
        client = MagicMock()
        client.client.chat_stream_async = AsyncMock(side_effect=RuntimeError("boom"))
        client.increment_request = MagicMock()
        client.model = "m"
        client.provider = MagicMock(id="p")
        manager._get_client_for_request = MagicMock(return_value=client)
        list(asyncio.run(_collect(manager.chat_stream([{"role": "user", "content": "hi"}]))))
        client.increment_request.assert_called_once_with(success=False)


async def _collect(agen):
    out = []
    try:
        async for c in agen:
            out.append(c)
    except Exception as e:  # 铁律断言辅助：异常穿透即失败
        raise AssertionError(f"chat_stream 抛出异常而非编码进流: {e!r}") from e
    return out


if __name__ == "__main__":
    unittest.main()
