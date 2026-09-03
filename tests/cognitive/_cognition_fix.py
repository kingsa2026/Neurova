
"""
测试认知编排器和技能注册表修复
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'neurova'))

print("=== 测试认知编排器和技能注册表修复 ===\n")

# 测试 1: 导入 get_cognition_orchestrator
print("1. 测试导入 get_cognition_orchestrator...")
try:
    from neurova.core.cognition_orchestrator import get_cognition_orchestrator
    print("✓ get_cognition_orchestrator 导入成功")
except Exception as e:
    print(f"✗ 导入失败: {e}")
    sys.exit(1)

# 测试 2: 获取认知编排器实例
print("\n2. 测试获取认知编排器实例...")
try:
    orchestrator = get_cognition_orchestrator()
    print(f"✓ 认知编排器实例创建成功: {orchestrator}")
except Exception as e:
    print(f"✗ 创建失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试 3: 检查技能注册表
print("\n3. 检查技能注册表...")
try:
    registry = orchestrator.get_registry()
    if registry:
        print("✓ 技能注册表已初始化")
        if hasattr(registry, 'skills'):
            print(f"✓ 注册表中有 {len(registry.skills)} 个技能")
        else:
            print("⚠  技能注册表结构可能与预期不同")
    else:
        print("⚠  技能注册表未找到")
except Exception as e:
    print(f"✗ 检查技能注册表失败: {e}")

# 测试 4: 测试 process_thought_cycle
print("\n4. 测试认知循环...")
try:
    result = orchestrator.process_thought_cycle({
        "query": "你好，请测试一下",
        "session_id": "test_session_123"
    })
    print(f"✓ 认知循环执行成功")
    print(f"  - 成功: {result.success}")
    print(f"  - 执行时间: {result.execution_time:.2f}秒")
    if hasattr(result, 'decision') and result.decision:
        print(f"  - 决策: {result.decision.get('action', 'unknown')}")
    if hasattr(result, 'execution_result') and result.execution_result:
        print(f"  - 执行结果: {result.execution_result}")
except Exception as e:
    print(f"✗ 认知循环执行失败: {e}")
    import traceback
    traceback.print_exc()

print("\n=== 测试完成 ===")
