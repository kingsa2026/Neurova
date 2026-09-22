"""DAG 工具编排器。

职责：
- 从目标能力描述或显式步骤表构建 DAG 执行计划；
- 按拓扑顺序分层并行执行（层内并发受 `_max_parallel` 约束）；
- 上游失败时下游步进显式记 `SKIPPED`，不许静默缺席；
- 导出编排结果（状态 / 耗时 / 逐步骤详情）。

架构：
    用户目标 ──▶ CapabilityGraph ──▶ DAG 执行计划

生产消费方是工具面的 `orchestrate_tools` 内置工具（`ToolExecutor._execute_orchestrate_tools`）：
编排器本身不含执行能力，每一个步进都经执行咽喉（票据 / `on_tool_executed` / 治理预检 /
hooks / per-tool 超时全链生效）。编排器**不可重入**——嵌套编排在同一条执行链上会无限
自我递归，故以 ContextVar 记账并在入口拒绝。
"""

import asyncio
from contextvars import ContextVar
from neurova.core.logger import get_logger
import time
import typing
from dataclasses import dataclass, field

# tool_layers imports
from neurova.tool_layers.capability_graph import ToolCapabilityGraph
# ADR 0009: ExecutionStatus 单一规范定义位于 tool_layers.types
from neurova.tool_layers.types import ExecutionStatus

logger = get_logger(__name__)

#: 编排重入深度（单条执行链上的 ContextVar 记账）。
#: 嵌套编排会让编排器在内层再次调用自己，形成无界递归；这里只记「是否已在编排中」，
#: 不做并发上限——同一 agent 的两次独立对话互不影响（ContextVar 随任务上下文复制）。
_orchestrationDepth: ContextVar[int] = ContextVar("neurova_orchestration_depth", default=0)

#: 单次编排的步进上限（与工具面 schema 同源约束，防止一次调用无界 fan-out）。
MAX_ORCHESTRATION_STEPS = 12


@dataclass
class StepResult:
    """单步执行结果"""

    step_id: str
    tool_name: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    output: typing.Optional[typing.Dict[str, typing.Any]] = None
    duration_ms: float = 0.0
    error: typing.Optional[str] = None

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "output": self.output,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class OrchestrationResult:
    """编排结果"""

    goal: str
    status: ExecutionStatus
    steps: typing.List[StepResult] = field(default_factory=list)
    total_duration_ms: float = 0.0
    error: typing.Optional[str] = None

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "goal": self.goal,
            "status": self.status.value,
            "steps": [step.to_dict() for step in self.steps],
            "total_duration_ms": self.total_duration_ms,
            "error": self.error,
        }


class OrchestrationStep:
    """一步编排的声明（工具面上的最小单元）。

    只承载声明，不含执行状态；执行状态落在 `StepResult`。
    """

    def __init__(
        self,
        tool_name: str,
        params: typing.Optional[typing.Dict[str, typing.Any]] = None,
        depends_on: typing.Optional[typing.List[str]] = None,
    ) -> None:
        self.tool_name = tool_name
        self.params = dict(params or {})
        self.depends_on = list(depends_on or [])

    @classmethod
    def coerce(cls, raw: typing.Any) -> typing.Optional["OrchestrationStep"]:
        """把外部传入的步骤归一成 `OrchestrationStep`；不合法返回 None。

        接受两种既有形态：纯工具名（str）与 `{"tool": …, "params": …, "depends_on": …}`。
        不合法形态返回 None 而不是就地兜底——调用方据此点名拒绝。
        """
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, str):
            return cls(raw) if raw.strip() else None
        if not isinstance(raw, dict):
            return None
        tool_name = str(raw.get("tool") or raw.get("name") or "").strip()
        if not tool_name:
            return None
        params = raw.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return None
        depends = raw.get("depends_on")
        if depends is None:
            depends = []
        if isinstance(depends, str):
            depends = [depends]
        if not isinstance(depends, list):
            return None
        return cls(tool_name, params, [str(dep) for dep in depends])

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {"tool": self.tool_name, "params": self.params, "depends_on": self.depends_on}


