"""
Neurflow 数据模型测试 — 垂直切片 1
测试 WorkflowDefinition 序列化/反序列化
"""
import time
import pytest
from neurova.collaboration.neurflow.models import (
    WorkflowStatus, NodeCategory, SubBlockConfig, NodePort,
    NodeDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowDefinition, NodeExecutionResult, ExecutionInstance, AgentInfo
)


class TestWorkflowDefinitionSerialization:
    """WorkflowDefinition 序列化/反序列化测试"""

    def test_workflow_definition_to_dict(self):
        """测试 to_dict 序列化"""
        # 创建测试数据
        node = WorkflowNode(
            id="node_1",
            type="builtin:llm",
            position={"x": 100, "y": 200},
            config={"prompt": "Hello"},
            label="LLM Node"
        )
        edge = WorkflowEdge(
            id="edge_1",
            source="node_1",
            target="node_2"
        )
        variable = WorkflowVariable(
            name="topic",
            type="string",
            default_value="AI",
            description="讨论主题"
        )
        workflow = WorkflowDefinition(
            id="wf_001",
            name="测试工作流",
            description="一个测试工作流",
            version="1.0.0",
            nodes=[node],
            edges=[edge],
            variables=[variable],
            tags=["test", "demo"],
            category="programming",
            author="test_user",
            created_at=1717833600.0,
            updated_at=1717833600.0,
            status=WorkflowStatus.DRAFT,
            template=False,
            public=False,
            metadata={"key": "value"}
        )

        # 序列化
        result = workflow.to_dict()

        # 验证基本字段
        assert result["id"] == "wf_001"
        assert result["name"] == "测试工作流"
        assert result["description"] == "一个测试工作流"
        assert result["version"] == "1.0.0"
        assert result["category"] == "programming"
        assert result["author"] == "test_user"
        assert result["status"] == "draft"
        assert result["template"] is False
        assert result["public"] is False
        assert result["metadata"] == {"key": "value"}

        # 验证节点序列化
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "node_1"
        assert result["nodes"][0]["type"] == "builtin:llm"
        assert result["nodes"][0]["position"] == {"x": 100, "y": 200}
        assert result["nodes"][0]["config"] == {"prompt": "Hello"}

        # 验证边序列化
        assert len(result["edges"]) == 1
        assert result["edges"][0]["id"] == "edge_1"
        assert result["edges"][0]["source"] == "node_1"
        assert result["edges"][0]["target"] == "node_2"

        # 验证变量序列化
        assert len(result["variables"]) == 1
        assert result["variables"][0]["name"] == "topic"
        assert result["variables"][0]["type"] == "string"
        assert result["variables"][0]["default_value"] == "AI"

        # 验证标签
        assert result["tags"] == ["test", "demo"]

    def test_workflow_definition_from_dict(self):
        """测试 from_dict 反序列化"""
        data = {
            "id": "wf_002",
            "name": "反序列化测试",
            "description": "测试反序列化",
            "version": "2.0.0",
            "nodes": [
                {
                    "id": "node_a",
                    "type": "builtin:condition",
                    "position": {"x": 0, "y": 0},
                    "config": {"expression": "True"},
                    "label": "条件节点",
                    "enabled": True,
                    "metadata": {}
                }
            ],
            "edges": [
                {
                    "id": "edge_a",
                    "source": "node_a",
                    "target": "node_b",
                    "source_handle": "true",
                    "target_handle": None,
                    "label": None,
                    "condition": None
                }
            ],
            "variables": [
                {
                    "name": "count",
                    "type": "number",
                    "default_value": 0,
                    "description": "计数器",
                    "scope": "workflow"
                }
            ],
            "tags": ["反序列化"],
            "category": "data",
            "author": "test_user",
            "created_at": 1717833600.0,
            "updated_at": 1717833600.0,
            "status": "published",
            "template": True,
            "public": True,
            "metadata": {"source": "test"}
        }

        # 反序列化
        workflow = WorkflowDefinition.from_dict(data)

        # 验证基本字段
        assert workflow.id == "wf_002"
        assert workflow.name == "反序列化测试"
        assert workflow.description == "测试反序列化"
        assert workflow.version == "2.0.0"
        assert workflow.category == "data"
        assert workflow.author == "test_user"
        assert workflow.status == WorkflowStatus.PUBLISHED
        assert workflow.template is True
        assert workflow.public is True
        assert workflow.metadata == {"source": "test"}

        # 验证节点
        assert len(workflow.nodes) == 1
        assert workflow.nodes[0].id == "node_a"
        assert workflow.nodes[0].type == "builtin:condition"
        assert workflow.nodes[0].position == {"x": 0, "y": 0}
        assert workflow.nodes[0].config == {"expression": "True"}
        assert workflow.nodes[0].label == "条件节点"
        assert workflow.nodes[0].enabled is True

        # 验证边
        assert len(workflow.edges) == 1
        assert workflow.edges[0].id == "edge_a"
        assert workflow.edges[0].source == "node_a"
        assert workflow.edges[0].target == "node_b"
        assert workflow.edges[0].source_handle == "true"

        # 验证变量
        assert len(workflow.variables) == 1
        assert workflow.variables[0].name == "count"
        assert workflow.variables[0].type == "number"
        assert workflow.variables[0].default_value == 0
        assert workflow.variables[0].scope == "workflow"

    def test_workflow_definition_roundtrip(self):
        """测试序列化/反序列化往返一致性"""
        original = WorkflowDefinition(
            id="wf_roundtrip",
            name="往返测试",
            description="测试往返一致性",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="n1",
                    type="builtin:start",
                    position={"x": 0, "y": 0},
                    config={},
                    label="开始"
                ),
                WorkflowNode(
                    id="n2",
                    type="builtin:end",
                    position={"x": 100, "y": 0},
                    config={"output_mapping": {"result": "$node.n1.output"}},
                    label="结束"
                )
            ],
            edges=[
                WorkflowEdge(id="e1", source="n1", target="n2")
            ],
            variables=[
                WorkflowVariable(name="input_text", type="string")
            ],
            tags=["roundtrip"],
            category="general",
            author="test",
            created_at=time.time(),
            updated_at=time.time(),
            status=WorkflowStatus.DRAFT
        )

        # 往返测试
        serialized = original.to_dict()
        restored = WorkflowDefinition.from_dict(serialized)

        # 验证一致性
        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.version == original.version
        assert len(restored.nodes) == len(original.nodes)
        assert len(restored.edges) == len(original.edges)
        assert len(restored.variables) == len(original.variables)
        assert restored.status == original.status
        assert restored.template == original.template
        assert restored.public == original.public

        # 验证节点细节
        for orig_node, restored_node in zip(original.nodes, restored.nodes):
            assert restored_node.id == orig_node.id
            assert restored_node.type == orig_node.type
            assert restored_node.position == orig_node.position
            assert restored_node.config == orig_node.config
            assert restored_node.label == orig_node.label

        # 验证边细节
        for orig_edge, restored_edge in zip(original.edges, restored.edges):
            assert restored_edge.id == orig_edge.id
            assert restored_edge.source == orig_edge.source
            assert restored_edge.target == orig_edge.target

    def test_workflow_definition_defaults(self):
        """测试默认值"""
        data = {
            "id": "wf_defaults",
            "name": "默认值测试",
            # 其他字段使用默认值
        }

        workflow = WorkflowDefinition.from_dict(data)

        # 验证默认值
        assert workflow.description == ""
        assert workflow.version == "1.0.0"
        assert workflow.nodes == []
        assert workflow.edges == []
        assert workflow.variables == []
        assert workflow.tags == []
        assert workflow.category == "general"
        assert workflow.author == ""
        assert workflow.status == WorkflowStatus.DRAFT
        assert workflow.template is False
        assert workflow.public is False
        assert workflow.metadata == {}

    def test_workflow_status_enum(self):
        """测试 WorkflowStatus 枚举"""
        assert WorkflowStatus.DRAFT.value == "draft"
        assert WorkflowStatus.PUBLISHED.value == "published"
        assert WorkflowStatus.RUNNING.value == "running"
        assert WorkflowStatus.PAUSED.value == "paused"
        assert WorkflowStatus.COMPLETED.value == "completed"
        assert WorkflowStatus.FAILED.value == "failed"
        assert WorkflowStatus.CANCELLED.value == "cancelled"

        # 测试从字符串创建
        assert WorkflowStatus("draft") == WorkflowStatus.DRAFT
        assert WorkflowStatus("published") == WorkflowStatus.PUBLISHED

    def test_node_category_enum(self):
        """测试 NodeCategory 枚举"""
        assert NodeCategory.FLOW.value == "flow"
        assert NodeCategory.TOOLS.value == "tools"
        assert NodeCategory.SKILLS.value == "skills"
        assert NodeCategory.MCP.value == "mcp"
        assert NodeCategory.AI.value == "ai"
        assert NodeCategory.MEMORY.value == "memory"
        assert NodeCategory.MEDIA.value == "media"
        assert NodeCategory.DOCUMENT.value == "document"
        assert NodeCategory.DATA.value == "data"
        assert NodeCategory.COMMERCE.value == "commerce"
        assert NodeCategory.WEB.value == "web"
        assert NodeCategory.INPUT.value == "input"


