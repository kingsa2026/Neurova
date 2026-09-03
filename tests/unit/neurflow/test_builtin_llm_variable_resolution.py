"""
测试 builtin:llm 变量解析修复

验证：
1. execution_engine 将 variable_resolver 和 resolution_context 传入节点 context
2. exec_llm 中的防御性解析正确工作
3. 变量引用在 prompt 和 system_prompt 中被正确解析
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any


# ============================================================
# 辅助：构造 mock 对象
# ============================================================

def _make_variable_resolver():
    """创建 mock VariableResolver"""
    resolver = MagicMock()
    
    def mock_resolve_config(config, context):
        """模拟变量解析：将 $input.xxx 替换为实际值"""
        if isinstance(config, str):
            if "$input.user_query" in config:
                return config.replace("$input.user_query", "今天天气怎么样")
            elif "$var.answer" in config:
                return config.replace("$var.answer", "晴朗")
        elif isinstance(config, dict):
            return {k: mock_resolve_config(v, context) for k, v in config.items()}
        return config
    
    resolver.resolve_config = mock_resolve_config
    return resolver


def _make_resolution_context():
    """创建 mock ResolutionContext"""
    ctx = MagicMock()
    ctx.workflow_id = "wf_test"
    ctx.execution_id = "exec_test"
    ctx.node_results = {}
    ctx.variables = {"user_query": "今天天气怎么样", "answer": "晴朗"}
    ctx.inputs = {"user_query": "今天天气怎么样"}
    ctx.memory_manager = None
    ctx.context_pool = None
    ctx.emotion_module = None
    ctx.crystallizer = None
    return ctx


# ============================================================
# variable_resolver 传递测试
# ============================================================

class TestVariableResolverPassing:
    """测试 variable_resolver 和 resolution_context 传递到节点 context"""

    def test_variable_resolver_in_ctx(self):
        """验证 execution_engine 将 variable_resolver 传入节点 context"""
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowStatus
        )
        import time

        now = time.time()
        start_node = WorkflowNode(
            id="start", type="builtin:start",
            position={"x": 0, "y": 0}, config={},
        )
        workflow = WorkflowDefinition(
            id="wf_test", name="Test", description="test", version="1.0.0",
            nodes=[start_node],
            edges=[], variables=[], tags=[], category="general",
            author="test", created_at=now, updated_at=now,
            status=WorkflowStatus.DRAFT,
        )

        mock_variable_resolver = _make_variable_resolver()
        mock_resolution_context = _make_resolution_context()

        # 构造 mock validation result
        mock_validation = MagicMock()
        mock_validation.is_valid = True
        mock_validation.errors = []

        with patch("neurova.collaboration.neurflow.execution_engine.get_node_registry") as mock_nr, \
             patch("neurova.collaboration.neurflow.execution_engine.get_variable_resolver") as mock_vr, \
             patch("neurova.collaboration.neurflow.execution_engine.get_dag_validator") as mock_dv:
            mock_nr.return_value.ensure_builtin = MagicMock()
            mock_dv.return_value.validate.return_value = mock_validation
            mock_dv.return_value.get_execution_path.return_value = ["start"]
            mock_vr.return_value.resolve_config.return_value = {}
            executor = WorkflowExecutor()
            
            # 替换 variable_resolver 为我们的 mock
            executor._variable_resolver = mock_variable_resolver

            # 捕获 _execute_node 的 context 参数
            captured_ctx = {}
            original_execute_node = executor._execute_node

            async def spy_execute_node(node, config, context):
                captured_ctx.update(context)
                return await original_execute_node(node, config, context)

            executor._execute_node = spy_execute_node

            # 使用 asyncio.run 来运行异步测试
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                executor.execute(
                    workflow, {},
                    memory_manager=MagicMock(),
                    context_pool=MagicMock(),
                    emotion_module=MagicMock(),
                )
            )
            loop.close()

            # 验证 variable_resolver 和 resolution_context 被传入
            assert "variable_resolver" in captured_ctx
            assert "resolution_context" in captured_ctx
            assert captured_ctx["variable_resolver"] is mock_variable_resolver
            # resolution_context 是由 execution_engine 构建的，不是直接传入的 mock
            assert captured_ctx["resolution_context"] is not None


# ============================================================
# exec_llm 防御性解析测试
# ============================================================

class TestExecLlmVariableResolution:
    """测试 exec_llm 中的防御性变量解析"""

    @pytest.mark.asyncio
    async def test_no_resolver_no_resolution(self):
        """无 variable_resolver 时不进行解析"""
        with patch("neurova.collaboration.neurflow.builtin._get_agent") as mock_get_agent:
            mock_agent = AsyncMock()
            mock_agent.chat.return_value = "回答内容"
            mock_get_agent.return_value = mock_agent

            from neurova.collaboration.neurflow.builtin import exec_llm
            
            config = {
                "prompt": "用户问：$input.user_query",
                "system_prompt": "你是助手",
                "temperature": 0.7,
                "max_tokens": 1024,
            }
            ctx = {}  # 无 variable_resolver
            
            result = await exec_llm(config, ctx)
            
            assert result["status"] == "success"
            # prompt 应保持原样（未解析）
            call_args = mock_agent.chat.call_args
            assert call_args[0][0] == "用户问：$input.user_query"

    @pytest.mark.asyncio
    async def test_resolver_resolves_prompt(self):
        """有 variable_resolver 时解析 prompt 中的变量"""
        with patch("neurova.collaboration.neurflow.builtin._get_agent") as mock_get_agent:
            mock_agent = AsyncMock()
            mock_agent.chat.return_value = "回答内容"
            mock_get_agent.return_value = mock_agent

            from neurova.collaboration.neurflow.builtin import exec_llm
            
            mock_resolver = _make_variable_resolver()
            mock_res_ctx = _make_resolution_context()
            
            config = {
                "prompt": "用户问：$input.user_query",
                "system_prompt": "你是助手",
                "temperature": 0.7,
                "max_tokens": 1024,
            }
            ctx = {
                "variable_resolver": mock_resolver,
                "resolution_context": mock_res_ctx,
            }
            
            result = await exec_llm(config, ctx)
            
            assert result["status"] == "success"
            # prompt 应被解析
            call_args = mock_agent.chat.call_args
            assert call_args[0][0] == "用户问：今天天气怎么样"

    @pytest.mark.asyncio
    async def test_resolver_resolves_system_prompt(self):
        """有 variable_resolver 时解析 system_prompt 中的变量"""
        with patch("neurova.collaboration.neurflow.builtin._get_agent") as mock_get_agent:
            mock_agent = AsyncMock()
            mock_agent.chat.return_value = "回答内容"
            mock_get_agent.return_value = mock_agent

            from neurova.collaboration.neurflow.builtin import exec_llm
            
            mock_resolver = _make_variable_resolver()
            mock_res_ctx = _make_resolution_context()
            
            config = {
                "prompt": "简单问题",
                "system_prompt": "根据变量 $var.answer 回答",
                "temperature": 0.7,
                "max_tokens": 1024,
            }
            ctx = {
                "variable_resolver": mock_resolver,
                "resolution_context": mock_res_ctx,
            }
            
            result = await exec_llm(config, ctx)
            
            assert result["status"] == "success"
            # system_prompt 应被解析
            call_args = mock_agent.chat.call_args
            assert call_args[1]["system_prompt"] == "根据变量 晴朗 回答"

    @pytest.mark.asyncio
    async def test_no_variable_refs_no_resolution(self):
        """无变量引用时不进行解析（即使有 resolver）"""
        with patch("neurova.collaboration.neurflow.builtin._get_agent") as mock_get_agent:
            mock_agent = AsyncMock()
            mock_agent.chat.return_value = "回答内容"
            mock_get_agent.return_value = mock_agent

            from neurova.collaboration.neurflow.builtin import exec_llm
            
            mock_resolver = _make_variable_resolver()
            mock_res_ctx = _make_resolution_context()
            
            config = {
                "prompt": "简单问题",
                "system_prompt": "你是助手",
                "temperature": 0.7,
                "max_tokens": 1024,
            }
            ctx = {
                "variable_resolver": mock_resolver,
                "resolution_context": mock_res_ctx,
            }
            
            result = await exec_llm(config, ctx)
            
            assert result["status"] == "success"
            # prompt 和 system_prompt 应保持原样
            call_args = mock_agent.chat.call_args
            assert call_args[0][0] == "简单问题"
            assert call_args[1]["system_prompt"] == "你是助手"

    @pytest.mark.asyncio
    async def test_resolver_exception_fallback(self):
        """resolver 异常时不影响 LLM 调用"""
        with patch("neurova.collaboration.neurflow.builtin._get_agent") as mock_get_agent:
            mock_agent = AsyncMock()
            mock_agent.chat.return_value = "回答内容"
            mock_get_agent.return_value = mock_agent

            from neurova.collaboration.neurflow.builtin import exec_llm
            
            mock_resolver = MagicMock()
            mock_resolver.resolve_config.side_effect = RuntimeError("解析失败")
            mock_res_ctx = _make_resolution_context()
            
            config = {
                "prompt": "用户问：$input.user_query",
                "system_prompt": "你是助手",
                "temperature": 0.7,
                "max_tokens": 1024,
            }
            ctx = {
                "variable_resolver": mock_resolver,
                "resolution_context": mock_res_ctx,
            }
            
            result = await exec_llm(config, ctx)
            
            # 应该仍然成功（resolver 异常被捕获，prompt 保持原样）
            assert result["status"] == "success"
            call_args = mock_agent.chat.call_args
            assert call_args[0][0] == "用户问：$input.user_query"

    @pytest.mark.asyncio
    async def test_agent_unavailable(self):
        """Agent 未初始化时返回 failed"""
        with patch("neurova.collaboration.neurflow.builtin._get_agent") as mock_get_agent:
            mock_get_agent.return_value = None

            from neurova.collaboration.neurflow.builtin import exec_llm
            
            config = {"prompt": "test"}
            ctx = {}
            
            result = await exec_llm(config, ctx)
            
            assert result["status"] == "failed"
            assert "Agent 未初始化" in result["error"]


# ============================================================
# 集成测试：resolver + context_pool + emotion_module
# ============================================================

class TestFullContextIntegration:
    """测试所有外部系统引用的完整集成"""

    def test_all_external_refs_in_context(self):
        """验证所有外部系统引用都在节点 context 中"""
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowStatus
        )
        import time

        now = time.time()
        start_node = WorkflowNode(
            id="start", type="builtin:start",
            position={"x": 0, "y": 0}, config={},
        )
        workflow = WorkflowDefinition(
            id="wf_test", name="Test", description="test", version="1.0.0",
            nodes=[start_node],
            edges=[], variables=[], tags=[], category="general",
            author="test", created_at=now, updated_at=now,
            status=WorkflowStatus.DRAFT,
        )

        mock_memory = MagicMock()
        mock_context = MagicMock()
        mock_emotion = MagicMock()
        mock_crystallizer = MagicMock()
        mock_variable_resolver = _make_variable_resolver()

        # 构造 mock validation result
        mock_validation = MagicMock()
        mock_validation.is_valid = True
        mock_validation.errors = []

        with patch("neurova.collaboration.neurflow.execution_engine.get_node_registry") as mock_nr, \
             patch("neurova.collaboration.neurflow.execution_engine.get_variable_resolver") as mock_vr, \
             patch("neurova.collaboration.neurflow.execution_engine.get_dag_validator") as mock_dv:
            mock_nr.return_value.ensure_builtin = MagicMock()
            mock_dv.return_value.validate.return_value = mock_validation
            mock_dv.return_value.get_execution_path.return_value = ["start"]
            mock_vr.return_value.resolve_config.return_value = {}
            executor = WorkflowExecutor()
            
            # 替换 variable_resolver 为我们的 mock
            executor._variable_resolver = mock_variable_resolver

            # 捕获 _execute_node 的 context 参数
            captured_ctx = {}
            original_execute_node = executor._execute_node

            async def spy_execute_node(node, config, context):
                captured_ctx.update(context)
                return await original_execute_node(node, config, context)

            executor._execute_node = spy_execute_node

            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                executor.execute(
                    workflow, {},
                    memory_manager=mock_memory,
                    context_pool=mock_context,
                    emotion_module=mock_emotion,
                    crystallizer=mock_crystallizer,
                )
            )
            loop.close()

            # 验证所有外部系统引用都在 context 中
            assert captured_ctx.get("memory_manager") is mock_memory
            assert captured_ctx.get("context_pool") is mock_context
            assert captured_ctx.get("emotion_module") is mock_emotion
            assert captured_ctx.get("crystallizer") is mock_crystallizer
            assert "variable_resolver" in captured_ctx
            assert "resolution_context" in captured_ctx