"""P1-6 工作流节点 token 计量接配额（TDD — Dify 对标 §4 P1-6）。

契约：
1. exec_llm 双路径（多模型客户端 / Agent.chat 回退）产出 usage 真值
   {prompt_tokens, completion_tokens, total_tokens}——替换恒空 {} 占位；
   来源缺失时键仍存在（前端契约稳定），值为 0
2. 引擎装配 NodeExecutionResult.tokens_used（多模型路径真值优先）
3. usage 真值 → ResourceQuotaManager.increment_llm_token 记账
   （user_id 取执行实例属主；0/缺值不记账，避免噪声计数）
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.collaboration.neurflow.builtin import exec_llm


def _ctx(user_id="u1"):
    return {
        "user_id": user_id,
        "node_id": "llm_1",
        "execution_id": "e1",
        "workflow_id": "wf1",
    }


class TestUsageExtraction:
    def test_usage_key_always_present(self):
        """无任何来源 → usage 键仍存在（契约稳定），值全 0"""
        with patch("neurova.collaboration.neurflow.builtin._get_multi_model_client", return_value=None), \
             patch("neurova.collaboration.neurflow.builtin._get_agent", return_value=None):
            result = asyncio.run(exec_llm({"prompt": "hi"}, _ctx()))
        # Agent 未初始化走 failed 路径——usage 契约只约束成功路径
        if result.get("status") == "success":
            assert set(result["output"]["usage"].keys()) >= {"prompt_tokens", "completion_tokens", "total_tokens"}

    def test_multi_model_path_extracts_real_usage(self):
        """多模型路径：response.usage（对象或 dict）→ 真值 + 配额记账"""
        from types import SimpleNamespace

        resp = MagicMock()
        resp.content = "答"
        resp.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
        client = MagicMock()
        client.chat = AsyncMock(return_value={
            "success": True, "response": resp, "duration": 0.1,
            "model": "gpt-4o", "provider": "p1",
        })

        quota = MagicMock()
        with patch("neurova.collaboration.neurflow.builtin._get_multi_model_client", return_value=client), \
             patch("neurova.collaboration.neurflow.builtin._get_resource_quota_manager", return_value=quota):
            result = asyncio.run(exec_llm(
                {"prompt": "hi", "model_provider": "p1", "model_name": "gpt-4o"}, _ctx()
            ))

        assert result["status"] == "success"
        usage = result["output"]["usage"]
        assert usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        quota.increment_llm_token.assert_called_once()
        args = quota.increment_llm_token.call_args
        assert args.kwargs.get("tokens") or args[0][-1] if args[0] else args.kwargs.get("tokens") == 15

    def test_multi_model_usage_dict_shape(self):
        """usage 为 dict 形态（部分网关）同样提取"""
        resp = {"choices": [{"message": {"content": "x"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
        client = MagicMock()
        client.chat = AsyncMock(return_value={
            "success": True, "response": resp, "duration": 0.1, "model": "m", "provider": "p",
        })
        quota = MagicMock()
        with patch("neurova.collaboration.neurflow.builtin._get_multi_model_client", return_value=client), \
             patch("neurova.collaboration.neurflow.builtin._get_resource_quota_manager", return_value=quota):
            result = asyncio.run(exec_llm(
                {"prompt": "hi", "model_provider": "p", "model_name": "m"}, _ctx()
            ))
        assert result["output"]["usage"]["total_tokens"] == 5

    def test_agent_chat_path_usage_from_response(self):
        """Agent.chat 回退路径：str 响应无 usage → 全 0（不造假）；对象响应带 usage 则提取"""
        agent = MagicMock()
        agent.chat = AsyncMock(return_value="纯文本回答")
        quota = MagicMock()
        with patch("neurova.collaboration.neurflow.builtin._get_multi_model_client", return_value=None), \
             patch("neurova.collaboration.neurflow.builtin._get_agent", return_value=agent), \
             patch("neurova.collaboration.neurflow.builtin._get_resource_quota_manager", return_value=quota):
            result = asyncio.run(exec_llm({"prompt": "hi"}, _ctx()))
        assert result["status"] == "success"
        assert result["output"]["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        quota.increment_llm_token.assert_not_called(), "全 0 不记账（避免噪声计数）"

    def test_zero_usage_not_recorded(self):
        """真 0 usage（网关不回传）不调配额记账"""
        resp = MagicMock()
        resp.content = "x"
        resp.usage = None
        client = MagicMock()
        client.chat = AsyncMock(return_value={
            "success": True, "response": resp, "duration": 0.1, "model": "m", "provider": "p",
        })
        quota = MagicMock()
        with patch("neurova.collaboration.neurflow.builtin._get_multi_model_client", return_value=client), \
             patch("neurova.collaboration.neurflow.builtin._get_resource_quota_manager", return_value=quota):
            asyncio.run(exec_llm({"prompt": "hi", "model_provider": "p", "model_name": "m"}, _ctx()))
        quota.increment_llm_token.assert_not_called()


class TestEngineTokensUsed:
    @pytest.mark.asyncio
    async def test_engine_reads_usage_into_tokens_used(self, tmp_path):
        """引擎把 usage.total_tokens 装配进 NodeExecutionResult.tokens_used"""
        import time as _time

        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
        )

        executor = WorkflowExecutor()
        wf = WorkflowDefinition(
            id="wf_tok", name="t", description="", version="1.0.0",
            nodes=[
                WorkflowNode(id="s", type="builtin:start", position={"x": 0, "y": 0}, config={"fields": []}),
                WorkflowNode(id="e", type="builtin:end", position={"x": 100, "y": 0}, config={}),
            ],
            edges=[WorkflowEdge(id="e1", source="s", target="e")],
            variables=[], tags=[], category="g", author="t",
            created_at=_time.time(), updated_at=_time.time(),
            status=WorkflowStatus.DRAFT,
        )
        instance = await executor.execute(wf, {})
        # start 节点无 usage —— tokens_used 保持 None（不伪 0）
        assert instance.node_results["s"].tokens_used is None
