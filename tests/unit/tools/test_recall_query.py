"""对照批 B3：recall_query 受限 Python 表达式查询。

红灯（实现前）：schema/dispatch 无 recall_query、引擎模块不存在。
绿灯：
- schema 与 _builtin_dispatch 双侧注册（既有不变量测试同款口径）；
- runRecallExpression：过滤/统计可表达；import/getattr/下划线属性拒绝；
  结果截断；
- handler：走 stub context_pool 的取数→投影→求值全链。
"""

import ast
import asyncio
from types import SimpleNamespace

import pytest

from neurova.tools.recall_expression import (
    RecallExpressionError,
    runRecallExpression,
)

ITEMS = [
    {"content": "部署失败了，报错在 build 阶段", "turn_id": "t1", "recalled_from": "memory_ledger"},
    {"content": "部署成功了", "turn_id": "t2", "recalled_from": "memory_ledger"},
    {"content": "回滚到上一个版本", "turn_id": "t3", "recalled_from": "memory_ledger"},
]


class TestExpressionEngine:

    def test_filter_expression(self):
        result = runRecallExpression(
            "[i['content'] for i in items if '失败' in i['content']]", ITEMS)
        assert "部署失败了" in result and "部署成功了" not in result

    def test_stats_expression(self):
        result = runRecallExpression("len(items)", ITEMS)
        assert result == "3"

    def test_import_rejected(self):
        with pytest.raises(RecallExpressionError):
            runRecallExpression("__import__('os').getcwd()", ITEMS)

    def test_getattr_rejected(self):
        with pytest.raises(RecallExpressionError):
            runRecallExpression("getattr(items, 'append')", ITEMS)

    def test_dunder_attribute_rejected(self):
        with pytest.raises(RecallExpressionError):
            runRecallExpression("items.__class__", ITEMS)

    def test_statement_rejected(self):
        with pytest.raises(RecallExpressionError):
            runRecallExpression("import os", ITEMS)

    def test_result_truncated(self):
        big = [{"content": "x" * 500} for _ in range(20)]
        result = runRecallExpression("str(items)", big)
        assert len(result) <= 2100 and "截断" in result


