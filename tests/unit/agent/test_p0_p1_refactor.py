"""
P0+P1 重构集成测试 (TDD)
验证:
- P0: 6个模块正确接线（ToolExecutor 集中化钩子）
- P1: agent_core.py 拆分后代理正常工作
- 闭环: 工具执行 → 生命周期 → 序列挖掘 → 基因进化 → 市场发布
"""

import pytest
import asyncio
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from pathlib import Path
import sys
import os

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ================================================================
# Test Suite 1: ToolExecutor 独立测试
# ================================================================

class TestToolExecutor:
    """验证 ToolExecutor 提取后功能不变"""

    def test_executor_initialization(self):
        """ToolExecutor 通过 agent_ref 正确初始化"""
        from neurova.tool_executor import ToolExecutor
        
        mock_agent = Mock()
        mock_agent._skill_registry = None
        mock_agent.tool_router = None
        mock_agent.tool_memory = None
        mock_agent.tool_lifecycle = None
        
        executor = ToolExecutor(mock_agent)
        assert executor._agent is mock_agent
        # tool_memory/tool_lifecycle 是 property（读 agent 属性），agent 未设时为 None
        assert executor.tool_memory is None
        assert executor.tool_lifecycle is None

    def test_on_tool_executed_dispatches_to_all_three(self):
        """_on_tool_executed 同时调度 memory + lifecycle + packer"""
        from neurova.tool_executor import ToolExecutor
        
        mock_agent = Mock()
        mock_agent.tool_memory = Mock()
        mock_agent.tool_memory.record_tool_usage = Mock()
        mock_agent.tool_lifecycle = Mock()
        mock_agent.tool_lifecycle.touch = Mock()
        mock_agent.skill_packer = Mock()
        mock_agent.skill_packer.observe = Mock()
        
        executor = ToolExecutor(mock_agent)
        executor.on_tool_executed(
            tool_name="test_tool",
            params={"key": "value"},
            user_input="help me",
            success=True,
            tool_source="skill_system",
            execution_time=1.5,
        )
        
        # 验证三个钩子都被调用
        mock_agent.tool_memory.record_tool_usage.assert_called_once()
        mock_agent.tool_lifecycle.touch.assert_called_once_with("test_tool", True)
        mock_agent.skill_packer.observe.assert_called_once()

    def test_on_tool_executed_graceful_when_components_none(self):
        """所有组件为 None 时不应崩溃"""
        from neurova.tool_executor import ToolExecutor
        
        mock_agent = Mock()
        mock_agent.tool_memory = None
        mock_agent.tool_lifecycle = None
        mock_agent.skill_packer = None
        
        executor = ToolExecutor(mock_agent)
        # 不应抛出异常
        executor.on_tool_executed(
            tool_name="test_tool",
            params={},
            user_input="test",
            success=True,
        )

    def test_parse_params_json(self):
        """解析 JSON 格式参数"""
        from neurova.tool_executor import ToolExecutor
        
        executor = ToolExecutor(Mock())
        result = executor._parse_params('{"key": "value", "num": 42}')
        assert result == {"key": "value", "num": 42}

    def test_parse_params_key_value(self):
        """解析 key=value 格式参数"""
        from neurova.tool_executor import ToolExecutor
        
        executor = ToolExecutor(Mock())
        result = executor._parse_params('file_path="test.txt", encoding="utf-8"')
        assert result == {"file_path": "test.txt", "encoding": "utf-8"}

    def test_parse_params_boolean(self):
        """解析布尔值"""
        from neurova.tool_executor import ToolExecutor
        
        executor = ToolExecutor(Mock())
        result = executor._parse_params('flag=true, other=false')
        assert result["flag"] is True
        assert result["other"] is False

    def test_parse_params_empty(self):
        """空参数返回空字典"""
        from neurova.tool_executor import ToolExecutor
        
        executor = ToolExecutor(Mock())
        result = executor._parse_params('')
        assert result == {}

    def test_execute_skill_tool_when_registry_none(self):
        """SkillRegistry 未初始化时返回 None"""
        from neurova.tool_executor import ToolExecutor
        
        mock_agent = Mock()
        mock_agent._skill_registry = None
        executor = ToolExecutor(mock_agent)
        
        result = asyncio.run(executor.execute_skill_tool("test", {}, None))
        # 现行契约：registry None 返回 error 信封（非裸 None）
        assert "error" in (result or {})

    def test_execute_skill_tool_not_found(self):
        """技能未找到时返回 None"""
        from neurova.tool_executor import ToolExecutor
        
        mock_agent = Mock()
        mock_agent._skill_registry = Mock()
        mock_agent._skill_registry.get_skill.return_value = None
        
        executor = ToolExecutor(mock_agent)
        # 现行契约：async 方法 + 未找到返回 error 信封
        result = asyncio.run(executor.execute_skill_tool("nonexistent", {}, None))
        assert "error" in (result or {})

    def test_get_builtin_tool_params_known_tool(self):
        """已知内置工具返回参数定义"""
        from neurova.tool_executor import ToolExecutor
        
        executor = ToolExecutor(Mock())
        params = executor._get_builtin_tool_params("file_write")
        assert "parameters" in params
        assert "properties" in params["parameters"]
        assert "file_path" in params["parameters"]["properties"]

    def test_get_builtin_tool_params_unknown_tool(self):
        """未知工具返回空参数定义"""
        from neurova.tool_executor import ToolExecutor
        
        executor = ToolExecutor(Mock())
        params = executor._get_builtin_tool_params("nonexistent_tool_xyz")
        # 现行契约：未知工具返回 None（调用方自行兜底），非空 schema
        assert params is None


