"""
文档处理工作流模板

流程：读取 → 分析 → 格式化 → 输出 DOC/PDF/PPT

典型场景：
- 文档转换
- 文档分析
- 报告生成
- 内容提取
"""
import time
import uuid
from typing import Dict, List, Any

from ..models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, NodeCategory
)


def get_document_template() -> WorkflowDefinition:
    """获取文档处理工作流模板
    
    Returns:
        预定义的文档处理工作流定义
    """
    nodes = _create_nodes()
    edges = _create_edges()
    variables = _create_variables()
    
    return WorkflowDefinition(
        id=f"template_document_{uuid.uuid4().hex[:8]}",
        name="文档处理",
        description="读取 → 分析 → 格式化 → 输出 DOC/PDF/PPT",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=variables,
        tags=["document", "pdf", "docx", "ppt", "conversion"],
        category="document",
        author="Neurflow",
        created_at=time.time(),
        updated_at=time.time(),
        status=WorkflowStatus.DRAFT,
        template=True,
        public=True,
        metadata={
            "difficulty": "beginner",
            "estimated_time": "10-20 minutes",
            "required_skills": ["document", "formatting"],
            "description": "自动化文档处理流程",
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
                    "file_path": {
                        "type": "file",
                        "required": True,
                        "description": "输入文档路径",
                        "file_types": [".docx", ".pdf", ".txt", ".md"],
                    },
                    "output_format": {
                        "type": "select",
                        "options": ["DOCX", "PDF", "PPTX", "Markdown", "HTML"],
                        "default": "PDF",
                        "description": "输出格式",
                    },
                    "analysis_type": {
                        "type": "select",
                        "options": ["摘要", "关键词提取", "结构分析", "情感分析", "翻译"],
                        "default": "摘要",
                        "description": "分析类型",
                    }
                }
            },
            label="开始",
        ),
        
        WorkflowNode(
            id="read_doc",
            type="builtin:doc-read",
            position={"x": 400, "y": 100},
            config={
                "file_path": "{{file_path}}",
                "format": "auto",
            },
            label="读取文档",
        ),
        
        WorkflowNode(
            id="analyze",
            type="builtin:llm",
            position={"x": 700, "y": 100},
            config={
                "prompt": """分析以下文档内容：

{{read_doc.output}}

分析类型：{{analysis_type}}

要求：
1. 提供详细分析结果
2. 保持原文关键信息
3. 结构化输出
4. 适合进一步处理

输出格式：JSON""",
                "temperature": 0.3,
                "max_tokens": 2000,
            },
            label="内容分析",
        ),
        
        WorkflowNode(
            id="format",
            type="builtin:llm",
            position={"x": 1000, "y": 100},
            config={
                "prompt": """根据分析结果格式化文档：

分析结果：{{analyze.output}}
原始内容：{{read_doc.output}}
输出格式：{{output_format}}

要求：
1. 保持分析结果的完整性
2. 适合目标格式
3. 包含必要的元数据
4. 格式规范

输出格式化后的内容：""",
                "temperature": 0.2,
                "max_tokens": 3000,
            },
            label="文档格式化",
        ),
        
        WorkflowNode(
            id="save",
            type="builtin:doc-write",
            position={"x": 1300, "y": 100},
            config={
                "content": "{{format.output}}",
                "format": "{{output_format}}",
                "template": "default",
            },
            label="保存文档",
        ),
        
        WorkflowNode(
            id="end",
            type="builtin:end",
            position={"x": 1600, "y": 100},
            config={
                "output_mapping": {
                    "analysis": "{{analyze.output}}",
                    "formatted_content": "{{format.output}}",
                    "output_path": "{{save.output.path}}",
                    "format": "{{output_format}}",
                },
            },
            label="结束",
        ),
    ]


def _create_edges() -> List[WorkflowEdge]:
    """创建边连接"""
    return [
        WorkflowEdge(id="e1", source="start", target="read_doc"),
        WorkflowEdge(id="e2", source="read_doc", target="analyze"),
        WorkflowEdge(id="e3", source="analyze", target="format"),
        WorkflowEdge(id="e4", source="format", target="save"),
        WorkflowEdge(id="e5", source="save", target="end"),
    ]


def _create_variables() -> List[WorkflowVariable]:
    """创建工作流变量"""
    return [
        WorkflowVariable(
            name="language",
            type="string",
            default_value="中文",
            description="文档语言",
            scope="workflow",
        ),
        WorkflowVariable(
            name="include_images",
            type="boolean",
            default_value=True,
            description="是否包含图片",
            scope="workflow",
        ),
    ]


__all__ = ["get_document_template"]