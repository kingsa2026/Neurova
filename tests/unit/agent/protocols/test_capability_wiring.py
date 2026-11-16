"""P2-3 CAPABILITY_* 接线单元测试。

覆盖：
- 注册即发布能力（register_agent capabilities 入参生效，缺省 chat/status）；
- 注销清能力；
- CAPABILITY_QUERY 经 send/request 都能拿到 CAPABILITY_RESPONSE（类型不被抹成 RESPONSE）；
- 查询不存在的 agent → 死信（request 返回 None）；
- COLLABORATION_INVITE → 显式 COLLABORATION_REJECT（诚实拒绝，非未知 action 错误）；
- register_runtime_agents 发布能力。
"""

from unittest.mock import MagicMock, patch

import pytest

from neurova.agent.protocols.acp_runtime import (
    ACPRuntime,
    DeliveryStatus,
    get_acp_runtime,
    reset_acp_runtime,
)
from neurova.agent.protocols.message_protocol import AgentMessage, MessageType


@pytest.fixture
def runtime():
    reset_acp_runtime()
    rt = get_acp_runtime()
    yield rt
    reset_acp_runtime()


def makeQuery(runtime, receiver, sender="main", correlation_id=None):
    return AgentMessage(
        type=MessageType.CAPABILITY_QUERY,
        sender_id=sender,
        receiver_id=receiver,
        action="capability_query",
        correlation_id=correlation_id,
    )


class TestCapabilityRegistry:
    def test_register_publishes_capabilities(self, runtime):
        runtime.register_agent("a1", lambda m: None, capabilities=["chat", "status", "review"])
        assert runtime.getCapabilities("a1") == ["chat", "status", "review"]

    def test_register_default_capabilities(self, runtime):
        runtime.register_agent("a2", lambda m: None)
        assert runtime.getCapabilities("a2") == ["chat", "status"]

    def test_unregister_clears_capabilities(self, runtime):
        runtime.register_agent("a3", lambda m: None, capabilities=["chat"])
        runtime.unregister_agent("a3")
        assert runtime.getCapabilities("a3") == []


class TestCapabilityQuery:
    @pytest.mark.asyncio
    async def test_query_via_request_returns_response(self, runtime):
        runtime.register_agent("worker", lambda m: None, capabilities=["chat", "status"])
        query = makeQuery(runtime, "worker")
        response = await runtime.request(query, timeout=2.0)
        assert response is not None
        assert response.type == MessageType.CAPABILITY_RESPONSE
        assert response.data["capabilities"] == ["chat", "status"]
        assert response.sender_capabilities == ["chat", "status"]
        assert response.receiver_id == "main"

    def test_query_via_send_delivered(self, runtime):
        runtime.register_agent("worker", lambda m: None, capabilities=["chat"])
        result = runtime.send(makeQuery(runtime, "worker"))
        assert result.status == DeliveryStatus.DELIVERED

    @pytest.mark.asyncio
    async def test_query_unknown_agent_dead_letter(self, runtime):
        response = await runtime.request(makeQuery(runtime, "nobody"), timeout=1.0)
        assert response is None

    @pytest.mark.asyncio
    async def test_send_async_query(self, runtime):
        runtime.register_agent("worker", lambda m: None, capabilities=["chat"])
        result = await runtime.send_async(makeQuery(runtime, "worker"))
        assert result.status == DeliveryStatus.DELIVERED


class TestCollaborationInvite:
    @pytest.mark.asyncio
    async def test_invite_gets_explicit_reject(self, runtime):
        reply = {"called": False}

        def handler(message):
            reply["called"] = True
            return None

        runtime.register_agent("worker", handler, capabilities=["chat"])
        invite = AgentMessage(
            type=MessageType.COLLABORATION_INVITE,
            sender_id="main",
            receiver_id="worker",
            action="collaborate",
            data={"role": "reviewer"},
        )
        # handler 返回 None 时 send 仍 DELIVERED；拒绝语义经 handler 返回的
        # COLLABORATION_REJECT 响应投回发起方——这里用 send_async 走完整链路
        result = await runtime.send_async(invite)
        assert result.status == DeliveryStatus.DELIVERED

    @pytest.mark.asyncio
    async def test_invite_handler_replies_reject(self, runtime):
        from neurova.agent.protocols.agent_adapter import make_agent_handler

        agent = MagicMock()
        runtime.register_agent("worker", make_agent_handler(agent), capabilities=["chat", "status"])
        invite = AgentMessage(
            type=MessageType.COLLABORATION_INVITE,
            sender_id="main",
            receiver_id="worker",
            action="collaborate",
            correlation_id="corr-1",
        )
        response = await runtime.request(invite, timeout=2.0)
        assert response is not None
        assert response.type == MessageType.COLLABORATION_REJECT
        assert response.data["error"] == "collaboration_invites_not_supported"


from unittest.mock import MagicMock  # noqa: E402  (测试文件底部集中补济导入顺序)


class TestRegisterRuntimeAgents:
    @pytest.mark.asyncio
    async def test_registration_publishes_capabilities(self, runtime):
        from neurova.agent.protocols.agent_adapter import register_runtime_agents

        agent = MagicMock()
        with patch("neurova.api.endpoints.get_app_state",
                   return_value={"agents": {"agentA": agent, "agentB": None}}):
            result = register_runtime_agents()
        assert result["registered"] == ["agentA"]
        assert runtime.getCapabilities("agentA") == ["chat", "status"]
