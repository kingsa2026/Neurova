"""012 · 冲突检测语义明确 —— 选"纯观测"就必须明写不阻断（红绿灯 TDD）。

现状（工单 012 的第二个失真点）：`_step_conflict_detection` 跑在 `save_memory`
**之后**，检出冲突只 `logger.warning` + 一条 message 为 "Detected N conflicts"
的 StepResult —— 读起来像"已处置"，实际什么都没改变，是"检测了但永远不拦"的
中间态。

裁决（spec §4 待裁决 4 二选一）：**显式降级为纯观测**。理由：前移否决需要"两条
里哪一条是错的"判据，冲突检测器只给矛盾分，误否决会直接丢真实记忆；D1 的口径
是"不砍量、把无证据摆在明面上"。

因此本步的契约是：结论里必须自带 `blocking=False`（有无冲突都一样），message 必须
写明"纯观测、不阻断"，不得再留"检出了冲突"这种读起来像处置完了的表述。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.post_chat_pipeline import PostChatPipeline


class RecordingConflictDetector:
    """冲突检测器替身：只承担 `detect_conflict(new_memory, existing_memories)` 契约。

    被测判据是"本步是否阻断"，不是检测算法；检测算法自身由
    tests/integration/test_full_conflict_integration.py 锁定。

    载荷成员取自**入参两条记忆**：Issue #72 第四轮起，账上成员必须能在库里定位
    （检测链会按"说不清是谁"拦下合成 id），替身也必须照真实契约给成员 id。
    """

    def __init__(self, conflicts: bool = True) -> None:
        self._report = conflicts
        self.seen: List[Dict[str, Any]] = []

    def detect_conflict(self, new_memory: Any, existing_memories: Any) -> List[Dict[str, Any]]:
        self.seen.append({"new": new_memory, "existing": list(existing_memories)})
        if not self._report or not existing_memories:
            return []
        return [{
            "type": "negation_conflict",
            "similarity": 0.9,
            "contradiction_score": 0.8,
            "memory1_id": new_memory.id,
            "memory2_id": existing_memories[0].id,
            "basis": "同一命题的否证：'我不喜欢咖啡' 与 '我喜欢咖啡'",
        }]


@pytest.fixture()
def probe(tmp_path):
    """真实 MemoryManager + 最小 pipeline；`.make(conflicts)` 按给定清单装配一步。"""
    manager = MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="conflict-agent",
        neuser_id="neu",
        user_id="u1",
        enable_buffer=False,
    )
    tokens: List[Any] = []

    def _make(conflicts: List[Dict[str, Any]]):
        detector = RecordingConflictDetector(conflicts)
        pipeline = PostChatPipeline.__new__(PostChatPipeline)
        tokens.append(PostChatPipeline._step_results_ctx.set([]))
        pipeline._get_dependency = lambda name: {
            "conflict_detector": detector,
            "memory_manager": manager,
        }.get(name)
        return pipeline, detector

    try:
        yield SimpleNamespace(make=_make, manager=manager)
    finally:
        manager.close()
        for token in tokens:
            PostChatPipeline._step_results_ctx.reset(token)


def _run(pipeline: PostChatPipeline):
    """跑一轮真实链路（save_memory → conflict_detection），返回检测步骤读数。

    检测对象是本轮**真实落地**的证据行：成员身份来自落库结果，不由测试桩合成。
    """

    async def _turn():
        await pipeline._step_save_memory("我不喜欢咖啡", "好的，记下了", "s1", True, None)
        await pipeline._step_conflict_detection("我不喜欢咖啡", "好的，记下了")

    asyncio.run(_turn())
    return pipeline._step_results[-1]


class TestObservationOnlyIsExplicit:
    def test_conflict_found_declares_non_blocking(self, probe):
        probe.manager.remember("用户喜欢咖啡")
        pipeline, detector = probe.make(True)
        result = _run(pipeline)

        assert result.data["conflicts_count"] >= 1, "检测确实跑到了（不是恒 0 的假观测）"
        assert result.data["blocking"] is False, "纯观测必须把'不阻断'写进结论"
        assert "不阻断" in result.message, f"message 必须自陈性质，实际: {result.message}"
        assert len(detector.seen[0]["existing"]) >= 1, "观测必须读到真实记忆，不得空转"
        assert len(probe.manager.get_all_memories()) == 3, (
            "纯观测不改写记忆：只多了本轮 save_memory 的两行"
        )

    def test_no_conflict_carries_the_same_declaration(self, probe):
        pipeline, _detector = probe.make(False)
        result = _run(pipeline)
        assert result.data["conflicts_count"] == 0
        assert result.data["blocking"] is False, "口径必须一致：无冲突时同样声明不阻断"
        assert "不阻断" in result.message

    def test_docstring_declares_observation_only(self):
        """步骤自身文档必须写明不阻断，别让读代码的人以为冲突已被处置。"""
        doc = PostChatPipeline._step_conflict_detection.__doc__ or ""
        assert "不阻断" in doc, "_step_conflict_detection 未声明纯观测语义"
