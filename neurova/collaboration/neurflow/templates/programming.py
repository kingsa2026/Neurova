"""
编程助手工作流模板

流程：需求分析 → TDD 实现 → 进化学习

典型场景：
- 自动化编程任务
- 代码生成和优化
- 测试驱动开发
- 代码审查和改进
"""

import time
import uuid
from typing import List

from ..models import WorkflowDefinition, WorkflowEdge, WorkflowNode, WorkflowStatus, WorkflowVariable


def get_programming_template() -> WorkflowDefinition:
    """获取编程助手工作流模板

    Returns:
        预定义的编程助手工作流定义
    """
    # 创建节点
    nodes = _create_nodes()

    # 创建边
    edges = _create_edges()

    # 创建变量
    variables = _create_variables()

    # 创建工作流定义
    return WorkflowDefinition(
        id=f"template_programming_{uuid.uuid4().hex[:8]}",
        name="编程助手",
        description="自动化编程任务：需求分析 → TDD 实现 → 进化学习",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=variables,
        tags=["programming", "tdd", "automation", "code-generation"],
        category="programming",
        author="Neurflow",
        created_at=time.time(),
        updated_at=time.time(),
        status=WorkflowStatus.DRAFT,
        template=True,
        public=True,
        metadata={
            "difficulty": "intermediate",
            "estimated_time": "15-30 minutes",
            "required_skills": ["programming", "testing"],
            "description": "使用 TDD 方法自动生成和优化代码",
        },
    )


def _create_nodes() -> List[WorkflowNode]:
    """创建模板节点"""
    return [
        # 开始节点
        WorkflowNode(
            id="start",
            type="builtin:start",
            position={"x": 100, "y": 100},
            config={
                "inputs_schema": {
                    "requirements": {
                        "type": "textarea",
                        "required": True,
                        "description": "编程需求描述",
                    },
                    "language": {
                        "type": "select",
                        "options": ["Python", "JavaScript", "TypeScript", "Java", "Go"],
                        "default": "Python",
                        "description": "目标编程语言",
                    },
                    "test_framework": {
                        "type": "select",
                        "options": ["pytest", "jest", "junit", "go test"],
                        "default": "pytest",
                        "description": "测试框架",
                    },
                }
            },
            label="开始",
            metadata={"category": "flow"},
        ),
        # 需求分析节点（LLM）
        WorkflowNode(
            id="analyze_requirements",
            type="builtin:llm",
            position={"x": 400, "y": 100},
            config={
                "prompt": """分析以下编程需求，并生成详细的技术规格：

需求：{{requirements}}
编程语言：{{language}}
测试框架：{{test_framework}}

请提供：
1. 功能分解（主要模块和函数）
2. 接口设计（输入/输出）
3. 测试用例设计（边界条件、正常流程、异常情况）
4. 实现策略（算法选择、数据结构）

输出格式：JSON""",
                "temperature": 0.3,
                "max_tokens": 2000,
            },
            label="需求分析",
            metadata={"category": "ai"},
        ),
        # TDD 实现节点
        WorkflowNode(
            id="tdd_implementation",
            type="builtin:tdd",
            position={"x": 700, "y": 100},
            config={
                "test_spec": """根据以下技术规格生成测试用例：

{{analyze_requirements.output}}

编程语言：{{language}}
测试框架：{{test_framework}}

要求：
1. 覆盖所有功能点
2. 包含边界条件测试
3. 包含异常处理测试
4. 测试代码可直接运行""",
                "implementation_prompt": """根据以下测试用例实现代码：

{{tdd_implementation.tests}}

技术规格：
{{analyze_requirements.output}}

要求：
1. 实现所有测试用例
2. 代码简洁、可读
3. 遵循最佳实践
4. 包含必要的错误处理""",
                "max_iterations": 5,
                "pass_threshold": 0.9,
            },
            label="TDD 实现",
            metadata={"category": "ai"},
        ),
        # 代码审查节点（LLM）
        WorkflowNode(
            id="code_review",
            type="builtin:llm",
            position={"x": 1000, "y": 100},
            config={
                "prompt": """审查以下代码实现：

实现代码：
{{tdd_implementation.output}}

测试结果：
{{tdd_implementation.tests}}

请提供：
1. 代码质量评分（1-10）
2. 性能分析
3. 安全性检查
4. 改进建议
5. 重构建议（如果需要）

输出格式：JSON""",
                "temperature": 0.2,
                "max_tokens": 1500,
            },
            label="代码审查",
            metadata={"category": "ai"},
        ),
        # 条件节点（检查代码质量）
        WorkflowNode(
            id="quality_check",
            type="builtin:condition",
            position={"x": 1300, "y": 100},
            config={
                "expression": "{{code_review.output.score}} >= 8",
                "branches": [
                    {"label": "高质量", "condition": "true"},
                    {"label": "需要改进", "condition": "false"},
                ],
            },
            label="质量检查",
            metadata={"category": "flow"},
        ),
        # 进化学习节点（代码质量高时）
        WorkflowNode(
            id="evolution_learning",
            type="builtin:evolution",
            position={"x": 1600, "y": 50},
            config={
                "mode": "learn",
                "feedback_data": {
                    "task_type": "code_generation",
                    "language": "{{language}}",
                    "quality_score": "{{code_review.output.score}}",
                    "test_pass_rate": "{{tdd_implementation.pass_rate}}",
                    "implementation": "{{tdd_implementation.output}}",
                    "review": "{{code_review.output}}",
                },
            },
            label="进化学习",
            metadata={"category": "ai"},
        ),
        # 代码优化节点（代码质量低时）
        WorkflowNode(
            id="code_optimization",
            type="builtin:llm",
            position={"x": 1600, "y": 200},
            config={
                "prompt": """根据审查结果优化代码：

原始实现：
{{tdd_implementation.output}}

审查反馈：
{{code_review.output}}

要求：
1. 应用所有改进建议
2. 保持测试通过
3. 提高代码质量

输出优化后的代码：""",
                "temperature": 0.3,
                "max_tokens": 2000,
            },
            label="代码优化",
            metadata={"category": "ai"},
        ),
        # 合并节点
        WorkflowNode(
            id="merge_results",
            type="builtin:merge",
            position={"x": 1900, "y": 100},
            config={
                "strategy": "first",
            },
            label="合并结果",
            metadata={"category": "flow"},
        ),
        # 结束节点
        WorkflowNode(
            id="end",
            type="builtin:end",
            position={"x": 2200, "y": 100},
            config={
                "output_mapping": {
                    "code": "{{tdd_implementation.output}}",
                    "tests": "{{tdd_implementation.tests}}",
                    "quality_score": "{{code_review.output.score}}",
                    "review": "{{code_review.output}}",
                    "language": "{{language}}",
                },
            },
            label="结束",
            metadata={"category": "flow"},
        ),
    ]


