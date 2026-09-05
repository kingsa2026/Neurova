"""睡眠巩固写回翻倍回归测试

事故（2026-09-05）：idle_tracker 空闲巩固每轮把整库记忆原样复制一份
（5040 → 10080 → 20160 指数翻倍，persist 库 37,714 行 / 去重仅 90 条）。

根因（双处对称缺陷）：
1. sleep.consolidate() 对单例簇也创建新 MemoryRecord 并填 merged_from=[自身id]
   → truthy，下游无法区分"真实合并产物"与"原样单例"。
2. sleep_writeback 新增分支门禁为 merged_from 非空（truthy），而删除侧已修为
   source_ids >= 2 —— 新增侧无门禁，单例记忆全部走 remember() 重复插入，
   且源记忆永不删除 → 每轮巩固 = 全库翻倍。

契约（本测试锁死）：
- 全部单例簇的巩固结果写回时 added == 0，原记忆走温度更新分支。
- 真实合并（≥2 源）仍走 remember() 新增 + 源记忆 soft forget。
- consolidate() 对单例簇保留原记录（id 不变、merged_from 不伪造）。
"""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation
from neurova.cognitive_layers.memory_layer.sleep_writeback import write_back_consolidation_result


def _rec(i, content, embedding=None):
    return MemoryRecord(
        id=f"m{i}",
        content=content,
        embedding=embedding or [],
        temperature=50.0,
        importance=50.0,
        created_at=datetime.now(),
    )


class TestSingletonClusterNoDuplication:
    """全部单例簇场景：写回不得新增任何记忆（翻倍事故防线）"""

    def _all_singleton_result(self, n=3):
        """模拟当前生产最常见情形：无 embedding → 每条记忆各自成簇。

        直接用真实 consolidate() 产出，保证与生产路径一致。
        """
        engine = SleepConsolidation(memory_manager=MagicMock(), storage=MagicMock())
        memories = [_rec(i, f"内容{i}唯一的记忆文本") for i in range(n)]
        merged_memories, merge_results = engine.consolidate(memories)
        return {"merged_memories": merged_memories, "merge_results": merge_results}

    def test_consolidate_singletons_keep_original_id(self):
        """单例簇在 consolidate() 输出中应保留原 id、不伪造 merged_from"""
        engine = SleepConsolidation(memory_manager=MagicMock(), storage=MagicMock())
        memories = [_rec(1, "你好，请问现在几点"), _rec(2, "今天天气不错")]
        merged_memories, merge_results = engine.consolidate(memories)

        by_id = {m.id: m for m in merged_memories}
        for src in memories:
            assert src.id in by_id, f"单例记忆 {src.id} 应原样保留，而非生成新记录"
            assert by_id[src.id].merged_from == [], (
                f"单例记忆 {src.id} 的 merged_from 应为空，不得伪造为 {by_id[src.id].merged_from}"
            )

    def test_writeback_all_singletons_adds_zero(self):
        """全单例巩固结果写回：added 必须为 0，走温度更新分支"""
        result = self._all_singleton_result(3)
        mock_mm = MagicMock()

        stats = write_back_consolidation_result(mock_mm, result)

        assert stats["added"] == 0, f"单例记忆不得被重新插入（翻倍根因），实际 added={stats['added']}"
        assert stats["forgotten"] == 0
        assert stats["updated"] == 3
        assert not mock_mm.remember.called, "单例记忆走温度更新分支，不得调用 remember()"

    def test_writeback_singletons_full_cycle_no_growth(self):
        """端到端语义：N 条记忆完整巩固一轮后，写回净增量必须为 0"""
        n = 10
        result = self._all_singleton_result(n)
        mock_mm = MagicMock()
        # 温度更新成功
        mock_mm.update_memory_temperature.return_value = True

        stats = write_back_consolidation_result(mock_mm, result)

        net_growth = stats["added"] - stats["forgotten"]
        assert net_growth == 0, f"一轮巩固后净增长必须为 0，实际 {net_growth}（事故根因）"


class TestRealMergeStillWorks:
    """真实合并（≥2 源）契约不回归：新增 + 删源照常"""

    def test_writeback_real_merge_adds_and_forgets(self):
        mock_mm = MagicMock()
        merged_mem = MagicMock()
        merged_mem.merged_from = ["m1", "m2"]
        merged_mem.content = "合并后的内容"
        merged_mem.categories = ["conversation"]
        merged_mem.importance = 60.0
        merged_mem.temperature = 55.0
        merged_mem.is_archived = False
        result = {
            "merged_memories": [merged_mem],
            "merge_results": [MagicMock(source_ids=["m1", "m2"])],
        }

        stats = write_back_consolidation_result(mock_mm, result)

        assert mock_mm.remember.called
        assert mock_mm.remember.call_args.kwargs["content"] == "合并后的内容"
        assert stats["added"] == 1
        assert stats["forgotten"] == 2

    def test_writeback_mixed_result(self):
        """混合场景：1 条真实合并 + 2 条单例 → added=1, forgotten=2, updated=2"""
        engine = SleepConsolidation(memory_manager=MagicMock(), storage=MagicMock())
        a1 = _rec("a1", "相似内容第一句，用于聚类合并测试")
        a2 = _rec("a2", "相似内容第二句，用于聚类合并测试", embedding=[1.0, 0.0])
        a1.embedding = [1.0, 0.0]
        s1 = _rec("s1", "完全不同的话题内容甲")
        s2 = _rec("s2", "完全不同的话题内容乙")

        # 手工构造：a1/a2 合并，s1/s2 单例 —— 绕开聚类实现细节，直接组装结果
        merged_memories, merge_results = engine.consolidate([a1, a2, s1, s2])
        result = {"merged_memories": merged_memories, "merge_results": merge_results}

        mock_mm = MagicMock()
        stats = write_back_consolidation_result(mock_mm, result)

        # a1/a2 嵌入相同必成一簇（≥2 源），s1/s2 单例
        assert stats["added"] == 1, f"仅真实合并产生新增，实际 {stats}"
        assert stats["forgotten"] == 2, f"仅合并源被删除，实际 {stats}"
        assert stats["updated"] == 2, f"两条单例走温度更新，实际 {stats}"
