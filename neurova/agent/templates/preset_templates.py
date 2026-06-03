# -*- coding: utf-8 -*-
"""
Agent 协作预设模板

提供开箱即用的协作模板：
1. 代码评审模板
2. 结对编程模板
3. 问题诊断模板
4. 知识共享模板
"""

import uuid
import time

from .collaboration_template import (
    CollaborationTemplate,
    TemplateType,
    AgentRole,
    TaskStep,
    WorkflowDefinition,
)

# ==================== 代码评审模板 ====================

CODE_REVIEW_WORKFLOW = WorkflowDefinition(
    workflow_id="wf_code_review",
    name="代码评审工作流",
    description="代码评审的标准工作流程：提交 → 预审 → 评审 → 修改 → 确认",
    steps=[
        TaskStep(
            step_id="step_submit",
            name="提交代码",
            description="作者提交代码供评审",
            assigned_role=AgentRole.AUTHOR,
            required_capabilities=["code_submission", "git_operations"],
            output_produces=["code_diff", "commit_message"],
            timeout_seconds=60,
        ),
        TaskStep(
            step_id="step_precheck",
            name="自动化预检",
            description="运行自动化检查（lint、单元测试、覆盖率）",
            assigned_role=AgentRole.REVIEWER,
            required_capabilities=["static_analysis", "test_execution"],
            input_requirements={"code": "from:step_submit"},
            output_produces=["lint_report", "test_report", "coverage_report"],
            timeout_seconds=300,
        ),
        TaskStep(
            step_id="step_review",
            name="代码评审",
            description="评审者审查代码质量和设计",
            assigned_role=AgentRole.REVIEWER,
            required_capabilities=["code_review", "design_patterns"],
            input_requirements={"code": "from:step_submit", "reports": "from:step_precheck"},
            output_produces=["review_comments", "suggestions"],
            depends_on=["step_submit", "step_precheck"],
            timeout_seconds=600,
        ),
        TaskStep(
            step_id="step_address",
            name="处理评审意见",
            description="作者处理评审意见并修改代码",
            assigned_role=AgentRole.AUTHOR,
            required_capabilities=["code_modification"],
            input_requirements={"comments": "from:step_review"},
            output_produces=["modified_code", "response_to_comments"],
            depends_on=["step_review"],
            timeout_seconds=600,
        ),
        TaskStep(
            step_id="step_final_review",
            name="最终确认",
            description="评审者确认所有意见已处理",
            assigned_role=AgentRole.REVIEWER,
            required_capabilities=["code_review"],
            input_requirements={"modified_code": "from:step_address"},
            output_produces=["approval_status", "final_comments"],
            depends_on=["step_address"],
            timeout_seconds=120,
        ),
    ],
    parallel_allowed=False,
    max_concurrent_steps=1,
    rollback_on_failure=True,
)

CODE_REVIEW_TEMPLATE = CollaborationTemplate(
    template_id="tpl_code_review",
    name="代码评审",
    description="标准的代码评审协作流程，包括自动化预检和人工评审",
    template_type=TemplateType.CODE_REVIEW,
    version="1.0",
    roles={
        "author_default": AgentRole.AUTHOR,
        "reviewer_default": AgentRole.REVIEWER,
    },
    role_requirements={
        "author": ["code_submission", "code_modification", "git_operations"],
        "reviewer": ["code_review", "static_analysis", "test_execution", "design_patterns"],
    },
    workflow=CODE_REVIEW_WORKFLOW,
    max_participants=4,
    min_participants=2,
    timeout_seconds=3600,
    tags=["代码质量", "协作", "评审", "CI/CD"],
    is_preset=True,
)


# ==================== 结对编程模板 ====================

