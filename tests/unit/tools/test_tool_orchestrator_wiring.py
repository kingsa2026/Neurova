"""接线 ToolOrchestrator：DAG 编排必须有真实生产消费方，且判据咬合真实面。

背景（根因，不是形状）：`neurova/tool_layers/tool_orchestrator.py` 此前是**零消费方死链**——
`agent_core.py` 建了实例、装了执行器，但全仓生产侧**没有任何地方**调用
`orchestrate()` / `build_plan_from_goal()`。协作红线明令「注册无消费者的模块」是断点形态，
003 票面自己写着「它本身是零调用方死链，本票不扩面（另票再议）」，而那张另票一直不存在。

接线时先把三处**假面**钉死，否则接上去的是一条必然失败的通路：

1. **假工具名**：默认能力图里的 `code_execute` / `data_process` / `memory_save` /
   `code_analyze` **都不是真实内置工具**（真实名是 `run_code` 等），
   于是 `build_plan_from_goal` 产出的计划里混着永远「未知工具」的步进——
   能力图成了工具清单的**第二份定义**（教义第 6 条禁）。
2. **假兜底**：目标解析不出来时兜底成 `process_data`，把「读不懂目标」静默变成
   「跑一个无关工具」，与教义第 2 条「报错要么根修要么诚实形态暴露」相反。
3. **假成败**：`_execute_step` 只要不抛异常就记 COMPLETED，执行器已声明的
   `{"success": False}` / `{"error": …}` 一律被抹成成功——同契约的成败判据分叉。

替身只放**工具边界**（`executor.execute` 的返回值），编排、分层、并发、成败与
工具面接线全走真代码。
"""

from __future__ import annotations

import ast
import asyncio
import io
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from neurova.builtin_tools import _BUILTIN_SCHEMAS
from neurova.tool_layers.capability_graph import ToolCapabilityGraph
from neurova.tool_layers.tool_orchestrator import ToolOrchestrator
from neurova.tool_executor import ToolExecutor

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR_PATH = REPO_ROOT / "neurova" / "tool_layers" / "tool_orchestrator.py"


class _ToolBoundary:
    """工具边界替身：记录每次调用并按脚本返回（替身只在工具边界，不上移到编排）。"""

    def __init__(self, results: Dict[str, Any] = None, delay: float = 0.0) -> None:
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self._results = results or {}
        self._delay = delay
        self.high_water = 0
        self._live = 0

    async def execute(self, tool_name: str, params: Dict[str, Any]) -> Any:
        self.calls.append((tool_name, dict(params or {})))
        self._live += 1
        self.high_water = max(self.high_water, self._live)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            payload = self._results.get(tool_name, {})
            return payload() if callable(payload) else payload
        finally:
            self._live -= 1


def _phantomCarriers(graph: ToolCapabilityGraph, registered) -> List[str]:
    """能力图里点名的、注册表里并不存在的工具名（判据本体，纯函数）。"""
    return sorted(set(graph.nodes) - set(registered))


# ---------------------------------------------------------------------------
# 判据一：能力图的工具名必须是真实工具（工具清单单一事实源）
# ---------------------------------------------------------------------------


class TestCapabilityCarriersAreRealTools:
    def test_default_graph_names_are_registered_builtins(self):
        phantoms = _phantomCarriers(ToolCapabilityGraph(), _BUILTIN_SCHEMAS)
        assert phantoms == [], (
            "默认能力图点名了不存在的工具——能力图成了工具清单的第二份定义，"
            "据此产出的执行计划里每一步都是「未知工具」:\n  " + "\n  ".join(phantoms)
        )

    @pytest.mark.parametrize(
        "goal",
        ["read the file", "search the web", "run a script", "read the file and search the web"],
    )
    def test_goal_plan_only_names_real_tools(self, goal):
        plan = ToolOrchestrator().build_plan_from_goal(goal)
        unknown = [name for name in plan if name not in _BUILTIN_SCHEMAS]
        assert plan, f"目标 {goal!r} 解析不出计划——能力图与解析口径已经脱节"
        assert unknown == [], f"目标 {goal!r} 的计划里混着不存在的工具：{unknown}"

    def test_carrier_criterion_flags_phantom_name(self):
        """反向控制：判据必须真的抓得住幻影名（合成输入，不看仓库现状）。"""
        graph = ToolCapabilityGraph()
        graph.register_tool("code_execute", capabilities=["run_code"])
        assert "code_execute" in _phantomCarriers(graph, _BUILTIN_SCHEMAS)
        assert _phantomCarriers(ToolCapabilityGraph(), _BUILTIN_SCHEMAS) == []