class TestExpressionResourceBoundary:

    def test_eval_is_not_used(self, monkeypatch):
        def forbiddenEval(*args, **kwargs):
            raise AssertionError("expression engine called eval")

        monkeypatch.setattr("builtins.eval", forbiddenEval)

        assert runRecallExpression("len(items)", [{}, {}]) == "2"

    def test_mutating_list_method_is_rejected_before_call(self):
        class GuardedItems(list):
            def append(self, item):
                raise RuntimeError("MUTATION_CALLED")

        with pytest.raises(RecallExpressionError, match="append"):
            runRecallExpression("[items.append(0) for _ in items]", GuardedItems([{}]))

    def test_container_allocation_budget(self):
        with pytest.raises(RecallExpressionError, match="容器"):
            runRecallExpression("[0] * 100000", [])

    def test_string_allocation_budget(self):
        with pytest.raises(RecallExpressionError, match="字符串"):
            runRecallExpression("'x' * 20001", [])

    def test_iteration_budget_accepts_boundary_and_rejects_next(self):
        boundary = [{"content": "x"} for _ in range(10000)]
        assert runRecallExpression("sum(1 for i in items)", boundary) == "10000"

        over = boundary + [{"content": "x"}]
        with pytest.raises(RecallExpressionError, match="迭代"):
            runRecallExpression("sum(1 for i in items)", over)

    def test_ast_node_budget_accepts_boundary_and_rejects_next(self):
        def expressionFor(size):
            return "sum([%s])" % ",".join(["1"] * size)

        def nodeCount(size):
            return sum(1 for _ in ast.walk(ast.parse(expressionFor(size), mode="eval")))

        size = 1
        while nodeCount(size + 1) <= 512:
            size += 1
        assert runRecallExpression(expressionFor(size), []) == str(size)
        with pytest.raises(RecallExpressionError, match="节点"):
            runRecallExpression(expressionFor(size + 1), [])

    def test_time_budget_is_enforced(self, monkeypatch):
        from neurova.tools import recall_expression

        clock = iter((0.0, 1.0))
        monkeypatch.setattr(recall_expression, "monotonic", lambda: next(clock), raising=False)

        with pytest.raises(RecallExpressionError, match="时间"):
            runRecallExpression("len(items)", [{}])

    def test_expression_length_is_bounded_before_parse(self):
        expression = "1+" * 5000 + "1"
        with pytest.raises(RecallExpressionError, match="长度"):
            runRecallExpression(expression, [])

    def test_step_budget_is_enforced(self, monkeypatch):
        from neurova.tools import recall_expression

        monkeypatch.setattr(recall_expression, "monotonic", lambda: 0.0)
        monkeypatch.setattr(recall_expression, "MAX_STEPS", 5)
        with pytest.raises(RecallExpressionError, match="步数"):
            runRecallExpression("sum(1 for i in items)", [{}, {}])

    def test_integer_allocation_is_bounded(self):
        with pytest.raises(RecallExpressionError, match="整数"):
            runRecallExpression("1 << 100000", [])

    def test_rendering_does_not_materialize_unbounded_repr(self):
        items = [{"content": "x" * 1000} for _ in range(100)]
        with pytest.raises(RecallExpressionError, match="字符串"):
            runRecallExpression("str(items)", items)

    def test_format_width_is_checked_before_allocation(self, monkeypatch):
        from neurova.tools import recall_expression

        def forbiddenFormat(value, spec):
            raise RuntimeError("FORMAT_CALLED")

        monkeypatch.setattr(recall_expression, "format", forbiddenFormat, raising=False)
        with pytest.raises(RecallExpressionError, match="字符串"):
            runRecallExpression("f'{0:>1000000000}'", [])

    def test_expandtabs_width_is_checked_before_allocation(self):
        with pytest.raises(RecallExpressionError, match="字符串"):
            runRecallExpression(
                "('\\t'*20000).expandtabs(10000000000000000000000000000000000000000)", [])

    def test_nested_container_allocations_share_one_budget(self):
        with pytest.raises(RecallExpressionError, match="容器"):
            runRecallExpression("[[0]*2000 for _ in [0]*2000]", [])

    def test_type_membership_does_not_execute_metaclass_equality(self):
        called = []

        class CountingMeta(type):
            def __eq__(cls, other):
                called.append(other)
                return False

        class CustomValue(metaclass=CountingMeta):
            pass

        with pytest.raises(RecallExpressionError, match="类型"):
            runRecallExpression("items[0]", [CustomValue()])
        assert called == []

    def test_stringify_charges_cumulative_output_budget(self, monkeypatch):
        from neurova.tools import recall_expression

        monkeypatch.setattr(recall_expression, "MAX_TOTAL_STRING_CHARS", 1000)
        with pytest.raises(RecallExpressionError, match="字符串"):
            runRecallExpression(
                "(a:=b'x'*100,list(map(str,[a]*100)))", [])

    def test_sum_charges_cumulative_container_allocations(self, monkeypatch):
        from neurova.tools import recall_expression

        monkeypatch.setattr(recall_expression, "MAX_TOTAL_CONTAINER_ITEMS", 25000)
        with pytest.raises(RecallExpressionError, match="容器"):
            runRecallExpression(
                "(a:=[0]*10000,[sum([a],[]) for _ in [0]*2])", [])

    def test_sum_charges_cumulative_bytes_allocations(self, monkeypatch):
        from neurova.tools import recall_expression

        monkeypatch.setattr(recall_expression, "MAX_TOTAL_STRING_CHARS", 25000)
        with pytest.raises(RecallExpressionError, match="字符串"):
            runRecallExpression(
                "(a:=b'x'*10000,[sum([a],b'') for _ in [0]*2])", [])

    def test_startswith_tuple_cannot_expand_structural_comparisons(self):
        with pytest.raises(RecallExpressionError, match="结构"):
            runRecallExpression(
                "(lambda p,r:r.startswith((p,)*200))('a'*19999+'b','a'*20000)", [])

    def test_positional_only_lambda_rejects_keyword_binding(self):
        with pytest.raises(RecallExpressionError, match="位置专用"):
            runRecallExpression("(lambda x,/:x)(x=1)", [])
        assert runRecallExpression("(lambda x,/:x)(1)", []) == "1"
        assert runRecallExpression("(lambda x,/,y:x+y)(1,y=2)", []) == "3"

    @pytest.mark.parametrize("operation", [
        "{(c,)*100}",
        "set([(c,)*100])",
        "{(c,)*100: 1}",
        "{(c,)*100: 1}.get((f,)*100)",
        "{(c,)*100: 1}[(f,)*100]",
        "c == f",
        "c < f",
        "c in [f]*100",
        "[c].count(f)",
        "(c,).index(f)",
        "sorted([c,f])",
        "min(c,f)",
        "{c}.union([f])",
        "{c}.issubset([f])",
    ])
    def test_structural_operations_cannot_expand_shared_containers(
            self, monkeypatch, operation):
        from neurova.tools import recall_expression

        monkeypatch.setattr(recall_expression, "MAX_STRUCTURAL_VISITS", 400,
                            raising=False)
        setup = (
            "(a:=(0,),b:=(a,)*10,c:=(b,)*10,d:=(0,),e:=(d,)*10,"
            "f:=(e,)*10,")
        with pytest.raises(RecallExpressionError, match="结构"):
            runRecallExpression(setup + operation + ")", [])

    @pytest.mark.parametrize("operation", [
        "{(c,)*10: i for i in [0]*100}",
        "{(c,)*10 for i in [0]*100}",
        "dict([((c,)*10,0)]*100)",
    ])
    def test_hash_container_builders_share_structural_budget(self, operation):
        setup = "(a:=(0,),b:=(a,)*10,c:=(b,)*10,"
        with pytest.raises(RecallExpressionError, match="结构"):
            runRecallExpression(setup + operation + ")", [])

    def test_walrus_inside_comprehension_binds_outer_scope(self):
        assert runRecallExpression("([(x:=i) for i in items],x)", [1, 2, 3]) == "([1, 2, 3], 3)"

    def test_bytes_percent_formatting_is_rejected_before_allocation(self):
        with pytest.raises(RecallExpressionError, match="格式化"):
            runRecallExpression("b'%100000000000000000000s' % b'x'", [])

    def test_round_rejects_unbounded_negative_precision(self):
        with pytest.raises(RecallExpressionError, match="round"):
            runRecallExpression("round(1, -1000000)", [])

    def test_custom_projection_objects_cannot_execute_format(self):
        called = []

        class CustomValue:
            def __format__(self, spec):
                called.append(spec)
                return "x"

        with pytest.raises(RecallExpressionError, match="类型"):
            runRecallExpression("f'{items[0]:>2}'", [CustomValue()])
        assert called == []

    def test_iterated_projection_objects_cannot_execute_bool(self):
        called = []

        class CustomValue:
            def __bool__(self):
                called.append(True)
                return True

        with pytest.raises(RecallExpressionError, match="类型"):
            runRecallExpression("any(items[0].values())", [{"x": CustomValue()}])
        assert called == []

    def test_nested_projection_objects_cannot_execute_equality(self):
        called = []

        class CustomValue:
            def __eq__(self, other):
                called.append(True)
                return True

        with pytest.raises(RecallExpressionError, match="类型"):
            runRecallExpression("items[0] == items[1]", [
                {"x": CustomValue()}, {"x": CustomValue()}])
        assert called == []

    def test_nested_long_string_is_rejected_before_repr_copy(self, monkeypatch):
        from neurova.tools import recall_expression

        originalRepr = repr
        seen = []

        def trackingRepr(value):
            if isinstance(value, (str, bytes)):
                seen.append(len(value))
            return originalRepr(value)

        monkeypatch.setattr(recall_expression, "repr", trackingRepr, raising=False)
        with pytest.raises(RecallExpressionError, match="字符串"):
            runRecallExpression("str(items)", [{"content": "x" * 100000}])
        assert seen == []

    def test_string_case_conversion_charges_actual_output(self):
        result = runRecallExpression("('a'*10000).lower()", [])
        assert result.startswith("a" * 100)

    def test_custom_class_hook_is_not_executed(self):
        called = []

        class CustomValue:
            @property
            def __class__(self):
                called.append(True)
                return str

        with pytest.raises(RecallExpressionError, match="类型"):
            runRecallExpression("items[0]", [CustomValue()])
        assert called == []

    def test_subscript_slices_share_string_budget(self):
        with pytest.raises(RecallExpressionError, match="字符串"):
            runRecallExpression(
                "[items[0]['content'][1:] for _ in [0]*200]",
                [{"content": "x" * 20000}])

    def test_set_methods_cannot_bypass_iteration_budget(self):
        values = {str(index): index for index in range(20000)}
        with pytest.raises(RecallExpressionError, match="迭代"):
            runRecallExpression("{0}.isdisjoint(items[0].values())", [values])

    @pytest.mark.parametrize("expression", [
        "[items[0]['content'].partition('y') for _ in [0]*100]",
        "[items[0]['content'].split('y') for _ in [0]*100]",
    ])
    def test_string_splitting_charges_nested_output(self, expression):
        with pytest.raises(RecallExpressionError, match="字符串"):
            runRecallExpression(expression, [{"content": "x" * 10000}])

    def test_split_accepts_sep_keyword(self):
        assert runRecallExpression("'a,b'.split(sep=',')", []) == "['a', 'b']"

    def test_pure_methods_lambdas_and_comprehensions_keep_working(self):
        expression = "list(map(lambda i: i['turn_id'], filter(lambda i: '成功' in i['content'], items)))"
        assert runRecallExpression(expression, ITEMS) == "['t2']"
        assert runRecallExpression("{i['turn_id']: len(i['content']) for i in items}", ITEMS).startswith("{'t1':")
        assert runRecallExpression("f\"{len(items)}:{items[0]['turn_id']}\"", ITEMS) == "3:t1"
        assert runRecallExpression("(n:=len(items), n+1)", ITEMS) == "(3, 4)"
        assert runRecallExpression("str()", ITEMS) == ""
        assert runRecallExpression("bool()", ITEMS) == "False"
        assert runRecallExpression("str(b'ab', 'utf-8')", ITEMS) == "ab"
        assert runRecallExpression("list(map(lambda a,b: a+b, [1,2], [10,20]))", ITEMS) == "[11, 22]"