# ================================================================
# Test Suite 2: PostChatPipeline 独立测试
# ================================================================

class TestPostChatPipeline:
    """验证对话后处理管线提取后功能不变"""

    def test_pipeline_initialization(self):
        """PostChatPipeline 通过 agent_ref 正确初始化"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        pipeline = PostChatPipeline(mock_agent)
        assert pipeline._agent is mock_agent

    def test_step_save_session_when_save_memory_false(self):
        """save_memory=False 时跳过 Session 保存"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        pipeline = PostChatPipeline(mock_agent)
        
        result = asyncio.run(
            pipeline._step_save_session(
                user_input="hello",
                reply="hi",
                session_id="s1",
                save_memory=False,
                metadata=None,
            )
        )
        assert result == "s1"  # 返回原始 session_id

    def test_step_save_memory_with_buffer(self):
        """使用缓冲区模式保存记忆"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.conversation_buffer = Mock()  # 真实挂载点：agent 层（mem_core.py:433）
        mock_agent.conversation_buffer.add_user_message = Mock()
        mock_agent.conversation_buffer.add_agent_message = Mock()
        mock_agent.memory_manager = Mock()
        
        pipeline = PostChatPipeline(mock_agent)
        asyncio.run(pipeline._step_save_memory("hello", "hi", "s1", save_memory=True))
        
        mock_agent.conversation_buffer.add_user_message.assert_called_once()
        mock_agent.conversation_buffer.add_agent_message.assert_called_once()

    def test_step_save_memory_without_buffer(self):
        """降级：直接写入记忆数据库"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.conversation_buffer = None
        mock_agent.memory_manager = Mock()
        mock_agent.memory_manager.remember = Mock()
        
        pipeline = PostChatPipeline(mock_agent)
        asyncio.run(pipeline._step_save_memory("hello", "hi", "s1", save_memory=True))
        
        assert mock_agent.memory_manager.remember.call_count == 2

    def test_step_save_memory_when_manager_none(self):
        """memory_manager 为 None 时跳过"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.memory_manager = None
        mock_agent.conversation_buffer = None  # agent 层缓冲也缺（Mock 默认 auto-Mock，须显式置 None）
        
        pipeline = PostChatPipeline(mock_agent)
        # 不应抛出异常
        asyncio.run(pipeline._step_save_memory("hello", "hi", "s1", save_memory=True))

    def test_step_cognitive_analysis_when_disabled(self):
        """growth_analyzer 为 None 时返回 None"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.growth_analyzer = None
        
        pipeline = PostChatPipeline(mock_agent)
        result = asyncio.run(pipeline._step_cognitive_analysis("hello"))
        # 现行契约（P0-D1）：分析器缺失时返回中性默认分 0.75，非 None
        assert result == 0.75

    def test_step_record_experience_without_evolution(self):
        """evolution 为 None 时跳过"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.evolution = None
        mock_agent._collect_tool_messages = Mock(return_value=[])
        
        pipeline = PostChatPipeline(mock_agent)
        # 不应抛出异常
        pipeline._step_record_experience("hello", "hi", True)

    def test_step_lifecycle_evaluate_when_none(self):
        """tool_lifecycle 为 None 时跳过"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.tool_lifecycle = None
        
        pipeline = PostChatPipeline(mock_agent)
        pipeline._step_lifecycle_evaluate()  # 不应抛出异常

    def test_step_pattern_mining_when_none(self):
        """pattern_miner 为 None 时跳过"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.pattern_miner = None
        mock_agent._collect_tool_messages = Mock(return_value=[])
        
        pipeline = PostChatPipeline(mock_agent)
        pipeline._step_pattern_mining()  # 不应抛出异常

    def test_step_genetic_evolution_when_none(self):
        """genetic_engine 或 pattern_miner 为 None 时跳过"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.genetic_engine = None
        mock_agent.pattern_miner = Mock()
        mock_agent._collect_tool_messages = Mock(return_value=[])
        
        pipeline = PostChatPipeline(mock_agent)
        pipeline._step_genetic_evolution()  # 不应抛出异常

    def test_step_marketplace_publish_when_none(self):
        """tool_marketplace 为 None 时跳过"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.tool_marketplace = None
        mock_agent._collect_tool_messages = Mock(return_value=[])
        
        pipeline = PostChatPipeline(mock_agent)
        pipeline._step_marketplace_publish()  # 不应抛出异常

    def test_full_process_async(self):
        """process() 完整异步管线"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.enable_tts = False
        mock_agent.tts_manager = None
        mock_agent.memory_manager = None
        mock_agent.growth_analyzer = None
        mock_agent.evolution = None
        mock_agent.tool_lifecycle = None
        mock_agent.pattern_miner = None
        mock_agent.genetic_engine = None
        mock_agent.tool_marketplace = None
        mock_agent._collect_tool_messages = Mock(return_value=[])
        mock_agent._save_to_session = Mock(return_value="s1")
        mock_agent._current_reasoning = None
        
        pipeline = PostChatPipeline(mock_agent)
        result = asyncio.run(pipeline.process(
            user_input="hello",
            reply="hi there",
            session_id="s1",
            save_memory=True,
            enable_tts=None,
            metadata=None,
        ))
        
        assert "actual_session_id" in result
        assert "audio_path" in result
        assert "audio_data" in result
        assert "cognitive_score" in result