PAIR_PROGRAMMING_WORKFLOW = WorkflowDefinition(
    workflow_id="wf_pair_programming",
    name="结对编程工作流",
    description="结对编程协作流程：导航-驾驶模式",
    steps=[
        TaskStep(
            step_id="step_planning",
            name="任务规划",
            description="双方共同讨论并规划任务",
            assigned_role=AgentRole.COORDINATOR,
            required_capabilities=["task_planning", "communication"],
            output_produces=["task_breakdown", "estimated_time"],
            timeout_seconds=300,
        ),
        TaskStep(
            step_id="step_driver_session",
            name="驾驶会话",
            description="驾驶员编写代码，导航者指导",
            assigned_role=AgentRole.AUTHOR,
            required_capabilities=["coding", "real_time_communication"],
            input_requirements={"task": "from:step_planning"},
            output_produces=["code_written", "implementation_notes"],
            timeout_seconds=900,
        ),
        TaskStep(
            step_id="step_navigator_review",
            name="导航者审查",
            description="导航者审查刚写的代码",
            assigned_role=AgentRole.REVIEWER,
            required_capabilities=["code_review", "debugging"],
            input_requirements={"code": "from:step_driver_session"},
            output_produces=["code_quality_assessment", "improvements"],
            depends_on=["step_driver_session"],
            timeout_seconds=300,
        ),
        TaskStep(
            step_id="step_role_switch",
            name="角色切换",
            description="切换驾驶和导航角色",
            assigned_role=AgentRole.COORDINATOR,
            required_capabilities=["coordination"],
            depends_on=["step_navigator_review"],
            timeout_seconds=60,
        ),
        TaskStep(
            step_id="step_integration",
            name="集成与测试",
            description="合并代码并运行测试",
            assigned_role=AgentRole.AUTHOR,
            required_capabilities=["git_operations", "test_execution"],
            input_requirements={"code": "from:step_driver_session"},
            output_produces=["merged_code", "test_results"],
            depends_on=["step_role_switch"],
            timeout_seconds=300,
        ),
    ],
    parallel_allowed=False,
    max_concurrent_steps=1,
    rollback_on_failure=True,
)

PAIR_PROGRAMMING_TEMPLATE = CollaborationTemplate(
    template_id="tpl_pair_programming",
    name="结对编程",
    description="经典的导航-驾驶模式结对编程",
    template_type=TemplateType.PAIR_PROGRAMMING,
    version="1.0",
    roles={
        "driver_1": AgentRole.AUTHOR,
        "navigator_1": AgentRole.REVIEWER,
    },
    role_requirements={
        "author": ["coding", "real_time_communication"],
        "reviewer": ["code_review", "debugging", "architecture_design"],
    },
    workflow=PAIR_PROGRAMMING_WORKFLOW,
    max_participants=2,
    min_participants=2,
    timeout_seconds=7200,
    tags=["编程", "协作", "知识传递", "实时"],
    is_preset=True,
)


# ==================== 问题诊断模板 ====================

DIAGNOSTIC_WORKFLOW = WorkflowDefinition(
    workflow_id="wf_diagnostic",
    name="问题诊断工作流",
    description="系统性问题诊断和解决流程",
    steps=[
        TaskStep(
            step_id="step_collect",
            name="信息收集",
            description="收集问题相关的信息和日志",
            assigned_role=AgentRole.DIAGNOSTIC,
            required_capabilities=["log_analysis", "data_collection"],
            output_produces=["collected_info", "relevant_logs"],
            timeout_seconds=300,
        ),
        TaskStep(
            step_id="step_analyze",
            name="根因分析",
            description="分析问题找出根本原因",
            assigned_role=AgentRole.DIAGNOSTIC,
            required_capabilities=["root_cause_analysis", "system_knowledge"],
            input_requirements={"info": "from:step_collect"},
            output_produces=["hypotheses", "analysis_report"],
            depends_on=["step_collect"],
            timeout_seconds=600,
        ),
        TaskStep(
            step_id="step_verify",
            name="假设验证",
            description="验证分析假设",
            assigned_role=AgentRole.DIAGNOSTIC,
            required_capabilities=["testing", "experiment_design"],
            input_requirements={"hypotheses": "from:step_analyze"},
            output_produces=["verified_hypothesis", "test_results"],
            depends_on=["step_analyze"],
            timeout_seconds=600,
        ),
        TaskStep(
            step_id="step_solution",
            name="解决方案",
            description="制定并验证解决方案",
            assigned_role=AgentRole.SOLVER,
            required_capabilities=["problem_solving", "solution_design"],
            input_requirements={"verified_hypothesis": "from:step_verify"},
            output_produces=["solution_proposal", "implementation_plan"],
            depends_on=["step_verify"],
            timeout_seconds=600,
        ),
        TaskStep(
            step_id="step_implement",
            name="实施修复",
            description="实施解决方案",
            assigned_role=AgentRole.SOLVER,
            required_capabilities=["system_modification", "deployment"],
            input_requirements={"solution": "from:step_solution"},
            output_produces=["implemented_fix", "deployment_status"],
            depends_on=["step_solution"],
            timeout_seconds=900,
        ),
        TaskStep(
            step_id="step_verify_fix",
            name="验证修复",
            description="验证修复是否有效",
            assigned_role=AgentRole.DIAGNOSTIC,
            required_capabilities=["verification_testing"],
            input_requirements={"fix": "from:step_implement"},
            output_produces=["verification_result", "monitoring_config"],
            depends_on=["step_implement"],
            timeout_seconds=300,
        ),
    ],
    parallel_allowed=True,
    max_concurrent_steps=2,
    rollback_on_failure=True,
)

