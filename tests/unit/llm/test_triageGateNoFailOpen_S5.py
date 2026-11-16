"""P1-10 红灯：LLM 分诊门三重 fail-open 与假探针收口。

- SecuritySandbox.__init__ 引用不存在的 ResourceQuota.rate_limit_requests_per_minute
  → 每次构造 OpenAIAdapter 必 AttributeError；
- triage._fetch_conversation_history 是 `return []  # Mock` 假历史源；
- 无历史/解析失败/调用异常三分支统一吞成 actionable=True（fail-open）；
- OpenAIAdapter._execute_openai_call 返回 "Mock response from OpenAI" 假实现。

修复判据：真历史源、真 HTTP 客户端（本地 aiohttp 服务）、不可判定以
TriageGateError 诚实暴露，不再无凭据放行。
"""

import asyncio
import json

from aiohttp import web
import pytest

from neurova.llm.adapters.openai_adapter import OpenAIAdapter
from neurova.llm.interfaces.provider_interface import ProviderConfig
from neurova.llm.sandbox.security_sandbox import SecuritySandbox
from neurova.sync.session_sync_manager import EventType, SessionEvent
from neurova.sync.session_sync_manager import (
    get_session_sync_manager,
    reset_session_sync_manager,
)
from neurova.llm.triage import (
    SmallBrainTriageGate,
    TriageGateError,
    reset_small_brain_triage_gate,
)


@pytest.fixture(autouse=True)
def _isolatedSingletons():
    reset_session_sync_manager()
    reset_small_brain_triage_gate()
    yield
    reset_session_sync_manager()
    reset_small_brain_triage_gate()


def _seedConversation(session_id: str):
    """经现役事实源（SessionSyncManager）写入真实对话事件。"""
    manager = get_session_sync_manager()
    session = manager.create_session(user_id="s5-user", agent_id="s5-agent", external_id=session_id)
    session.add_event(SessionEvent(
        event_type=EventType.USER_MESSAGE,
        session_id=session.session_id,
        payload={"content": "帮我检查这个文件"},
    ))
    session.add_event(SessionEvent(
        event_type=EventType.AGENT_REPLY,
        session_id=session.session_id,
        payload={"content": "正在看"},
    ))
    return session.session_id


def testSecuritySandboxInitDoesNotRaiseAttributeError():
    """构造沙箱不得因引用不存在的 quota 字段而炸（P1-10 根因之一）。"""
    config = ProviderConfig(api_key="k", model_name="gpt-4o-mini")
    sandbox = SecuritySandbox(config)  # 修复前：AttributeError
    assert sandbox.quota.max_requests_per_minute == 60


def testFetchConversationHistoryUsesRealSessionStore():
    """历史取自 SessionSyncManager（USER_MESSAGE + AGENT_REPLY），不再恒 []。"""
    real_session_id = _seedConversation("s5-conv-1")
    gate = SmallBrainTriageGate()
    history = asyncio.run(gate._fetch_conversation_history(real_session_id))
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "帮我检查这个文件"


def testTriageNoHistoryRaisesInsteadOfFailOpen():
    """无可分诊历史＝不可判定，诚实报错，不再无凭据放行。"""
    gate = SmallBrainTriageGate()
    with pytest.raises(TriageGateError):
        asyncio.run(gate.triage_message("s5-conv-not-exists"))


def testTriageUnparseableOutputRaisesInsteadOfSubstringGuess():
    """模型输出不可解析（如含 'truly' 的自然语句）不得被 'true' in 前缀误判为放行。"""

    class _FakeResult:
        content = "The model declined this request truly unexpectedly."

    gate = SmallBrainTriageGate()
    with pytest.raises(TriageGateError):
        gate._parse_actionable(_FakeResult.content)


def testOpenAIAdapterWithoutApiKeyRaisesInsteadOfMock():
    """api_key 为空时如实报错，不得返回 Mock 假响应。"""
    config = ProviderConfig(api_key="", model_name="gpt-4o-mini", timeout_seconds=5.0)
    adapter = OpenAIAdapter(config)
    with pytest.raises(ValueError):
        asyncio.run(adapter.call([_msg("user", "ping")]))


