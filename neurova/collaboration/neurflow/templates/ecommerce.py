"""
电商运营工作流模板

流程：商品监控 → 价格分析 → 广告文案 → 自动回复

典型场景：
- 电商运营
- 商品管理
- 价格监控
- 客户服务
"""
import time
import uuid
from typing import Dict, List, Any

from ..models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, NodeCategory
)


def get_ecommerce_template() -> WorkflowDefinition:
    """获取电商运营工作流模板
    
    Returns:
        预定义的电商运营工作流定义
    """
    nodes = _create_nodes()
    edges = _create_edges()
    variables = _create_variables()
    
    return WorkflowDefinition(
        id=f"template_ecommerce_{uuid.uuid4().hex[:8]}",
        name="电商运营",
        description="商品监控 → 价格分析 → 广告文案 → 自动回复",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=variables,
        tags=["ecommerce", "retail", "marketing", "customer-service"],
        category="ecommerce",
        author="Neurflow",
        created_at=time.time(),
        updated_at=time.time(),
        status=WorkflowStatus.DRAFT,
        template=True,
        public=True,
        metadata={
            "difficulty": "intermediate",
            "estimated_time": "15-30 minutes",
            "required_skills": ["ecommerce", "marketing", "customer-service"],
            "description": "自动化电商运营流程",
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
                    "platform": {
                        "type": "select",
                        "options": ["淘宝", "京东", "拼多多", "亚马逊", "独立站"],
                        "default": "淘宝",
                        "description": "电商平台",
                    },
                    "product_category": {
                        "type": "textarea",
                        "required": True,
                        "description": "商品类目",
                    },
                    "monitor_type": {
                        "type": "select",
                        "options": ["价格监控", "库存监控", "评价监控", "竞品监控"],
                        "default": "价格监控",
                        "description": "监控类型",
                    }
                }
            },
            label="开始",
        ),
        
        WorkflowNode(
            id="monitor",
            type="builtin:price-monitor",
            position={"x": 400, "y": 100},
            config={
                "products": "{{product_category}}",
                "alert_threshold": 0.1,
            },
            label="商品监控",
        ),
        
        WorkflowNode(
            id="analyze",
            type="builtin:llm",
            position={"x": 700, "y": 100},
            config={
                "prompt": """分析以下监控数据：

监控结果：{{monitor.output}}
平台：{{platform}}
类目：{{product_category}}

要求：
1. 价格趋势分析
2. 竞争对手分析
3. 市场机会识别
4. 风险预警
5. 行动建议

输出格式：JSON""",
                "temperature": 0.3,
                "max_tokens": 1500,
            },
            label="价格分析",
        ),
        
        WorkflowNode(
            id="ad_copy",
            type="builtin:ad-copy",
            position={"x": 1000, "y": 50},
            config={
                "product": "{{product_category}}",
                "platform": "{{platform}}",
                "style": "促销",
            },
            label="广告文案",
        ),
        
        WorkflowNode(
            id="review_respond",
            type="builtin:review-respond",
            position={"x": 1000, "y": 200},
            config={
                "reviews": "{{monitor.output.reviews}}",
                "tone": "专业友好",
                "templates": "default",
            },
            label="评价回复",
        ),
        
        WorkflowNode(
            id="merge",
            type="builtin:merge",
            position={"x": 1300, "y": 100},
            config={
                "strategy": "all",
            },
            label="结果合并",
        ),
        
        WorkflowNode(
            id="end",
            type="builtin:end",
            position={"x": 1600, "y": 100},
            config={
                "output_mapping": {
                    "analysis": "{{analyze.output}}",
                    "ad_copy": "{{ad_copy.output}}",
                    "review_responses": "{{review_respond.output}}",
                    "platform": "{{platform}}",
                    "category": "{{product_category}}",
                },
            },
            label="结束",
        ),
    ]


def _create_edges() -> List[WorkflowEdge]:
    """创建边连接"""
    return [
        WorkflowEdge(id="e1", source="start", target="monitor"),
        WorkflowEdge(id="e2", source="monitor", target="analyze"),
        WorkflowEdge(id="e3", source="analyze", target="ad_copy"),
        WorkflowEdge(id="e4", source="analyze", target="review_respond"),
        WorkflowEdge(id="e5", source="ad_copy", target="merge"),
        WorkflowEdge(id="e6", source="review_respond", target="merge"),
        WorkflowEdge(id="e7", source="merge", target="end"),
    ]


def _create_variables() -> List[WorkflowVariable]:
    """创建工作流变量"""
    return [
        WorkflowVariable(
            name="price_alert_threshold",
            type="number",
            default_value=0.1,
            description="价格变动阈值（10%）",
            scope="workflow",
        ),
        WorkflowVariable(
            name="auto_publish",
            type="boolean",
            default_value=False,
            description="是否自动发布广告文案",
            scope="workflow",
        ),
    ]


__all__ = ["get_ecommerce_template"]