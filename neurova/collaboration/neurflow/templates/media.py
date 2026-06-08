"""
媒体创作工作流模板

流程：文案 → 配音 → 封面 → 视频 → 合成

典型场景：
- 视频创作
- 音频制作
- 多媒体内容生成
"""
import time
import uuid
from typing import Dict, List, Any

from ..models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, NodeCategory
)


def get_media_template() -> WorkflowDefinition:
    """获取媒体创作工作流模板
    
    Returns:
        预定义的媒体创作工作流定义
    """
    nodes = _create_nodes()
    edges = _create_edges()
    variables = _create_variables()
    
    return WorkflowDefinition(
        id=f"template_media_{uuid.uuid4().hex[:8]}",
        name="媒体创作",
        description="文案 → 配音 → 封面 → 视频 → 合成",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=variables,
        tags=["media", "video", "audio", "multimedia", "content"],
        category="media",
        author="Neurflow",
        created_at=time.time(),
        updated_at=time.time(),
        status=WorkflowStatus.DRAFT,
        template=True,
        public=True,
        metadata={
            "difficulty": "intermediate",
            "estimated_time": "30-60 minutes",
            "required_skills": ["media", "content-creation"],
            "description": "自动化多媒体内容创作流程",
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
                        "description": "媒体内容主题",
                    },
                    "duration": {
                        "type": "select",
                        "options": ["短片 (1-3分钟)", "中等 (3-10分钟)", "长片 (10-30分钟)"],
                        "default": "短片 (1-3分钟)",
                        "description": "视频时长",
                    },
                    "style": {
                        "type": "select",
                        "options": ["教育", "娱乐", "商业", "纪录片", "创意"],
                        "default": "教育",
                        "description": "媒体风格",
                    }
                }
            },
            label="开始",
        ),
        
        WorkflowNode(
            id="script",
            type="builtin:llm",
            position={"x": 400, "y": 100},
            config={
                "prompt": """为以下主题创作媒体脚本：

主题：{{topic}}
时长：{{duration}}
风格：{{style}}

要求：
1. 包含开场、主体、结尾
2. 适合目标时长
3. 语言生动，适合口语表达
4. 包含视觉元素描述

输出格式：JSON 格式脚本""",
                "temperature": 0.7,
                "max_tokens": 2000,
            },
            label="文案创作",
        ),
        
        WorkflowNode(
            id="voiceover",
            type="builtin:tts",
            position={"x": 700, "y": 100},
            config={
                "text": "{{script.output.voiceover}}",
                "voice": "zh-CN-YunxiNeural",
                "speed": 1.0,
                "language": "zh-CN",
            },
            label="配音生成",
        ),
        
        WorkflowNode(
            id="thumbnail",
            type="builtin:llm",
            position={"x": 1000, "y": 50},
            config={
                "prompt": """为以下内容设计封面图描述：

主题：{{topic}}
风格：{{style}}
脚本摘要：{{script.output.summary}}

要求：
1. 视觉吸引力强
2. 符合内容主题
3. 包含关键信息
4. 适合社交媒体分享

输出封面图设计描述：""",
                "temperature": 0.8,
                "max_tokens": 500,
            },
            label="封面设计",
        ),
        
        WorkflowNode(
            id="video_gen",
            type="builtin:llm",
            position={"x": 1000, "y": 200},
            config={
                "prompt": """根据脚本生成视频分镜：

脚本：{{script.output.script}}
时长：{{duration}}

要求：
1. 每个场景包含：镜头描述、时长、转场效果
2. 适合目标时长
3. 视觉节奏合理
4. 包含字幕时间点

输出格式：JSON 分镜脚本""",
                "temperature": 0.5,
                "max_tokens": 2000,
            },
            label="视频分镜",
        ),
        
        WorkflowNode(
            id="merge",
            type="builtin:merge",
            position={"x": 1300, "y": 100},
            config={
                "strategy": "all",
            },
            label="素材合并",
        ),
        
        WorkflowNode(
            id="end",
            type="builtin:end",
            position={"x": 1600, "y": 100},
            config={
                "output_mapping": {
                    "script": "{{script.output}}",
                    "voiceover": "{{voiceover.output}}",
                    "thumbnail": "{{thumbnail.output}}",
                    "storyboard": "{{video_gen.output}}",
                    "duration": "{{duration}}",
                    "style": "{{style}}",
                },
            },
            label="结束",
        ),
    ]


def _create_edges() -> List[WorkflowEdge]:
    """创建边连接"""
    return [
        WorkflowEdge(id="e1", source="start", target="script"),
        WorkflowEdge(id="e2", source="script", target="voiceover"),
        WorkflowEdge(id="e3", source="script", target="thumbnail"),
        WorkflowEdge(id="e4", source="script", target="video_gen"),
        WorkflowEdge(id="e5", source="voiceover", target="merge"),
        WorkflowEdge(id="e6", source="thumbnail", target="merge"),
        WorkflowEdge(id="e7", source="video_gen", target="merge"),
        WorkflowEdge(id="e8", source="merge", target="end"),
    ]


def _create_variables() -> List[WorkflowVariable]:
    """创建工作流变量"""
    return [
        WorkflowVariable(
            name="background_music",
            type="string",
            default_value="轻音乐",
            description="背景音乐类型",
            scope="workflow",
        ),
        WorkflowVariable(
            name="subtitle_style",
            type="string",
            default_value="白色黑边",
            description="字幕样式",
            scope="workflow",
        ),
    ]


__all__ = ["get_media_template"]