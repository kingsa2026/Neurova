"""红绿灯 TDD：process_multimodal 视频路由修复 (C2)。

全链路根因：Agent.process_multimodal 将 media_type="video" 映射到
LLMRequestType.VIDEO_GENERATION，但视频"理解"应路由到 VIDEO_UNDERSTANDING。
错误映射会让视频理解请求被路由到视频生成模型族，导致功能失常。

测试用最小 Agent 替身 + patch select_model_for_request，捕获实际路由的请求类型。
当前 bug：video -> VIDEO_GENERATION -> 断言失败（红）。修复后应 -> VIDEO_UNDERSTANDING（绿）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from neurova import agent_core
from neurova.llm.llm_router import RequestType as LLMRequestType


def test_process_multimodal_video_maps_to_video_understanding(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        "neurova.llm.llm_router.select_model_for_request",
        lambda rt: captured.setdefault("rt", rt),
    )
    agent = SimpleNamespace(
        config=SimpleNamespace(llm_config=SimpleNamespace(model="m1")),
        voice_pipeline=None,
        asr_manager=None,
        chat=AsyncMock(return_value={"text": "ok"}),
    )
    asyncio.run(
        agent_core.Agent.process_multimodal(
            agent, content="描述这个视频的内容", media_type="video", metadata={}
        )
    )
    assert captured.get("rt") == LLMRequestType.VIDEO_UNDERSTANDING
