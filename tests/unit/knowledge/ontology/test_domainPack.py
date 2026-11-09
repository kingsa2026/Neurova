# -*- coding: utf-8 -*-
"""标准本体领域包契约（GB/T 48000.3 评估档 G5，第 9 章扩展方式的示范载体）。

- 包是数据（JSON），不是代码级种子——按第 9 章扩展原则承载"标准文献"领域词汇；
- 导入 = seedMissing 只补缺：已登记术语一行不动（写入方覆盖声明以登记者为准）；
- 词汇依据：GB/T 48000.3 征求意见稿（2025-04-29）6.2.1–6.2.13 ＋ 第 8 章，
  正式版核对约定见评估档 §5.4（包内 note 字段随包声明）。
"""
import pytest

from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.ontology.domain_pack import (
    loadDomainPack,
    importDomainPack,
    availablePacks,
)
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture()
def registry():
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    store = KnowledgeFactStore(":memory:")
    applyTo(store._conn)
    yield OntologyTermRegistry(store)
    store.close()


class TestPackLoad:
    def test_packLoads(self):
        pack = loadDomainPack("standard")
        assert pack["packId"] == "standard"
        assert pack["namespace"] == "so"
        concepts = [t for t in pack["terms"] if t["kind"] == "concept"]
        relations = [t for t in pack["terms"] if t["kind"] == "relation"]
        # 6.2 一级实体类型代表性锚点（标准实体根/相关方/层次/信息单元/约束/外部资源）
        ids = {t["termId"] for t in concepts}
        assert {"Standard", "Stakeholder", "StructuralElement",
                "InformationUnit", "Constraint", "ExternalResource"} <= ids
        # 全部术语挂 so 命名空间且带定义（G1/G4 字段）
        assert all(t.get("namespace") == "so" for t in pack["terms"])
        assert all(str(t.get("definition") or "").strip() for t in pack["terms"])
        # 8 章关系代表锚点
        relIds = {t["termId"] for t in relations}
        assert {"hasPart", "defines", "hasPrecondition",
                "normativeReference", "replacedBy", "administeredBy"} <= relIds

    def test_availablePacks(self):
        packs = availablePacks()
        assert {p["packId"] for p in packs} >= {"standard"}


class TestImport:
    def test_importSeedsAllAndIdempotent(self, registry):
        pack = loadDomainPack("standard")
        added1 = importDomainPack(registry, "standard")
        assert added1 == len(pack["terms"])
        added2 = importDomainPack(registry, "standard")
        assert added2 == 0, "二次导入必须零写入（只补缺）"

    def test_importedTermsCarryNamespaceAndDefinition(self, registry):
        importDomainPack(registry, "standard")
        term = registry.term("Standard", tenantId="default")
        assert term["namespace"] == "so"
        assert term["definition"].strip()
        # 层级：章/条挂 StructuralElement（6.2.5）
        assert registry.term("Clause", tenantId="default")["parent_term_id"] == "StructuralElement"

    def test_importDoesNotClobberUserEdits(self, registry):
        """写入方已登记的同名术语一行不动（seedMissing 只补缺纪律）。"""
        registry.register("Standard", "concept", label="用户改过的标准")
        importDomainPack(registry, "standard")
        term = registry.term("Standard", tenantId="default")
        assert term["label"] == "用户改过的标准"
        assert term["namespace"] == "", "已存在行不被包回写"

    def test_unknownPackRejected(self, registry):
        with pytest.raises(ValueError, match="未注册领域包"):
            importDomainPack(registry, "nonexistent")