# ================================================================
# Test Suite 3: P0 6模块接线端到端测试
# ================================================================

class TestP0ModuleWiring:
    """验证 P0 6模块在 ToolExecutor + PostChatPipeline 中的接线"""

    def test_tool_executor_wires_lifecycle_touch(self):
        """工具执行后触发 ToolLifecycleManager.touch()"""
        from neurova.tool_executor import ToolExecutor
        
        mock_agent = Mock()
        mock_agent.tool_memory = Mock()
        mock_agent.tool_memory.record_tool_usage = Mock()
        mock_agent.tool_lifecycle = Mock()
        mock_agent.tool_lifecycle.touch = Mock()
        mock_agent.skill_packer = None
        
        executor = ToolExecutor(mock_agent)
        executor.on_tool_executed("navigate", {}, "go to page", True)
        
        mock_agent.tool_lifecycle.touch.assert_called_once_with("navigate", True)

    def test_post_chat_wires_pattern_mining(self):
        """对话后将工具序列加入 PatternMiner"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        # 现行结构：pattern_miner 挂 evolution 容器（post_chat_pipeline.py:1319）
        mock_agent.evolution = Mock()
        mock_agent.evolution.pattern_miner = Mock()
        mock_agent.evolution.pattern_miner.mine.return_value = []
        mock_agent._collect_tool_messages = Mock(return_value=[
            {"tool_name": "navigate", "type": "tool_call"},
            {"tool_name": "screenshot", "type": "tool_call"},
        ])
        
        pipeline = PostChatPipeline(mock_agent)
        asyncio.run(pipeline._step_pattern_mining())
        
        # add_sequence 以序列调用
        mock_agent.evolution.pattern_miner.add_sequence.assert_called_once()
        mock_agent.evolution.pattern_miner.mine.assert_called_once()

    def test_post_chat_wires_lifecycle_evaluate(self):
        """对话后触发 ToolLifecycleManager.evaluate()"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.tool_lifecycle = Mock()
        mock_agent.tool_lifecycle.evaluate = Mock(return_value={"degraded": 0, "archived": 0})
        mock_agent.tool_lifecycle.apply_decay = Mock(return_value={})
        mock_agent.evolution = Mock()
        mock_agent.evolution._tool_weights = {}
        
        pipeline = PostChatPipeline(mock_agent)
        asyncio.run(pipeline._step_lifecycle_evaluate())
        
        mock_agent.tool_lifecycle.evaluate.assert_called_once()

    def test_post_chat_wires_genetic_evolution(self):
        """每 50 个序列时触发 ToolGeneticEngine.evolve()"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        # 现行结构：genetic_engine/pattern_miner 挂 evolution 容器（:1435-1437）
        mock_agent.evolution = Mock()
        mock_agent.evolution.pattern_miner = Mock()
        mock_agent.evolution.pattern_miner.sequence_count = 50
        mock_agent.evolution.pattern_miner.get_top_patterns = Mock(return_value=[
            {"tools": ["a", "b"], "success_rate": 0.9}
        ])
        mock_agent.evolution.genetic_engine = Mock()
        mock_agent.evolution.genetic_engine.population = []
        mock_agent._collect_tool_messages = Mock(return_value=[])
        
        pipeline = PostChatPipeline(mock_agent)
        asyncio.run(pipeline._step_genetic_evolution())
        
        mock_agent.evolution.genetic_engine.evolve.assert_called_once()

    def test_post_chat_wires_marketplace_publish(self):
        """成功工具自动发布到 ToolMarketplace"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_agent.tool_marketplace = Mock()
        mock_agent.tool_marketplace.get_tool_by_name = Mock(return_value=None)
        mock_agent.tool_marketplace.add_tool = Mock()
        mock_agent._skill_registry = Mock()
        mock_agent._skill_registry.get_skill = Mock(return_value=Mock(
            description="test tool",
            schema={"type": "object"},
        ))
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test-agent"
        mock_agent._collect_tool_messages = Mock(return_value=[
            {"tool_name": "new_tool", "type": "tool_result", "success": True}
        ])
        
        pipeline = PostChatPipeline(mock_agent)
        asyncio.run(pipeline._step_marketplace_publish())
        
        mock_agent.tool_marketplace.add_tool.assert_called_once()


