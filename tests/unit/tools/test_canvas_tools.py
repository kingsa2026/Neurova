"""
Agent 画布工具（canvas_*）测试（TDD 红灯）— Phase 1

覆盖：
1. Schema 注册：9 个 canvas_* 工具在 _BUILTIN_SCHEMAS 可见（LLM 能看到），
   且 _builtin_dispatch 分派表齐全（schema ↔ 执行体不变量由
   test_builtin_tools_expansion.py::TestSchemaDispatchConsistency 统一守护）。
2. ToolExecutor._execute_canvas_* 薄封装：参数校验、CanvasOpError →
   {"error", "code"}、成功返回 {"success": True, ...}、session_id 透传。

注：执行方法为 async，用 asyncio.run 运行，避免依赖 pytest-asyncio。
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

CANVAS_TOOLS = {
    # 工具名 → 必填参数
    "canvas_create": ["name"],
    "canvas_read": ["canvas_id"],
    "canvas_add_node": ["canvas_id", "node_type"],
    "canvas_connect": ["canvas_id", "source_node", "target_node"],
    "canvas_set_config": ["canvas_id", "node_id", "values"],
    "canvas_move_node": ["canvas_id", "node_id", "x", "y"],
    "canvas_remove_node": ["canvas_id", "node_id"],
    "canvas_layout": ["canvas_id"],
    "canvas_run": ["canvas_id"],
    "canvas_list_nodes": [],
}


def _make_executor():
    from neurova.tool_executor import ToolExecutor

    agent = Mock()
    agent._skill_registry = Mock()
    agent.tool_router = Mock()
    agent.tool_memory = Mock()
    agent.tool_lifecycle = Mock()
    agent.skill_packer = Mock()
    agent.config = Mock()
    agent._current_session_id = "sess_test"
    return ToolExecutor(agent)


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════
# 1. Schema 注册（LLM 可见性）
# ═══════════════════════════════════════════════════════════════


class TestCanvasToolSchemas:
    @pytest.mark.parametrize("tool_name", sorted(CANVAS_TOOLS))
    def test_schema_registered_with_valid_shape(self, tool_name):
        from neurova.builtin_tools import get_builtin_tool_params

        schema = get_builtin_tool_params(tool_name)
        assert schema is not None, f"{tool_name} 未注册 schema — LLM 看不到该工具"
        assert schema.get("description"), f"{tool_name} 缺少 description"
        params = schema["parameters"]
        assert params["type"] == "object"
        assert isinstance(params.get("properties"), dict)
        assert set(params.get("required", [])) == set(CANVAS_TOOLS[tool_name])

    def test_openai_tools_visibility(self):
        from neurova.builtin_tools import BuiltinToolRegistry

        names = {t["function"]["name"] for t in BuiltinToolRegistry().get_openai_tools()}
        assert set(CANVAS_TOOLS) <= names

    @pytest.mark.parametrize("tool_name", sorted(CANVAS_TOOLS))
    def test_dispatch_entry_exists(self, tool_name):
        """分派表必须覆盖每个 canvas 工具（否则调用返回'未知内置工具'）"""
        from neurova.tool_executor import ToolExecutor

        assert tool_name in ToolExecutor._builtin_dispatch
        method_name = ToolExecutor._builtin_dispatch[tool_name]
        assert hasattr(ToolExecutor, method_name), f"{method_name} 执行方法不存在"


# ═══════════════════════════════════════════════════════════════
# 2. 执行封装行为
# ═══════════════════════════════════════════════════════════════


class TestCanvasToolExecution:
    def _patch_service(self):
        """把 CanvasOpService 单例替换为 AsyncMock"""
        service = Mock()
        service.create_canvas = AsyncMock(
            return_value={"id": "canvas_x", "name": "t", "version": 1, "nodes": [], "edges": []}
        )
        service.read_canvas = AsyncMock(
            return_value={"id": "canvas_x", "name": "t", "version": 3, "nodes": [], "edges": []}
        )
        service.add_node = AsyncMock(
            return_value={"id": "n1", "type": "builtin:start", "version": 4}
        )
        service.connect = AsyncMock(return_value={"id": "e1"})
        service.set_config = AsyncMock(return_value={"id": "n1", "config": {"a": 1}})
        service.move_node = AsyncMock(return_value={"id": "n1", "position": {"x": 1, "y": 2}})
        service.remove_node = AsyncMock(return_value={"removed_edges": 1})
        service.apply_layout = AsyncMock(return_value={"n1": {"x": 0, "y": 0}})
        service.list_nodes = AsyncMock(
            return_value=[{"type": "builtin:start", "label": "开始", "category": "flow"}]
        )
        patcher = patch(
            "neurova.tool_executor.get_canvas_op_service", return_value=service
        )
        return patcher, service

    def test_canvas_create_passes_session_and_actor(self):
        patcher, service = self._patch_service()
        patcher.start()
        try:
            ex = _make_executor()
            result = _run(ex._execute_canvas_create({"name": "流水线", "description": "d"}))
            assert result["success"] is True
            assert result["canvas_id"] == "canvas_x"
            kwargs = service.create_canvas.call_args.kwargs
            assert kwargs["session_id"] == "sess_test"
            assert kwargs["actor"] == "agent"
        finally:
            patcher.stop()

    def test_canvas_add_node_returns_node_and_version(self):
        patcher, service = self._patch_service()
        patcher.start()
        try:
            ex = _make_executor()
            result = _run(
                ex._execute_canvas_add_node(
                    {"canvas_id": "canvas_x", "node_type": "builtin:start", "base_version": 3}
                )
            )
            assert result["success"] is True
            assert result["node"]["id"] == "n1"
            kwargs = service.add_node.call_args.kwargs
            assert kwargs["base_version"] == 3
        finally:
            patcher.stop()

    def test_canvas_op_error_becomes_error_dict(self):
        from neurova.collaboration.canvas_ops import CanvasOpError

        patcher, service = self._patch_service()
        service.add_node = AsyncMock(
            side_effect=CanvasOpError("未注册类型: x", code="unknown_node_type")
        )
        patcher.start()
        try:
            ex = _make_executor()
            result = _run(
                ex._execute_canvas_add_node({"canvas_id": "c", "node_type": "x"})
            )
            assert result["success"] is False
            assert result["code"] == "unknown_node_type"
            assert "未注册类型" in result["error"]
        finally:
            patcher.stop()

    def test_canvas_version_conflict_surfaces_code(self):
        from neurova.collaboration.canvas_ops import CanvasVersionConflict

        patcher, service = self._patch_service()
        service.add_node = AsyncMock(
            side_effect=CanvasVersionConflict("版本冲突: base=1 current=2", current_version=2)
        )
        patcher.start()
        try:
            ex = _make_executor()
            result = _run(
                ex._execute_canvas_add_node(
                    {"canvas_id": "c", "node_type": "builtin:start", "base_version": 1}
                )
            )
            assert result["success"] is False
            assert result["code"] == "version_conflict"
            # agent 需要当前版本号来重读重试
            assert result["current_version"] == 2
        finally:
            patcher.stop()

    def test_canvas_list_nodes_no_session_required(self):
        patcher, service = self._patch_service()
        patcher.start()
        try:
            ex = _make_executor()
            result = _run(ex._execute_canvas_list_nodes({"query": "开始"}))
            assert result["success"] is True
            assert result["nodes"][0]["type"] == "builtin:start"
            assert service.list_nodes.call_args.kwargs.get("query") == "开始"
        finally:
            patcher.stop()

    def test_canvas_run_executes_workflow_and_summarizes(self):
        """canvas_run：编译画布 → neurflow 执行 → 返回节点级结果摘要"""
        patcher, service = self._patch_service()
        service.read_canvas = AsyncMock(
            return_value={
                "id": "canvas_x",
                "name": "t",
                "version": 1,
                "nodes": [
                    {"id": "n1", "type": "builtin:start", "position": {"x": 0, "y": 0}, "config": {}},
                    {"id": "n2", "type": "builtin:end", "position": {"x": 300, "y": 0}, "config": {}},
                ],
                "edges": [
                    {"id": "e1", "source": {"nodeId": "n1", "portId": "output"},
                     "target": {"nodeId": "n2", "portId": "input"}}
                ],
            }
        )
        patcher.start()

        # mock neurflow 执行器：返回成功实例
        instance = Mock()
        instance.id = "exec_1"
        instance.status = Mock(value="completed")
        instance.outputs = {"result": "ok"}
        instance.error = None
        instance.duration = 0.5
        node_result = Mock()
        node_result.status = "success"
        node_result.output = {"text": "hi"}
        node_result.error = None
        node_result.duration = 0.1
        instance.node_results = {"n1": node_result, "n2": node_result}

        executor_mock = Mock()
        executor_mock.create_instance = Mock(return_value=instance)
        executor_mock.execute = AsyncMock(return_value=instance)

        try:
            with patch(
                "neurova.tool_executor.get_workflow_executor", return_value=executor_mock
            ):
                ex = _make_executor()
                result = _run(ex._execute_canvas_run({"canvas_id": "canvas_x"}))
            assert result["success"] is True
            assert result["status"] == "completed"
            assert result["node_results"]["n1"]["status"] == "success"
        finally:
            patcher.stop()
