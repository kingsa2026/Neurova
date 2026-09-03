#!/usr/bin/env python3
"""功能测试：验证新创建的模块可以正常工作"""
import sys

try:
    print("测试上下文系统...")
    from neurova.context import ContextBuilder, TokenBudget
    
    # 测试 ContextBuilder 实例化
    builder = ContextBuilder()
    print(f"✓ ContextBuilder 实例化成功: {builder}")
    
    # 测试 TokenBudget 默认值
    budget = TokenBudget()
    print(f"✓ TokenBudget 默认值: max_total={budget.max_total}, system_prompt={budget.system_prompt}")
    
    print("\n测试协作系统...")
    from neurova.collaborate import (
        TemplateType, AgentRole, TaskStep, WorkflowDefinition,
        CollaborationTemplate, TemplateManager, get_template_manager
    )
    
    # 测试枚举值
    print(f"✓ TemplateType.CODE_REVIEW: {TemplateType.CODE_REVIEW.value}")
    print(f"✓ AgentRole.COORDINATOR: {AgentRole.COORDINATOR.value}")
    
    # 测试数据类
    step = TaskStep(step_id="1", name="测试步骤")
    print(f"✓ TaskStep 创建成功: {step.name}")
    
    # 测试工作流定义
    workflow = WorkflowDefinition(steps=[step])
    print(f"✓ WorkflowDefinition 创建成功: {len(workflow.steps)} 个步骤")
    
    # 测试模板管理器
    manager = get_template_manager()
    print(f"✓ TemplateManager 获取成功: {manager}")
    
    print("\n测试工作流系统...")
    from neurova.collaborate.workflow import (
        FlowPhase, FlowEvent, FlowContext, ScheduledTask,
        FlowOrchestrator, get_orchestrator,
        AgentScheduler, get_scheduler
    )
    
    # 测试枚举值
    print(f"✓ FlowPhase.IDLE: {FlowPhase.IDLE.value}")
    print(f"✓ FlowEvent.PHASE_CHANGED: {FlowEvent.PHASE_CHANGED.value}")
    
    # 测试上下文
    context = FlowContext()
    print(f"✓ FlowContext 创建成功: {context.flow_id}")
    
    # 测试计划任务
    task = ScheduledTask(name="测试任务", action="test")
    print(f"✓ ScheduledTask 创建成功: {task.name}")
    
    # 测试编排器
    orchestrator = get_orchestrator()
    print(f"✓ FlowOrchestrator 获取成功: {orchestrator}")
    
    # 测试调度器
    scheduler = get_scheduler()
    print(f"✓ AgentScheduler 获取成功: {scheduler}")
    
    print("\n" + "="*60)
    print("所有功能测试通过！")
    print("="*60)
    
except Exception as e:
    print(f"测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)