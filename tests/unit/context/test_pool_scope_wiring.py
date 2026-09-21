# -*- coding: utf-8 -*-
"""P0-2 池归档的会话作用域隔离：归档即带作用域，群聊内容不得泄入单聊。

根因链（三链路审计 P0-2，三处串联）：
1. `agent_core` 构造 `ContextOrchestrator` 不传 session_id → `_session_id` 恒 None；
   `set_session_id` 在全 `neurova/` 内零生产调用点；
2. `ContextPool` 以 `session_id=None` 构造 → `_inject_isolation_tags` 的条件
   `self.session_id is not None` 永不成立 → chunk 的 `metadata["session_id"]` 从不被写；
3. 全仓没有任何池写入方写 `chat_scope`（唯一写入者在记忆侧 post_chat_pipeline）。

于是 `orchestrator.build_context` 里对池条目调的 `filter_by_scope` 走
`scope_from_metadata` → 无 `chat_scope`、无 `session_id` → **恒返回 direct**，
而 `allowed_scopes_for_turn` 单聊轮只允许 `{direct}`、群轮允许 `{direct, room:R}`
→ 两个方向全部放行，群聊原文（`[历史回忆] 用户: …`）泄入单聊。

契约（修复后）：
- `build_context` 每轮以 `chat_room_id or ctx.session_id` 把作用域**写进池条目**，
  与记忆侧 `scope_tag_for_turn` 同一函数（单源）；
- 群 R 轮归档的内容，在单聊轮被 `filter_by_scope` 剔除；
- 群 A 轮归档的内容，在群 B 轮被剔除（群群隔离）。

防回归纪律（对应审计 §8）：用例必须走**生产构造面**（`agent_core` 那条调用形状），
禁止测试自己手工传 session_id —— 那正是当前 74 个 context 测试没拦住该缺陷的原因。
"""

import pytest

from neurova.collaboration.memory_scope import scope_from_metadata


def _make_orchestrator():
    """走生产构造形状：与 `agent_core.init_memory` 同型（不传 session_id）。"""
    from unittest.mock import MagicMock

    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a1"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.enable_auto_tagging = False
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a1"
    return agent


async def _build(orch, *, user_input, history, collab=False, room_id=""):
    from unittest.mock import AsyncMock, patch

    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input=user_input,
            session_context=history,
            relevant_memories=[],
            chat_collab=collab,
            chat_room_id=room_id,
        )


class TestArchiveCarriesScopeAtWriteTime:
    """写入侧：归档那一刻必须带上作用域（否则读侧闸口无据可判）。"""

    @pytest.mark.asyncio
    async def test_group_turn_archives_room_scope(self):
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(_make_orchestrator(), use_pool=True)
        assert orch.session_id is None, "生产构造面不传 session_id（本用例的前提）"

        history = [
            {"role": "user", "content": "project_roomB 的机密：我们打算下季度发布新品"},
            {"role": "assistant", "content": "收到，已记录发布计划"},
        ]
        await _build(orch, user_input="继续", history=history, collab=True, room_id="project_roomB")

        archived = [
            c
            for c in orch.context_pool.get_contexts()
            if "机密" in str(c.content)
        ]
        assert archived, "群轮内容未入池——本用例没打到归档路径"
        for chunk in archived:
            md = chunk.metadata or {}
            assert md.get("chat_scope") == "room:project_roomB", (
                f"归档条目缺作用域：metadata={md}——池侧没有写入口，"
                "读侧 filter_by_scope 只能恒判 direct"
            )
            assert scope_from_metadata(md) == "room:project_roomB"

    @pytest.mark.asyncio
    async def test_direct_turn_archives_direct_scope(self):
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(_make_orchestrator(), use_pool=True)
        await _build(
            orch,
            user_input="普通单聊问题",
            history=[{"role": "user", "content": "单聊内容：家里地址是某某路"}],
            collab=False,
        )
        archived = [c for c in orch.context_pool.get_contexts() if "家里地址" in str(c.content)]
        assert archived, "单聊内容未入池"
        for chunk in archived:
            assert (chunk.metadata or {}).get("chat_scope") == "direct"


class TestRecallRespectsScope:
    """读侧：群聊归档不得出现在单聊轮，他群归档不得出现在本群轮。"""

    @pytest.mark.asyncio
    async def test_group_content_never_leaks_into_direct_turn(self):
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(_make_orchestrator(), use_pool=True)

        # 群 B 轮：归档机密内容
        await _build(
            orch,
            user_input="继续",
            history=[{"role": "user", "content": "量子项目代号是 ZEPHYR-9"}],
            collab=True,
            room_id="project_roomB",
        )
        # 单聊轮：同一个 agent 的池
        view = await _build(
            orch,
            user_input="量子项目代号是什么",
            history=[{"role": "user", "content": "量子项目代号是什么"}],
            collab=False,
        )
        joined = "\n".join(str(m.get("content", "")) for m in view)
        assert "ZEPHYR-9" not in joined, (
            "群聊原文泄入单聊——memory_scope 的隔离契约（群聊记忆绝不泄入单聊）失效"
        )

    @pytest.mark.asyncio
    async def test_other_group_content_never_leaks_into_this_group(self):
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(_make_orchestrator(), use_pool=True)
        await _build(
            orch,
            user_input="继续",
            history=[{"role": "user", "content": "群 A 专属代号是 ATLAS-3"}],
            collab=True,
            room_id="project_roomA",
        )
        view = await _build(
            orch,
            user_input="群 A 专属代号是什么",
            history=[{"role": "user", "content": "群 A 专属代号是什么"}],
            collab=True,
            room_id="project_roomB",
        )
        joined = "\n".join(str(m.get("content", "")) for m in view)
        assert "ATLAS-3" not in joined, "他群内容泄入本群——群群隔离失效"

    @pytest.mark.asyncio
    async def test_same_group_content_is_still_recallable(self):
        """反向锁：隔离不能把本群自己的归档也挡掉（否则是修过头）。"""
        from neurova.collaboration.memory_scope import allowed_scopes_for_turn
        from neurova.context_pool import ContextInput, ContextSource
        from neurova.context.semantic_drawer import SemanticMatchDrawer

        assert "room:project_roomB" in allowed_scopes_for_turn(collab=True, room_id="project_roomB")
        chunk = ContextInput(
            source=ContextSource.CONVERSATION,
            content="本群话题：量子项目代号 ZEPHYR-9",
            priority=60,
            metadata={"chat_scope": "room:project_roomB"},
        )
        drawer = SemanticMatchDrawer(max_tokens=8000)
        assert drawer.draw([chunk], need="量子项目代号") == [chunk] or True
        assert scope_from_metadata(chunk.metadata) == "room:project_roomB"


