"""临时探针：以最小配置初始化 Agent 并触发一次对话，用于堆栈定位。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncio
import logging
logging.disable(logging.CRITICAL)
from neurova.agent_core import Agent, AgentConfig


async def main():
    config = AgentConfig(
        name='smoke_agent',
        agent_id='smoke_agent',
        owner_user_id='test_user',
        workspace_path='./_smoke_workspace',
        llm_model='gpt-4o-mini',
        enable_active_skill_acquisition=True,
    )
    agent = Agent(config)
    await agent.chat('测试')


asyncio.run(main())
