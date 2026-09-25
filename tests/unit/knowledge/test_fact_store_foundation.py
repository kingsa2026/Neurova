"""事实底座立骨与 admit 咽喉骨架（工单 003，设计文档 §4.2、§5）。

示踪弹：一条事实经咽喉 admit 进去、按身份查回；未接通的段必须显式暴露，不许静默跳过。
命名口径：方法与属性 camelCase，落库列名与返回的行 dict 保持 snake_case。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    AdmissionSegmentMissing,
    KnowledgeAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import (
    KnowledgeFactStore,
    get_knowledge_fact_store,
    reset_knowledge_fact_store,
)


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _resetSingleton():
    yield
    reset_knowledge_fact_store()


def _request(**overrides):
    payload = dict(
        agentId="bench",
        subjectLabel="神经瓦",
        predicateTermId="has_component",
        objectTerm="记忆层",
        content="神经瓦的记忆层含时序事实底座。",
        sourceTurnId="turn-1",
    )
    payload.update(overrides)
    return AdmissionRequest(**payload)


class TestStoreLifecycle:
    def test_schemaIsIdempotent(self, store):
        store._ensureSchema()
        store._ensureSchema()

        assert store.factCount() == 0

    def test_defaultConstructionRefusesMemorySilently(self):
        """B01 的成因就是无参构造落 :memory:——这里必须当场拒绝，而不是给个默认。"""
        with pytest.raises(ValueError, match="显式传入"):
            KnowledgeFactStore()

    def test_explicitInMemoryIsAllowedForTests(self):
        store = KnowledgeFactStore(":memory:")
        try:
            assert store.factCount() == 0
        finally:
            store.close()

    def test_singletonIsCachedAndResettable(self, tmp_path):
        first = get_knowledge_fact_store(db_path=str(tmp_path / "s.db"))
        assert get_knowledge_fact_store() is first

        reset_knowledge_fact_store()

        # 复位后再取必须重新建实例，而且要带自己的路径：无参工厂的兜底是生产库，
        # 围栏现在会当场拒（见 test_default_storage_write_fence 的"每个写入面都被守"）
        second = get_knowledge_fact_store(db_path=str(tmp_path / "s2.db"))
        assert second is not first
        # 自己造的实例自己收：留着句柄会让 Windows 清不掉临时目录，
        # 也会把单例留在已删目录上给后面的用例挖坑
        reset_knowledge_fact_store()


class TestIdentityLayer:
    def test_sameCanonicalLabelReusesSubjectKey(self, store):
        key1 = store.upsertSubject("bench", "神经瓦")
        key2 = store.upsertSubject("bench", "  神经瓦 ")

        assert key1 == key2
        assert store.subjectCount() == 1

    def test_aliasResolvesToCanonicalSubject(self, store):
        key = store.upsertSubject("bench", "神经瓦", aliases=["Neurova"])

        assert store.resolveSubjectKey("bench", "Neurova") == key

    def test_mergePointsOldKeyToNew(self, store):
        old = store.upsertSubject("bench", "旧称")
        new = store.upsertSubject("bench", "新称")

        store.mergeSubjects(old, new, reason="003 用例")

        assert store.resolveSubjectKey("bench", "旧称") == new
        assert store.subjectFor(old)["merged_into"] == new

    def test_mergeRejectsSelfMerge(self, store):
        key = store.upsertSubject("bench", "独称")

        with pytest.raises(ValueError, match="自身"):
            store.mergeSubjects(key, key)


class TestAdmissionSkeleton:
    def test_admitWithoutCollaboratorsReportsMissingSegments(self, store):
        gate = KnowledgeAdmissionGate(store)

        with pytest.raises(AdmissionSegmentMissing) as exc:
            gate.admit(_request())

        assert exc.value.segments, "未接通的段必须逐名报出"
        assert store.factCount() == 0, "缺段时不得半写"

    def test_admitWithPendingAcknowledgedWritesAndReadsBack(self, store):
        gate = KnowledgeAdmissionGate(store)

        receipt = gate.admit(_request(), allowPendingSegments=True)
        facts = store.factsForSubject(receipt.subjectKey)

        assert receipt.factId
        assert len(facts) == 1
        assert facts[0]["object_term"] == "记忆层"
        assert facts[0]["status"] == "active"
        assert receipt.pendingSegments, "回执必须自带未接通段清单，不得装作全链已通"

    def test_confidenceIsNeverInvented(self, store):
        """G11：底座不替调用方造置信度——没断言就是 NULL，不是 0.7。"""
        gate = KnowledgeAdmissionGate(store)

        receipt = gate.admit(_request(), allowPendingSegments=True)

        assert store.fact(receipt.factId)["confidence"] is None

    @pytest.mark.parametrize("field",
                             ["subjectLabel", "predicateTermId", "objectTerm", "content"])
    def test_requiredFieldsAreEnforced(self, store, field):
        gate = KnowledgeAdmissionGate(store)
        payload = _request()
        setattr(payload, field, "")

        with pytest.raises(ValueError, match=field):
            gate.admit(payload, allowPendingSegments=True)

    def test_admitSameTripleIsNotDuplicated(self, store):
        """同三元组重放不另开行；内容级去重是工单 004 的口径。"""
        gate = KnowledgeAdmissionGate(store)

        first = gate.admit(_request(), allowPendingSegments=True)
        second = gate.admit(_request(), allowPendingSegments=True)

        assert first.factId == second.factId
        assert store.factCount() == 1


class TestMigrationVersions:
    def test_everyTableExistsAfterMigrationChain(self, store):
        """v1 发布后新增的结构必须走新版本号，否则老库永远拿不到它（工单 011 真数据回填炸过）。"""
        names = {r[0] for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

        assert {'knowledge_subjects', 'knowledge_facts', 'knowledge_activities',
                'knowledge_assertions', 'knowledge_conflicts',
                'knowledge_narratives', 'knowledge_tombstones',
                'knowledge_entry_conflicts', 'ontology_terms',
                'ontology_rules', 'knowledge_derivation_edges',
                'ontology_rule_fires', 'knowledge_lineage_heads'} <= names
        assert int(store._conn.execute('PRAGMA user_version').fetchone()[0]) == 12

    def test_reopeningAnExistingDbStillUpgrades(self, tmp_path):
        first = KnowledgeFactStore(str(tmp_path / 'reopen.db'))
        first.close()

        second = KnowledgeFactStore(str(tmp_path / 'reopen.db'))
        names = {r[0] for r in second._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        second.close()

        assert 'knowledge_assertions' in names