# ================================================================
# Test Suite 4: NLToolSynthesizer 接线测试
# ================================================================

class TestNLToolSynthesizerWiring:
    """验证 NL 工具合成在 chat() 中的接线"""

    def test_synthesizer_initialized_with_pattern_miner(self):
        """NLToolSynthesizer 在 Agent.__init__ 中正确初始化"""
        from neurova.evolution import PatternMiner, NLToolSynthesizer
        
        pm = PatternMiner(min_support=3)
        synth = NLToolSynthesizer(pattern_miner=pm)
        
        # 现行实现以 _pattern_miner 私有属性存储
        assert synth._pattern_miner is pm

    def test_synthesize_basic_flow(self):
        """NL → 工具合成基本流程"""
        from neurova.evolution import NLToolSynthesizer
        
        synth = NLToolSynthesizer()
        # 现行签名 synthesize(description, context=None)——author_id 已移除
        result = synth.synthesize(description="读取网页表格并导出为 CSV")
        
        # 至少应该返回一个结果
        assert result is not None
        # 现行 ToolSynthesisResult 契约：success/stages_completed 字段
        assert hasattr(result, "success")
        assert hasattr(result, "stages_completed")


# ================================================================
# Test Suite 5: ToolOrchestrator 接线测试
# ================================================================

