# -*- coding: utf-8 -*-
"""A3 红灯：NeuacpMemberAdapter——swarm 成员鸭子面契约测试。

覆盖：chat 返回 {"text"} 且经 metadata["event_emitter"] 流式输出、
config.name、current_session_id、llm_client 注入、permission fail-closed、
stream=False 兼容。
"""
import asyncio
import sys
from pathlib import Path

from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.acp_member import NeuacpMemberAdapter
from neurova.agent.neuacp.executor import NeuacpSessionContext

FAKE_AGENT = Path(__file__).with_name("fake_acp_agent.py")


def makeAdapter(mode, *, name="OpenCode 编码代理", permission_asker=None, verify_channel=None):
    executor = NeuacpStdioExecutor(
        [sys.executable, str(FAKE_AGENT)],
        cwd=str(FAKE_AGENT.parent),
        env_extra={"FAKE_ACP_MODE": mode},
    )
    adapter = NeuacpMemberAdapter(
        executor,
        name=name,
        cwd=str(FAKE_AGENT.parent),
        permission_asker=permission_asker,
        verify_channel=verify_channel,
    )
    return adapter


def test_chatReturnsTextAndStreamsViaMetadataEmitter():
    async def run():
        adapter = makeAdapter("acp_flow")
        chunks = []
        metadata = {"event_emitter": lambda kind, text: chunks.append((kind, text))}
        response = await adapter.chat("写个登录页", stream=True, session_id="m-9", metadata=metadata)
        await adapter.close()
        return chunks, response

    chunks, response = asyncio.run(run())
    assert chunks == [("content", "你好 Neuacp"), ("reasoning", "思考中")]
    assert response == {"text": "你好 Neuacp"}


def test_configNameAndCurrentSessionIdExposed():
    async def run():
        adapter = makeAdapter("acp_flow", name="Qoder 编码代理")
        assert adapter.config.name == "Qoder 编码代理"
        await adapter.chat("任务", stream=True, session_id="m-42", metadata={"event_emitter": lambda k, t: None})
        await adapter.close()
        return adapter

    adapter = asyncio.run(run())
    assert adapter.current_session_id == "m-42"


def test_missingEmitterStillReturnsText():
    async def run():
        adapter = makeAdapter("acp_flow")
        response = await adapter.chat("任务", stream=True, session_id="m-1", metadata={})
        await adapter.close()
        return response

    assert asyncio.run(run()) == {"text": "你好 Neuacp"}


def test_verifyChannelInjected():
    class FakeVerifyChannel:
        async def chat(self, messages, **kwargs):
            return None

    channel = FakeVerifyChannel()
    adapter = makeAdapter("acp_flow", verify_channel=channel)
    assert adapter.llm_client is channel


def test_permissionFailClosedWithoutAsker():
    async def run():
        adapter = makeAdapter("acp_permission", permission_asker=None)
        chunks = []
        metadata = {"event_emitter": lambda kind, text: chunks.append((kind, text))}
        response = await adapter.chat("改配置", stream=True, session_id="m-2", metadata=metadata)
        await adapter.close()
        return chunks, response

    chunks, response = asyncio.run(run())
    assert ("content", "权限被拒，任务中止") in chunks
    # deny 前的 content chunk 也会累积进最终文本（agent 先干活再请求权限）
    assert response == {"text": "你好 Neuacp权限被拒，任务中止"}


def test_permissionAskerReceivesAction():
    async def run():
        asks = []

        def asker(action, reason, context):
            asks.append(action)
            return {"approved": True}

        adapter = makeAdapter("acp_permission", permission_asker=asker)
        await adapter.chat("改配置", stream=True, session_id="m-3", metadata={"event_emitter": lambda k, t: None})
        await adapter.close()
        return asks

    asks = asyncio.run(run())
    assert asks and "写入 src/app.py" in asks[0]


def test_streamFalseStillReturnsText():
    async def run():
        adapter = makeAdapter("acp_flow")
        response = await adapter.chat("任务", stream=False, session_id="m-4", metadata={})
        await adapter.close()
        return response

    assert asyncio.run(run()) == {"text": "你好 Neuacp"}
