"""
集成测试 - Agent → Router → Skill 完整调用链
"""
import pytest
from unittest.mock import MagicMock, patch
from neurova.router import MessageRouter, Message, MessageType, create_default_router
from neurova.skill_system import SkillRegistry, create_default_skills


class TestAgentRouterSkillChain:
    """测试 Agent → Router → Skill 完整调用链"""

    @patch('neurova.agent.LLMClient')
    @patch('neurova.agent.ContextBuilder')
    def test_full_chain_chat(self, mock_ctx, mock_llm, temp_workspace):
        """完整聊天调用链"""
        mock_llm_instance = MagicMock()
        mock_llm_instance.chat.return_value = MagicMock(content="AI回复")
        mock_llm.return_value = mock_llm_instance

        mock_ctx_instance = MagicMock()
        mock_ctx_instance.build_context.return_value = [
            {"role": "system", "content": "系统"},
            {"role": "user", "content": "你好"},
        ]
        mock_ctx_instance.compress_if_needed.return_value = [
            {"role": "system", "content": "系统"},
            {"role": "user", "content": "你好"},
        ]
        mock_ctx.return_value = mock_ctx_instance

        from neurova.agent import Agent, AgentConfig
        config = AgentConfig(
            workspace_path=str(temp_workspace),
            enable_memory=False,
        )
        agent = Agent(config=config)

        # 创建路由器并注册Agent
        router = create_default_router(agent=agent)

        # 通过路由器发送消息
        result = router.route(Message(content="你好"))
        assert result.success is True
        assert result.message_type == MessageType.CHAT

    def test_full_chain_with_memory(self, temp_workspace, temp_db_path):
        """带记忆的完整调用链"""
        from neurova.agent import Agent, AgentConfig
        config = AgentConfig(
            workspace_path=str(temp_workspace),
            db_path=temp_db_path,
            enable_memory=True,
        )
        agent = Agent(config=config)
        agent.init_router()

        router = agent.router
        # 使用普通消息
        result = router.route(Message(content="你好"))
        assert result.success is True

    @patch('neurova.agent.LLMClient')
    def test_command_routing(self, mock_llm, temp_workspace):
        """命令路由"""
        mock_llm_instance = MagicMock()
        mock_llm.return_value = mock_llm_instance

        from neurova.agent import AgentConfig
        config = AgentConfig(workspace_path=str(temp_workspace), enable_memory=False)
        agent = None  # 测试默认路由器

        router = create_default_router(agent=agent)
        result = router.route(Message(content="/help"))
        assert result.success is True
        assert result.message_type == MessageType.COMMAND

    def test_skill_execution_chain(self):
        """Skill执行链"""
        registry = create_default_skills()
        result = registry.execute_skill("web_search", query="测试搜索")
        assert result.success is True

    @patch('neurova.agent.LLMClient')
    @patch('neurova.agent.ContextBuilder')
    def test_multi_turn_conversation(self, mock_ctx, mock_llm, temp_workspace):
        """多轮对话"""
        mock_llm_instance = MagicMock()
        mock_llm_instance.chat.return_value = MagicMock(content="AI回复")
        mock_llm.return_value = mock_llm_instance

        mock_ctx_instance = MagicMock()
        mock_ctx_instance.build_context.return_value = [
            {"role": "system", "content": "系统"},
            {"role": "user", "content": "你好"},
        ]
        mock_ctx_instance.compress_if_needed.return_value = [
            {"role": "system", "content": "系统"},
            {"role": "user", "content": "你好"},
        ]
        mock_ctx.return_value = mock_ctx_instance

        from neurova.agent import AgentConfig
        config = AgentConfig(workspace_path=str(temp_workspace), enable_memory=False)

        from neurova.agent import Agent
        agent = Agent(config=config)
        router = create_default_router(agent=agent)

        # 第一轮
        result1 = router.route(Message(content="你好"))
        assert result1.success is True

        # 第二轮
        result2 = router.route(Message(content="你今天怎么样？"))
        assert result2.success is True

        # 第三轮
        result3 = router.route(Message(content="再见"))
        assert result3.success is True

        assert len(agent.conversation_history) == 6  # 3轮 = 6条消息


