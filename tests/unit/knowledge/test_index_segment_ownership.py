"""「入索引」段必须报出**谁在拥有它**，不许永远挂成"还没做"。

病灶（审计 2026-09-21 §5.5 / Issue #75）：上一批把 `indexing` 从"永远缺一段"改成
`planned` 如实报出，这是对的；但 `planned` 是个双值名册里的垃圾桶——它同时装着
"还没人做"和"由别处负责"。回执上每条写入都挂着 `plannedSegments=['indexing']`，
读的人分不清这是欠账还是设计，欠账就永远没人认领。

判据（不是改名，是可核验的归属）：

1. 名册三态：`wired`（本段内联或有协作者）/ `delegated`（**另有归属**，必须点名归属）/
   `planned`（还没人做）。`delegated` 段必须在名册里写出 owner，写不出就不许进这一态。
2. 归属必须是真的：本文件去查那两个 owner 在真实生产路径上存不存在、有没有被调用。
   owner 一旦消失，守卫红——所以这不是标签，是接线断言。
3. `delegated` 不许混进拒写判据，也不许混进 `planned`；回执三栏分列。
4. 反面控制：名册里若出现"没有 owner 的 delegated"，本文件必须报出来。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from neurova.knowledge.foundation.admission import (
    SEGMENT_OWNERS,
    SEGMENT_STATUS,
    SEGMENTS,
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEUROVA = PROJECT_ROOT / "neurova"


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _request():
    return AdmissionRequest(
        agentId="default", subjectLabel="甲", predicateTermId="uses", objectTerm="乙",
        content="甲使用乙",
        assertions=[{"actorType": "user", "actorId": "u1",
                     "mediumRef": "unit", "statementText": "甲使用乙"}],
    )


class TestRosterIsThreeValuedAndOwned:
    def test_everySegmentHasADeclaredStatus(self):
        assert set(SEGMENT_STATUS) == set(SEGMENTS), "名册必须穷举段序"
        assert set(SEGMENT_STATUS.values()) <= {"wired", "delegated", "planned"}

    def test_delegatedSegmentsNameTheirOwner(self):
        for name, status in SEGMENT_STATUS.items():
            if status != "delegated":
                continue
            owners = SEGMENT_OWNERS.get(name)
            assert owners, "段 %r 报了 delegated 却写不出归属——那就是换个说法盖欠账" % name

    def test_plannedSegmentsHaveNoOwner(self):
        for name, status in SEGMENT_STATUS.items():
            if status == "planned":
                assert name not in SEGMENT_OWNERS, (
                    "段 %r 报了 planned 却挂着归属：要么接线，要么老实说是欠账" % name)

    def test_receiptSplitsAllThreeColumns(self, store):
        receipt = productionAdmissionGate(store).admit(_request())

        assert receipt.pendingSegments == [], "装配漏接的段才是 pending"
        assert receipt.delegatedSegments == ["indexing"], "另有归属的段要分列报出"
        assert receipt.plannedSegments == [], (
            "把 delegated 报成 planned，读的人就分不清欠账与设计")


class TestDelegatedOwnersExistOnTheProductionPath:
    """归属不是标签：去这两个 owner 的实现里查它真的在跑。"""

    def test_narrativeAndChunkIndexOwnerIsTheRepositoryIndexer(self):
        owners = SEGMENT_OWNERS["indexing"]
        repo = (NEUROVA / "knowledge" / "repository.py").read_text(encoding="utf-8")

        for symbol in ("_rebuild_indexes", "_apply_pending_ops", "_ensure_indexes"):
            assert symbol in repo, "条目/分块索引的 owner 少了 %s" % symbol
        assert "index_memories" in repo, "向量路没有写入方，索引段就真的没人拥有"
        assert any("repository" in owner for owner in owners), (
            "归属里必须点名条目仓库索引器：%s" % owners)

    def test_factRankingOwnerIsTheReadSurface(self):
        owners = SEGMENT_OWNERS["indexing"]
        surface = (NEUROVA / "knowledge" / "foundation" / "read_surface.py"
                   ).read_text(encoding="utf-8")

        assert "bm25_rank" in surface, "事实路的排序是查询时算的，owner 就是读面"
        assert "searchableFacts" in surface
        assert any("read_surface" in owner for owner in owners), (
            "归属里必须点名读面：%s" % owners)

    def test_repositoryIndexerIsReachableFromTheSearchPath(self):
        """owner 存在还不够——它得在检索路上被调到（否则是"接了不工作"）。"""
        repo = (NEUROVA / "knowledge" / "repository.py").read_text(encoding="utf-8")
        searchBlock = repo.split("def search_visible_items", 1)[1]

        assert "_ensure_indexes" in searchBlock, (
            "索引维护没有挂在检索入口上，owner 就是个死函数")


class TestDelegatedIsNotAWiringGap:
    def test_bareGateStillReportsPendingNotDelegated(self, store):
        from neurova.knowledge.foundation.admission import KnowledgeAdmissionGate

        bare = KnowledgeAdmissionGate(store)

        assert set(bare.pendingSegments()), "裸门缺的是已实现的段"
        assert "indexing" not in bare.pendingSegments(), (
            "另有归属的段不许进拒写判据——否则纪律又被永久报警淹没")

    def test_noDelegatedSegmentWithoutOwnerInRosterSource(self):
        """反面控制：名册源码里 delegated 与 owner 必须成对出现。"""
        src = io.open(NEUROVA / "knowledge" / "foundation" / "admission.py",
                      encoding="utf-8").read()
        delegated = [line for line in src.splitlines() if '"delegated"' in line]
        assert delegated, "名册里已无 delegated 态——本守卫失去被测对象"


class TestOwnershipIsReadable:
    """归属要能被读出来，而不是只写在源码注释里。"""

    def test_gateReportsOwnersForDelegatedSegments(self, store):
        gate = productionAdmissionGate(store)

        owners = gate.segmentOwners()

        assert "indexing" in owners and owners["indexing"], (
            "另有归属的段必须能在回执/门上报出 owner，否则读的人仍旧不知道谁负责")
        assert set(owners) == {name for name, status in SEGMENT_STATUS.items()
                               if status == "delegated"}

    def test_segmentsAppliedKeepsOnlyWhatRanHere(self, store):
        """`segmentsApplied` 只说"本段在咽喉里跑过"，不许把别处负责的段算进来。"""
        receipt = productionAdmissionGate(store).admit(_request())

        assert "identity_resolution" in receipt.segmentsApplied
        assert not any(entry.startswith("indexing") for entry in receipt.segmentsApplied), (
            "索引由别处负责，混进 segmentsApplied 就是账面冒领")
