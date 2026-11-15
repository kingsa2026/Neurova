# -*- coding: utf-8 -*-
"""B10 泄漏解法：双通道召回（输入通道保纯 + 近轮通道受控带标签）。

泄漏机理（实测）：把近轮要点混进同一个召回锚 → 近轮话题的旧归档条目
借复合锚过 0.65 门槛混进当前问题的召回面。

双通道契约：
1. 输入通道：锚 = 纯 user_input，门槛 0.65（不变）——近轮话题条目在此
   通道永远过不了门槛（泄漏物理切断）；
2. 近轮通道（NEUROVA_RECALL_DUAL_CHANNEL=1 开启，默认关）：锚 = 近轮
   要点，门槛 0.75（更严），预算 = 召回额度 ×30% 封顶，条目以
   `[近轮相关]` 前缀进 <history> 块（模型知道其出处）；
3. 两通道按 hash 合并去重；近轮通道条目同样过作用域闸与注入面去重；
4. 默认关时行为与改前逐字一致（单通道、纯输入锚）。
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.pool_models import ContextInput, ContextSource


class TopicVectorStore:
    """按主题词路由向量的确定性替身（非 MagicMock）。

    含「固件升级」→ e0；含「数据库迁移」→ e1；含「缓存淘汰」→ e2；
    其余（如"继续"）→ e3。正交向量下跨主题相似度 = 0.5（过不了 0.65）。
    """

    def __init__(self, dim: int = 4):
        self._dim = dim

    def _vec(self, text: str):
        v = [0.0] * self._dim
        if "固件升级" in text:
            v[0] = 1.0
        elif "数据库迁移" in text:
            v[1] = 1.0
        elif "缓存淘汰" in text:
            v[2] = 1.0
        else:
            v[3] = 1.0
        return v

    def encode(self, text: str):
        return self._vec(text)

    def encode_batch(self, texts):
        return [self._vec(t) for t in texts]


def _mk_agent(agent_id="a-dual"):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u-dual"
    agent.agent_id = agent_id
    return agent


def _mk_orchestrator() -> ContextOrchestrator:
    return ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)


def _seed_topics(orch: ContextOrchestrator):
    """三主题 × 2 条归档（主题词入内容，供主题向量路由命中）。"""
    for topic, items in {
        "固件升级": ["固件升级前必须先备份配置", "固件升级失败要校验 CRC 回滚"],
        "数据库迁移": ["数据库迁移要分批执行避免锁表", "数据库迁移前先导出 schema 快照"],
        "缓存淘汰": ["缓存淘汰策略采用 LRU 算法实现", "缓存淘汰的容量上限是 4096 条"],
    }.items():
        for j, item in enumerate(items):
            orch.context_pool.add_context(
                ContextInput(source=ContextSource.MEMORY, content=f"[{topic}#{j}] {item}", priority=60, tokens=50)
            )


async def _build(orch: ContextOrchestrator, user_input: str, window=None):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述占位"
        return await orch.build_context(
            user_input=user_input,
            session_context=window if window is not None else [_long_msg(0)],
            relevant_memories=[],
        )


def _long_msg(i: int) -> dict:
    return {"role": "user", "content": f"第{i}轮的执行细节：" + "细节" * 200}


def _viewText(msgs) -> str:
    return "\n".join(str(m.get("content", "")) for m in msgs)


class TestDualChannelRecall:
    @pytest.mark.asyncio
    async def test_kill_switch_single_channel(self, monkeypatch):
        """kill-switch（=0）：单通道，行为与改前一致（无 [近轮相关] 行）。"""
        monkeypatch.setenv("NEUROVA_RECALL_DUAL_CHANNEL", "0")
        orch = _mk_orchestrator()
        _seed_topics(orch)
        orch.context_pool._drawer._vector_store = TopicVectorStore()
        view = await _build(orch, "数据库迁移要注意什么")
        assert "[近轮相关]" not in _viewText(view)

    @pytest.mark.asyncio
    async def test_input_channel_stays_pure(self, monkeypatch):
        """泄漏修复判据：输入问数据库迁移、近轮谈固件升级——
        [历史回忆]（输入通道）里不得出现固件条目。"""
        monkeypatch.setenv("NEUROVA_RECALL_DUAL_CHANNEL", "1")
        orch = _mk_orchestrator()
        _seed_topics(orch)
        orch.context_pool._drawer._vector_store = TopicVectorStore()
        window = [{"role": "user", "content": "固件升级的流程再过一遍"}]
        view = await _build(orch, "数据库迁移要注意什么", window=window)
        text = _viewText(view)
        history_rows = [line for line in text.splitlines() if line.startswith("[历史回忆]")]
        assert history_rows, "输入通道应召回数据库迁移条目"
        assert all("固件升级" not in row for row in history_rows), (
            f"输入通道泄漏近轮话题条目：{history_rows}"
        )
        assert "数据库迁移" in text

    @pytest.mark.asyncio
    async def test_recent_channel_labeled_and_hit(self, monkeypatch):
        """近轮通道：短输入"继续"下，近轮任务（缓存淘汰）条目带标注进视图。"""
        monkeypatch.setenv("NEUROVA_RECALL_DUAL_CHANNEL", "1")
        orch = _mk_orchestrator()
        _seed_topics(orch)
        orch.context_pool._drawer._vector_store = TopicVectorStore()
        window = [{"role": "user", "content": "我们接着讨论缓存淘汰策略的优化"}]
        view = await _build(orch, "继续", window=window)
        text = _viewText(view)
        recent_rows = [line for line in text.splitlines() if line.startswith("[近轮相关]")]
        assert recent_rows, "近轮通道应带标注召回任务条目"
        assert all("缓存淘汰" in row for row in recent_rows)

    @pytest.mark.asyncio
    async def test_channels_deduped_by_hash(self, monkeypatch):
        """两通道都命中的条目只进一次（hash 去重）。"""
        monkeypatch.setenv("NEUROVA_RECALL_DUAL_CHANNEL", "1")
        orch = _mk_orchestrator()
        _seed_topics(orch)
        orch.context_pool._drawer._vector_store = TopicVectorStore()
        window = [{"role": "user", "content": "数据库迁移的方案再确认一下"}]
        view = await _build(orch, "数据库迁移要注意什么", window=window)
        migration_rows = [
            line
            for line in _viewText(view).splitlines()
            if "数据库迁移" in line and ("[历史回忆]" in line or "[近轮相关]" in line)
        ]
        assert len(migration_rows) == len(set(migration_rows)), f"跨通道重复：{migration_rows}"


class TestRecentTurnsAnchor:
    def test_anchor_from_recent_turns(self):
        orch = _mk_orchestrator()
        window = [
            {"role": "user", "content": "先看看缓存淘汰策略的代码"},
            {"role": "assistant", "content": "已定位到 LRU 实现"},
        ]
        anchor = orch._buildRecentTurnsAnchor(window)
        assert anchor.startswith("近轮要点：")
        assert "缓存淘汰策略" in anchor and "LRU" in anchor

    def test_anchor_empty_window(self):
        orch = _mk_orchestrator()
        assert orch._buildRecentTurnsAnchor([]) == ""