class TestNodeExecutionResult:
    """NodeExecutionResult 测试"""

    def test_node_execution_result_creation(self):
        """测试创建 NodeExecutionResult"""
        result = NodeExecutionResult(
            node_id="node_1",
            status="success",
            output={"text": "Hello"},
            started_at=1717833600.0,
            finished_at=1717833601.0,
            duration=1.0,
            tokens_used=100,
            cost=0.01,
            metadata={"model": "gpt-4"}
        )

        assert result.node_id == "node_1"
        assert result.status == "success"
        assert result.output == {"text": "Hello"}
        assert result.error is None
        assert result.started_at == 1717833600.0
        assert result.finished_at == 1717833601.0
        assert result.duration == 1.0
        assert result.tokens_used == 100
        assert result.cost == 0.01
        assert result.metadata == {"model": "gpt-4"}

    def test_node_execution_result_defaults(self):
        """测试 NodeExecutionResult 默认值"""
        result = NodeExecutionResult(
            node_id="node_2",
            status="failed",
            output=None,
            error="Something went wrong"
        )

        assert result.node_id == "node_2"
        assert result.status == "failed"
        assert result.output is None
        assert result.error == "Something went wrong"
        assert result.started_at == 0.0
        assert result.finished_at is None
        assert result.duration is None
        assert result.tokens_used is None
        assert result.cost is None
        assert result.metadata == {}


