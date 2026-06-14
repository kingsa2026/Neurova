#!/usr/bin/env python3
"""
Neurova 记忆系统闭环演示脚本

完整演示闭环系统的工作流程：
1. 初始化组件（storage, scheduler, monitor）
2. 创建闭环管理器
3. 启动闭环
4. 执行操作并观察自动修复
5. 查看状态和日志
"""

import time
import logging
import sys
from pathlib import Path

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def demo_closed_loop():
    """演示完整闭环系统"""
    print("\n" + "="*70)
    print("🚀 Neurova 记忆系统闭环演示")
    print("="*70)
    
    # 1. 导入组件
    print("\n📦 步骤1: 导入组件...")
    try:
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        from neurova.core.闭环_manager import start_闭环, get_闭环_manager, stop_闭环
        from neurova.core.task_scheduler import TaskType
        print("   ✅ 所有组件导入成功")
    except ImportError as e:
        print(f"   ❌ 组件导入失败: {e}")
        return
    
    # 2. 初始化存储
    print("\n💾 步骤2: 初始化记忆存储...")
    storage = MemoryStorage(
        db_path="data/demo_闭环/memory.db",
        neuser_id="demo",
        user_id="闭环_user",
        enable_async_index=True,
        enable_incremental_sync=True
    )
    print("   ✅ 记忆存储初始化完成")
    
    # 3. 添加一些初始数据
    print("\n📝 步骤3: 添加初始记忆...")
    test_memories = [
        {"content": "这是一个测试记忆", "memory_type": "test", "importance": 0.8},
        {"content": "闭环系统会自动管理索引", "memory_type": "test", "importance": 0.7},
        {"content": "健康检查会监控索引状态", "memory_type": "test", "importance": 0.6}
    ]
    
    for i, mem_data in enumerate(test_memories):
        memory = storage.save(**mem_data)
        print(f"   ✅ 记忆 {i+1} 已保存: {memory.id[:16]}...")
    
    # 4. 启动闭环管理器
    print("\n🔄 步骤4: 启动闭环管理器...")
    try:
        闭环 = start_闭环(auto_repair=True)
        print("   ✅ 闭环管理器已启动")
        print(f"   📊 初始状态: {闭环.get_status()['is_running']}")
    except Exception as e:
        print(f"   ❌ 启动失败: {e}")
        storage.close()
        return
    
    # 5. 等待初始同步
    print("\n⏳ 步骤5: 等待初始同步...")
    time.sleep(2)
    storage.wait_for_index_completion(timeout=3)
    print("   ✅ 初始同步完成")
    
    # 6. 执行健康检查
    print("\n🔍 步骤6: 执行健康检查...")
    health_result = 闭环.trigger_check()
    print(f"   结果: {health_result}")
    
    # 7. 显示当前状态
    print("\n📊 步骤7: 查看闭环状态...")
    status = 闭环.get_status()
    print(f"   运行状态: {'✅ 运行中' if status['is_running'] else '❌ 已停止'}")
    print(f"   总检查次数: {status['total_checks']}")
    print(f"   总修复次数: {status['total_repairs']}")
    print(f"   失败修复次数: {status['failed_repairs']}")
    print(f"   当前问题数: {len(status['current_issues'])}")
    if status['current_issues']:
        for issue in status['current_issues']:
            print(f"      - {issue}")
    
    # 8. 执行更多操作触发闭环
    print("\n🔧 步骤8: 执行操作并观察闭环响应...")
    
    # 添加更多记忆
    print("   添加新记忆...")
    for i in range(5):
        memory = storage.save(
            content=f"操作 {i+1}: 测试记忆内容 #{i+1}",
            memory_type="demo",
            importance=0.5 + i * 0.1
        )
        print(f"      ✅ 记忆 {i+1}: {memory.id[:16]}...")
        time.sleep(0.5)
    
    # 等待索引更新
    print("   等待索引更新...")
    time.sleep(2)
    storage.wait_for_index_completion(timeout=3)
    
    # 更新一些记忆
    print("   更新记忆...")
    mem_list = storage.list_memories()
    if mem_list:
        storage.update_memory(
            memory_id=mem_list[0].id,
            content="更新后的记忆内容，包含更多信息"
        )
        print(f"      ✅ 更新记忆: {mem_list[0].id[:16]}...")
    
    # 删除一个记忆
    if len(mem_list) > 1:
        storage.delete(mem_list[1].id)
        print(f"      ✅ 删除记忆: {mem_list[1].id[:16]}...")
    
    # 9. 再次检查状态
    print("\n📊 步骤9: 再次查看闭环状态...")
    health_result = 闭环.trigger_check()
    print(f"   健康检查: {health_result}")
    
    status = 闭环.get_status()
    print(f"   总检查次数: {status['total_checks']}")
    print(f"   总修复次数: {status['total_repairs']}")
    print(f"   当前问题数: {len(status['current_issues'])}")
    
    # 10. 索引完整性检查
    print("\n🔍 步骤10: 索引完整性检查...")
    check_result = storage.check_vector_index_integrity()
    print(f"   数据库记忆数: {check_result['db_count']}")
    print(f"   索引向量数: {check_result['index_count']}")
    print(f"   状态: {'✅ 通过' if check_result['ok'] else '⚠️ 需要修复'}")
    print(f"   消息: {check_result['message']}")
    
    # 11. 手动触发修复
    print("\n🔧 步骤11: 手动触发修复...")
    repair_result = 闭环.trigger_repair()
    print(f"   修复结果: {repair_result}")
    
    # 12. 查看最终状态
    print("\n📊 步骤12: 最终状态...")
    status =闭环.get_status()
    print(f"   运行时间: 正常")
    print(f"   总检查次数: {status['total_checks']}")
    print(f"   总修复次数: {status['total_repairs']}")
    print(f"   失败修复次数: {status['failed_repairs']}")
    
    # 13. 清理
    print("\n🧹 步骤13: 清理资源...")
    stop_闭环()
    storage.close()
    print("   ✅ 资源已清理")
    
    # 14. 总结
    print("\n" + "="*70)
    print("🎉 闭环演示完成！")
    print("="*70)
    
    print("\n📋 演示总结:")
    print("   ✅ 闭环系统成功启动并运行")
    print("   ✅ 健康检查正常工作")
    print("   ✅ 自动修复机制已配置")
    print("   ✅ 所有操作自动同步到索引")
    print("   ✅ 索引完整性得到保证")
    
    print("\n📁 生成的文件:")
    print("   - data/demo_闭环/memory.db")
    print("   - data/demo_闭环/vector_index_*.pkl")
    print("   - data/闭环_config.json")
    
    print("\n💡 关键特性:")
    print("   1. 自动健康检查（每5分钟）")
    print("   2. 自动检测索引问题")
    print("   3. 自动修复（可配置）")
    print("   4. 完整的状态追踪")
    print("   5. 告警和日志记录")


