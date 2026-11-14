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
from typing import Any, Dict, List

from ..models import WorkflowDefinition, WorkflowStatus
from .builder import buildEdges, buildNodes, buildVariables


def get_media_template() -> WorkflowDefinition:
    """获取媒体创作工作流模板

    Returns:
        预定义的媒体创作工作流定义
    """
    return WorkflowDefinition(
        id=f"template_media_{uuid.uuid4().hex[:8]}",
        name="媒体创作",
        description="文案 → 配音 → 封面 → 视频 → 合成",
        version="1.0.0",
        nodes=buildNodes(_NODE_SPECS),
        edges=buildEdges(_EDGE_SPECS),
        variables=buildVariables(_VARIABLE_SPECS),
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
                },
            },
        },
    },
    {
        "id": "script",
        "type": "builtin:llm",
        "x": 400,
        "y": 100,
        "label": "文案创作",
        "config": {
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
    },
    {
        "id": "voiceover",
        "type": "builtin:tts",
        "x": 700,
        "y": 100,
        "label": "配音生成",
        "config": {
            "text": "{{script.output.voiceover}}",
            "voice": "zh-CN-YunxiNeural",
            "speed": 1.0,
            "language": "zh-CN",
        },
    },
    {
        "id": "thumbnail",
        "type": "builtin:llm",
        "x": 1000,
        "y": 50,
        "label": "封面设计",
        "config": {
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
    },
    {
        "id": "video_gen",
        "type": "builtin:llm",
        "x": 1000,
        "y": 200,
        "label": "视频分镜",
        "config": {
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
    },
    {
        "id": "merge",
        "type": "builtin:merge",
        "x": 1300,
        "y": 100,
        "label": "素材合并",
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
                "script": "{{script.output}}",
                "voiceover": "{{voiceover.output}}",
                "thumbnail": "{{thumbnail.output}}",
                "storyboard": "{{video_gen.output}}",
                "duration": "{{duration}}",
                "style": "{{style}}",
            },
        },
    },
]

# 边声明式 spec：id/source/target（条件边带 source_handle）
_EDGE_SPECS: List[Dict[str, Any]] = [
    {
        "id": "e1",
        "source": "start",
        "target": "script",
    },
    {
        "id": "e2",
        "source": "script",
        "target": "voiceover",
    },
    {
        "id": "e3",
        "source": "script",
        "target": "thumbnail",
    },
    {
        "id": "e4",
        "source": "script",
        "target": "video_gen",
    },
    {
        "id": "e5",
        "source": "voiceover",
        "target": "merge",
    },
    {
        "id": "e6",
        "source": "thumbnail",
        "target": "merge",
    },
    {
        "id": "e7",
        "source": "video_gen",
        "target": "merge",
    },
    {
        "id": "e8",
        "source": "merge",
        "target": "end",
    },
]

# 变量声明式 spec：name/type/默认值/描述/作用域
_VARIABLE_SPECS: List[Dict[str, Any]] = [
    {
        "name": "background_music",
        "type": "string",
        "default_value": "轻音乐",
        "description": "背景音乐类型",
        "scope": "workflow",
    },
    {
        "name": "subtitle_style",
        "type": "string",
        "default_value": "白色黑边",
        "description": "字幕样式",
        "scope": "workflow",
    },
]


__all__ = ["get_media_template"]