class TestExecutionInstance:
    """ExecutionInstance 测试"""

    def test_execution_instance_creation(self):
        """测试创建 ExecutionInstance"""
        instance = ExecutionInstance(
            id="exec_001",
            workflow_id="wf_001",
            status=WorkflowStatus.RUNNING,
            inputs={"topic": "AI"},
            outputs={"result": "Hello"},
            node_results={},
            variables={"style": "formal"},
            started_at=1717833600.0,
            finished_at=None,
            duration=None,
            error=None,
            agent_id="agent_1",
            user_id="user_1",
            metadata={"source": "api"}
        )

        assert instance.id == "exec_001"
        assert instance.workflow_id == "wf_001"
        assert instance.status == WorkflowStatus.RUNNING
        assert instance.inputs == {"topic": "AI"}
        assert instance.outputs == {"result": "Hello"}
        assert instance.node_results == {}
        assert instance.variables == {"style": "formal"}
        assert instance.started_at == 1717833600.0
        assert instance.finished_at is None
        assert instance.duration is None
        assert instance.error is None
        assert instance.agent_id == "agent_1"
        assert instance.user_id == "user_1"
        assert instance.metadata == {"source": "api"}

    def test_execution_instance_defaults(self):
        """测试 ExecutionInstance 默认值"""
        instance = ExecutionInstance(
            id="exec_002",
            workflow_id="wf_002",
            status=WorkflowStatus.DRAFT,
            inputs={}
        )

        assert instance.id == "exec_002"
        assert instance.workflow_id == "wf_002"
        assert instance.status == WorkflowStatus.DRAFT
        assert instance.inputs == {}
        assert instance.outputs is None
        assert instance.node_results == {}
        assert instance.variables == {}
        assert instance.started_at == 0.0
        assert instance.finished_at is None
        assert instance.duration is None
        assert instance.error is None
        assert instance.agent_id is None
        assert instance.user_id is None
        assert instance.metadata == {}