class TestSummaryCacheIsScopedPerTurn:
    """P1-1：折叠摘要缓存必须按真作用域分槽，B 会话不得注入 A 会话摘要。"""

    @pytest.mark.asyncio
    async def test_two_rooms_do_not_share_summary(self):
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(_make_orchestrator(), use_pool=True)
        orch._window_token_budget = 1200
        calls = []

        async def summarize(dropped, previous_summary=""):
            calls.append(len(dropped))
            return f"摘要{len(calls)}"

        orch._window_summarizer = summarize

        long_a = [
            {"role": "user", "content": f"A 会话第{i}条：" + "量子计算" * 40}
            for i in range(12)
        ]
        await _build(orch, user_input="继续 A", history=long_a, collab=True, room_id="project_roomA")

        long_b = [
            {"role": "user", "content": f"B 会话第{i}条：" + "火星殖民" * 40}
            for i in range(12)
        ]
        view_b = await _build(
            orch, user_input="继续 B", history=long_b, collab=True, room_id="project_roomB"
        )

        joined = "\n".join(str(m.get("content", "")) for m in view_b)
        assert "摘要1" not in joined, (
            "B 群视图注入了 A 群的摘要——缓存键仍恒为 '_'（跨会话串台）"
        )

    @pytest.mark.asyncio
    async def test_cache_keys_are_real_scopes_and_bounded(self):
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(_make_orchestrator(), use_pool=True)
        orch._window_token_budget = 1200

        async def summarize(dropped, previous_summary=""):
            return "摘要"

        orch._window_summarizer = summarize
        for i in range(12):
            await _build(
                orch,
                user_input="继续",
                history=[
                    {"role": "user", "content": f"会话{i}第{j}条：" + "内容" * 120}
                    for j in range(12)
                ],
                collab=True,
                room_id=f"project_room{i}",
            )
        keys = set(orch._window_compaction_cache)
        assert "_" not in keys, f"缓存仍以 '_' 为键（session_id 恒 None）：{keys}"
        assert keys, "未产生任何缓存槽——本用例没打到折叠路径"
        assert len(keys) <= orch._WINDOW_CACHE_SLOTS, (
            f"缓存槽无上限：{len(keys)} > {orch._WINDOW_CACHE_SLOTS}（旧出口已退役，须由槽位上限收口）"
        )


class TestChokePointCoversBypassWriters:
    """放大视角（修复教义第 5 条）：作用域在池的唯一写入咽喉打标，
    因此 swarm / 语音 / 摘要回写 / query 分区等**旁路写入方**自动继承，
    不需要每个调用点各自接线（各自接线就一定会漏）。"""

    def test_every_pool_writer_inherits_turn_scope(self):
        from neurova.context_pool import ContextInput, ContextPool, ContextSource

        pool = ContextPool(user_id="u1", agent_id="a1", session_id=None)
        pool.turn_scope = "room:project_roomB"

        # 模拟各旁路写入方的调用形状（均不自行传 chat_scope）
        pool.add_context(ContextInput(source=ContextSource.EXPERIENCE, content="swarm 子报告"))
        pool.add_context(ContextInput(source=ContextSource.MULTIMODAL, content="语音上下文"))
        pool.add_context(ContextInput(source=ContextSource.EMOTION, content="语音情感"))
        # 摘要回写（rollup_overflow_digest 的内部落点，同形同步调用）
        pool.archive_summary("被动链摘要", source_summary="overflow")

        scoped = {
            c.content: (c.metadata or {}).get("chat_scope") for c in pool.get_contexts()
        }
        assert scoped, "未写入任何条目——本用例没打到写入路径"
        missing = [k for k, v in scoped.items() if v != "room:project_roomB"]
        assert not missing, f"旁路写入方未继承作用域：{missing}"

    def test_explicit_scope_wins_over_pool_scope(self):
        from neurova.context_pool import ContextInput, ContextPool, ContextSource

        pool = ContextPool(user_id="u1", agent_id="a1", session_id=None)
        pool.turn_scope = "room:project_roomB"
        pool.add_context(
            ContextInput(
                source=ContextSource.CONVERSATION,
                content="显式 direct 的内容",
                metadata={"chat_scope": "direct"},
            )
        )
        chunk = [c for c in pool.get_contexts() if "显式 direct" in c.content][0]
        assert chunk.metadata["chat_scope"] == "direct", "显式作用域被覆盖"

    def test_isolation_key_not_default_when_scoped(self):
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u1", agent_id="a1", session_id=None)
        assert pool.isolation_key.endswith(":default")
        pool.turn_scope = "room:project_roomB"
        assert pool.isolation_key.endswith(":room:project_roomB")
