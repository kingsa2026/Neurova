#!/usr/bin/env python3
"""
Neurova 优化功能演示脚本

演示以下功能：
1. 定时任务管理
2. 系统监控与告警
3. 向量索引管理（增量同步、异步更新）
4. 记忆存储自动同步
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


def demo_task_scheduler():
    """演示定时任务管理"""
    print("\n" + "="*60)
    print("1. 定时任务管理演示")
    print("="*60)
    
    try:
        from neurova.core.task_scheduler import (
            get_task_scheduler,
            TaskType,
            AlertLevel
        )
    except ImportError as e:
        print(f"⚠️  模块导入失败: {e}")
        print("   提示: 确保 apscheduler 已安装")
        return
    
    scheduler = get_task_scheduler(data_dir="data/demo/scheduler")
    
    # 创建任务
    print("\n📋 创建示例任务...")
    
    # 1. 向量索引同步任务（每天凌晨2点）
    task1 = scheduler.create_task(
        name="Daily Vector Index Sync",
        description="Sync vector index with database",
        task_type=TaskType.CRON,
        target="vector_index_incremental_sync",
        cron_expression="0 2 * * *",  # 每天凌晨2点
        enabled=True,
        max_retries=3
    )
    print(f"✅ 创建任务: {task1.name}")
    
    # 2. 健康检查任务（每小时）
    task2 = scheduler.create_task(
        name="Hourly Health Check",
        description="Check system health status",
        task_type=TaskType.INTERVAL,
        target="system_health_check",
        interval_seconds=3600,  # 每小时
        enabled=True,
        max_retries=2
    )
    print(f"✅ 创建任务: {task2.name}")
    
    # 3. 一次性测试任务（10秒后）
    from datetime import datetime, timedelta
    run_time = (datetime.now() + timedelta(seconds=10)).isoformat()
    task3 = scheduler.create_task(
        name="One-Time Test Task",
        description="Test task for demonstration",
        task_type=TaskType.ONCE,
        once_time=run_time,
        enabled=True
    )
    print(f"✅ 创建任务: {task3.name} (运行时间: {run_time})")
    
    # 显示统计
    stats = scheduler.get_stats()
    print(f"\n📊 任务统计:")
    print(f"   总任务数: {stats['total_tasks']}")
    print(f"   启用任务: {stats['enabled_tasks']}")
    print(f"   调度器可用: {'✅' if stats['has_scheduler'] else '❌'}")
    
    # 列出所有任务
    print(f"\n📜 任务列表:")
    for task in scheduler.list_tasks():
        status_icon = "✅" if task.enabled else "⏸️"
        print(f"   {status_icon} [{task.task_type.value}] {task.name}")
    
    # 暂停演示任务
    scheduler.close()
    print("\n✅ 定时任务演示完成")


def demo_system_monitoring():
    """演示系统监控与告警"""
    print("\n" + "="*60)
    print("2. 系统监控与告警演示")
    print("="*60)
    
    try:
        from neurova.core.monitoring import (
            get_system_monitor,
            setup_default_rules,
            AlertLevel
        )
    except ImportError as e:
        print(f"⚠️  模块导入失败: {e}")
        print("   提示: 确保 psutil 已安装")
        return
    
    monitor = get_system_monitor(data_dir="data/demo/monitoring")
    
    # 设置默认规则
    if len(monitor.rules) == 0:
        print("\n📋 设置默认告警规则...")
        setup_default_rules(monitor)
        print(f"✅ 添加了 {len(monitor.rules)} 条告警规则")
    
    # 收集系统指标
    print("\n📊 收集系统指标...")
    metrics = monitor.collect_metrics()
    
    print(f"\n💻 系统指标:")
    print(f"   CPU 使用率: {metrics.cpu_percent}%")
    print(f"   内存使用率: {metrics.memory_percent}%")
    print(f"   磁盘使用率: {metrics.disk_percent}%")
    print(f"   进程数: {metrics.process_count}")
    print(f"   网络发送: {metrics.network_sent_bytes / 1024:.2f} KB")
    print(f"   网络接收: {metrics.network_recv_bytes / 1024:.2f} KB")
    
    # 评估规则
    print("\n🔍 评估告警规则...")
    monitor.evaluate_rules(metrics)
    
    # 显示统计
    stats = monitor.get_stats()
    print(f"\n📈 监控统计:")
    print(f"   总告警数: {stats['total_alerts']}")
    print(f"   活跃告警: {stats['active_alerts']}")
    print(f"   警告告警: {stats['warning_alerts']}")
    print(f"   错误告警: {stats['error_alerts']}")
    print(f"   规则数量: {stats['total_rules']}")
    
    # 创建测试告警
    print("\n⚠️ 创建测试告警...")
    test_alert = monitor.create_alert(
        level=AlertLevel.WARNING,
        title="Demo Warning",
        message="这是一个演示警告",
        source="demo_script",
        metadata={"demo": True, "timestamp": time.time()}
    )
    print(f"✅ 创建告警: {test_alert.title}")
    
    # 显示活跃告警
    active_alerts = monitor.get_alerts(status=None, limit=5)
    print(f"\n📢 最近告警 ({len(active_alerts)}):")
    for alert in active_alerts[-3:]:
        level_emoji = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.ERROR: "❌",
            AlertLevel.CRITICAL: "🚨"
        }
        emoji = level_emoji.get(alert.level, "")
        print(f"   {emoji} [{alert.level.value}] {alert.title}")
    
    print("\n✅ 系统监控演示完成")


def demo_vector_index_manager():
    """演示向量索引管理"""
    print("\n" + "="*60)
    print("3. 向量索引管理演示")
    print("="*60)
    
    try:
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
    except ImportError as e:
        print(f"⚠️  模块导入失败: {e}")
        return
    
    print("\n📦 初始化记忆存储...")
    storage = MemoryStorage(
        db_path="data/demo/memory.db",
        neuser_id="demo",
        user_id="demo_user",
        enable_async_index=True,
        enable_incremental_sync=True
    )
    
    # 添加测试记忆
    print("\n📝 添加测试记忆...")
    test_memories = [
        {
            "content": "Neurova 是一个智能代理框架",
            "memory_type": "knowledge",
            "importance": 0.8
        },
        {
            "content": "记忆系统支持增量同步和异步更新",
            "memory_type": "knowledge",
            "importance": 0.7
        },
        {
            "content": "LongMemEval 基准测试包含24个测试用例",
            "memory_type": "knowledge",
            "importance": 0.6
        }
    ]
    
    for i, mem_data in enumerate(test_memories):
        memory = storage.save(**mem_data)
        print(f"   ✅ 添加记忆 {i+1}: {memory.id}")
    
    # 等待索引更新
    if storage._index_manager:
        print(f"\n⏳ 等待索引更新...")
        storage.wait_for_index_completion(timeout=2)
        
        index_stats = storage.get_index_manager_state()
        if index_stats:
            print(f"\n📊 索引状态:")
            print(f"   待处理操作: {index_stats.get('pending_operations', 0)}")
            print(f"   同步状态: {index_stats.get('sync_status', 'unknown')}")
    
    # 搜索测试
    print("\n🔍 测试向量搜索...")
    search_results = storage.vector_search.search("Neurova 记忆系统", top_k=3)
    print(f"   找到 {len(search_results)} 个相关结果:")
    for result in search_results:
        score = result.get('score', 0)
        text_preview = result.get('text', '')[:50]
        print(f"      [{score:.3f}] {text_preview}...")
    
    # 更新记忆
    print("\n✏️ 更新记忆...")
    if storage.list_memories():
        mem_id = storage.list_memories()[0].id
        storage.update_memory(
            memory_id=mem_id,
            content="Neurova 是一个强大的智能代理框架，支持记忆管理"
        )
        print(f"   ✅ 更新记忆: {mem_id}")
    
    # 删除记忆
    print("\n🗑️ 删除一个记忆...")
    if storage.list_memories():
        mem_to_delete = storage.list_memories()[0]
        storage.delete(mem_to_delete.id)
        print(f"   ✅ 删除记忆: {mem_to_delete.id}")
    
    # 完整性检查
    print("\n🔍 索引完整性检查...")
    check_result = storage.check_vector_index_integrity()
    print(f"   数据库记忆数: {check_result['db_count']}")
    print(f"   索引向量数: {check_result['index_count']}")
    print(f"   检查通过: {'✅' if check_result['ok'] else '⚠️'}")
    
    # 显示统计
    mem_list = storage.list_memories()
    print(f"\n📈 总体统计:")
    print(f"   记忆总数: {len(mem_list)}")
    
    storage.close()
    print("\n✅ 向量索引管理演示完成")


def main():
    """主函数"""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║           Neurova 优化功能演示脚本                             ║
║                                                               ║
║  功能列表:                                                    ║
║    1. 定时任务管理 (TaskScheduler)                            ║
║    2. 系统监控与告警 (SystemMonitor)                          ║
║    3. 向量索引管理 (增量同步、异步更新)                       ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # 创建数据目录
    Path("data/demo").mkdir(parents=True, exist_ok=True)
    
    # 演示各功能
    demo_task_scheduler()
    demo_system_monitoring()
    demo_vector_index_manager()
    
    # 总结
    print("\n" + "="*60)
    print("🎉 所有演示完成！")
    print("="*60)
    print("\n📊 生成的文件位置:")
    print("   定时任务数据: data/demo/scheduler/")
    print("   监控数据: data/demo/monitoring/")
    print("   记忆数据库: data/demo/memory.db")
    print("   向量索引: data/demo/vector_index*.pkl")
    print("\n💡 使用说明:")
    print("   1. 在实际应用中，通过 get_task_scheduler() 获取调度器")
    print("   2. 通过 get_system_monitor() 获取监控器")
    print("   3. 定期调用 sync_incremental() 进行增量同步")
    print("   4. 定期调用 check_vector_index_integrity() 进行完整性检查")
    print("\n" + "="*60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  演示已停止")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ 演示失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
