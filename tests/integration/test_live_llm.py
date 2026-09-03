"""实际对话测试 - 使用真实 LLM"""
import sys
import asyncio
import tempfile
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, '.')

from neurova.agent_core import Agent, AgentConfig
from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
from neurova.agent.crystallized_experience_manager import (
    CrystallizedExperienceManager, RetrievalStatus, CrystallizedExperience, RetrievalResult
)


def main():
    with patch.object(Agent, '_load_identity'), \
         patch.object(Agent, '_init_memory_modules'), \
         patch.object(Agent, '_init_cognitive_graph'):
        config = AgentConfig(
            agent_id='live_test', name='LiveTest',
            workspace_path=tempfile.mkdtemp(),
            enable_memory=False, enable_tts=False, enable_asr=False,
            enable_evolution=True, enable_experience_summary=True,
            enable_cognitive_capabilities=False,
        )
        agent = Agent(config=config)

    print('=== Agent init OK ===')
    print('Evolution:', 'OK' if agent.evolution else 'MISSING')

    # 补充 _load_identity 跳过的属性
    agent.soul = 'You are a helpful AI assistant.'
    agent.personality = 'Friendly'
    agent.conversation_history = []
    agent._tool_messages_list = []
    agent._last_tool_used = None

    # Mock tool_executor 的 execute_text_tool_calls 避免解析 bug
    agent.tool_executor.execute_text_tool_calls = AsyncMock(side_effect=lambda r, u: r)

    mock_cem = MagicMock()
    mock_cem.retrieve = AsyncMock(return_value=RetrievalResult(
        status=RetrievalStatus.SUCCESS, experiences=[], source='crystallized', latency_ms=5.0,
    ))

    async def run():
        pipeline = ChatPipeline(agent)

        print('\n--- Round 1: Hello ---')
        with patch('neurova.agent.chat_pipeline.CrystallizedExperienceManager', return_value=mock_cem):
            ctx1 = ChatContext(user_input='你好，请用一句话介绍你自己')
            r1 = await pipeline.execute(ctx1)
            print('Reply:', r1.get('text', '')[:200])

        print('\n--- Round 2: Python ---')
        with patch('neurova.agent.chat_pipeline.CrystallizedExperienceManager', return_value=mock_cem):
            ctx2 = ChatContext(user_input='Python是什么？')
            r2 = await pipeline.execute(ctx2)
            print('Reply:', r2.get('text', '')[:200])

        print('\n--- Round 3: Memory ---')
        with patch('neurova.agent.chat_pipeline.CrystallizedExperienceManager', return_value=mock_cem):
            ctx3 = ChatContext(user_input='你刚才说了什么？')
            r3 = await pipeline.execute(ctx3)
            print('Reply:', r3.get('text', '')[:200])

        print('\n=== Loop Stats ===')
        print('Context builds:', agent.context_orchestrator.build_context.call_count)
        print('Post-chat:', agent.post_chat_pipeline.process.call_count)
        print('Memory updates:', agent.memory_agent.update_history.call_count)

    asyncio.run(run())


if __name__ == '__main__':
    main()
