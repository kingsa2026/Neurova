"""
测试 Computer Use 工具集成
验证 Agent 能否通过 LLM 调用 Computer Use 工具
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def test_computer_use_tools():
    """测试 Computer Use 工具是否正确注册"""
    print("=" * 60)
    print("Computer Use 集成测试")
    print("=" * 60)
    
    # 1. 测试 ComputerUseManager
    print("\n1. 测试 ComputerUseManager 初始化...")
    try:
        from neurova.computer_use import get_computer_use_manager, ComputerUseManager
        manager = get_computer_use_manager()
        status = manager.get_status()
        print(f"   ✓ ComputerUseManager 已初始化")
        print(f"   - 真实模式: {status.get('real_mode', False)}")
        print(f"   - pyautogui: {status.get('has_pyautogui', False)}")
        print(f"   - Pillow: {status.get('has_pil', False)}")
        print(f"   - 视觉理解: {status.get('has_vision', False)}")
    except Exception as e:
        print(f"   ✗ ComputerUseManager 初始化失败: {e}")
        return
    
    # 2. 测试 Agent 初始化（包含 Computer Use 工具）
    print("\n2. 测试 Agent 初始化...")
    try:
        from neurova.agent_core import Agent, AgentConfig
        
        config = AgentConfig(
            name="测试Agent",
            agent_id="test_agent",
            workspace_path=str(project_root),
            enable_memory=False,  # 禁用记忆以简化测试
        )
        
        agent = Agent(config)
        print(f"   ✓ Agent 初始化成功")
        
        # 检查 Computer Use 工具是否已注册
        if hasattr(agent, '_builtin_computer_screenshot'):
            print(f"   ✓ Computer Use 工具已注册到 Agent")
        else:
            print(f"   ✗ Computer Use 工具未注册到 Agent")
            
    except Exception as e:
        print(f"   ✗ Agent 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 3. 测试工具参数 schema
    print("\n3. 测试工具参数 schema...")
    computer_tools = [
        "computer_screenshot",
        "computer_click", 
        "computer_type",
        "computer_scroll",
        "computer_shell",
        "computer_visual_parse",
        "computer_smart_click",
        "computer_smart_type",
    ]
    
    for tool_name in computer_tools:
        schema = agent._get_builtin_tool_params(tool_name)
        if schema and "description" in schema:
            print(f"   ✓ {tool_name}: {schema['description'][:50]}...")
        else:
            print(f"   ✗ {tool_name}: schema 缺失")
    
    # 4. 测试 _build_tools_for_llm
    print("\n4. 测试 _build_tools_for_llm...")
    try:
        tools = await agent._build_tools_for_llm()
        if tools:
            tool_names = [t['function']['name'] for t in tools]
            computer_tools_in_llm = [t for t in tool_names if t.startswith('computer_')]
            print(f"   ✓ 总工具数: {len(tools)}")
            print(f"   ✓ Computer Use 工具数: {len(computer_tools_in_llm)}")
            print(f"   ✓ Computer Use 工具: {computer_tools_in_llm}")
        else:
            print(f"   ✗ 未获取到工具列表")
    except Exception as e:
        print(f"   ✗ _build_tools_for_llm 失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 5. 测试 ToolRouter 注册
    print("\n5. 测试 ToolRouter 注册...")
    if agent.tool_router:
        try:
            all_tools = await agent.tool_router.get_all_tools(
                agent_id="test_agent",
                user_id="default"
            )
            tool_names = [t.name for t in all_tools]
            computer_tools_in_router = [t for t in tool_names if t.startswith('computer_')]
            print(f"   ✓ ToolRouter 工具总数: {len(all_tools)}")
            print(f"   ✓ Computer Use 工具数: {len(computer_tools_in_router)}")
            print(f"   ✓ Computer Use 工具: {computer_tools_in_router}")
        except Exception as e:
            print(f"   ✗ ToolRouter 查询失败: {e}")
    else:
        print(f"   ✗ ToolRouter 未初始化")
    
    # 6. 测试单个工具执行（模拟模式）
    print("\n6. 测试工具执行（模拟模式）...")
    try:
        # 测试截图
        result = await agent._builtin_computer_screenshot({})
        if result.get("success") or result.get("image_base64"):
            print(f"   ✓ computer_screenshot 执行成功")
        else:
            print(f"   ✗ computer_screenshot 执行失败: {result}")
        
        # 测试点击
        result = await agent._builtin_computer_click({"x": 100, "y": 200})
        if result.get("success"):
            print(f"   ✓ computer_click 执行成功")
        else:
            print(f"   ✗ computer_click 执行失败: {result}")
        
        # 测试输入
        result = await agent._builtin_computer_type({"text": "Hello World"})
        if result.get("success"):
            print(f"   ✓ computer_type 执行成功")
        else:
            print(f"   ✗ computer_type 执行失败: {result}")
            
    except Exception as e:
        print(f"   ✗ 工具执行测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_computer_use_tools())