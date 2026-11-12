# -*- coding: utf-8 -*-
"""W1 抽取面数值 qualifier 引导（specs/2026-11-12 §3）。

extractionPrompt 对 qualifier_schema 声明了数值键的谓词输出数值引导段；
抽取产物（带 qualifier 的关系）经 admit 落 qualifier 数值形。注入假 llm_call
断言 prompt 文案；抽取产物经唯一咽喉落库断言 canonical 形。输出形状仍是
SPO＋qualifier，不造第二抽取形状（B-10 纪律：候选谓词清单仍取注册表）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.graph_bridge import admitExtractedFacts, extractionPrompt
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("warehouses", "concept", label="仓库")
    registry.register("goods", "concept", label="货物")
    registry.register("stores", "relation", domain=["warehouses"],
                      qualifierSchema={"allowed": {"capacity": {"type": "number"}},
                                       "required": []})
    registry.register("mentions", "relation")
    yield s, registry
    s.close()


class TestPromptNumericGuide:
    def test_numericPredicateGetsGuide(self, kb):
        _s, registry = kb
        prompt = extractionPrompt(registry, title="t", content="c")
        assert "stores" in prompt and "capacity" in prompt, \
            "声明数值键的谓词应在 prompt 里获得数值 qualifier 引导"
        assert "单位" in prompt, "引导应说明数字＋单位形态"

    def test_noNumericPredicateNoGuide(self, tmp_path):
        s = KnowledgeFactStore(str(tmp_path / "kb2.db"))
        registry = OntologyTermRegistry(s)
        registry.register("mentions", "relation")
        prompt = extractionPrompt(registry, title="t", content="c")
        assert "qualifier" not in prompt, "无数值谓词时引导段缺席（存量 prompt 零漂移）"
        s.close()

    def test_boundaryUntouched(self, kb):
        _s, registry = kb
        prompt = extractionPrompt(registry, title="t", content="c")
        assert "安全边界" in prompt, "_UNTRUSTED_CONTENT_BOUNDARY 注入边界不动"


class TestExtractionQualifierAdmission:
    def test_relationQualifierLandsCanonical(self, kb):
        s, registry = kb
        item = {"knowledge_id": "k1", "agent_id": "default", "tenant_id": "default",
                "title": "入库单", "content": "仓库W1 stores 货物X 数量 200M",
                "category": ""}
        data = {"entities": [{"label": "仓库W1", "type": "warehouses"},
                             {"label": "货物X", "type": "goods"}],
                "relations": [{"source": "仓库W1", "target": "货物X",
                               "type": "stores", "qualifier": {"capacity": "200MB"}}]}
        factIds = admitExtractedFacts(data, item, s, termRegistry=registry)
        assert factIds, "抽取产物应经咽喉落库"
        qualifier_hit = None
        for fid in factIds:
            fact = s.fact(fid)
            if fact["predicate_term_id"] == "stores":
                qualifier_hit = fact["qualifier"]
        assert qualifier_hit is not None, "stores 关系应落库"
        cap = qualifier_hit.get("capacity")
        assert isinstance(cap, dict) and cap["dimension"] == "data", cap
        assert cap["value"] == pytest.approx(2e8)
