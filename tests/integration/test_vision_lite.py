"""
测试轻量级视觉理解模块
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def test_vision_lite():
    """测试轻量级视觉理解模块"""
    print("=" * 60)
    print("轻量级视觉理解模块测试")
    print("=" * 60)
    
    # 1. 测试依赖检测
    print("\n1. 测试依赖检测...")
    try:
        from neurova.computer_use.vision_lite import (
            HAS_PIL, HAS_OPENCV, HAS_PYTESSERACT, HAS_EASYOCR,
            is_lite_vision_available, get_lite_visual_parser
        )
        print(f"   ✓ Pillow: {HAS_PIL}")
        print(f"   ✓ OpenCV: {HAS_OPENCV}")
        print(f"   ✓ pytesseract: {HAS_PYTESSERACT}")
        print(f"   ✓ easyocr: {HAS_EASYOCR}")
        print(f"   ✓ 轻量级视觉理解可用: {is_lite_vision_available()}")
    except Exception as e:
        print(f"   ✗ 依赖检测失败: {e}")
        return
    
    # 2. 测试视觉解析器初始化
    print("\n2. 测试视觉解析器初始化...")
    try:
        parser = get_lite_visual_parser()
        if parser:
            print(f"   ✓ 轻量级视觉解析器初始化成功")
        else:
            print(f"   ✗ 轻量级视觉解析器初始化失败")
            return
    except Exception as e:
        print(f"   ✗ 视觉解析器初始化失败: {e}")
        return
    
    # 3. 测试图像解析
    print("\n3. 测试图像解析...")
    try:
        from PIL import Image
        import io
        import base64
        
        # 创建一个测试图像
        test_image = Image.new('RGB', (800, 600), color='white')
        
        # 转换为 base64
        buffer = io.BytesIO()
        test_image.save(buffer, format='PNG')
        image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        # 解析图像
        result = parser.parse_from_base64(image_base64)
        
        print(f"   ✓ 图像解析成功")
        print(f"   - 元素数量: {len(result.elements)}")
        print(f"   - 图标数量: {result.metadata.get('num_icons', 0)}")
        print(f"   - 文本数量: {result.metadata.get('num_text', 0)}")
        print(f"   - 按钮数量: {result.metadata.get('num_buttons', 0)}")
        print(f"   - 输入框数量: {result.metadata.get('num_inputs', 0)}")
        print(f"   - 解析耗时: {result.metadata.get('latency', 0):.2f}s")
        print(f"   - 模式: {result.metadata.get('mode', 'unknown')}")
        
    except Exception as e:
        print(f"   ✗ 图像解析失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 4. 测试 ComputerUseManager 集成
    print("\n4. 测试 ComputerUseManager 集成...")
    try:
        from neurova.computer_use import get_computer_use_manager
        
        manager = get_computer_use_manager()
        status = manager.get_status()
        
        print(f"   ✓ ComputerUseManager 初始化成功")
        print(f"   - 视觉理解模式: {status.get('vision_mode', 'unknown')}")
        print(f"   - 视觉理解可用: {status.get('vision_available', False)}")
        print(f"   - 视觉解析功能: {status.get('capabilities', {}).get('visual_parse', False)}")
        print(f"   - 智能点击功能: {status.get('capabilities', {}).get('smart_click', False)}")
        
    except Exception as e:
        print(f"   ✗ ComputerUseManager 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 5. 测试 Agent 集成
    print("\n5. 测试 Agent 集成...")
    try:
        from neurova.agent_core import Agent, AgentConfig
        
        config = AgentConfig(
            name="测试Agent",
            agent_id="test_agent",
            workspace_path=str(project_root),
            enable_memory=False,
        )
        
        agent = Agent(config)
        
        # 检查视觉理解工具是否已注册
        if hasattr(agent, '_builtin_computer_visual_parse'):
            print(f"   ✓ 视觉解析工具已注册到 Agent")
        else:
            print(f"   ✗ 视觉解析工具未注册到 Agent")
        
        # 检查智能点击工具是否已注册
        if hasattr(agent, '_builtin_computer_smart_click'):
            print(f"   ✓ 智能点击工具已注册到 Agent")
        else:
            print(f"   ✗ 智能点击工具未注册到 Agent")
        
    except Exception as e:
        print(f"   ✗ Agent 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_vision_lite())