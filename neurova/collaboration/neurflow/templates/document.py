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
from typing import Any, Dict, List

from ..models import WorkflowDefinition, WorkflowStatus
from .builder import buildEdges, buildNodes, buildVariables


def get_document_template() -> WorkflowDefinition:
    """获取文档处理工作流模板

    Returns:
        预定义的文档处理工作流定义
    """
    return WorkflowDefinition(
        id=f"template_document_{uuid.uuid4().hex[:8]}",
        name="文档处理",
        description="读取 → 分析 → 格式化 → 输出 DOC/PDF/PPT",
        version="1.0.0",
        nodes=buildNodes(_NODE_SPECS),
        edges=buildEdges(_EDGE_SPECS),
        variables=buildVariables(_VARIABLE_SPECS),
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
        },
    )


# 节点声明式 spec：id/type/坐标/label/config，装配统一走 .builder
_NODE_SPECS: List[Dict[str, Any]] = [
    {
        "id": "start",
        "type": "builtin:start",
        "x": 100,
        "y": 100,
        "label": "开始",
        "config": {
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
                },
            },
        },
    },
    {
        "id": "read_doc",
        "type": "builtin:doc-read",
        "x": 400,
        "y": 100,
        "label": "读取文档",
        "config": {
            "file_path": "{{file_path}}",
            "format": "auto",
        },
    },
    {
        "id": "analyze",
        "type": "builtin:llm",
        "x": 700,
        "y": 100,
        "label": "内容分析",
        "config": {
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
    },
    {
        "id": "format",
        "type": "builtin:llm",
        "x": 1000,
        "y": 100,
        "label": "文档格式化",
        "config": {
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
    },
    {
        "id": "save",
        "type": "builtin:doc-write",
        "x": 1300,
        "y": 100,
        "label": "保存文档",
        "config": {
            "content": "{{format.output}}",
            "format": "{{output_format}}",
            "template": "default",
        },
    },
    {
        "id": "end",
        "type": "builtin:end",
        "x": 1600,
        "y": 100,
        "label": "结束",
        "config": {
            "output_mapping": {
                "analysis": "{{analyze.output}}",
                "formatted_content": "{{format.output}}",
                "output_path": "{{save.output.path}}",
                "format": "{{output_format}}",
            },
        },
    },
]

# 边声明式 spec：id/source/target（条件边带 source_handle）
_EDGE_SPECS: List[Dict[str, Any]] = [
    {
        "id": "e1",
        "source": "start",
        "target": "read_doc",
    },
    {
        "id": "e2",
        "source": "read_doc",
        "target": "analyze",
    },
    {
        "id": "e3",
        "source": "analyze",
        "target": "format",
    },
    {
        "id": "e4",
        "source": "format",
        "target": "save",
    },
    {
        "id": "e5",
        "source": "save",
        "target": "end",
    },
]

# 变量声明式 spec：name/type/默认值/描述/作用域
_VARIABLE_SPECS: List[Dict[str, Any]] = [
    {
        "name": "language",
        "type": "string",
        "default_value": "中文",
        "description": "文档语言",
        "scope": "workflow",
    },
    {
        "name": "include_images",
        "type": "boolean",
        "default_value": True,
        "description": "是否包含图片",
        "scope": "workflow",
    },
]


__all__ = ["get_document_template"]