# ---------------------------------------------------------------------------
# 判据二：读不懂目标时诚实弃权，不制造「跑个无关工具」的假计划
# ---------------------------------------------------------------------------


class TestUnknownGoalAbstains:
    def test_unknown_goal_yields_no_plan(self):
        orchestrator = ToolOrchestrator()
        assert orchestrator.build_plan_from_goal("do something unknown") == []

    @pytest.mark.asyncio
    async def test_unknown_goal_orchestration_fails_with_named_reason(self):
        orchestrator = ToolOrchestrator()
        boundary = _ToolBoundary()
        orchestrator.set_executor(boundary.execute)

        result = await orchestrator.orchestrate("do something unknown")

        assert result.status.value == "failed"
        assert result.error, "读不懂目标必须点名原因，不许静默产出空结果"
        assert boundary.calls == [], "没有可执行计划时不得调用任何工具"

    def test_abstain_criterion_is_not_vacuous(self):
        """反向控制：可解析的目标必须仍产出计划（弃权不是把整条臂关掉）。"""
        assert ToolOrchestrator().build_plan_from_goal("read the file") != []


# ---------------------------------------------------------------------------
# 判据三：步进参数与依赖（真实消费方必须能传参数、能声明依赖）
# ---------------------------------------------------------------------------


class TestPlanStepsCarryParamsAndDeps:
    @pytest.mark.asyncio
    async def test_step_params_reach_the_executor(self):
        orchestrator = ToolOrchestrator()
        boundary = _ToolBoundary()
        orchestrator.set_executor(boundary.execute)

        result = await orchestrator.orchestrate(
            "explicit plan",
            tool_plan=[
                {"tool": "file_read", "params": {"file_path": "a.txt"}},
                {"tool": "file_write", "params": {"file_path": "b.txt", "content": "x"}},
            ],
        )

        assert result.status.value == "completed"
        assert [name for name, _ in boundary.calls] == ["file_read", "file_write"]
        assert boundary.calls[0][1] == {"file_path": "a.txt"}
        assert boundary.calls[1][1] == {"file_path": "b.txt", "content": "x"}

    @pytest.mark.asyncio
    async def test_explicit_depends_on_gates_order(self):
        orchestrator = ToolOrchestrator()
        boundary = _ToolBoundary()
        orchestrator.set_executor(boundary.execute)

        await orchestrator.orchestrate(
            "declared deps",
            tool_plan=[
                {"tool": "calculator", "params": {"expression": "1+1"}, "depends_on": ["get_datetime"]},
                {"tool": "get_datetime", "params": {}},
            ],
        )

        assert [name for name, _ in boundary.calls] == ["get_datetime", "calculator"], (
            "显式声明的 depends_on 没被分层采纳——反向书写的计划会以错的顺序执行"
        )

    @pytest.mark.asyncio
    async def test_dependencies_outside_the_plan_do_not_stall(self):
        """图依赖落在计划外时不得让步进卡到「无法解析依赖」的兜底层。"""
        orchestrator = ToolOrchestrator()
        boundary = _ToolBoundary()
        orchestrator.set_executor(boundary.execute)

        # web_fetch 在默认图里依赖 web_search，但本计划只点名 web_fetch
        result = await orchestrator.orchestrate(
            "single step", tool_plan=[{"tool": "web_fetch", "params": {"url": "https://e.com"}}]
        )

        layers = orchestrator._partition_plan_into_layers(
            orchestrator.normalize_steps([{"tool": "web_fetch", "params": {}}])
        )
        assert result.status.value == "completed"
        assert [name for name, _ in boundary.calls] == ["web_fetch"]
        assert len(layers) == 1, f"计划外依赖把单步计划拖成多层：{layers}"

    @pytest.mark.asyncio
    async def test_step_placeholder_reads_previous_output(self):
        """`{step_<idx>.<field>}` 占位符必须真的被渲染——schema 承诺了它。"""
        orchestrator = ToolOrchestrator()
        boundary = _ToolBoundary({"get_datetime": {"datetime": "2026-09-23"}})
        orchestrator.set_executor(boundary.execute)

        await orchestrator.orchestrate(
            "placeholder",
            tool_plan=[
                {"tool": "get_datetime", "params": {}},
                {
                    "tool": "file_write",
                    "params": {"file_path": "x.txt", "content": "{step_0.datetime}"},
                    "depends_on": ["get_datetime"],
                },
            ],
        )

        assert boundary.calls[1][1]["content"] == "2026-09-23", (
            f"占位符没被渲染：{boundary.calls[1][1]}"
        )

    @pytest.mark.asyncio
    async def test_string_plan_still_supported(self):
        """向后兼容：纯工具名列表（既有调用形态）继续可用。"""
        orchestrator = ToolOrchestrator()
        boundary = _ToolBoundary()
        orchestrator.set_executor(boundary.execute)

        result = await orchestrator.orchestrate("legacy", tool_plan=["get_datetime"])
        assert result.status.value == "completed"
        assert [name for name, _ in boundary.calls] == ["get_datetime"]


