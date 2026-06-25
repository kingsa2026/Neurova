"""
ToolOrchestrator v1.0.0 — DAG 工具编排器 (Phase 3 P3-1b)

职责:
- 从目标能力描述自动构建 DAG 执行计划
- 按拓扑顺序分层并行执行工具
- 处理失败降级、步骤依赖等待
- 导出编排结果（成功/失败/耗时/步骤详情）

架构:
    用户目标 ──▶ CapabilityGraph ──▶ DAG 执行计划
"""

import asyncio
from neurova.core.logger import get_logger
import time
import typing
from dataclasses import dataclass, field
from enum import Enum

# tool_layers imports
from neurova.tool_layers.capability_graph import ToolCapabilityGraph

logger = get_logger(__name__)


class ExecutionStatus(str, Enum):
    """执行状态枚举"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


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


class ToolOrchestrator:
    """
    DAG 工具编排器

    功能：
    1. 从目标自动构建执行计划
    2. 按拓扑顺序执行工具
    3. 支持失败降级
    4. 支持并行执行（如果工具无依赖）
    """

    def __init__(self):
        """初始化编排器"""
        self._executor = None
        self._capability_graph = ToolCapabilityGraph()
        self._step_timeout = 30.0  # 单步超时（秒）
        self._max_parallel = 5  # 最大并行数

    def set_executor(self, executor: typing.Any) -> None:
        """设置工具执行器"""
        self._executor = executor

    def build_plan_from_goal(self, goal: str) -> typing.List[str]:
        """
        从目标构建执行计划

        参数:
            goal: 用户目标描述

        返回:
            工具执行顺序列表
        """
        # 解析目标为能力列表
        capabilities = self._resolve_goal_to_capabilities_sync(goal)

        # 使用能力图构建执行计划
        if capabilities:
            return self._capability_graph.build_execution_plan(capabilities)

        # 如果无法解析，返回默认计划
        return []

    async def orchestrate(
        self,
        goal: str,
        context: typing.Optional[typing.Dict] = None,
        tool_plan: typing.Optional[typing.List[str]] = None,
    ) -> OrchestrationResult:
        """
        编排执行

        参数:
            goal: 用户目标
            context: 执行上下文
            tool_plan: 直接传入的工具执行计划（跳过 goal 解析）

        返回:
            编排结果
        """
        start_time = time.time()

        try:
            # 构建执行计划：优先使用直接传入的 plan，否则从 goal 解析
            plan = tool_plan if tool_plan is not None else self.build_plan_from_goal(goal)

            if not plan:
                return OrchestrationResult(
                    goal=goal,
                    status=ExecutionStatus.FAILED,
                    error="No execution plan could be built from goal",
                    total_duration_ms=(time.time() - start_time) * 1000,
                )

            # 将 plan 分成可并行执行的层
            layers = self._partition_plan_into_layers(plan)

            step_results = []
            step_counter = 0

            for layer in layers:
                layer_results = await self._execute_layer(layer, step_counter, context or {})
                step_results.extend(layer_results)
                step_counter += len(layer)

                # 检查本层是否有失败且降级也失败的步骤
                for result in layer_results:
                    if result.status == ExecutionStatus.FAILED:
                        # 降级已在 _execute_layer 内部处理
                        # 如果仍然失败，整个编排失败
                        if result.error and "fallback also failed" in result.error:
                            return OrchestrationResult(
                                goal=goal,
                                status=ExecutionStatus.FAILED,
                                steps=step_results,
                                total_duration_ms=(time.time() - start_time) * 1000,
                                error=f"Step {result.step_id} failed and fallback also failed",
                            )

            # 检查所有步骤是否成功
            all_success = all(s.status == ExecutionStatus.SUCCESS for s in step_results)

            return OrchestrationResult(
                goal=goal,
                status=ExecutionStatus.SUCCESS if all_success else ExecutionStatus.FAILED,
                steps=step_results,
                total_duration_ms=(time.time() - start_time) * 1000,
                error=None if all_success else "Some steps failed",
            )

        except Exception as e:
            logger.error("Orchestration failed: %s", e)
            return OrchestrationResult(
                goal=goal,
                status=ExecutionStatus.FAILED,
                total_duration_ms=(time.time() - start_time) * 1000,
                error=str(e),
            )

    def _partition_plan_into_layers(self, plan: typing.List[str]) -> typing.List[typing.List[str]]:
        """
        将执行计划分层：同一层内的工具无相互依赖，可以并行执行

        参数:
            plan: 拓扑排序后的工具计划

        返回:
            分层列表，每层包含可并行执行的工具
        """
        layers = []
        remaining = list(plan)

        while remaining:
            # 找出当前所有依赖都已在前面层中完成的工具
            current_layer = []
            executed = set()
            for layer in layers:
                executed.update(layer)

            for tool in remaining:
                node = self._capability_graph.get_node(tool)
                if not node:
                    # 未知工具放在当前层（无法解析依赖）
                    current_layer.append(tool)
                    continue

                # 检查所有依赖是否都已执行
                deps_met = all(dep in executed for dep in node.dependencies)
                if deps_met:
                    current_layer.append(tool)

            if not current_layer:
                # 防止无限循环：如果无法找到可执行的工具，剩余全部放入下一层
                logger.warning("Cannot resolve dependencies for: %s", remaining)
                current_layer = remaining[:]

            layers.append(current_layer)
            # 从 remaining 中移除当前层的工具
            for tool in current_layer:
                if tool in remaining:
                    remaining.remove(tool)

        return layers

    async def _execute_layer(
        self, layer: typing.List[str], step_offset: int, context: typing.Dict[str, typing.Any]
    ) -> typing.List[StepResult]:
        """
        执行一层工具（层内并行）

        参数:
            layer: 本层工具列表
            step_offset: 步骤 ID 偏移
            context: 执行上下文

        返回:
            本层所有工具的执行结果
        """
        if len(layer) == 1:
            # 单个工具直接执行
            result = await self._execute_step(f"step_{step_offset}", layer[0], context)

            # 失败降级
            if result.status == ExecutionStatus.FAILED:
                fallback_result = await self._try_fallback(f"step_{step_offset}", layer[0], context, result.error)
                if fallback_result.status == ExecutionStatus.SUCCESS:
                    return [fallback_result]
                else:
                    return [
                        StepResult(
                            step_id=result.step_id,
                            tool_name=result.tool_name,
                            status=ExecutionStatus.FAILED,
                            error=f"{result.error} | fallback also failed: {fallback_result.error}",
                        )
                    ]

            return [result]

        # 多个工具并行执行
        min(len(layer), self._max_parallel)

        # 构建所有任务
        tasks = []
        for i, tool_name in enumerate(layer):
            step_id = f"step_{step_offset + i}"
            tasks.append(self._execute_step(step_id, tool_name, context))

        # 使用 asyncio.gather 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果和异常
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                step_id = f"step_{step_offset + i}"
                final_results.append(
                    StepResult(step_id=step_id, tool_name=layer[i], status=ExecutionStatus.FAILED, error=str(result))
                )
            else:
                # 失败降级
                if result.status == ExecutionStatus.FAILED:
                    fallback_result = await self._try_fallback(result.step_id, result.tool_name, context, result.error)
                    if fallback_result.status == ExecutionStatus.SUCCESS:
                        final_results.append(fallback_result)
                    else:
                        final_results.append(
                            StepResult(
                                step_id=result.step_id,
                                tool_name=result.tool_name,
                                status=ExecutionStatus.FAILED,
                                error=f"{result.error} | fallback also failed: {fallback_result.error}",
                            )
                        )
                else:
                    final_results.append(result)

        return final_results

    def _resolve_goal_to_capabilities_sync(self, goal: str) -> typing.List[str]:
        """
        同步版本：解析目标为能力列表

        使用词边界匹配避免子串误匹配（如 "search" 中包含 "read"）。
        多个匹配规则之间按优先级排列，独立检测。

        参数:
            goal: 用户目标

        返回:
            能力列表
        """
        import re

        goal_lower = goal.lower()
        capabilities = []

        # 使用 word-boundary 正则避免子串误匹配
        # 每个模式独立匹配，支持多个能力共存
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
        ]

        seen = set()
        for pattern, capability in patterns:
            if re.search(pattern, goal_lower) and capability not in seen:
                capabilities.append(capability)
                seen.add(capability)

        # 宽泛回退：如果上面精确匹配没有命中
        if not capabilities:
            fallback_patterns = [
                (r"\bsearch\b", "search_files"),
                (r"\bfind\b", "search_files"),
                (r"\bmemory\b", "search_memory"),
                (r"\bcode\b", "run_code"),
            ]
            for pattern, capability in fallback_patterns:
                if re.search(pattern, goal_lower) and capability not in seen:
                    capabilities.append(capability)
                    seen.add(capability)

        # 最终兜底
        if not capabilities:
            capabilities = ["process_data"]

        return capabilities

    async def _resolve_goal_to_capabilities(self, goal: str) -> typing.List[str]:
        """
        异步版本：解析目标为能力列表

        参数:
            goal: 用户目标

        返回:
            能力列表
        """
        # 这里可以调用 LLM 进行更智能的解析
        return self._resolve_goal_to_capabilities_sync(goal)

    async def _execute_step(self, step_id: str, tool_name: str, params: typing.Dict[str, typing.Any]) -> StepResult:
        """
        执行单个步骤

        参数:
            step_id: 步骤 ID
            tool_name: 工具名称
            params: 执行参数

        返回:
            步骤结果
        """
        start_time = time.time()

        try:
            # 检查执行器
            if not self._executor:
                return StepResult(
                    step_id=step_id, tool_name=tool_name, status=ExecutionStatus.FAILED, error="No executor configured"
                )

            # 执行工具（带超时）
            try:
                output = await asyncio.wait_for(self._executor.execute(tool_name, params), timeout=self._step_timeout)
            except asyncio.TimeoutError:
                return StepResult(
                    step_id=step_id,
                    tool_name=tool_name,
                    status=ExecutionStatus.TIMEOUT,
                    duration_ms=(time.time() - start_time) * 1000,
                    error=f"Step timed out after {self._step_timeout} seconds",
                )

            # 计算执行时间
            duration_ms = (time.time() - start_time) * 1000

            return StepResult(
                step_id=step_id,
                tool_name=tool_name,
                status=ExecutionStatus.SUCCESS,
                output=output,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error("Step %s (%s) failed: %s", step_id, tool_name, e)

            return StepResult(
                step_id=step_id,
                tool_name=tool_name,
                status=ExecutionStatus.FAILED,
                duration_ms=duration_ms,
                error=str(e),
            )

    async def _try_fallback(
        self, step_id: str, primary_tool: str, params: typing.Dict[str, typing.Any], error: str
    ) -> StepResult:
        """
        尝试降级执行

        参数:
            step_id: 步骤 ID
            primary_tool: 主工具名称
            params: 执行参数
            error: 主工具错误信息

        返回:
            步骤结果
        """
        # 获取降级工具
        fallbacks = self._capability_graph.suggest_fallback(primary_tool)

        for fallback_tool in fallbacks:
            logger.info("Trying fallback %s for %s", fallback_tool, primary_tool)

            result = await self._execute_step(f"{step_id}_fallback", fallback_tool, params)

            if result.status == ExecutionStatus.SUCCESS:
                logger.info("Fallback %s succeeded", fallback_tool)
                return result

        # 所有降级都失败
        return StepResult(
            step_id=step_id,
            tool_name=primary_tool,
            status=ExecutionStatus.FAILED,
            error=f"All fallbacks failed for {primary_tool}: {error}",
        )

    def _capability_to_dag(self, capabilities: typing.List[str]) -> typing.Dict[str, typing.List[str]]:
        """
        将能力列表转换为 DAG

        参数:
            capabilities: 能力列表

        返回:
            DAG 邻接表
        """
        dag = {}

        for cap in capabilities:
            # 找到拥有该能力的工具
            tools = self._capability_graph._capability_index.get(cap, [])

            if tools:
                tool = tools[0]
                node = self._capability_graph.get_node(tool)

                if node:
                    # 添加节点和依赖
                    dag[tool] = list(node.dependencies)

        return dag

    def _can_run_in_parallel(
        self, tool_name: str, previous_tools: typing.List[str], previous_results: typing.List[StepResult]
    ) -> bool:
        """
        检查工具是否可以并行执行

        参数:
            tool_name: 工具名称
            previous_tools: 之前执行的工具列表
            previous_results: 之前执行的结果

        返回:
            是否可以并行执行
        """
        node = self._capability_graph.get_node(tool_name)
        if not node:
            return False

        # 检查所有依赖是否已完成
        for dep in node.dependencies:
            if dep in previous_tools:
                # 检查依赖是否成功
                for result in previous_results:
                    if result.tool_name == dep and result.status != ExecutionStatus.SUCCESS:
                        return False
            else:
                # 依赖未执行，不能并行
                return False

        return True