class TestAgentInfo:
    """AgentInfo 测试"""

    def test_agent_info_creation(self):
        """测试创建 AgentInfo"""
        agent = AgentInfo(
            agent_id="neurflow_abc123",
            name="编程助手",
            role="developer",
            config={"model": "gpt-4"},
            flow_id="wf_001",
            created_at=1717833600.0,
            archived_at=None,
            status="active",
            capabilities=["coding", "testing"],
            metadata={"source": "workflow"}
        )

        assert agent.agent_id == "neurflow_abc123"
        assert agent.name == "编程助手"
        assert agent.role == "developer"
        assert agent.config == {"model": "gpt-4"}
        assert agent.flow_id == "wf_001"
        assert agent.created_at == 1717833600.0
        assert agent.archived_at is None
        assert agent.status == "active"
        assert agent.capabilities == ["coding", "testing"]
        assert agent.metadata == {"source": "workflow"}

    def test_agent_info_defaults(self):
        """测试 AgentInfo 默认值"""
        agent = AgentInfo(
            agent_id="neurflow_def456",
            name="测试 Agent",
            role="tester"
        )

        assert agent.agent_id == "neurflow_def456"
        assert agent.name == "测试 Agent"
        assert agent.role == "tester"
        assert agent.config == {}
        assert agent.flow_id is None
        assert agent.created_at == 0.0
        assert agent.archived_at is None
        assert agent.status == "active"
        assert agent.capabilities == []
        assert agent.metadata == {}


class TestSubBlockConfig:
    """SubBlockConfig 测试"""

    def test_sub_block_config_creation(self):
        """测试创建 SubBlockConfig"""
        config = SubBlockConfig(
            id="prompt",
            title="提示词",
            type="textarea",
            placeholder="请输入提示词",
            description="LLM 的提示词",
            required=True,
            default_value="Hello",
            options=None,
            min=None,
            max=None,
            language=None,
            provider_capability=None,
            file_types=None,
            condition=None,
            depends_on=None,
            validation=None
        )

        assert config.id == "prompt"
        assert config.title == "提示词"
        assert config.type == "textarea"
        assert config.placeholder == "请输入提示词"
        assert config.description == "LLM 的提示词"
        assert config.required is True
        assert config.default_value == "Hello"

    def test_sub_block_config_defaults(self):
        """测试 SubBlockConfig 默认值"""
        config = SubBlockConfig(
            id="temperature",
            title="温度",
            type="slider"
        )

        assert config.id == "temperature"
        assert config.title == "温度"
        assert config.type == "slider"
        assert config.placeholder is None
        assert config.description is None
        assert config.required is False
        assert config.default_value is None
        assert config.options is None
        assert config.min is None
        assert config.max is None
        assert config.language is None
        assert config.provider_capability is None
        assert config.file_types is None
        assert config.condition is None
        assert config.depends_on is None
        assert config.validation is None


class TestNodeDefinition:
    """NodeDefinition 测试"""

    def test_node_definition_creation(self):
        """测试创建 NodeDefinition"""
        node_def = NodeDefinition(
            type="tool:web_search",
            label="网页搜索",
            icon="🔍",
            category="tools",
            description="搜索网页内容",
            sub_blocks=[
                SubBlockConfig(id="query", title="搜索词", type="input", required=True)
            ],
            inputs=[NodePort(id="input", label="输入")],
            outputs=[NodePort(id="output", label="输出"), NodePort(id="error", label="错误")],
            source="tool",
            source_id="web_search",
            version="1.0.0",
            tags=["search", "web"],
            deprecated=False
        )

        assert node_def.type == "tool:web_search"
        assert node_def.label == "网页搜索"
        assert node_def.icon == "🔍"
        assert node_def.category == "tools"
        assert node_def.description == "搜索网页内容"
        assert len(node_def.sub_blocks) == 1
        assert node_def.sub_blocks[0].id == "query"
        assert len(node_def.inputs) == 1
        assert len(node_def.outputs) == 2
        assert node_def.source == "tool"
        assert node_def.source_id == "web_search"
        assert node_def.version == "1.0.0"
        assert node_def.tags == ["search", "web"]
        assert node_def.deprecated is False

    def test_node_definition_defaults(self):
        """测试 NodeDefinition 默认值"""
        node_def = NodeDefinition(
            type="builtin:start",
            label="开始",
            icon="▶️",
            category="flow",
            description="工作流开始节点",
            sub_blocks=[],
            inputs=[],
            outputs=[NodePort(id="output", label="输出")]
        )

        assert node_def.type == "builtin:start"
        assert node_def.label == "开始"
        assert node_def.icon == "▶️"
        assert node_def.category == "flow"
        assert node_def.description == "工作流开始节点"
        assert node_def.sub_blocks == []
        assert node_def.inputs == []
        assert len(node_def.outputs) == 1
        assert node_def.source == "builtin"
        assert node_def.source_id is None
        assert node_def.version == "1.0.0"
        assert node_def.tags == []
        assert node_def.deprecated is False


