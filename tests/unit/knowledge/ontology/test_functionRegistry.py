# -*- coding: utf-8 -*-
"""W2 函数层登记面（specs/2026-11-12 §4）：ontology_functions 表＋唯一读写面。

登记即编译校验（未知符号/越界节点/超深度超尺寸即拒）；output_predicate 须是
注册表在册关系（B-10 纪律：候选谓词清单取注册表）；租户隔离（PK tenant+id）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.function_registry import FunctionRegistry
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("warehouses", "concept", label="仓库")
    registry.register("stores", "relation", domain=["warehouses"],
                      qualifierSchema={"allowed": {"capacity": {"type": "number"}}})
    registry.register("stock_level", "relation")
    registry.register("coverage_days", "relation")
    yield s, registry
    s.close()


class TestFunctionRegistryCrud:
    def test_registerAndList(self, kb):
        s, _registry = kb
        reg = FunctionRegistry(s)
        row = reg.register(
            functionId="stock_coverage", tenantId="default",
            exprText='sum(facts("stores")) / 100',
            outputPredicate="coverage_days",
            inputBindings={"subject": "仓库"},
            label="库存覆盖天数")
        assert row["function_id"] == "stock_coverage"
        assert row["materialization"] == "observe", "缺省 observe（灰度通则 3）"
        assert len(reg.list(tenantId="default")) == 1

    def test_tenantIsolation(self, kb):
        s, _registry = kb
        reg = FunctionRegistry(s)
        reg.register(functionId="f1", tenantId="default",
                     exprText='count(facts("stores"))',
                     outputPredicate="stock_level")
        assert reg.get("f1", tenantId="acme") is None, "跨租户零读"
        with pytest.raises(LookupError):
            reg.update("f1", tenantId="acme", exprText='count(facts("stores"))')

    def test_unregisterOutputPredicateRejected(self, kb):
        """output_predicate 不在注册表 → 登记即拒（B-10：谓词清单取注册表）。"""
        s, _registry = kb
        reg = FunctionRegistry(s)
        with pytest.raises(ValueError, match="注册表"):
            reg.register(functionId="f2", tenantId="default",
                         exprText='count(facts("stores"))',
                         outputPredicate="not_a_term")

    def test_updateAndDisable(self, kb):
        s, _registry = kb
        reg = FunctionRegistry(s)
        reg.register(functionId="f3", tenantId="default",
                     exprText='count(facts("stores"))',
                     outputPredicate="stock_level")
        row = reg.update("f3", tenantId="default", enabled=False,
                         materialization="enforce")
        assert row["enabled"] is False
        assert row["materialization"] == "enforce"

    def test_deleteRetractsConclusions(self, kb):
        """写入即经 dispatch 产出结论（幂等：显式 fireFor 不重复产行）；
        删函数按源撤回其结论（精确撤销复用 derivation_ledger）。"""
        s, registry = kb
        reg = FunctionRegistry(s)
        reg.register(
            functionId="stock_coverage", tenantId="default",
            exprText='sum(facts("stores"))',
            outputPredicate="coverage_days",
            inputBindings={"subject": "仓库"},
            label="库存覆盖天数")
        from neurova.knowledge.foundation.admission import (
            AdmissionRequest, productionAdmissionGate,
        )
        gate = productionAdmissionGate(s)
        receipt = gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="仓库W1", predicateTermId="stores",
            objectTerm="货物X", content="仓库W1 stores 货物X",
            qualifier={"capacity": "200M"},
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test",
                         "statementText": "仓库W1 stores 货物X"}]))
        key = s.resolveSubjectKey("default", "仓库W1")
        conclusions = [f for f in s.factsForSubject(key)
                       if f["predicate_term_id"] == "coverage_days"]
        assert conclusions, "dispatch 应已产出 coverage_days 结论"
        fact = conclusions[0]
        assert fact["qualifier"].get("derived_by") == "function:stock_coverage"
        reg.delete("stock_coverage", tenantId="default",
                   reason="测试删除撤其结论")
        assert s.fact(fact["fact_id"])["status"] == "retracted", \
            "删函数只撤其结论（精确撤销复用 derivation_ledger）"


class TestCompileRejectAtRegistration:
    @pytest.mark.parametrize("expr", [
        "__import__('os').system('x')",              # 恶意调用
        "().__class__",                              # 属性访问
        "[x for x in range(3)]",                     # 推导式
        "lambda: 1",                                 # lambda
        "facts('stores')[0]",                        # 下标
        "sum(facts('stores')); 1",                   # 多语句
        "1 +",                                       # 语法错
    ])
    def test_maliciousOrMalformedRejected(self, kb, expr):
        s, _registry = kb
        reg = FunctionRegistry(s)
        with pytest.raises(ValueError):
            reg.register(functionId="bad", tenantId="default",
                         exprText=expr, outputPredicate="stock_level")
        assert reg.get("bad", tenantId="default") is None

    def test_unknownNameRejected(self, kb):
        s, _registry = kb
        reg = FunctionRegistry(s)
        with pytest.raises(ValueError, match="未知"):
            reg.register(functionId="bad2", tenantId="default",
                         exprText="mystery_var + 1",
                         outputPredicate="stock_level")

    def test_unknownSelectorPredicateRejected(self, kb):
        """selector 引用的谓词不在注册表 → 登记即拒（B-10 同款）。"""
        s, _registry = kb
        reg = FunctionRegistry(s)
        with pytest.raises(ValueError, match="注册表"):
            reg.register(functionId="bad3", tenantId="default",
                         exprText='count(facts("ghost_predicate"))',
                         outputPredicate="stock_level")

    def test_depthAndSizeCapRejected(self, kb):
        """括号不产生 AST 深度——深度/尺寸超限用真嵌套表达式验证（左嵌套加法链）。"""
        s, _registry = kb
        reg = FunctionRegistry(s)
        deep = "1 + " * 60 + "1"
        with pytest.raises(ValueError, match="深度|尺寸"):
            reg.register(functionId="deep", tenantId="default",
                         exprText=deep, outputPredicate="stock_level")
