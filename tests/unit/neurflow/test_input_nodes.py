"""builtin:text_input 和 builtin:media_input 节点测试（TDD RED→GREEN）

text_input: 提供纯文本值给工作流，输出 {text: value}
media_input: 提供富媒体载荷（image/audio/video/file），输出 {media: {type, source, value}}
"""

import pytest
from unittest.mock import MagicMock, patch

from neurova.collaboration.neurflow.builtin import (
    BUILTIN_NODES,
    exec_text_input,
    exec_media_input,
)


# ----------------------------- 节点定义测试 -----------------------------


def test_text_input_node_definition():
    """builtin:text_input 节点定义存在于 BUILTIN_NODES"""
    node = next((n for n in BUILTIN_NODES if n["type"] == "builtin:text_input"), None)
    assert node is not None, "builtin:text_input 未在 BUILTIN_NODES 中注册"
    assert node["category"] == "input"
    assert node["icon"], "text_input 应有图标"
    sub_block_ids = {sb["id"] for sb in node.get("sub_blocks", [])}
    assert "value" in sub_block_ids, "text_input 应含 value sub_block"
    # 输出端口含 text
    output_ids = {o["id"] for o in node.get("outputs", [])}
    assert "text" in output_ids, "text_input 输出应含 text 端口"


def test_media_input_node_definition():
    """builtin:media_input 节点定义存在于 BUILTIN_NODES"""
    node = next((n for n in BUILTIN_NODES if n["type"] == "builtin:media_input"), None)
    assert node is not None, "builtin:media_input 未在 BUILTIN_NODES 中注册"
    assert node["category"] == "input"
    sub_block_ids = {sb["id"] for sb in node.get("sub_blocks", [])}
    assert "media_type" in sub_block_ids, "media_input 应含 media_type sub_block"
    assert "source" in sub_block_ids, "media_input 应含 source sub_block"
    assert "value" in sub_block_ids, "media_input 应含 value sub_block"
    output_ids = {o["id"] for o in node.get("outputs", [])}
    assert "media" in output_ids, "media_input 输出应含 media 端口"


# ----------------------------- exec_text_input -----------------------------


@pytest.mark.asyncio
async def test_exec_text_input_basic():
    """纯文本值原样返回"""
    config = {"value": "Hello, world!"}
    result = await exec_text_input(config, {})
    assert result["status"] == "success"
    assert result["output"]["text"] == "Hello, world!"


@pytest.mark.asyncio
async def test_exec_text_input_empty():
    """空值也应成功"""
    config = {}
    result = await exec_text_input(config, {})
    assert result["status"] == "success"
    assert result["output"]["text"] == ""


@pytest.mark.asyncio
async def test_exec_text_input_variable_resolved():
    """值中的 ${node.output} 变量引用由引擎变量解析器解析后回填"""
    mock_resolver = MagicMock()
    mock_resolver.resolve_config.return_value = "resolved-value"
    ctx = {"variable_resolver": mock_resolver, "resolution_context": MagicMock()}
    config = {"value": "${start.output}"}
    result = await exec_text_input(config, ctx)
    assert result["status"] == "success"
    assert result["output"]["text"] == "resolved-value"
    mock_resolver.resolve_config.assert_called_once()


# ----------------------------- exec_media_input -----------------------------


@pytest.mark.asyncio
async def test_exec_media_input_url():
    """图片 URL 透传"""
    config = {
        "media_type": "image",
        "source": "url",
        "value": "https://example.com/photo.png",
    }
    result = await exec_media_input(config, {})
    assert result["status"] == "success"
    media = result["output"]["media"]
    assert media["type"] == "image"
    assert media["source"] == "url"
    assert media["value"] == "https://example.com/photo.png"


@pytest.mark.asyncio
async def test_exec_media_input_defaults():
    """缺省 media_type 默认 file，缺省 source 默认 url"""
    config = {"value": "data/report.pdf"}
    result = await exec_media_input(config, {})
    assert result["status"] == "success"
    media = result["output"]["media"]
    assert media["type"] == "file"
    assert media["source"] == "url"
    assert media["value"] == "data/report.pdf"


@pytest.mark.asyncio
async def test_exec_media_input_base64():
    """base64 数据透传"""
    config = {
        "media_type": "audio",
        "source": "base64",
        "value": "UklGRiQAAABXQVZFZm10...",
    }
    result = await exec_media_input(config, {})
    assert result["status"] == "success"
    media = result["output"]["media"]
    assert media["type"] == "audio"
    assert media["source"] == "base64"


# ----------------------------- 执行器注册 -----------------------------


def test_executors_registered():
    """text_input 和 media_input 执行器应注册在 BUILTIN_EXECUTORS 中"""
    from neurova.collaboration.neurflow.builtin import BUILTIN_EXECUTORS

    assert "builtin:text_input" in BUILTIN_EXECUTORS
    assert "builtin:media_input" in BUILTIN_EXECUTORS
