"""
遗留 C — exec_merge strategy 语义测试

契约（builtin.exec_merge）：
- 收集所有入边上游的 output（现状保留）
- strategy="all"（默认）：所有上游 output 真值才 success，否则 status="waiting"（等待剩余上游）
- strategy="any"：任一上游 output 真值即 success
- 非字典结果/无 output 的上游不参与判定
"""
import pytest

from neurova.collaboration.neurflow.builtin import exec_merge


def _ctx(results):
    return {"node_results": results}


class TestExecMergeStrategy:
    @pytest.mark.asyncio
    async def test_default_all_success_when_all_upstream_truthy(self):
        ctx = _ctx({
            "a": {"status": "success", "output": {"x": 1}},
            "b": {"status": "success", "output": {"y": 2}},
        })
        ctx["expected_upstream"] = ["a", "b"]
        out = await exec_merge({"strategy": "all"}, ctx)
        assert out["status"] == "success"
        assert out["output"] == {"a": {"x": 1}, "b": {"y": 2}}

    @pytest.mark.asyncio
    async def test_all_waits_when_an_upstream_missing(self):
        """all 策略：期望上游 b 尚未产出 → waiting，不提前合并"""
        ctx = _ctx({
            "a": {"status": "success", "output": {"x": 1}},
            # b 尚未执行
        })
        ctx["expected_upstream"] = ["a", "b"]
        out = await exec_merge({"strategy": "all"}, ctx)
        assert out["status"] == "waiting"
        assert out["output"] == {"a": {"x": 1}}

    @pytest.mark.asyncio
    async def test_any_succeeds_on_first_truthy(self):
        ctx = _ctx({
            "a": {"status": "success", "output": {"x": 1}},
            # b 未产出
        })
        ctx["expected_upstream"] = ["a", "b"]
        out = await exec_merge({"strategy": "any"}, ctx)
        assert out["status"] == "success"
        assert out["output"] == {"a": {"x": 1}}

    @pytest.mark.asyncio
    async def test_any_waits_when_nothing_yet(self):
        ctx = _ctx({})
        ctx["expected_upstream"] = ["a"]
        out = await exec_merge({"strategy": "any"}, ctx)
        assert out["status"] == "waiting"

    @pytest.mark.asyncio
    async def test_non_dict_results_ignored(self):
        ctx = _ctx({
            "bad": "not-a-dict",
            "a": {"status": "success", "output": 42},
        })
        ctx["expected_upstream"] = ["a"]
        out = await exec_merge({"strategy": "any"}, ctx)
        assert out["status"] == "success"
        assert out["output"] == {"a": 42}

    @pytest.mark.asyncio
    async def test_no_expected_upstream_falls_back(self):
        """无注入（如单测直接构造）时 any=有产出即过，all=空则 waiting"""
        out = await exec_merge({"strategy": "any"}, _ctx({
            "a": {"status": "success", "output": 1},
        }))
        assert out["status"] == "success"