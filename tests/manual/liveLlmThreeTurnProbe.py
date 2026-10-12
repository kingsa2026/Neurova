"""活体探针：真 LLM 三轮对话（台账 §6-133 分流里判「迁」的那一档）。

跑法：`PYTHONPATH="$(git rev-parse --show-toplevel)" python tests/manual/liveLlmThreeTurnProbe.py`

迁的理由：它原来叫 `tests/integration/test_live_llm.py`，待在唯一测试根里却**一条用例都不产**
（§6-133 那 26 档之一）——它本来就是一份要真配额、真模型的手工配方，全程只 print 计数、零断言，
`pytest` 收集不到它，而任何人 grep 到这个名字都会以为"跨轮对话有回归测试"。
它唯一的价值是那三步 patch（`_load_identity`/`_init_memory_modules`/`_init_cognitive_graph`）
的复现顺序，删了就把配方一起丢了。

迁过来就归 `tests/unit/ci/test_manual_live_verify_contract.py` 那条契约管：脚本构造生产持久对象
（这里 `Agent(...)` 会落会话/记忆存储）却不经隔离单点，未注入时 `get_data_root()` 直接落仓库
`data/`——所以这里必须在导入任何 `neurova.*` **之前**调 `isolatedDataRoot()`。
"""
import sys
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

#: 仓内唯一的数据根隔离落点；放在生产模块导入之前（`get_data_root()` 虽按调用时解析，
#: 编排器与连接池的构造期会立刻取它）。
isolatedDataRoot()

from neurova.agent_core import Agent, AgentConfig  # noqa: E402
from neurova.agent.chat_pipeline import ChatPipeline, ChatContext  # noqa: E402
from neurova.agent.crystallized_experience_manager import (  # noqa: E402
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
