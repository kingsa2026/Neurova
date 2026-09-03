"""
测试脚本：使用最小化的 Agent，只测试 LLM 调用
"""
import asyncio
import requests
import json

# 测试 1: 直接测试 LLM 客户端
def test_llm_client():
    print("=== 测试1: 直接测试 LLM 客户端 ===")
    from neurova.llm_client import LLMClient, LLMConfig
    
    config = LLMConfig(
        model='glm-5.1',
        api_key='test',  # 使用无效 Key 测试连接
        base_url='https://ark.cn-beijing.volces.com/api/coding/v3'
    )
    
    client = LLMClient(config)
    print("LLMClient 创建成功")
    
    try:
        response = client.chat([{'role':'user','content':'Hello'}], timeout=5)
        print("响应:", response[:100])
    except Exception as e:
        print("错误（预期）:", type(e).__name__, str(e)[:200])
    
    print("✅ LLMClient 正常工作（返回错误而不是卡住）\n")


# 测试 2: 测试 Agent 初始化
def test_agent_init():
    print("=== 测试2: 测试 Agent 初始化 ===")
    from neurova.agent_core import Agent, AgentConfig
    from pathlib import Path
    
    workspace = Path('neurova/agents/kai/workspace')
    config = AgentConfig(
        name='凯',
        agent_id='kai',
        workspace_path=str(workspace),
        llm_model='glm-5.1',
        llm_provider='volcano-coding-cn',
        enable_memory=False  # 禁用记忆系统
    )
    
    print("开始创建 Agent...")
    try:
        agent = Agent(config)
        print("✅ Agent 创建成功")
        return agent
    except Exception as e:
        print("❌ Agent 创建失败:", type(e).__name__, str(e)[:200])
        return None


# 测试 3: 测试 Agent.chat() 方法
async def test_agent_chat(agent):
    print("\n=== 测试3: 测试 Agent.chat() 方法 ===")
    
    if not agent:
        print("❌ Agent 未创建，跳过测试")
        return
    
    print("开始调用 chat()...")
    try:
        result = await asyncio.wait_for(
            agent.chat('你好'),
            timeout=10
        )
        print("✅ chat() 成功:", str(result)[:200])
    except asyncio.TimeoutError:
        print("❌ chat() 超时（10秒）")
    except Exception as e:
        print("❌ chat() 失败:", type(e).__name__, str(e)[:200])


# 主函数
async def main():
    # 测试 1
    test_llm_client()
    
    # 测试 2
    agent = test_agent_init()
    
    # 测试 3
    if agent:
        await test_agent_chat(agent)
    
    print("\n=== 测试完成 ===")


if __name__ == '__main__':
    asyncio.run(main())