# ---------------------------------------------------------------------------
# 判据四：成败判据单源（执行器声明的失败不许被抹成成功）
# ---------------------------------------------------------------------------


class TestStepVerdictFollowsExecutorDeclaration:
    @pytest.mark.asyncio
    async def test_error_payload_is_a_failed_step(self):
        orchestrator = ToolOrchestrator()
        boundary = _ToolBoundary({"calculator": {"error": "表达式无法计算"}})
        orchestrator.set_executor(boundary.execute)

        result = await orchestrator.orchestrate("boom", tool_plan=["calculator"])

        assert result.steps[0].status.value == "failed"
        assert result.status.value == "failed", "步进真失败，整体却报成功"

    @pytest.mark.asyncio
    async def test_declared_success_false_is_a_failed_step(self):
        orchestrator = ToolOrchestrator()
        boundary = _ToolBoundary({"calculator": {"success": False, "error": "上游超时"}})
        orchestrator.set_executor(boundary.execute)

        result = await orchestrator.orchestrate("boom", tool_plan=["calculator"])
        assert result.steps[0].status.value == "failed"

    @pytest.mark.asyncio
    async def test_background_envelope_is_not_completed(self):
        """超时转后台的步进是「未完成」，不许记成 COMPLETED。"""
        orchestrator = ToolOrchestrator()
        boundary = _ToolBoundary({"web_search": {"status": "background", "task_id": "bg_1"}})
        orchestrator.set_executor(boundary.execute)

        result = await orchestrator.orchestrate("slow", tool_plan=["web_search"])

        assert result.steps[0].status.value != "completed"
        assert result.status.value == "failed"

    @pytest.mark.asyncio
    async def test_verdict_criterion_is_not_vacuous(self):
        """反向控制：正常载荷必须仍是 completed，收紧不是把整条臂判红。"""
        orchestrator = ToolOrchestrator()
        boundary = _ToolBoundary({"calculator": {"result": 2}})
        orchestrator.set_executor(boundary.execute)

        result = await orchestrator.orchestrate("ok", tool_plan=["calculator"])
        assert result.steps[0].status.value == "completed"
        assert result.status.value == "completed"


