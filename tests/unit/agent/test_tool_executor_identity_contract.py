"""tool_executor 身份读取契约防回归（台账 #5，2026-09-11）

根因：ToolExecutor._agent_identity 曾以 public 别名 current_user_id
优先读取——任何真值影子（MagicMock auto-attr / 带 public 别名的包装
Agent）都会遮蔽显式注入的 _current_user_id，导致 browser_* 身份注入
与 supervisor.track_user_id 落错主体。

规范契约（与 tool_executor.py social_search 读取点同源）：
先 _current_user_id（显式注入名），后 public current_user_id（轮次级
ContextVar property 别名），再 agent.user_id / config.user_id 兜底。

红→绿：test_prefers_explicit_private_id_over_truthy_public_shadow 在
旧顺序（public 优先）下红，修正顺序后绿。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.mark.usefixtures()
class TestAgentIdentityContract:
    def _make_executor(self, agent) -> object:
        from neurova.tool_executor import ToolExecutor

        return ToolExecutor(agent_ref=agent)

    def test_prefers_explicit_private_id_over_truthy_public_shadow(self):
        """_current_user_id 必须优先于真值 public 别名（旧顺序下本测试红）"""
        mock_agent = MagicMock()
        mock_agent._current_user_id = "alice"
        # 注意：mock_agent.current_user_id 未显式设置 → MagicMock 自动
        # 生成真值影子。旧实现读到该影子而非 "alice"。
        executor = self._make_executor(mock_agent)

        user_id, _ = executor._agent_identity()
        assert user_id == "alice"

    def test_public_property_alias_still_works(self):
        """真实 Agent 无 _current_user_id 实例属性（已迁 turn_context），
        走 public property 别名——回退链不得被破坏"""
        mock_agent = MagicMock(spec=["current_user_id", "config"])
        mock_agent.current_user_id = "turn-user"
        mock_agent.config = MagicMock()
        mock_agent.config.user_id = None

        executor = self._make_executor(mock_agent)
        user_id, _ = executor._agent_identity()
        assert user_id == "turn-user"

    @pytest.mark.asyncio
    async def test_identity_injection_uses_resolved_id(self):
        """端到端：browser_* 入口注入的 ContextVar 值 == 契约解析出的身份"""
        from neurova.core.identity_context import (
            clear_request_user_id,
            get_request_user_id,
        )

        mock_agent = MagicMock()
        mock_agent._current_user_id = "alice"

        executor = self._make_executor(mock_agent)

        async def fake_navigate(params):
            return {"ctx_user_id": get_request_user_id()}

        executor._execute_browser_navigate = fake_navigate
        try:
            result = await executor._execute_builtin_tool(
                "browser_navigate", {"url": "https://example.com"}
            )
        finally:
            clear_request_user_id()
        assert result["ctx_user_id"] == "alice"
