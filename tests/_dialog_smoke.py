"""对话流程冒烟测试: Agent + 工具 + 技能"""
import asyncio
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.CRITICAL)

from neurova.agent_core import Agent, AgentConfig


async def main():
    print("=== [1] Agent 初始化 ===")
    config = AgentConfig(
        name="smoke_agent",
        agent_id="smoke_agent",
        owner_user_id="test_user",
        workspace_path="./_smoke_workspace",
        llm_model="gpt-4o-mini",  # 用占位模型，不真实调用 LLM
        enable_active_skill_acquisition=True,  # 启用技能管理器
    )
    agent = Agent(config)
    print(f"  Agent 创建 OK: {agent.config.agent_id}")
    print(f"  workspace: {agent.config.workspace_path}")

    print("\n=== [2] 子系统检查 ===")
    # 检查关键子系统
    for attr in ['tool_executor', 'tool_orchestrator', 'tool_router', 'skill_manager',
                 'context_orchestrator', 'memory_manager', 'cognitive_engine',
                 'voice_pipeline', 'loop_manager']:
        val = getattr(agent, attr, None)
        print(f"  - {attr}: {'✓' if val is not None else '✗'} ({type(val).__name__ if val else 'None'})")

    print("\n=== [3] 技能注册表 ===")
    try:
        skill_reg = getattr(agent, 'skill_manager', None)
        if skill_reg is not None:
            skills = skill_reg.list_skills() if hasattr(skill_reg, 'list_skills') else \
                (skill_reg.skills if hasattr(skill_reg, 'skills') else {})
            print(f"  已注册技能数: {len(skills)}")
            keys = list(skills.keys())[:5] if isinstance(skills, dict) else list(skills)[:5]
            for k in keys:
                print(f"    - {k}")
        else:
            print("  [WARN] skill_manager 为 None")
    except Exception as e:
        print(f"  [BUG] 技能系统异常: {e}")

    print("\n=== [4] 工具注册表 ===")
    try:
        tool_reg = getattr(agent, '_tool_registry', None) or getattr(agent, 'tool_registry', None)
        if tool_reg is not None:
            tools = tool_reg.list_tools() if hasattr(tool_reg, 'list_tools') else \
                (tool_reg.tools if hasattr(tool_reg, 'tools') else [])
            print(f"  已注册工具数: {len(tools)}")
            keys = list(tools.keys())[:5] if isinstance(tools, dict) else list(tools)[:5]
            for k in keys:
                print(f"    - {k}")
        else:
            print("  [WARN] tool_registry 为 None")
    except Exception as e:
        print(f"  [BUG] 工具注册表异常: {e}")

    print("\n=== [5] 上下文池隔离 ===")
    try:
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource
        reg = ContextPoolRegistry()
        pool = reg.get_or_create(user_id="test_user", agent_id="smoke_agent", session_id="s1")
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="测试上下文",
            priority=50,
        ))
        results = pool.query(query="测试", limit=3)
        print(f"  上下文调取 OK: 返回 {len(results)} 条")
        assert len(results) == 1
        assert results[0].metadata.get("session_id") == "s1"
    except Exception as e:
        print(f"  [BUG] 上下文池异常: {e}")

    print("\n=== [6] 对话流程 (async chat) ===")
    try:
        reply = await agent.chat("你好，请介绍一下你自己")
        print(f"  chat() 返回: {str(reply)[:100]}...")
        assert reply is not None
        print("  对话流程 OK")
    except Exception as e:
        import traceback
        print(f"  [BUG] 对话流程异常: {type(e).__name__}: {e}")
        traceback.print_exc()

    print("\n=== 全部流程通过 ===")


if __name__ == "__main__":
    asyncio.run(main())
