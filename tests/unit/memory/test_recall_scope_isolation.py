# -*- coding: utf-8 -*-
"""P1-10 票 A 验收·检索链请求作用域隔离黑盒测试。

背景（全库断点审计 P1-10 复核，audit-reports/simplification-audit-2026-11-12-复核.md）：
- 票 B（渠道 sender→neuser 绑定）已由并发批在 channel_router.py:290-292 落地
  （每回合 set_request_scope(真 turnIdentity)）；
- 写路径经 memoryScope() 单源盖章（cognitive_storage_engine.py:389-395）；
- 本文件验证读侧：同一 MemoryManager（同一 agent 库）下，用户 A 写入的私有记忆
  在用户 B 的请求作用域里**不得被召回**——覆盖 manager.recall、
  CognitiveStorageEngine.retrieve、UnifiedRetriever.retrieve、
  NeurovaRecallEngine.recall_flat 四条读路。

已知的未覆盖面（另票）：MoE 向量索引在 mem_core.py:806-812 按 persist.db 全库
无差别建索引（不含身份元数据），MoE 支路的隔离需先改索引形状，见台账复核。
"""
import pytest


@pytest.fixture
def stack(tmp_path):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
        CognitiveStorageEngine,
    )
    from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
    from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

    mgr = MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="agent_iso",
        neuser_id="default",
        user_id="default",
    )
    engine = CognitiveStorageEngine(agent_id="agent_iso", memory_manager=mgr)
    retriever = UnifiedRetriever(engine)
    recall = NeurovaRecallEngine(memory_manager=mgr)
    return mgr, retriever, recall


SECRET = "用户A的私有事实：保险箱密码是1qaz2wsx"


def _contents(rows):
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(str(r.get("content") or ""))
        else:
            out.append(str(getattr(r, "content", "") or ""))
    return out


class TestRecallScopeIsolation:
    @pytest.mark.asyncio
    async def test_user_a_writes_user_b_cannot_recall(self, stack):
        mgr, retriever, recall = stack

        mgr.set_request_scope(neuser_id="ne-a", user_id="u-a")
        mgr.remember(SECRET, auto_classify=False)

        # 用户 B 的请求作用域：任何读路都不得带回 A 的私有事实
        mgr.set_request_scope(neuser_id="ne-b", user_id="u-b")
        leaked = []

        recalled = mgr.recall(SECRET[:6], limit=10)
        if SECRET in _contents(recalled):
            leaked.append("manager.recall")

        engine_rows = retriever.engine.retrieve(SECRET[:6], limit=10)
        if SECRET in _contents(engine_rows):
            leaked.append("storage_engine.retrieve")

        unified = await retriever.retrieve(SECRET[:6], limit=10)
        if SECRET in _contents(unified):
            leaked.append("unified_retriever.retrieve")

        flat = recall.recall_flat(SECRET[:6], limit=10)
        if SECRET in _contents(flat):
            leaked.append("recall_flat")

        assert not leaked, (
            f"跨人串忆实锤：用户 B 的作用域召回了用户 A 的私有记忆，泄漏读路={leaked}"
        )

    @pytest.mark.asyncio
    async def test_owner_still_recalls_own_memory(self, stack):
        """反向对照：作用域隔离不得把本人记忆也隔离掉。"""
        mgr, retriever, recall = stack
        mgr.set_request_scope(neuser_id="ne-a", user_id="u-a")
        mgr.remember(SECRET, auto_classify=False)

        assert SECRET in _contents(mgr.recall(SECRET[:6], limit=10)), "本人召回不得丢"
        unified = await retriever.retrieve(SECRET[:6], limit=10)
        assert SECRET in _contents(unified), "本人经统一检索器不得丢"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
