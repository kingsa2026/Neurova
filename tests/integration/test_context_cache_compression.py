#!/usr/bin/env python3
"""
上下文缓存与记忆管理集成测试

来源沿革（B6-10 批次 C）：本文件原含 `test_context_compression()`，锁定已退役的
`SmartContextCompressor` / `CompressionConfig`（装配即弃的第二份压缩实现，
真通路见 `tests/unit/context/test_envelope.py`），随之退场。
存活的缓存面契约保留在本文件。

测试场景:
1. 上下文缓存 - 优先读缓存、批量写入
2. 记忆管理 - 缓冲写入、批量提交
3. 集成测试 - 完整工作流
"""

import sys
import time
from pathlib import Path

# 添加项目根目录
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.insert(0, str(project_root))

from neurova.context_cache import ContextCacheManager
from neurova.memory import MemoryManager


def test_context_cache():
    """测试上下文缓存管理"""
    print("\n" + "="*60)
    print("测试 1: 上下文缓存管理")
    print("="*60)
    
    # 初始化缓存管理器（小容量用于测试）
    cache = ContextCacheManager(
        max_entries=5,
        max_memory_mb=10,
        batch_write_interval=5,
        persistence_enabled=True,
        storage_path="data/test_contexts"
    )
    
    # 1. 写入多个上下文
    print("\n--- 步骤1: 写入上下文到缓存 ---")
    for i in range(3):
        session_id = f"session_{i:03d}"
        agent_id = "kai"
        
        context_data = {
            'conversation_history': [
                {'role': 'user', 'content': f'测试消息{i}-1'},
                {'role': 'assistant', 'content': f'回复消息{i}-1'},
                {'role': 'user', 'content': f'测试消息{i}-2'},
            ],
            'metadata': {'channel': 'wechat'},
        }
        
        success = cache.put_context(
            session_id=session_id,
            agent_id=agent_id,
            context_data=context_data,
            immediate_write=False
        )
        print(f"  ✅ 写入缓存: {session_id} (dirty={cache.cache[f'{agent_id}:{session_id}'].is_dirty})")
    
    # 2. 从缓存读取（应该命中）
    print("\n--- 步骤2: 从缓存读取 ---")
    for i in range(3):
        session_id = f"session_{i:03d}"
        agent_id = "kai"
        
        context_data = cache.get_context_with_agent(session_id, agent_id)
        if context_data:
            history = context_data.get('conversation_history', [])
            print(f"  ✅ 缓存命中: {session_id} (历史{len(history)}条)")
        else:
            print(f"  ❌ 缓存未命中: {session_id}")
    
    # 3. 触发缓存淘汰（超过max_entries）
    print("\n--- 步骤3: 触发缓存淘汰 ---")
    for i in range(3, 7):  # 再写入4个，超过max_entries=5
        session_id = f"session_{i:03d}"
        agent_id = "kai"
        
        context_data = {
            'conversation_history': [
                {'role': 'user', 'content': f'新消息{i}'},
            ],
        }
        
        cache.put_context(
            session_id=session_id,
            agent_id=agent_id,
            context_data=context_data,
            immediate_write=False
        )
        print(f"  写入: {session_id} (缓存大小: {len(cache.cache)})")
    
    # 4. 批量写入
    print("\n--- 步骤4: 批量写入 ---")
    written = cache.batch_write()
    print(f"  ✅ 批量写入: {written} 个上下文")
    
    # 5. 查看统计
    print("\n--- 步骤5: 缓存统计 ---")
    stats = cache.get_stats()
    print(f"  缓存大小: {stats['cache_size']}/{stats['max_entries']}")
    print(f"  命中率: {stats['hit_rate']:.0%}")
    print(f"  命中: {stats['hits']}, 未命中: {stats['misses']}")
    print(f"  写入: {stats['writes']}, 淘汰: {stats['evictions']}")
    
    # 6. 强制刷新
    print("\n--- 步骤6: 强制刷新 ---")
    flushed = cache.flush_all()
    print(f"  ✅ 刷新: {flushed} 个上下文")
    
    print("\n✅ 上下文缓存测试完成")
