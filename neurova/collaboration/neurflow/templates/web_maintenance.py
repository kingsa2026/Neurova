"""
网站维护工作流模板

流程：内容抓取 → SEO 分析 → 内容更新 → 死链检测

典型场景：
- 网站维护
- SEO 优化
- 内容更新
- 链接检查
"""

import time
import uuid
from typing import Any, Dict, List

from ..models import WorkflowDefinition, WorkflowStatus
from .builder import buildEdges, buildNodes, buildVariables


def get_web_maintenance_template() -> WorkflowDefinition:
    """获取网站维护工作流模板

    Returns:
        预定义的网站维护工作流定义
    """
    return WorkflowDefinition(
        id=f"template_web_maintenance_{uuid.uuid4().hex[:8]}",
        name="网站维护",
        description="内容抓取 → SEO 分析 → 内容更新 → 死链检测",
        version="1.0.0",
        nodes=buildNodes(_NODE_SPECS),
        edges=buildEdges(_EDGE_SPECS),
        variables=buildVariables(_VARIABLE_SPECS),
        tags=["web", "seo", "maintenance", "content", "links"],
        category="web_maintenance",
        author="Neurflow",
        created_at=time.time(),
        updated_at=time.time(),
        status=WorkflowStatus.DRAFT,
        template=True,
        public=True,
        metadata={
            "difficulty": "intermediate",
            "estimated_time": "20-40 minutes",
            "required_skills": ["web", "seo", "content-management"],
            "description": "自动化网站维护流程",
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
                "website_url": {
                    "type": "input",
                    "required": True,
                    "description": "网站 URL",
                },
                "maintenance_type": {
                    "type": "select",
                    "options": ["全面维护", "SEO优化", "内容更新", "链接检查"],
                    "default": "全面维护",
                    "description": "维护类型",
                },
                "depth": {
                    "type": "slider",
                    "min": 1,
                    "max": 5,
                    "default": 3,
                    "description": "抓取深度",
                },
            },
        },
    },
    {
        "id": "scrape",
        "type": "builtin:web-scrape",
        "x": 400,
        "y": 100,
        "label": "内容抓取",
        "config": {
            "url": "{{website_url}}",
            "selector": "auto",
            "pagination": True,
        },
    },
    {
        "id": "seo_analysis",
        "type": "builtin:seo-optimize",
        "x": 700,
        "y": 50,
        "label": "SEO 分析",
        "config": {
            "content": "{{scrape.output}}",
            "keywords": "auto",
            "target_url": "{{website_url}}",
        },
    },
    {
        "id": "broken_links",
        "type": "builtin:broken-link-check",
        "x": 700,
        "y": 200,
        "label": "死链检测",
        "config": {
            "url": "{{website_url}}",
            "depth": "{{depth}}",
        },
    },
    {
        "id": "content_update",
        "type": "builtin:llm",
        "x": 1000,
        "y": 50,
        "label": "内容更新",
        "config": {
            "prompt": """根据 SEO 分析结果更新网站内容：

原始内容：{{scrape.output}}
SEO 分析：{{seo_analysis.output}}

要求：
1. 应用 SEO 建议
2. 提升内容质量
3. 保持原有结构
4. 优化关键词密度

输出更新后的内容：""",
            "temperature": 0.3,
            "max_tokens": 3000,
        },
    },
    {
        "id": "fix_links",
        "type": "builtin:llm",
        "x": 1000,
        "y": 200,
        "label": "链接修复",
        "config": {
            "prompt": """修复以下死链：

死链列表：{{broken_links.output}}
网站 URL：{{website_url}}

要求：
1. 分析死链原因
2. 提供修复建议
3. 生成修复脚本
4. 预防措施

输出修复方案：""",
            "temperature": 0.2,
            "max_tokens": 1500,
        },
    },
    {
        "id": "generate_report",
        "type": "builtin:llm",
        "x": 1300,
        "y": 100,
        "label": "报告生成",
        "config": {
            "prompt": """生成网站维护报告：

网站 URL：{{website_url}}
维护类型：{{maintenance_type}}
SEO 分析：{{seo_analysis.output}}
死链检测：{{broken_links.output}}
内容更新：{{content_update.output}}
链接修复：{{fix_links.output}}

要求：
1. 维护摘要
2. 详细分析
3. 修复结果
4. 优化建议
5. 后续计划

输出格式：Markdown""",
            "temperature": 0.3,
            "max_tokens": 2000,
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
                "seo_analysis": "{{seo_analysis.output}}",
                "broken_links": "{{broken_links.output}}",
                "content_update": "{{content_update.output}}",
                "link_fix": "{{fix_links.output}}",
                "report": "{{generate_report.output}}",
                "url": "{{website_url}}",
            },
        },
    },
]

# 边声明式 spec：id/source/target（条件边带 source_handle）
_EDGE_SPECS: List[Dict[str, Any]] = [
    {
        "id": "e1",
        "source": "start",
        "target": "scrape",
    },
    {
        "id": "e2",
        "source": "scrape",
        "target": "seo_analysis",
    },
    {
        "id": "e3",
        "source": "scrape",
        "target": "broken_links",
    },
    {
        "id": "e4",
        "source": "seo_analysis",
        "target": "content_update",
    },
    {
        "id": "e5",
        "source": "broken_links",
        "target": "fix_links",
    },
    {
        "id": "e6",
        "source": "content_update",
        "target": "generate_report",
    },
    {
        "id": "e7",
        "source": "fix_links",
        "target": "generate_report",
    },
    {
        "id": "e8",
        "source": "generate_report",
        "target": "end",
    },
]

# 变量声明式 spec：name/type/默认值/描述/作用域
_VARIABLE_SPECS: List[Dict[str, Any]] = [
    {
        "name": "check_frequency",
        "type": "string",
        "default_value": "weekly",
        "description": "检查频率",
        "scope": "workflow",
    },
    {
        "name": "auto_fix",
        "type": "boolean",
        "default_value": False,
        "description": "是否自动修复",
        "scope": "workflow",
    },
]


__all__ = ["get_web_maintenance_template"]
