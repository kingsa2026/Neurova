# -*- coding: utf-8 -*-
"""D3 取长补短判据（2026-11-14 死码退役批）。

explainability.py（旧全局单例版）退役，其全仓唯一的「触发链树」能力并入
现役 modules/explainability_module.py。本档钉住并入后的能力不回退：
链式树（六类节点/父子）、memory_id↔链双向索引、JSON 导出/导入回放、
容量治理、树状可视化。
"""
from __future__ import annotations

import json

import pytest

from neurova.cognitive_layers.memory_layer.modules.explainability_module import (
    ExplainabilityModule,
    TriggerNodeType,
)

pytestmark = pytest.mark.timeout(120)


def _module(max_chains: int = 10000) -> ExplainabilityModule:
    module = ExplainabilityModule(max_chains=max_chains)
    module.init()
    return module


def testStartChainAddsNodesAndCompletesWithMemoryLink():
    module = _module()
    chain_id = module.start_chain("召回解释", description="单元测试链")
    n1 = module.add_node_to_chain(chain_id, TriggerNodeType.INPUT, "用户提问")
    n2 = module.add_node_to_chain(
        chain_id, TriggerNodeType.DECISION, "召回裁决", data={"score": 0.83}, parent_node_id=n1
    )
    assert n1 and n2
    assert module.complete_chain(chain_id, result={"memory_id": "mem_1", "hit": True}, memory_id="mem_1")

    chains = module.get_memory_chains("mem_1")
    assert len(chains) == 1 and chains[0].chain_id == chain_id
    assert chains[0].root_node_id == n1
    # 父子关系建立
    assert chains[0].nodes[n1].children == [n2]


def testExplainMemoryChainsReturnsPath():
    module = _module()
    chain_id = module.start_chain("链A")
    module.add_node_to_chain(chain_id, TriggerNodeType.TRIGGER, "关键词命中")
    module.complete_chain(chain_id, result={"memory_id": "m9"}, memory_id="m9")

    report = module.explain_memory_chains("m9")
    assert report["memory_id"] == "m9"
    assert report["chain_count"] == 1
    entry = report["chains"][0]
    assert entry["name"] == "链A"
    assert entry["node_count"] == 1
    assert entry["path"][0]["name"] == "关键词命中"


def testExplainMemoryChainsEmptyIsHonest():
    module = _module()
    report = module.explain_memory_chains("不存在")
    assert report["chain_count"] == 0 and report["chains"] == []


def testVisualizeChainRendersTree():
    module = _module()
    chain_id = module.start_chain("可视化链")
    n1 = module.add_node_to_chain(chain_id, TriggerNodeType.INPUT, "输入节点")
    module.add_node_to_chain(chain_id, TriggerNodeType.OUTPUT, "输出节点", parent_node_id=n1)
    text = module.visualize_chain(chain_id)
    assert "可视化链" in text and "输入节点" in text and "输出节点" in text


def testExportImportRoundTrip():
    module = _module()
    chain_id = module.start_chain("导出链", metadata={"turn": 7})
    module.add_node_to_chain(chain_id, TriggerNodeType.MEMORY, "记忆节点")
    module.complete_chain(chain_id, result={"memory_id": "m77"}, memory_id="m77")

    payload = module.export_chain(chain_id)
    assert payload and json.loads(payload)["chain_id"] == chain_id

    other = _module()
    imported_id = other.import_chain(payload)
    assert imported_id == chain_id
    # 导入侧也建立 memory 双向索引
    assert other.get_memory_chains("m77")


def testMaxChainsCleanupEvictsOldest():
    module = _module(max_chains=2)
    first = module.start_chain("最早")
    second = module.start_chain("次早")
    latest = module.start_chain("最新")
    module._cleanup_old_chains()
    assert module.get_chain(first) is None
    assert module.get_chain(second) is not None
    assert module.get_chain(latest) is not None
    assert len(module._chains) == 2


def testStatsIncludeChainCounters():
    module = _module()
    chain_id = module.start_chain("统计链")
    module.add_node_to_chain(chain_id, TriggerNodeType.PROCESSING, "处理")
    stats = module.get_stats()
    assert stats["active_chains"] == 1
    assert stats["total_chains"] == 1
    assert stats["total_chain_nodes"] == 1
