# -*- coding: utf-8 -*-
"""检索器协议一致性（Issue #189）：声明接入的适配器必须真的满足 `Retriever`。

实测病灶：`AnnotationRetrieverAdapter` 缺 `get_quality_score`，而
`MemoryRetrievalChain.add_retriever` 的守卫是 `isinstance(retriever, Retriever)`。
于是每个 Agent 构建（本次 4 次）都走 `chat_pipeline` 的
`except Exception` → 一条 "接入失败（降级跳过）" warning，人工标注这条最高权威
检索源**从未真正挂上链**——静默降级，正是修复教义第 2 条要暴露的形态。

为什么既有用例没红：`tests/unit/agent/test_annotation_retriever.py:91` 用的是
`MagicMock()` 当链（教义第 3 条禁止的写法），假对象对任何 retriever 都点头。
本文件一律用**真链** `MemoryRetrievalChain`。
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 全仓声明"我要进检索链"的适配器（生产装配点 `chat_pipeline._init_memory_retrieval_chain`）
_ADAPTERS = {
    "AnnotationRetrieverAdapter": "neurova.agent.annotation_retriever",
    "UnifiedRetrieverAdapter": "neurova.agent.retriever_adapters",
    "MoERetrieverAdapter": "neurova.agent.retriever_adapters",
    "CacheRetrieverAdapter": "neurova.agent.retriever_adapters",
    "FallbackRetrieverAdapter": "neurova.agent.retriever_adapters",
    "KnowledgeRetrieverAdapter": "neurova.agent.knowledge_retriever_adapter",
    "TKGRetrieverAdapter": "neurova.agent.tkg_retriever_adapter",
    "GraphRetrieverAdapter": "neurova.agent.graph_retriever_adapter",
}

_PROTOCOL_MEMBERS = ("name", "priority", "retrieve", "get_quality_score")


@pytest.mark.parametrize("cls_name,module", sorted(_ADAPTERS.items()))
def test_adapter_declares_every_protocol_member(cls_name, module):
    """结构性判据：协议四件套一件都不能少（缺一件即 `add_retriever` 必抛）。"""
    import importlib

    cls = getattr(importlib.import_module(module), cls_name)
    missing = [member for member in _PROTOCOL_MEMBERS if not hasattr(cls, member)]
    assert not missing, (
        f"{cls_name} 缺 {missing}——`add_retriever` 的 isinstance 守卫会拒绝它，"
        "而装配点的 except 会把拒收降级成一条 warning（静默丢检索源）。"
    )


def test_annotation_adapter_satisfies_protocol_on_a_real_chain(tmp_path):
    """真链自证：注册必须成功，且真的进了链（不是被 except 吞掉）。"""
    from neurova.agent.annotation_retriever import AnnotationRetrieverAdapter
    from neurova.agent.memory_retrieval_chain import MemoryRetrievalChain, Retriever

    class _Store:
        pass

    adapter = AnnotationRetrieverAdapter(_Store())
    assert isinstance(adapter, Retriever), "缺协议成员，isinstance 守卫必拒"

    chain = MemoryRetrievalChain()
    chain.add_retriever(adapter)  # 不得抛
    assert [r.name for r in chain.get_retrievers()] == ["AnnotationRetriever"]


def test_real_chain_registration_runs_the_pipeline_entry(tmp_path, monkeypatch):
    """生产装配 helper 走真链也要成功（`register_annotation_retriever`）。"""
    from neurova.agent.annotation_retriever import register_annotation_retriever
    from neurova.agent.memory_retrieval_chain import MemoryRetrievalChain

    class _Store:
        pass

    chain = MemoryRetrievalChain()
    assert register_annotation_retriever(chain, _Store()) is True
    assert len(chain.get_retrievers()) == 1


def test_annotation_quality_score_reflects_hits():
    """新补的 `get_quality_score` 必须有真语义（不能是恒 0 占位）。"""
    from neurova.agent.annotation_retriever import AnnotationRetrieverAdapter

    adapter = AnnotationRetrieverAdapter(object())
    assert adapter.get_quality_score([], "q") == 0.0
    # 未标 annotation 的普通记忆不是人工定标产物，不给满分
    assert adapter.get_quality_score([{"content": "普通记忆"}], "q") == 0.0
    hit = [{"content": "7 天无理由退款", "metadata": {"annotation": True}}]
    assert adapter.get_quality_score(hit, "退款政策") == 1.0


def test_assembly_point_escalates_annotation_failure_to_error():
    """放大视角：同类分支（TKG/图检索）缺席是 ERROR，标注分支不得只留 warning。"""
    src = (PROJECT_ROOT / "neurova" / "agent" / "chat_pipeline.py").read_text(encoding="utf-8")
    marker = "AnnotationRetrieverAdapter 接入失败"
    assert marker in src, "装配点标记丢失，判据前提失效"
    # 取标记所在的那一条 logger 调用
    line = next(
        ln for ln in src.splitlines() if marker in ln
    )
    assert "logger.error" in line, (
        f"标注检索缺席仍只记 warning（本轮对话没有人工标注可比对，会被当成无事发生）: {line}"
    )


def test_chain_still_rejects_a_non_conforming_retriever():
    """反向锁：守卫不能被"放宽协议"消除（那是把报错抹平，不是修根因）。"""
    from neurova.agent.memory_retrieval_chain import MemoryRetrievalChain

    class _NotARetriever:
        pass

    with pytest.raises(TypeError):
        MemoryRetrievalChain().add_retriever(_NotARetriever())