class TestMemorySystemFullFlow:
    """测试记忆系统完整流程"""

    def test_full_memory_lifecycle(self, sample_memory_manager):
        """记忆完整生命周期：记住 → 检索 → 升温 → 衰减 → 遗忘"""
        # 1. 记住
        memory_id = sample_memory_manager.remember(
            content="用户喜欢编程和阅读",
            category="profile",
            emotion_score=0.7,
        )
        assert memory_id.startswith('mem_')

        # 2. 检索
        results = sample_memory_manager.recall(query="编程", limit=5)
        assert len(results) >= 1

        # 3. 检查访问次数增加
        retrieved = sample_memory_manager.storage.get(memory_id)
        assert retrieved['access_count'] >= 1

        # 4. 建立关联
        memory_id2 = sample_memory_manager.remember(content="用户是程序员")
        sample_memory_manager.relate(memory_id, memory_id2, 'related')

        # 5. 衰减周期
        updated = sample_memory_manager.run_decay_cycle()
        assert isinstance(updated, int)

        # 6. 遗忘 - 由于FK约束，需要先删除关联
        sample_memory_manager.storage.conn.execute(
            "DELETE FROM memory_relations WHERE source_memory_id = ? OR target_memory_id = ?",
            (memory_id, memory_id)
        )
        sample_memory_manager.storage.conn.commit()
        sample_memory_manager.forget(memory_id)
        assert sample_memory_manager.storage.get(memory_id) is None

    def test_memory_with_emotion(self, sample_memory_manager):
        """带情感的记忆流程"""
        memory_id = sample_memory_manager.remember(
            content="用户分享了一个悲伤的故事",
            category="emotional",
            emotion_score=0.8,
        )

        results = sample_memory_manager.recall(query="悲伤", limit=5)
        assert len(results) >= 1

    def test_crystallized_memory_persistence(self, sample_memory_manager):
        """固化记忆持久性测试"""
        memory_id = sample_memory_manager.remember(
            content="用户的生日是3月15日",
            is_crystallized=True,
        )

        retrieved = sample_memory_manager.storage.get(memory_id)
        assert retrieved['temperature'] == 100.0

        # 衰减不应影响固化记忆
        sample_memory_manager.run_decay_cycle()
        retrieved = sample_memory_manager.storage.get(memory_id)
        assert retrieved['temperature'] == 100.0


