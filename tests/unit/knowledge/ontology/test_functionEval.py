# -*- coding: utf-8 -*-
"""W2 受限 AST 求值器（specs/2026-11-12 §4）：function_eval.py 判据。

算术/比较/布尔/聚合在白名单内可算；白名单外节点（属性访问/下标/lambda/推导式/
import）编译期即拒；求值期零 eval/exec。selector＝facts(predicate, qualifierFilter?,
asOf?)，qualifierFilter 值 $绑 定名引用 input_bindings；D1：selector 取全租户事实集，
行数超上限显式拒不静默截断。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.function_eval import (
    FunctionCompileError,
    SelectorCapError,
    compileFunction,
    evaluateFunction,
)


def _compile_ok(expr):
    return compileFunction(expr, allowedNames=("subject",), allowedPredicates=("stores",))


class TestCompile:
    def test_arithmeticAndComparison(self):
        assert _compile_ok("1 + 2 * 3")
        assert _compile_ok("(1 + 2) / 3 > 0.5 and not (1 == 2)")

    def test_aggregates(self):
        assert _compile_ok('sum(facts("stores"))')
        assert _compile_ok('count(facts("stores", {"warehouse": "$subject"}))')
        assert _compile_ok('avg(facts("stores"))')
        assert _compile_ok('min(facts("stores"))')
        assert _compile_ok('max(facts("stores"))')

    def test_forbiddenNodesRejected(self):
        for expr in ("a.b", "x[0]", "lambda: 1", "[i for i in y]",
                     "__import__('os')", "f'{1}'", "{'a': 1}", "'a' if x else 'b'"):
            with pytest.raises(FunctionCompileError):
                _compile_ok(expr)

    def test_nonWhitelistCallRejected(self):
        with pytest.raises(FunctionCompileError):
            _compile_ok("open('x')")

    def test_selectorRequiresLiteralPredicate(self):
        """selector 谓词须是字面量（可静态提依赖），不接受拼接。"""
        with pytest.raises(FunctionCompileError):
            _compile_ok("count(facts(subject))")


class TestEvaluate:
    def _kb(self, tmp_path, rows):
        s = KnowledgeFactStore(str(tmp_path / "kb.db"))
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        registry = OntologyTermRegistry(s)
        registry.register("stores", "relation",
                          qualifierSchema={"allowed": {"capacity": {"type": "number"}}})
        gate = productionAdmissionGate(s)
        for i, (subject, obj, qualifier) in enumerate(rows):
            content = "%s stores %s" % (subject, obj)
            gate.admit(AdmissionRequest(
                agentId="default", subjectLabel=subject, predicateTermId="stores",
                objectTerm=obj, content=content, qualifier=qualifier or {},
                assertions=[{"actorType": "pipeline", "actorId": "unit",
                             "mediumRef": "unit:test", "statementText": content}]))
        return s

    def _runner(self, store):
        from neurova.knowledge.ontology.function_eval import makeSelectorRunner

        return makeSelectorRunner(store, agentId="default", tenantId="default")

    def test_sumOverQuantityFacts(self, tmp_path):
        s = self._kb(tmp_path, [
            ("仓库W1", "货物A", {"capacity": "200M"}),
            ("仓库W2", "货物B", {"capacity": "0.3G"}),
        ])
        compiled = _compile_ok('sum(facts("stores"))')
        value = evaluateFunction(compiled, {}, self._runner(s))
        assert value == pytest.approx(5e8), "200M + 0.3G = 5e8（量值归一后聚合）"
        s.close()

    def test_countAndQualifierFilter(self, tmp_path):
        s = self._kb(tmp_path, [
            ("仓库W1", "货物A", {"capacity": "1"}),
            ("仓库W2", "货物B", {"capacity": "2"}),
        ])
        compiled = _compile_ok('count(facts("stores", {"subject_key": "$subject"}))')
        value = evaluateFunction(
            compiled, {"subject": "仓库W1"}, self._runner(s))
        assert value == 1, "qualifierFilter 绑定名过滤"
        s.close()

    def test_emptySelectorAggregates(self, tmp_path):
        s = self._kb(tmp_path, [])
        assert evaluateFunction(_compile_ok('count(facts("stores"))'), {},
                                self._runner(s)) == 0
        assert evaluateFunction(_compile_ok('sum(facts("stores"))'), {},
                                self._runner(s)) == 0
        assert evaluateFunction(_compile_ok('avg(facts("stores"))'), {},
                                self._runner(s)) is None, "空集 avg/min/max 诚实 None"
        s.close()

    def test_selectorCapExplicitReject(self, tmp_path, monkeypatch):
        s = self._kb(tmp_path, [("仓库W%d" % i, "货物%d" % i, {}) for i in range(3)])
        from neurova.knowledge.ontology import function_eval

        monkeypatch.setattr(function_eval, "SELECTOR_ROW_CAP", 2)
        compiled = function_eval.compileFunction(
            'sum(facts("stores"))', allowedNames=(), allowedPredicates=("stores",))
        with pytest.raises(SelectorCapError):
            evaluateFunction(compiled, {}, self._runner(s))
        s.close()

    def test_zeroEvalExec(self):
        """求值器不引用 eval/exec（白名单求值走 AST 解释，零 eval/exec）。"""
        import inspect

        from neurova.knowledge.ontology import function_eval

        source = inspect.getsource(function_eval)
        for banned in ("eval(", "exec(", "__subclasses__", "getattr(ast"):
            assert banned not in source, banned
