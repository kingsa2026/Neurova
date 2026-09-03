"""
TDD 测试: AgentLLMClient.chat() 错误包装层透明化

被测 Bug:
    neurova/agent_core.py:132-145 的 AgentLLMClient.chat() 把
    MultiModelLLMClient.chat() 返回的结构化 dict
    {"success": False, "error": "...", "model": "...", "provider": "..."}
    包装为 LLMResponse(content="[LLM Error] ..."),丢失了 model/provider 字段,
    且包装时无任何日志,导致:
      1. 前端只看到 "[LLM Error] No client available" 字符串,无法区分错误类型
      2. 运维需翻 server.log 找原始 error 字段
      3. 包装层完全静默,无人知道何时发生包装

修复目标 (surgical,保留 LLMResponse 契约):
    包装失败响应前,用 logger.warning 记录原始 error/model/provider,
    不抹除原始错误信息,不改变返回类型。

关联源码:
    - neurova/agent_core.py:132-145 (AgentLLMClient.chat 包装层)
    - neurova/llm/multi_model_client.py:360-365 (No client available — 无 model/provider)
    - neurova/llm/multi_model_client.py:380-387 (Exception 路径 — 含 model/provider)

运行:
    cd e:\\项目\\Neurova
    python -m unittest tests.unit.agent.test_agent_llm_error_logging -v

注意:
    neurova.agent_core 存在循环导入问题(agent_core → agent/__init__ → agent_core),
    故在 setUp 内导入 AgentLLMClient,与 tests/unit/agent/ 下其他测试文件保持一致。
"""

