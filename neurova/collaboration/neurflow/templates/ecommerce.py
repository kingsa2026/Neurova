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
from typing import Any, Dict, List

from ..models import WorkflowDefinition, WorkflowStatus
from .builder import buildEdges, buildNodes, buildVariables


def get_ecommerce_template() -> WorkflowDefinition:
    """获取电商运营工作流模板

    Returns:
        预定义的电商运营工作流定义
    """
    return WorkflowDefinition(
        id=f"template_ecommerce_{uuid.uuid4().hex[:8]}",
        name="电商运营",
        description="商品监控 → 价格分析 → 广告文案 → 自动回复",
        version="1.0.0",
        nodes=buildNodes(_NODE_SPECS),
        edges=buildEdges(_EDGE_SPECS),
        variables=buildVariables(_VARIABLE_SPECS),
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
                },
            },
        },
    },
    {
        "id": "monitor",
        "type": "builtin:price-monitor",
        "x": 400,
        "y": 100,
        "label": "商品监控",
        "config": {
            "products": "{{product_category}}",
            "alert_threshold": 0.1,
        },
    },
    {
        "id": "analyze",
        "type": "builtin:llm",
        "x": 700,
        "y": 100,
        "label": "价格分析",
        "config": {
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
    },
    {
        "id": "ad_copy",
        "type": "builtin:ad-copy",
        "x": 1000,
        "y": 50,
        "label": "广告文案",
        "config": {
            "product": "{{product_category}}",
            "platform": "{{platform}}",
            "style": "促销",
        },
    },
    {
        "id": "review_respond",
        "type": "builtin:review-respond",
        "x": 1000,
        "y": 200,
        "label": "评价回复",
        "config": {
            "reviews": "{{monitor.output.reviews}}",
            "tone": "专业友好",
            "templates": "default",
        },
    },
    {
        "id": "merge",
        "type": "builtin:merge",
        "x": 1300,
        "y": 100,
        "label": "结果合并",
        "config": {
            "strategy": "all",
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
                "ad_copy": "{{ad_copy.output}}",
                "review_responses": "{{review_respond.output}}",
                "platform": "{{platform}}",
                "category": "{{product_category}}",
            },
        },
    },
]

# 边声明式 spec：id/source/target（条件边带 source_handle）
_EDGE_SPECS: List[Dict[str, Any]] = [
    {
        "id": "e1",
        "source": "start",
        "target": "monitor",
    },
    {
        "id": "e2",
        "source": "monitor",
        "target": "analyze",
    },
    {
        "id": "e3",
        "source": "analyze",
        "target": "ad_copy",
    },
    {
        "id": "e4",
        "source": "analyze",
        "target": "review_respond",
    },
    {
        "id": "e5",
        "source": "ad_copy",
        "target": "merge",
    },
    {
        "id": "e6",
        "source": "review_respond",
        "target": "merge",
    },
    {
        "id": "e7",
        "source": "merge",
        "target": "end",
    },
]

# 变量声明式 spec：name/type/默认值/描述/作用域
_VARIABLE_SPECS: List[Dict[str, Any]] = [
    {
        "name": "price_alert_threshold",
        "type": "number",
        "default_value": 0.1,
        "description": "价格变动阈值（10%）",
        "scope": "workflow",
    },
    {
        "name": "auto_publish",
        "type": "boolean",
        "default_value": False,
        "description": "是否自动发布广告文案",
        "scope": "workflow",
    },
]


__all__ = ["get_ecommerce_template"]