class TestWorkflowNode:
    """WorkflowNode 测试"""

    def test_workflow_node_creation(self):
        """测试创建 WorkflowNode"""
        node = WorkflowNode(
            id="node_1",
            type="builtin:llm",
            position={"x": 100, "y": 200},
            config={"prompt": "Hello", "temperature": 0.7},
            label="LLM 节点",
            enabled=True,
            metadata={"source": "palette"}
        )

        assert node.id == "node_1"
        assert node.type == "builtin:llm"
        assert node.position == {"x": 100, "y": 200}
        assert node.config == {"prompt": "Hello", "temperature": 0.7}
        assert node.label == "LLM 节点"
        assert node.enabled is True
        assert node.metadata == {"source": "palette"}

    def test_workflow_node_defaults(self):
        """测试 WorkflowNode 默认值"""
        node = WorkflowNode(
            id="node_2",
            type="builtin:condition",
            position={"x": 0, "y": 0},
            config={"expression": "True"}
        )

        assert node.id == "node_2"
        assert node.type == "builtin:condition"
        assert node.position == {"x": 0, "y": 0}
        assert node.config == {"expression": "True"}
        assert node.label is None
        assert node.enabled is True
        assert node.metadata == {}


class TestWorkflowEdge:
    """WorkflowEdge 测试"""

    def test_workflow_edge_creation(self):
        """测试创建 WorkflowEdge"""
        edge = WorkflowEdge(
            id="edge_1",
            source="node_1",
            target="node_2",
            source_handle="true",
            target_handle="input",
            label="条件成立",
            condition="$node.condition.output.branch == 'true'"
        )

        assert edge.id == "edge_1"
        assert edge.source == "node_1"
        assert edge.target == "node_2"
        assert edge.source_handle == "true"
        assert edge.target_handle == "input"
        assert edge.label == "条件成立"
        assert edge.condition == "$node.condition.output.branch == 'true'"

    def test_workflow_edge_defaults(self):
        """测试 WorkflowEdge 默认值"""
        edge = WorkflowEdge(
            id="edge_2",
            source="node_a",
            target="node_b"
        )

        assert edge.id == "edge_2"
        assert edge.source == "node_a"
        assert edge.target == "node_b"
        assert edge.source_handle is None
        assert edge.target_handle is None
        assert edge.label is None
        assert edge.condition is None


class TestWorkflowVariable:
    """WorkflowVariable 测试"""

    def test_workflow_variable_creation(self):
        """测试创建 WorkflowVariable"""
        var = WorkflowVariable(
            name="topic",
            type="string",
            default_value="AI",
            description="讨论主题",
            scope="workflow"
        )

        assert var.name == "topic"
        assert var.type == "string"
        assert var.default_value == "AI"
        assert var.description == "讨论主题"
        assert var.scope == "workflow"

    def test_workflow_variable_defaults(self):
        """测试 WorkflowVariable 默认值"""
        var = WorkflowVariable(
            name="count",
            type="number"
        )

        assert var.name == "count"
        assert var.type == "number"
        assert var.default_value is None
        assert var.description is None
        assert var.scope == "workflow"


class TestNodePort:
    """NodePort 测试"""

    def test_node_port_creation(self):
        """测试创建 NodePort"""
        port = NodePort(
            id="output",
            label="输出结果",
            type="json",
            required=True,
            multiple=False
        )

        assert port.id == "output"
        assert port.label == "输出结果"
        assert port.type == "json"
        assert port.required is True
        assert port.multiple is False

    def test_node_port_defaults(self):
        """测试 NodePort 默认值"""
        port = NodePort(
            id="input",
            label="输入"
        )

        assert port.id == "input"
        assert port.label == "输入"
        assert port.type == "any"
        assert port.required is False
        assert port.multiple is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])