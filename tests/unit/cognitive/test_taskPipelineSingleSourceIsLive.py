"""任务编排的单点活路核验（序 6 甲方案余下半 · 丙′ 裁定）。

台账 §6-135 把 `neurova/cognitive` 包内那只编排器判为「全仓唯一实装 ⇒ 需人裁」，
比对象只选了同名近邻 `core/cognition_orchestrator.py`。本档把比对象换成**真正在服务
请求的那条路**（NeurFlow：节点注册表 + `WorkflowExecutor` + 团队 Agent 管理 + 执行实例
落盘），逐格实测后才动旧件——丙′ 的前置「先把任务编排做成真能力」由此判定成立与否。

判据分两面，缺一面都不算闭环：
- 活路面（今天就得绿）：流水线节点**真被 await**、执行器解析不到时**不报成功**、
  代理注册表与执行实例的读写面在位。这是"替代存在"之外的"替代等价"证据。
- 退役面（今天红）：旧件还在位、还被当模板引用 ⇒ 红。删净后转绿。
反向断言（`TestSubstitutesMustStay`）钉住"不许把活路一起删掉来买绿"。
"""

import ast
import asyncio
import importlib
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
LIVE_ENGINE = REPO / "neurova" / "collaboration" / "neurflow" / "execution_engine.py"
LIVE_AGENTS = REPO / "neurova" / "collaboration" / "neurflow" / "agent_manager.py"
LIVE_STORAGE = REPO / "neurova" / "collaboration" / "neurflow" / "storage.py"
# 旧件按段拼出，避免本档自己成为一条"引用退役路径"的命中点
FAKE_FILE = REPO.joinpath(*("neurova cognitive orchestrator.py".split()))
FAKE_MODULE = ".".join(("neurova", "cognitive", "orchestrator"))
PROBE_TYPE = "probe:echoOnce"


