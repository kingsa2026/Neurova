"""N1：节点参数自描述与环境需求。

判据：
1. NodeDefinition 持久化 `env_requirements`，读回逐字一致；
2. CanvasOpService.list_nodes 返回 sub_blocks/inputs/outputs/default_config/
   required/env_requirements，旧字段保持；
3. 未声明环境的节点如实返回空列表，不猜。
"""

from __future__ import annotations

import asyncio

import pytest

from neurova.collaboration.canvas_ops import CanvasOpService
from neurova.collaboration.neurflow.models import NodeDefinition, NodePort, SubBlockConfig
from neurova.collaboration.neurflow.node_registry import (
    get_node_registry,
    reset_node_registry,
)
from neurova.collaboration.neurflow.storage import NeurflowStorage


@pytest.fixture
def registry():
    reset_node_registry()
    reg = get_node_registry()
    yield reg
    reset_node_registry()


def _definition(env=None):
    return NodeDefinition(
        type="test:agent_schema",
        label="Agent Schema",
        icon="T",
        category="tools",
        description="test node",
        sub_blocks=[
            SubBlockConfig(
                id="target",
                title="Target",
                type="input",
                required=True,
                default_value="A",
            ),
            SubBlockConfig(id="optional", title="Optional", type="input"),
        ],
        inputs=[NodePort(id="input", label="Input")],
        outputs=[NodePort(id="output", label="Output")],
        source="builtin",
        env_requirements=list(env or []),
    )


def test_nodeDefinitionPersistsEnvRequirements(tmp_path):
    storage = NeurflowStorage()
    definition = _definition(["NEUROVA_A", "NEUROVA_B"])
    assert storage.save_node_definition(definition)
    loaded = storage.get_node_definition("test:agent_schema")
    assert loaded is not None
    assert loaded.env_requirements == ["NEUROVA_A", "NEUROVA_B"]
    storage.delete_node_definition("test:agent_schema")


def test_listNodesReturnsParameterContract(registry):
    registry.register(_definition(["NEUROVA_A"]))
    service = CanvasOpService()
    nodes = asyncio.run(service.list_nodes(query="test:agent_schema"))
    assert len(nodes) == 1
    node = nodes[0]

    # 旧字段保持
    for key in ("type", "label", "icon", "category", "description", "source"):
        assert key in node
    # 新字段
    assert node["version"]
    assert node["env_requirements"] == ["NEUROVA_A"]
    assert node["default_config"] == {"target": "A"}
    assert node["required"] == ["target"]
    assert [b["id"] for b in node["sub_blocks"]] == ["target", "optional"]
    assert node["inputs"][0]["id"] == "input"
    assert node["outputs"][0]["id"] == "output"


def test_undeclaredEnvIsEmptyNotGuessed(registry):
    registry.register(_definition())
    service = CanvasOpService()
    node = asyncio.run(service.list_nodes(query="test:agent_schema"))[0]
    assert node["env_requirements"] == []


def test_nodeSchemaToolRegistration():
    from neurova.builtin_tools import _BUILTIN_SCHEMAS, get_builtin_tool_capability
    from neurova.tool_executor import ToolExecutor

    assert "node_schema" in _BUILTIN_SCHEMAS
    assert ToolExecutor._builtin_dispatch.get("node_schema") == "_execute_node_schema"
    cap = get_builtin_tool_capability("node_schema")
    assert cap is not None and cap.readOnly is True


@pytest.mark.asyncio
async def test_nodeSchemaToolReturnsExactNode():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from neurova.tool_executor import ToolExecutor

    agent = SimpleNamespace(
        _current_user_id="u1",
        config=SimpleNamespace(agent_id="agent-x", user_id="u1"),
    )
    executor = ToolExecutor.__new__(ToolExecutor)
    executor._agent = agent
    executor._canvas_call = AsyncMock(
        return_value=[
            {"type": "builtin:ad-streaming", "label": "广告流投放", "env_requirements": ["X"]},
            {"type": "builtin:ad-monitor", "label": "广告监控"},
        ]
    )
    executor._is_canvas_error = lambda result: False

    result = await ToolExecutor._execute_node_schema(executor, {"node_type": "builtin:ad-streaming"})
    assert result["success"] is True
    assert result["node"]["type"] == "builtin:ad-streaming"

    missing = await ToolExecutor._execute_node_schema(executor, {"node_type": "builtin:no_such"})
    assert missing["success"] is False
    assert missing["code"] == "unknown_node_type"
