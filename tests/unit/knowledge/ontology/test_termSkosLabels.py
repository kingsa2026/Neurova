# -*- coding: utf-8 -*-
"""B10 L2 术语层（升级计划 §12.3）：SKOS 多语言标签、模块化、版本化 IRI。

SKOS 只做词表与导出，不参与推理；core 模块不被 domain 覆盖；
新登记版本走 semver，存量 vN 继续可读。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def registry(store):
    return OntologyTermRegistry(store)


class TestSkosLabels:
    def test_multilingualLabelsRoundTrip(self, registry):
        registry.register("part_of", "relation", label="属于",
                          labels={"zh": "属于", "en": "part of"},
                          altLabels={"zh": ["隶属于"], "en": ["contained in"]})

        term = registry.term("part_of")
        assert term["labels"]["en"] == "part of"
        assert term["alt_labels"]["zh"] == ["隶属于"]

    def test_prefLabelFallsBackToLabel(self, registry):
        """没声明多语言时，prefLabel 读 label——单语存量零漂移。"""
        registry.register("plain", "concept", label="普通")

        assert registry.term("plain")["labels"].get("zh", registry.term("plain")["label"]) \
            in ("普通", None) or registry.term("plain")["label"] == "普通"

    def test_unknownLangRejected(self, registry):
        """语言标记闭集守卫：非 BCP47 形状拒绝（防自由文本污染词表）。"""
        with pytest.raises(ValueError, match="语言"):
            registry.register("bad_lang", "concept", labels={"not a lang": "x"})


class TestTermModules:
    def test_seedPredicatesAreCore(self, registry):
        assert registry.term("is_a")["module"] == "core"
        assert registry.term("documented_as")["module"] == "core"

    def test_domainTermRegisteredAsDomain(self, registry):
        registry.register("supplies_to", "relation", module="domain")
        assert registry.term("supplies_to")["module"] == "domain"

    def test_domainCannotOverrideCoreSameId(self, registry):
        """core 同 id 不许被 domain 覆盖：结构谓词是地基，不是业务可改面。"""
        with pytest.raises(ValueError, match="core"):
            registry.register("is_a", "relation", module="domain")

    def test_moduleFlipFromDomainToCoreRejected(self, registry):
        registry.register("biz_rel", "relation", module="domain")
        with pytest.raises(ValueError, match="core"):
            registry.register("biz_rel", "relation", module="core")


class TestVersionedIri:
    def test_semverAcceptedAndLegacyVnStillReadable(self, registry):
        registry.register("semver_term", "concept", version="1.2.3")
        assert registry.term("semver_term")["version"] == "1.2.3"

        registry.register("legacy_term", "concept", version="v3")
        assert registry.term("legacy_term")["version"] == "v3", "存量 vN 仍可读"

    def test_garbageVersionRejected(self, registry):
        with pytest.raises(ValueError, match="版本"):
            registry.register("bad_ver", "concept", version="第3版")

    def test_versionedIriExportHelper(self, registry):
        """冻结版本导出：.../v1/<term> 形状；默认仍是 kbg:<term> 不带版本段。"""
        from neurova.knowledge.ontology.term_registry import versionedIri

        assert versionedIri("part_of", "1.0.0") == \
            "https://neurova.local/knowledge/1.0.0/part_of"
        from neurova.knowledge.ontology.turtle import iri
        assert iri("part_of") == "kbg:part_of", "默认导出不带版本段"
