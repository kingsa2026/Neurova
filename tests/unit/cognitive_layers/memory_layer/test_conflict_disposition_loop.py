"""Issue #72 残余项 · 记忆侧冲突链必须闭环（写入→读取→反馈），不得是只写不读的账。

现状取证（本文件编写时实测）：

- `post_chat_pipeline._step_conflict_detection` 检出冲突后只 `logger.warning` +
  一条 StepResult；`manager.get_conflict_summary()` 全仓**零调用方**
  （实测返回 `{'total_conflicts': 0, ...}` 而检测刚报出 1 处冲突——
  因为该读数来自 `ConflictModule` 自己的账，而检测根本没写进去）。
- 于是"冲突"这件事在写入侧被检出、在读取侧看不见：既是 no-op，也是一处断点。
- `ConflictModule._has_negation` 是同一根因（子串含否定词）的**第二份实现**，
  与 `conflict.py` 的误报同形——一个根因两处实现，修一处等于没修。

契约（本文件锁定）：
- 检出的冲突必须带**依据**（凭哪两句、哪条规则认定的）落进记忆侧的账，
  且该账可读：`get_conflict_summary()` 与 `get_stats()` 都要看得到。
- 依据缺失的冲突不得进账（"自动裁决要么带依据，要么不动手"的同一条纪律）。
- 纯观测语义不变：不阻断写入、不改写记忆（工单 012 裁决），
  但"检出了什么"必须可读。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.modules.conflict_module import (
    Conflict,
    ConflictModule,
)
from neurova.post_chat_pipeline import PostChatPipeline


class RecordingConflictDetector:
    """只承担 `detect_conflict(new_memory, existing_memories)` 契约的替身。

    按真实检测器的口径产出**成员就是入参两条记忆**的载荷：Issue #72 第四轮起，
    账上成员必须能在库里定位（合成 id 会被检测链按"说不清是谁"拦下），
    故替身也必须照真实契约给出成员的 id，否则测的就不是生产契约。
    """

    def __init__(self, kind: str = "semantic_contradiction") -> None:
        self._kind = kind
        self.seen: List[Dict[str, Any]] = []

    def detect_conflict(self, new_memory: Any, existing_memories: Any) -> List[Dict[str, Any]]:
        self.seen.append({"new": new_memory, "existing": list(existing_memories)})
        if not existing_memories:
            return []
        return [{
            "type": self._kind,
            "similarity": 0.2,
            "contradiction_score": 0.5,
            "memory1_id": new_memory.id,
            "memory2_id": existing_memories[0].id,
            "basis": "同一对象的取值互斥：'系统出故障了' 与 '系统运行正常'",
        }]


@pytest.fixture()
def manager(tmp_path):
    m = MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="conflict-loop",
        neuser_id="neu",
        user_id="u1",
        enable_buffer=False,
    )
    yield m
    m.close()


def _runStep(manager: MemoryManager, kind: str = "semantic_contradiction"):
    """跑一轮真实链路（save_memory → conflict_detection）。

    检测对象是本轮**真实落地**的证据行：成员身份由落库结果给出，不再由测试桩合成
    （Issue #72 第四轮：账上成员必须能定位）。步骤结果在 contextvar 复位**前**取好。
    """
    pipeline = PostChatPipeline.__new__(PostChatPipeline)
    pipeline._step_results_store = []
    token = PostChatPipeline._step_results_ctx.set([])
    detector = RecordingConflictDetector(kind)
    manager.remember("系统运行正常", memory_type="semantic", origin="owner")
    pipeline._get_dependency = lambda name: {
        "conflict_detector": detector,
        "memory_manager": manager,
    }.get(name)
    try:
        async def _turn():
            await pipeline._step_save_memory("系统怎么样", "系统出故障了", "s1", True, None)
            await pipeline._step_conflict_detection("系统怎么样", "系统出故障了")

        asyncio.run(_turn())
        return pipeline._step_results[-1]
    finally:
        PostChatPipeline._step_results_ctx.reset(token)


class TestLedgerIsWrittenWithBasis:
    def test_detectedConflictLandsInTheMemorySideLedger(self, manager):
        result = _runStep(manager)

        assert result.data["conflicts_count"] >= 1
        summary = manager.get_conflict_summary()
        assert summary["total_conflicts"] == result.data["conflicts_count"], (
            "检出的冲突必须进账，否则读数恒 0 等于没检测"
        )
        assert summary["unresolved"] == summary["total_conflicts"], (
            "尚未处置的冲突应如实计为未解决（本条尚无处置路径，未解决数即入账数）"
        )

    def test_basisIsCarriedOnTheRecordedConflict(self, manager):
        _runStep(manager, "negation_conflict")

        recorded = manager.get_traces_by_trigger(trigger="conflict_detection")
        assert recorded, "冲突账必须可按来源读出"
        assert recorded[0]["basis"], "依据缺失的冲突不得进账——否则又回到'判不出哪条为准'"
        assert "互斥" in recorded[0]["basis"]

    def test_statsExposeTheConflictReading(self, manager):
        result = _runStep(manager)

        stats = manager.get_stats()

        assert "conflicts" in stats, "冲突必须是 /memory/stats 上读得到的读数"
        assert stats["conflicts"]["total"] == result.data["conflicts_count"]

    def test_noBasisMeansNoLedgerEntry(self, manager):
        """依据缺失（旧形状的载荷）不得进账：诚实边界，不假装记了依据。"""
        result = _runStep(manager, "")
        # 替身按 kind="" 产出无 type 的载荷；检测链的入账口径只认唯一判据的两类，
        # 故检出数照报、入账数如实为 0，账上不留记录（诚实边界：不假装记了依据）。
        assert result.data["conflicts_count"] >= 1
        assert result.data["conflicts_recorded"] == 0
        assert manager.get_conflict_summary()["total_conflicts"] == 0


class TestTheSecondImplementationSharesOneRule:
    def test_moduleNegationIsNotSubstringPresence(self):
        """第二份实现（ConflictModule）不得留着同一个误报根因。"""
        module = ConflictModule()
        assert module.detect_conflict("m1", "今天天气不错", "m2", "今天天气很好") is None

    def test_moduleStillCatchesRealContradiction(self):
        module = ConflictModule()
        found = module.detect_conflict("m1", "系统运行正常", "m2", "系统出故障了")
        assert found is not None
        assert found.conflict_type.value == "contradiction"

    def test_recordedConflictNamesItsBasis(self):
        module = ConflictModule()
        found = module.detect_conflict("m1", "系统运行正常", "m2", "系统出故障了")
        assert found.basis, "账上的冲突必须自带依据"


class TestObservationSemanticsUnchanged:
    def test_writePathStillDoesNotBlockOrRewrite(self, manager):
        result = _runStep(manager)

        assert result.data["blocking"] is False, "工单 012 裁决：不阻断写入"
        assert "不阻断" in result.message
        # 纯观测不改写记忆：库里只该有 remember 的一条 + 本轮 save_memory 的两条
        assert len(manager.get_all_memories()) == 3, "纯观测不改写记忆"