class TestRegistration:

    def test_schema_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert "recall_query" in _BUILTIN_SCHEMAS

    def test_dispatch_registered(self):
        from neurova.tool_executor import ToolExecutor

        assert ToolExecutor._builtin_dispatch["recall_query"] == "_execute_recall_query"


class TestHandler:

    def _executor_with_pool(self, recalled):
        stub_pool = SimpleNamespace(recall_evicted=lambda query, limit: recalled)
        stub_agent = SimpleNamespace(
            context_orchestrator=SimpleNamespace(context_pool=stub_pool))
        from neurova.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)  # 跳过重装配；只挂本用例需要的引用
        executor._agent = stub_agent
        return executor

    def test_handler_end_to_end(self):
        recalled = [SimpleNamespace(content=c, metadata={"turn_id": t, "recalled_from": "memory_ledger"})
                    for c, t in [("部署失败", "t1"), ("部署成功", "t2")]]
        executor = self._executor_with_pool(recalled)
        result = asyncio.run(executor._execute_recall_query(
            {"expression": "[i['content'] for i in items]", "query": "部署"}))
        assert result["success"] is True and result["count"] == 2
        assert "部署失败" in result["result"]

    def test_handler_requires_pool(self):
        from neurova.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)
        executor._agent = SimpleNamespace(context_orchestrator=None)
        result = asyncio.run(executor._execute_recall_query({"expression": "len(items)"}))
        assert "上下文池不可用" in result["error"]

    def test_handler_surfaces_expression_errors(self):
        recalled = [SimpleNamespace(content="x", metadata={})]
        executor = self._executor_with_pool(recalled)
        result = asyncio.run(executor._execute_recall_query(
            {"expression": "__import__('os')"}))
        assert "error" in result
