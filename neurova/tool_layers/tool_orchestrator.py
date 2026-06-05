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
from dataclasses import dataclass, field
import enum
import logging
import time
import typing
from enum import Enum

# tool_layers imports
from neurova.tool_layers.capability_graph import ToolCapabilityGraph

logger = logging.getLogger(__name__)


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
            "error": self.error
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
            "error": self.error
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
    
    async def orchestrate(self, goal: str, context: typing.Optional[typing.Dict] = None) -> OrchestrationResult:
        """
        编排执行
        
        参数:
            goal: 用户目标
            context: 执行上下文
            
        返回:
            编排结果
        """
        start_time = time.time()
        
        try:
            # 构建执行计划
            plan = self.build_plan_from_goal(goal)
            
            if not plan:
                return OrchestrationResult(
                    goal=goal,
                    status=ExecutionStatus.FAILED,
                    error="No execution plan could be built from goal",
                    total_duration_ms=(time.time() - start_time) * 1000
                )
            
            # 执行计划
            step_results = []
            for i, tool_name in enumerate(plan):
                step_id = f"step_{i}"
                
                # 检查是否可以并行执行
                if self._can_run_in_parallel(tool_name, plan[:i], step_results):
                    # 并行执行（这里简化为顺序执行）
                    result = await self._execute_step(step_id, tool_name, context or {})
                else:
                    # 顺序执行
                    result = await self._execute_step(step_id, tool_name, context or {})
                
                step_results.append(result)
                
                # 如果步骤失败，尝试降级
                if result.status == ExecutionStatus.FAILED:
                    fallback_result = await self._try_fallback(
                        step_id, tool_name, context or {}, result.error
                    )
                    if fallback_result.status == ExecutionStatus.SUCCESS:
                        # 替换失败结果
                        step_results[-1] = fallback_result
                    else:
                        # 降级也失败，整个编排失败
                        return OrchestrationResult(
                            goal=goal,
                            status=ExecutionStatus.FAILED,
                            steps=step_results,
                            total_duration_ms=(time.time() - start_time) * 1000,
                            error=f"Step {step_id} failed and fallback also failed"
                        )
            
            # 检查所有步骤是否成功
            all_success = all(s.status == ExecutionStatus.SUCCESS for s in step_results)
            
            return OrchestrationResult(
                goal=goal,
                status=ExecutionStatus.SUCCESS if all_success else ExecutionStatus.FAILED,
                steps=step_results,
                total_duration_ms=(time.time() - start_time) * 1000,
                error=None if all_success else "Some steps failed"
            )
            
        except Exception as e:
            logger.error(f"Orchestration failed: {e}")
            return OrchestrationResult(
                goal=goal,
                status=ExecutionStatus.FAILED,
                total_duration_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )
    
    def _resolve_goal_to_capabilities_sync(self, goal: str) -> typing.List[str]:
        """
        同步版本：解析目标为能力列表
        
        参数:
            goal: 用户目标
            
        返回:
            能力列表
        """
        # 简单的关键词匹配（实际实现可能使用 LLM）
        goal_lower = goal.lower()
        capabilities = []
        
        if "read" in goal_lower or "file" in goal_lower:
            capabilities.append("read_file")
        if "write" in goal_lower or "save" in goal_lower:
            capabilities.append("write_file")
        if "search" in goal_lower or "find" in goal_lower:
            capabilities.append("search_files")
        if "memory" in goal_lower or "remember" in goal_lower:
            capabilities.append("search_memory")
        if "web" in goal_lower or "internet" in goal_lower:
            capabilities.append("search_web")
        if "code" in goal_lower or "execute" in goal_lower:
            capabilities.append("run_code")
        
        # 如果没有匹配到，返回通用能力
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
    
    async def _execute_step(
        self, 
        step_id: str, 
        tool_name: str, 
        params: typing.Dict[str, typing.Any]
    ) -> StepResult:
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
                    step_id=step_id,
                    tool_name=tool_name,
                    status=ExecutionStatus.FAILED,
                    error="No executor configured"
                )
            
            # 执行工具（带超时）
            try:
                output = await asyncio.wait_for(
                    self._executor.execute(tool_name, params),
                    timeout=self._step_timeout
                )
            except asyncio.TimeoutError:
                return StepResult(
                    step_id=step_id,
                    tool_name=tool_name,
                    status=ExecutionStatus.TIMEOUT,
                    duration_ms=(time.time() - start_time) * 1000,
                    error=f"Step timed out after {self._step_timeout} seconds"
                )
            
            # 计算执行时间
            duration_ms = (time.time() - start_time) * 1000
            
            return StepResult(
                step_id=step_id,
                tool_name=tool_name,
                status=ExecutionStatus.SUCCESS,
                output=output,
                duration_ms=duration_ms
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Step {step_id} ({tool_name}) failed: {e}")
            
            return StepResult(
                step_id=step_id,
                tool_name=tool_name,
                status=ExecutionStatus.FAILED,
                duration_ms=duration_ms,
                error=str(e)
            )
    
    async def _try_fallback(
        self,
        step_id: str,
        primary_tool: str,
        params: typing.Dict[str, typing.Any],
        error: str
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
            logger.info(f"Trying fallback {fallback_tool} for {primary_tool}")
            
            result = await self._execute_step(
                f"{step_id}_fallback",
                fallback_tool,
                params
            )
            
            if result.status == ExecutionStatus.SUCCESS:
                logger.info(f"Fallback {fallback_tool} succeeded")
                return result
        
        # 所有降级都失败
        return StepResult(
            step_id=step_id,
            tool_name=primary_tool,
            status=ExecutionStatus.FAILED,
            error=f"All fallbacks failed for {primary_tool}: {error}"
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
        self, 
        tool_name: str, 
        previous_tools: typing.List[str], 
        previous_results: typing.List[StepResult]
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