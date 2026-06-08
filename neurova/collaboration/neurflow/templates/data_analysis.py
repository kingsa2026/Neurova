"""
数据分析工作流模板

流程：抓取 → 清洗 → 分析 → 可视化 → 报告

典型场景：
- 数据分析
- 数据可视化
- 报告生成
- 数据挖掘
"""
import time
import uuid
from typing import Dict, List, Any

from ..models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, NodeCategory
)


def get_data_analysis_template() -> WorkflowDefinition:
    """获取数据分析工作流模板
    
    Returns:
        预定义的数据分析工作流定义
    """
    nodes = _create_nodes()
    edges = _create_edges()
    variables = _create_variables()
    
    return WorkflowDefinition(
        id=f"template_data_analysis_{uuid.uuid4().hex[:8]}",
        name="数据分析",
        description="抓取 → 清洗 → 分析 → 可视化 → 报告",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=variables,
        tags=["data", "analysis", "visualization", "report", "statistics"],
        category="data_analysis",
        author="Neurflow",
        created_at=time.time(),
        updated_at=time.time(),
        status=WorkflowStatus.DRAFT,
        template=True,
        public=True,
        metadata={
            "difficulty": "intermediate",
            "estimated_time": "20-40 minutes",
            "required_skills": ["data-analysis", "statistics", "visualization"],
            "description": "自动化数据分析流程",
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
                    "data_source": {
                        "type": "textarea",
                        "required": True,
                        "description": "数据来源（URL、文件路径或描述）",
                    },
                    "analysis_goal": {
                        "type": "textarea",
                        "required": True,
                        "description": "分析目标",
                    },
                    "output_format": {
                        "type": "select",
                        "options": ["HTML报告", "PDF报告", "Markdown", "JSON数据"],
                        "default": "HTML报告",
                        "description": "输出格式",
                    }
                }
            },
            label="开始",
        ),
        
        WorkflowNode(
            id="fetch_data",
            type="builtin:web-scrape",
            position={"x": 400, "y": 100},
            config={
                "url": "{{data_source}}",
                "selector": "auto",
                "pagination": False,
            },
            label="数据抓取",
        ),
        
        WorkflowNode(
            id="clean_data",
            type="builtin:llm",
            position={"x": 700, "y": 100},
            config={
                "prompt": """清洗以下数据：

原始数据：{{fetch_data.output}}
分析目标：{{analysis_goal}}

要求：
1. 处理缺失值
2. 标准化格式
3. 去除异常值
4. 为分析做准备

输出清洗后的数据：""",
                "temperature": 0.2,
                "max_tokens": 2000,
            },
            label="数据清洗",
        ),
        
        WorkflowNode(
            id="analyze_data",
            type="builtin:data-analyze",
            position={"x": 1000, "y": 100},
            config={
                "data": "{{clean_data.output}}",
                "analysis_type": "comprehensive",
                "columns": "auto",
            },
            label="数据分析",
        ),
        
        WorkflowNode(
            id="visualize",
            type="builtin:data-visualize",
            position={"x": 1300, "y": 50},
            config={
                "data": "{{analyze_data.output}}",
                "chart_type": "auto",
                "x_axis": "auto",
                "y_axis": "auto",
            },
            label="数据可视化",
        ),
        
        WorkflowNode(
            id="generate_report",
            type="builtin:llm",
            position={"x": 1300, "y": 200},
            config={
                "prompt": """生成数据分析报告：

分析结果：{{analyze_data.output}}
可视化图表：{{visualize.output}}
分析目标：{{analysis_goal}}

要求：
1. 包含执行摘要
2. 详细分析结果
3. 关键发现
4. 建议和结论
5. 图表说明

输出格式：{{output_format}}""",
                "temperature": 0.3,
                "max_tokens": 3000,
            },
            label="报告生成",
        ),
        
        WorkflowNode(
            id="end",
            type="builtin:end",
            position={"x": 1600, "y": 100},
            config={
                "output_mapping": {
                    "analysis": "{{analyze_data.output}}",
                    "visualization": "{{visualize.output}}",
                    "report": "{{generate_report.output}}",
                    "format": "{{output_format}}",
                },
            },
            label="结束",
        ),
    ]


def _create_edges() -> List[WorkflowEdge]:
    """创建边连接"""
    return [
        WorkflowEdge(id="e1", source="start", target="fetch_data"),
        WorkflowEdge(id="e2", source="fetch_data", target="clean_data"),
        WorkflowEdge(id="e3", source="clean_data", target="analyze_data"),
        WorkflowEdge(id="e4", source="analyze_data", target="visualize"),
        WorkflowEdge(id="e5", source="analyze_data", target="generate_report"),
        WorkflowEdge(id="e6", source="visualize", target="end"),
        WorkflowEdge(id="e7", source="generate_report", target="end"),
    ]


def _create_variables() -> List[WorkflowVariable]:
    """创建工作流变量"""
    return [
        WorkflowVariable(
            name="sample_size",
            type="number",
            default_value=1000,
            description="采样大小",
            scope="workflow",
        ),
        WorkflowVariable(
            name="confidence_level",
            type="number",
            default_value=0.95,
            description="置信水平",
            scope="workflow",
        ),
    ]


__all__ = ["get_data_analysis_template"]