class TestChannelMessageProcessing:
    """测试多渠道消息处理"""

    def test_message_from_different_senders(self):
        """不同发送者的消息处理"""
        router = create_default_router()

        senders = ["user_1", "user_2", "admin"]
        for sender in senders:
            msg = Message(content=f"来自{sender}的消息", sender=sender)
            result = router.route(msg)
            assert result.success is True

    def test_message_types_processing(self):
        """不同类型消息处理"""
        router = create_default_router()

        # 普通消息
        result_chat = router.route(Message(content="普通消息"))
        assert result_chat.success is True

        # 问题 - 中文问号不匹配英文正则，归类为CHAT
        result_question = router.route(Message(content="这是一个问题？"))
        assert result_question.success is True
        # 中文问号不匹配 \?$ 正则
        assert result_question.message_type == MessageType.CHAT

        # 英文问号匹配问题模式
        result_eng_question = router.route(Message(content="Is this a question?"))
        assert result_eng_question.message_type == MessageType.QUESTION

        # 命令
        result_cmd = router.route(Message(content="/help"))
        assert result_cmd.success is True

    def test_skill_request_routing(self):
        """Skill请求路由 - 需要注入SkillRegistry"""
        from neurova.skill import create_default_skills
        registry = create_default_skills()
        router = create_default_router(skill_registry=registry)
        result = router.route(Message(content="帮我搜索天气"))
        assert result.success is True
        assert result.message_type == MessageType.SKILL_REQUEST

    def test_memory_request_routing(self):
        """记忆请求路由 - 需要注入MemoryManager"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.db"
            from neurova.memory import MemoryManager
            manager = MemoryManager(db_path)
            manager.remember(content="之前说过的话")
            router = create_default_router(memory_manager=manager)
            result = router.route(Message(content="回忆一下之前"))
            assert result.success is True
            manager.close()


class TestContextBuilderIntegration:
    """测试上下文构建器集成"""

    def test_context_with_memories(self):
        """带记忆的上下文构建"""
        from neurova.context import ContextBuilder
        builder = ContextBuilder()

        memories = [
            {"content": "用户喜欢苹果", "temperature": 75.0, "is_important": True},
            {"content": "用户是程序员", "temperature": 50.0},
        ]

        context = builder.build_context(
            system_prompt="你是AI助手",
            memories=memories,
            conversation_history=[
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好！"},
            ],
            user_input="你喜欢什么？",
        )

        assert len(context) >= 3
        assert context[0]["role"] == "system"
        assert "相关记忆" in context[0]["content"]

    def test_context_compression(self):
        """上下文压缩"""
        from neurova.context import ContextBuilder
        builder = ContextBuilder()

        # 创建长对话历史
        history = []
        for i in range(20):
            history.append({"role": "user", "content": f"消息{i}" * 100})
            history.append({"role": "assistant", "content": f"回复{i}" * 100})

        context = builder.build_context(
            system_prompt="系统提示",
            memories=[],
            conversation_history=history,
            user_input="最新消息",
        )

        # 压缩后应该控制长度
        compressed = builder.compress_if_needed(context)
        assert len(compressed) <= len(context)

    def test_context_with_emotion(self):
        """带情感的上下文"""
        from neurova.context import ContextBuilder
        builder = ContextBuilder()

        agent_emotion = {"joy": 0.8, "hope": 0.6}
        context = builder.build_context(
            system_prompt="系统提示",
            memories=[],
            conversation_history=[],
            user_input="你好",
            agent_emotion=agent_emotion,
        )

        assert "情感状态" in context[0]["content"]


class TestLLMClientIntegration:
    """测试LLM客户端集成"""

    def test_llm_mock_response(self):
        """模拟LLM响应"""
        from neurova.llm_client import LLMClient, LLMConfig
        config = LLMConfig(api_key="", model="gpt-4")  # 空key进入模拟模式
        client = LLMClient(config)

        response = client.chat([{"role": "user", "content": "你好"}])
        assert response.content != ""
        assert response.role == "assistant"

    def test_llm_stream_mock_response(self):
        """模拟流式LLM响应"""
        from neurova.llm_client import LLMClient, LLMConfig
        config = LLMConfig(api_key="", model="gpt-4")
        client = LLMClient(config)

        chunks = list(client.chat_stream([{"role": "user", "content": "你好"}]))
        assert len(chunks) > 0

    def test_llm_token_count(self):
        """Token计数"""
        from neurova.llm_client import LLMClient, LLMConfig
        config = LLMConfig(api_key="")
        client = LLMClient(config)

        chinese_tokens = client.count_tokens("你好世界")
        assert chinese_tokens > 0

        english_tokens = client.count_tokens("hello world")
        assert english_tokens > 0

    def test_llm_stats(self):
        """LLM统计"""
        from neurova.llm_client import LLMClient, LLMConfig
        config = LLMConfig(api_key="")
        client = LLMClient(config)

        client.chat([{"role": "user", "content": "测试"}])
        stats = client.get_stats()
        assert stats["request_count"] >= 1
        assert stats["success_rate"] == 1.0
