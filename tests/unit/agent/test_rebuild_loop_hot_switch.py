"""模型热切换 rebuild_loop 异步真执行 — 回归测试（红绿灯 TDD）

根因：Agent.rebuild_loop 是同步方法，内部调用 async 的
LoopManager.rebuild() 却未 await —— 返回协程对象（truthy）谎报成功，
Loop 从未重建；旧 Loop 构造时缓存的 self.llm_client = agent.llm_client
仍指向旧客户端（旧模型），导致聊天页切模型后对话仍用旧模型打新服务商
（实测：商汤网关报 400 "Model id: moonshotai/Kimi-K2.6 has no provider
supported"，而 agent 配置已是商汤模型）。

锁定契约：
1. rebuild_loop 必须真正 await LoopManager.rebuild（rebuild 实际执行）；
2. 重建后 agent.loop 必须换成 loop_manager.get_loop() 的新 Loop；
3. 无论重建还是同模型短路，Loop 上缓存的 llm_client 必须刷新为
   agent.llm_client 当前引用（防止旧 client 残留）。
"""
from __future__ import annotations

import asyncio
import types

from neurova.agent_core import Agent


class FakeLoopManager:
    def __init__(self) -> None:
        self.rebuild_awaited: list[str] = []
        self._loop = None

    async def rebuild(self, model_name: str) -> bool:
        self.rebuild_awaited.append(model_name)
        self._loop = types.SimpleNamespace(llm_client=None)
        return True

    def get_loop(self):
        return self._loop


def _make_agent() -> types.SimpleNamespace:
    """最小桩：只提供 rebuild_loop 触碰的属性，绑定真实方法。"""
    mgr = FakeLoopManager()
    agent = types.SimpleNamespace(
        loop_manager=mgr,
        loop=types.SimpleNamespace(llm_client="OLD_CLIENT"),
        llm_client="NEW_CLIENT",
        config=types.SimpleNamespace(llm_config=types.SimpleNamespace(model="old-model")),
    )
    agent.rebuild_loop = Agent.rebuild_loop.__get__(agent)
    return agent


def test_rebuild_loop_actually_executes_async_rebuild():
    """rebuild_loop 必须真正执行 LoopManager.rebuild（旧实现返回协程谎报成功）。"""
    agent = _make_agent()
    result = asyncio.run(agent.rebuild_loop("new-model"))
    assert result is True
    assert agent.loop_manager.rebuild_awaited == ["new-model"], (
        "LoopManager.rebuild 从未被执行（协程未 await）——热切换静默失效"
    )


def test_rebuild_loop_swaps_to_new_loop():
    agent = _make_agent()
    old_loop = agent.loop
    asyncio.run(agent.rebuild_loop("new-model"))
    assert agent.loop is not old_loop
    assert agent.loop is agent.loop_manager.get_loop()


def test_rebuild_loop_refreshes_cached_llm_client():
    """Loop 缓存的 llm_client 必须刷新为 agent.llm_client 当前引用。"""
    agent = _make_agent()
    asyncio.run(agent.rebuild_loop("new-model"))
    assert agent.loop.llm_client == "NEW_CLIENT"