# ---------------------------------------------------------------------------
# 判据五：上游失败后，下游步进以 SKIPPED 显式暴露（不是静默缺席、不是假成功）
# ---------------------------------------------------------------------------


class TestFailedLayerSkipsDownstream:
    @pytest.mark.asyncio
    async def test_downstream_steps_are_marked_skipped(self):
        orchestrator = ToolOrchestrator()
        boundary = _ToolBoundary({"file_read": {"error": "文件不存在"}})
        orchestrator.set_executor(boundary.execute)

        result = await orchestrator.orchestrate(
            "chain",
            tool_plan=[
                {"tool": "file_read", "params": {}},
                {"tool": "calculator", "params": {"expression": "1+1"}, "depends_on": ["file_read"]},
            ],
        )

        by_tool = {step.tool_name: step.status.value for step in result.steps}
        assert by_tool["file_read"] == "failed"
        assert by_tool["calculator"] == "skipped", (
            f"上游失败的依赖步进没有被显式标注，读者分不清「没跑」与「跑成功了」：{by_tool}"
        )
        assert [name for name, _ in boundary.calls] == ["file_read"], (
            "上游已失败，下游步进仍被执行"
        )
        assert result.status.value == "failed"


# ---------------------------------------------------------------------------
# 判据六：并行上限必须真的生效（`_max_parallel` 被读，不只被写）
# ---------------------------------------------------------------------------


class TestMaxParallelIsEnforced:
    @pytest.mark.asyncio
    async def test_parallel_layer_respects_max_parallel(self):
        orchestrator = ToolOrchestrator()
        orchestrator._max_parallel = 3
        boundary = _ToolBoundary(delay=0.05)
        orchestrator.set_executor(boundary.execute)

        plan = [{"tool": f"tool_{index}", "params": {}} for index in range(7)]
        result = await orchestrator.orchestrate("fan out", tool_plan=plan)

        assert result.status.value == "completed"
        assert len(boundary.calls) == 7
        assert boundary.high_water <= 3, (
            f"并发高水位 {boundary.high_water} 超过声明上限 3——上限只写不读"
        )

    @pytest.mark.asyncio
    async def test_cap_criterion_is_not_vacuous(self):
        """反向控制：上限以内确实并行（不是把并发关掉换来的绿灯）。"""
        orchestrator = ToolOrchestrator()
        orchestrator._max_parallel = 5
        boundary = _ToolBoundary(delay=0.05)
        orchestrator.set_executor(boundary.execute)

        plan = [{"tool": f"tool_{index}", "params": {}} for index in range(4)]
        await orchestrator.orchestrate("fan out", tool_plan=plan)
        assert boundary.high_water > 1, "层内没有并行，判据被并发关闭掩盖了"


# ---------------------------------------------------------------------------
# 判据七：死码不留（同一语义不许存在第二份实现）
# ---------------------------------------------------------------------------


class TestNoParallelPolicyDuplication:
    def test_unused_second_implementations_are_gone(self):
        source = io.open(ORCHESTRATOR_PATH, encoding="utf-8").read()
        tree = ast.parse(source)
        names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        leftovers = sorted({"can_run_in_parallel", "capability_to_dag"} & {
            name for name in names if name.startswith("_")
        })
        assert leftovers == [], (
            "依赖可达性/能力转 DAG 的旧实现仍留在文件里（分层已由 "
            f"_partition_plan_into_layers 一份承担）：{leftovers}"
        )


# ---------------------------------------------------------------------------
# 判据八：工具面接线（真实生产消费者）
# ---------------------------------------------------------------------------


def _probe_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EKB_DB", str(tmp_path / "experience_knowledge.db"))
    from neurova.skills.experience_knowledge_base import reset_experience_knowledge_base

    reset_experience_knowledge_base()
    from neurova.agent_core import Agent

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return Agent(
        name="OrchestratorProbe",
        agent_id="orchestrator-probe-01",
        workspace_path=str(workspace),
        enable_memory=False,
    )