import logging
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class _ListLogHandler(logging.Handler):
    """收集所有日志记录,用于断言"无 WARNING 日志"。

    assertLogs 要求至少有一条日志,无法断言"零日志",故用此 handler。
    """

    def __init__(self, level=logging.NOTSET):
        super().__init__(level=level)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class TestAgentLLMClientErrorLogging(unittest.IsolatedAsyncioTestCase):
    """AgentLLMClient.chat() 错误包装层日志透明化测试。

    5 个用例覆盖:
      1. 失败路径记录 WARNING 且日志含 error/model/provider 三个字段
      2. 失败路径仍返回 LLMResponse(契约不破坏)
      3. LLMResponse.content 包含原始 error 字符串(不抹除/不简化)
      4. 成功路径不应触发 WARNING 日志
      5. result 缺 model/provider 字段时日志 fallback 为 "unknown"(不抛 KeyError)
    """

    def setUp(self):
        # 在 setUp 内导入,规避 agent_core 循环导入问题
        from neurova.agent_core import AgentLLMClient
        from neurova.llm_client import LLMResponse

        self.AgentLLMClient = AgentLLMClient
        self.LLMResponse = LLMResponse

    def _make_client(self) -> "AgentLLMClient":
        """构造 model='auto' 的 AgentLLMClient。"""
        return self.AgentLLMClient(model="auto", provider_id="")

    async def _run_chat_with_result(self, result_dict: dict):
        """mock MultiModelLLMClient.chat 返回 result_dict,执行 AgentLLMClient.chat。

        patch 目标是 neurova.llm.multi_model_client.get_multi_model_client,
        因为 AgentLLMClient._get_client 在函数内部 from ... import get_multi_model_client。
        """
        client = self._make_client()
        mock_inner = MagicMock()
        mock_inner.chat = AsyncMock(return_value=result_dict)
        with patch(
            "neurova.llm.multi_model_client.get_multi_model_client",
            return_value=mock_inner,
        ):
            return await client.chat([{"role": "user", "content": "hi"}])

    # ===== RED→GREEN #1: 失败时记录 WARNING 日志含诊断信息 =====
    async def test_error_response_logs_warning_with_diagnostics(self):
        """失败路径应记录 WARNING,且日志消息含 error/model/provider 三个字段。

        这是本次修复的核心断言:包装层不再静默。
        """
        with self.assertLogs("neurova.agent_core", level="WARNING") as cm:
            await self._run_chat_with_result({
                "success": False,
                "error": "No client available",
                "model": "gpt-4",
                "provider": "openai",
            })
        combined = " | ".join(cm.output)
        self.assertIn("No client available", combined, "日志必须含原始 error 字段")
        self.assertIn("gpt-4", combined, "日志必须含 model 字段")
        self.assertIn("openai", combined, "日志必须含 provider 字段")

    # ===== RED→GREEN #2: 失败时仍返回 LLMResponse(契约不破坏) =====
    async def test_error_response_still_returns_llm_response(self):
        """失败路径返回值必须是 LLMResponse 实例,不能改成 dict 或 None。

        保证 chat_pipeline / openai_loop 等调用方契约不破坏。
        """
        with self.assertLogs("neurova.agent_core", level="WARNING"):
            result = await self._run_chat_with_result({
                "success": False,
                "error": "boom",
                "model": "m",
                "provider": "p",
            })
        self.assertIsInstance(
            result, self.LLMResponse,
            "失败路径必须返回 LLMResponse,契约不可破坏",
        )

    # ===== RED→GREEN #3: LLMResponse.content 包含原始 error 字符串(不抹除) =====
    async def test_error_response_content_contains_original_error(self):
        """content 必须包含原始 error 字段的完整字符串,不能简化或抹除。

        遵循"放大视角找根因,不从表面抹除报错信息"原则。
        """
        original_error = "ConnectionResetError: connection reset by peer"
        with self.assertLogs("neurova.agent_core", level="WARNING"):
            result = await self._run_chat_with_result({
                "success": False,
                "error": original_error,
                "model": "claude-3",
                "provider": "anthropic",
            })
        self.assertIn(
            "ConnectionResetError", result.content,
            "content 必须保留原始错误的关键标识,不能抹除",
        )
        self.assertIn(
            "connection reset by peer", result.content,
            "content 必须保留原始错误的具体描述",
        )

    # ===== RED→GREEN #4: 成功路径不应有 WARNING 日志 =====
    async def test_success_response_no_warning(self):
        """成功路径不应触发 WARNING 日志,避免日志噪音。

        用 _ListLogHandler 手动捕获(assertLogs 无法断言"零日志")。
        """
        success_resp = self.LLMResponse(content="hello", model="gpt-4")
        client = self._make_client()
        mock_inner = MagicMock()
        mock_inner.chat = AsyncMock(return_value={
            "success": True,
            "response": success_resp,
            "duration": 0.1,
            "model": "gpt-4",
            "provider": "openai",
        })

        agent_logger = logging.getLogger("neurova.agent_core")
        handler = _ListLogHandler(level=logging.WARNING)
        agent_logger.addHandler(handler)
        try:
            with patch(
                "neurova.llm.multi_model_client.get_multi_model_client",
                return_value=mock_inner,
            ):
                result = await client.chat([{"role": "user", "content": "hi"}])
        finally:
            agent_logger.removeHandler(handler)

        warning_records = [
            r for r in handler.records if r.levelno >= logging.WARNING
        ]
        self.assertEqual(
            len(warning_records), 0,
            f"成功路径不应有 WARNING 日志,实际捕获: "
            f"{[r.getMessage() for r in warning_records]}",
        )
        # 顺便验证成功路径正确解包 LLMResponse
        self.assertIsInstance(result, self.LLMResponse)
        self.assertEqual(result.content, "hello")

    # ===== RED→GREEN #5: result 缺 model/provider 字段时日志 fallback "unknown" =====
    async def test_error_with_missing_fields_logs_unknown(self):
        """result 缺 model/provider 字段时,日志应 fallback 为 "unknown",不抛 KeyError。

        现实场景: MultiModelLLMClient.chat() 的 "No client available" 路径
        (multi_model_client.py:360-365) 只返回 {"success": False, "error": "..."},
        不含 model/provider,此时日志必须 graceful fallback。
        """
        with self.assertLogs("neurova.agent_core", level="WARNING") as cm:
            await self._run_chat_with_result({
                "success": False,
                "error": "No client available",
                # 故意不提供 model / provider
            })
        combined = " | ".join(cm.output)
        self.assertIn("No client available", combined)
        self.assertIn("unknown", combined, "缺字段时必须 fallback 为 unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
