# -*- coding: utf-8 -*-
"""
流程编排器

管理工作流的执行过程，协调多个 Agent 的协作。
"""

import logging
import time
from typing import Dict, List, Optional, Any, Callable

from ..models import WorkflowDefinition, TaskStep, AgentRole
from .models import FlowPhase, FlowEvent, FlowContext, ScheduledTask
from .scheduler import get_scheduler

logger = logging.getLogger(__name__)


class FlowOrchestrator:
    """流程编排器
    
    负责管理工作流的执行过程，包括：
    - 工作流实例的创建和管理
    - 步骤的执行和协调
    - Agent 任务的分配
    - 执行状态的监控
    """
    
    def __init__(self):
        self._flows: Dict[str, FlowContext] = {}
        self._step_handlers: Dict[str, Callable] = {}  # step_name -> handler
        self._agent_capabilities: Dict[str, List[str]] = {}  # agent_id -> capabilities
        self._event_handlers: List[Callable] = []
        
        logger.info("FlowOrchestrator initialized")
    
    def register_step_handler(self, step_name: str, handler: Callable) -> None:
        """注册步骤处理器
        
        Args:
            step_name: 步骤名称
            handler: 处理函数，签名: (step: TaskStep, context: FlowContext) -> Any
        """
        self._step_handlers[step_name] = handler
        logger.info(f"Registered handler for step: {step_name}")
    
    def register_agent(self, agent_id: str, capabilities: List[str]) -> None:
        """注册 Agent 及其能力
        
        Args:
            agent_id: Agent ID
            capabilities: Agent 能力列表
        """
        self._agent_capabilities[agent_id] = capabilities
        logger.info(f"Registered agent: {agent_id} with capabilities: {capabilities}")
    
    def create_flow(self, workflow: WorkflowDefinition, template_id: str = "",
                   participants: Dict[str, AgentRole] = None) -> FlowContext:
        """创建工作流实例
        
        Args:
            workflow: 工作流定义
            template_id: 关联的模板ID
            participants: 参与者及其角色
            
        Returns:
            工作流上下文
        """
        context = FlowContext(
            template_id=template_id,
            participants={aid: role.value for aid, role in (participants or {}).items()},
        )
        
        self._flows[context.flow_id] = context
        
        # 初始化事件
        context.add_event(FlowEvent.PHASE_CHANGED, {
            "old_phase": "none",
            "new_phase": FlowPhase.INITIALIZATION.value,
        })
        
        logger.info(f"Flow created: {context.flow_id}")
        self._emit_event("flow_created", context)
        
        return context
    
    def start_flow(self, flow_id: str, workflow: WorkflowDefinition) -> bool:
        """启动工作流
        
        Args:
            flow_id: 工作流ID
            workflow: 工作流定义
            
        Returns:
            是否启动成功
        """
        context = self._flows.get(flow_id)
        if not context:
            logger.error(f"Flow not found: {flow_id}")
            return False
        
        # 验证工作流
        valid, errors = workflow.validate()
        if not valid:
            logger.error(f"Workflow validation failed: {errors}")
            context.fail(f"Workflow validation failed: {errors}")
            return False
        
        # 进入规划阶段
        context.set_phase(FlowPhase.PLANNING)
        
        # 分配任务给 Agent
        self._assign_tasks(workflow, context)
        
        # 进入执行阶段
        context.set_phase(FlowPhase.EXECUTION)
        
        logger.info(f"Flow started: {flow_id}")
        self._emit_event("flow_started", context)
        
        return True
    
    def execute_step(self, flow_id: str, step_id: str, workflow: WorkflowDefinition) -> Optional[Any]:
        """执行工作流步骤
        
        Args:
            flow_id: 工作流ID
            step_id: 步骤ID
            workflow: 工作流定义
            
        Returns:
            步骤执行结果
        """
        context = self._flows.get(flow_id)
        if not context:
            logger.error(f"Flow not found: {flow_id}")
            return None
        
        step = workflow.get_step(step_id)
        if not step:
            logger.error(f"Step not found: {step_id}")
            return None
        
        # 检查依赖是否满足
        if not self._check_dependencies(step, context):
            logger.warning(f"Dependencies not met for step: {step_id}")
            return None
        
        # 设置当前步骤
        context.current_step_id = step_id
        
        # 触发步骤开始事件
        context.add_event(FlowEvent.STEP_STARTED, {"step_id": step_id})
        self._emit_event("step_started", context, {"step_id": step_id})
        
        # 查找处理器
        handler = self._step_handlers.get(step.name)
        if not handler:
            logger.error(f"No handler for step: {step.name}")
            context.fail_step(step_id, f"No handler for step: {step.name}")
            return None
        
        try:
            # 执行步骤
            result = handler(step, context)
            
            # 标记步骤完成
            context.complete_step(step_id, result)
            
            logger.info(f"Step completed: {step_id}")
            self._emit_event("step_completed", context, {"step_id": step_id, "result": result})
            
            return result
            
        except Exception as e:
            context.fail_step(step_id, str(e))
            logger.exception(f"Step failed: {step_id}: {e}")
            self._emit_event("step_failed", context, {"step_id": step_id, "error": str(e)})
            return None
    
    def complete_flow(self, flow_id: str) -> bool:
        """完成工作流
        
        Args:
            flow_id: 工作流ID
            
        Returns:
            是否完成成功
        """
        context = self._flows.get(flow_id)
        if not context:
            return False
        
        context.complete()
        logger.info(f"Flow completed: {flow_id}")
        self._emit_event("flow_completed", context)
        return True
    
    def fail_flow(self, flow_id: str, error: str = None) -> bool:
        """标记工作流失败
        
        Args:
            flow_id: 工作流ID
            error: 错误信息
            
        Returns:
            是否操作成功
        """
        context = self._flows.get(flow_id)
        if not context:
            return False
        
        context.fail(error)
        logger.info(f"Flow failed: {flow_id}")
        self._emit_event("flow_failed", context, {"error": error})
        return True
    
    def cancel_flow(self, flow_id: str) -> bool:
        """取消工作流
        
        Args:
            flow_id: 工作流ID
            
        Returns:
            是否取消成功
        """
        context = self._flows.get(flow_id)
        if not context:
            return False
        
        context.cancel()
        logger.info(f"Flow cancelled: {flow_id}")
        self._emit_event("flow_cancelled", context)
        return True
    
    def get_flow(self, flow_id: str) -> Optional[FlowContext]:
        """获取工作流上下文"""
        return self._flows.get(flow_id)
    
    def list_flows(self, phase: FlowPhase = None) -> List[FlowContext]:
        """列出工作流
        
        Args:
            phase: 按阶段过滤
            
        Returns:
            工作流列表
        """
        flows = list(self._flows.values())
        if phase:
            flows = [f for f in flows if f.current_phase == phase]
        return flows
    
    def _assign_tasks(self, workflow: WorkflowDefinition, context: FlowContext) -> None:
        """分配任务给 Agent"""
        for step in workflow.steps:
            # 根据角色找到合适的 Agent
            assigned_agent = self._find_agent_for_step(step, context)
            if assigned_agent:
                context.participants[assigned_agent] = step.assigned_role.value
                context.add_event(FlowEvent.TASK_ASSIGNED, {
                    "step_id": step.step_id,
                    "agent_id": assigned_agent,
                    "role": step.assigned_role.value,
                })
    
    def _find_agent_for_step(self, step: TaskStep, context: FlowContext) -> Optional[str]:
        """为步骤找到合适的 Agent"""
        required_caps = set(step.required_capabilities)
        
        # 首先检查已分配的参与者
        for agent_id, role in context.participants.items():
            if role == step.assigned_role.value:
                agent_caps = set(self._agent_capabilities.get(agent_id, []))
                if required_caps.issubset(agent_caps):
                    return agent_id
        
        # 如果没有找到，尝试匹配任何有能力的 Agent
        for agent_id, capabilities in self._agent_capabilities.items():
            if required_caps.issubset(set(capabilities)):
                return agent_id
        
        return None
    
    def _check_dependencies(self, step: TaskStep, context: FlowContext) -> bool:
        """检查步骤依赖是否满足"""
        for dep_id in step.depends_on:
            if not context.is_step_completed(dep_id):
                return False
        return True
    
    def add_event_handler(self, handler: Callable) -> None:
        """添加事件处理器"""
        self._event_handlers.append(handler)
    
    def _emit_event(self, event_type: str, context: FlowContext, data: Dict[str, Any] = None) -> None:
        """触发事件"""
        event_data = {
            "event_type": event_type,
            "flow_id": context.flow_id,
            "phase": context.current_phase.value if isinstance(context.current_phase, FlowPhase) else context.current_phase,
            "timestamp": time.time(),
            **(data or {}),
        }
        
        for handler in self._event_handlers:
            try:
                handler(event_data)
            except Exception as e:
                logger.exception(f"Error in event handler: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        flows = list(self._flows.values())
        return {
            "total_flows": len(flows),
            "active_flows": len([f for f in flows if f.current_phase == FlowPhase.EXECUTION]),
            "completed_flows": len([f for f in flows if f.current_phase == FlowPhase.COMPLETION]),
            "failed_flows": len([f for f in flows if f.current_phase == FlowPhase.FAILED]),
            "cancelled_flows": len([f for f in flows if f.current_phase == FlowPhase.CANCELLED]),
        }


# 全局编排器实例
_global_orchestrator: Optional[FlowOrchestrator] = None


def get_orchestrator() -> FlowOrchestrator:
    """获取全局编排器"""
    global _global_orchestrator
    if _global_orchestrator is None:
        _global_orchestrator = FlowOrchestrator()
    return _global_orchestrator