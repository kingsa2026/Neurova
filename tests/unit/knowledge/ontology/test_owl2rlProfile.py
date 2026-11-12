# -*- coding: utf-8 -*-
"""B11 L5：OWL 2 RL 子集声明（profile 文档单源）与引擎能力的互咬判据。

profile 文档是"支持/不支持"的唯一事实源；引擎侧与文档逐条互咬——
文档说不支持的，引擎登记即拒或形状不存在；说支持的，判据在册。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from neurova.knowledge.foundation import productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine, RuleError
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILE = REPO_ROOT / "docs" / "specs" / "2026-11-05-ontology-owl2rl-profile.md"

SUPPORTED = ("subClassOf", "subPropertyOf", "domain", "range", "inverseOf",
             "symmetric", "transitive", "functional", "hasValue")
UNSUPPORTED = ("unionOf", "complementOf", "oneOf", "equivalentClass", "sameAs")


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def engine(store):
    return ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(
        st, toolVersion="b11"))


def test_profileDocExistsAndDeclaresThreeStates():
    assert PROFILE.exists(), "profile 文档是子集声明的唯一事实源"
    text = PROFILE.read_text(encoding="utf-8")
    for axiom in SUPPORTED:
        assert axiom in text, "profile 缺支持条目 %s" % axiom
    for axiom in UNSUPPORTED:
        assert axiom in text, "profile 缺不支持条目 %s（要写明拒法）" % axiom
    assert "物化" in text and "校验" in text and "仅导出" in text, \
        "三态标注（物化/校验/仅导出）必须在册"


def test_unsupportedAxiomsRefusedAtEngineOrAbsent(store):
    """文档说不支持的：引擎要么登记即拒，要么根本没有该形状——不静默半支持。"""
    engine = ForwardChainingEngine(store, gateFactory=None)
    with pytest.raises(RuleError):
        engine.registerRule("bad_shape", "p", [{"atom": "p", "subject": "X",
                                                "object": "Y"}], shape="unionOf")
    assert engine.rule("bad_shape") is None


def test_supportedAxiomsHaveLiveMechanisms(store, engine):
    """说支持的：机制在册（auto 规则族/条件类/闭包/账本），不是纸面声明。"""
    registry = OntologyTermRegistry(store)
    registry.register("parent_rel", "relation")
    registry.register("child_rel", "relation", parentTermId="parent_rel")
    registry.register("knows", "relation", transitive=True)
    engine.ensureAutoRules()

    ids = {r["rule_id"] for r in engine.rules()}
    assert "auto_subproperty:child_rel" in ids, "subPropertyOf 机制在册"
    assert "auto_transitive:knows" in ids, "transitive 机制在册"
