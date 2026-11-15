# -*- coding: utf-8 -*-
"""B10 跑数据：召回需求锚（纯输入 vs 输入+近轮要点）的召回质量对照。

用真嵌入面（onnx bge-small-zh，与生产同款）在受控池上量三个数：
- 命中：短输入（"继续"）下，增强锚能否召回与**近轮任务**相关、
  纯输入锚够不着 0.65 门槛的条目（这是 B10 的价值主张）；
- 泄漏：增强锚把「与当前输入无关、只与近轮相关」的条目带进视图的
  数量（这是 B10 的风险面，0.633→0.685 泄漏事故的复测）；
- 中性：长输入（本身语义明确）下两锚结果应一致。

判据（宽松地板，数据供决策）：
- 短输入场景：增强锚命中数 > 纯锚命中数（价值成立）；
- 泄漏场景：增强锚的泄漏条数如实记录（≤2 条，超出则默认转正无望）。
"""
import asyncio
import os
import sys
from typing import Dict, List
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.semantic_drawer import SemanticMatchDrawer

TOPICS = {
    "固件升级": ["固件升级前必须先备份配置", "固件升级需要先擦除 flash 扇区", "固件升级失败回滚要校验 CRC"],
    "缓存淘汰": ["缓存淘汰策略采用 LRU 算法实现", "缓存淘汰的容量上限是 4096 条", "缓存淘汰要考虑热点键保护"],
    "数据库迁移": ["数据库迁移要分批次执行避免锁表", "数据库迁移前先导出 schema 快照", "数据库迁移回滚脚本必须预演"],
}


def _seed_pool(pool) -> Dict[str, List[str]]:
    seeded = {}
    for topic, items in TOPICS.items():
        seeded[topic] = []
        for j, item in enumerate(items):
            drop = ContextInput(
                source=ContextSource.MEMORY,
                content=f"[{topic}#{j}] {item}",
                priority=60,
                tokens=60,
            )
            pool.add_context(drop)
            seeded[topic].append(drop.hash)
    # 干扰项（与三主题都无关）
    for j, noise in enumerate(["今天中午吃了面条", "楼下新开了一家咖啡店", "昨天的球赛很精彩"]):
        pool.add_context(ContextInput(source=ContextSource.CONVERSATION, content=noise, priority=50, tokens=20))
    return seeded


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


def _drawn_contents(orch: ContextOrchestrator, need: str) -> List[str]:
    drops = orch.context_pool.draw(need=need, budget_tokens=10 ** 6)
    return [str(d.content) for d in drops]


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


@pytest.mark.asyncio
async def test_anchor_recall_and_leak():
    orch = _mk_orchestrator()
    _seed_pool(orch.context_pool)

    # 场景一（价值面）：近轮在谈「缓存淘汰」，当前输入只有两个字"继续"。
    # 纯输入锚：向量几乎无区分力 → 相关条目过不了 0.65 门槛；
    # 增强锚：锚里带上近轮要点 → 缓存淘汰条目应被召回。
    recent_cache = [{"role": "user", "content": "我们接着讨论缓存淘汰策略的优化"}]
    plain_short = orch._buildRecallNeedAnchor("继续", [])
    enriched_short = orch._buildRecallNeedAnchor("继续", recent_cache)

    plain_hits = [c for c in _drawn_contents(orch, plain_short) if "缓存淘汰" in c]
    enrich_hits = [c for c in _drawn_contents(orch, enriched_short) if "缓存淘汰" in c]
    print("\n[B10] 短输入纯锚命中缓存淘汰:", len(plain_hits), "增强锚:", len(enrich_hits))

    # 场景二（泄漏面）：近轮在谈「固件升级」，当前输入问「数据库迁移」。
    # 增强锚可能把固件条目带进来——泄漏必须如实计数（≤2 条，超过则默认转正无望）。
    recent_fw = [{"role": "user", "content": "固件升级的流程再过一遍"}]
    enriched_leak = orch._buildRecallNeedAnchor("数据库迁移要注意什么", recent_fw)
    leak_drawn = _drawn_contents(orch, enriched_leak)
    leaks = [c for c in leak_drawn if "固件升级" in c]
    relevant = [c for c in leak_drawn if "数据库迁移" in c]
    print("[B10] 泄漏场景: 命中数据库迁移", len(relevant), "条；固件泄漏", len(leaks), "条")

    # 场景三（中性面）：长输入本身语义明确，两锚都应命中同主题。
    long_input = "数据库迁移分批执行的具体做法是什么"
    plain_long = _drawn_contents(orch, orch._buildRecallNeedAnchor(long_input, []))
    enrich_long = _drawn_contents(orch, orch._buildRecallNeedAnchor(long_input, recent_fw))
    plain_hits_long = sum(1 for c in plain_long if "数据库迁移" in c)
    enrich_hits_long = sum(1 for c in enrich_long if "数据库迁移" in c)
    print("[B10] 长输入: 纯锚命中", plain_hits_long, "增强锚命中", enrich_hits_long)

    # 数据研判（2026-11-15 实测，真嵌入面）：
    # - 价值面未复现：本池上纯输入锚"继续"已能召回全部缓存淘汰条目（3=3）——
    #   小池同质内容下 bge 的无关基线本就偏高，短输入区分力问题被掩盖；
    # - 泄漏面实锤：增强锚把与当前输入无关的固件条目带进视图（泄漏 3 条
    #   > 预算 ≤2）——与 0.633→0.685 的门槛泄漏事故同向。
    # 结论：B10 维持默认关；本用例作为数据记录与回归探针（长输入中性面
    # 不丢命中＝抽屉功能性地板）。
    assert plain_hits_long >= 1, "长输入下抽屉应命中同主题条目（功能性地板）"
    assert enrich_hits_long >= plain_hits_long, "长输入下增强锚不得丢命中"
    assert len(leaks) >= 1, "泄漏场景应如实呈现（B10 维持默认关的依据）"
