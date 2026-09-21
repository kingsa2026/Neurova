#!/usr/bin/env python3
"""
上下文缓存、压缩和记忆管理测试

测试场景:
1. 上下文缓存 - 优先读缓存、批量写入
2. 智能压缩 - 会话完整性保护
3. 记忆管理 - 缓冲写入、批量提交
4. 集成测试 - 完整工作流
"""

import sys
import time
from pathlib import Path

# 添加项目根目录
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.insert(0, str(project_root))

from neurova.context_cache import ContextCacheManager
from neurova.context_compressor import SmartContextCompressor, CompressionConfig
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


def test_context_compression():
    """测试智能上下文压缩"""
    print("\n" + "="*60)
    print("测试 2: 智能上下文压缩（保护会话完整性）")
    print("="*60)
    
    # 配置（小预算用于测试）
    config = CompressionConfig(
        max_context_tokens=500,
        system_prompt_budget=100,
        memory_budget=100,
        history_budget=300,
        min_recent_turns=3  # 最少保留3轮
    )
    
    compressor = SmartContextCompressor(config)
    
    # 1. 创建长对话历史（10轮）
    print("\n--- 步骤1: 创建长对话历史 ---")
    history = []
    for i in range(10):
        history.append({
            'role': 'user',
            'content': f'这是第{i+1}轮用户消息，内容比较长，关于某个话题的讨论' * 3
        })
        history.append({
            'role': 'assistant',
            'content': f'这是第{i+1}轮助手回复，详细的回答和解释' * 3
        })
    
    print(f"  总轮次: 10")
    print(f"  总消息: {len(history)}")
    
    # 2. 创建记忆
    memories = [
        {'content': '用户喜欢喝咖啡', 'temperature': 90, 'is_crystallized': True, 'is_important': True},
        {'content': '用户住在北京', 'temperature': 80, 'is_crystallized': False, 'is_important': True},
        {'content': '用户讨厌下雨天', 'temperature': 60, 'is_crystallized': False, 'is_important': False},
        {'content': '用户养了一只猫', 'temperature': 50, 'is_crystallized': False, 'is_important': False},
        {'content': '用户昨天去了电影院', 'temperature': 30, 'is_crystallized': False, 'is_important': False},
    ]
    print(f"  记忆数: {len(memories)}")
    
    # 3. 执行压缩
    print("\n--- 步骤2: 执行智能压缩 ---")
    system_prompt = "你是一个友好的AI助手，名叫Kai"
    user_input = "今天天气怎么样？"
    
    result = compressor.compress_context(
        system_prompt=system_prompt,
        memories=memories,
        conversation_history=history,
        user_input=user_input
    )
    
    # 4. 验证压缩结果
    print("\n--- 步骤3: 验证压缩结果 ---")
    context = result['context']
    stats = result['stats']
    
    print(f"  原始tokens: {stats['original_tokens']}")
    print(f"  压缩后tokens: {stats['compressed_tokens']}")
    print(f"  压缩率: {stats['compression_ratio']:.0%}")
    print(f"  是否压缩: {stats['compressed']}")
    
    # 验证会话完整性
    print("\n--- 步骤4: 验证会话完整性 ---")
    turn_count = 0
    incomplete_turns = 0
    
    i = 0
    while i < len(context):
        msg = context[i]
        if msg.get('role') == 'user':
            # 检查是否有对应的assistant回复
            if i + 1 < len(context) and context[i+1].get('role') == 'assistant':
                turn_count += 1
                i += 2  # 跳过完整的轮次
            elif msg.get('is_summary'):
                print(f"  ✅ 轮次{turn_count+1}: 摘要 (保留了{msg.get('original_turns', '?')}轮)")
                i += 1
            else:
                incomplete_turns += 1
                i += 1
        else:
            i += 1
    
    print(f"  完整轮次: {turn_count}")
    print(f"  不完整轮次: {incomplete_turns}")
    
    if incomplete_turns == 0:
        print(f"  ✅ 会话完整性保护成功！")
    else:
        print(f"  ❌ 存在不完整的会话轮次")
    
    # 5. 显示摘要
    print(f"\n--- 步骤5: 压缩摘要 ---")
    print(f"  {result['summary']}")
    
    print("\n✅ 上下文压缩测试完成")