DIAGNOSTIC_TEMPLATE = CollaborationTemplate(
    template_id="tpl_diagnostic",
    name="问题诊断",
    description="系统性问题诊断和解决的标准流程",
    template_type=TemplateType.DIAGNOSTIC,
    version="1.0",
    roles={
        "diagnostic_agent": AgentRole.DIAGNOSTIC,
        "solver_agent": AgentRole.SOLVER,
    },
    role_requirements={
        "diagnostic": ["log_analysis", "root_cause_analysis", "system_knowledge", "verification_testing"],
        "solver": ["problem_solving", "solution_design", "system_modification", "deployment"],
    },
    workflow=DIAGNOSTIC_WORKFLOW,
    max_participants=4,
    min_participants=2,
    timeout_seconds=7200,
    tags=["诊断", "故障排除", "问题解决", "运维"],
    is_preset=True,
)


# ==================== 知识共享模板 ====================

KNOWLEDGE_SHARING_WORKFLOW = WorkflowDefinition(
    workflow_id="wf_knowledge_sharing",
    name="知识共享工作流",
    description="知识传递和学习的标准流程",
    steps=[
        TaskStep(
            step_id="step_assess",
            name="知识评估",
            description="评估学习者的当前知识水平",
            assigned_role=AgentRole.TEACHER,
            required_capabilities=["knowledge_assessment", "questioning"],
            output_produces=["knowledge_gap_analysis", "learning_objectives"],
            timeout_seconds=300,
        ),
        TaskStep(
            step_id="step_prepare",
            name="内容准备",
            description="准备教学内容和材料",
            assigned_role=AgentRole.TEACHER,
            required_capabilities=["content_creation", "knowledge_curation"],
            input_requirements={"objectives": "from:step_assess"},
            output_produces=["teaching_materials", "examples"],
            depends_on=["step_assess"],
            timeout_seconds=600,
        ),
        TaskStep(
            step_id="step_present",
            name="知识讲授",
            description="讲授核心概念和知识",
            assigned_role=AgentRole.TEACHER,
            required_capabilities=["teaching", "communication"],
            input_requirements={"materials": "from:step_prepare"},
            output_produces=["presented_knowledge", "questions_raised"],
            depends_on=["step_prepare"],
            timeout_seconds=1800,
        ),
        TaskStep(
            step_id="step_learn",
            name="主动学习",
            description="学习者通过实践学习",
            assigned_role=AgentRole.LEARNER,
            required_capabilities=["active_learning"],
            input_requirements={"knowledge": "from:step_present"},
            output_produces=["learned_concepts", "practice_results"],
            depends_on=["step_present"],
            timeout_seconds=1800,
        ),
        TaskStep(
            step_id="step_practice",
            name="练习与反馈",
            description="完成练习并获得反馈",
            assigned_role=AgentRole.TEACHER,
            required_capabilities=["feedback", "assessment"],
            input_requirements={"practice": "from:step_learn"},
            output_produces=["feedback", "improvement_suggestions"],
            depends_on=["step_learn"],
            timeout_seconds=600,
        ),
        TaskStep(
            step_id="step_evaluate",
            name="效果评估",
            description="评估学习效果",
            assigned_role=AgentRole.TEACHER,
            required_capabilities=["evaluation", "testing"],
            input_requirements={"practice_results": "from:step_practice"},
            output_produces=["evaluation_report", "certification"],
            depends_on=["step_practice"],
            timeout_seconds=300,
        ),
    ],
    parallel_allowed=False,
    max_concurrent_steps=1,
    rollback_on_failure=False,
)

KNOWLEDGE_SHARING_TEMPLATE = CollaborationTemplate(
    template_id="tpl_knowledge_sharing",
    name="知识共享",
    description="知识传递和学习的标准流程",
    template_type=TemplateType.KNOWLEDGE_SHARING,
    version="1.0",
    roles={
        "teacher_agent": AgentRole.TEACHER,
        "learner_agent": AgentRole.LEARNER,
    },
    role_requirements={
        "teacher": ["knowledge_assessment", "content_creation", "teaching", "feedback", "evaluation"],
        "learner": ["active_learning", "receptive_learning"],
    },
    workflow=KNOWLEDGE_SHARING_WORKFLOW,
    max_participants=10,
    min_participants=2,
    timeout_seconds=14400,
    allow_observer=True,
    tags=["学习", "教学", "知识传递", "培训"],
    is_preset=True,
)


# ==================== 预设模板集合 ====================

PRESET_TEMPLATES = [
    CODE_REVIEW_TEMPLATE,
    PAIR_PROGRAMMING_TEMPLATE,
    DIAGNOSTIC_TEMPLATE,
    KNOWLEDGE_SHARING_TEMPLATE,
]