class ToolOrchestrator:
    """DAG 工具编排器。

    功能：
    1. 从目标构建执行计划（能力图 → 承接工具）
    2. 按拓扑分层执行（层内并行，受 `_max_parallel` 约束）
    3. 上游失败时下游步进显式记 `SKIPPED`
    4. 成败判据单源（委托执行器的 `_result_is_success`）

    执行器由 `set_executor` 注入；生产上是工具面 `orchestrate_tools` 的委托对象。
    """

    def __init__(self, max_parallel: int = 5, step_timeout: float = 30.0):
        """初始化编排器

        参数:
            max_parallel: 层内并发上限
            step_timeout: 单步超时（秒）
        """
        self._executor = None
        self._capability_graph = ToolCapabilityGraph()
        self._step_timeout = float(step_timeout)
        self._max_parallel = max(1, int(max_parallel))

    def set_executor(self, executor: typing.Any) -> None:
        """设置工具执行器（接受纯 async 可调用，或暴露 `execute` 的对象）。"""
        self._executor = executor

    async def _invoke_executor(
        self, tool_name: str, params: typing.Dict[str, typing.Any]
    ) -> typing.Any:
        """调用执行器——两种形态在这里**一处**归一，不在上层分叉。

        形态一：`self._executor` 本身是可调用（生产形态，工具面委托的对象）；
        形态二：`self._executor` 暴露 `execute`（早期形态）。判据是「拿得出可调用的
        `execute` 就优先用它」——`unittest.mock.Mock` 本身可调用，先判可调用会把
        Mock 的自动属性当成真的执行体。
        """
        execute = getattr(self._executor, "execute", None)
        target = execute if callable(execute) else self._executor
        if not callable(target):
            raise TypeError("执行器既不可调用也不暴露 execute(tool_name, params)")
        outcome = target(tool_name, params)
        return await outcome if asyncio.iscoroutine(outcome) else outcome

    def is_orchestrating(self) -> bool:
        """当前执行链是否已在编排中（工具面据此拒绝自嵌套）。"""
        return _orchestrationDepth.get() > 0

    def build_plan_from_goal(self, goal: str) -> typing.List[str]:
        """从目标构建执行计划（工具名列表）。

        读不懂目标时返回**空表**——把「读不懂」静默换成一个无关工具，
        会让调用方把弃权当成一条已规划好的链路。
        """
        capabilities = self._resolve_goal_to_capabilities_sync(goal)
        if not capabilities:
            return []
        tools = self._capability_graph.tools_for_capabilities(capabilities)
        if not tools:
            return []
        return self._capability_graph.build_execution_plan(tools)

    def normalize_steps(self, raw_steps: typing.Any) -> typing.List[OrchestrationStep]:
        """归一外部步骤表；不合法即抛 `ValueError`（诚实形态，不静默丢弃）。"""
        if not isinstance(raw_steps, (list, tuple)):
            raise ValueError("steps 必须是列表")
        if not raw_steps:
            raise ValueError("steps 不能为空")
        if len(raw_steps) > MAX_ORCHESTRATION_STEPS:
            raise ValueError(
                f"steps 步进数 {len(raw_steps)} 超过上限 {MAX_ORCHESTRATION_STEPS}"
            )
        steps: typing.List[OrchestrationStep] = []
        for index, raw in enumerate(raw_steps):
            step = OrchestrationStep.coerce(raw)
            if step is None:
                raise ValueError(f"第 {index} 步格式错误：需要工具名或 {{tool, params, depends_on}} 形态")
            steps.append(step)
        return steps

    async def orchestrate(
        self,
        goal: str,
        context: typing.Optional[typing.Dict] = None,
        tool_plan: typing.Optional[typing.List] = None,
    ) -> OrchestrationResult:
        """编排执行。

        参数:
            goal: 用户目标（`tool_plan` 为 None 时用于构建计划）
            context: 执行上下文（并入每步 params 的 `_context`）
            tool_plan: 显式步骤表（工具名、或 `{tool, params, depends_on}`）

        返回:
            编排结果；读不懂目标/无可执行计划时 `FAILED` 且点名原因。
        """
        start_time = time.time()
        if self.is_orchestrating():
            return OrchestrationResult(
                goal=goal,
                status=ExecutionStatus.FAILED,
                error="嵌套编排被拒绝：编排器不可重入（同一条执行链上会无限递归）",
                total_duration_ms=(time.time() - start_time) * 1000,
            )

        try:
            steps = self._resolve_steps(goal, tool_plan)
        except ValueError as invalid:
            return OrchestrationResult(
                goal=goal,
                status=ExecutionStatus.FAILED,
                error=str(invalid),
                total_duration_ms=(time.time() - start_time) * 1000,
            )

        if not steps:
            return OrchestrationResult(
                goal=goal,
                status=ExecutionStatus.FAILED,
                error="No execution plan could be built from goal",
                total_duration_ms=(time.time() - start_time) * 1000,
            )

        token = _orchestrationDepth.set(_orchestrationDepth.get() + 1)
        self._step_outputs = {}
        try:
            layers = self._partition_plan_into_layers(steps)
            step_results: typing.List[StepResult] = []
            offset = 0
            blocked: typing.Set[str] = set()

            for layer in layers:
                runnable = [step for step in layer if not (blocked & set(step.depends_on))]
                skipped = [step for step in layer if step not in runnable]
                for step in skipped:
                    blocked.add(step.tool_name)
                    step_results.append(
                        StepResult(
                            step_id=f"step_{offset + layer.index(step)}",
                            tool_name=step.tool_name,
                            status=ExecutionStatus.SKIPPED,
                            error="上游依赖失败，本步未执行",
                        )
                    )
                if runnable:
                    layer_results = await self._execute_layer(
                        runnable, offset, context or {}
                    )
                    step_results.extend(layer_results)
                    for result in layer_results:
                        if result.status is not ExecutionStatus.COMPLETED:
                            blocked.add(result.tool_name)
                offset += len(layer)

            all_success = all(
                step.status is ExecutionStatus.COMPLETED for step in step_results
            )
            return OrchestrationResult(
                goal=goal,
                status=ExecutionStatus.COMPLETED if all_success else ExecutionStatus.FAILED,
                steps=step_results,
                total_duration_ms=(time.time() - start_time) * 1000,
                error=None if all_success else "Some steps failed",
            )
        except Exception as exc:  # noqa: BLE001 - 编排整体异常须以结果形态返回
            logger.error("Orchestration failed: %s", exc)
            return OrchestrationResult(
                goal=goal,
                status=ExecutionStatus.FAILED,
                total_duration_ms=(time.time() - start_time) * 1000,
                error=str(exc),
            )
        finally:
            self._step_outputs = {}
            _orchestrationDepth.reset(token)

    def _resolve_steps(
        self, goal: str, tool_plan: typing.Optional[typing.List]
    ) -> typing.List[OrchestrationStep]:
        """把 goal / tool_plan 归一成步骤表（不合法即抛 ValueError）。"""
        if tool_plan is not None:
            return self.normalize_steps(tool_plan)
        return [OrchestrationStep(name) for name in self.build_plan_from_goal(goal)]

    def _partition_plan_into_layers(
        self, plan: typing.List[OrchestrationStep]
    ) -> typing.List[typing.List[OrchestrationStep]]:
        """把步骤表分层：同层内的步进相互无依赖，可并行。

        依赖来源两处合一：显式声明的 `depends_on` 优先，其次取能力图里该工具的前置。
        落在计划**之外**的图依赖不参与分层——否则单步计划会被图里早就退役的前置
        拖进「无法解析依赖」的兜底层。
        """
        declared = {step.tool_name: self._dependency_names(step) for step in plan}
        in_plan = set(declared)
        layers: typing.List[typing.List[OrchestrationStep]] = []
        remaining = list(plan)

        while remaining:
            executed = {step.tool_name for layer in layers for step in layer}
            current: typing.List[OrchestrationStep] = []
            for step in remaining:
                deps = {dep for dep in declared[step.tool_name] if dep in in_plan}
                if deps <= executed:
                    current.append(step)
            if not current:
                current = list(remaining)
                logger.warning(
                    "Cannot resolve dependencies for: %s",
                    [step.tool_name for step in remaining],
                )
            layers.append(current)
            current_names = {step.tool_name for step in current}
            remaining = [step for step in remaining if step.tool_name not in current_names]

        return layers

    def _dependency_names(self, step: OrchestrationStep) -> typing.List[str]:
        """步进的前置工具名：显式声明优先，否则取能力图。"""
        if step.depends_on:
            return list(step.depends_on)
        node = self._capability_graph.get_node(step.tool_name)
        return list(node.dependencies) if node else []

    @staticmethod
    def _render_params(
        params: typing.Dict[str, typing.Any], step_outputs: typing.Dict[int, typing.Any]
    ) -> typing.Dict[str, typing.Any]:
        """`{step_<idx>.<field>}` 占位符渲染（**单源**在既有技能序列解释器）。

        占位符约定不是本模块的私有语法：`ToolSequenceSkill` 早已按同一约定解释它。
        此处直接复用那份实现，不在编排器里再写一遍解析（教义第 6 条）。
        """
        from neurova.skill_system import ToolSequenceSkill

        return ToolSequenceSkill._render_params(params, step_outputs)

    async def _execute_layer(
        self,
        layer: typing.List[OrchestrationStep],
        step_offset: int,
        context: typing.Dict[str, typing.Any],
    ) -> typing.List[StepResult]:
        """执行一层步进（层内并发受 `_max_parallel` 约束）。"""
        semaphore = asyncio.Semaphore(self._max_parallel)

        async def _run(index: int, step: OrchestrationStep) -> StepResult:
            async with semaphore:
                params = self._render_params(step.params, step_outputs)
                return await self._execute_step(
                    f"step_{step_offset + index}", step.tool_name, params, context
                )

        step_outputs: typing.Dict[int, typing.Any] = getattr(self, "_step_outputs", {})

        results = await asyncio.gather(
            *(_run(index, step) for index, step in enumerate(layer)),
            return_exceptions=True,
        )

        final: typing.List[StepResult] = []
        for index, outcome in enumerate(results):
            if isinstance(outcome, BaseException):
                final.append(
                    StepResult(
                        step_id=f"step_{step_offset + index}",
                        tool_name=layer[index].tool_name,
                        status=ExecutionStatus.FAILED,
                        error=str(outcome),
                    )
                )
                continue
            if outcome.status is ExecutionStatus.COMPLETED:
                final.append(outcome)
                if outcome.output is not None:
                    step_outputs[step_offset + index] = outcome.output
                continue
            step = layer[index]
            final.append(
                await self._try_fallback(
                    outcome.step_id, step.tool_name, step.params, outcome.error or "", context
                )
            )
        return final

    def _resolve_goal_to_capabilities_sync(self, goal: str) -> typing.List[str]:
        """解析目标为能力列表。

        词边界匹配（避免 "search" 命中 "read"）。**读不懂就返回空表**：
        历史实现兜底成 `process_data`，把「没听懂」变成「跑个无关工具」。
        """
        import re

        goal_lower = (goal or "").lower()
        patterns = [
            (r"\bread\b", "read_file"),
            (r"\bwrite\b", "write_file"),
            (r"\bsave\b", "write_file"),
            (r"\bsearch\b.*\b(file|files|directory|directories)\b", "search_files"),
            (r"\bfind\b.*\b(file|files)\b", "search_files"),
            (r"\bsearch\b.*\b(memory|memories)\b", "search_memory"),
            (r"\bremember\b", "search_memory"),
            (r"\brecall\b", "search_memory"),
            (r"\bsearch\b.*\b(web|internet|online)\b", "search_web"),
            (r"\bfetch\b.*\burl\b", "search_web"),
            (r"\bexecute\b.*\bcode\b", "run_code"),
            (r"\brun\b.*\b(code|script)\b", "run_code"),
            (r"\bcalculate\b", "calculate"),
            (r"\bplan\b", "plan_task"),
        ]

        capabilities: typing.List[str] = []
        seen: typing.Set[str] = set()
        for pattern, capability in patterns:
            if re.search(pattern, goal_lower) and capability not in seen:
                capabilities.append(capability)
                seen.add(capability)
        return capabilities

    async def _execute_step(
        self,
        step_id: str,
        tool_name: str,
        params: typing.Dict[str, typing.Any],
        context: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> StepResult:
        """执行单个步骤。成败判据委托执行器声明（单源），不按「有没有抛异常」猜。"""
        start_time = time.time()

        if not self._executor:
            return StepResult(
                step_id=step_id,
                tool_name=tool_name,
                status=ExecutionStatus.FAILED,
                error="No executor configured",
            )

        call_params = dict(params or {})
        if context:
            call_params["_context"] = dict(context)

        try:
            output = await asyncio.wait_for(
                self._invoke_executor(tool_name, call_params), timeout=self._step_timeout
            )
        except asyncio.TimeoutError:
            return StepResult(
                step_id=step_id,
                tool_name=tool_name,
                status=ExecutionStatus.TIMEOUT,
                duration_ms=(time.time() - start_time) * 1000,
                error=f"Step timed out after {self._step_timeout} seconds",
            )
        except Exception as exc:  # noqa: BLE001 - 单步异常转结果形态，不吞原因
            logger.error("Step %s (%s) failed: %s", step_id, tool_name, exc)
            return StepResult(
                step_id=step_id,
                tool_name=tool_name,
                status=ExecutionStatus.FAILED,
                duration_ms=(time.time() - start_time) * 1000,
                error=str(exc),
            )

        duration_ms = (time.time() - start_time) * 1000
        # 超时转后台的信封既不是成功也不是失败，而是**未完成**（工具仍在后台跑）。
        # 它是 `tool_coordinator.run_with_timeout` 的显式状态，不是内容判据的第三种取值，
        # 故不并入 `_result_is_success`（那会让判据承担两种语义）。
        if isinstance(output, dict) and output.get("status") == "background":
            return StepResult(
                step_id=step_id,
                tool_name=tool_name,
                status=ExecutionStatus.TIMEOUT,
                output=output,
                duration_ms=duration_ms,
                error="工具执行超时已转入后台，本轮未完成",
            )

        if not self._result_is_success(output):
            return StepResult(
                step_id=step_id,
                tool_name=tool_name,
                status=ExecutionStatus.FAILED,
                output=output if isinstance(output, dict) else None,
                duration_ms=duration_ms,
                error=self._failure_reason(output),
            )

        return StepResult(
            step_id=step_id,
            tool_name=tool_name,
            status=ExecutionStatus.COMPLETED,
            output=output if isinstance(output, dict) else None,
            duration_ms=duration_ms,
        )

    def _failure_reason(self, output: typing.Any) -> str:
        """从工具返回里取失败原因；取不到时点名「工具自报失败」，不编造。"""
        if isinstance(output, dict):
            if output.get("error"):
                return str(output["error"])
            if output.get("status") == "background":
                return "工具执行超时已转入后台，本轮未完成"
            if output.get("success") is False:
                return "工具自报 success=False"
        return "工具自报失败"

    @staticmethod
    def _result_is_success(output: typing.Any) -> bool:
        """成败判据单源：委托执行咽喉的 `_result_is_success`。

        本模块不复写第二份内容判据（教义第 6 条）；`tool_executor` 与本模块
        互为上下游，模块级互导会成环，故在此惰性取用。
        """
        from neurova.tool_executor import ToolExecutor

        return ToolExecutor._result_is_success(output)

    async def _try_fallback(
        self,
        step_id: str,
        primary_tool: str,
        params: typing.Dict[str, typing.Any],
        error: str,
        context: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> StepResult:
        """按能力图的降级关系重试一步；全失败则保留主因（不覆盖成兜底语义）。"""
        fallbacks = self._capability_graph.suggest_fallback(primary_tool)
        primary_error = error or "unknown error"
        if not fallbacks:
            # 无降级路径时保留主因原文——报「all fallbacks failed」会让读者以为
            # 试过若干兜底并全部失败，而事实是根本没有兜底。
            return StepResult(
                step_id=step_id,
                tool_name=primary_tool,
                status=ExecutionStatus.FAILED,
                error=primary_error,
            )

        for fallback_tool in fallbacks:
            logger.info("Trying fallback %s for %s", fallback_tool, primary_tool)
            outcome = await self._execute_step(
                f"{step_id}_fallback", fallback_tool, params or {}, context
            )
            if outcome.status is ExecutionStatus.COMPLETED:
                logger.info("Fallback %s succeeded", fallback_tool)
                return outcome

        return StepResult(
            step_id=step_id,
            tool_name=primary_tool,
            status=ExecutionStatus.FAILED,
            error=f"{primary_error} | all fallbacks failed",
        )
