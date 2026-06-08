"""
文学创作工作流模板

流程：大纲 → 检索参考 → 撰写 → 人工审核 → 润色 → 输出

典型场景：
- 文章写作
- 小说创作
- 报告撰写
- 内容生成
"""
import time
import uuid
from typing import Dict, List, Any

from ..models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, NodeCategory
)


def get_writing_template() -> WorkflowDefinition:
    """获取文学创作工作流模板
    
    Returns:
        预定义的文学创作工作流定义
    """
    nodes = _create_nodes()
    edges = _create_edges()
    variables = _create_variables()
    
    return WorkflowDefinition(
        id=f"template_writing_{uuid.uuid4().hex[:8]}",
        name="文学创作",
        description="大纲 → 检索参考 → 撰写 → 人工审核 → 润色 → 输出",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=variables,
        tags=["writing", "content", "creative", "article"],
        category="writing",
        author="Neurflow",
        created_at=time.time(),
        updated_at=time.time(),
        status=WorkflowStatus.DRAFT,
        template=True,
        public=True,
        metadata={
            "difficulty": "beginner",
            "estimated_time": "20-40 minutes",
            "required_skills": ["writing", "creativity"],
            "description": "自动化文学创作流程",
        }
    )


def _create_nodes() -> List[WorkflowNode]:
    """创建模板节点"""
    return [
        WorkflowNode(
            id="start",
            type="builtin:start",
            position={"x": 100, "y": 100},
            config={
                "inputs_schema": {
                    "topic": {
                        "type": "textarea",
                        "required": True,
                        "description": "写作主题",
                    },
                    "style": {
                        "type": "select",
                        "options": ["正式", "非正式", "学术", "创意", "技术"],
                        "default": "正式",
                        "description": "写作风格",
                    },
                    "length": {
                        "type": "select",
                        "options": ["短文 (500字)", "中等 (1500字)", "长文 (3000字)", "自定义"],
                        "default": "中等 (1500字)",
                        "description": "文章长度",
                    }
                }
            },
            label="开始",
        ),
        
        WorkflowNode(
            id="outline",
            type="builtin:llm",
            position={"x": 400, "y": 100},
            config={
                "prompt": """为以下主题创建详细大纲：

主题：{{topic}}
风格：{{style}}
长度：{{length}}

要求：
1. 结构清晰，逻辑连贯
2. 包含引言、正文、结论
3. 列出主要观点和支持论据
4. 考虑目标读者

输出格式：Markdown 大纲""",
                "temperature": 0.5,
                "max_tokens": 1000,
            },
            label="大纲生成",
        ),
        
        WorkflowNode(
            id="research",
            type="builtin:memory-load",
            position={"x": 700, "y": 100},
            config={
                "query": "{{topic}} 相关资料",
                "limit": 5,
                "memory_type": "knowledge",
            },
            label="检索参考",
        ),
        
        WorkflowNode(
            id="draft",
            type="builtin:llm",
            position={"x": 1000, "y": 100},
            config={
                "prompt": """根据以下大纲和参考资料撰写初稿：

大纲：
{{outline.output}}

参考资料：
{{research.output}}

主题：{{topic}}
风格：{{style}}

要求：
1. 遵循大纲结构
2. 引用参考资料
3. 保持风格一致
4. 语言流畅自然

输出完整文章：""",
                "temperature": 0.7,
                "max_tokens": 3000,
            },
            label="撰写初稿",
        ),
        
        WorkflowNode(
            id="human_review",
            type="builtin:human_input",
            position={"x": 1300, "y": 100},
            config={
                "prompt": "请审核初稿并提供反馈：{{draft.output}}",
                "timeout": 300,
            },
            label="人工审核",
        ),
        
        WorkflowNode(
            id="polish",
            type="builtin:llm",
            position={"x": 1600, "y": 100},
            config={
                "prompt": """根据审核反馈润色文章：

初稿：
{{draft.output}}

审核反馈：
{{human_review.output}}

要求：
1. 应用所有修改建议
2. 提升语言质量
3. 保持风格一致
4. 检查逻辑连贯性

输出润色后的文章：""",
                "temperature": 0.3,
                "max_tokens": 3000,
            },
            label="文章润色",
        ),
        
        WorkflowNode(
            id="end",
            type="builtin:end",
            position={"x": 1900, "y": 100},
            config={
                "output_mapping": {
                    "article": "{{polish.output}}",
                    "outline": "{{outline.output}}",
                    "references": "{{research.output}}",
                    "style": "{{style}}",
                    "topic": "{{topic}}",
                },
            },
            label="结束",
        ),
    ]


def _create_edges() -> List[WorkflowEdge]:
    """创建边连接"""
    return [
        WorkflowEdge(id="e1", source="start", target="outline"),
        WorkflowEdge(id="e2", source="outline", target="research"),
        WorkflowEdge(id="e3", source="research", target="draft"),
        WorkflowEdge(id="e4", source="draft", target="human_review"),
        WorkflowEdge(id="e5", source="human_review", target="polish"),
        WorkflowEdge(id="e6", source="polish", target="end"),
    ]


def _create_variables() -> List[WorkflowVariable]:
    """创建工作流变量"""
    return [
        WorkflowVariable(
            name="tone",
            type="string",
            default_value="专业",
            description="文章基调",
            scope="workflow",
        ),
        WorkflowVariable(
            name="include_citations",
            type="boolean",
            default_value=True,
            description="是否包含引用",
            scope="workflow",
        ),
    ]


__all__ = ["get_writing_template"]