def _create_edges() -> List[WorkflowEdge]:
    """创建边连接"""
    return [
        # 开始 → 需求分析
        WorkflowEdge(
            id="start_to_analyze",
            source="start",
            target="analyze_requirements",
        ),
        # 需求分析 → TDD 实现
        WorkflowEdge(
            id="analyze_to_tdd",
            source="analyze_requirements",
            target="tdd_implementation",
        ),
        # TDD 实现 → 代码审查
        WorkflowEdge(
            id="tdd_to_review",
            source="tdd_implementation",
            target="code_review",
        ),
        # 代码审查 → 质量检查
        WorkflowEdge(
            id="review_to_check",
            source="code_review",
            target="quality_check",
        ),
        # 质量检查 → 进化学习（高质量）
        WorkflowEdge(
            id="check_to_evolution",
            source="quality_check",
            target="evolution_learning",
            source_handle="true",
        ),
        # 质量检查 → 代码优化（需要改进）
        WorkflowEdge(
            id="check_to_optimization",
            source="quality_check",
            target="code_optimization",
            source_handle="false",
        ),
        # 进化学习 → 合并结果
        WorkflowEdge(
            id="evolution_to_merge",
            source="evolution_learning",
            target="merge_results",
        ),
        # 代码优化 → 合并结果
        WorkflowEdge(
            id="optimization_to_merge",
            source="code_optimization",
            target="merge_results",
        ),
        # 合并结果 → 结束
        WorkflowEdge(
            id="merge_to_end",
            source="merge_results",
            target="end",
        ),
    ]


def _create_variables() -> List[WorkflowVariable]:
    """创建工作流变量"""
    return [
        WorkflowVariable(
            name="max_iterations",
            type="number",
            default_value=5,
            description="TDD 最大迭代次数",
            scope="workflow",
        ),
        WorkflowVariable(
            name="quality_threshold",
            type="number",
            default_value=8,
            description="代码质量阈值（1-10）",
            scope="workflow",
        ),
        WorkflowVariable(
            name="include_comments",
            type="boolean",
            default_value=True,
            description="是否包含代码注释",
            scope="workflow",
        ),
    ]


# 便捷导出
__all__ = ["get_programming_template"]