def _buildWorkflow(node_type: str) -> "object":
    from neurova.collaboration.neurflow.models import (
        WorkflowDefinition,
        WorkflowEdge,
        WorkflowNode,
        WorkflowStatus,
    )

    return WorkflowDefinition(
        id="wf_single_source_probe",
        name="单点活路核验",
        description="证明节点执行器真被 await",
        version="1.0.0",
        nodes=[
            WorkflowNode(id="n_start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="n_probe", type=node_type, position={"x": 200, "y": 0}, config={"text": "hi"}),
            WorkflowNode(id="n_end", type="builtin:end", position={"x": 400, "y": 0}, config={}),
        ],
        edges=[
            WorkflowEdge(id="e1", source="n_start", target="n_probe"),
            WorkflowEdge(id="e2", source="n_probe", target="n_end"),
        ],
        variables=[],
        tags=["probe"],
        category="test",
        author="guard",
        created_at=0.0,
        updated_at=0.0,
        status=WorkflowStatus.PUBLISHED,
    )


@pytest.fixture()
def liveRegistry():
    """真注册表 + 真单例，用完摘干净——不让探针节点漏进后续跑测。"""
    from neurova.collaboration.neurflow.node_registry import get_node_registry, reset_node_registry

    reset_node_registry()
    registry = get_node_registry()
    registry.ensure_builtin()
    yield registry
    registry.unregister(PROBE_TYPE)
    reset_node_registry()


class TestLivePipelineReallyExecutes:
    def test_registeredNodeExecutorIsAwaited(self, liveRegistry):
        """跑一条三步流水线：中间那步的执行器必须**真被 await**，其返回值必须落进节点结果。

        这是旧件 `orchestrate()` 缺的那格——它给每一步直接写 "completed"，
        仓里没有任何一只 handler 被调用过。
        """
        from neurova.collaboration.neurflow.execution_engine import get_workflow_executor
        from neurova.collaboration.neurflow.models import NodeDefinition, WorkflowStatus

        calls = []

        async def _echo(config, context):
            calls.append(dict(config))
            return {"output": "echoed:" + str(config.get("text", ""))}

        liveRegistry.register(
            NodeDefinition(
                type=PROBE_TYPE,
                label="探针回显",
                icon="🧪",
                category="tools",
                description="核验执行器真被 await",
                sub_blocks=[],
                inputs=[],
                outputs=[],
            ),
            _echo,
        )

        instance = asyncio.run(
            get_workflow_executor().execute(_buildWorkflow(PROBE_TYPE), inputs={"topic": "t"})
        )

        assert len(calls) == 1, f"注册的执行器一次都没被调用（calls={calls}）"
        assert calls[0].get("text") == "hi", "传给执行器的 config 不是解析后的节点配置"
        probe = instance.node_results.get("n_probe")
        assert probe is not None and probe.status == "success"
        assert probe.output == "echoed:hi", f"执行器返回值未落进节点结果：{probe.output!r}"
        assert instance.status == WorkflowStatus.COMPLETED, instance.error

    def test_unresolvableNodeTypeNeverReportsSuccess(self, liveRegistry):
        """解析不到执行器的节点**不得**被记成 success——终态必须是失败且带原因。

        旧件那侧的对照事实：任何一步都直接 "completed"，原因字段永远是 None。
        """
        from neurova.collaboration.neurflow.execution_engine import get_workflow_executor
        from neurova.collaboration.neurflow.models import WorkflowStatus

        instance = asyncio.run(
            get_workflow_executor().execute(_buildWorkflow("probe:doesNotExist"), inputs={})
        )

        assert instance.status == WorkflowStatus.FAILED, (
            f"未注册执行器的节点被判成 {instance.status.value}——等于谎报完成"
        )
        assert instance.status != WorkflowStatus.COMPLETED
        probe = instance.node_results.get("n_probe")
        if probe is not None:
            assert probe.status != "success"
            assert probe.error, "失败节点必须留下原因"
        else:
            assert instance.error, "在工作流校验阶段就被拒绝时，实例必须带原因"


class TestFakePipelineFaceRetired:
    def test_legacyFakeOrchestratorIsGone(self):
        """旧件（自称任务流水线、实际只写状态）必须退役，且不可 import。"""
        assert not FAKE_FILE.exists(), f"旧件仍在位：{FAKE_FILE}"
        sys.modules.pop(FAKE_MODULE, None)
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(FAKE_MODULE)

    def test_noCodeCitesTheRetiredFace(self):
        """没有任何生产/测试/脚本代码再把它当实现或"DCL 修复模板"引用。

        引用不存在的落点当模板，正是 §6-116 那条悬空红 18 天的形态。
        """
        needles = (str(FAKE_FILE.relative_to(REPO)).replace("\\", "/"), FAKE_MODULE)
        hits = []
        for root in ("neurova", "tests", "scripts"):
            for path in (REPO / root).rglob("*.py"):
                if "__pycache__" in path.parts or path == pathlib.Path(__file__).resolve():
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                if any(needle in text for needle in needles):
                    hits.append(str(path.relative_to(REPO)))
        assert hits == [], f"退役路径仍被引用：{sorted(hits)}"


class TestSubstitutesMustStay:
    """反向断言：判据不许靠"把顶上那条路也删了"转绿。"""

    def test_liveFacesAreInPlace(self):
        for path in (LIVE_ENGINE, LIVE_AGENTS, LIVE_STORAGE):
            assert path.exists(), f"顶替旧件的那条活路消失了：{path}"

        from neurova.collaboration.neurflow.agent_manager import NeurflowAgentManager
        from neurova.collaboration.neurflow.models import AgentInfo

        for face in ("create_agent", "list_agents", "archive_agent"):
            assert callable(getattr(NeurflowAgentManager, face, None)), f"代理注册表少了 {face}"
        assert "capabilities" in {f.name for f in _dataclassFields(AgentInfo)}, (
            "旧件注册表的 capabilities 格在活路里没有落点"
        )

    def test_liveDispatchIsReallyAwaited(self):
        """按 AST 核：活路的 `_execute_node` 里必须存在"await 注册表解析出的执行器"。

        只断"函数存在"是形状检查；本档要的是派发面真的异步调用出去。
        """
        tree = ast.parse(LIVE_ENGINE.read_text(encoding="utf-8"))
        fn = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_execute_node"),
            None,
        )
        assert fn is not None, "活路的节点执行函数不在了"
        awaited_calls = {
            n.value.func.id
            for n in ast.walk(fn)
            if isinstance(n, ast.Await) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
        }
        assert "executor" in awaited_calls, f"_execute_node 不再 await 解析出的执行器：{sorted(awaited_calls)}"

    def test_executionInstancesPersist(self):
        """旧件的"三态落盘"由活路的执行实例读写顶替：写侧与读侧都得在。"""
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        for face in ("save_execution", "get_execution"):
            assert callable(getattr(NeurflowStorage, face, None)), f"执行实例持久化少了 {face}"

    def test_thisJudgmentKeepsItsLiveFaces(self):
        """本档自身也在守卫面上：摘掉活路那两格判据＝本条红。"""
        text = pathlib.Path(__file__).read_text(encoding="utf-8")
        for grade in ("test_registeredNodeExecutorIsAwaited", "test_unresolvableNodeTypeNeverReportsSuccess"):
            assert f"def {grade}(" in text, f"核验活路的判据被摘掉：{grade}"


def _dataclassFields(cls):
    import dataclasses

    return dataclasses.fields(cls) if dataclasses.is_dataclass(cls) else ()
