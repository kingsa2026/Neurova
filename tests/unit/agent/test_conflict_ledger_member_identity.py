"""Issue #72 第四轮 · 冲突账上的成员必须是库里查得到的行（红绿灯 TDD）。

断链形状（本文件编写时实测）：`_step_conflict_detection` 用一个**自造的** id
`pending_new_memory` 充当"本轮新证据"——那个 id 在库里根本不存在（实测
`get_memory("pending_new_memory")` 为 None）。而同一轮 `save_memory` 刚落地的
`user_memory_id` / `agent_memory_id` **没有任何读方**。于是：

- 账上 `memory_id_1` 恒为查不到的合成 id，下游连"被指控的两条到底是谁"都指不出来；
- 这正是这条链只能停在"纯观测"、判不出"哪条为准"的现场根因（Issue #72 正文最后一条）。

本文件锁定的契约：
- 冲突检测**逐条落在本轮真实落地的证据行**上，账上每个成员 id 都要能在库里定位
  （否则这条账无法被处置，只是又一份读不懂的账）。
- 本轮没有落地的新证据行时（`save_memory=False`）：观测照跑（不静默跳过），
  但**不落账**，并把"没有可定位的证据行"写进步骤读数（不许拿合成 id 冒充成员）。
- 纯观测语义不变：`blocking=False`、不回滚不新增行（工单 012 裁决原样保留）。
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from neurova.cognitive_layers.memory_layer.conflict import LegacyConflictDetector
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.post_chat_pipeline import PostChatPipeline


@pytest.fixture()
def manager(tmp_path):
    m = MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="ledger-agent",
        neuser_id="neu",
        user_id="u1",
        enable_buffer=False,
    )
    yield m
    m.close()


def _pipeline(manager: MemoryManager) -> PostChatPipeline:
    pipeline = PostChatPipeline.__new__(PostChatPipeline)
    pipeline._step_results_store = []
    pipeline._get_dependency = lambda name: {
        "conflict_detector": LegacyConflictDetector(use_semantic=False),
        "memory_manager": manager,
    }.get(name)
    return pipeline


def _run_turn(pipeline: PostChatPipeline, user_input: str, reply: str, *, save_memory: bool = True):
    """跑一轮真实链路：save_memory → conflict_detection（同一任务上下文，与生产同序）。"""

    async def _turn():
        await pipeline._step_save_memory(user_input, reply, "sess-1", save_memory, None)
        await pipeline._step_conflict_detection(user_input, reply)
        return [r for r in pipeline._step_results if r.step_name == "conflict_detection"][-1]

    return asyncio.run(_turn())


class TestLedgerMembersAreRealRows:
    def test_new_evidence_carries_theLandedRowId(self, manager):
        """账上"新证据"必须指向本轮真实落地的行，不是合成 id。"""
        manager.remember("用户: 我喜欢咖啡", memory_type="episodic", origin="owner")
        pipeline = _pipeline(manager)

        result = _run_turn(pipeline, "我不喜欢咖啡", "好的，记下了")

        assert result.data["conflicts_count"] >= 1, (
            "真否证必须检出——否则本判据会退化成'没冲突所以没问题'的空转"
        )
        ledger = manager.get_traces_by_trigger(trigger="conflict_detection")
        assert ledger, "检出的冲突必须落账"
        landed = {m["id"] for m in manager.get_all_memories()}
        for record in ledger:
            for member in (record["memory_id_1"], record["memory_id_2"]):
                assert member in landed, (
                    f"账上成员 {member!r} 在库里查不到——下游据此判不出哪条为准，"
                    "这条账就无法被处置"
                )

    def test_ledgerMemberIdentityIsNotSynthesised(self, manager):
        manager.remember("用户: 我喜欢咖啡", memory_type="episodic", origin="owner")
        pipeline = _pipeline(manager)

        _run_turn(pipeline, "我不喜欢咖啡", "好的，记下了")

        ledger = manager.get_traces_by_trigger(trigger="conflict_detection")
        members = {record["memory_id_1"] for record in ledger}
        assert "pending_new_memory" not in members, (
            "合成 id 又回来了：它是'查不到的成员'的旧写法"
        )

    def test_evidenceRowsReadBackIsReported(self, manager):
        """判据咬合面：本轮检查了几条真实证据行，必须可读（不然读数说不清范围）。"""
        manager.remember("用户: 我喜欢咖啡", memory_type="episodic", origin="owner")
        pipeline = _pipeline(manager)

        result = _run_turn(pipeline, "我不喜欢咖啡", "好的，记下了")

        assert result.data["evidence_rows"] >= 2, (
            "save_memory 落了用户/助手两行，两行都该被当作本轮证据被检查"
        )


class TestNoLandedRowMeansNoLedgerEntry:
    def test_missingNewEvidenceRowIsDeclaredNotFaked(self, manager):
        """本轮没有落地的新证据行：不落账，并把原因写进读数（不许编个 id 冒充）。"""
        manager.remember("用户: 我喜欢咖啡", memory_type="episodic", origin="owner")
        pipeline = _pipeline(manager)

        result = _run_turn(pipeline, "我不喜欢咖啡", "好的，记下了", save_memory=False)

        assert result.data["evidence_rows"] == 0
        assert result.data["conflicts_recorded"] == 0, (
            "成员无法定位时不得入账——落一条查不到成员的账等于又添一份读不懂的账"
        )
        assert "没有本轮" in result.message, (
            f"为什么不判必须点明（否则读起来像'观测跑了、确实没冲突'）：{result.message}"
        )
        assert manager.get_conflict_summary()["total_conflicts"] == 0


class TestObservationSemanticsUnchanged:
    def test_writePathStillDoesNotBlockOrRewrite(self, manager):
        manager.remember("用户: 我喜欢咖啡", memory_type="episodic", origin="owner")
        pipeline = _pipeline(manager)
        before = len(manager.get_all_memories())

        result = _run_turn(pipeline, "我不喜欢咖啡", "好的，记下了")

        assert result.data["blocking"] is False
        assert "不阻断" in result.message
        assert len(manager.get_all_memories()) == before + 2, (
            "纯观测不改写记忆：只多了本轮 save_memory 的两行"
        )
