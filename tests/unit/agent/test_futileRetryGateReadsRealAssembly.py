# -*- coding: utf-8 -*-
"""恢复轮的「旋钮到不到得了网关」必须在**真装配点**上答——环级判据。

§6-397 批 H 的 E 笔掐掉了空转重试，但判据读的是路由门面的 `config.compat`
（那份从没被赋过值，恒为 dataclass 默认）；amd 恰好同结果，所以既有的
`test_futileThinkingRetryIsSkipped.py` 用手工塞好 compat 的替身全测不出来（形态 403）。

本文件把判据打在**生产同一个类**上：`AgentLLMClient`（`agent_core.py:121`）+
真 `MultiModelLLMClient`（真 `LLMProviderManager`，独立 providers.json 路径）。
只有网络出口 `chat_stream` 被打桩——判定链路（门面 → 路由 → provider 行 → compat）
全程走真代码。

三条判据的方向各不相同：
- 候选行声明了 `enable_thinking` ⇒ 恢复轮照旧重试（今天被误掐，红）；
- 候选行只声明 `reasoning_effort`（amd 现值）⇒ 照旧不重试、以交代收尾（不扩大战果）；
- 本轮打到谁路由答不出 ⇒ fail-open，照旧重试（不借判据躲重试）。
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.agent_core import AgentLLMClient
from neurova.llm.multi_model_client import MultiModelLLMClient
from neurova.llm.provider_manager import LLMProviderManager

GARBAGE_UNIT = "lock"
GARBAGE_CHUNK = 50
GARBAGE_CHUNKS = 40
TAIL_SENTINEL = "⟦tail-reached⟧"

SILENT_BASE = "https://developer.amd.com.cn/radeon/v1"
SILENT_MODEL = "GLM-Silent-Flash"
TOGGLE_BASE = "https://toggle.example/v1"
TOGGLE_MODEL = "Qwen-Toggle-Flash"
ORPHAN_MODEL = "NoSuchModel-9"


def garbageChunks() -> list:
    return [
        SimpleNamespace(content=None, reasoning_content=GARBAGE_UNIT * GARBAGE_CHUNK,
                        usage=None, tool_calls=None, finish_reason=None)
        for _ in range(GARBAGE_CHUNKS)
    ] + [SimpleNamespace(content=None, reasoning_content=TAIL_SENTINEL,
                         usage=None, tool_calls=None, finish_reason="length")]


def cleanContentRound() -> list:
    return [
        SimpleNamespace(content="好。", reasoning_content=None, usage=None,
                        tool_calls=None, finish_reason=None),
        SimpleNamespace(content=None, reasoning_content=None, usage=None,
                        tool_calls=None, finish_reason="stop"),
    ]


def _runTurn(routing, *, model, provider_id=""):
    """走真门面的流式一轮：`rounds[0]` 是本轮，`rounds[1]` 是恢复轮（若发起）。"""
    rounds = [garbageChunks(), cleanContentRound()]
    calls: list = []

    async def fakeChatStream(messages, **kwargs):
        calls.append(dict(kwargs))
        idx = min(len(calls) - 1, len(rounds) - 1)
        for chunk in rounds[idx]:
            yield chunk

    routing.chat_stream = fakeChatStream

    facade = AgentLLMClient(model=model, provider_id=provider_id)
    agent = MagicMock()
    agent._tool_messages_list = []
    agent._round_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    agent.skill_registry = None
    agent.llm_client = facade
    loop = OpenAILoop(agent)
    loop.llm_client = facade

    request = {
        "messages": [{"role": "user", "content": "继续任务"}],
        "stream": True,
        "max_tokens": 4096,
        "thinking_enabled": True,
        "thinking_effort": "deep",
    }

    async def go():
        return [e async for e in loop._predict_stream(request)]

    return calls, asyncio.run(go())


@pytest.fixture
def routing(tmp_path, monkeypatch):
    """真 manager（独立 providers.json）+ 真路由实例；只桩网络出口。"""
    manager = LLMProviderManager(
        config={"config_path": str(tmp_path / "providers.json")}
    )
    silent = manager.add_provider(
        name="Silent Gw", provider="openai", base_url=SILENT_BASE,
        api_key="sk-test", models=[SILENT_MODEL],
    )
    manager.add_provider(
        name="Toggle Gw", provider="openai", base_url=TOGGLE_BASE,
        api_key="sk-test", models=[TOGGLE_MODEL],
        compat_dict={"supports_thinking_toggle": True},
    )
    scope = f"probe-assembly-{uuid.uuid4().hex[:8]}"
    inst = MultiModelLLMClient(scope=scope, provider_manager=manager)
    monkeypatch.setattr(
        "neurova.llm.multi_model_client.get_multi_model_client",
        lambda s=None: inst,
    )
    try:
        yield inst, silent.id
    finally:
        MultiModelLLMClient._instances.pop(scope, None)


class TestRealAssemblyDrivesTheRetry:
    def testToggleCapableRowGetsItsRetryBack(self, routing):
        """候选行声明了 enable_thinking ⇒ 这一轮真能自救，不许掐。"""
        inst, _ = routing

        calls, events = _runTurn(inst, model=TOGGLE_MODEL)

        assert len(calls) == 2, (
            f"网关收得到关思考却被判『到不了』＝白丢一次自救：{[e.get('type') for e in events]}"
        )

    def testSilentRowStillSkipsTheFutileRetry(self, routing):
        """不扩大战果：只声明 reasoning_effort 的网关照旧掐掉那第二次调用。"""
        inst, _ = routing

        calls, events = _runTurn(inst, model=SILENT_MODEL)

        assert len(calls) == 1, calls
        contents = [e["data"] for e in events if e.get("type") == "content" and e.get("data")]
        assert contents, "不重试也得有交代，不许空气泡"
        assert GARBAGE_UNIT * 3 not in "".join(contents)

    def testUnresolvableRoutingFailsOpenToRetry(self, routing):
        """池里无人认这个模型 ⇒ 本轮打到谁答不出，按『能到』处理，照旧重试。"""
        inst, _ = routing

        calls, _events = _runTurn(inst, model=ORPHAN_MODEL)

        assert len(calls) == 2, calls

    def testPinnedSilentProviderIsNotRescuedByAnotherRow(self, routing):
        """钉死静默提供方时，重试打的还是那一家——池里别的房不算进来。"""
        inst, silent_id = routing

        calls, _events = _runTurn(inst, model=TOGGLE_MODEL, provider_id=silent_id)

        assert len(calls) == 1, calls
