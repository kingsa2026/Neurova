"""
测试脚本：最小化 Agent 配置，禁用所有可选模块
"""
import asyncio
import time
import sys

print("=== 测试：最小化 Agent 配置 ===")

# 添加调试输出到 Agent.__init__()
print("\n步骤1: 打补丁 - 禁用所有可选模块...")

# 补丁1：禁用记忆模块
class MockMemoryManager:
    def __init__(self, *args, **kwargs):
        pass

# 补丁2：禁用 TTS 管理器
class MockTTSManager:
    def __init__(self, *args, **kwargs):
        pass
    def is_initialized(self):
        return True

# 应用补丁
print("步骤2: 导入模块...")
try:
    from neurova.agent_core import Agent, AgentConfig
    from pathlib import Path
    
    # 打补丁：禁用可选模块
    import neurova.agent_core as ac
    original_init_memory = ac.Agent._init_memory_modules
    
    def mock_init_memory(self):
        print("🔍 步骤2.1: _init_memory_modules() 被调用（已禁用）", flush=True)
        # 不执行任何操作
        self.memory_manager = None
        self.storage = None
        self.temperature_engine = None
        print("🔍 步骤2.1: 完成（已禁用）", flush=True)
    
    ac.Agent._init_memory_modules = mock_init_memory
    print("✅ 补丁应用成功")
    
except Exception as e:
    print(f"❌ 导入模块失败: {e}")
    sys.exit(1)

print("\n步骤3: 创建 AgentConfig（禁用所有可选模块）...")
try:
    workspace = Path('neurova/agents/kai/workspace')
    config = AgentConfig(
        name='凯',
        agent_id='kai',
        workspace_path=str(workspace),
        llm_model='glm-5.1',
        llm_provider='volcano-coding-cn',
        enable_memory=False,  # 禁用记忆系统
        enable_streaming=False,
        enable_active_skill_acquisition=False,
        enable_cognitive_capabilities=False,  # 禁用认知能力
        enable_evolution=False,
        enable_experience_summary=False,
        enable_tts=False,  # 禁用 TTS
    )
    print("✅ AgentConfig 创建成功")
except Exception as e:
    print(f"❌ AgentConfig 创建失败: {e}")
    sys.exit(1)

print("\n步骤4: 创建 Agent（超时30秒）...")
start = time.time()
try:
    # 使用 asyncio.wait_for 设置超时
    async def create_agent():
        print("🔍 正在创建 Agent...", flush=True)
        agent = Agent(config)
        print("🔍 Agent 创建完成", flush=True)
        return agent
    
    # 注意：Agent() 是同步的，需要使用 asyncio.to_thread()
    agent = asyncio.run(asyncio.wait_for(
        asyncio.to_thread(Agent, config),
        timeout=30
    ))
    elapsed = time.time() - start
    print(f"✅ Agent 创建成功（耗时 {elapsed:.2f} 秒）")
    print(f"  Agent ID: {agent.config.agent_id}")
    print(f"  Agent 名称: {agent.config.name}")
    
except asyncio.TimeoutError:
    elapsed = time.time() - start
    print(f"❌ Agent 创建超时（{elapsed:.2f} 秒）")
    print("可能的原因：")
    print("1. LLM 客户端初始化卡住")
    print("2. 其他核心模块初始化卡住")
    sys.exit(1)
    
except Exception as e:
    elapsed = time.time() - start
    print(f"❌ Agent 创建失败（{elapsed:.2f} 秒）: {type(e).__name__}: {str(e)[:300]}")
    sys.exit(1)

print("\n步骤5: 测试 Agent.chat() 方法（超时30秒）...")
start = time.time()
try:
    result = asyncio.run(asyncio.wait_for(
        asyncio.to_thread(agent.chat, '你好'),
        timeout=30
    ))
    elapsed = time.time() - start
    print(f"✅ Agent.chat() 成功（耗时 {elapsed:.2f} 秒）")
    print(f"  回复: {str(result)[:300]}")
    
except asyncio.TimeoutError:
    elapsed = time.time() - start
    print(f"❌ Agent.chat() 超时（{elapsed:.2f} 秒）")
    print("可能的原因：")
    print("1. LLM 调用卡住")
    print("2. 记忆检索卡住")
    print("3. 其他步骤卡住")
    
except Exception as e:
    elapsed = time.time() - start
    print(f"❌ Agent.chat() 失败（{elapsed:.2f} 秒）: {type(e).__name__}: {str(e)[:300]}")

print("\n=== 测试完成 ===")
