# -*- coding: utf-8 -*-
"""neurflow 节点与 Agent/LLM 的桥接单源（P2-28）。

原 ``builtin.py`` / ``commerce_nodes.py`` / ``drama_nodes.py`` 三处互抄的
``_get_agent`` / ``_call_agent`` / ``_extract_llm_text`` 收口到这里：
Agent 获取与调用口径一处定义，LLM 响应文本提取一处实现。
调用方以 ``from neurova.collaboration.neurflow.llm_bridge import
xxx as _xxx`` 别名接回，模块内既有调用点与测试桩零改动。
"""
from __future__ import annotations

from typing import Any

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def get_agent():
    """获取 Agent 实例（未初始化返回 None，不抛错）"""
    try:
        from neurova.agent_core import Agent

        return Agent.get_instance()
    except (ImportError, AttributeError):
        logger.debug("Agent 未可用")
        return None


async def call_agent(prompt: str, system_prompt: str = "", agent_getter=None) -> str:
    """调用 Agent 生成文本，失败时抛出异常。

    ``agent_getter``：调用方传入的 Agent 获取器，缺省用本模块 :func:`get_agent`。
    保留该参数是因为消费方模块的 ``_get_agent`` 是既有测试的替换点
    （patch 消费方模块名），薄包装把本模块接缝传进来，实现仍单源。
    """
    getter = agent_getter or get_agent
    agent = getter()
    if agent is None:
        raise RuntimeError("Agent 未初始化")
    response = await agent.chat(
        prompt,
        system_prompt=system_prompt,
        metadata={"history": []},
    )
    return response if isinstance(response, str) else str(response)


def extract_llm_text(response: Any) -> str:
    """从多种响应形状中安全提取文本内容"""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            if isinstance(message, dict):
                return str(message.get("content", ""))
        return str(response)
    # OpenAI 风格对象：choices[0].message.content
    try:
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            if hasattr(message, "content"):
                return str(message.content)
    except Exception:
        pass
    return str(response)