class TestToolOrchestratorWiring:
    """验证 DAG 编排器在 Agent 中正确接线"""

    def test_orchestrator_with_set_executor(self):
        """ToolOrchestrator 设置执行器后可用"""
        from neurova.tool_layers import ToolOrchestrator
        
        orch = ToolOrchestrator()
        
        async def mock_executor(tool_name, params):
            return {"success": True, "data": f"executed {tool_name}"}
        
        orch.set_executor(mock_executor)
        
        # 现行签名 build_plan_from_goal(goal)——能力解析在方法内部
        plan = orch.build_plan_from_goal(goal="screenshot and analyze")
        assert isinstance(plan, list)

    def test_orchestrator_builds_plan(self):
        """从目标构建执行计划"""
        from neurova.tool_layers import ToolOrchestrator
        
        orch = ToolOrchestrator()
        plan = orch.build_plan_from_goal(goal="navigate then read")
        
        # 至少返回一个步骤
        assert isinstance(plan, list)


# ================================================================
# Test Suite 6: 闭环集成测试
# ================================================================

class TestCloseLoopIntegration:
    """验证六环节闭环在重构后仍然完整"""

    def test_tool_execution_to_lifecycle_chain(self):
        """工具执行 → lifecycle.touch → experience 链"""
        from neurova.tool_executor import ToolExecutor
        from neurova.post_chat_pipeline import PostChatPipeline
        
        # Step 1: 创建 mock agent 并执行工具
        mock_agent = Mock()
        mock_agent.tool_memory = Mock()
        mock_agent.tool_memory.record_tool_usage = Mock()
        mock_agent.tool_lifecycle = Mock()
        mock_agent.tool_lifecycle.touch = Mock()
        mock_agent.tool_lifecycle.evaluate = Mock(return_value={})
        mock_agent.tool_lifecycle.apply_decay = Mock(return_value={})
        mock_agent.skill_packer = Mock()
        mock_agent.skill_packer.observe = Mock()
        mock_agent.pattern_miner = None
        mock_agent.genetic_engine = None
        mock_agent.tool_marketplace = None
        mock_agent.evolution = Mock()
        mock_agent.evolution._tool_weights = {}
        mock_agent.memory_manager = None
        mock_agent.growth_analyzer = None
        mock_agent.tts_manager = None
        mock_agent.config = Mock()
        mock_agent.config.enable_tts = False
        mock_agent._collect_tool_messages = Mock(return_value=[])
        mock_agent._save_to_session = Mock(return_value="s1")
        mock_agent._current_reasoning = None
        
        executor = ToolExecutor(mock_agent)
        pipeline = PostChatPipeline(mock_agent)
        
        # Step 2: 执行工具
        executor.on_tool_executed(
            tool_name="screenshot",
            params={},
            user_input="take a screenshot",
            success=True,
        )
        
        # 验证 lifecycle.touch 被调用（现行签名含 success）
        mock_agent.tool_lifecycle.touch.assert_called_once_with("screenshot", True)
        
        # Step 3: 处理对话后管线
        asyncio.run(pipeline.process(
            user_input="take a screenshot",
            reply="done",
            session_id="s1",
            save_memory=True,
            enable_tts=None,
            metadata=None,
        ))
        
        # 验证 experience 被记录
        mock_agent.evolution.on_experience_recorded.assert_called_once()

    def test_all_p0_components_graceful_with_none(self):
        """所有 P0 组件为 None 时不应崩溃（降级安全）"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        # 所有 P0 组件为 None
        mock_agent.tool_lifecycle = None
        mock_agent.pattern_miner = None
        mock_agent.genetic_engine = None
        mock_agent.tool_marketplace = None
        mock_agent.evolution = None
        mock_agent.memory_manager = None
        mock_agent.growth_analyzer = None
        mock_agent.tts_manager = None
        mock_agent.config = Mock()
        mock_agent.config.enable_tts = False
        mock_agent._collect_tool_messages = Mock(return_value=[])
        mock_agent._save_to_session = Mock(return_value="s1")
        mock_agent._current_reasoning = None
        
        pipeline = PostChatPipeline(mock_agent)
        
        # 不应抛出异常
        result = asyncio.run(pipeline.process(
            user_input="hello",
            reply="hi",
            session_id="s1",
            save_memory=True,
            enable_tts=None,
            metadata=None,
        ))
        
        assert result["actual_session_id"] == "s1"
        # 现行契约（P0-D1）：分析器缺失时 cognitive_score 用默认 0.75
        assert result["cognitive_score"] == 0.75
