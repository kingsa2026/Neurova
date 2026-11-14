"""
AI 短剧一键成片模板（批次4，打通画布工作流）

主题 → 剧本 → 分镜（风格+画幅注入每镜提示词）→ 逐镜生图 → 旁白 TTS → 合成/连播清单。

产物经 llm/generators 实测协议矩阵与落盘单源（批次0）进入 AIGC「记录」同池。
无 FFmpeg 环境时 video-compose 输出 slideshow manifest，前端连播播放器消费。
"""

import time
from typing import Any, Dict, List

from ..models import WorkflowDefinition, WorkflowStatus
from .builder import buildEdges, buildNodes

# 固定模板 id：启动种子幂等 + AIGC 页按 id 一键实例化
SHORT_DRAMA_TEMPLATE_ID = "template_short_drama"


def get_short_drama_template() -> WorkflowDefinition:
    """短剧一键成片模板（启动时种子入工作流库，template=True public=True）"""
    return WorkflowDefinition(
        id=SHORT_DRAMA_TEMPLATE_ID,
        name="AI 短剧一键成片",
        description="主题 → 剧本 → 分镜 → 逐镜生图 → 旁白 → 连播清单/FFmpeg 成片",
        version="1.0.0",
        nodes=buildNodes(_NODE_SPECS),
        edges=buildEdges(_EDGE_SPECS),
        variables=[],
        tags=["media", "drama", "aigc", "一键成片"],
        category="media",
        author="Neurova",
        created_at=time.time(),
        updated_at=time.time(),
        status=WorkflowStatus.PUBLISHED,
        template=True,
        public=True,
        metadata={
            "difficulty": "beginner",
            "estimated_time": "3-10 minutes",
            "description": "输入一句话主题，自动完成剧本、分镜、逐镜画面与旁白合成",
        },
    )


# 节点声明式 spec：id/type/坐标/label/config，装配统一走 .builder
_NODE_SPECS: List[Dict[str, Any]] = [
    {
        "id": "start",
        "type": "builtin:start",
        "x": 60,
        "y": 200,
        "label": "开始",
        "config": {
            "inputs_schema": {
                "theme": {
                    "type": "textarea",
                    "required": True,
                    "description": "一句话主题（例：落魄赘婿遭人羞辱，三年之期已到，龙王归来）",
                },
                "genre": {
                    "type": "select",
                    "options": ["都市逆袭", "甜宠恋爱", "悬疑惊悚", "古装权谋", "战神归来"],
                    "default": "都市逆袭",
                    "description": "题材",
                },
                "style": {
                    "type": "input",
                    "default": "cinematic",
                    "description": "视觉风格（注入每个镜头的画面提示词）",
                },
                "aspect_ratio": {
                    "type": "select",
                    "options": ["9:16 竖屏", "16:9 横屏", "1:1 方形"],
                    "default": "9:16 竖屏",
                    "description": "画幅（项目锁，创建后统一注入每镜）",
                },
                "image_provider": {
                    "type": "select",
                    "options": [
                        {
                            "value": "openai",
                            "label": "OpenAI 兼容",
                        },
                        {
                            "value": "wanx",
                            "label": "通义万相/百炼",
                        },
                        {
                            "value": "ark",
                            "label": "火山 Seedream",
                        },
                        {
                            "value": "comfyui",
                            "label": "ComfyUI 自建",
                        },
                    ],
                    "default": "openai",
                    "description": "图像生成服务商",
                },
            },
        },
    },
    {
        "id": "script",
        "type": "builtin:short-drama-script",
        "x": 300,
        "y": 200,
        "label": "剧本生成",
        "config": {
            "logline": "$node.start.output.theme",
            "genre": "$node.start.output.genre",
            "episodes": 1,
        },
    },
    {
        "id": "storyboard",
        "type": "builtin:storyboard",
        "x": 560,
        "y": 200,
        "label": "分镜拆解",
        "config": {
            "script": "$node.script.output.script",
            "style": "$node.start.output.style",
            "aspect_ratio": "$node.start.output.aspect_ratio",
        },
    },
    {
        "id": "scenes",
        "type": "builtin:scene-gen",
        "x": 820,
        "y": 120,
        "label": "逐镜生图",
        "config": {
            "shots": "$node.storyboard.output.shots",
            "provider": "$node.start.output.image_provider",
            "style": "$node.start.output.style",
        },
    },
    {
        "id": "voiceover",
        "type": "builtin:voice-over",
        "x": 820,
        "y": 300,
        "label": "旁白合成",
        "config": {
            "shots": "$node.storyboard.output.shots",
            "voice": "旁白 浑厚",
            "language": "zh",
        },
    },
    {
        "id": "compose",
        "type": "builtin:video-compose",
        "x": 1100,
        "y": 200,
        "label": "成片合成",
        "config": {
            "clips": "$node.scenes.output.images",
            "resolution": "1080x1920",
            "transition": "fade",
        },
    },
    {
        "id": "end",
        "type": "builtin:end",
        "x": 1360,
        "y": 200,
        "label": "结束",
        "config": {
            "output_mapping": {
                "storyboard": "$node.storyboard.output.shots",
                "images": "$node.scenes.output.images",
                "audio": "$node.voiceover.output.audio_paths",
                "compose": "$node.compose.output",
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
        "target": "storyboard",
    },
    {
        "id": "e3",
        "source": "storyboard",
        "target": "scenes",
    },
    {
        "id": "e4",
        "source": "storyboard",
        "target": "voiceover",
    },
    {
        "id": "e5",
        "source": "scenes",
        "target": "compose",
    },
    {
        "id": "e6",
        "source": "voiceover",
        "target": "compose",
    },
    {
        "id": "e7",
        "source": "compose",
        "target": "end",
    },
]