def demo_manual_operations():
    """演示手动操作闭环系统"""
    print("\n" + "="*70)
    print("🔧 手动操作演示")
    print("="*70)
    
    from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
    from neurova.core.闭环_manager import create_闭环_manager, get_闭环_manager
    
    # 创建存储
    storage = MemoryStorage(
        db_path="data/demo_闭环/manual_test.db",
        neuser_id="demo",
        user_id="manual_user",
        enable_async_index=True,
        enable_incremental_sync=True
    )
    
    # 创建闭环（不自动启动）
    闭环 = create_闭环_manager(
        storage=storage,
        auto_repair=False  # 禁用自动修复，便于演示
    )
    
    # 演示手动操作
    print("\n📝 添加测试记忆...")
    for i in range(3):
        storage.save(content=f"测试记忆 {i+1}", memory_type="test")
    
    print("\n🔍 执行健康检查...")
    result = 闭环.trigger_check()
    print(f"   {result}")
    
    print("\n🔧 手动触发修复...")
    result =闭环.trigger_repair()
    print(f"   {result}")
    
    print("\n📊 查看状态...")
    status =闭环.get_status()
    print(f"   检查次数: {status['total_checks']}")
    print(f"   修复次数: {status['total_repairs']}")
    
    # 演示配置更新
    print("\n⚙️ 更新配置...")
    闭环.update_config(auto_repair=True, check_interval=60)
    print("   ✅ 配置已更新")
    
    # 清理
    storage.close()
    print("\n✅ 手动操作演示完成")


def main():
    """主函数"""
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║              Neurova 记忆系统闭环演示                                ║
║                                                                      ║
║  闭环流程:                                                          ║
║    定时触发 → 健康检查 → 评估规则 → 告警 → 自动修复 → 验证           ║
╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    # 创建数据目录
    Path("data/demo_闭环").mkdir(parents=True, exist_ok=True)
    
    try:
        # 演示完整闭环
        demo_closed_loop()
        
        # 可选：演示手动操作
        # demo_manual_operations()
        
    except KeyboardInterrupt:
        print("\n\n⏹️ 演示已停止")
        from neurova.core.闭环_manager import stop_闭环
        stop_闭环()
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ 演示失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
