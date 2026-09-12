#!/usr/bin/env python3
"""
测试 ResolutionContext 外部系统注入
验证 $memory/$context/$emotion/$crystal 四个变量前缀能否正常工作

契约来源：neurova/collaboration/neurflow/variable_resolver.py
  - ResolutionContext 四个延迟注入字段（memory_manager/context_pool/
    emotion_module/crystallizer）
  - $memory 默认走 search_memories（_resolve_memory）、$context 走
    get_context 后按路径取字段（_resolve_context）、$emotion 走
    current()（_resolve_emotion）、$crystal 走 retrieve(query)
    （_resolve_crystal）
注入链路：neurova/collaboration/neurflow/execution_engine.py
  （ResolutionContext(...) 构造点逐一传入四个外部系统）

注：resolve() 为同步 API，本文件历史版本误用 async def 且无
pytest.mark.asyncio 标记（strict 模式下不被任何插件接管）、断言全部
缺位（print 脚本风）——2026-09-12 按现行同步契约重写。
"""

from unittest.mock import MagicMock

from neurova.collaboration.neurflow.variable_resolver import (
    ResolutionContext,
    VariableResolver,
)


def _make_context() -> ResolutionContext:
    """构造注入四个外部系统替身的解析上下文"""
    mock_memory = MagicMock()
    mock_memory.search_memories.return_value = [
        {"content": "测试记忆内容", "score": 0.95}
    ]

    mock_context = MagicMock()
    mock_context.get_context.return_value = {
        "system_prompt": "你是一个AI助手",
        "recent_messages": [],
    }

    mock_emotion = MagicMock()
    mock_emotion.current.return_value = {
        "valence": 0.8,
        "primary_emotion": "happy",
    }

    mock_crystal = MagicMock()
    mock_crystal.retrieve.return_value = [
        {"pattern": "测试模式", "confidence": 0.9}
    ]

    return ResolutionContext(
        workflow_id="test_workflow",
        execution_id="test_execution",
        memory_manager=mock_memory,
        context_pool=mock_context,
        emotion_module=mock_emotion,
        crystallizer=mock_crystal,
    )


def test_api_endpoint_exposes_agent_instance_getter():
    """API 端点暴露 get_agent_instance（注入链路入口依赖，重导入故用例内导入）"""
    from neurova.api.endpoints import get_agent_instance

    assert callable(get_agent_instance)


def test_resolution_context_injection():
    """外部系统注入后四个变量前缀均可解析"""
    resolver = VariableResolver()
    context = _make_context()

    # $memory 前缀：默认走 search_memories
    result = resolver.resolve("$memory.test_query", context)
    assert result.success, result.error
    assert result.value == [{"content": "测试记忆内容", "score": 0.95}]

    # $context 前缀：get_context 后按路径取字段
    result = resolver.resolve("$context.system_prompt", context)
    assert result.success, result.error
    assert result.value == "你是一个AI助手"

    # $emotion 前缀：current() 后按路径取字段
    result = resolver.resolve("$emotion.valence", context)
    assert result.success, result.error
    assert result.value == 0.8

    # $crystal 前缀：retrieve(query)
    result = resolver.resolve("$crystal.test_pattern", context)
    assert result.success, result.error
    assert result.value == [{"pattern": "测试模式", "confidence": 0.9}]
