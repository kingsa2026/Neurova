"""测试工具调用 + 技能检索能力是否真实可用"""
import asyncio
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.CRITICAL)
from neurova.agent_core import Agent, AgentConfig


async def main():
    # 启用技能获取
    config = AgentConfig(
        name="cap_test",
        agent_id="cap_test",
        owner_user_id="test_user",
        workspace_path="./_cap_workspace",
        llm_model="gpt-4o-mini",
        enable_active_skill_acquisition=True,
        enable_skill_packer=True,
    )
    agent = Agent(config)

    # 先触发懒初始化 (chat 内部会 init_router)
    try:
        await agent.chat("warmup")
    except Exception:
        pass
    # === 工具测试 ===
    print("=== [工具] 注册表 ===")
    tre = agent.tool_executor
    # 列出工具
    if hasattr(tre, 'list_tools'):
        tools = tre.list_tools()
    elif hasattr(tre, '_tools'):
        tools = list(tre._tools.keys())
    else:
        tools = []
    print(f"  工具数: {len(tools)}")
    for t in (list(tools)[:8] if isinstance(tools, (list, dict)) else []) :
        print(f"    - {t}")

    # 尝试直接执行一个工具（如果有 calculator / echo 类）
    print("\n=== [工具] 直接调用 ===")
    test_tool = None
    for name in ['calculator', 'echo', 'time', 'datetime', 'web_search', 'file_read']:
        if name in (tools if isinstance(tools, (list, dict)) else []):
            test_tool = name
            break
    # === 技能测试 ===
    print("\n=== [技能] 检索 ===")
    sm = agent.skill_manager
    if sm is not None:
        try:
            skills = sm.list_skills() if hasattr(sm, 'list_skills') else (sm.skills if hasattr(sm, 'skills') else {})
            print(f"  技能数: {len(skills)}")
            # 尝试检索相关技能
            if hasattr(sm, 'retrieve_skills'):
                rec = sm.retrieve_skills("如何写 Python 代码", limit=3)
                print(f"  检索 'Python' 返回 {len(rec)} 个技能")
        except Exception as e:
            print(f"  [BUG] 技能检索异常: {type(e).__name__}: {e}")
    else:
        print("  [WARN] skill_manager 为 None（需配置启用）")

    # === 通过对话触发技能 ===
    print("\n=== [对话] 触发技能/工具 ===")
    try:
        reply = await agent.chat("帮我用计算器算一下 123 * 456")
        print(f"  回复片段: {str(reply)[:120]}")
    except Exception as e:
        import traceback
        print(f"  [BUG] 对话异常: {type(e).__name__}: {e}")
        traceback.print_exc()

    print("\n=== 工具/技能测试完成 ===")


asyncio.run(main())

