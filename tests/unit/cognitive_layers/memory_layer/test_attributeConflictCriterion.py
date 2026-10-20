"""同属性异值判据并入单源（§6-370）。

v2 的 `ConflictDetector.detect()` 里唯一被 live 判据缺掉的能力是「同一属性、不同取值」
（例：`项目使用 PostgreSQL 数据库` vs `项目使用 MySQL 数据库`）。本批把它并进
`conflict.judgeClauseConflict`——记忆侧唯一判据——再退役 v2。

契约两条：
- 命中：同一属性键、值不同且不是包含关系 ⇒ `attribute_conflict`，`basis` 带键与两值；
- 误报控制：同值、不同键、版本号演进（值都是 `python`）、复合词里的「为/是」、无关记忆
  都不得报成属性冲突；否定命题仍走 `negation_conflict`，不得被属性支抢走。
"""

from __future__ import annotations

from neurova.cognitive_layers.memory_layer.conflict import (
    LegacyConflictDetector,
    judgeClauseConflict,
)
from neurova.cognitive_layers.memory_layer.models import Memory


class TestAttributeValueCriterion:
    def testDifferentIdentifierForSameAttributeFires(self):
        hit = judgeClauseConflict(
            "项目使用 PostgreSQL 数据库",
            "项目使用 MySQL 数据库",
        )

        assert hit is not None, "同一属性上的两个取值互斥，必须报出"
        assert hit[0] == "attribute_conflict"
        assert "postgresql" in hit[3].lower()
        assert "mysql" in hit[3].lower()
        assert "项目" in hit[3], "属性键要报对"
        assert "项目使" not in hit[3], "贪婪匹配把谓词的第一个字吃进了键里"

    def testSpeakerPrefixedTurnStillFires(self):
        hit = judgeClauseConflict(
            "用户: 项目使用 PostgreSQL 数据库\n助手: 记下了",
            "助手: 项目使用 MySQL 数据库",
        )

        assert hit is not None
        assert hit[0] == "attribute_conflict"

    def testSameValueIsNotAConflict(self):
        assert judgeClauseConflict(
            "项目使用 PostgreSQL 数据库",
            "项目使用 PostgreSQL 数据库",
        ) is None

    def testDifferentAttributeKeysAreNotAConflict(self):
        assert judgeClauseConflict(
            "数据库使用 PostgreSQL",
            "缓存使用 Redis",
        ) is None, "两个不同对象各自的取值不构成同一属性的冲突"

    def testContainedValueIsNotAConflict(self):
        assert judgeClauseConflict(
            "项目使用 PostgreSQL",
            "项目使用 PostgreSQL 数据库",
        ) is None, "值只是带了后缀，不是互斥取值"

    def testPythonVersionChangeIsNotAttributeConflict(self):
        # 值都取到 python；3.10/3.12 是演进，不是同一属性的互斥取值。
        assert judgeClauseConflict(
            "项目使用 Python 3.10 版本开发",
            "项目使用 Python 3.12 版本开发",
        ) is None

    def testCopulaInsideCompoundWordIsNotAnAttribute(self):
        assert judgeClauseConflict(
            "我认为这个方案可行",
            "我认为另一个方案可行",
        ) is None, "「认为」里的「为」不是属性谓词"

    def testNegationKeepsItsOwnKind(self):
        hit = judgeClauseConflict(
            "服务器是生产环境",
            "服务器不是生产环境",
        )

        assert hit is not None
        assert hit[0] == "negation_conflict", "否定命题不得被属性支改判"

    def testUnrelatedMemoriesAreNotAConflict(self):
        assert judgeClauseConflict(
            "今天和张三讨论了文件下载方案",
            "用户反馈界面很好用",
        ) is None


class TestSingleSourceFlowsThroughLiveDetector:
    def testLegacyDetectorCarriesAttributeConflict(self):
        detector = LegacyConflictDetector(use_semantic=False)
        newMemory = Memory(id="n1", content="项目使用 PostgreSQL 数据库")
        existing = [Memory(id="e1", content="项目使用 MySQL 数据库")]

        conflicts = detector.detect_conflict(newMemory, existing)

        assert len(conflicts) == 1, "单源判据的结论必须沿既有 detect_conflict 契约出得来"
        assert conflicts[0]["type"] == "attribute_conflict"
        assert conflicts[0]["basis"]
        assert conflicts[0]["memory1_id"] == "n1"
        assert conflicts[0]["memory2_id"] == "e1"

    def testRealDetectorAndRealLedgerCarryTheSignal(self, tmp_path):
        """检出只是半程：属性冲突必须沿 `record_conflicts` 真正进账。

        `record_conflicts` 有一道类型白名单（来源不明的载荷不入账）；新类型若不进白名单，
        步骤会报"检出 1 条、入账 0 条"，读数看起来像没有冲突——与 v2 当年"检出但没人读"
        是同一种断点。
        """
        import asyncio

        from neurova.cognitive_layers.memory_layer.manager import MemoryManager
        from neurova.post_chat_pipeline import PostChatPipeline

        manager = MemoryManager(
            db_path=str(tmp_path / "mem.db"),
            agent_id="attr-live",
            neuser_id="neu",
            user_id="u1",
            enable_buffer=False,
        )
        manager.remember("项目使用 PostgreSQL 数据库", memory_type="semantic", origin="owner")
        pipeline = PostChatPipeline.__new__(PostChatPipeline)
        pipeline._step_results_store = []
        token = PostChatPipeline._step_results_ctx.set([])
        pipeline._get_dependency = lambda name: {
            "conflict_detector": LegacyConflictDetector(use_semantic=False),
            "memory_manager": manager,
        }.get(name)
        try:
            async def _turn():
                await pipeline._step_save_memory(
                    "项目使用 MySQL 数据库", "已更新", "s370", True, None)
                await pipeline._step_conflict_detection(
                    "项目使用 MySQL 数据库", "已更新")

            asyncio.run(_turn())
            result = pipeline._step_results[-1]
            summary = manager.get_conflict_summary()

            assert result.data.get("conflicts_count", 0) >= 1
            assert summary["total_conflicts"] == result.data["conflicts_count"], (
                "检出的属性冲突必须进账；入账 0 等于这条能力又被白名单吞掉")
            recorded = manager.get_traces_by_trigger(trigger="conflict_detection")
            assert recorded and "取值互斥" in recorded[0]["basis"]
        finally:
            PostChatPipeline._step_results_ctx.reset(token)
            manager.close()
