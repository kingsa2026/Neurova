"""进化记忆会话快照冻结测试（OpenOcta 启发 P2 #11：SnapshotForSession）

问题：记忆温度/结晶引擎/进化写入即时生效 → 长会话中途 soul.md 更新、
性格调整、结晶经验落库会改变当前 system prompt，破坏可复现性
（同会话内两次相同提问可能因 prompt 漂移得到不同回答）。

OpenOcta 方案：会话开始时冻结注入 prompt 的记忆/人设快照，写入只在
**下次会话**生效。Neurova 等价实现：
- Agent 快照缓存：ChatPipeline 每轮请求开始时取一次
  {soul, personality, constitution}——同一 session_id 的首轮缓存，
  之后同会话轮次复用（快照冻结）；session 变化时重建
- build_context 的 system_instructions 优先消费快照
- 快照生命周期：会话切换自动换快照；进程生命周期内 LRU 上限防膨胀

注意：结晶经验注入本就在"本轮检索产物"段（每轮变化属正常语义——
OpenOcta 冻结的是 prompt 身份层，不是上下文检索层），无需冻结。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def agent():
    a = MagicMock()
    a.soul = "原始灵魂"
    a.personality = "原始性格"
    a.config.constitution = "原始宪法"
    return a


class TestSessionSnapshot:
    def test_snapshot_taken_once_per_session(self, agent):
        """同会话多次取快照 = 首次冻结值；身份文件中途变化不影响本会话。"""
        from neurova.agent.session_snapshot import SessionSnapshotCache

        cache = SessionSnapshotCache(max_sessions=10)
        s1 = cache.get(agent, session_id="sess-1")
        assert s1["soul"] == "原始灵魂"

        # 身份"进化"：soul 被改写
        agent.soul = "进化后的灵魂"
        s2 = cache.get(agent, session_id="sess-1")
        assert s2 is s1, "同会话第二次取应命中缓存（快照冻结）"
        assert s2["soul"] == "原始灵魂", "会话中途的写入不得影响当前 prompt"

    def test_new_session_gets_new_snapshot(self, agent):
        """写入下次会话生效：session 切换 → 重建快照，包含最新进化。"""
        from neurova.agent.session_snapshot import SessionSnapshotCache

        cache = SessionSnapshotCache(max_sessions=10)
        cache.get(agent, session_id="sess-1")
        agent.soul = "进化后的灵魂"

        s2 = cache.get(agent, session_id="sess-2")
        assert s2["soul"] == "进化后的灵魂"

    def test_none_session_bypasses_cache(self, agent):
        """无 session_id（无状态调用）不缓存、每次现取——诚实降级。"""
        from neurova.agent.session_snapshot import SessionSnapshotCache

        cache = SessionSnapshotCache(max_sessions=10)
        s1 = cache.get(agent, session_id=None)
        agent.soul = "变了"
        s2 = cache.get(agent, session_id=None)
        assert s1 is not s2 and s2["soul"] == "变了"
        assert cache.size == 0, "None 会话不得占用缓存位"

    def test_lru_eviction(self, agent):
        """超上限 LRU 淘汰最旧会话快照（防长跑进程膨胀）。"""
        from neurova.agent.session_snapshot import SessionSnapshotCache

        cache = SessionSnapshotCache(max_sessions=3)
        for i in range(5):
            cache.get(agent, session_id=f"s{i}")
        assert cache.size <= 3

    def test_snapshot_shape(self, agent):
        """快照含 prompt 身份层三件套（soul/personality/constitution）。"""
        from neurova.agent.session_snapshot import SessionSnapshotCache

        cache = SessionSnapshotCache(max_sessions=10)
        snap = cache.get(agent, session_id="s")
        assert set(snap.keys()) == {"soul", "personality", "constitution"}


class TestBuildContextConsumesSnapshot:
    """build_context 消费快照：system_instructions 来自冻结值而非活值。

    装配链：ChatPipeline._step_activity_tracking 每轮经
    get_session_snapshot_cache().get(agent, session_id) 冻结并写入
    agent._frozen_identity_snapshot → orchestrator.build_context 优先消费。
    本组测试按真实契约直接在 agent 上挂快照属性；use_pool=True 走池路径
    （非池路径末尾经 context_builder.compress_if_needed，mock 下返回值失真）。
    """

    def _make_orchestrator(self, agent):
        from neurova.context.orchestrator import ContextOrchestrator

        return ContextOrchestrator(agent, use_pool=True)

    def _build(self, co, user_input):
        import asyncio

        ctx = co.build_context(user_input=user_input)
        if asyncio.iscoroutine(ctx):
            ctx = asyncio.run(ctx)
        return ctx

    def test_build_context_uses_frozen_soul(self, agent):
        from neurova.agent.session_snapshot import SessionSnapshotCache

        co = self._make_orchestrator(agent)
        agent._frozen_identity_snapshot = SessionSnapshotCache(max_sessions=10).get(
            agent, session_id="sess-9"
        )
        ctx = self._build(co, "hi")

        first_soul = next(m["content"] for m in ctx if m.get("role") == "system")
        assert first_soul == "原始灵魂"

        # 身份进化后同会话再构建 → 仍是冻结值
        agent.soul = "进化后的灵魂"
        ctx2 = self._build(co, "hi again")
        soul2 = next(m["content"] for m in ctx2 if m.get("role") == "system")
        assert soul2 == "原始灵魂", "同会话 system prompt 不得漂移"

    def test_no_snapshot_cache_falls_back_to_live(self, agent):
        """未装配快照（旧实例/属性缺失）→ 活值兜底，零行为变化。"""
        co = self._make_orchestrator(agent)
        ctx = self._build(co, "hi")
        soul = next(m["content"] for m in ctx if m.get("role") == "system")
        assert soul == "原始灵魂"

    def test_degraded_snapshot_partial_fields_fallback(self, agent):
        """快照缺 soul（脏数据）→ 整体退回活值路径（不输出空 prompt）。"""
        agent._frozen_identity_snapshot = {"personality": "残缺"}
        co = self._make_orchestrator(agent)
        ctx = self._build(co, "hi")
        soul = next(m["content"] for m in ctx if m.get("role") == "system")
        assert soul == "原始灵魂"


class TestSessionSwitch:
    def test_same_cache_shared_across_instances(self, agent):
        """快照缓存挂在 agent 上（多 pipeline 实例共享同会话冻结值）。"""
        from neurova.agent.session_snapshot import SessionSnapshotCache

        cache = SessionSnapshotCache(max_sessions=10)
        s1 = cache.get(agent, session_id="shared")
        agent.soul = "改了"
        s2 = cache.get(agent, session_id="shared")
        assert s2 is s1
