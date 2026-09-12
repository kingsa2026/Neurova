"""B-5 回归测试：身份读取序对齐（_current_user_id 优先，public 别名兜底）。

契约（对齐 tool_executor._agent_identity，见 tool_executor.py 读取序注释）：
- `agent/loops/base.py` _execute_tool_call_worker 的 SkillRegistry 隔离注入；
- `post_chat_pipeline.py` _collect_round_artifacts 的产物归属 user_id。

两处都必须先读 ``_current_user_id``（请求级显式身份；无 public property
别名的 Agent / 测试替身只设此名），再回退 public ``current_user_id``。
反序时真值影子（如 MagicMock auto-attr current_user_id）会遮蔽显式身份。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import neurova.api.endpoints.artifacts_api as artifacts_api
from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.post_chat_pipeline import PostChatPipeline


def _make_loop_with_skill_only(identity_kwargs):
    """替身 Agent：只带 skill_registry，捕获隔离注入的 (args, ctx)。"""
    captured = {}

    async def _execute_skill(name, args, ctx):
        captured["args"] = args
        captured["ctx"] = ctx
        return SimpleNamespace(success=True, data={"ok": True}, error=None)

    registry = SimpleNamespace(execute_skill=AsyncMock(side_effect=_execute_skill))
    agent = SimpleNamespace(
        llm_client=SimpleNamespace(),
        config=SimpleNamespace(name="t", user_id="cfg-u", agent_id="a1"),
        skill_registry=registry,
        **identity_kwargs,
    )
    return OpenAILoop(agent), captured


class TestB5SkillInjectionReadOrder:
    def test_request_identity_from_current_user_id_only(self):
        """替身只设 _current_user_id（无 public 别名）→ 隔离注入取到该身份。"""
        loop, captured = _make_loop_with_skill_only({"_current_user_id": "req-u-1"})
        tc = {
            "id": "c1",
            "function": {"name": "kb_builder", "arguments": "{}"},
        }
        asyncio.run(loop._execute_tool_call_worker(tc))
        assert captured["ctx"] == {"user_id": "req-u-1"}
        assert captured["args"]["_caller_user_id"] == "req-u-1"

    def test_public_alias_fallback(self):
        """只有 public 别名（无 _current_user_id）→ 兜底读 public 别名。"""
        loop, captured = _make_loop_with_skill_only({"current_user_id": "alias-u-2"})
        tc = {"id": "c2", "function": {"name": "kb_builder", "arguments": "{}"}}
        asyncio.run(loop._execute_tool_call_worker(tc))
        assert captured["ctx"] == {"user_id": "alias-u-2"}


class TestB5CollectArtifactsReadOrder:
    def _pipeline_and_capture(self, identity_kwargs):
        seen = {}

        def _fake_extract(tool_name, result_text, agent_id="", user_id=""):
            seen["agent_id"] = agent_id
            seen["user_id"] = user_id
            return []

        agent = SimpleNamespace(
            config=SimpleNamespace(agent_id="agt-1"),
            **identity_kwargs,
        )
        pipeline = PostChatPipeline(agent)
        # 完全隔离：替身 extract_tool_artifacts，不触真实实现
        orig = artifacts_api.extract_tool_artifacts
        artifacts_api.extract_tool_artifacts = _fake_extract
        try:
            events = pipeline._collect_round_artifacts(
                [{"type": "tool_result", "tool_name": "t", "result": "r"}]
            )
        finally:
            artifacts_api.extract_tool_artifacts = orig
        assert events == []
        return seen

    def test_request_identity_from_current_user_id_only(self):
        seen = self._pipeline_and_capture({"_current_user_id": "req-u-3"})
        assert seen["user_id"] == "req-u-3"

    def test_public_alias_fallback(self):
        seen = self._pipeline_and_capture({"current_user_id": "alias-u-4"})
        assert seen["user_id"] == "alias-u-4"
