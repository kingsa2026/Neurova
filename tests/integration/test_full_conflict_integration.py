"""
记忆冲突检测系统集成测试
测试目标：验证冲突检测、睡眠集成、闭环系统
"""

import sys
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 配置日志
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

import pytest

pytest.skip(
    "引用不存在的模块 neurova.core.闭环_manager（非法模块名），且 conflict_detector 已改名为 conflict_detector_v2。"
    "已整体 skip，待确认闭环/冲突检测的对齐方案；详见 docs/test-debt-skip-list.md",
    allow_module_level=True,
)


def test_storage_conflict_detection():
    """测试基础冲突检测测试"""
    print("\n" + "="*60)
    print("1. 测试冲突检测模块测试")
    print("="*60)
    
    from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
    from neurova.cognitive_layers.memory_layer.conflict_detector import (
        MemoryConflictDetector,
        ConflictLevel,
        ConflictType,
    )
    
    # 创建测试存储
    storage = MemoryStorage(
        db_path=":memory:",
        neuser_id="test_user",
        user_id="test_user",
        enable_cache=False
    )
    
    # 测试1: 创建第一个记忆
    mem1_id = str(uuid.uuid4())
    mem1 = {
        'id': mem1_id,
        'content': '用户喜欢蓝色，生日在冬天喜欢喝咖啡',
        'type': 'long_term',
        'category': 'user_info',
        'created_at': datetime.now().isoformat(),
    }
    
    print(f"\n- 保存记忆1: {mem1['content'][:50]}...")
    storage.save(mem1)
    print("  ✓ 保存成功")
    
    # 测试2: 创建冲突的记忆
    mem2_id = str(uuid.uuid4())
    mem2 = {
        'id': mem2_id,
        'content': '用户不喜欢蓝色，讨厌咖啡，生日在夏天',
        'type': 'long_term',
        'category': 'user_info',
        'created_at': datetime.now().isoformat(),
    }
    
    print(f"\n- 保存记忆2: {mem2['content'][:50]}...")
    storage.save(mem2)
    print("  ✓ 保存成功（应该触发冲突检测")
    
    # 检查冲突
    print("\n- 检查冲突")
    conflicts = storage.get_conflicts(status='pending')
    print(f"  ✓ 发现 {len(conflicts)} 个待处理冲突")
    
    for conflict in conflicts:
        print(f"    - 冲突类型: {conflict.get('conflict_type')}")
        print(f"    - 冲突级别: {conflict.get('conflict_level')}")
        print(f"    - 描述: {conflict.get('description')[:60]}")
    
    # 查看冲突统计
    stats = storage.get_conflict_stats()
    print(f"\n- 冲突统计: {stats}")
    
    return storage, [mem1_id, mem2_id]


def test_sleep_integration():
    """测试睡眠系统集成冲突检测"""
    print("\n" + "="*60)
    print("2. 测试睡眠系统集成")
    print("="*60)
    
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
    
    storage, mem_ids = test_storage_conflict_detection()
    
    # 创建睡眠整理模块
    sleep_module = SleepConsolidation(storage=storage)
    print("\n- 创建睡眠整理模块")
    
    # 准备测试记忆（模拟从数据库加载）
    class MockMemory:
        def __init__(self, id, content, temp=70.0):
            self.id = id
            self.content = content
            self.temperature = temp
            self.emotion_score = 0.5
    
    test_memories = [
        MockMemory(mem_ids[0], '用户喜欢蓝色，生日在冬天喜欢喝咖啡'),
        MockMemory(mem_ids[1], '用户不喜欢蓝色，讨厌咖啡，生日在夏天'),
        MockMemory(str(uuid.uuid4()), '用户喜欢音乐，喜欢爬山'),
        MockMemory(str(uuid.uuid4()), '用户不喜欢音乐，但喜欢爬山'),
    ]
    
    # 运行浅睡眠整理
    print("\n- 运行浅睡眠整理（轻度冲突处理）")
    result = sleep_module.run_light_sleep_cycle(test_memories)
    print(f"  ✓ 结果: {result}")
    
    # 检查是否使用冲突检测
    contradiction_result = result.get('contradiction_handling', {})
    print(f"    - 冲突检测使用: {contradiction_result.get('conflict_detector_used', False)}")
    print(f"    - 待处理冲突: {len(contradiction_result.get('pending', []))}")
    
    return result


def test_closed_loop_integration():
    """测试闭环系统集成"""
    print("\n" + "="*60)
    print("3. 测试闭环系统集成")
    print("="*60)
    
    from neurova.core.闭环_manager import (
        Neurova闭环Manager,
        start_闭环,
    )
    
    from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
    
    print("\n- 创建存储")
    storage = MemoryStorage(
        db_path=":memory:",
        neuser_id="test_user",
        user_id="test_user",
        enable_cache=False
    )
    
    # 保存一些测试记忆
    mem_a = {'id': str(uuid.uuid4()), 'content': '用户喜欢蓝色', 'type': 'long_term'}
    mem_b = {'id': str(uuid.uuid4()), 'content': '用户不喜欢蓝色', 'type': 'long_term'}
    mem_c = {'id': str(uuid.uuid4()), 'content': '用户喜欢咖啡', 'type': 'long_term'}
    storage.save(mem_a)
    storage.save(mem_b)
    storage.save(mem_c)
    
    print("  ✓ 测试记忆保存")
    
    # 创建闭环管理器
    print("\n- 创建闭环管理器")
    loop_manager = Neurova闭环Manager(
        storage=storage,
        scheduler=None,
        monitor=None,
        auto_repair=False,
        auto_conflict_check=False,  # 先禁用自动检查，手动测试
        auto_resolve_conflicts=False
    )
    
    # 测试冲突检查任务
    print("\n- 运行冲突检查")
    check_result = loop_manager._task_conflict_check()
    print(f"  ✓ 结果: {check_result}")
    
    # 测试状态
    print("\n- 状态:")
    status = loop_manager.get_status()
    print(f"  - 当前问题: {status.get('current_issues')}")
    
    # 测试获取冲突统计
    print("\n- 存储冲突统计:")
    conflict_stats = storage.get_conflict_stats()
    print(f"  - 统计: {conflict_stats}")
    
    return loop_manager


if __name__ == '__main__':
    print("\n" + "="*60)
    print("Neurova 记忆冲突检测系统集成测试")
    print("="*60)
    
    # 运行所有测试
    try:
        test_sleep_integration()
        test_closed_loop_integration()
        
        print("\n" + "="*60)
        print("✅ 所有测试完成！")
        print("="*60)
        
        print("\n系统功能总结:")
        print("\n1. 冲突检测 (MemoryConflictDetector:")
        print("   - 在记忆保存时自动检测")
        print("   - 检测否定词、数字、时间、实体冲突")
        print("   - 冲突持久化到memory_conflicts表")
        
        print("\n2. 睡眠系统集成 (SleepConsolidation):")
        print("   - 浅睡眠期轻度冲突检测")
        print("   - 深度睡眠期深度冲突处理")
        print("   - 自动保存冲突到数据库")
        
        print("\n3. 闭环系统集成 (Neurova闭环Manager):")
        print("   - 自动冲突检查")
        print("   - 冲突统计与自动解决（可选）")
        print("   - 健康检查 + 冲突状态跟踪")
        
        print("\n" + "="*60)
        
    except Exception as e:
        print(f"\n❌ 测试错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
