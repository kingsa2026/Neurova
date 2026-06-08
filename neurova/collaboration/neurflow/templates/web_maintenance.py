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
from typing import Dict, List, Any

from ..models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, NodeCategory
)


def get_web_maintenance_template() -> WorkflowDefinition:
    """获取网站维护工作流模板
    
    Returns:
        预定义的网站维护工作流定义
    """
    nodes = _create_nodes()
    edges = _create_edges()
    variables = _create_variables()
    
    return WorkflowDefinition(
        id=f"template_web_maintenance_{uuid.uuid4().hex[:8]}",
        name="网站维护",
        description="内容抓取 → SEO 分析 → 内容更新 → 死链检测",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=variables,
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
                    }
                }
            },
            label="开始",
        ),
        
        WorkflowNode(
            id="scrape",
            type="builtin:web-scrape",
            position={"x": 400, "y": 100},
            config={
                "url": "{{website_url}}",
                "selector": "auto",
                "pagination": True,
            },
            label="内容抓取",
        ),
        
        WorkflowNode(
            id="seo_analysis",
            type="builtin:seo-optimize",
            position={"x": 700, "y": 50},
            config={
                "content": "{{scrape.output}}",
                "keywords": "auto",
                "target_url": "{{website_url}}",
            },
            label="SEO 分析",
        ),
        
        WorkflowNode(
            id="broken_links",
            type="builtin:broken-link-check",
            position={"x": 700, "y": 200},
            config={
                "url": "{{website_url}}",
                "depth": "{{depth}}",
            },
            label="死链检测",
        ),
        
        WorkflowNode(
            id="content_update",
            type="builtin:llm",
            position={"x": 1000, "y": 50},
            config={
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
            label="内容更新",
        ),
        
        WorkflowNode(
            id="fix_links",
            type="builtin:llm",
            position={"x": 1000, "y": 200},
            config={
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
            label="链接修复",
        ),
        
        WorkflowNode(
            id="generate_report",
            type="builtin:llm",
            position={"x": 1300, "y": 100},
            config={
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
            label="报告生成",
        ),
        
        WorkflowNode(
            id="end",
            type="builtin:end",
            position={"x": 1600, "y": 100},
            config={
                "output_mapping": {
                    "seo_analysis": "{{seo_analysis.output}}",
                    "broken_links": "{{broken_links.output}}",
                    "content_update": "{{content_update.output}}",
                    "link_fix": "{{fix_links.output}}",
                    "report": "{{generate_report.output}}",
                    "url": "{{website_url}}",
                },
            },
            label="结束",
        ),
    ]


def _create_edges() -> List[WorkflowEdge]:
    """创建边连接"""
    return [
        WorkflowEdge(id="e1", source="start", target="scrape"),
        WorkflowEdge(id="e2", source="scrape", target="seo_analysis"),
        WorkflowEdge(id="e3", source="scrape", target="broken_links"),
        WorkflowEdge(id="e4", source="seo_analysis", target="content_update"),
        WorkflowEdge(id="e5", source="broken_links", target="fix_links"),
        WorkflowEdge(id="e6", source="content_update", target="generate_report"),
        WorkflowEdge(id="e7", source="fix_links", target="generate_report"),
        WorkflowEdge(id="e8", source="generate_report", target="end"),
    ]


def _create_variables() -> List[WorkflowVariable]:
    """创建工作流变量"""
    return [
        WorkflowVariable(
            name="check_frequency",
            type="string",
            default_value="weekly",
            description="检查频率",
            scope="workflow",
        ),
        WorkflowVariable(
            name="auto_fix",
            type="boolean",
            default_value=False,
            description="是否自动修复",
            scope="workflow",
        ),
    ]


__all__ = ["get_web_maintenance_template"]