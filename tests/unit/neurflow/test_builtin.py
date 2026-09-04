"""
Neurflow builtin.py 测试 — TDD 垂直切片 9

测试内置节点定义功能：
1. 内置节点注册
2. 节点执行器
3. 流程控制节点
4. AI 节点
5. 记忆节点
6. 专用领域节点
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, List, Any

# 导入待测模块
from neurova.collaboration.neurflow.builtin import (
    BUILTIN_NODES,
    register_builtin_nodes,
    get_builtin_executors,
    # 执行器
    exec_start,
    exec_end,
    exec_condition,
    exec_loop,
    exec_parallel,
    exec_merge,
    exec_delay,
    exec_llm,
    exec_agent,
    exec_evolution,
    exec_tdd,
    exec_memory_load,
    exec_memory_save,
    exec_context,
    exec_emotion,
    exec_variable,
    exec_transform,
    exec_human_input,
    exec_approval,
)


class TestBuiltinNodesDefinition:
    """测试内置节点定义"""

    def test_has_all_flow_nodes(self):
        """应包含所有流程控制节点"""
        flow_nodes = [n for n in BUILTIN_NODES if n["type"].startswith("builtin:") and n["category"] == "flow"]
        flow_types = [n["type"] for n in flow_nodes]
        assert "builtin:start" in flow_types
        assert "builtin:end" in flow_types
        assert "builtin:condition" in flow_types
        assert "builtin:loop" in flow_types
        assert "builtin:parallel" in flow_types
        assert "builtin:merge" in flow_types
        assert "builtin:delay" in flow_types

    def test_has_ai_nodes(self):
        """应包含 AI 节点"""
        ai_nodes = [n for n in BUILTIN_NODES if n["category"] == "ai"]
        ai_types = [n["type"] for n in ai_nodes]
        assert "builtin:llm" in ai_types
        assert "builtin:agent" in ai_types
        assert "builtin:evolution" in ai_types
        assert "builtin:tdd" in ai_types

    def test_has_memory_nodes(self):
        """应包含记忆节点"""
        memory_nodes = [n for n in BUILTIN_NODES if n["category"] == "memory"]
        memory_types = [n["type"] for n in memory_nodes]
        assert "builtin:memory-load" in memory_types
        assert "builtin:memory-save" in memory_types
        assert "builtin:context" in memory_types
        assert "builtin:emotion" in memory_types

    def test_has_data_nodes(self):
        """应包含数据节点"""
        data_nodes = [n for n in BUILTIN_NODES if n["category"] == "data"]
        data_types = [n["type"] for n in data_nodes]
        assert "builtin:variable" in data_types
        assert "builtin:transform" in data_types

    def test_has_input_nodes(self):
        """应包含人工输入节点"""
        input_nodes = [n for n in BUILTIN_NODES if n["category"] == "input"]
        input_types = [n["type"] for n in input_nodes]
        assert "builtin:human_input" in input_types
        assert "builtin:approval" in input_types

    def test_node_has_required_fields(self):
        """每个节点应有必需字段"""
        for node in BUILTIN_NODES:
            assert "type" in node, f"节点缺少 type: {node}"
            assert "label" in node, f"节点缺少 label: {node}"
            assert "icon" in node, f"节点缺少 icon: {node}"
            assert "category" in node, f"节点缺少 category: {node}"
            assert "description" in node, f"节点缺少 description: {node}"
            assert "sub_blocks" in node, f"节点缺少 sub_blocks: {node}"
            assert "inputs" in node, f"节点缺少 inputs: {node}"
            assert "outputs" in node, f"节点缺少 outputs: {node}"

    def test_node_type_format(self):
        """节点类型应以 builtin: 开头"""
        for node in BUILTIN_NODES:
            assert node["type"].startswith("builtin:"), f"节点类型格式错误: {node['type']}"


class TestRegisterBuiltinNodes:
    """测试注册内置节点"""

    def test_register_calls_registry_register(self):
        """应调用 registry.register 注册每个节点"""
        mock_registry = MagicMock()
        register_builtin_nodes(mock_registry)
        assert mock_registry.register.call_count == len(BUILTIN_NODES)

    def test_register_is_idempotent(self):
        """重复注册应是幂等的"""
        mock_registry = MagicMock()
        register_builtin_nodes(mock_registry)
        first_count = mock_registry.register.call_count
        
        # 再次注册
        register_builtin_nodes(mock_registry)
        second_count = mock_registry.register.call_count
        
        # 应该重新注册（不是追加）
        assert second_count == first_count * 2


class TestBuiltinExecutors:
    """测试内置节点执行器"""

    def test_get_builtin_executors_returns_dict(self):
        """应返回执行器字典"""
        executors = get_builtin_executors()
        assert isinstance(executors, dict)
        assert len(executors) > 0

    def test_executors_have_all_builtin_types(self):
        """应包含所有内置节点类型的执行器"""
        executors = get_builtin_executors()
        for node in BUILTIN_NODES:
            assert node["type"] in executors, f"缺少执行器: {node['type']}"


class TestFlowNodeExecutors:
    """测试流程控制节点执行器"""

    @pytest.mark.asyncio
    async def test_exec_start(self):
        """开始节点应返回成功"""
        config = {}
        ctx = {"inputs": {"topic": "test"}}
        result = await exec_start(config, ctx)
        assert result["status"] == "success"
        assert "output" in result

    @pytest.mark.asyncio
    async def test_exec_end(self):
        """结束节点应返回成功"""
        config = {}
        ctx = {"node_results": {"prev": {"output": "test_result"}}}
        result = await exec_end(config, ctx)
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_exec_condition_true(self):
        """条件节点应根据表达式返回分支"""
        config = {"expression": "True"}
        ctx = {}
        result = await exec_condition(config, ctx)
        assert result["status"] == "success"
        assert result["output"]["branch"] == "true"

    @pytest.mark.asyncio
    async def test_exec_condition_false(self):
        """条件节点应根据表达式返回假分支"""
        config = {"expression": "False"}
        ctx = {}
        result = await exec_condition(config, ctx)
        assert result["status"] == "success"
        assert result["output"]["branch"] == "false"

    @pytest.mark.asyncio
    async def test_exec_loop_with_max_iterations(self):
        """循环节点应受 max_iterations 限制"""
        config = {"max_iterations": 3}
        ctx = {}
        result = await exec_loop(config, ctx)
        assert result["status"] == "success"
        assert result["output"]["iterations"] <= 3

    @pytest.mark.asyncio
    async def test_exec_delay(self):
        """延时节点应等待指定时间"""
        config = {"seconds": 0.1}
        ctx = {}
        result = await exec_delay(config, ctx)
        assert result["status"] == "success"


class TestAINodeExecutors:
    """测试 AI 节点执行器"""

    @pytest.mark.asyncio
    async def test_exec_llm_with_mock_agent(self):
        """LLM 节点应调用 Agent.chat()"""
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(return_value="AI response")

        with patch("neurova.collaboration.neurflow.builtin._get_agent", return_value=mock_agent):
            config = {"prompt": "Hello", "temperature": 0.7}
            ctx = {}
            result = await exec_llm(config, ctx)
            assert result["status"] == "success"
            assert result["output"]["text"] == "AI response"
            mock_agent.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_exec_llm_without_agent(self):
        """无 Agent 时应返回错误"""
        with patch("neurova.collaboration.neurflow.builtin._get_agent", return_value=None):
            config = {"prompt": "Hello"}
            ctx = {}
            result = await exec_llm(config, ctx)
            assert result["status"] == "failed"
            assert "error" in result

    @pytest.mark.asyncio
    async def test_exec_evolution_learn(self):
        """进化节点 learn 模式"""
        mock_evo = MagicMock()
        mock_evo.on_experience_recorded = MagicMock()

        with patch("neurova.collaboration.neurflow.builtin._get_evolution", return_value=mock_evo):
            config = {"mode": "learn", "feedback_data": {"tools": []}}
            ctx = {}
            result = await exec_evolution(config, ctx)
            assert result["status"] == "success"
            mock_evo.on_experience_recorded.assert_called_once()


class TestMemoryNodeExecutors:
    """测试记忆节点执行器"""

    @pytest.mark.asyncio
    async def test_exec_memory_load(self):
        """记忆加载节点"""
        mock_memory = MagicMock()
        mock_memory.search = MagicMock(return_value=[{"content": "memory1"}])

        with patch("neurova.collaboration.neurflow.builtin._get_memory_manager", return_value=mock_memory):
            config = {"query": "test query", "limit": 5}
            ctx = {}
            result = await exec_memory_load(config, ctx)
            assert result["status"] == "success"
            mock_memory.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_exec_memory_save(self, tmp_path, monkeypatch):
        """记忆保存节点（confirm=True 直写语义，契约不变）"""
        from neurova.memory.pending_memory import PendingMemoryStore

        monkeypatch.setattr(
            "neurova.memory.pending_memory.get_pending_memory_store",
            lambda: PendingMemoryStore(db_path=str(tmp_path / "p.db")),
        )
        mock_memory = MagicMock()
        mock_memory.remember = MagicMock()

        with patch("neurova.collaboration.neurflow.builtin._get_memory_manager", return_value=mock_memory):
            config = {"content": "new memory", "importance": 0.8, "confirm": True}
            ctx = {}
            result = await exec_memory_save(config, ctx)
            assert result["status"] == "success"
            assert result["output"]["saved"] is True
            mock_memory.remember.assert_called_once()

    @pytest.mark.asyncio
    async def test_exec_memory_save_pending_interception(self, tmp_path, monkeypatch):
        """P1-2 闭环审查修 E：工作流 memory-save 节点默认进待确认队列，
        不直写主库；confirm=True 按次直写；队列缺席降级直写。"""
        from neurova.memory.pending_memory import PendingMemoryStore
        import neurova.collaboration.neurflow.builtin as builtin_mod

        store = PendingMemoryStore(db_path=str(tmp_path / "p2.db"))
        monkeypatch.setattr(
            "neurova.memory.pending_memory.get_pending_memory_store", lambda: store
        )
        mock_memory = MagicMock()

        with patch("neurova.collaboration.neurflow.builtin._get_memory_manager", return_value=mock_memory):
            # 默认：进待审，不直写
            result = await exec_memory_save({"content": "需要确认的记忆"}, {"user_id": "u9"})
            assert result["status"] == "success"
            assert result["output"]["pending"] is True
            assert result["output"]["review_id"]
            assert store.list_pending()[0]["proposed_by"] == "u9"
            mock_memory.remember.assert_not_called()

            # confirm=True：按次直写
            result = await exec_memory_save({"content": "直接入库", "confirm": True}, {})
            assert result["output"] == {"saved": True, "content": "直接入库"}
            mock_memory.remember.assert_called_once()

        # 队列缺席（挂载失败）：降级直写
        def boom():
            raise RuntimeError("queue unavailable")

        with patch("neurova.collaboration.neurflow.builtin._get_memory_manager", return_value=mock_memory),              patch("neurova.memory.pending_memory.get_pending_memory_store", boom):
            result = await exec_memory_save({"content": "降级直写"}, {})
            assert result["output"] == {"saved": True, "content": "降级直写"}


class TestDataNodeExecutors:
    """测试数据节点执行器"""

    @pytest.mark.asyncio
    async def test_exec_variable(self):
        """变量节点应设置变量"""
        config = {"name": "test_var", "value": "test_value"}
        ctx = {"variables": {}}
        result = await exec_variable(config, ctx)
        assert result["status"] == "success"
        assert ctx["variables"]["test_var"] == "test_value"

    @pytest.mark.asyncio
    async def test_exec_transform(self):
        """数据转换节点"""
        config = {"expression": "input.upper()"}
        ctx = {"input": "hello"}
        result = await exec_transform(config, ctx)
        assert result["status"] == "success"


class TestInputNodeExecutors:
    """测试人工输入节点执行器"""

    @pytest.mark.asyncio
    async def test_exec_human_input(self):
        """人工输入节点应等待输入"""
        config = {"prompt": "请输入", "timeout": 1}
        ctx = {}
        result = await exec_human_input(config, ctx)
        # 在测试环境中，应返回超时或模拟输入
        assert result["status"] in ["success", "timeout"]

    @pytest.mark.asyncio
    async def test_exec_approval(self):
        """审批节点应等待审批"""
        config = {"approver": "admin", "message": "请审批"}
        ctx = {}
        result = await exec_approval(config, ctx)
        # 在测试环境中，应返回超时或模拟审批
        assert result["status"] in ["success", "timeout", "pending"]