class TestOrchestrateToolIsWired:
    def test_tool_registered_in_inventory_and_dispatch(self):
        assert "orchestrate_tools" in _BUILTIN_SCHEMAS, "编排工具没进工具清单，LLM 看不见它"
        schema = _BUILTIN_SCHEMAS["orchestrate_tools"]["parameters"]
        assert "steps" in schema["properties"]
        assert "goal" in schema["properties"]
        assert ToolExecutor._builtin_dispatch.get("orchestrate_tools"), (
            "有 schema 无执行体 = LLM 调用必返回「未知内置工具」"
        )

    def test_agent_wires_orchestrator_to_the_choke(self, tmp_path, monkeypatch):
        agent = _probe_agent(tmp_path, monkeypatch)
        assert agent.tool_orchestrator is not None, "Agent 上没有编排器实例"
        assert agent.tool_orchestrator._executor is not None, (
            "编排器没装执行器——接上去也只会返回 No executor configured"
        )

    def test_tool_face_runs_dag_through_the_choke(self, tmp_path, monkeypatch):
        agent = _probe_agent(tmp_path, monkeypatch)

        async def _run():
            from neurova.skills.creation_governance import (
                begin_task,
                flush_task,
                missing_context_count,
            )
            from neurova.skills.skill_service import SkillService

            before = missing_context_count()
            begin_task()
            payload = await agent.tool_executor.execute(
                "orchestrate_tools",
                {
                    "steps": [
                        {"tool": "get_datetime", "params": {}},
                        {
                            "tool": "calculator",
                            "params": {"expression": "6*7"},
                            "depends_on": ["get_datetime"],
                        },
                    ]
                },
            )
            service = SkillService(agent_id=agent.config.agent_id)
            record = flush_task(service, "多步编排", completed=True)
            return payload, record, before, missing_context_count()

        payload, record, before, after = asyncio.run(_run())

        assert ToolExecutor._result_is_success(payload), f"工具面编排没跑通：{payload}"
        assert [step["tool_name"] for step in payload["steps"]] == ["get_datetime", "calculator"]
        assert all(step["status"] == "completed" for step in payload["steps"])
        assert record is not None, "编排这一轮没有落下任何票据"
        assert [step["tool"] for step in record["steps"]] == [
            "get_datetime",
            "calculator",
            "orchestrate_tools",
        ], (
            "票据里没有两个内层步进——说明编排绕过了执行咽喉（票据/钩子/治理全丢）"
        )
        assert after == before, "本轮出现了未进证据账本的执行（漏采）"

    def test_tool_face_rejects_nested_orchestration(self, tmp_path, monkeypatch):
        agent = _probe_agent(tmp_path, monkeypatch)

        async def _run():
            return await agent.tool_executor.execute(
                "orchestrate_tools",
                {"steps": [{"tool": "orchestrate_tools", "params": {"steps": []}}]},
            )

        payload = asyncio.run(_run())
        assert ToolExecutor._result_is_success(payload) is False
        assert "orchestrate_tools" in str(payload.get("error", "")), (
            "自嵌套编排必须点名拒绝，不许静默执行或抛裸异常"
        )

    def test_tool_face_requires_steps_or_goal(self, tmp_path, monkeypatch):
        agent = _probe_agent(tmp_path, monkeypatch)

        async def _run(params):
            return await agent.tool_executor.execute("orchestrate_tools", params)

        empty = asyncio.run(_run({}))
        assert ToolExecutor._result_is_success(empty) is False
        assert "steps" in str(empty.get("error", "")) or "goal" in str(empty.get("error", ""))

        oversized = asyncio.run(
            _run({"steps": [{"tool": "get_datetime", "params": {}} for _ in range(64)]})
        )
        assert ToolExecutor._result_is_success(oversized) is False, (
            "步进数无上限——一次调用可以无限fan-out"
        )
