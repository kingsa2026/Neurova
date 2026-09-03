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
from neurova.memory_rw_manager import MemoryReadWriteManager
from neurova.enhanced_context_builder import EnhancedContextBuilder


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


def test_memory_management():
    """测试记忆管理"""
    print("\n" + "="*60)
    print("测试 3: 记忆读写管理")
    print("="*60)
    
    # 初始化记忆管理器
    mem_mgr = MemoryManager(db_path="data/test_memory.db")
    rw_mgr = MemoryReadWriteManager(
        memory_manager=mem_mgr,
        batch_write_interval=5,
        batch_size=10
    )
    
    # 1. 缓冲模式创建记忆
    print("\n--- 步骤1: 缓冲模式创建记忆 ---")
    for i in range(5):
        memory_id = rw_mgr.create_memory(
            content=f"缓冲记忆{i+1}: 用户的偏好设置",
            category="preference",
            is_important=(i < 2),
            buffered=True
        )
        print(f"  创建记忆: {memory_id} (已缓冲)")
    
    print(f"  缓冲区大小: {len(rw_mgr.write_buffer)}")
    
    # 2. 立即模式创建记忆
    print("\n--- 步骤2: 立即模式创建记忆 ---")
    immediate_id = rw_mgr.create_memory(
        content="立即记忆: 重要信息",
        category="important",
        is_important=True,
        buffered=False
    )
    print(f"  创建记忆: {immediate_id} (已写入)")
    
    # 3. 检索记忆
    print("\n--- 步骤3: 检索记忆 ---")
    memories = rw_mgr.recall_memories(query="用户偏好", limit=5)
    print(f"  检索到: {len(memories)} 条记忆")
    for mem in memories[:3]:
        print(f"    - {mem['content'][:30]} (temp={mem['temperature']:.0f})")
    
    # 4. 批量写入
    print("\n--- 步骤4: 批量写入 ---")
    written = rw_mgr.batch_write()
    print(f"  批量写入: {written} 条记忆")
    
    # 5. 统计
    print("\n--- 步骤5: 记忆统计 ---")
    stats = rw_mgr.get_stats()
    print(f"  读取: {stats['reads']}")
    print(f"  写入: {stats['writes']}")
    print(f"  批量写入: {stats['batch_writes']}")
    print(f"  缓冲区: {stats['buffer_size']}")
    
    # 清理
    mem_mgr.close()
    
    print("\n✅ 记忆管理测试完成")


def test_enhanced_builder():
    """测试增强版上下文构建器"""
    print("\n" + "="*60)
    print("测试 4: 增强版上下文构建器集成测试")
    print("="*60)
    
    # 初始化
    mem_mgr = MemoryManager(db_path="data/test_memory_enhanced.db")
    rw_mgr = MemoryReadWriteManager(mem_mgr)
    
    builder = EnhancedContextBuilder(
        cache_config={
            'max_entries': 10,
            'batch_write_interval': 5,
            'persistence_enabled': True,
            'storage_path': "data/test_enhanced_contexts"
        },
        memory_manager=mem_mgr,
        memory_rw_config={'batch_write_interval': 5}
    )
    
    # 1. 创建记忆
    print("\n--- 步骤1: 创建记忆 ---")
    builder.create_memory("用户喜欢喝奶茶", category="preference", is_important=True)
    builder.create_memory("用户住在北京", category="fact", is_crystallized=True)
    print(f"  ✅ 记忆已创建")
    
    # 2. 构建上下文（第1轮）
    print("\n--- 步骤2: 构建上下文 - 第1轮 ---")
    result1 = builder.build_context(
        session_id="test_session_001",
        agent_id="kai",
        system_prompt="你是Kai，一个友好的AI助手",
        user_input="你好，今天天气怎么样？",
        conversation_history=[],
        channel="wechat"
    )
    
    print(f"  上下文消息数: {len(result1['context'])}")
    print(f"  压缩率: {result1['stats']['compression']['compression_ratio']:.0%}")
    
    # 3. 添加消息到会话
    print("\n--- 步骤3: 添加消息到会话 ---")
    builder.add_message_to_session(
        session_id="test_session_001",
        agent_id="kai",
        role="user",
        content="今天天气怎么样？",
        channel="wechat"
    )
    builder.add_message_to_session(
        session_id="test_session_001",
        agent_id="kai",
        role="assistant",
        content="今天北京天气晴朗，温度适宜！",
        channel="wechat"
    )
    print(f"  ✅ 已添加2条消息")
    
    # 4. 构建上下文（第2轮 - 使用缓存）
    print("\n--- 步骤4: 构建上下文 - 第2轮（使用缓存） ---")
    result2 = builder.build_context(
        session_id="test_session_001",
        agent_id="kai",
        system_prompt="你是Kai，一个友好的AI助手",
        user_input="那明天呢？",
        conversation_history=builder.get_session_history("test_session_001", "kai"),
        channel="wechat"
    )
    
    print(f"  上下文消息数: {len(result2['context'])}")
    print(f"  缓存命中率: {result2['stats']['cache']['hit_rate']:.0%}")
    print(f"  缓存大小: {result2['stats']['cache']['cache_size']}")
    
    # 5. 查看缓存摘要
    print("\n--- 步骤5: 缓存摘要 ---")
    cache_summary = builder.get_cache_summary()
    for entry in cache_summary:
        print(f"  会话: {entry['session_id']}, 访问: {entry['access_count']}次, Tokens: {entry['token_count']}")
    
    # 6. 强制刷新
    print("\n--- 步骤6: 强制刷新 ---")
    builder.flush_all()
    print(f"  ✅ 所有缓存和缓冲已刷新")
    
    # 7. 最终统计
    print("\n--- 步骤7: 最终统计 ---")
    stats = builder.get_stats()
    print(f"  缓存: {stats['cache']['hits']}命中/{stats['cache']['misses']}未命中")
    print(f"  会话构建: {stats['sessions'].get('test_session_001', {}).get('build_count', 0)}次")
    
    # 清理
    mem_mgr.close()
    
    print("\n✅ 增强版构建器测试完成")


if __name__ == "__main__":
    try:
        test_context_cache()
        test_context_compression()
        test_memory_management()
        test_enhanced_builder()
        
        print("\n" + "="*60)
        print("🎉 所有测试完成!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
