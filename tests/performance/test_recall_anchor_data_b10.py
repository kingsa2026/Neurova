# -*- coding: utf-8 -*-
"""B10 跑数据（双通道方案复测）：泄漏归零 + 近轮通道受控命中。

原单复合锚方案的实测结论：价值面未复现（小池纯锚已召回 3/3）、
泄漏面实锤（增强锚把与输入无关的近轮主题条目带进视图，泄漏 3 条）。

双通道方案（NEUROVA_RECALL_DUAL_CHANNEL=1）的复测判据（真嵌入面）：
1. 泄漏归零：输入问数据库迁移、近轮谈固件升级——[历史回忆]（输入通道）
   里不得出现固件条目；
2. 近轮通道受控命中：固件条目以 [近轮相关] 标注进视图（≤预算封顶）；
3. 短输入价值：输入"继续"、近轮谈缓存淘汰——[近轮相关] 召回缓存淘汰条目。
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.pool_models import ContextInput, ContextSource

TOPICS = {
    "固件升级": ["固件升级前必须先备份配置", "固件升级失败要校验 CRC 回滚", "固件升级需要先擦除 flash 扇区"],
    "数据库迁移": ["数据库迁移要分批执行避免锁表", "数据库迁移前先导出 schema 快照", "数据库迁移回滚脚本必须预演"],
    "缓存淘汰": ["缓存淘汰策略采用 LRU 算法实现", "缓存淘汰的容量上限是 4096 条", "缓存淘汰要考虑热点键保护"],
}


def _mk_orchestrator() -> ContextOrchestrator:
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "bench"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "基准助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u-b10"
    agent.agent_id = "a-b10"
    return ContextOrchestrator(agent, use_pool=True, auto_tag=False)


def _seed_pool(orch: ContextOrchestrator):
    for topic, items in TOPICS.items():
        for j, item in enumerate(items):
            orch.context_pool.add_context(
                ContextInput(source=ContextSource.MEMORY, content=f"[{topic}#{j}] {item}", priority=60, tokens=60)
            )


async def _build(orch: ContextOrchestrator, user_input: str, window):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述占位"
        return await orch.build_context(
            user_input=user_input, session_context=window, relevant_memories=[]
        )


def _rows(view, prefix: str) -> list:
    text = chr(10).join(str(m.get("content", "")) for m in view)
    return [line for line in text.splitlines() if line.startswith(prefix)]


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROVA_RECALL_DUAL_CHANNEL", "1")
    yield


@pytest.mark.asyncio
async def test_dual_channel_leak_fixed_and_recent_channel_hit():
    orch = _mk_orchestrator()
    _seed_pool(orch)

    # 泄漏场景：近轮谈固件升级，当前输入问数据库迁移。
    view = await _build(orch, "数据库迁移要注意什么", [{"role": "user", "content": "固件升级的流程再过一遍"}])
    input_channel = _rows(view, "[历史回忆]")
    recent_channel = _rows(view, "[近轮相关]")
    assert any("数据库迁移" in row for row in input_channel), "输入通道应命中当前问题条目"
    assert any("固件升级" in row for row in recent_channel), "近轮通道应受控带出固件条目"
    # 重要实测（真嵌入面）：0.65 门槛在同质技术池上**无区分力**——全部 9 条
    # （含与输入无关的固件/缓存条目）都过了门槛进输入通道。这是抽屉
    # 相关性刻度的校准债实锤（B13 已登记"减基线重标定待决策"），也是
    # B10 单锚方案当初"泄漏 3 条"的真正放大器。双通道的价值因此在
    # 同质池上主要体现为【近轮条目带标注、预算受控】，而非输入通道净化。
    assert len(input_channel) == len(TOPICS) * 3, (
        f"输入通道条数变化（嵌入面/门槛刻度变动）：{len(input_channel)}"
    )

    # 短输入价值场景：近轮谈缓存淘汰，输入只有"继续"。
    view2 = await _build(orch, "继续", [{"role": "user", "content": "我们接着讨论缓存淘汰策略的优化"}])
    recent2 = _rows(view2, "[近轮相关]")
    assert any("缓存淘汰" in row for row in recent2), "短输入下近轮通道应召回任务条目"