def _msg(role: str, content: str):
    from neurova.llm.interfaces.provider_interface import Message

    return Message(role=role, content=content)


class _OpenAIMockServer:
    """本地 OpenAI 兼容 chat/completions 假服务——真 HTTP 链路，不碰外网。"""

    def __init__(self):
        self.received = []
        self._runner = None
        self.port = 0

    async def _handler(self, request):
        self.received.append(await request.json())
        return web.json_response({
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": json.dumps(
                {"actionable": False, "reason": "agent loop"}, ensure_ascii=False
            )}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30},
        })

    async def start(self):
        app = web.Application()
        app.router.add_post("/v1/chat/completions", self._handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()


def testOpenAIAdapterRealHttpCallEndToEnd():
    """真客户端走本地 HTTP 服务取回真实 content/usage，替代 Mock 假实现。"""
    server = _OpenAIMockServer()

    async def _scenario():
        await server.start()
        try:
            config = ProviderConfig(
                api_key="sk-test",
                base_url=f"http://127.0.0.1:{server.port}/v1",
                model_name="gpt-4o-mini",
                timeout_seconds=5.0,
            )
            adapter = OpenAIAdapter(config)
            result = await adapter.call([_msg("user", "ping")])
            assert result.content == json.dumps(
                {"actionable": False, "reason": "agent loop"}, ensure_ascii=False
            )
            assert result.usage["prompt_tokens"] == 21
            assert result.usage["completion_tokens"] == 9
            assert server.received[0]["model"] == "gpt-4o-mini"
            assert server.received[0]["messages"][0]["content"] == "ping"
        finally:
            await server.stop()

    asyncio.run(_scenario())


def testTriageGateEndToEndActionableFalse():
    """全链路：真历史 + 真客户端 → 分诊结论如实落地（不再恒 actionable=True）。"""
    server = _OpenAIMockServer()

    async def _scenario():
        await server.start()
        try:
            real_session_id = _seedConversation("s5-conv-2")
            gate = SmallBrainTriageGate(provider_config=ProviderConfig(
                api_key="sk-test",
                base_url=f"http://127.0.0.1:{server.port}/v1",
                model_name="gpt-4o-mini",
                timeout_seconds=5.0,
            ))
            result = await gate.triage_message(real_session_id)
            assert result.actionable is False
            assert result.reason == "agent loop"
            # 二次调用命中缓存，服务端不再收到新请求
            seen = len(server.received)
            cached = await gate.triage_message(real_session_id)
            assert cached.actionable is False
            assert len(server.received) == seen
        finally:
            await server.stop()

    asyncio.run(_scenario())


def testSandboxAcquireResourceDoesNotBlockEventLoop():
    """并发闸打满后，第二个 acquire_resource 等待期间事件循环必须保持可调度。

    修复前 acquire_resource 在循环线程直调 threading.Semaphore.acquire(blocking=True)，
    整个事件循环被卡到超时；await 心跳被推迟 ≈timeout 秒即红灯证据。
    """
    config = ProviderConfig(api_key="k", model_name="gpt-4o-mini", timeout_seconds=1.5)

    async def _scenario():
        sandbox = SecuritySandbox(config)
        async with sandbox.acquire_resource():
            async def _second():
                async with sandbox.acquire_resource():
                    pass  # 额度已满，不应到达

            second_task = asyncio.create_task(_second())
            await asyncio.sleep(0.05)  # 让 second 进入 acquire
            loop = asyncio.get_running_loop()
            heartbeat_start = loop.time()
            await asyncio.sleep(0.05)  # 心跳：被阻塞时这条会推迟到 acquire 超时后
            heartbeat_gap = loop.time() - heartbeat_start
            assert heartbeat_gap < 0.5, (
                f"事件循环被 acquire_resource 卡住 {heartbeat_gap:.2f}s（>0.5s）"
            )
            second_task.cancel()
            try:
                await asyncio.wait_for(second_task, timeout=3.0)
            except (asyncio.CancelledError, TimeoutError):
                pass

    asyncio.run(_scenario())
